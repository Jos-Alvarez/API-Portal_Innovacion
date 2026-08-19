# ADR 0020: Ciclo de vida de los temporales

## Estado

Aceptado

## Contexto

H-02 (Crítico, Abierto): ADR 0006 hace del `try/finally` del pipeline el único lugar donde vive la
limpieza de temporales, con la intención declarada de que el borrado ocurra *"una vez enviada la
respuesta HTTP"*. Eso no es lo que un `finally` hace. FastAPI construye la respuesta completa dentro
de la propia llamada ASGI del endpoint (`request_response`: `response = await f(request)` y luego
`await response(scope, receive, send)` en la misma corrutina), de modo que todo lo que un `try/finally`
protege corre **antes** de que se envíe un solo byte del cuerpo. Cuando la respuesta *es* el temporal
(un `FileResponse`/`StreamingResponse` que sirve el archivo procesado), el `finally` borra el archivo
antes de que el bucle de envío pueda leerlo: el camino de éxito queda roto por construcción.

La medición, ya hecha en la exploración de este cambio y no re-derivada acá: `FileResponse._handle_simple`
no tiene guarda de `OSError`/desconexión; `StreamingResponse` sí guarda, pero relanza `ClientDisconnect()`.
**Ambas** clases llaman a `self.background()` recién después del bucle de envío, así que **ambas**
se saltan la limpieza cedida si el cliente se desconecta a mitad de envío. Cambiar de clase de
respuesta no cierra nada.

## Decisión

