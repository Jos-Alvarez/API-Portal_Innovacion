# Technical Design Document: Servicio de Procesadores (FastAPI)

**Tipo de proyecto:** Brownfield. El repositorio `procesadores` es nuevo, pero nace dentro de un
ecosistema ya diseñado. Repositorios y documentos revisados:

- `L:\App_Portal` — Portal de Innovación (Next.js + TypeScript). Se leyeron `BACKLOG.md`,
  `TECH-DESIGN.md`, `DESIGN.md` y los ADR 0001 a 0010.
- `L:\API-Portal\Contado_Carga.py` — el script manual que se migra en el ítem #12.

**Design.md disponible:** Sí, pero pertenece al portal (`L:\App_Portal\DESIGN.md`). Este servicio no
tiene interfaz de usuario, así que `DESIGN.md` **no impone modelo de datos** acá. Lo único que baja a
este repositorio es una restricción de contrato: los errores tipificados deben poder mostrarse como
banners en lenguaje claro sin códigos técnicos (`DESIGN.md`, líneas 80 y 82). Esa restricción se
resuelve en el ADR 0014.

**Autoridad de arquitectura.** Este documento está **subordinado** a los ADR del portal. Ante
cualquier discrepancia, manda el ADR del portal. Los ADR nuevos de este repositorio se numeran
**desde 0011** para que ningún número se repita en el ecosistema.

**Sobre los ADR heredados.** No se duplican en este repositorio. Copiarlos crearía dos versiones del
mismo documento que se desincronizan — precisamente lo que el ADR 0006 prohíbe al hablar de una
"segunda verdad". Se referencian por su ruta en `L:\App_Portal\adrs\`.

## Resumen

Se construye el servicio de procesadores del Portal de Innovación de Lima Expresa: el **ítem #9** del
backlog maestro. Es un servicio FastAPI que recibe archivos del portal por red interna, los procesa
con módulos Python y devuelve el resultado — un archivo suelto o varios empaquetados en ZIP.

Reemplaza la práctica actual de ejecutar scripts a mano moviendo archivos entre carpetas locales de
"Entrada" y "Salida". Su valor no es procesar un archivo: es que **toda automatización futura se
incorpore aportando solo su lógica de negocio**, sobre un pipeline que ya resuelve autenticación,
validación, límites, errores tipificados, empaquetado y limpieza.

El servicio no conoce usuarios, no escribe en la base de datos y no registra analítica. Esas tres
cosas son del portal.

## Arquitectura de componentes

### Del ecosistema (ya existía — ADR 0001)

```
Navegador
   │  POST /api/procesadores/{id}/ejecutar
   ▼
Portal (Next.js) ─── resuelve sesión, verifica asignación en SQL Server
   │                 403 si no corresponde, sin procesar
   │  red interna + token de servicio
   ▼
Servicio de procesadores (FastAPI)  ← ESTE REPOSITORIO
   │  SELECT (solo lectura)
   ▼
SQL Server  ← esquema propiedad del portal (Prisma migra; acá solo se lee)
```

El portal es el **único** consumidor. El navegador nunca alcanza este servicio. El portal escribe el
`evento_uso`; el servicio devuelve resultado o error tipificado.

### Interna del servicio (nueva — ADR 0011, 0012)

```
app/
  core/                    # el pipeline agnóstico — nunca importa de procesadores/
    pipeline.py            # los 9 pasos, en orden
    validaciones.py        # cantidad, formato, tamaño, tamaño descomprimido
    errores.py             # los 5 tipos tipificados
    empaquetado.py         # ZIP si hay más de una salida
    temporales.py          # try/finally, limpieza total
    ejecucion.py           # semáforo de admisión + proceso dedicado por ejecución
    db.py                  # espejo de solo lectura de SQL Server
    seguridad.py           # token de servicio
    interfaz.py            # ABC Procesador
  procesadores/            # un paquete autocontenido por procesador
    passthrough/           # ítem #11 — prueba la tubería
      modulo.py
      ruta.py
    contado_carga/         # ítem #12
      modulo.py
      ruta.py
  registry.py              # clave -> instancia
  main.py
