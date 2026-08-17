# Revisión adversarial del diseño — Servicio de Procesadores

**Fecha:** 2026-08-14 · **Alcance:** `PRD.md`, `TECH-DESIGN.md`, ADR 0011 a 0015, más los ADR 0001 y
0006 heredados del portal.

> **Qué es este documento.** El registro de una revisión hecha para **buscar dónde se rompe el
> diseño**, no para validarlo. No es una auditoría de calidad ni una lista de mejoras: cada hallazgo
> es un problema concreto con su consecuencia. Lo que sobrevivió a la revisión también está anotado,
> porque saber qué se cuestionó y aguantó vale tanto como saber qué falló.
>
> Este documento **no es autoridad de arquitectura**. Las decisiones viven en los ADR; acá está por
> qué algunas cambiaron y qué sigue sin resolverse.

## Método y sus límites

- La revisión corrió en una **conversación nueva**, sin la historia de cómo se produjo el diseño. Es
  deliberado: preguntarle a quien escribió un documento si está seguro tiende a producir una defensa,
  no una crítica.
- Se leyeron completos el PRD, el Technical Design, los cinco ADR de este repositorio y los ADR 0001
  y 0006 del portal (los dos que más condicionan este servicio).
- **No se leyeron** `DESIGN.md` del portal ni los ADR 0002, 0003, 0005 y 0007. Seis de las once
  decisiones en vigor son heredadas y solo dos se verificaron contra su fuente. La revisión es más
  débil en todo lo que dependa de las otras cuatro.

## Estado

| # | Hallazgo | Severidad | Estado |
|---|---|---|---|
| H-01 | El pool no aislaba la muerte del hijo | Crítico | **Resuelto** — ADR 0012 reescrito |
| H-02 | La limpieza en `try/finally` borra el temporal antes de enviarlo | Crítico | **Abierto** |
| H-03 | Concurrencia real N×N y presupuesto de RAM sin agregar | Crítico | **Parcial** |
| H-04 | La defensa anti-OOM mide la magnitud equivocada | Crítico | **Abierto** |
| H-05 | Tres fallos del sistema sin tipo de error | Crítico | **Registrado, sin resolver** |
| H-06 | Paridad byte a byte contra endurecimiento obligatorio | Crítico | **Registrado, sin resolver** |
| H-07 | Sin timeout ni terminación real del hijo | Advertencia | **Resuelto** |
| H-08 | El health check contradice "token obligatorio" | Advertencia | **Abierto** |
| H-09 | Sin decisión sobre la ingesta de archivos | Advertencia | **Abierto** |
| H-10 | Observabilidad sin hilo conductor con el portal | Advertencia | **Parcial** |
| H-11 | `salida_esperada` se lee y no se usa | Advertencia | **Abierto** |
| H-12 | "Idéntica en Linux y Windows" sin fijar el start method | Advertencia | **Resuelto** |
| H-13 | Sin backpressure: el pool encolaba sin límite | Advertencia | **Resuelto** |
| H-14 | Un módulo puede alcanzar la base de datos | Sugerencia | **Resuelto** |
| H-15 | El manifiesto de fixtures no tiene quién lo revise | Sugerencia | **Resuelto** |
| H-16 | La clave del procesador vive en tres lugares | Sugerencia | **Parcial** |

Ocho resueltos, tres parciales, cinco abiertos.

---

## Resueltos

### H-01 · El pool no aislaba la muerte del hijo — Crítico

**Dónde:** ADR 0012 (versión original).

El ADR prometía que "el peor caso mata a un hijo aislado y ninguna otra ejecución se ve afectada".
`ProcessPoolExecutor` no hace eso: cuando un hijo termina de forma no limpia — el caso del OOM
killer, justamente el que el ADR venía a resolver — el executor entra en estado *broken*, todas las
tareas pendientes y en vuelo fallan con `BrokenProcessPool`, y todo `submit` posterior levanta la
misma excepción. Un archivo anómalo no mataba a un hijo: mataba a todas las ejecuciones concurrentes
y dejaba al worker de API inservible hasta un reinicio.

