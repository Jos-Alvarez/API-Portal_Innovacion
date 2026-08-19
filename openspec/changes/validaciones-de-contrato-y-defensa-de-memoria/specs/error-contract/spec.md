# Delta for Error Contract

## Purpose

BACKLOG item #7 (`validaciones-de-contrato-y-defensa-de-memoria`). `ContextoTamano`'s existing
three-field shape (ADR 0014, fixed verbatim) is unchanged and stays the single-file case. A
total-sum size violation has no single offending `archivo`, so a new sibling context shape is added
rather than stretching `ContextoTamano`. `TipoError`'s five-value enum (ADR 0014) is unchanged — no
sixth value is introduced.

Out of scope: any new `TipoError` member, any change to `ContextoFormato`/`ContextoContenido`/
`ContextoCantidad`/`ContextoClaveInexistente`, the request-validation-error handler (already
shipped).

## ADDED Requirements

### Requirement: A total-sum size violation uses a dedicated context shape
When every individual file passes its own size check but the batch's summed bytes exceed
`tamano_max_total_bytes`, the route MUST raise `ErrorTamano` via a new `ErrorTamano.total()`
classmethod, still carrying `tipo: "tamano"` and status 422, with `contexto` shaped as
`ContextoTamanoTotal = {archivos: list[str], limite_bytes: int, recibido_bytes: int}` — a new
sibling `TypedDict` joined into the `Contexto` union, not `ContextoTamano`. `recibido_bytes` MUST be
a real sum on either path: the summed tracked `carga.size` values when the pre-copy pass fires, or
the summed actually-copied bytes when the measured pass does. `archivos` MUST list every file the
sum was taken over.

#### Scenario: Total-sum violation carries the new context shape
- GIVEN a batch whose individual files each pass but whose summed bytes exceed
  `tamano_max_total_bytes`
- WHEN the response is inspected
- THEN `tipo` is `"tamano"`, status is 422, and `contexto` matches `ContextoTamanoTotal`
  (`archivos`, `limite_bytes`, `recibido_bytes`), never `ContextoTamano`'s `archivo` field

### Requirement: The single-file tamano shape is unchanged
`ContextoTamano`'s three fields (`archivo`, `limite_bytes`, `recibido_bytes`) MUST remain exactly
as ADR 0014 fixed them, for all three single-file cases: the pre-copy tracked-size rejection, the
mid-stream bounded-copy abort, and the declared-uncompressed-size check.

#### Scenario: Single-file cases keep the verbatim shape
- GIVEN a pre-copy tracked-size rejection, a mid-stream size abort and a declared-uncompressed-size
  rejection
- WHEN each response's `contexto` is inspected
- THEN both match `ContextoTamano` exactly, with no added or removed field

### Requirement: The closed enum gains no member
`TipoError` MUST remain exactly the five values fixed by ADR 0014; the total-sum and
declared-uncompressed-size cases both map to the existing `tamano` value, never a new one.

#### Scenario: No sixth value appears
- GIVEN every error condition this change introduces
- WHEN each response's `tipo` is inspected
- THEN it is always one of the existing five values, never a new one