```

### El pipeline común, paso a paso

Único lugar donde viven validaciones, errores, empaquetado y limpieza. En el **proceso padre**:

0. **Admisión** (ADR 0012). Intenta tomar un cupo del semáforo de ejecuciones sin bloquear. Si no
   hay ninguno libre, responde **503 de inmediato**, antes de leer el cuerpo de la petición y sin
   escribir un solo temporal. No se encola: aceptar trabajo que va a empezar después de que el
   portal cortó a los 2 minutos es gastar memoria y CPU para nadie.
1. Resuelve la fila `procesador` en SQL Server por `clave_procesador` (ADR 0013).
2. Valida la cantidad de archivos contra `entradas_min` / `entradas_max`.
3. Valida el formato de cada archivo.
4. Valida el tamaño comprimido de cada archivo contra `tamano_max`, y la suma contra
   `tamano_max_total`.
5. Valida el **tamaño descomprimido declarado** contra el límite seguro de RAM (anti zip-bomb,
   ADR 0006). Primera línea de defensa contra el agotamiento de memoria.
6. Busca el módulo en el registry e invoca `validar(archivos)` — validación de **contenido**.
7. Despacha `procesar(archivos)` a un **proceso dedicado** (ADR 0012), con timeout duro y
   terminación real si lo excede. Segunda línea de defensa.
8. Empaqueta: una salida se entrega tal cual; más de una se comprime en ZIP.
9. Limpia **todos** los temporales en `try/finally` — entradas, salidas y el ZIP.

Los pasos 0 a 6, 8 y 9 corren en el proceso padre. Solo el paso 7 cruza a un proceso hijo, que se
crea para esa ejecución y muere con ella. **Los procesos hijo nunca tocan la base de datos**, y con
el arranque forzado en `spawn` del ADR 0012 tampoco heredan conexiones que pudieran usar sin querer.

El cupo tomado en el paso 0 se libera en el mismo `try/finally` que limpia los temporales: en
éxito, en error de validación, en excepción del módulo y en timeout.

### Arranque del servicio

Antes de aceptar la primera petición, `main.py` hace tres cosas en orden:

1. **Fija el método de arranque de procesos** en `spawn` (ADR 0012), antes de crear cualquier
   proceso o conexión.
2. **Exige el token de servicio** en el entorno. Sin token configurado, el servicio no arranca: no
   existe el modo "abierto por omisión".
3. **Contrasta el registry contra la base de datos.** Lee las claves de `procesador` y las compara
   con las claves registradas en el código, según esta tabla:

| Situación | Qué hace el arranque |
|---|---|
| Clave en el registry **sin fila alguna** en la base | **Falla al arrancar**, nombrando la clave. Es un despliegue incompleto: hay código con una ruta viva que nunca va a poder ejecutarse |
| Clave en el registry con fila presente pero `activo = false` | **Arranca**, con advertencia en el log. Desactivar un procesador desde el panel admin es una operación legítima y no puede tumbar el servicio |
| Fila activa **sin entrada en el registry** | **Arranca**, con advertencia explícita nombrando la clave. El catálogo lo administra el portal y un alta anticipada no debe impedir un despliegue; en ejecución esa clave sigue dando el error de desincronización |

La asimetría es deliberada: el arranque falla por lo que este repositorio controla (su propio
código) y solo advierte por lo que administra el portal (las filas). Un chequeo que fallara en los
tres casos le daría a un administrador la capacidad de impedir el arranque del servicio desde un
formulario web.

Esto convierte la desincronización fila ↔ registry de un 500 en producción, que aparece cuando un
usuario ya subió su archivo, en un mensaje en el arranque del despliegue. También es la primera
señal — imperfecta pero temprana — de que el espejo de SQLAlchemy quedó desactualizado tras una
migración de Prisma: si la consulta de arranque falla, falla antes de recibir tráfico.

**Costo asumido:** el arranque pasa a depender de SQL Server. Si la base no responde, el servicio no
levanta y el orquestador reintenta. Se acepta porque un servicio que no puede leer el contrato no
puede procesar nada de todos modos (ADR 0013), pero el mensaje de fallo tiene que distinguir "no
pude conectar" de "el registry no coincide", o el diagnóstico se vuelve adivinanza.

## Decisiones de arquitectura

### Heredadas del portal (`L:\App_Portal\adrs\`)

| # | Decisión | Estado | Qué impone acá |
|---|---|---|---|
| [ADR-0001](../App_Portal/adrs/0001-monolito-full-stack.md) | Portal monolítico + servicio independiente de procesadores | Aceptado (heredado) | Este servicio existe como desplegable aparte; workers fijos y límite de RAM por instancia |
| [ADR-0002](../App_Portal/adrs/0002-modelo-datos-tablas-separadas.md) | Modelo de datos en tablas separadas | Aceptado (heredado) | La fila `procesador` y sus campos de contrato de E/S |
| [ADR-0003](../App_Portal/adrs/0003-api-rest-json-interna.md) | API REST JSON interna, portal como proxy | Aceptado (heredado) | El navegador nunca llama acá; el portal reenvía |
| [ADR-0005](../App_Portal/adrs/0005-base-datos-sql-server.md) | SQL Server, portal dueño único del esquema | Aceptado (heredado) | Acceso de solo lectura, usuario con `SELECT`, sin DDL ni escritura |
| [ADR-0006](../App_Portal/adrs/0006-procesadores-registro-modulos.md) | Procesadores como módulos con interfaz común y registro por clave | Aceptado (heredado) | Registry, ruta por procesador, pipeline común, ZIP, límites, temporales en disco |
| [ADR-0007](../App_Portal/adrs/0007-estado-servidor-fuente-verdad.md) | Estado del servidor como fuente de verdad | Aceptado (heredado) | La autorización ocurre en el portal; este servicio no consulta permisos |

### Nuevas de este repositorio

| # | Decisión | Estado |
|---|---|---|
| [ADR-0011](adrs/0011-estructura-core-procesadores.md) | Estructura en dos paquetes: `core` y `procesadores` | Aceptado |
| [ADR-0012](adrs/0012-ejecucion-en-procesos-dedicados.md) | Ejecución en procesos dedicados, con admisión acotada y rechazo con 503 | Aceptado (mecanismo revisado) |
| [ADR-0013](adrs/0013-lectura-directa-del-contrato-en-bd.md) | Lectura directa del contrato en SQL Server, sin cache | Aceptado |
| [ADR-0014](adrs/0014-contrato-de-errores-tipificados.md) | Contrato de errores: tipo y datos, sin copia de interfaz | Aceptado |
| [ADR-0015](adrs/0015-fixtures-de-paridad-fuera-del-repositorio.md) | Fixtures de paridad fuera del repositorio, con manifiesto de procedencia | Aceptado |

## Modelo de datos

Este servicio **no es dueño de ninguna entidad persistida**. El modelo relacional pertenece al portal
(ADR 0002) y lo migra Prisma (ADR 0005).

### Lo que se lee de SQL Server

Una sola tabla, en solo lectura, mediante un espejo declarativo en SQLAlchemy Core:

| Campo de `procesador` | Uso en el pipeline |
|---|---|
| `clave_procesador` | Clave de búsqueda; enlaza la fila con la entrada del registry |
| `activo` | Una fila inactiva produce error tipificado `clave_inexistente` |
| formatos aceptados | Paso 3 — validación de formato |
| `tamano_max` | Paso 4 — tamaño comprimido de **cada** archivo |
| `tamano_max_total` | Paso 4 — **suma** de los tamaños comprimidos |
| `entradas_min` / `entradas_max` | Paso 2 — validación de cantidad |
| `salida_esperada` | Permite al portal anticipar si la respuesta es archivo suelto o ZIP |

Esta fila es la **única fuente de verdad del contrato**. No hay endpoint de descubrimiento y no hay
declaración equivalente en el código del módulo: una segunda declaración sería una segunda verdad
que se desincroniza (ADR 0006).

### Estructuras en memoria (no persistidas)

- **`ArchivoEntrada`** — nombre original, ruta del temporal en disco, tamaño comprimido, formato.
- **`ArchivoSalida`** — nombre propuesto, ruta del temporal, tipo MIME.
- **`ErrorTipificado`** — `tipo` (enum cerrado de cinco valores) y `contexto` (datos estructurados
  del fallo, sin texto de interfaz).

Los `ArchivoEntrada` cruzan al proceso hijo **como rutas, no como bytes** (ADR 0012).

## Criterios de aceptación por flujo

### Ejecución exitosa con salida única

- [ ] Una petición con token válido, clave existente y archivos dentro del contrato devuelve el
      archivo con su tipo MIME y su nombre correctos, sin envolverlo en ZIP.
- [ ] El módulo recibe rutas de temporales existentes y legibles, nunca bytes en memoria.
- [ ] Tras la respuesta, el directorio temporal de esa petición queda sin archivos.

### Ejecución exitosa con salida múltiple

- [ ] Un módulo que devuelve dos o más archivos produce **un ZIP**, armado por el pipeline y no por
      el módulo.
- [ ] El ZIP contiene exactamente los archivos devueltos, con sus nombres, sin rutas absolutas ni
      componentes de directorio embebidos.
- [ ] Tras la respuesta, ni los archivos de salida ni el ZIP intermedio sobreviven.

### Autenticación

- [ ] Petición sin header de token → 401, sin leer el cuerpo del request.
- [ ] Token vacío, malformado o incorrecto → 401, sin pistas sobre el token esperado.
- [ ] El servicio **no arranca** si la variable de entorno del token no está configurada.
- [ ] La comparación del token usa tiempo constante, verificable por inspección del código.
- [ ] Ninguna traza, log o mensaje de error contiene el token, ni siquiera parcialmente.

### Rechazo por contrato

- [ ] Menos de `entradas_min` o más de `entradas_max` archivos → 422 con `tipo: "cantidad"`.
- [ ] Formato no aceptado → 422 con `tipo: "formato"`.
- [ ] Un archivo que excede `tamano_max` → 422 con `tipo: "tamano"`, sin cargarlo entero en memoria.
- [ ] Varios archivos cuya **suma** excede `tamano_max_total` → 422 con `tipo: "tamano"`, aunque cada
      uno individualmente sea válido.
- [ ] `Content-Length` ausente o menor al real → el corte ocurre igual, leyendo el stream.
- [ ] Ninguno de estos casos llega a invocar `procesar` del módulo.
- [ ] Toda respuesta de error incluye `contexto` con los datos del fallo y **ningún texto destinado
      al usuario final**.

### Defensa de memoria

- [ ] Un `.xlsx` cuyo contenido descomprimido declarado excede el límite seguro se rechaza **antes**
      de instanciar el módulo y antes de que pandas u openpyxl lo abran.
- [ ] Un módulo que agota la memoria mata a su proceso hijo, y el servicio responde con un error
      controlado — **nunca** con una conexión cortada ni un worker de API caído.
- [ ] Con dos ejecuciones concurrentes, matar el proceso hijo de una desde afuera no altera el
      resultado de la otra: la superviviente termina normalmente y devuelve su salida completa. Este
      es el criterio que la versión original del ADR 0012 no cumplía, y se verifica matando el
      proceso, no simulando una excepción.
- [ ] Tras la muerte de un hijo, la siguiente petición se atiende con normalidad, sin reinicio del
      servicio ni estado degradado.
- [ ] Tras un fallo por memoria, los temporales de esa petición igual se eliminan.

### Admisión y saturación

- [ ] Con todos los cupos de `EJECUCIONES_MAX` ocupados, una petición nueva recibe **503 de
      inmediato**: no espera, no encola, y el cuerpo de la petición no se lee.
- [ ] Tras un 503 por saturación no queda ningún temporal escrito para esa petición.
- [ ] Al terminar una ejecución — con éxito, con error o por timeout — el cupo queda libre y la
      siguiente petición se admite.
- [ ] Un módulo que se cuelga se termina al alcanzar `TIMEOUT_EJECUCION`, el proceso hijo muere de
      verdad (no queda huérfano consumiendo CPU) y el cupo se libera.
- [ ] `TIMEOUT_EJECUCION` es estrictamente menor que el corte de 2 minutos del portal, verificable
      por configuración.
- [ ] Cada rechazo por saturación queda registrado en el log operativo: sin eso, `EJECUCIONES_MAX`
      mal calibrado se ve como un servicio caído y no hay forma de distinguirlo.

### Desincronización fila ↔ registry

- [ ] `clave_procesador` presente en la base pero ausente del registry → error explícito e
      inequívoco, distinguible de "el procesador no existe".
- [ ] Fila inexistente o con `activo = false` → `tipo: "clave_inexistente"`.
- [ ] La base de datos inaccesible → error controlado, nunca un stack trace hacia el portal.

#### Chequeo de arranque

- [ ] Una clave registrada en el código **sin ninguna fila** en la base impide el arranque, y el
      mensaje nombra la clave. El despliegue falla en el despliegue, no en la primera petición de un
      usuario que ya subió su archivo.
- [ ] Una clave registrada cuya fila existe pero está inactiva **no** impide el arranque: deja una
      advertencia en el log. Desactivar un procesador desde el panel admin no puede tumbar el
      servicio.
- [ ] Una fila activa sin entrada en el registry **no** impide el arranque: deja una advertencia
      explícita que nombra la clave. El catálogo lo administra el portal y un alta anticipada es
      legítima.
- [ ] El fallo por base inaccesible al arrancar tiene un mensaje distinto del fallo por registry
      desincronizado. Son dos problemas con dos culpables distintos y no pueden compartir salida.
- [ ] El chequeo usa el mismo usuario de base de datos de solo lectura: es un `SELECT` más, no una
      excepción al ADR 0005.

### Invariantes de arquitectura

- [ ] Una comprobación automatizada verifica que **`core/` no importa nada de `procesadores/`**, y
      falla la CI si alguien lo rompe.
- [ ] La misma comprobación verifica que **ningún módulo de `procesadores/` importa `core.db`**, ni
      directa ni transitivamente, y falla la CI si alguien lo rompe. Sin esta regla, la afirmación
      del ADR 0013 de que un módulo de negocio no alcanza la base de datos depende de la disciplina
      de quien lo escribe: nada impide un `from app.core import db`, y el proceso hijo hereda las
      credenciales por variable de entorno. La regla la convierte en una línea visible en el diff.
- [ ] Un procesador puede importar del resto de `core/` lo que necesite (la interfaz, los tipos de
      error): la prohibición es del acceso a datos, no de `core/` entero.
- [ ] Un test verifica que **cada** ruta por procesador delega en el pipeline común y no reimplementa
      validación, empaquetado ni manejo de errores.
- [ ] Buscar el nombre de cualquier procesador dentro de `core/` devuelve cero resultados.
- [ ] Incorporar un segundo procesador toca cero archivos de `core/`.

### Paridad de `Contado_Carga` (ítem #12)

- [ ] Los 3 pares reales pasan. Ninguno se ajustó para que pasara: el `sha256` de cada fixture
      coincide con el manifiesto.
- [ ] El TXT coincide **byte a byte**, incluyendo codificación UTF-8 y fin de línea.
- [ ] El fin de línea del TXT se fija de forma explícita en el código, no se hereda de la plataforma.
- [ ] Las columnas se leen **por nombre**; falta una columna obligatoria → `tipo: "contenido"` con la
      columna faltante en el `contexto`.
- [ ] Una fila con plaza no reconocida en `MAPEO_PLAZAS` **se cuenta y se reporta**; no desaparece en
      silencio.
- [ ] Cero filas procesadas → `tipo: "contenido"`, nunca un ZIP vacío ni un éxito sin archivos.
- [ ] Ninguna excepción se traga: no quedan `continue` silenciosos ni `traceback.print_exc()`.
- [ ] En CI, la ausencia de fixtures **falla**; solo el entorno local puede saltear la prueba, y con
      aviso explícito.

### Rendimiento

- [ ] p95 de `Contado_Carga` ≤ 15 segundos, medido de punta a punta en el servicio.
- [ ] El costo de arranque del proceso hijo está **medido**, no supuesto, y documentado como parte
      del presupuesto de esos 15 segundos.

## Riesgos técnicos abiertos

- **El entorno de despliegue no está definido** (ítem #0): contenedor Linux o servicio Windows
  nativo. El ADR 0012 se eligió para ser indiferente a esa decisión, pero hay una consecuencia real:
  en Linux el límite de RAM lo impone el contenedor y el OOM killer produce el fallo esperado del
  hijo; **en Windows nativo no hay equivalente directo** y haría falta un Job Object o un guardián
  explícito. Mientras no se resuelva, la validación de tamaño descomprimido del ADR 0006 es la única
  defensa efectiva de memoria en ese escenario.

- **Dos de los cinco errores tipificados no tienen destino en el portal.** El ADR 0006 mapea
  `evento_uso` a `error_formato`, `error_tamano` y `error_contenido`, y `DESIGN.md` nombra esos
  mismos tres motivos en el banner. **`cantidad` y `clave_inexistente` no figuran en ninguno de los
  dos.** `cantidad` es un fallo que el usuario puede corregir y merece su propio banner;
  `clave_inexistente` es un fallo de sistema y no debería presentarse como error del usuario.
  Resolverlo es trabajo del ítem #10, pero si nadie lo toma, esos dos errores llegan al portal sin
  tratamiento.

- **El fin de línea del TXT depende hoy de la plataforma.** `Contado_Carga.py` abre el archivo con
  `open(ruta, 'w', encoding='utf-8')` sin `newline=''`, así que en Windows emite CRLF y en Linux
  emitiría LF. La codificación UTF-8 está confirmada como correcta; el fin de línea **no está
  confirmado** con el sistema que consume el TXT. Si el consumidor exige CRLF y el servicio termina
  desplegado en Linux, la paridad se rompe. Los fixtures lo detectan, pero conviene confirmarlo antes
  de escribir el módulo.

- **Dependencias externas bloqueantes** (prerrequisitos del backlog, responsabilidad de TI): red
  interna con el endpoint inalcanzable desde fuera, y SQL Server provisionado con el usuario de
  privilegios acotados para este servicio. El ítem #9 no puede cerrarse sin ambos, y ninguno se
  resuelve en este repositorio.

- **Costo de arranque del proceso hijo sin medir.** El ADR 0012 arranca un proceso por ejecución y
  fuerza `spawn` en las dos plataformas, así que el intérprete reimporta el árbol de módulos con
  pandas adentro en cada petición — también en Linux, donde antes se asumía `fork`. Puede costar
  cientos de milisegundos. Es aceptable contra 15 segundos, pero es una suposición hasta que se mida.

- **`EJECUCIONES_MAX` no tiene todavía un valor fundado.** Es el único parámetro de concurrencia del
  servicio y de él dependen dos cosas opuestas: el techo de memoria agregada y la frecuencia con la
  que un usuario legítimo se come un 503. Calibrarlo exige medir la huella real de `Contado_Carga`
  contra la RAM de la instancia, y esa instancia todavía no existe (ítem #0). Hasta entonces el
  número es una estimación conservadora, no un dato.

- **Ni la saturación ni los fallos del proceso hijo tienen tipo de error.** El vocabulario cerrado
  del ADR 0006 tiene cinco valores pensados para fallos de la entrada del usuario. El 503 por
  saturación, la muerte del hijo por memoria y el timeout de ejecución no son ninguno de ellos: no
  son culpa del archivo y no hay nada que el usuario pueda corregir. Mapearlos a `tamano` o
  `contenido` — como hacía la versión original del ADR 0012 — le diría al usuario que su archivo es
  demasiado grande cuando lo que pasó fue que el servicio se quedó sin memoria, y ensuciaría la
  analítica del portal con `error_tamano` falsos. El ADR 0012 decidió **no** inventar tipos nuevos,
  porque el vocabulario lo fijó un ADR heredado. Sumado al hueco de `cantidad` y `clave_inexistente`,
  son cinco situaciones que llegan al portal sin destino definido, y todas aterrizan en el ítem #10.

- **El espejo de SQLAlchemy se desactualiza en silencio.** Cada migración de Prisma en el portal
  puede romper la lectura acá. El chequeo de arranque contra el registry mitiga parte del problema —
  consulta la tabla al iniciar, así que una columna renombrada o eliminada falla antes de recibir
  tráfico — pero **no es una verificación de esquema**: solo toca los campos que esa consulta usa. Un
  cambio en una columna que el chequeo no lee sigue manifestándose recién en tiempo de ejecución.

- **La paridad byte a byte y el endurecimiento obligatorio de `Contado_Carga` pueden ser
  incompatibles.** El PRD exige que la salida coincida byte a byte con la del script actual y, al
  mismo tiempo, que el módulo migrado deje de descartar filas en silencio, falle con cero filas
  procesadas y lea columnas por nombre. Si alguno de los tres pares reales contiene una fila que el
  script viejo descartó sin avisar, el módulo migrado —haciendo exactamente lo correcto— va a
  producir una salida distinta a la esperada. El manifiesto de procedencia del ADR 0015 documenta
  cómo se generó cada salida, pero no declara qué comportamiento representa. **Hay que revisar los
  tres pares y confirmar que no contienen descartes antes de congelar sus hashes**; si alguno los
  contiene, hay que decidir explícitamente cuál de los dos requisitos manda.

- **Los otros dos procesadores reales del ítem #12 siguen sin reglas de negocio documentadas.** No
  bloquean nada: el pipeline (#9), el fixture (#11) y `Contado_Carga` avanzan sin ellos. Se relevarán
  más adelante.