Contradecía el objetivo textual del ADR 0001 heredado, que era el motivo por el que se había elegido
el pool.

**Cómo se resolvió.** Se reabrió el ADR 0012 y se eliminó el pool. Cada ejecución corre en un
proceso dedicado que nace y muere con ella, sin estado compartido con las demás. El aislamiento dejó
de depender de las semánticas de fallo de una librería y pasó a ser una propiedad de la estructura:
no hay pool que pueda quedar roto porque no hay pool.

### H-07 · Sin timeout ni terminación real del hijo — Advertencia

**Dónde:** ADR 0012 (versión original), PRD "Ejecución y limpieza".

`future.result(timeout=...)` corta la espera, no al hijo; `future.cancel()` solo sirve antes de que
la tarea arranque. Un módulo colgado seguía consumiendo CPU y RAM indefinidamente. Como segundo
orden, si el padre corría su limpieza mientras el huérfano tenía el archivo abierto, en **Windows**
`os.remove` falla con `PermissionError` y el criterio "cero temporales sobrevivientes" se rompía
justo en el caso que lo motivó.

**Cómo se resolvió.** `join(TIMEOUT_EJECUCION)` seguido de `kill()`, con el límite estrictamente por
debajo del corte de 2 minutos del portal. Al morir el hijo antes de la limpieza, desaparece también
el bloqueo de archivo en Windows.

### H-12 · "Idéntica en Linux y Windows" sin fijar el start method — Advertencia

**Dónde:** ADR 0012 (versión original).

El ADR apoyaba buena parte de su valor en ser indiferente al ítem #0, pero no fijaba el método de
arranque de procesos. En Windows es `spawn`; en Linux fue `fork` durante años y cambia con las
versiones. Con `fork`, el hijo hereda los descriptores del padre —entre ellos el pool de conexiones
`pyodbc`— y su recolección de basura o su salida pueden cerrar sockets que el padre sigue usando,
aunque el hijo nunca consulte la base.

**Cómo se resolvió.** `multiprocessing.set_start_method("spawn", force=True)` en el arranque de
`main.py`, antes de crear cualquier proceso o conexión. La afirmación de portabilidad pasó a ser
verdadera en vez de una suposición sobre defaults.

### H-13 · Sin backpressure: el pool encolaba sin límite — Advertencia

**Dónde:** ADR 0012 (versión original), PRD.

Con las ejecuciones ocupadas, las peticiones se encolaban sin tope. El portal corta a los 2 minutos,
pero el trabajo encolado se ejecutaba igual después: quemaba CPU y RAM para una respuesta que ya
nadie iba a leer, y le sacaba el lugar a una petición que sí tenía cliente esperando.

**Cómo se resolvió.** Semáforo de admisión con `acquire(blocking=False)` y **503 inmediato** cuando
no hay cupo: sin encolar, sin esperar, sin leer el cuerpo y sin escribir temporales. Bajado también
al PRD, porque es comportamiento visible para el usuario final.

### H-14 · Un módulo puede alcanzar la base de datos — Sugerencia

**Dónde:** ADR 0013, Consecuencias.

El ADR afirmaba que "un módulo de negocio no tiene forma de alcanzar la base ni por accidente". Era
falso: nada impedía un `from app.core import db`, y el proceso hijo hereda las credenciales por
variable de entorno. Lo único que protegía era que el usuario de base de datos es de solo lectura,
que es otra cosa.

**Cómo se resolvió.** Se agregó a los invariantes del Technical Design una comprobación estática que
prohíbe a `procesadores/` importar `core.db`, directa o transitivamente, y falla la CI. Se corrigió
la afirmación del ADR 0013 para nombrar las tres cosas que ahora la sostienen: `spawn`, la regla de
import y el usuario acotado como último contenedor de daño.

