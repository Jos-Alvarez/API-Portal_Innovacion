# Proposal: Autenticación por token de servicio

## Intent

BACKLOG item #2. PRD: *"Token de servicio obligatorio... Sin token válido, se rechaza con 401 antes
de leer el cuerpo"* and *"...con token vacío, malformado o incorrecto → 401, sin pistas sobre el
token esperado."* Item #1 shipped fail-closed startup and left the auth seam as a comment. This
change makes rejection real: a reusable dependency that closes every 401 path without leaking the
expected token, timing, or which failure mode occurred.

## Scope

### In Scope
- `app/core/seguridad.py`: `exigir_token` dependency — parses `Authorization`, constant-time
  compares, raises 401 with an empty body.
- A **test-only** router/app exercising `exigir_token` (nothing wired into shipped `crear_app()`).
- Tests: every malformed-header variant, constant-time proof, sentinel-absence in logs/output,
  `debug=False` assertion, an access-log header-absence test.

### Out of Scope
- Typed error contract (#3), `Procesador` ABC/registry (#4), SQL Server mirror (#5), temp-file
  lifecycle (#6), contract validations (#7), bounded admission/processes (#8), packaging (#9),
  common pipeline (#10), registry↔DB check (#11). No change to `configuracion.py`'s
  `token_servicio` field (its `min_length=1` floor is load-bearing, per item #1's comment).

## Capabilities

### New Capabilities
- `service-token-auth`: request-level 401 enforcement via `Authorization: Bearer` on
  dependency-scoped routes.

### Modified Capabilities
None.

## Approach

- **Header/scheme**: `Authorization: Bearer <token>` (new decision — unspecified elsewhere).
  Chosen because `Authorization` is commonly redacted by proxies/load balancers/logging stacks by
  default; a custom header name is not.
- **Parsing**: read via `request.headers.get(...)` as a raw string — never a typed/validated
  FastAPI parameter (`request_validation_exception_handler` echoes `input`, which would leak the
  submitted token in a 422 body).
- **"Malformed" enumeration** — all MUST reach 401 indistinguishably: header absent; wrong scheme
  (not `Bearer`); missing space after scheme; empty credential; extra/irregular whitespace;
  non-ASCII bytes; multiple `Authorization` headers. No branch may produce a different status code,
  response body, or header set per case.
- **Scope of the indistinguishability guarantee** (corrected — an earlier draft of this proposal also
  demanded identical wall-clock timing across every branch, which contradicts the deliberate
  short-circuit on an absent header and is not achievable). The guarantee is:
  - **Response shape**: every rejection path produces a byte-identical response — same status, same
    empty body, same headers. This is what stops a caller probing which failure mode it hit.
  - **The comparison itself**: two *different incorrect* credentials must not be distinguishable from
    each other. That is exactly what `hmac.compare_digest` provides, and what a `len()` pre-check
    would destroy.
  - **Explicitly NOT guaranteed**: identical wall-clock time between "no header at all" and "header
    present but wrong". The absent-header path short-circuits before the comparison and is therefore
    measurably faster. That difference leaks nothing — the caller already knows whether it sent a
    header.
  - **How it is proven**: structurally, not by measurement — assert that `compare_digest` is used,
    that no length check precedes it, and that every rejection path returns the same response object.
    A wall-clock timing test is flaky by nature, and a flaky test guarding a security property is
    worse than none, because it ends up muted.
- **Comparison**: `hmac.compare_digest` on bytes; no manual `len()` pre-check; absent header
  short-circuits before comparison (presence isn't secret, content is).
  **Encoding correction** — an earlier draft said "UTF-8 on both sides". That is wrong for the
  presented credential and was corrected after the design phase verified the real behavior:
  Starlette decodes header values as **latin-1**, so the presented credential must be re-encoded with
  latin-1 to recover the exact wire bytes, while the configured token is encoded with UTF-8.
  Re-encoding the presented credential as UTF-8 double-encodes any non-ASCII token — verified:
  `b"clav\xc3\xa9"` on the wire round-trips to `b"clav\xc3\x83\xc2\xa9"` — producing a permanent,
  undiagnosable 401 for a correct token. latin-1 encoding is also total, so it cannot raise and there
  is no 500 path to guard.
- **401 body**: empty (custom `Response`, not `HTTPException`, which always emits `{"detail":...}`).
  **`WWW-Authenticate: Bearer` recommendation: include it.** RFC 7235 says a 401 SHOULD carry it;
  it names only the scheme, already public via this proposal/README, so it adds no leak surface
  while keeping the response HTTP-conformant.
- **Attachment**: `Depends(exigir_token)` on future processor routers only — never global
  middleware with a path allow-list (ADR 0016 precedent).
- **401 stays outside ADR 0014's closed enum** (`formato`/`tamano`/`contenido`/`cantidad`/
  `clave_inexistente`); this change must not force a typed shape onto it.
- **Forward risk, not solved here**: FastAPI's `routing.get_request_handler` reads the request body
  before `solve_dependencies` runs, for both per-route and per-router `Depends`/`dependencies`. No
  route in this change has a body, so it's moot today — but item #6's `UploadFile` routes will need
  raw ASGI/`Mount`-scoped middleware, not `Depends()`, to guarantee zero bytes read pre-auth.
  Recorded as an inherited constraint on #6; not addressed here.
- **New leak surfaces**: app must never be constructed with `debug=True` (Starlette traceback
  renderer); add a test proving Uvicorn's default access log doesn't surface header values.
- **Recommend, don't author here**: a local ADR (0017, next free number after 0011–0016)
  documenting the `Authorization: Bearer` + empty-body decisions, deferred to design/apply.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `app/core/seguridad.py` | New | `exigir_token` dependency |
| `tests/test_seguridad_token.py` (+ test-only router fixture) | New | Full malformed-header matrix, timing, leak, debug, access-log tests |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Distinguishable 401 branches leak failure mode | Med | Single code path → single response for every malformed case; test matrix enforces it |
| `debug=True` or access-log regression later | Low | Explicit test now; regression caught by suite |
| Scope creep toward #6's middleware problem | Med | Explicitly recorded as out-of-scope forward risk, not solved |

## Rollback Plan

New files only; nothing wired into `crear_app()`. Revert the commit(s) / delete
`app/core/seguridad.py` and its tests — no runtime, schema, or route is touched, no migration.

## Dependencies

- Item #1 (`esqueleto-servicio-arranque-seguro`) — shipped, provides `SecretStr` config and the
  `Depends(exigir_token)` seam comment in `app/main.py`.

## Success Criteria

- [ ] Every malformed-header variant returns 401 with an empty body and `WWW-Authenticate: Bearer`.
- [ ] Comparison uses `hmac.compare_digest`; no `len()` pre-check exists; proven structurally, never
      by wall-clock measurement.
- [ ] Token never appears in logs/traces/errors, including partially.
- [ ] `app/core/seguridad.py` has the only `get_secret_value()` call site.
- [ ] Estimated diff ~250–350 changed lines (dependency + full test matrix), under the 400-line
      review budget; confirmed at tasks time.

## Proposal question round

Business-shaping decisions were already settled in the exploration question round (Engram
`sdd/autenticacion-por-token-de-servicio/decisions`): header/scheme, empty 401 body, raw-string
parsing, `hmac.compare_digest`, `Depends()`-only attachment, single `get_secret_value()` call site.
This proposal adds two new recommendations not previously decided: including `WWW-Authenticate:
Bearer`, and deferring a new ADR 0017 to design/apply rather than authoring it now. If either
recommendation should be reconsidered, or a second question round is wanted before moving to specs,
say so — otherwise this proposal is ready for `sdd-spec`/`sdd-design`.
