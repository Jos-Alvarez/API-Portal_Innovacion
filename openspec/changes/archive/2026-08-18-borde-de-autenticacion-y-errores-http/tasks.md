# Tasks: Borde de autenticación y errores HTTP

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 372–488 (plan ~460, per design §10) |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 → PR 2 (design's own split, unchanged) |
| Delivery strategy | ask-on-risk (default; none supplied) |
| Chain strategy | pending |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: pending
400-line budget risk: High

No second split proposed — estimate is within the design's forecast range, not materially above it.

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | Wire 401 + `RequestValidationError` handlers; empty-422 module | PR 1 | `uv run pytest tests/test_validacion_http.py -v` | N/A — no shipped route carries a body until Unit 2's mount lands; proven via the test-only app (design §8 row 6) | Revert `app/core/validacion_http.py`, the two `crear_app()` handler-registration lines, `tests/test_validacion_http.py` |
| 2 | Pre-body auth boundary (`/interno` mount + ASGI middleware), ADR 0019, route-pin update | PR 2 | `uv run pytest tests/test_borde_autenticacion.py tests/test_seguridad_token.py -v` | `uv run uvicorn app.main:app` then `GET /interno/x` without a token — real 401 from the shipped app | Revert `AutenticacionDeBorde`, the `Mount(...)` append, `adrs/0019-*.md`, `tests/test_borde_autenticacion.py`, and the `_rutas_efectivas`/literal edit in `tests/test_seguridad_token.py` |

## Phase 1: Obligation 1 — wire the 401 handler

- [x] 1.1 `app/main.py`: import `registrar_manejador_401` from `app.core.seguridad`; call it inside `crear_app()` before the app is returned. Remove the stale `# costura #2` comment describing the dependency-based plan.

## Phase 2: Obligation 2 — `RequestValidationError` → empty 422

- [x] 2.1 Create `app/core/validacion_http.py`: `responder_validacion_invalida(request, exc) -> Response` returning `Response(status_code=422)` (no body, no `tipo`), and `registrar_manejador_validacion(app)` calling `app.add_exception_handler(RequestValidationError, responder_validacion_invalida)`. Docstring explains why no `tipo` fits (design §4.1).
- [x] 2.2 `app/main.py`: call `registrar_manejador_validacion(app)` inside `crear_app()`.
- [x] 2.3 Create `tests/test_validacion_http.py` with a test-only app (item #3's pattern): one route with a declared body + `registrar_manejador_validacion`. Test: POST a sentinel-bearing body that fails validation → `422`, `respuesta.content == b""`, sentinel absent from full raw response bytes (design §8 row 6).
- [x] 2.4 Same file: test `crear_app().exception_handlers[TokenInvalido] is responder_token_invalido` and `[RequestValidationError] is responder_validacion_invalida` (design §8 row 7).

Note: the `error-contract` spec amendment (empty 422 body, not `{"tipo","contexto"}`) is **already applied** in `specs/error-contract/spec.md` — no task needed.

## Phase 3: Obligation 3 — pre-body authentication boundary

- [x] 3.1 `app/core/seguridad.py`: add `AutenticacionDeBorde` ASGI middleware (`__slots__`, reads `scope["headers"]` via `Request(scope)`, calls `exigir_token`, never `receive()`; design §2.3). Export it. Update the module docstring — it no longer says nothing here is wired into `crear_app()`.
- [x] 3.2 `app/main.py`: create `router_interno = APIRouter()`; append `Mount("/interno", app=router_interno, middleware=[Middleware(AutenticacionDeBorde)])` to `app.router.routes`. Remove the remaining stale `# costura #2` comment.
- [x] 3.3 `tests/test_seguridad_token.py` (in scope for this change): extend `_rutas_efectivas` to descend into `Mount` (`isinstance(ruta, Mount)` branch, design §5). Keep the existing five-entry literal unchanged; add a separate assertion for the mount set `{"/interno"}`.
- [x] 3.4 Create `tests/test_borde_autenticacion.py`:
  - [x] 3.4.1 Row 1: hand-built `http` scope, `recibir_espia` list, `anyio.run(...)` — assert spy stays empty and response is 401/empty body/`WWW-Authenticate: Bearer` (body never consumed).
  - [x] 3.4.2 Row 2: `TestClient(crear_app())`, `GET /interno/x` with no header, wrong token, malformed header → 401/empty body/`WWW-Authenticate: Bearer` in all cases.
  - [x] 3.4.3 Row 3: same route with the correct token → 404 (empty mount; proves passthrough).
  - [x] 3.4.4 Row 4: no `Authorization` header — `GET /salud` → 200; `GET /docs`, `GET /openapi.json` → 200.
  - [x] 3.4.5 Row 8: sentinel/subprocess variant of item #2's existing test, driven through `/interno`, proving the token stays absent from captured output on the new path.

## Phase 4: ADR 0019

- [x] 4.1 Create `adrs/0019-frontera-autenticada-por-montaje.md`, MADR format matching `adrs/0011`–`0018`, neutral professional Spanish. Sections: Estado, Contexto, Decisión, Alternativas consideradas, Consecuencias — content per design §6. Record accepted costs in *Consecuencias*: routes inside `/interno` are invisible to `/openapi.json` (V9); driving a mounted bare `APIRouter` this way is unexercised while the mount is empty.

## Phase 5: Static verification

- [x] 5.1 `uv run pytest`
- [x] 5.2 `uv run ruff check .`
- [x] 5.3 `uv run ruff format --check .`
- [x] 5.4 `uv run mypy app tests`
