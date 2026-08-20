# ADR 0022: Admisión acotada y plomería del proceso dedicado

## Estado

Aceptado

## Contexto

ADR 0012 fija el mecanismo de este ítem del backlog (#8): sin `ProcessPoolExecutor` ni pool de
ningún tipo, un `multiprocessing.Process` dedicado por ejecución, admisión no bloqueante con un
semáforo acotado, y rechazo inmediato con 503 en vez de encolar. Ese mecanismo no se reabre acá.

Lo que ADR 0012 deja sin resolver son cinco decisiones que este diseño (`design.md` del cambio
`admision-acotada-y-proceso-dedicado`) tuvo que tomar para implementar ese mecanismo, una de las
cuales es una **desviación de la propia tabla de ADR 0012**. Un lector que en el futuro compare el
código contra ADR 0012 necesita encontrar, en un solo lugar, por qué esa fila no se implementó como
está escrita y quién es dueño del reemplazo. Las otras cuatro son decisiones de plomería que, sin
registro, un lector tendría que reconstruir por arqueología del código.

Numeración verificada contra el contenido de `adrs/` en disco: `0011` a `0021` existen (once
archivos). `openspec/config.yaml:8` todavía dice "0011-0015 exist" y está desactualizado -- la V7 del
ítem #7 ya lo había registrado, y desde entonces se desactualizó un número más.

## Decisión

### 1. El slot de admisión vive durante toda la petición autenticada, y tiene un único sitio de liberación

El semáforo se adquiere en `AdmisionDeBorde`, la middleware ASGI montada como segunda entrada de la
`Mount("/interno", ...)` existente (auth primero, admisión segunda -- el orden de la lista determina
quién envuelve a quién). La adquisición y la liberación viven en el mismo `with admitir():` alrededor
de `await self.app(...)`, con un único `try/finally` que es el **único** `release()` de todo el
repositorio.

La alternativa obvia -- liberar dentro del `finally` del pipeline de 9 pasos del ítem #10 -- se
descartó porque no cubre el caso decisivo: `RequestValidationError` la levanta FastAPI **antes** de
que el cuerpo de la ruta corra, así que ese `finally` nunca se ejecuta y el slot queda filtrado en
cada 422. Adquirir y liberar alrededor del hijo solamente tampoco sirve: la admisión pasaría a ocurrir
**después** de leer el cuerpo, violando tanto la redacción de ADR 0012 ("antes de leer el cuerpo")
como el criterio de "cero bytes de cuerpo leídos en saturación".

El costo, nombrado en vez de descubierto después: un slot queda ocupado durante el parseo multipart y
la copia acotada, no solo durante el hijo. Una subida lenta consume capacidad sin llegar a generar un
proceso. Es sobreaproximación deliberada -- nunca menos concurrencia real que `EJECUCIONES_MAX`,
nunca más -- y la exposición queda acotada a llamadores autenticados porque admisión corre después del
chequeo de token. `TIMEOUT_EJECUCION` no acota este costo; solo lo acota el corte de 2 minutos del
portal.

### 2. La fila de "excepción de módulo" de ADR 0012 no se implementa como está escrita

ADR 0012 dice que cuando el módulo levanta una excepción, la respuesta es un "error tipificado de
contenido". Eso no es implementable hoy: `ContextoContenido.motivo` es un `Literal["columna_faltante",
"cero_filas"]` cerrado, sin espacio para "el módulo se cayó", y `ContextoContenido` no tiene un campo
para una traza. Honrar esa celda tal cual exigiría ampliar un literal cerrado -- exactamente la
presión que ADR 0014 existe para resistir.

En su lugar, este cambio levanta `FalloDelModulo` (`clase: str`, `mensaje: str`, `traza: str`), una
excepción que nunca es `TipoError`. La traducción HTTP final de `FalloDelModulo` queda a cargo del
ítem #10, que ya es dueño del vocabulario de brecha de sincronización (H-05). La traza es material de
log operativo (ítem #14), nunca cuerpo de respuesta.

### 3. La bandera `matado`, nunca el número de `exitcode`, discrimina nuestra propia terminación

`clasificar_desenlace(*, exitcode, matado, hubo_mensaje) -> Desenlace` es una función pura donde
`matado` gana sobre cualquier lectura del `exitcode`: si el padre lo mató, es `MATADO`, sin importar
qué número haya quedado. En caso contrario, un mensaje bien formado más `exitcode == 0` es `NORMAL`;
todo lo demás es `ANOMALO`.

**Evidencia que obliga a esto**: en Windows, `multiprocessing.popen_spawn_win32.Popen.terminate()`
llama a `TerminateProcess` con el código `TERMINATE = 0x10000`, y el propio `multiprocessing` lo
**normaliza de vuelta** antes de exponerlo (`popen_spawn_win32.py`, líneas 17 y 110-114/121-129):

```python
TERMINATE = 0x10000
...
if code == TERMINATE:
    code = -signal.SIGTERM
