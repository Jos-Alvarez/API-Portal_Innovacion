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

### Requirement: Shipped application route set is unchanged
This change MUST NOT add any route to the shipped `crear_app()`. The route set MUST be identical
before and after this change.

#### Scenario: Shipped route set unchanged
- GIVEN the shipped `crear_app()` before and after this change
- WHEN their route sets are compared
- THEN they are identical

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
