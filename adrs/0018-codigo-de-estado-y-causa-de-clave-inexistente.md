# ADR 0018: Código de estado y causa de `clave_inexistente`

## Estado

Aceptado

## Contexto

ADR 0014 define el vocabulario cerrado de errores tipificados y fija la forma de `contexto` para
`tamano`, pero para `clave_inexistente` solo dice *"un código de error de servidor"*, sin nombrar un
código concreto.

TECH-DESIGN.md exige, además, que la desincronización entre el registry en memoria y la base de
datos (el procesador existe en uno pero no en el otro) sea distinguible de "el procesador
directamente no existe". ADR 0014 cierra el enum en cinco valores y `clave_inexistente` ya es uno de
ellos, así que esa distinción no puede resolverse añadiendo un sexto `tipo` sin reabrir el enum que
este mismo ADR declara cerrado.

## Decisión

1. `clave_inexistente` responde **HTTP 500**.
2. La distinción de causa vive en `contexto.causa`, un literal cerrado, con `tipo` sin cambios para
   ambas causas:
   - Fila ausente/inactiva en la base de datos: `causa` es `"fila_ausente"` o `"fila_inactiva"`.
   - Desincronización registry↔base de datos: `causa` es `"no_en_registry"` o `"no_en_bd"`.

`clave_procesador` y `causa` son las únicas claves de `contexto` en ambos casos; solo el dominio
cerrado de `causa` distingue una variante de la otra.

## Alternativas consideradas

- **HTTP 503** -- se descartó porque el ítem #8 (admisión acotada) reserva 503 para saturación.
  Compartirlo con `clave_inexistente` borraría la distinción del portal entre "reintenta más tarde"
  (503, ítem #8) y "esto no existe y reintentar no cambia nada" (500, este ADR).

- **Un sexto valor de `tipo`** -- se descartó porque ADR 0014 cierra el enum en cinco valores, y un
  caso adicional por cada causa no accionable inflaría un vocabulario que ya distingue *contenido* de
  las peticiones, no orígenes internos de una falla de configuración/datos.

## Consecuencias

- Este ADR cierra el requisito de distinguibilidad de TECH-DESIGN para `clave_inexistente`, **no**
  H-05 en su totalidad: la indisponibilidad de la base de datos (ADR 0013) y la muerte o el timeout
  de un proceso hijo (ADR 0012) siguen exactamente tan sin resolver como los registra
  `REVISION-ADVERSARIAL.md`, y el propio texto de H-05 dice que no puede resolverse solo desde este
  repositorio.
- El ítem #11 (chequeo de arranque registry↔base de datos) emite `no_en_registry`/`no_en_bd` a través
  de esta misma forma de `contexto`.
- Dos obligaciones quedan heredadas por el ítem #6 (o por el primer ítem que embarque una ruta con
  cuerpo o autenticación), y no las resuelve este cambio:
  1. `registrar_manejador_401(app)` todavía no se cablea en producción; quien embarque la primera
     ruta de procesador con `Depends(exigir_token)` debe también llamarlo en `crear_app()`.
  2. El manejador por defecto de `RequestValidationError` de FastAPI sigue activo y sigue filtrando:
     devuelve 422 con `{"detail": [...]}` -- estructuralmente distinto de `{"tipo", "contexto"}` -- y
     hace eco de `input` sin filtrar, la misma clase de fuga que los ítems #1 y #2 cerraron cada uno
     en su alcance. Hoy no está vivo (ninguna ruta embarcada declara un cuerpo), pero el ítem #6 debe
     decidir explícitamente: sobrescribirlo, acotarlo, o cerrarlo de otra forma.
