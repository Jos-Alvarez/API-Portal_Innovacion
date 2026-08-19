# Error Contract Specification

## Purpose

BACKLOG item #3, authority ADR 0014: a closed, machine-readable typed-error vocabulary the service
raises, serialized by a class-keyed handler as `{"tipo", "contexto"}`. New domain — no prior
`openspec/specs/error-contract/spec.md`.

Out of scope: `Procesador` ABC/registry (#4), SQL Server mirror (#5), temp-file lifecycle (#6)
including wiring `registrar_manejador_401` and the `RequestValidationError` 422 collision (both
recorded here as inherited obligations for #6, not solved by it), contract validations (#7),
bounded admission (#8), packaging (#9), the pipeline (#10), registry↔database check (#11). No
requirement here changes `app/core/configuracion.py` or `app/core/seguridad.py`.

## Requirements

### Requirement: Closed error vocabulary
The `tipo` field MUST take exactly one of five values: `formato`, `tamano`, `contenido`,
`cantidad`, `clave_inexistente`. No other value MUST ever appear.

#### Scenario: Only vocabulary members appear
- GIVEN each of the six error conditions raised via the test-only router (five types, two
  `clave_inexistente` causes)
- WHEN the responses are inspected
- THEN `tipo` is always one of the five closed values, never any other

### Requirement: Error envelope shape
Every typed error response MUST be a JSON object with exactly two top-level keys, `tipo` (string)
and `contexto` (object). This MUST NOT be Starlette's default `HTTPException` body
(`{"detail": ...}`).

#### Scenario: Envelope has exactly two keys, not the default shape
- GIVEN any of the six error conditions
- WHEN the response body is inspected
- THEN it contains exactly `tipo` and `contexto`, and no `detail` key

### Requirement: contexto contains no composed prose
Every field inside `contexto` MUST be a number, a raw string copied verbatim from the request or a
database row, or a member of a closed literal enum defined by the service. No field MAY be a
sentence, phrase, or any string assembled by the service for a human reader.

#### Scenario: No assembled text in any contexto
- GIVEN the `contexto` payload for each of the six error conditions
- WHEN each field is inspected
- THEN none is service-composed text; each is a raw value or closed enum member

### Requirement: contexto shape and status code are fixed per type

| tipo | contexto | Status |
|---|---|---|
| `formato` | `{archivo: str, formato_recibido: str, formatos_aceptados: list[str]}` | 422 |
| `tamano` (ADR 0014, fixed verbatim) | `{archivo: str, limite_bytes: int, recibido_bytes: int}` | 422 |
| `contenido` | `{archivo: str, motivo: "columna_faltante"\|"cero_filas", columna: str\|None}` | 422 |
| `cantidad` | `{minimo: int, maximo: int, recibido: int}` | 422 |
| `clave_inexistente` (fila) | `{clave_procesador: str, causa: "fila_ausente"\|"fila_inactiva"}` | 500 |
| `clave_inexistente` (desync) | `{clave_procesador: str, causa: "no_en_registry"\|"no_en_bd"}` | 500 |

For `contenido`, `columna` MUST be populated only when `motivo` is `"columna_faltante"`; it MUST
be `None` for `"cero_filas"`. Both `clave_inexistente` rows share `tipo: "clave_inexistente"` and
distinguish their cause only through `causa`, never a sixth `tipo` value.

#### Scenario: Each condition returns its documented shape and status
- GIVEN each of the six error conditions raised via the test-only router
- WHEN the response is inspected
- THEN its status and `contexto` fields match exactly the row above for that condition/cause

#### Scenario: contenido's columna reflects the motivo
- GIVEN the content-rejection condition raised once with `motivo: "columna_faltante"` and once with
  `"cero_filas"`
- WHEN `contexto.columna` is inspected in each response
- THEN it is the missing column name in the first case and `None` in the second

### Requirement: Contract proven via a test-only router
A test-only router MUST exercise all six error conditions and assert their documented status and
`contexto` shape. It MUST NOT be wired into the shipped `crear_app()`.

#### Scenario: Test-only routes absent from the shipped app
- GIVEN the shipped `crear_app()`
- WHEN its registered routes are inspected
- THEN none of the test-only error-triggering routes are present

> **Requirement removed on 2026-08-18.** This slot held "Shipped application route set is
> unchanged", worded as *"**This change** MUST NOT add any route…"* with a scenario comparing
> `crear_app()` *"before and after **this change**"*. That wording was correct inside the originating
> change's delta, where "this change" had a referent. Promoted into this permanent domain spec it
> refers to nothing, and read as a standing invariant it became **false** when
> `borde-de-autenticacion-y-errores-http` deliberately added the `/interno` authentication mount.
>
> It was an assertion about one change's diff, not a property of this domain. The living invariant is
> `service-token-auth`'s "Shipped application route set changes deliberately, for the authentication
> boundary only", which names the current surface and is pinned by a test. Do not restore this
> requirement here.

### Requirement: Local ADR 0018 documents the two status/contract decisions
This change MUST add `adrs/0018-*.md`, MADR format matching `adrs/0011`-`0017`, neutral
professional Spanish, documenting: (1) `clave_inexistente` maps to HTTP 500, rejecting 503
(reserved by item #8 for saturation); (2) registry↔database desync distinguishability resolved via
`contexto.causa` rather than a sixth `tipo` value, rejecting the wider enum. It MUST state
explicitly that this closes TECH-DESIGN's distinguishability requirement, not H-05 in full.

#### Scenario: ADR present with required content
- GIVEN this change is complete
- WHEN `adrs/0018-*.md` is inspected
- THEN it exists in MADR format and documents both decisions, their rejected alternatives, and the
  H-05 honesty boundary

### Requirement: Request validation failures are answered outside ADR 0014's vocabulary
A `RequestValidationError` raised during request parsing or validation MUST be answered by a handler
registered inside `crear_app()` with **422 and an empty body**. It MUST NOT return FastAPI's default
`{"detail": [...]}`, and the response MUST contain neither the value the client submitted nor the
service token.

It MUST NOT carry ADR 0014's `{"tipo", "contexto"}` envelope either.

**Amended after the design phase.** An earlier draft of this requirement demanded the typed envelope.
That is not satisfiable: ADR 0014's vocabulary is closed at five values — `formato`, `tamano`,
`contenido`, `cantidad`, `clave_inexistente` — and every one of them describes a *content* failure a
processor found in a file it could read. A `RequestValidationError` is a request whose shape never
parsed; it never reached the content layer. `cantidad` comes closest and still does not fit, because
its `contexto` carries `minimo`/`maximo` from the processor contract, which an exception handler at
this layer does not have.

The shipped `error-contract` spec states that no `tipo` other than the five MUST ever appear, so
inventing a sixth is barred. An empty body follows ADR 0017's existing precedent, where the 401 was
deliberately kept outside the enum and answered with no body at all: a status that says "this request
is unusable" without claiming a vocabulary that does not describe it. ADRs outrank a spec draft, so
the requirement is amended rather than the ADR bent.

#### Scenario: Malformed body is rejected with an empty 422
- GIVEN a route with a declared request body, protected by the service-token dependency
- WHEN a request carrying a valid token is sent with a body that fails validation
- THEN the response status is 422, its body is empty, and it contains neither `detail` nor `tipo`

#### Scenario: The rejection leaks neither the submitted value nor the token
- GIVEN the same request, carrying a distinctive sentinel value in the body
- WHEN the full response, including its headers, is inspected
- THEN neither the sentinel nor the service token appears anywhere in it

#### Scenario: Handler is active in the shipped application
- GIVEN the shipped `crear_app()`
- WHEN it is constructed
- THEN a handler for `RequestValidationError` has been registered before the app is returned

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
