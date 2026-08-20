# ADR 0023: Cero salidas y fallas de empaquetado — dos lados del vocabulario tipificado

## Estado

Aceptado

## Contexto

El ítem #9 construye `app/core/empaquetado.py`, el módulo que ADR 0011 nombra en su mapa de `core/`
("ZIP si hay más de una salida") y que TECH-DESIGN.md ubica como el paso 8 del pipeline. Su trabajo
es convertir la `list[ArchivoSalida]` que devuelve `ejecutar_modulo` (ítem #8, ADR 0022) en una única
`ArchivoSalida`: la entrada misma si hay una sola, o un ZIP plano recién escrito si hay dos o más.

Ese módulo tiene dos fallas propias, y ninguna de las dos tenía un lugar obvio en el vocabulario ya
embarcado.

**Primera: cero salidas.** El BACKLOG la asigna sin ambigüedad a `TipoError.CONTENIDO` — 422, no
500 —, y PRD.md refuerza el porqué: *"no es un error del sistema, pero el portal necesita
distinguirlo del éxito normal: debe llegar como error de contenido, no como ZIP vacío"*. Lo que no
estaba decidido es la **forma** del `contexto`, y la forma embarcada no encaja:

- `ContextoContenido` exige `archivo: str`. En el punto de falla, el empaquetado sostiene una lista
  **vacía** de `ArchivoSalida` y nunca ve un `ArchivoEntrada`: no tiene literalmente ningún nombre de
  archivo en alcance. Sólo un centinela (`""`, `"(salida)"`) cabría en ese campo.
- `motivo` es un `Literal` cerrado de dos valores, y uno de ellos —`"cero_filas"`— ya existe y
  *parece* aplicable. No lo es: se acuñó en el ítem #3 con la semántica de filas de `Contado_Carga`
  (ítem #16, todavía sin construir). "No hay filas válidas en el origen" y "el módulo no devolvió
  ningún archivo" son hechos distintos: un procesador que filtra puede tener filas y aun así no
  producir archivos.

ADR 0021 ya enfrentó exactamente esta forma del problema del lado de la entrada — una violación del
límite **total** del lote no tiene un `archivo` culpable — y la resolvió con una forma hermana en la
unión `Contexto` (`ContextoTamanoTotal`) en lugar de un centinela en un campo de texto libre, dejando
`ContextoTamano` intacto y el enum en cinco valores.

**Segunda: nombres duplicados o degenerados entre las salidas de una misma llamada.**
`nombre_propuesto` lo escribe código de primera parte —el procesador de los ítems #12/#16—, no el
cliente, a diferencia de `nombre_original` en `ArchivoEntrada`. Dos hechos verificados contra el
CPython 3.12 instalado, no recordados, gobiernan la decisión:

- **V1 — la normalización de `arcname` que hace `zipfile` es parcial, no una defensa.**
  `ZipInfo.from_file` aplica `os.path.normpath(os.path.splitdrive(arcname)[1])` y después quita los
  separadores **iniciales**. `normpath` colapsa un `a/../b` interior pero conserva un `..` inicial,
  así que `"../../x.txt"` sobrevive como escape relativo dentro del archivo comprimido; y un
  `arcname` de `"/"` queda vacío tras el bucle de recorte, con lo que la siguiente iteración de
  `while arcname[0] in ...` levanta `IndexError` (`zipfile/__init__.py:563-569`).
- **V2 — un `arcname` duplicado no falla.** `_writecheck` emite `warnings.warn('Duplicate name: %r')`
  y escribe el miembro igual; quedan las dos entradas y la extracción se queda con la última
  (`zipfile/__init__.py:1782-1786`). Nada en esta suite convierte advertencias en errores
  (`pyproject.toml` no fija `-W error`), así que en la práctica la pérdida sí es silenciosa.

## Decisión

- **Cero salidas usa una forma hermana, no un `motivo` ampliado.** `ContextoSinSalidas`
  —`{motivo: Literal["sin_salidas"]}`— entra en la unión `Contexto` como hermano de
  `ContextoContenido`; `ErrorContenido.contexto` pasa a `ContextoContenido | ContextoSinSalidas` y la
  clase gana una clasificadora `sin_salidas()`, mismo patrón que `ErrorTamano.total()` y
  `ErrorContenido.columna_faltante`. Sigue siendo `TipoError.CONTENIDO` → 422: `_ESTADO_HTTP` no se
  toca y **el enum sigue teniendo exactamente cinco miembros**. Lo que ADR 0014 cerró es el conjunto
  de miembros del enum; las cargas de contexto nunca estuvieron en ese alcance, como ADR 0021 ya
  registró una vez.
- **`"cero_filas"` no se reutiliza.** Su semántica es de nivel de fila del origen y pertenece al
  ítem #16. Forzarla acá haría que el portal —que redacta el banner a partir de `motivo`, ADR 0014—
  afirmara algo falso sobre los datos del usuario.
- **La forma lleva exactamente un campo, y ese campo es el discriminante.** `motivo` ya es la clave
  por la que el portal se ramifica en los dos casos embarcados de `contenido`, así que la forma nueva
  extiende la ramificación existente en vez de introducir una segunda. No se agrega
  `clave_procesador`: el portal ya sabe cuál llamó, está en la URL. No se agrega un conteo: la lista
  está vacía y ningún campo del contrato declara una cantidad esperada de salidas. A diferencia de
  `ErrorTamano.total()`, `sin_salidas()` no recibe argumentos, así que no hay ningún placeholder que
  sobrescribir y ningún estado intermedio inválido que pueda observarse.
- **Duplicados y nombres degenerados levantan `SalidaMalFormada`, que no es un `ErrorTipificado`.**
  ADR 0014 describe los cuatro tipos de 422 como *"los cuatro tipos que el usuario puede provocar y
  corregir"*; el cliente no puede provocar ni corregir un `nombre_propuesto` duplicado, porque no lo
  escribe. ADR 0018 ya mandó el único caso no corregible —`CLAVE_INEXISTENTE`— a un código de error
  de servidor en vez de a un 422, y ADR 0022 fijó la forma para "no es un `TipoError`; el ítem #10
  traduce": `FalloDelModulo`, `EjecucionExpirada`, `HijoMuerto`. Esta falla sigue 0018/0022, no 0014.
- **Las dos fallas del módulo quedan a lados opuestos del vocabulario tipificado a propósito.** Cero
  salidas es un hecho sobre los **datos del cliente**, que el BACKLOG pone explícitamente en el
  vocabulario que el cliente ve; un nombre duplicado es un hecho sobre **nuestro** código, sobre el
  que el cliente no puede hacer nada. La asimetría es la decisión, no un descuido.
- **El `arcname` se aplana siempre, y un nombre degenerado levanta en vez de recibir un respaldo.**
  El aplanado es manipulación de texto —`replace("\\", "/")` más `rpartition("/")`—, nunca
  construcción de un `Path`, siguiendo la regla que `app/recepcion.py` ya enuncia verbatim para el
  lado de la entrada. V1 muestra que esto no es redundante con la biblioteca estándar. Un resultado
  de `""`, `"."` o `".."` levanta `SalidaMalFormada`: inventar un nombre de respaldo renombraría un
  archivo en silencio y podría colisionar a su vez.

## Alternativas consideradas

- **Reutilizar `ErrorContenido.cero_filas(archivo=...)` con un centinela en `archivo`.** Rechazada
  sobre precedente propio: ADR 0021 rechazó exactamente ese movimiento para `ContextoTamano.archivo`
  porque *"codifica un segundo significado en un campo de texto libre y rompe por convención la forma
  que ADR 0014 fija por tipo"*. El argumento no cambia por estar del lado de la salida.
- **Agregar un tercer valor al `Literal` cerrado y conservar la forma de tres campos.** Resuelve la
  mitad semántica —el motivo diría la verdad— y deja intacta la mitad estructural: `archivo` seguiría
  exigiendo un valor que no existe. Rechazada por resolver medio problema.
- **Agregar `clave_procesador` a `ContextoSinSalidas`.** Rechazada: obligaría a pasar la clave a una
  función pura sólo para devolverla, y el portal ya la conoce.
- **Un `TypedDict` vacío.** Rechazada: perdería el discriminante `motivo` que el portal ya usa para
  ramificar dentro de `contenido`, y obligaría a distinguir las formas por ausencia de campos.
- **`SalidaMalFormada` como un `ErrorTipificado` de contenido (422).** Rechazada: le diría al cliente
  que cometió un error corregible cuando el error es nuestro, y ADR 0018 ya fijó que esa distinción
  la lleva el código de estado.
- **`SalidaMalFormada` como subclase de `FalloDeEjecucion` (ADR 0022).** Rechazada sobre semántica,
  no sobre costo de importación —que no existe, porque `app/core/errores.py` ya importa `starlette`—:
  el hijo corrió bien, esto no es una falla de ejecución, y un `except FalloDeEjecucion` amplio del
  ítem #10 tragaría un bug de empaquetado como si el módulo se hubiera caído. Además mantiene el paso
  8 sin ninguna dependencia del paso 7, así que cualquiera de los dos se revierte solo. Precedente:
  `ServicioSaturado` es una `Exception` suelta dentro de `ejecucion.py` por la misma razón.
- **Tolerar duplicados con el comportamiento de `zipfile` (*last-write-wins*).** Rechazada: V2
  muestra que la pérdida es efectivamente silenciosa en esta suite, y perder una salida en silencio
  es peor que fallar ruidosamente. Es la misma lógica de "o sale la salida completa, o es un error"
  que PRD.md exige para el ZIP a medias.
- **Un sexto valor de `TipoError`.** Rechazada: ADR 0014 cierra el enum y la autoridad heredada
  manda.

## Consecuencias

- **La unión `Contexto` llega a siete miembros y el portal gana una tercera rama de `contenido`.** Es
  un cambio de contrato entre repositorios y hay que tratarlo como tal, exactamente como ADR 0014
  advierte. El fallback que ese ADR ya hace obligatorio en el ítem #10 acota el daño de no
  implementarla a tiempo: el usuario vería el mensaje genérico, no un banner vacío.
- **El patrón "forma hermana" deja de ser una excepción y pasa a ser el mecanismo por defecto** para
  una falla sin culpable único. ADR 0021 lo usó una vez y tuvo que justificar por qué no reabría ADR
  0014; ésta es la segunda. Queda nombrado acá para que una tercera no se discuta desde cero.
- **El costo en `mypy --strict` es cero, y está medido.** La suite ya indexa una unión de dos formas
  por una clave presente en un solo miembro (`tests/test_errores_tipificados.py:275`, sobre
  `ContextoTamano | ContextoTamanoTotal`) con `strict = true` y sin `disable_error_code`, y el gate
  está verde. La forma nueva no necesita `cast` ni `type: ignore`.
- **`SalidaMalFormada` queda sin traducción HTTP hasta el ítem #10**, igual que `FalloDelModulo`,
  `EjecucionExpirada` y `HijoMuerto` (ADR 0022). Si el ítem #10 no la contempla, cae en el manejador
  genérico del framework. Es la misma deuda ya declarada, no una nueva.
- **Un procesador que proponga dos veces el mismo nombre falla la petición entera.** Es deliberado, y
  significa que los ítems #12/#16 deben garantizar nombres únicos entre las salidas de una misma
  llamada. Queda nombrado acá como restricción sobre ellos en lugar de descubierto por uno de ellos.
- **No se introduce ningún techo de tamaño de salida.** No existe hoy un equivalente de
  `PRESUPUESTO_DE_RAM_BYTES` del lado de la salida, `ArchivoSalida` ni siquiera lleva un campo de
  tamaño, y este cambio no inventa uno. Un procesador mal comportado puede producir un ZIP
  arbitrariamente grande dentro del directorio de la petición, acotado sólo por la limpieza de
  `Reserva`. Brecha declarada abierta; si alguna vez se cierra, el techo debe ser un `Final`
  documentado del módulo y no un campo de `ContratoProcesador` — ADR 0021 rechazó esa ubicación una
  vez.
- **`empaquetado.py` no reclama propiedad de ningún temporal.** Borra exactamente el único archivo
  que él mismo creó cuando la escritura falla, y nunca el directorio; no importa nada de
  `app/core/temporales.py` y nunca llama a `ceder_limpieza()`. El único punto de transferencia que
  fija ADR 0020 queda intacto.
- **`openspec/config.yaml:8` sigue desactualizado** ("0011-0015 exist"). Ya lo señalaron el ítem #7 y
  el ítem #8; este registro es el **0023**, verificado contra el contenido real de `adrs/`.