```

Es decir, `Process.exitcode` después de nuestro propio `kill()` en Windows es `-15` -- el mismo valor
que produciría un `SIGTERM` externo en POSIX, y en POSIX nuestro propio `SIGKILL` produce `-9`, el
mismo valor que dejaría el OOM killer del sistema. En ambas plataformas, el número de `exitcode` es
**ambiguo entre "lo matamos nosotros" y "lo mató otra cosa"**, y las dos codificaciones de plataforma
colisionan entre sí en vez de separarse. El padre es el único código que puede llamar a `kill()`, así
que ya conoce la respuesta y no debe intentar reconstruirla a partir de un número que la pierde.

### 4. `daemon=True` y su restricción real sobre procesadores futuros

TECH-DESIGN exige que "el proceso hijo muere de verdad, no queda huérfano consumiendo CPU" si el
padre se cae. Un proceso daemon garantiza eso: no puede sobrevivir a un padre caído. El costo, real y
registrado acá para que no lo descubra un ítem futuro por sorpresa: **un proceso daemon no puede crear
sus propios hijos**. Cualquier procesador que los ítems #12 o #16 agreguen queda constreñido a no usar
`joblib` ni `n_jobs>1` (ni ningún otro mecanismo que dependa de `multiprocessing` anidado). Es
consistente con "estrictamente síncrono" de ADR 0006.

### 5. `ErrorTipificado` gana una garantía de pickling

`ErrorTipificado.__reduce__` devuelve `(_reconstruir, (type(self),), dict(self.__dict__))`, donde
`_reconstruir` es una función de nivel de módulo que evita el `__init__` solo-por-palabra-clave de
cada subclase con `cls.__new__(cls)`. Sin esto, `pickle.loads(pickle.dumps(error))` levanta
`TypeError` porque `self.args == ()` en las cinco subclases (cada una llama a
`super().__init__()` sin argumentos), y el `__reduce__` heredado de `Exception` intenta reconstruir
llamando a `cls()`. Esto toca el territorio de ADR 0014 sin reabrir el enum -- la misma distinción que
ADR 0021 ya tuvo que registrar una vez para la unión de contextos.

## Alternativas consideradas

- **Liberar el slot en el `finally` del pipeline del ítem #10, en vez de en la middleware.** Rechazada
  sobre evidencia: todo 422 por `RequestValidationError` deja ese `finally` sin ejecutar y filtra el
  slot permanentemente.
- **Adquirir el slot alrededor del hijo únicamente.** Rechazada: viola "admisión antes de leer el
  cuerpo" y el criterio de cero bytes/cero temporales en saturación.
- **Un `asyncio.Semaphore` en vez de `threading.BoundedSemaphore`.** Rechazada: ADR 0012 nombra la
  variante acotada explícitamente, y el contador debe ser observable también desde código de
  threadpool.
- **Forzar la fila de "excepción de módulo" de ADR 0012 ampliando `ContextoContenido.motivo`.**
  Rechazada: reabriría exactamente la presión que ADR 0014 existe para resistir sobre un literal
  cerrado.
- **Leer el `exitcode` crudo para distinguir nuestra propia terminación de una externa.** Rechazada
  sobre evidencia (V4): las codificaciones de Windows y POSIX colisionan entre sí, así que el número
  por sí solo no alcanza.
- **Enviar `(tipo, contexto)` por el `Pipe` y reconstruir el error a mano en `ejecucion.py`.**
  Rechazada: exige una tabla de mapeo por forma de contexto que un módulo de plomería no tiene por qué
  conocer, y que debería actualizarse cada vez que se agregue una forma (como ya pasó con
  `ContextoTamanoTotal`).
- **Un séptimo/sexto valor de `TipoError` para saturación, timeout o muerte del hijo.** Rechazada:
  ADR 0014 cierra el enum en cinco valores; ninguno de estos tres es un error tipificado.

## Consecuencias

- **Un slot de admisión puede quedar ocupado sin que llegue a generarse ningún proceso** (subida
  lenta, petición que termina en 422 antes del hijo). Es sobreaproximación deliberada, acotada a
  llamadores autenticados y al corte de 2 minutos del portal.
- **La traducción HTTP de `FalloDelModulo` queda pendiente del ítem #10.** Este cambio solo garantiza
  que la excepción y su traza lleguen intactas al padre; no decide el código de estado ni el cuerpo de
  respuesta.
- **`joblib`/`n_jobs>1` quedan fuera de alcance para cualquier procesador futuro** mientras
  `daemon=True` siga vigente (ítems #12/#16 heredan la restricción, no la descubren solos).
- **El clasificador de desenlace es puro y se prueba localmente con las convenciones POSIX como datos**,
  aunque esta caja de desarrollo/CI es Windows-only: lo que no puede ejercitarse localmente es la
  *producción* de esos códigos, no su *manejo*.
- **La garantía de pickling de `ErrorTipificado` es general**, no específica de este ítem: cualquier
  código futuro que necesite serializar un error tipificado (no solo el `Pipe` del proceso hijo) hereda
  la garantía sin cambios adicionales.
- **Riesgo abierto: el proceso hijo hereda `os.environ` completo**, incluido `TOKEN_SERVICIO` y las
  credenciales de base de datos que el ítem #5 pueda incorporar más adelante. `multiprocessing.Process`
  no expone un parámetro `env` con el que acotar el entorno del hijo, así que `spawn` aísla los
  descriptores del padre pero no sus variables de entorno. Hoy el impacto está acotado porque el hijo
  ejecuta código propio del repositorio y no toca la base (ADR 0013), pero el día que un procesador
  concreto ejecute o importe algo de terceros, ese código lee el token del servicio sin pedir permiso.
  Queda registrado sin mitigación y sin test: inventar uno daría la impresión de que el riesgo está
  cubierto. La mitigación real —lanzar el hijo con un entorno saneado— es trabajo de otro ítem.