- **Modelo de propiedad con un único punto de transferencia.** `Reserva` es la dueña del directorio
  temporal de una petición: borra en su `finally` salvo que `ceder_limpieza()` haya transferido esa
  propiedad a un `BackgroundTask` de la respuesta. Antes de la transferencia, el `finally` limpia
  (camino de error de hoy); después, es un no-op y la respuesta limpia tras su propio envío (camino de
  éxito de los ítems #9/#10).
- **Raíz dedicada.** `Path(tempfile.gettempdir()) / "api-portal-temporales"`, creada por
  `preparar_raiz()` al arranque y, defensivamente, otra vez en cada `reservar()`. Cada petición recibe
  un subdirectorio propio vía `mkdtemp(prefix="pet-", dir=raiz)`: creación atómica, nombre único,
  permisos de sólo el dueño en POSIX, y no deriva nada de un cliente.
- **Barrendero gobernado por `_EN_VUELO` y edad, ambas condiciones requeridas.** Un hijo directo de la
  raíz se borra sólo si está ausente del registro en proceso `_EN_VUELO` (`dict[Path, float]`,
  poblado por `reservar()` con `time.monotonic()`) **y** su antigüedad por `mtime` supera el umbral. La
  edad sola nunca basta: es exactamente la suposición que borraría una subida lenta en curso. El
  registro tampoco puede crecer sin límite -- una petición desconectada nunca corre su propia
  limpieza --, así que el barrendero desaloja del registro las entradas más viejas que el mismo umbral
  antes de aplicar la regla de borrado. Un solo umbral gobierna ambos lados; no hay un segundo número
  que se pueda desincronizar.
- **Dos constantes nombradas.** `UMBRAL_DE_EDAD = 15 minutos` y `INTERVALO_DE_BARRIDO = 5 minutos`,
  adyacentes en el módulo, no en `Configuracion` -- no hay necesidad operativa identificada de
  ajustarlas por entorno. El umbral debe exceder la vida en vuelo más larga posible: el portal corta a
  los 2 minutos (ADR 0012, `TECH-DESIGN.md:300`) y `TIMEOUT_EJECUCION` queda estrictamente por debajo
  de ese corte, así que 15 minutos es aproximadamente 7.5 veces ese límite real.
- **Pasada de arranque y tarea periódica, ambas.** La pasada de arranque cubre el momento en que la
  población de huérfanos es más alta -- una caída, un OOM, un reinicio forzado dejan `_EN_VUELO` vacío
  y todo directorio sobreviviente sin dueño. La tarea periódica cubre el estado estacionario:
  desconexiones y borrados fallidos durante un proceso de vida larga.
- **Los nombres en disco siempre los genera el servidor.** `nombre_original` se conserva verbatim para
  el contrato (regla de cadena verbatim de ADR 0014) pero nunca llega a construir una ruta. La
  extensión se deriva con `nombre_original.rpartition(".")`, nunca con `Path(nombre_original).suffix`
  -- construir un `Path` a partir de una cadena de cliente es exactamente lo que esta decisión
  prohíbe, aunque el resultado sólo se lea.

## Alternativas consideradas

- **Cambiar `FileResponse` por `StreamingResponse` (o viceversa).** Descartado: la medición muestra que
  ambas clases llaman a `background()` después del bucle de envío: ninguna cierra el agujero de
  desconexión, así que el cambio no arregla nada.
- **Borrado temprano (`unlink` antes de que el sistema operativo cierre el último handle).**
  Descartado: sólo funciona en POSIX -- en Windows un archivo con un handle abierto no puede
  desvincularse de esa manera -- y ADR 0012 deja el objetivo de despliegue sin decidir. Nada en este
  repositorio puede fijar esa decisión por adelantado.
- **Leer el resultado a memoria antes de limpiar.** Descartado: contradice la razón por la que ADR 0006
  pone los temporales en disco en primer lugar. Además duplicaría en memoria un archivo que ya puede
  pesar hasta el límite de `tamano_max_bytes` del contrato.
- **Middleware ASGI dentro del `Mount`, limpiando después de `await self.app(...)`.** Técnicamente más
  fuerte -- sobreviviría también a una desconexión --, pero se descarta por tres razones: (a) ADR 0006
  hace del **pipeline** el único dueño de la limpieza de temporales (*"el pipeline común sigue siendo
  el único lugar donde viven las validaciones, los errores tipificados y la limpieza de temporales"*),
  y un middleware saca esa propiedad fuera del pipeline que los ítems #9/#10 construyen; (b) crearía un
  directorio temporal para **toda** petición a `/interno`, incluidas las que no suben nada; (c) sigue
  sin eliminar la necesidad de un barrendero -- la muerte de un proceso sigue huérfanando directorios
  de todas formas.
- **Sanear `nombre_original` en vez de generar el nombre en disco.** Descartado: generar el nombre en
  el servidor cierra traversal, acentos y colisiones de nombre duplicado en una sola decisión, en vez
  de exigir que tres reglas de escapado distintas estén todas bien, siempre, en cada punto de uso.

## Consecuencias

- El criterio de aceptación se degrada honestamente: "cero temporales tras la respuesta" es cierto en
  el camino feliz; ante una desconexión a mitad de envío pasa a ser "cero dentro del umbral" --
  acotado por `UMBRAL_DE_EDAD + INTERVALO_DE_BARRIDO` (15 + 5 = 20 minutos en el peor caso), no
  indefinido.
- El barrendero también sirve de mecanismo de reintento: en Windows, `shutil.rmtree` puede lanzar
  `PermissionError` si un handle sigue abierto (un `FileResponse` en pleno envío, o un antivirus
  escaneando). La limpieza usa `rmtree(..., ignore_errors=True)`, así que un borrado fallido queda en
  silencio; el directorio permanece, envejece más allá del umbral, y una pasada posterior del
  barrendero lo vuelve a intentar.
- **La solidez de `_EN_VUELO` depende de que ADR 0012 fije un único worker de Uvicorn para el servicio,
  y debe revisarse si el ítem #0 alguna vez elige un despliegue con más de un worker.** Un registro en
  proceso sólo es una autoridad completa mientras exista un único proceso de servicio: con más de un
  worker, cada uno vería sólo sus propias reservas, y la protección de directorios en vuelo se
  degradaría silenciosamente a "sólo edad" -- exactamente la regla insegura que la condición doble de
  esta decisión existe para evitar. Quien tome esa decisión de despliegue debe encontrar esta nota.
- H-09 casos 2, 3 y 4 (nombre de archivo hostil, nombre duplicado, extensión mal derivada) se cierran
  acá. El caso 1 (la mentira de `Content-Length`) sigue siendo del ítem #7, que aplica el límite de
  tamaño del contrato.
- La ruta parametrizada de recepción (Slice B, fuera de este registro) es un andamiaje temporal que se
  desvía deliberadamente del diseño por-procesador de ADR 0006; no se autoriza ni se deroga nada de ese
  ADR acá.
