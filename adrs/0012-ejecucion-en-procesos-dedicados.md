# ADR 0012: Ejecución de los módulos en procesos dedicados, con admisión acotada

## Estado

Aceptado — **reemplaza el mecanismo de la versión original de este ADR** (ver "Revisión del
mecanismo"). El objetivo heredado del ADR 0001 no cambia; lo que cambia es la forma de cumplirlo,
porque la original no lo cumplía.

### Revisión del mecanismo

La versión original decidía un `ProcessPoolExecutor(max_workers=N, max_tasks_per_child=1)`. Una
revisión adversarial del diseño encontró tres defectos que invalidan **el mecanismo**, no el
objetivo:

1. **El pool no aísla la muerte del hijo.** Cuando un proceso hijo termina de forma no limpia — el
   caso del OOM killer, que es exactamente el que este ADR venía a resolver — `ProcessPoolExecutor`
   entra en estado *broken*: todas las tareas pendientes y en vuelo fallan con `BrokenProcessPool`,
   y todo `submit` posterior levanta la misma excepción. El executor no se recupera solo. Un archivo
   anómalo no mataba a un hijo aislado: mataba a **todas las ejecuciones concurrentes** y dejaba al
   worker de API sirviendo errores hasta un reinicio. Eso contradice el objetivo textual del
   ADR 0001 — "no tumbe todo el servicio ni afecte a otras ejecuciones en curso" — que era el motivo
   por el que se había elegido el pool.
2. **Un pool es una cola.** Con los cupos ocupados, las peticiones se encolaban sin tope. El portal
   corta a los 2 minutos (ítem #10), pero el trabajo encolado se ejecutaba igual después: quemaba
   CPU y RAM para una respuesta que ya nadie iba a leer, y ocupaba el cupo de una petición que sí
   tenía cliente esperando.
3. **La concurrencia real no era `max_workers`.** El diagrama original ponía un pool de N dentro de
   cada uno de los N workers de Uvicorn — hasta N×N procesos con pandas cargado — contra un
   presupuesto de memoria que se validaba por archivo y nunca se agregaba entre ejecuciones.

Lo que **no** cambia: el módulo de negocio corre en otro proceso, cruzan rutas y no bytes, se
arranca un proceso por ejecución, el pipeline sigue siendo el dueño del ciclo, y los procesos hijo
nunca tocan la base de datos.

## Contexto

El ADR 0001 fija la política de concurrencia y memoria del servicio y no la deja abierta: exige un
**número fijo y limitado de workers**, un **límite estricto de RAM por contenedor/instancia**, y
establece el objetivo textual de que un archivo anómalo, en el peor caso, **mate a un worker
concreto (aislado y reiniciable) y devuelva un error controlado**, pero **no tumbe todo el
servicio** ni afecte a otras ejecuciones en curso.

Cinco hechos condicionan el mecanismo:

1. **FastAPI ejecuta los handlers síncronos en un threadpool de 40 hilos por defecto.** Sin acotarlo,
   un único proceso acepta decenas de ejecuciones de pandas en paralelo y agota la memoria. Cualquier
   opción elegida obliga a capar esa concurrencia con un número explícito.
2. **Gunicorn es POSIX-only.** El entorno corporativo de Lima Expresa es Microsoft (Windows Server,
   Entra ID, SQL Server) y el ítem #0 aún no define si el despliegue es contenedor Linux o servicio
   Windows nativo. Una decisión que dependa de Gunicorn ata el diseño a una plataforma que todavía
   no está confirmada.
3. **Los archivos ya viven en disco temporal** por decisión del ADR 0006 (para aliviar la RAM). Eso
   abarata drásticamente delegar el trabajo a otro proceso: se pasa una **ruta**, no los bytes.
4. **El aislamiento tiene que sobrevivir a una terminación abrupta**, no solo a una excepción. El
   modo de fallo que motiva todo esto es el proceso muerto desde afuera; un mecanismo cuyo
   comportamiento ante esa muerte sea "estado compartido inconsistente" no sirve, por más limpia que
   sea su API.
5. **El método de arranque de procesos difiere por plataforma y por versión de Python.** En Windows
   es `spawn`; en Linux fue `fork` durante años y cambió con las versiones recientes. Con `fork`, el
   hijo hereda los descriptores del padre — entre ellos el pool de conexiones `pyodbc` — y su
   recolección de basura o su salida pueden cerrar sockets que el padre sigue usando, aunque el hijo
   nunca consulte la base. Dejar el método al default convierte "idéntico en Linux y en Windows" en
   una afirmación falsa.

El procesamiento es CPU-bound (pandas, openpyxl) y estrictamente síncrono (ADR 0006).

## Decisión

**No hay pool.** La capa web permanece liviana y cada ejecución del módulo de negocio corre en un
**proceso dedicado**, creado y destruido dentro de la petición, detrás de un **semáforo de admisión
que rechaza en vez de encolar**:

```
Uvicorn (1 worker de API — liviano, sin trabajo pesado)
  └─ ruta cáscara -> pipeline
       ├─ semáforo de admisión (EJECUCIONES_MAX)
       │     └─ sin cupo libre -> 503 inmediato, sin encolar y sin leer el cuerpo
       └─ multiprocessing.Process dedicado (spawn) -> modulo.procesar(rutas_temporales)
             join(TIMEOUT_EJECUCION) -> kill() si no terminó
```

### `spawn` explícito y forzado

En el arranque de `main.py`, antes de crear cualquier proceso o conexión:

```python
multiprocessing.set_start_method("spawn", force=True)
```

No es una preferencia de plataforma: es lo que hace verdadera la afirmación de que el diseño se
comporta igual en Linux y en Windows. Con `spawn` el hijo arranca con un intérprete limpio y **no
hereda descriptores del padre**, así que la regla del ADR 0013 — los hijos no tocan la base — pasa a
estar respaldada por el mecanismo y no solo por la disciplina de quien escribe el módulo.

### Un proceso por ejecución, sin estado compartido

Cada ejecución crea su propio `Process`, le pasa las rutas de los temporales y lo espera. Al
terminar, el proceso muere y no queda nada compartido con la ejecución siguiente. **El aislamiento
deja de ser una propiedad del comportamiento de una librería y pasa a ser una propiedad de la
estructura: no hay pool que pueda quedar roto porque no hay pool.** Un hijo que muere se lleva su
propia ejecución y nada más.

El resultado vuelve por un `Pipe`: rutas de los archivos de salida, o el error tipificado, o la
excepción del módulo con su traza. **Nunca bytes de archivo.**

### Admisión acotada: 503 en vez de cola

- Un `threading.BoundedSemaphore(EJECUCIONES_MAX)` se adquiere con `acquire(blocking=False)` **al
  entrar a la ruta, antes de leer el cuerpo de la petición**.
- Sin cupo libre → **503 inmediato**. No se encola, no se espera, no se lee el archivo, no se
  escribe un temporal.
- El cupo se libera siempre en el `finally`, incluidos el camino de error y el de timeout.

Rechazar rápido es deliberado: aceptar una petición que va a empezar a ejecutarse después de que el
portal ya cortó a los 2 minutos es gastar RAM y CPU para nadie, y le roba el cupo a una petición
con cliente esperando.

### Un solo worker de API

`EJECUCIONES_MAX` es el **único** parámetro de concurrencia del servicio. Para que acote la máquina
y no solo un proceso, Uvicorn corre con **un worker de API**: la capa web solo recibe archivos,
valida y coordina, mientras todo el trabajo pesado ocurre en los procesos hijo, que sí son varios.

Si el despliegue del ítem #0 exigiera varios workers de API, el presupuesto se divide explícitamente
entre ellos (`EJECUCIONES_MAX` por worker = total ÷ workers) y queda documentado en la configuración
del despliegue. Lo que no puede volver a pasar es que la concurrencia real sea el producto de dos
números que nadie multiplicó.

### Timeout duro con terminación real

- El padre espera con `join(TIMEOUT_EJECUCION)`; si el hijo no terminó, lo mata con `kill()` y
  devuelve un error controlado.
- `TIMEOUT_EJECUCION` es **estrictamente menor** que el corte de 2 minutos del portal, para que sea
  este servicio el que decide y responde, y no el portal el que recibe una conexión cortada.
- Sin este punto la admisión acotada no funciona: un módulo colgado retendría su cupo para siempre
  y la capacidad efectiva del servicio iría cayendo a cero rechazo tras rechazo.

### Traducción de fallos

| Qué pasó | Cómo termina la petición |
|---|---|
| El módulo devuelve normalmente | Salida del pipeline (archivo suelto o ZIP) |
| El módulo levanta una excepción | Excepción y traza cruzan por el `Pipe`; error tipificado de contenido |
| El hijo muere desde afuera (OOM, `exitcode` anómalo) | Error controlado; la respuesta llega, el worker de API no muere |
| El hijo excede `TIMEOUT_EJECUCION` | `kill()` y error controlado |
| No hay cupo libre | **503**, sin cuerpo leído y sin temporal escrito |

En los tres últimos casos el pipeline conserva el dueño del ciclo: el `try/finally` de limpieza de
temporales corre igual y el cupo del semáforo se libera igual.

## Alternativas consideradas

- **`pebble.ProcessPool` con `max_tasks=1` y timeout por tarea** — es la opción con menos código
  propio: aísla el fallo por tarea (`ProcessExpired` en lugar de romper el pool entero), reemplaza
  al worker muerto solo, y trae el timeout con terminación real ya resuelto y testeado por terceros.
  Se descartó por dos motivos. El primero es que **sigue siendo un pool, es decir una cola**, y el
  requisito acá es rechazar sin encolar: habría que anteponerle el semáforo de admisión igual, y una
  vez puesto ese semáforo el pool solo aporta el reciclado de workers, que `max_tasks=1` vuelve
  irrelevante porque el proceso muere después de cada tarea de todos modos. El segundo es que agrega
  una dependencia de terceros en el camino crítico de ejecución para un equipo de una persona.
  **Sigue siendo la opción a tomar si la plomería propia (ver Consecuencias) se vuelve una carga de
  mantenimiento real.**

- **Conservar el `ProcessPoolExecutor` y reconstruirlo al detectar `BrokenProcessPool`** — es el
  cambio más chico posible sobre la decisión original y deja el servicio operativo después del
  fallo. Se descartó porque no arregla el defecto, solo lo limpia: reconstruir el pool no le devuelve
  la vida a las ejecuciones concurrentes que ya murieron con él, y convierte un fallo de una
  ejecución en un reinicio del mecanismo de ejecución completo. El ADR 0001 no pide recuperarse del
  daño colateral: pide que no haya daño colateral.

- **N procesos worker con un trabajo pesado cada uno** (Gunicorn con `UvicornWorker` en Linux, o
  `uvicorn --workers` en Windows, con el threadpool capado a 1) — la opción más simple y estándar,
  con menos código propio que mantener. Se descartó por dos motivos: cuando un archivo anómalo mata
  al worker, **la petición en curso muere con él** y el portal recibe una conexión cortada en lugar
  del error controlado que el ADR 0001 pide explícitamente; y la variante más robusta (Gunicorn) no
  corre en Windows, atando la decisión a una plataforma aún no confirmada.

- **Concurrencia 1 por instancia más réplicas detrás de un balanceador** — el aislamiento sería
  perfecto y la aplicación quedaría trivial, sin semáforo ni procesos que administrar, con el límite
  de RAM impuesto por el orquestador y el rechazo por saturación resuelto en el balanceador. Se
  descartó porque exige orquestador y balanceador que el ítem #0 todavía no define, y porque para un
  uso interno acotado desaprovecha recursos de forma notoria. **Sigue siendo la evolución natural si
  el volumen de uso crece.**

## Consecuencias

- Se cumple el objetivo del ADR 0001 **de forma estructural**: no hay estado compartido entre
  ejecuciones, así que la muerte de un hijo no tiene por dónde propagarse. El peor caso mata a un
  proceso aislado, el servicio devuelve un error controlado y ninguna otra ejecución se ve afectada.
  Esta vez la propiedad se sostiene en el mecanismo, no en la esperanza de que una librería la tenga.
- La política de concurrencia queda en **un solo número real** (`EJECUCIONES_MAX`), no repartida
  entre el threadpool de Starlette, la cantidad de workers de Uvicorn y el tamaño de un pool.
- El servicio tiene una respuesta definida bajo saturación en lugar de degradarse en silencio, y
  nunca trabaja para un cliente que ya se fue.
- Las fugas de memoria de las librerías de procesamiento no son un problema operativo: cada
  ejecución arranca en un proceso limpio y muere con él.
- El diseño es portable entre Linux y Windows **porque el método de arranque está fijado**, no
  porque se asuma que los defaults coinciden. El ítem #0 puede resolverse después sin reabrir esto.
- **Costo real: el 503 es una respuesta nueva que el portal tiene que contemplar.** No es uno de los
  cinco errores tipificados del ADR 0014 y no lo puede ser: no es un fallo del usuario ni de su
  archivo, y no hay nada que corregir en la entrada. El portal necesita un caso propio — mensaje de
  "el servicio está ocupado, reintentá en unos segundos" y probablemente ningún `evento_uso` de
  error de usuario. Sin ese caso, un pico de carga le muestra al usuario un banner vacío. **Es
  trabajo obligatorio del ítem #10, no opcional.**
- **Costo real: la muerte del hijo y el timeout tampoco tienen tipo.** El ADR 0006 fijó un
  vocabulario de cinco valores pensado para fallos de la entrada, y la versión original de este ADR
  los mapeaba a "tamaño/contenido". Eso está mal: son fallos del sistema, y presentarlos como error
  del usuario le dice a alguien que su archivo es demasiado grande cuando lo que pasó es que se
  quedó sin memoria el servicio, además de contaminar la analítica del portal con `error_tamano`
  falsos. Este ADR **no** inventa un tipo nuevo, porque el vocabulario lo fijó el ADR 0006 heredado.
  Queda como riesgo abierto en el Technical Design, junto con el hueco de `cantidad` y
  `clave_inexistente` que ya estaba registrado.
- **Costo real: hay plomería propia que escribir y testear** — el `Pipe`, el `join`/`kill`, la
  propagación de la excepción del hijo con su traza, y la liberación del semáforo en todos los
  caminos. Es la contrapartida de no depender de las semánticas de fallo de una librería de terceros,
  y es exactamente el código que hay que cubrir con tests porque corre solo en el peor día.
- **Costo real: `spawn` en las dos plataformas significa pagar el peaje también en Linux.** Arrancar
  un intérprete nuevo por ejecución reimporta el árbol de módulos con pandas adentro y puede costar
  cientos de milisegundos por petición. Antes ese costo era solo de Windows; ahora se elige pagarlo
  en ambas para no tener dos comportamientos distintos. Es aceptable contra el presupuesto de 15
  segundos de p95, pero **hay que medirlo, no suponerlo** — sigue siendo el mismo riesgo abierto que
  ya registraba el Technical Design.
- **Costo real: sin cola, un pico de peticiones legítimas se rechaza con 503 aunque hubiera cabido
  esperando unos segundos.** Es deliberado, pero significa que `EJECUCIONES_MAX` mal calibrado se
  siente como un servicio caído. Hay que medirlo con uso real y ajustarlo, y el log operativo tiene
  que registrar los rechazos por saturación para poder verlo venir.
- **Costo real: `spawn` obliga a que el módulo de la aplicación sea importable sin efectos
  secundarios** y a que todo lo que cruza al hijo sea serializable. Con rutas de archivo es una
  restricción menor, pero acota la firma de `procesar` y hay que respetarla al escribir cada módulo.
- **Costo real:** depurar a través de un límite de proceso es más incómodo. Las trazas del hijo no
  aparecen solas en el log del padre; por eso la propagación explícita por el `Pipe` es parte de la
  decisión y no un detalle de implementación.
- El aislamiento por proceso **no impone por sí solo un techo de RAM al hijo**. En Linux el límite lo
  pone el contenedor y el OOM killer produce la terminación abrupta que este diseño ya maneja; en
  Windows nativo no hay equivalente directo y haría falta un Job Object o un guardián explícito. Por
  eso la **validación temprana del tamaño descomprimido del ADR 0006 sigue siendo la primera línea
  de defensa**, y esto es la segunda, no su reemplazo.
- **La versión mínima de Python ya no la fija este ADR.** La restricción de 3.11 venía de
  `max_tasks_per_child`, que desapareció junto con el pool. Se mantiene 3.11 como piso por otras
  razones (soporte vigente y tipado moderno), pero es una decisión de plataforma independiente y el
  ítem #0 no necesita tratarla como una consecuencia de este mecanismo.