### H-15 · El manifiesto de fixtures no tiene quién lo revise — Sugerencia

**Dónde:** ADR 0015.

El ADR decía que la verificación por `sha256` "sostiene la regla del PRD de que ninguno se ajusta
para que pase". Con un equipo de una persona no hay revisor: regenerar la salida con el código nuevo
y actualizar el hash en el mismo cambio es un solo paso. El control era procedimental y no tenía
quién lo ejecutara. Y un hash prueba que el archivo no cambió, no de dónde salió.

**Cómo se resolvió.** El manifiesto exige por par un bloque de **procedencia**: `version_script`
(sha256 del `.py` que produjo la salida, porque el script no está versionado), `generado_el`,
`generado_en` y `fin_de_linea` observado. Un par sin procedencia completa es un fallo. El ADR ahora
dice con todas las letras que la barrera es procedimental; lo que agrega la procedencia es que
ajustar un fixture deje de ser invisible.

---

## Parciales

### H-03 · Concurrencia real N×N y presupuesto de RAM sin agregar — Crítico

**Dónde:** ADR 0012 (versión original), ADR 0001.

El diagrama ponía un pool de N dentro de cada uno de los N workers de Uvicorn: hasta N×N procesos
con pandas cargado, no N. El ADR celebraba que la concurrencia quedaba "en un solo parámetro
explícito" cuando eran dos que se multiplicaban. Y el límite de memoria se validaba **por archivo**
contra el límite seguro del worker, sin ningún control agregado entre ejecuciones concurrentes.

**Qué se resolvió.** La multiplicación. Uvicorn corre con un worker de API y `EJECUCIONES_MAX` es el
único parámetro de concurrencia; si el ítem #0 exigiera varios workers, el presupuesto se divide
explícitamente y queda documentado.

**Qué sigue abierto.** El presupuesto de memoria sigue sin agregarse. `EJECUCIONES_MAX` acota
**cuántas** ejecuciones hay a la vez, no **cuánta memoria** suman. Si el límite seguro por ejecución
es de 1 GB y `EJECUCIONES_MAX` es 4, cada petición pasa la validación individualmente y el
contenedor puede reventar igual. Hace falta una de dos cosas: calibrar `EJECUCIONES_MAX` × límite
seguro contra la RAM de la instancia como una sola cuenta explícita, o un techo de RAM por proceso
hijo. Enganchado con H-04, que es el mismo problema visto desde el otro lado.

### H-10 · Observabilidad sin hilo conductor con el portal — Advertencia

**Dónde:** PRD "Logging operativo estructurado", Technical Design.

El PRD exige logging estructurado por ejecución y el Technical Design no tenía **ni un solo** criterio
de aceptación para logs. Falta lo que los hace servir: un **id de correlación** que el portal mande en
el header y el servicio registre. Sin eso, diagnosticar "a Fulano le falló la ejecución de ayer a las
3" es cruzar timestamps a ojo entre el `evento_uso` del portal y los logs del servicio — que es
exactamente el problema de trazabilidad que el PRD dice venir a resolver.

**Qué se resolvió.** El registro de los rechazos por saturación, que sin él vuelven indistinguible un
límite mal calibrado de un servicio caído.

**Qué sigue abierto.** Todo lo demás: el id de correlación, el formato, el destino, y las trazas del
proceso hijo, que el ADR 0012 anota como costo pero ninguna decisión resuelve. No hay ADR de
observabilidad.

### H-16 · La clave del procesador vive en tres lugares — Sugerencia

**Dónde:** ADR 0011, ADR 0013, Technical Design.

Segmento de la URL, clave del registry y `clave_procesador` en la base. Los ADR solo nombraban la
desincronización registry ↔ base.

