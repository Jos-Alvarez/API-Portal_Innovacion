---
title: "Servicio de Procesadores — Portal de Innovación Lima Expresa"
---

# PRD: Servicio de Procesadores (FastAPI)

> **Documento subordinado.** Este PRD describe el repositorio `procesadores` (FastAPI), que es el
> **ítem #9** del backlog maestro del Portal de Innovación. La autoridad de arquitectura son los
> ADR del portal (`L:\App_Portal\adrs\`) y `BACKLOG.md`. Ante cualquier discrepancia entre este
> documento y un ADR, **manda el ADR**. Este PRD no crea decisiones de arquitectura: las refleja y
> las baja a requisitos de producto para este servicio.
>
> Documentos de referencia leídos y respetados: ADR 0001 (dos desplegables y política de
> concurrencia/memoria), ADR 0002 (modelo de datos y fila `procesador`), ADR 0003 (contrato REST y
> proxy del portal), ADR 0005 (SQL Server, acceso de solo lectura), ADR 0006 (registry, rutas por
> procesador, pipeline común, empaquetado ZIP, límites), y `BACKLOG.md`.
>
> Los **mecanismos** con los que este servicio cumple todo eso viven en sus propios ADR (`adrs/`,
> numerados desde 0011) y en su `TECH-DESIGN.md`. Este PRD los cita cuando una decisión de mecanismo
> tiene consecuencia visible para el producto — el rechazo con 503 bajo saturación del ADR 0012 es el
> caso —, pero la regla no cambia: ante una discrepancia, manda el ADR.

## Problema

Hoy el procesamiento de archivos se ejecuta de forma manual: cada usuario corre scripts de Python
en su máquina, moviendo archivos entre carpetas locales de "Entrada" y "Salida". Esto genera cuatro
problemas concretos:

- **Dependencia del entorno local**: el procesamiento solo funciona si el usuario tiene Python, las
  dependencias correctas y el script actualizado en su equipo.
- **Sin trazabilidad**: nadie sabe qué se procesó, cuándo, por quién, ni si falló.
- **Sin validación previa**: los errores de formato se descubren recién cuando el script explota a
  mitad de la ejecución.
- **Costo de agregar automatizaciones nuevas**: cada script nuevo implica distribuirlo, documentarlo
  y capacitar a los usuarios uno por uno.

Importa ahora porque el Portal de Innovación es el punto de entrada web del ecosistema, pero la
ejecución pesada no puede vivir en Node: el ecosistema Python (pandas, openpyxl, python-docx) es el
adecuado para manipular Excel y Word, y esa carga debe estar aislada del portal (ADR 0001).

## Usuario objetivo

**Consumidor directo y exclusivo**: el backend de Next.js del Portal de Innovación, actuando como
**proxy** (ADR 0003, ADR 0006). El navegador llama a `POST /api/procesadores/{id}/ejecutar` en el
portal; el portal resuelve la sesión, **verifica la asignación del usuario en SQL Server** y recién
entonces reenvía los archivos a este servicio por red interna. El navegador **nunca** llama a este
servicio directamente.

**Usuario final indirecto**: el personal interno de Lima Expresa que hoy ejecuta scripts
manualmente y que, con esto, sube archivos desde el navegador y descarga el resultado sin tocar una
terminal.

El portal se autentica con un **token de servicio** en los headers. Hay **un único token de
servicio global**, exclusivo del portal. Este servicio **no conoce al usuario**: no ve la cookie de
sesión, no recibe identidad y no consulta permisos. Confía en que el portal ya autorizó (ADR 0006,
ADR 0007).

## Objetivo / resultado esperado

Que cualquier automatización de transformación de archivos se pueda incorporar aportando **solo su
lógica de negocio**: un módulo Python que implementa la interfaz `Procesador`, su inscripción en el
registry por clave, y una ruta cáscara que declara su forma de entrada. Todo lo transversal —
validaciones, límites, errores tipificados, empaquetado ZIP, limpieza de temporales — ya está
resuelto en el pipeline común y no se vuelve a escribir nunca.

Para el usuario final: sube archivos en el portal, recibe el resultado (archivo suelto o ZIP), y ya
no depende de su máquina ni de carpetas locales.

## Alcance (qué sí incluye esta versión)

### Autenticación y superficie

- **Token de servicio obligatorio**: toda petición debe presentar el token en los headers. Sin token
  válido, se rechaza con 401 antes de leer el cuerpo del request. El token se configura por variable
  de entorno; no vive en el código ni en el repositorio.
- **Una ruta interna por procesador** (ADR 0006), por ejemplo
  `POST /interno/procesadores/contado-carga/ejecutar`. Cada ruta declara **su propia forma de
  entrada** (cuántos archivos y con qué nombre de campo) y **delega de inmediato en el pipeline
  común**. Una ruta que valide formatos, resuelva errores o arme el ZIP por su cuenta está mal
  escrita.
- **Endpoint de health check** para monitoreo y despliegue.

### Pipeline común (el corazón del servicio)

Único lugar donde viven las validaciones, los errores tipificados, el empaquetado y la limpieza.
Para cada ejecución, en este orden:

1. **Resuelve la fila `procesador` en SQL Server** por `clave_procesador` (solo lectura).
2. **Valida la cantidad** de archivos contra `entradas_min` / `entradas_max`.
3. **Valida el formato** de cada archivo contra los formatos aceptados de la fila.
4. **Valida el tamaño comprimido de cada archivo** contra `tamano_max`, y la **suma** contra
   `tamano_max_total`.
5. **Valida el tamaño descomprimido declarado** (anti zip-bomb, obligatorio): los `.xlsx`/`.docx`
   son archivos ZIP; antes de pasarlos a pandas u openpyxl, se inspeccionan los metadatos del ZIP y
   se suma el tamaño descomprimido de sus entradas. Si excede el límite seguro de RAM del worker
   (configurable, holgadamente por debajo de la memoria disponible), se aborta con error controlado
   — **nunca un OOM**.
6. **Busca el módulo en el registry** por clave e invoca `validar(archivos)`, que delega en el
   módulo la validación de **contenido**.
7. **Ejecuta** `procesar(archivos)`.
8. **Empaqueta la salida**: un archivo se entrega tal cual con su MIME y su nombre; **más de uno se
   comprime en ZIP**. La decisión es del pipeline, nunca del módulo.
9. **Limpia todos los temporales** en `try/finally`: cada archivo de entrada, cada archivo de salida
   y el ZIP intermedio. Ninguno sobrevive a la request, ni en éxito ni en error.

- **Interfaz `Procesador` común** (ADR 0006): `validar(archivos: list[ArchivoEntrada]) ->
  ErrorTipificado | None` y `procesar(archivos: list[ArchivoEntrada]) -> list[ArchivoSalida]`.
  Siempre listas, incluso para un solo archivo: un único camino de código, sin ramas especiales.
- **Registry indexado por clave**: `dict[str, Procesador]`.
- **Vocabulario de errores tipificados**, definido en este servicio y consumido por el portal:
  **formato, tamaño, contenido, cantidad, clave inexistente**. El portal los mapea al banner de la
  UI y al tipo de `evento_uso`. Este vocabulario se define acá y se consume allá, no al revés.

### Datos y almacenamiento

- **Acceso a SQL Server de solo lectura** (ADR 0005): los modelos Python son un **espejo del esquema
  dictado por Prisma en el portal**. El servicio lee la fila `procesador` y nada más. Corre con un
  **usuario de BD acotado**: `SELECT` sobre las tablas que necesita, **sin DDL y sin
  `INSERT`/`UPDATE`/`DELETE`**.
- **Temporales en volumen de disco**, no en memoria (ADR 0006): los archivos de entrada y salida se
  escriben en disco temporal para **aliviar la RAM** durante el procesamiento, evitando tener el
  archivo completo en memoria a la vez que las estructuras de pandas/openpyxl.
- **Sin estado entre requests**: el servicio no almacena archivos para descargas posteriores. La
  persistencia del resultado es responsabilidad del navegador del usuario.

### Operación

- **Concurrencia acotada** (ADR 0001, ADR 0012): un número fijo y limitado de ejecuciones
  simultáneas, y **límite estricto de RAM por contenedor/instancia**. Cada ejecución corre en un
  proceso propio que nace y muere con ella. En el peor caso un archivo anómalo mata a **ese proceso**
  — aislado, y sin nada compartido con los demás — y devuelve error controlado, sin tumbar el
  servicio ni afectar otras ejecuciones en curso.
- **Rechazo inmediato bajo saturación, sin cola de espera** (ADR 0012). Si todos los cupos de
  ejecución están ocupados, el servicio responde **503 en el acto**: no encola la petición, no espera
  y no llega a leer el archivo. Aceptar trabajo que recién iba a empezar después de que el portal
  cortó a los 2 minutos es gastar memoria y CPU para una respuesta que nadie va a leer, y le quita la
  cupo a una petición que sí tiene a alguien esperando del otro lado.

  **Este 503 no es un error tipificado y no puede serlo**: no es culpa del archivo ni del usuario, y
  no hay nada en la entrada que se pueda corregir. Es una condición temporal del servicio y el
  mensaje que corresponde es "está ocupado, reintentá en unos segundos". El portal necesita tratarlo
  como un caso propio (ítem #10), distinto de los cinco errores de contrato.
- **Techo de tiempo por ejecución** (ADR 0012): un módulo que se cuelga se termina de verdad al
  alcanzar el límite, por debajo de los 2 minutos del portal, y libera su cupo. Sin eso, una sola
  ejecución trabada iría comiéndose la capacidad del servicio hasta que todo respondiera 503.
- **Logging operativo estructurado** por ejecución: clave del procesador, cantidad y tamaño de
  archivos, duración, resultado y tipo de error, **más los rechazos por saturación**. Es para
  **diagnóstico y operación del servicio**, no la fuente de la analítica del producto. Sin el
  registro de rechazos, un límite de concurrencia mal calibrado se ve exactamente igual que un
  servicio caído.

### Entregables de procesador

- **Procesador de fixture (passthrough)** — ítem #11 del backlog: módulo mínimo que recibe un
  archivo y devuelve una salida marcada, más una variante multi-archivo que devuelve ZIP. **Es el
  que prueba la tubería completa** navegador → portal → FastAPI → descarga, sin depender de reglas
  de negocio.
- **`Contado_Carga`** — uno de los 3 procesadores reales del ítem #12, posterior al #11. Recibe un
  Excel financiero y devuelve dos archivos (un Excel y un TXT) que el pipeline empaqueta en ZIP.
  Sus reglas de negocio están documentadas por el código de `Contado_Carga.py`, con el
  endurecimiento obligatorio detallado en "Casos borde".

## No alcance (qué explícitamente no incluye esta versión)

### Lo que pertenece al portal, no a este servicio

- **No hay endpoint de descubrimiento de contratos.** La **única fuente de verdad** del contrato de
  entrada/salida es la fila `procesador` en SQL Server (`entradas_min`, `entradas_max`,
  `tamano_max`, `tamano_max_total`, `salida_esperada`), administrada desde el panel admin del portal
  (ítem #6). El portal arma la interfaz de carga leyendo esa fila. Un endpoint de descubrimiento
  sería una **segunda verdad que se desincroniza**, y el ADR 0006 lo prohíbe explícitamente.
- **No se registra `evento_uso`.** El servicio devuelve el resultado o un error tipificado; el
  **portal escribe la fila**, porque es quien conoce al usuario. La analítica del producto vive
  entera en el portal.
- **No hay dominio de identidad**: sin sesión, sin usuarios, sin permisos, sin roles. La autorización
  por asignación ocurre en el portal, antes de que la petición llegue acá.
- **No se administra el catálogo**: alta, edición y baja de la fila `procesador` son del panel admin
  del portal (ítem #6).

### Límites del propio servicio

- **No es dueño del esquema de base de datos** ni ejecuta migraciones. Está **estrictamente
  prohibido** crear o alterar tablas, índices o columnas. Si necesita un cambio estructural, se
  solicita al portal, que lo implementa en su migración de Prisma (ADR 0005).
- **No escribe ninguna fila** en la base de datos.
- **No hay procesamiento asíncrono ni cola de trabajos**: todo se resuelve dentro del request HTTP.
  **Tampoco hay cola de espera interna**: una petición que llega con el servicio saturado se rechaza
  con 503, no se guarda para atenderla cuando se libere un cupo. No hay sala de espera, ni tiempo
  estimado, ni reintento automático del lado del servicio — el reintento es del usuario, desde el
  portal.
- **No hay persistencia de archivos** ni historial descargable ni reprocesamiento posterior.
- **No hay UI propia**: el único frontend del ecosistema es el portal.
- **No hay soporte para múltiples consumidores**: un solo token global para el portal, sin emisión
  de tokens por cliente ni identificación de terceros.
- **No hay gestión de permisos por procesador en el servicio**: un token válido habilita todas las
  rutas internas. La restricción por usuario es del portal.
- **No hay rotación automática ni dos tokens válidos en simultáneo**: rotar implica cambiar la
  variable de entorno en el servicio y en el portal y reiniciar — **downtime planificado**.
- **No hay carga dinámica de procesadores en caliente**: dar de alta un procesador requiere módulo +
  registro + ruta cáscara + fila en BD, y por lo tanto **un despliegue del servicio**.
- **No hay ejecución en sandbox de los módulos**: el código de los procesadores lo escribe el equipo
  interno y se considera confiable.
- **No hay multi-tenancy ni aislamiento por cliente.**

## Criterios de éxito

- **Cero dependencia local**: el 100% de los usuarios de un procesador migrado ejecuta su trabajo
  desde el portal. El script deja de distribuirse.
- **El pipeline es agnóstico, y es verificable**: el código del pipeline común no contiene ninguna
  referencia — import, condicional o nombre — a un procesador concreto. Buscar el nombre de
  cualquier procesador dentro del pipeline devuelve cero resultados. Las rutas cáscara sí nombran a
  su procesador; el pipeline jamás.
- **Toda ruta delega**: existe un test que verifica que **cada** ruta por procesador llama al
  pipeline común y no reimplementa validación, empaquetado ni manejo de errores. Este test es lo que
  impide que la separación de rutas degenere en la alternativa que el ADR 0006 rechazó.
- **Costo de agregar un procesador**: incorporar una automatización nueva requiere módulo, registro,
  ruta cáscara y fila en BD — **cero cambios en el pipeline común**. Verificable al agregar el
  segundo procesador: archivos del pipeline tocados, cero.
- **Ninguna petición sin autenticar llega a un módulo**: el 100% de las peticiones sin token o con
  token inválido se rechaza con 401, sin ejecutar lógica de negocio y sin registrar el contenido del
  archivo. (El token es estático por configuración: no hay vencimiento en esta versión.)
- **Errores tipificados antes de procesar**: el 100% de las entradas inválidas se rechaza con uno de
  los cinco tipos definidos (formato / tamaño / contenido / cantidad / clave inexistente), sin
  invocar el módulo cuando la falla es de cantidad, formato, tamaño o clave.
- **Nunca un OOM**: ningún archivo, por anómalo que sea, produce una caída por memoria sin error
  controlado. Verificable con un `.xlsx` de zip-bomb en la suite de tests.
- **Cero temporales sobrevivientes**: tras cada ejecución — éxito, error de validación, excepción del
  módulo, timeout o rechazo por saturación — el volumen temporal queda sin archivos de esa request.
  Verificable en test.
- **Nunca se acepta trabajo que no se va a poder atender a tiempo**: con todos los cupos ocupados,
  el 100% de las peticiones nuevas se rechaza con 503 de inmediato y **ninguna queda encolada**.
  Verificable en test: ocupados los cupos, la petición siguiente responde sin haber leído su archivo
  y sin haber escrito un temporal.
- **Ningún cupo se pierde**: tras cien ejecuciones mezclando éxito, error, excepción del módulo y
  timeout, la capacidad de ejecuciones simultáneas del servicio es la misma que al arrancar.
  Verificable en test, y es lo que impide que el servicio se degrade solo hasta responder 503 a todo.
- **Paridad de salida verificable** para cada procesador real: se validan con **3 pares reales de
  entrada/salida**, preparados **antes** de escribir la lógica de validación de negocio. El TXT se
  compara **byte a byte** (cubre codificación y fin de línea) y el Excel por contenido normalizado.
  Los 3 pares pasan; ninguno se ajusta para que pase.
- **Latencia**: para `Contado_Carga`, el tiempo de respuesta p95 **no supera los 15 segundos**,
  validado contra el promedio de la ejecución manual actual. El servicio corta por su cuenta antes
  del techo del portal, que corta a los 2 minutos (ítem #10); ninguno de los dos es el objetivo, son
  el techo duro.

## Casos borde a contemplar

### Autenticación y superficie

- **Petición sin header de token, con token vacío, malformado o incorrecto** → 401, sin pistas sobre
  el token esperado y sin leer el archivo.
- **El servicio arranca sin token configurado** en el entorno — no debe arrancar "abierto" por
  omisión; si falta la configuración, **falla al iniciar**.
- **Comparación del token vulnerable a timing** — verificación de tiempo constante, no `==`.
- **El token aparece en logs, mensajes de error o trazas** — nunca debe registrarse, ni parcialmente.
- **Petición directa desde el navegador** al endpoint interno — debe ser inalcanzable por red; el
  aislamiento es un requisito de infraestructura (prerrequisito de TI, ítem #0), no una preferencia.

### Contrato y base de datos

- **`clave_procesador` existe en la fila de BD pero no en el registry** (desincronización
  fila ↔ código) → error claro y explícito. Es un modo de fallo nuevo que introduce esta
  arquitectura, y el ADR 0006 lo señala por nombre.
- **La fila `procesador` no existe o está marcada inactiva** → error tipificado de clave inexistente.
- **La base de datos no responde** — el servicio no puede validar nada sin la fila; debe devolver un
  error controlado que el portal pueda mostrar, no un stack trace.
- **El espejo Python del esquema quedó desactualizado** tras una migración de Prisma del portal →
  error de lectura, nunca corrupción: el usuario de BD no tiene DDL.

### Archivos y límites

- **Cero archivos enviados** a una ruta que exige al menos uno → error de cantidad.
- **Más archivos que `entradas_max`**, o menos que `entradas_min` → error de cantidad.
- **Un archivo excede `tamano_max`** → error de tamaño, sin cargarlo entero en memoria.
- **La suma de los archivos excede `tamano_max_total`** — diez archivos de 24 MB son 240 MB en una
  sola request. El presupuesto de memoria es del worker, no de cada archivo por separado.
- **`Content-Length` ausente o mentido** — el corte por tamaño no puede depender solo del header
  declarado; hay que cortar también mientras se lee el stream.
- **Archivo `.xlsx`/`.docx` que se descomprime a varios GB** (zip bomb o Excel legítimo enorme) →
  abortado antes de tocar pandas u openpyxl.
- **Archivo con extensión válida pero contenido corrupto o vacío** (un `.xlsx` de 0 bytes, un CSV sin
  encabezados) — la extensión no alcanza; el módulo debe fallar con error de contenido.
- **Nombres de archivo con caracteres especiales, acentos, espacios o rutas embebidas** — riesgo de
  path traversal al escribir temporales y al armar el ZIP de salida.
- **Dos archivos de entrada con el mismo nombre** en una carga múltiple.
- **El módulo devuelve cero archivos de salida** (la entrada no tenía filas válidas) — no es un error
  del sistema, pero el portal necesita distinguirlo del éxito normal: debe llegar como error de
  contenido, no como ZIP vacío.
- **El módulo genera el primer archivo pero falla al generar el segundo** — no se devuelve un ZIP a
  medias; o sale la salida completa, o es un error.

### Ejecución y limpieza

- **Todos los cupos de ejecución ocupados y llega una petición más** → 503 inmediato, sin encolar,
  sin leer el archivo y sin dejar temporales de esa petición. El caso hay que provocarlo en un test,
  no esperar a verlo en producción.
- **Un cupo no se libera** tras un error, un timeout o una excepción del módulo — es la forma en
  que este diseño se degrada hasta responder 503 a todo. La liberación va en el mismo `try/finally`
  que la limpieza de temporales, y se verifica igual que ella.
- **El procesamiento excede el timeout de 2 minutos del portal** — el servicio debe liberar sus
  temporales igual, aunque nadie escuche la respuesta.
- **Un módulo se cuelga y nunca termina** (un bucle infinito, una operación patológica de pandas) —
  el servicio lo corta por su cuenta antes del timeout del portal y termina el proceso de verdad. Un
  proceso huérfano consumiendo CPU con su cupo tomado es peor que un error.
- **El cliente corta la conexión** a mitad del procesamiento — el `try/finally` corre igual.
- **Un módulo mata a su proceso de ejecución por memoria** — ese proceso es aislado y no comparte
  nada con los demás; el resto de las ejecuciones en curso terminan normalmente y la petición
  siguiente se atiende sin reinicio.
- **Ejecuciones concurrentes del mismo procesador** — los módulos no comparten estado global entre
  requests. El registry aloja instancias; ninguna puede guardar estado de una ejecución.
- **Un módulo escribe a rutas absolutas** heredadas del script original — el patrón "carpeta
  Entrada/Salida" no puede sobrevivir a la migración.

### Endurecimiento obligatorio de `Contado_Carga` (ítem #12)

Estos tres puntos surgen de leer `Contado_Carga.py` y son **requisitos de la migración**, no
sugerencias. El script actual falla en silencio en los tres casos:

- **Fin de línea del TXT forzado explícitamente.** Hoy el volcado usa
  `open(archivo, 'w', encoding='utf-8')` sin `newline=''`, así que en Windows Python traduce `\n` a
  `\r\n` y el archivo sale con **CRLF**. En un contenedor Linux, el mismo código emite **LF**. La
  codificación UTF-8 es correcta y se mantiene; el fin de línea debe fijarse explícitamente al valor
  que espera el sistema destino, no heredarse de la plataforma.
- **Lectura de columnas por nombre, no por posición.** Hoy el script accede con `fila.iloc[1]`,
  `iloc[8]`, `iloc[13]`, `iloc[14]`. El riesgo real no es que renombren una columna: es que
  **inserten una**. Todo se corre un lugar, el script no falla y produce salida incorrecta. La
  migración lee por nombre de columna y **falla con error de contenido** si falta alguna obligatoria.
- **Los descartes dejan de ser silenciosos.** Hoy las filas cuya plaza no está en `MAPEO_PLAZAS`
  (10 plazas con texto exacto) se descartan con un `continue`, igual que las filas con fechas
  inválidas. Si el Excel trae una plaza nueva o con el texto apenas distinto, esas filas desaparecen
  y el proceso termina "bien". La migración debe **contar los descartes y reportarlos**, y tratar el
  caso de **cero filas procesadas** como error de contenido explícito, no como éxito vacío.
- Además: las excepciones por fila (`continue`) y la global (`traceback.print_exc()`) dejan de
  tragarse. Todo error se convierte en error tipificado; nada se imprime a stdout esperando que
  alguien lo lea.

## Supuestos y riesgos abiertos

- **Decisión heredada — HTTP plano dentro del perímetro**: el tráfico portal ↔ servicio va por HTTP
  plano, protegido por el aislamiento estricto de la red interna. El token de servicio viaja en
  claro y por lo tanto **no protege contra un atacante que ya esté dentro del perímetro**. El control
  de confidencialidad es el aislamiento de red; el token protege contra invocaciones no autorizadas
  desde fuera del portal.

  **Política estricta de arquitectura**: si el servicio alguna vez sale de la red interna aislada,
  pasar a TLS/HTTPS es **obligatorio y previo** a la exposición. Condiciones que la disparan: el
  endpoint se vuelve alcanzable desde fuera, aparece un consumidor que no es el portal, o los datos
  procesados pasan a exigir cifrado en tránsito.

- **Dependencia externa bloqueante**: el ítem #9 depende del #0 (red interna aislada, base de datos
  provisionada con sus dos usuarios de distinto privilegio) y del #2 (esquema y migraciones del
  portal). Ninguno de los dos lo resuelve este repositorio. Si TI demora, no hay nada que programar
  acá.

- **El 503 por saturación no tiene todavía tratamiento en el portal**: es una respuesta que no existía
  cuando se escribió el contrato de errores, y no es ninguno de los cinco tipos, así que el mapeo del
  ítem #10 no lo cubre. Necesita su propio mensaje — "el servicio está ocupado, reintentá en unos
  segundos" — y una decisión sobre si merece o no una fila de `evento_uso`, que probablemente no,
  porque no es un error del usuario ni una ejecución. Si nadie lo toma, un pico de carga le deja al
  usuario un banner vacío o un error genérico que lo invita a corregir un archivo que está bien.

- **El número de ejecuciones simultáneas todavía no tiene un valor fundado**: de él dependen dos
  cosas opuestas — el techo de memoria del servicio y la frecuencia con la que un usuario legítimo se
  come un 503. Calibrarlo exige medir la huella real de `Contado_Carga` contra la RAM de la instancia,
  y esa instancia no existe hasta el ítem #0. Hasta entonces es una estimación conservadora, no un
  dato, y el primer mes de uso real es lo que lo va a ajustar.

- **Riesgo de acoplamiento por BD compartida**: el servicio depende del esquema que migra el portal.
  Un cambio de estructura del portal puede romper la lectura del espejo Python sin aviso previo.
  La coordinación es en una sola dirección, pero existe.

- **Riesgo de degradación de las rutas cáscara**: la superficie del servicio crece con el catálogo, y
  la presión para "resolver rápido" una particularidad metiendo validación dentro de una ruta es
  real — aparece bajo deadline, no en el diseño. La regla: si una ruta necesita validar algo, o va
  al pipeline o va al módulo, nunca a la ruta. El test de delegación es lo que sostiene esto.

- **Riesgo de versiones de Pandas**: pandas y sus dependencias de Excel (`openpyxl`, `xlrd`) son
  pesadas y sensibles a versión. Un cambio puede alterar silenciosamente cómo se leen tipos, fechas
  o decimales y romper la paridad de salida sin que falle nada. Las versiones se fijan.

- **Riesgo de migración subestimada**: `Contado_Carga.py` lee de una carpeta fija, escribe a rutas
  absolutas y traga excepciones. Convertirlo a "recibe bytes, devuelve bytes" con errores tipificados
  es reescritura, no envoltura.

- **Versionado por clave de procesador**: si un procesador rompe compatibilidad, se registra como
  clave nueva (`contado-carga-v2`), lo que implica **fila nueva + módulo nuevo + ruta nueva**, y la
  anterior sigue viva. Consecuencia a asumir: las claves viejas se acumulan y nadie las retira por
  iniciativa propia. Hace falta una señal de deprecación en el panel admin y una decisión consciente
  de retiro.

- **Supuesto validado**: los volúmenes son compatibles con procesamiento síncrono. Los límites
  (25 MB por archivo, `tamano_max_total` por procesador, y el tope de tamaño descomprimido contra la
  RAM del worker) son lo que **mantiene válida la arquitectura sin cola**, no parámetros cosméticos
  que se suben cuando molestan. El día que un caso de uso necesite superarlos, la conversación es
  cola de trabajos, no un número más grande.

- **Abierto**: dos de los tres procesadores reales del ítem #12 siguen sin reglas de negocio
  documentadas. `Contado_Carga` está desbloqueado porque su código las documenta; los otros dos no.
