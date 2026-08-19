# ADR 0021: Validaciones de contrato y presupuesto de memoria

## Estado

Aceptado

## Contexto

`app/recepcion.py` embarcó con una costura explícita — `del entradas  # costura del ítem #7` — y con
el orden invertido: cada archivo subido se copiaba entero al directorio temporal de la petición
**antes** de que nada comparara su cantidad, formato, tamaño o tamaño declarado sin comprimir contra
el contrato del procesador receptor. `ContratoProcesador` (`app/core/contrato.py`) ya llevaba cuatro
límites — `entradas_min`/`entradas_max`, `formatos_aceptados`, `tamano_max_bytes`,
`tamano_max_total_bytes` — sin ningún punto de aplicación en el código.

Dos hallazgos de `REVISION-ADVERSARIAL.md` tocan esta costura:

- **H-04 (Crítico, abierto)**: ADR 0006 afirma que un archivo queda "acotado por el tope de 25 MB
  comprimido". Para un `.xlsx` —XML dentro de un ZIP— eso es falso: el tamaño descomprimido no guarda
  relación fija con el comprimido, y el techo real de memoria lo debe imponer el proceso hijo.
- **H-09 (Advertencia, abierto)**: el cuerpo multipart se procesa por completo antes de que el cuerpo
  de la ruta reciba el control.

Tres hechos verificados contra el código instalado (`starlette==1.6.0`), no recordados, gobiernan las
decisiones de abajo:

- **V1 — `UploadFile.size` es una cuenta medida, no una declaración del cliente.**
  `formparsers.py:232-237` construye cada parte de archivo con `size=0` y
  `datastructures.py:451-454` hace `self.size += len(data)` por cada trozo realmente escrito. Un
  `Content-Length` mentiroso no llega a ese campo. La propuesta de este cambio había justificado la
  copia acotada como defensa contra esa mentira; esa premisa era falsa y quedó corregida.
- **V2 — `max_part_size` nunca se aplica a partes de archivo.** `on_part_data` guarda el techo detrás
  de `if self._current_part.file is None:` (`formparsers.py:181-188`); los bytes de archivo van
  directo a `_file_parts_to_write` sin control alguno.
- **V3 — el recurso sin cota es el disco temporal del sistema operativo, no la RAM.**
  `spool_max_size = 1024 * 1024` acota a 1 MB la huella en memoria de cada parte antes de volcarla a
  `gettempdir()`; `max_files` (1000 por defecto) acota cantidades, no tamaños.

ADR 0014 cierra el vocabulario de errores en cinco valores. Una violación del límite **total** del
lote no tiene un `archivo` culpable, así que no entra limpiamente en `ContextoTamano`, cuya forma de
tres campos ese ADR fija verbatim.

## Decisión

- **Dos fases alrededor de `reservar()`.** La resolución del contrato y las comprobaciones de
  cantidad, formato y tamaño declarado corren **antes** de entrar en `with reservar()`; la copia, la
  medición y la inspección del ZIP corren **dentro**. Una petición rechazada en la fase 1 no cuesta ni
  un `mkdtemp` ni un byte. El diseño del ítem #6 ya había rechazado el middleware ASGI en parte porque
  "crearía un directorio temporal para CADA petición a /interno, incluso las que no suben nada": una
  petición con la clave equivocada o con la cantidad equivocada es exactamente una de ésas.
  `app/core/temporales.py` no se modifica en una sola línea — ésa es la prueba mecánica de que la
  garantía de limpieza del ítem #6 queda intacta.
- **La copia sigue acotada, con la justificación corregida.** `_copiar` recibe `limite_bytes`, corta
  en cuanto la cuenta cruzaría el límite y **cierra el manejador de salida antes de levantar** (en
  Windows, `rmtree` sobre un manejador abierto levanta `PermissionError`, que ADR 0020 sólo tolera
  difiriendo al barrendero). No está para atrapar una mentira de tamaño —V1 muestra que no hay tal
  mentira—, sino porque `carga.size` es `int | None` y la copia es la **única** aplicación cuando vale
  `None`; porque ADR 0020 define `tamano_comprimido` como "bytes que llegaron a disco", y un techo del
  lado del escritor mantiene esa definición cierta por construcción; y porque los ítems #9/#10 son los
  próximos llamadores de esta costura y no deben poder excederse por olvidar la comprobación previa.
