# ADR 0015: Fixtures de paridad fuera del repositorio, con manifiesto de procedencia

## Estado

Aceptado

## Contexto

El PRD exige validar cada procesador real contra **3 pares reales de entrada/salida**, preparados
antes de escribir la lógica de negocio, comparando el TXT **byte a byte** (para cubrir codificación y
fin de línea) y el Excel por contenido normalizado. Esa decisión está tomada y no se reabre: sin
fixtures reales, "el servicio produce lo mismo que el script" es una opinión.

Lo que quedaba abierto es **dónde viven esos archivos**. No es una cuestión de organización: los
pares de `Contado_Carga` son extractos financieros reales de Lima Expresa — importes, referencias,
cuentas contables y las diez plazas de `MAPEO_PLAZAS`. Versionarlos los deja en el historial de Git
de forma permanente, replicados en cada clon y cada runner de CI; un borrado posterior no los quita
del historial.

Una sutileza técnica condiciona cualquier alternativa basada en anonimizar: el volcado del TXT
formatea cada celda según su **tipo y magnitud** — `round(abs(importe), 2)` para los montos, y una
rama especial que imprime sin decimales los números mayores a `1000000000` por asumir que son
identificadores. Alterar la escala de un valor al anonimizarlo **cambia la salida esperada**, y el
fixture deja de probar lo que se creía que probaba.

Hay una segunda pregunta que el `sha256` no responde. Un hash prueba que el archivo **no cambió**;
no dice **de dónde salió**, y en una prueba de paridad eso es la mitad del valor. La salida esperada
la produjo `Contado_Carga.py` en la máquina de alguien, en una fecha, sobre una plataforma — y el
propio Technical Design ya registra que el fin de línea del TXT **se hereda hoy de la plataforma**:
el mismo script emite CRLF en Windows y LF en Linux. Un fixture sin procedencia no permite
distinguir "esta es la salida correcta" de "esta es la salida que dio la máquina de quien lo
generó". Con un equipo de una persona no hay revisor externo que atrape esa diferencia, así que
tiene que quedar escrita en el artefacto.

## Decisión

Los pares reales viven **fuera del repositorio**, en un recurso compartido interno, y el repositorio
guarda únicamente un **manifiesto** con sus nombres, sus `sha256` esperados y **la procedencia de
cada salida esperada**.

```
repo/
  tests/paridad/
    manifiesto.toml          # nombres + sha256 + procedencia de cada par
    test_contado_carga.py

fuera del repo:
  \\servidor\innovacion\fixtures\contado_carga\
    01_entrada.xlsx  01_salida.xlsx  01_salida.txt
    02_...           03_...
```

- La ubicación se resuelve por **variable de entorno** (`FIXTURES_PARIDAD`).
- **El manifiesto es parte del contrato de la prueba.** Antes de comparar, el test verifica el
  `sha256` de cada fixture contra el manifiesto: si alguien reemplazó o "arregló" un archivo de
  referencia, la prueba falla por hash, no por contenido. Esto es lo que sostiene la regla del PRD de
  que los tres pares pasan y **ninguno se ajusta para que pase**.
- **Cada par declara su procedencia, y es obligatoria.** Un hash sin procedencia dice que el archivo
  no cambió, no que sea la salida correcta. El manifiesto registra, por par:

```toml
[[contado_carga.pares]]
id             = "01"
entrada        = { archivo = "01_entrada.xlsx", sha256 = "…" }
salida_xlsx    = { archivo = "01_salida.xlsx",  sha256 = "…" }
salida_txt     = { archivo = "01_salida.txt",   sha256 = "…" }

  [contado_carga.pares.procedencia]
  generado_por     = "Contado_Carga.py"
  version_script   = "sha256:…"          # del .py exacto que produjo esta salida
  generado_el      = "2026-08-14"
  generado_en      = "Windows Server 2019 / Python 3.11.9"
  fin_de_linea     = "CRLF"              # observado, no asumido
```

- **`version_script` es un `sha256` del `.py`, no un número de versión.** El script manual no está
  versionado y no hay etiqueta que citar; el hash del archivo que efectivamente corrió es el único
  identificador que no se puede confundir ni recordar mal.
- **`generado_en` y `fin_de_linea` son parte de la procedencia, no decoración.** El Technical Design
  registra que el fin de línea del TXT hoy se hereda de la plataforma; sin estos dos campos, el día
  que la comparación byte a byte falle nadie va a poder distinguir un cambio de comportamiento del
  módulo de un cambio de plataforma de generación.
- **En CI, la ausencia de fixtures es un fallo, no un salto.** Un test que se saltea en silencio es
  peor que no tenerlo: da luz verde sin haber probado nada. Solo el entorno de desarrollo local puede
  saltear la prueba, y con un aviso explícito en la salida.
