# ADR 0014: Contrato de errores tipificados — tipo y datos, sin copia de interfaz

## Estado

Aceptado

## Contexto

El backlog fija la dirección del contrato de errores sin ambigüedad: "#9 y #10 comparten el contrato
de errores. El servicio los tipifica y el portal los mapea al `evento_uso` y al banner de la UI.
Definir ese vocabulario de errores en #9 y consumirlo en #10, no al revés."

El vocabulario ya está cerrado por el ADR 0006, con cinco tipos: **formato, tamaño, contenido,
cantidad y clave inexistente**. Lo que faltaba decidir es la **forma concreta** de la respuesta que
viaja del servicio al portal.

La restricción determinante viene de la interfaz: `DESIGN.md` exige "lenguaje claro sin códigos"
para el estado de error, y especifica el banner de procesador como "banner rojo con título 700 +
motivo específico + Reintentar". `DESIGN.md` pertenece al portal, y es la autoridad sobre cómo el
producto le habla al usuario. Si el servicio devolviera texto listo para mostrar, esa autoridad
quedaría partida entre dos repositorios y dos toolchains.

**Hueco detectado y no resuelto por este ADR:** el ADR 0006 mapea `evento_uso` a tres tipos de error
(`error_formato`, `error_tamano`, `error_contenido`) y `DESIGN.md` nombra los mismos tres motivos en
el banner. **`cantidad` y `clave inexistente` no tienen destino definido en ninguno de los dos.** Es
un hueco del lado del portal (ítem #10), no de este servicio, y queda registrado como riesgo abierto
en el Technical Design.

## Decisión

El servicio devuelve un **error tipificado legible por máquina, sin texto de interfaz**: el tipo y
los datos crudos del fallo. El portal redacta el mensaje que ve el usuario.

```
HTTP 422
{
  "tipo": "tamano",
  "contexto": {
    "archivo": "contado_enero.xlsx",
    "limite_bytes": 26214400,
    "recibido_bytes": 31457280
  }
}
```

- **`tipo`** es uno de los cinco valores cerrados del ADR 0006, en un enum del servicio:
  `formato`, `tamano`, `contenido`, `cantidad`, `clave_inexistente`.
- **`contexto`** lleva los datos estructurados del fallo — nombre de archivo, límite, valor recibido,
  columna faltante, cantidad esperada — para que el portal pueda componer un mensaje específico y
  útil sin inventar nada.
- **El servicio no emite texto destinado a un usuario final.** Ni en `tipo`, ni en `contexto`, ni en
  ningún campo adicional. La única redacción que produce el servicio son los logs operativos, que
  nadie muestra en pantalla.
- El código HTTP distingue el fallo del usuario del fallo del sistema: los cuatro tipos que el
  usuario puede provocar y corregir responden **422**; `clave_inexistente`, que es una
  desincronización entre la fila en base de datos y el registry, responde con un código de error de
  servidor, porque no es culpa de quien subió el archivo ni hay nada que pueda hacer al respecto.

## Alternativas consideradas

- **Tipo más mensaje en español ya redactado** — el servicio devolvería el texto listo y el portal lo
  pintaría tal cual, lo que ahorraría código de mapeo en Next.js y haría que un tipo nuevo se
  mostrara sin tocar el portal. Se descartó porque parte la copia de la interfaz en dos repositorios:
  cambiar una palabra de un banner exigiría desplegar el servicio de Python, y `DESIGN.md` dejaría de
  ser la autoridad única sobre el lenguaje del producto. El ahorro de código no compensa perder ese
  límite.

- **RFC 9457 Problem Details** (`application/problem+json` con `type`, `title`, `status`, `detail` y
  extensiones) — es un estándar reconocible, documentado y con herramientas que ya lo parsean. Se
  descartó por dos motivos: es verboso para una API interna con un consumidor único y conocido, y —
  más importante — no responde la pregunta de fondo. Sus campos `title` y `detail` están pensados
  para texto legible por humanos, así que adoptarlo empujaría justamente hacia la alternativa
  anterior, con copia de interfaz viviendo en el servicio.

## Consecuencias

- **`DESIGN.md` sigue siendo la autoridad única de la redacción.** Todo el texto que ve el usuario
  vive en el portal, en un solo idioma de trabajo y un solo repositorio.
- Cambiar el texto de un banner es un cambio en el portal. El servicio no se toca ni se despliega.
- El portal puede componer mensajes mucho más específicos que un texto genérico, porque recibe los
  datos: puede decir qué archivo, qué límite y cuánto pesaba, en lugar de "el archivo es demasiado
  grande".
- El contrato es estable y testeable: cinco valores cerrados en un enum, verificables con una prueba
  que recorre el conjunto completo.
- **Costo real:** el portal necesita implementar un caso por cada tipo, **y un fallback**. Si el
  servicio incorpora un tipo nuevo y el portal no lo contempla, el usuario ve el mensaje genérico o —
  peor, si no hay fallback — un banner vacío. Ese fallback es obligatorio en el ítem #10, no
  opcional.
- **Costo real:** la forma de `contexto` varía según el tipo, así que no es un objeto uniforme. El
  portal tiene que saber qué campos esperar en cada caso, y ese conocimiento es un acoplamiento real
  entre los dos repositorios que ningún tipado automático cubre — son dos lenguajes distintos. Un
  cambio en los campos de `contexto` es un cambio de contrato y hay que tratarlo como tal.
- Dos de los cinco tipos (`cantidad` y `clave_inexistente`) no tienen todavía destino en el
  `evento_uso` ni en el banner de `DESIGN.md`. El servicio los emite igual, porque son parte del
  vocabulario que fijó el ADR 0006; resolver dónde aterrizan es trabajo del ítem #10.