**Qué se resolvió.** El chequeo de arranque contrasta el registry contra la base y convierte esa
desincronización de un 500 en producción —que aparece cuando un usuario ya subió su archivo— en un
mensaje al desplegar. La regla es asimétrica a propósito: **falla** por lo que controla este
repositorio (clave registrada sin fila alguna) y **solo advierte** por lo que administra el portal
(fila activa sin registry, fila inactiva). Un chequeo simétrico le daría a un administrador la
capacidad de impedir el arranque del servicio desde un formulario web.

**Qué sigue abierto.** La tercera pata. El segmento de la URL de la ruta cáscara no se contrasta
contra nada: si la ruta declara `contado-carga` y el registry indexa `contado_carga`, no hay
comprobación que lo note.

---

## Abiertos

### H-02 · La limpieza en `try/finally` borra el temporal antes de enviarlo — Crítico

**Dónde:** Technical Design, pipeline paso 9 y criterios de "Ejecución exitosa".

El pipeline limpia los temporales en `try/finally` y el criterio dice que tras la respuesta el
directorio queda sin archivos. Pero los archivos viven en disco justamente para aliviar la RAM, así
que la respuesta va a ser un `FileResponse` sobre una ruta — y en ASGI el cuerpo se streamea
**después** de que la función del endpoint retorna. El `finally` corre antes: el temporal se borra
antes de enviarse y el usuario recibe un archivo vacío o un 500. **En el camino feliz, no en un
borde.**

Ninguna de las dos salidas está decidida, y las dos tienen costo:

- Leer el resultado a memoria antes de limpiar contradice el motivo por el que los temporales están
  en disco (ADR 0006).
- Colgar la limpieza de un `BackgroundTask` hace que "cero temporales tras la respuesta" pase a ser
  eventual, y obliga a definir qué pasa si el cliente corta a mitad del stream — caso borde que el
  PRD ya lista.

Vale la pena notar que el ADR 0006 heredado dice "eliminar los temporales **una vez enviada la
respuesta HTTP**", que no es lo mismo que un `try/finally`. Esa diferencia de una línea es todo el
problema.

### H-04 · La defensa anti-OOM mide la magnitud equivocada — Crítico

**Dónde:** ADR 0006 heredado, adoptado sin cuestionar por el Technical Design.

El Technical Design dice que en Windows nativo la validación de tamaño descomprimido "es la única
defensa efectiva de memoria". Esa única defensa tiene dos agujeros:

- **Es un dato declarado por el propio archivo.** El tamaño descomprimido sale del directorio central
  del ZIP. Un `.xlsx` fabricado puede declarar 5 MB y expandir a varios GB; `zipfile` recién lo nota
  cuando ya descomprimió todo y verifica el CRC. La prueba de zip-bomb que el PRD exige va a pasar en
  verde con una bomba honesta y dar confianza falsa.
- **Aunque el número fuera cierto, no es la magnitud que importa.** Lo que agota la RAM no es el XML
  descomprimido: es el `DataFrame`. La relación entre ambos no es 1:1 y suele ser mucho peor con
  columnas de texto. El mismo ADR 0006 dice que los formatos no-ZIP "se acotan por el tope de 25 MB
  comprimido, que ya limita su tamaño en memoria", y eso es directamente falso: un CSV de 25 MB con
  texto se convierte en cientos de MB de objetos Python.

El criterio de éxito "**nunca un OOM**: ningún archivo, por anómalo que sea" no está sostenido por
esta comprobación. Necesita un techo real de memoria del proceso hijo (Job Object en Windows,
cgroup o `RLIMIT_AS` en Linux) o una lectura acotada que corte al superar N bytes descomprimidos
**reales**. Resolver esto cierra también la mitad que quedó abierta de H-03.

**Nota sobre urgencia:** el modelo de amenaza atenúa la probabilidad — las entradas vienen de
personal interno autenticado, no de internet. Lo que no atenúa es el Excel legítimo enorme, ni la
falsa confianza de un test que pasa sin probar lo que dice probar.

### H-05 · Tres fallos del sistema sin tipo de error — Crítico

**Dónde:** ADR 0014, ADR 0013, ADR 0012.