- **Un par sin bloque de procedencia completo también es un fallo**, en CI y en local. Si el
  manifiesto acepta pares a medias, la exigencia se degrada a una convención y vuelve el problema que
  vino a resolver.
- Actualizar un fixture es una operación deliberada: se reemplaza el archivo en el recurso compartido
  **y** se actualizan su hash **y su procedencia** en el manifiesto, en un cambio revisable. Cambiar
  un hash sin tocar la procedencia es la señal exacta de que alguien ajustó el archivo de referencia
  para que la prueba pasara.

## Alternativas consideradas

- **Versionar los tres pares dentro del repositorio** — sería lo más simple y lo más reproducible:
  clonar y correr, sin configuración ni accesos que gestionar, y la prueba de paridad quedaría tan
  robusta como cualquier otra. Se descartó porque deja importes y cuentas contables reales en el
  historial de Git de forma **irreversible**, replicados en cada máquina y cada runner, y viajando
  con el repositorio si alguna vez cambia de alojamiento. El costo de conveniencia no justifica una
  exposición permanente que no se puede deshacer.

- **Derivados anonimizados en el repositorio, con los reales fuera para una verificación manual
  previa al despliegue** — permitiría una CI completa sin cifras reales. Se descartó por dos motivos:
  la anonimización tendría que preservar tipo y magnitud de cada valor para no alterar la salida
  esperada (ver Contexto), lo que la vuelve un procedimiento frágil que alguien debe mantener
  correcto indefinidamente; y crea **dos juegos de fixtures que pueden divergir**, con el riesgo de
  que la CI pase en verde contra los anonimizados mientras los reales fallan.

## Consecuencias

- **Cero datos financieros en el historial de Git.** El repositorio se puede mover, clonar o
  publicar internamente sin arrastrar cifras de la empresa.
- La verificación por `sha256` levanta una barrera contra el peor fallo de esta clase de pruebas:
  ajustar el archivo de referencia hasta que la prueba pase. **Es una barrera procedimental, no
  técnica**, y conviene decirlo con todas las letras: con un equipo de una persona, regenerar la
  salida con el código nuevo y actualizar el hash en el mismo cambio es un solo paso y no hay
  revisor que lo frene. Lo que agrega la procedencia es que ese paso deja de ser invisible — para
  hacerlo hay que escribir a mano una fecha, una plataforma y el hash de un script, y eso obliga a
  mirar de frente lo que se está haciendo.
- **La salida esperada queda atada al artefacto que la produjo.** Cuando la comparación byte a byte
  falle dentro de seis meses, el manifiesto responde la primera pregunta del diagnóstico — con qué
  script, en qué plataforma y con qué fin de línea se generó esto — en lugar de dejarla a la memoria
  de alguien.
- Actualizar un fixture deja rastro revisable en el manifiesto, con la conversación que corresponde.
- **Costo real:** generar un par ahora tiene un procedimiento que hay que seguir y documentar en el
  README — calcular dos hashes, anotar plataforma y fin de línea observado — en lugar de copiar tres
  archivos a una carpeta. Es fricción deliberada en el único momento en que la prueba puede
  corromperse.
- **Hueco que la procedencia no cierra:** el manifiesto documenta **cómo** se generó la salida
  esperada, pero no declara **qué comportamiento representa**. Los tres puntos de endurecimiento
  obligatorio del PRD (reportar descartes, leer columnas por nombre, fallar con cero filas) hacen que
  el módulo migrado produzca, a propósito, una salida distinta a la del script viejo para cualquier
  entrada que contenga una fila descartada en silencio. Mientras eso no se resuelva, un par puede
  tener procedencia impecable y aun así codificar un comportamiento que la migración viene a
  corregir. Queda registrado como riesgo abierto en el Technical Design.
- **Costo real:** las pruebas de paridad **no corren recién clonado el repositorio**. Quien se sume
  al proyecto necesita acceso al recurso compartido y la variable configurada, y eso hay que
  documentarlo en el README o se convierte en conocimiento tribal.
- **Costo real:** aparece una dependencia de infraestructura para poder probar. Si el recurso
  compartido no está disponible, la CI falla — que es el comportamiento correcto, pero significa que
  la disponibilidad de ese recurso ahora bloquea despliegues.
- **Costo real:** el repositorio ya no es autocontenido. La reproducibilidad histórica depende de que
  esos archivos sigan existiendo y sin cambios; el manifiesto detecta la alteración, pero no la
  desaparición. Conviene que el recurso compartido tenga respaldo.
- La misma mecánica sirve para los otros dos procesadores reales del ítem #12 cuando lleguen sus
  reglas de negocio: un directorio y una sección de manifiesto por procesador.