- **`app/core/validaciones.py` recibe primitivos, nunca tipos de Starlette.** Cinco funciones puras que
  comparan `str`/`int` contra un `ContratoProcesador` y levantan los errores tipificados ya embarcados.
  Ningún `UploadFile` cruza a `app/core/`: la ruta extrae, el núcleo compara. Así el módulo es
  ejercitable con contratos construidos a mano —imprescindible, porque `_TABLA_CONTRATOS` está vacía— y
  ningún llamador futuro no-multipart (ítem #10) arrastra Starlette consigo.
- **`PRESUPUESTO_DE_RAM_BYTES = 256 MB` como `Final` de módulo**, siguiendo el precedente de
  `UMBRAL_DE_EDAD`/`INTERVALO_DE_BARRIDO` en `temporales.py`, no como campo de `ContratoProcesador`.
  Es una elección con piso fundado, no una cita: `tamano_max_bytes` acota una subida en 25 MB
  comprimidos y un `.xlsx` comprime del orden de 5–20×, así que 250 MB es el techo realista del rango
  legítimo; y 256 MB queda "holgadamente por debajo de la memoria del worker" (ADR 0006). El chequeo
  suma `ZipInfo.file_size` del directorio central, **sin descomprimir nada**. Un archivo que no es ZIP
  y un ZIP corrupto son ambos no-ops deliberados: decidir si un archivo es un `.xlsx` válido es
  validación de **contenido**, y `ContextoContenido.motivo` es `Literal["columna_faltante",
  "cero_filas"]` — inventar un fallo que el vocabulario cerrado no puede expresar es exactamente la
  presión que ADR 0014 existe para resistir.
- **La unión de contextos crece; el enum no.** `ContextoTamanoTotal = {archivos, limite_bytes,
  recibido_bytes}` entra en la unión `Contexto` como hermano de `ContextoTamano`, y `ErrorTamano` gana
  una clasificadora `total()` (mismo patrón que `ErrorContenido.columna_faltante`). Ambos casos siguen
  siendo `TipoError.TAMANO` → 422. Lo que ADR 0014 cerró es el **conjunto de miembros del enum**; las
  cargas de contexto nunca estuvieron en ese alcance.

## Alternativas consideradas

- **`request.form(max_part_size=...)`, soltando la dependencia declarativa `File()`.** Rechazada
  **sobre evidencia**, no diferida: V2 muestra que ese techo no toca las partes de archivo. Adoptarla
  cambiaría la firma embarcada de `recibir()`, perdería el parámetro declarado en OpenAPI y no cerraría
  nada.
- **Un middleware ASGI que cuente bytes crudos en `receive()`.** Diferida. Es el **único** mecanismo
  que puede abortar antes de que el parser escriba algo, y por lo tanto lo único que cierra H-09. Se
  presentó con su costo completo —superficie arquitectónica nueva junto a `AutenticacionDeBorde`, un
  cambio en `app/main.py`, y una pregunta abierta sobre qué error tipificado produce un aborte a mitad
  de flujo— y quedó fuera de alcance por decisión explícita del usuario.
- **Un sexto valor de `TipoError`.** Rechazada: ADR 0014 cierra el enum y la autoridad heredada manda.
- **Un centinela `"(total)"` en `ContextoTamano.archivo`.** Rechazada: conserva una sola forma, pero
  codifica un segundo significado en un campo de texto libre y rompe por convención la forma que ADR
  0014 fija por tipo.
- **Una subclase `ErrorTamanoTotal(ErrorTamano)`.** Rechazada: construcción más limpia, sin marcador de
  posición, pero deja dos clases para un solo `TipoError` frente al patrón de clasificadora ya
  embarcado en este mismo archivo.
- **Un campo de presupuesto de RAM en `ContratoProcesador`.** Rechazada: ADR 0006 trata el techo de
  memoria como asunto del worker, no como valor por procesador, y tocar ese dataclass reabriría el
  módulo de desviación de ADR 0013 sin necesidad operativa conocida.

## Consecuencias

- **H-09 queda declarado abierto**, y el recurso expuesto queda nombrado con precisión: **disco
  temporal del sistema operativo**, no RAM (V3), a lo largo de hasta `max_files = 1000` partes de
  tamaño no acotado. Lo cierra el middleware ASGI o el ítem #8, nunca la alternativa que V2 descarta.
- **H-04 recibe una primera línea de defensa, no un techo.** Un ZIP que declara menos de lo que
  realmente descomprime sigue pudiendo exceder el presupuesto una vez que un procesador lo abra;
  `zipfile` sólo nota la mentira después de descomprimir y verificar el CRC, y la magnitud que agota la
  RAM de verdad es el `DataFrame` de pandas, no el XML crudo. El techo real es del ítem #8.
- **Con `_TABLA_CONTRATOS` vacía, la ruta de producción ya no escribe nada.** Al subir la resolución
  del contrato por encima de la copia, toda petición muere en `ErrorClaveInexistente` antes de la fase
  2. Es el comportamiento correcto —una clave desconocida no debe costar una escritura— pero la
  evidencia de recepción del ítem #6 pasa a depender de un contrato inyectado en pruebas
  (monkeypatch de `_TABLA_CONTRATOS`), no del camino de producción sin ayuda.
- **256 MB se mueve** en cuanto la carga de un procesador real lo contradiga; recién entonces
  promoverlo a `Configuracion` deja de ser especulativo.
- **`ContratoProcesador.activo` sigue sin aplicarse.** El campo existe y `CausaFila` ya contiene
  `"fila_inactiva"`; ambos siguen inalcanzables. Queda nombrado acá en lugar de añadido en silencio:
  el alcance de este cambio enumera exactamente cinco ejes de validación y ése no es uno.
- **La suma descomprimida es por archivo, no por lote.** Ésa es la forma de una bomba ZIP. Es discutible
  recién cuando un contrato acepte más de un archivo; hoy `entradas_max = 1` hace que lote y archivo
  sean lo mismo.