El ADR 0014 cierra el vocabulario en cinco valores y dice que el servicio no emite nada fuera de
ellos. Pero el diseño necesita emitir tres cosas más:

- **ADR 0013** decide que si la base no responde se devuelve "un error tipificado de servicio no
  disponible". Ese tipo no existe.
- El Technical Design exige que la desincronización fila ↔ registry sea "distinguible de: el
  procesador no existe". Con cinco valores cerrados y `clave_inexistente` ya asignado a la fila
  ausente o inactiva, ese criterio es insatisfacible.
- La muerte del proceso hijo y el timeout de ejecución tampoco tienen dónde caer. La versión original
  del ADR 0012 los mapeaba a "tamaño/contenido": eso le diría al usuario que su archivo es demasiado
  grande cuando lo que pasó fue que el servicio se quedó sin memoria, y ensuciaría la analítica del
  portal con `error_tamano` falsos.

**Qué se hizo.** Registrarlo. El ADR 0012 reescrito decide explícitamente **no** inventar tipos
nuevos, porque el vocabulario lo fijó el ADR 0006 heredado, y el Technical Design lo lleva a riesgos
abiertos. El 503 por saturación se documentó en el PRD como respuesta que no es —y no puede ser— un
error tipificado.

**Qué falta.** La decisión de fondo. Sumado al hueco preexistente de `cantidad` y
`clave_inexistente`, son cinco situaciones que llegan al portal sin destino definido. Resolverlo
exige reabrir el ADR 0006 del portal o cerrarlo del lado del ítem #10; no se puede hacer solo desde
este repositorio.

### H-06 · Paridad byte a byte contra endurecimiento obligatorio — Crítico

**Dónde:** PRD "Criterios de éxito" y "Endurecimiento obligatorio de `Contado_Carga`", ADR 0015.

El PRD pide dos cosas incompatibles sobre los mismos tres pares de fixtures:

1. El TXT coincide **byte a byte** con el que produjo el script actual.
2. El script actual **está mal** en tres formas que la migración debe corregir: descarta filas en
   silencio cuando la plaza no está en `MAPEO_PLAZAS`, se traga excepciones y lee por posición.

Si cualquiera de los tres pares contiene una fila que el script descartó en silencio —y la
probabilidad no es baja, porque ese es justamente el defecto que se quiere corregir— entonces el
código nuevo, **haciendo lo correcto**, produce una salida distinta a la esperada. Y "cero filas
procesadas → error de contenido" convierte un fixture legítimo del script viejo en un fallo del
nuevo.

**Qué se hizo.** El manifiesto ahora documenta **cómo** se generó cada salida esperada (H-15), y el
riesgo quedó registrado en el Technical Design y en las consecuencias del ADR 0015.

**Qué falta.** El manifiesto documenta la procedencia, no **qué comportamiento representa** la salida
esperada. La acción concreta: **revisar los tres pares y confirmar que no contienen descartes
silenciosos antes de congelar sus hashes.** Si alguno los contiene, hay que decidir explícitamente
cuál de los dos requisitos manda — y si gana el comportamiento corregido, la salida esperada no la
puede generar el script, hay que construirla a mano y "paridad" pasa a significar otra cosa.

### H-08 · El health check contradice "token obligatorio" — Advertencia

**Dónde:** PRD "Autenticación y superficie", Technical Design "Autenticación".

El PRD dice que toda petición debe presentar el token y que sin token válido se rechaza con 401, y el
criterio de aceptación lo formaliza sin excepciones. En la misma sección pide un endpoint de health
check para monitoreo y despliegue. Un probe de orquestador o balanceador no lleva el token de
servicio: o el health está exento —y entonces hay una ruta sin autenticar que ningún documento
declara— o el probe siempre da 401 y el despliegue nunca queda sano.

Tampoco está decidido si el health consulta SQL Server. Si lo hace, un hipo de base reinicia
contenedores; si no lo hace, reporta sano mientras el 100% de las peticiones falla. Cero criterios de
aceptación para el único endpoint que decide si el servicio se considera vivo.

### H-09 · Sin decisión sobre la ingesta de archivos — Advertencia

**Dónde:** área de decisión ausente. `core/temporales.py` aparece en la estructura como si el problema
estuviera resuelto.

No hay ADR sobre la ingesta multipart, y ahí aterrizan cuatro casos borde del PRD que hoy no tienen
dueño:

- "`Content-Length` ausente o mentido → hay que cortar mientras se lee el stream". Con `UploadFile`
  de Starlette el cuerpo ya se consumió entero antes de que se pueda ver el tamaño. Cortar durante el
  stream exige una decisión concreta y no está tomada.
- "Nombres con caracteres especiales o **rutas embebidas**": riesgo de path traversal al escribir
  temporales y al armar el ZIP de salida.
- "Dos archivos de entrada con el mismo nombre".
- El directorio temporal por petición que los criterios de aceptación mencionan pero que ninguna
  decisión define.

Es el punto de entrada de datos no confiables y es el único componente del pipeline sin decisión
escrita.

### H-11 · `salida_esperada` se lee y no se usa — Advertencia

**Dónde:** Technical Design, "Modelo de datos".

La tabla dice que el campo "permite al portal anticipar si la respuesta es archivo suelto o ZIP" —
pero el portal lee esa fila por su cuenta. Que este servicio lo traiga y no lo use es un campo muerto
en el `SELECT`.

Esconde además una tercera desincronización que nadie cubrió: la fila declara "archivo suelto", el
módulo devuelve dos, el pipeline arma un ZIP y el portal —que preparó la interfaz para un archivo
suelto— recibe algo que no espera. El campo debería ser una **postcondición verificada** después de
`procesar`, o no leerse. Hoy no es ni una cosa ni la otra.

---

## Lo que aguantó la revisión

**ADR 0011 — estructura en dos paquetes.** No se le encontró un problema real. Las dos alternativas
son genuinamente viables y están descartadas por razones concretas: la de tres paquetes tiene un
beneficio que el ADR reconoce y anota como pérdida (leer toda la superficie HTTP de un tirón), y el
descarte de arquitectura hexagonal por proporción está bien argumentado para nueve pasos secuenciales
y un equipo de una persona. El ADR admite además que la estructura solo cubre la mitad del invariante
y nombra qué cubre la otra mitad.

**ADR 0015 — fixtures fuera del repositorio.** La decisión de fondo se sostiene: sacar extractos
financieros reales del historial de Git es correcto, y el argumento de por qué anonimizar rompe el
fixture —la rama que imprime sin decimales los números mayores a `1000000000`— es específico y
técnico, no genérico. Las objeciones (H-06, H-15) son sobre lo que el manifiesto no podía garantizar,
no sobre dónde viven los archivos.

**ADR 0014 — contrato de errores.** Acertó en lo difícil: dejar toda la redacción del lado de
`DESIGN.md` y mandar solo tipo y datos, con un descarte de RFC 9457 bien fundado. Su problema (H-05)
es de completitud del enum, no de forma.

**ADR 0013 — lectura directa sin cache.** El argumento central se sostiene y es el mejor de los cinco:
el beneficio de resiliencia de una cache es ilusorio porque el portal consulta la misma base antes de
reenviar y falla primero. Los dos costos reales están anotados sin maquillaje. Lo único que se le
corrigió fue una afirmación de más (H-14).

## Qué mirar primero

1. **H-02**, porque rompe el camino feliz y no depende de nadie más.
2. **H-04 junto con la mitad abierta de H-03**, que son el mismo problema de memoria visto desde dos
   lados y hoy no tienen defensa real.
3. **H-06**, porque su acción concreta —revisar los tres pares antes de congelar los hashes— hay que
   hacerla **antes** de escribir el módulo, no después.
4. **H-05**, que necesita conversación con el ítem #10 y no se puede cerrar solo desde acá.
