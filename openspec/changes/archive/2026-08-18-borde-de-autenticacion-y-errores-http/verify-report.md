# Verification Report — borde-de-autenticacion-y-errores-http

**PASS 2 — supersedes pass 1 in full.** Pass 1 (PASS WITH WARNINGS, 0 CRITICAL / 1 WARNING /
1 SUGGESTION) is stale on its SUGGESTION: the user closed the wiring debt it flagged rather than
deferring it a third time. This report re-verifies the entire change, not only the follow-up.

**Mode**: full artifacts (proposal, specs, design, tasks all present)
**Verdict**: PASS WITH WARNINGS

## What changed since pass 1

A follow-up batch (Engram `sdd/borde-de-autenticacion-y-errores-http/apply-progress`, obs #103,
Unit 3) wired `registrar_manejador_errores(app)` inside `crear_app()` — the third and last of the
change's carried handlers — and added two behavioural tests in `tests/test_errores_tipificados.py`.
Suite grew from 106 to 108 tests. No dependency changed.

## Completeness (tasks.md)

All 14 tasks across 5 phases are checked [x]. No unchecked task found. Task 3.3's authorised
modification of tests/test_seguridad_token.py matches what shipped. The follow-up (handler wiring +
2 tests) was authorised by the user directly, outside the original task list, closing design §12's
"Recorded, not solved" item early rather than leaving it for the parked reception half.

## Command evidence (real output, this pass)

    $ python -m uv run pytest
    108 passed, 1 warning in 5.00s
    (StarletteDeprecationWarning re: httpx - pre-existing, unrelated)
    Coverage: 99% (app/core/validacion_http.py 100%, app/core/seguridad.py 100%, app/main.py 100%)

    $ python -m uv run ruff check .
    All checks passed!

    $ python -m uv run ruff format --check .
    45 files already formatted

    $ python -m uv run mypy app tests
    Success: no issues found in 30 source files

All four commands pass with real, observed output. No claims of green not backed by execution.
`git status --short` confirms only app/core/seguridad.py, app/main.py, tests/test_errores_tipificados.py
and tests/test_seguridad_token.py are modified; adrs/0019-*.md, app/core/validacion_http.py,
tests/test_borde_autenticacion.py, tests/test_validacion_http.py are new (untracked); pyproject.toml
and uv.lock do not appear in the diff at all. Work remains uncommitted, as instructed.

## Spec compliance matrix

### service-token-auth delta

| Requirement / Scenario | Status | Evidence |
|---|---|---|
| Route set changes deliberately for the auth boundary | PASS | app/main.py wires registrar_manejador_401 and appends Mount("/interno", ...) inside crear_app(); test_rutas_de_produccion_no_cambian updated to assert esperado_montajes = {"/interno"} alongside the unchanged 5-entry literal - passes |
| 401 handler wired into production | PASS | app.exception_handlers[TokenInvalido] is responder_token_invalido on the shipped crear_app() - asserted by test |
| Pinned route-set test updated, not merely passing | PASS | _rutas_efectivas descends into Mount (isinstance(ruta, Mount) branch at test_seguridad_token.py:274); literal unchanged, mount set asserted separately |
| /salud unaffected by the new mount | PASS | test_salud_y_documentacion_fuera_de_la_frontera: no Authorization header, GET /salud returns 200 |
| Token never appears in captured output (general + new boundary) | PASS | sentinel/subprocess variant through /interno, asserts sentinel absent from combined stdout/stderr |
| Auth failures on the authenticated surface never surface as 500 | PASS | test_rechazo_desde_la_app_embarcada - 401, empty body, WWW-Authenticate: Bearer, never 500 |
| Rejection happens before the body is read | PASS | test_rechazo_no_consume_el_cuerpo - hand-built ASGI scope + spy receive(), anyio.run. Asserts recibir_espia == [] and a full, correct 401 response was still produced |

### error-contract delta (amended: empty 422, not the typed envelope)

Spec on disk (`specs/error-contract/spec.md`) carries the amendment verbatim: "422 and an empty body
... MUST NOT carry ADR 0014's {tipo, contexto} envelope either." Implementation matches.

| Requirement / Scenario | Status | Evidence |
|---|---|---|
| Malformed body -> empty 422 | PASS | test_cuerpo_malformado_responde_422_vacio: status 422, respuesta.content == b"" |
| No detail, no tipo, no contexto | PASS | responder_validacion_invalida returns bare Response(status_code=422) - no body at all |
| Neither submitted value nor service token leaks | PARTIAL (documented, not a defect - carried forward, see WARNING below) | Sentinel proven absent; service token not actively exercised in this specific test |
| Handler active in crear_app() | PASS | app.exception_handlers[RequestValidationError] is responder_validacion_invalida on the shipped app |

### The closed item — typed-error handler now wired (this pass's focus)

| Requirement | Status | Evidence |
|---|---|---|
| registrar_manejador_errores(app) wired in crear_app() | PASS | app/main.py:20,40 - import + call, third registration alongside the other two, before `return app` |
| Wiring proven by registry identity | PASS | test_manejador_registrado_en_la_app_embarcada: crear_app().exception_handlers[ErrorTipificado] is responder_error_tipificado |
| Wiring proven behaviourally, on the shipped app | PASS | test_manejador_activo_en_la_app_embarcada - see judgment below |

## Judgment: do the two new tests prove genuine wiring, or only a call?

`test_manejador_registrado_en_la_app_embarcada` is a registry-identity check only (mirrors the
existing pattern for the 401 and validation handlers) — it proves the handler object is present in
`app.exception_handlers`, nothing more.

`test_manejador_activo_en_la_app_embarcada` is the behavioural proof, and it is genuine:

- It calls the real `crear_app()` factory — the exact function `app = crear_app()` at the bottom of
  `app/main.py` also calls — not a hand-built test app.
- It appends a throwaway `GET /prueba-error-tipificado` route directly onto that real app instance,
  which raises `ErrorFormato` (one of the five ADR 0014 types).
- It opens `TestClient(app, raise_server_exceptions=False)` inside a `with` block, which runs the
  real `ciclo_de_vida` lifespan (the same lifespan the shipped app runs), requiring the
  `token_sentinela` + `limpiar_cache_configuracion` fixtures because `crear_app()`'s lifespan now
  calls `obtener_configuracion()` and fails closed without a configured token.
- `raise_server_exceptions=False` is the correct choice here: it lets the *exception handler machinery*
  answer instead of pytest re-raising the exception past FastAPI, which is what would happen with the
  default `raise_server_exceptions=True`. This is exactly the same mechanism the exception handler
  registration protects — if `registrar_manejador_errores` had not been called, the request would
  return a 500, not the ADR 0014 envelope.
- It asserts a full 422 response with the exact `{"tipo": "formato", "contexto": {...}}` body ADR 0014
  requires, not just a status code.

This proves the handler is genuinely active on the object that ships, through the same code path a
real request would take. It is not a call that merely exercises `responder_error_tipificado` in
isolation — that was already covered by the pre-existing parametrized suite in
`test_errores_tipificados.py`, untouched by this batch. The new test's job — and the only thing it
needed to add — is proving *registration*, and it does so behaviourally rather than by inspection
alone. No CRITICAL or WARNING finding here.

## Correctness — properties re-audited this pass

### 1. Exactly one 401 construction site — RE-CONFIRMED, no CRITICAL finding

`grep -rn "status_code=401" app/` returns exactly one hit: `app/core/seguridad.py:41`, inside
`responder_token_invalido`. `AutenticacionDeBorde.__call__` never builds a `Response`; it calls
`await exigir_token(Request(scope))`, whose only `raise` site is unchanged from item #2. The exception
unwinds through the outer app's `ExceptionMiddleware`, which already owned `responder_token_invalido`
before this change. Nothing in the follow-up batch touched `app/core/seguridad.py`'s 401 path — the
follow-up only added a third, unrelated handler registration.

### 2. Rejection without consuming the body — unchanged, still genuinely proven

`test_rechazo_no_consume_el_cuerpo` (untouched by the follow-up) builds a spy `receive()` and a real
26 MB `Content-Length`, drives the real `crear_app()`, and asserts the spy was never called while a
complete, correct 401 was still produced. Deterministic, not timing-based.

### 3. The empty 422 — status, body, headers, re-audited

`responder_validacion_invalida` (untouched by the follow-up) returns `Response(status_code=422)` with
no content or header arguments. No `detail`, `tipo`, or `contexto` key can appear because no body is
emitted at all. Sentinel proven absent by `test_sentinela_ausente_de_la_respuesta_completa`.
Service-token leak coverage remains vacuous in this specific test — see WARNING below (carried
forward, unchanged from pass 1, not reopened by this pass's edits).

### 4. All three handlers registered inside crear_app(), before it returns — RE-CONFIRMED

`app/main.py::crear_app()` now calls, in order: `registrar_manejador_401(app)`,
`registrar_manejador_validacion(app)`, `registrar_manejador_errores(app)` — all before the `Mount` is
appended and before `return app`. No handler registration happens anywhere outside `crear_app()`.
This closes design §12's "Recorded, not solved" item and the SUGGESTION carried across all three prior
passes.

### 5. The route pin sees the mount — RE-CONFIRMED, untouched by the follow-up

`_rutas_efectivas` (tests/test_seguridad_token.py:246-283) is unmodified since pass 1: three branches
(`_IncludedRouter`, `Mount`, leaf). The `Mount` branch recurses into `ruta.routes` with the extended
prefix and adds `prefijo + ruta.path` to the mount set. The five-entry route literal
(`/salud`, `/openapi.json`, `/docs`, `/docs/oauth2-redirect`, `/redoc`) is byte-identical to the
pre-change literal; `esperado_montajes = {"/interno"}` is a separate assertion. No CRITICAL or WARNING
finding here.

### 6. /salud and doc routes stay outside the authenticated surface structurally

`app/main.py` registers `router_salud` via `app.include_router(router_salud)` and the `/interno` mount
separately via `app.router.routes.append(Mount(...))`. No path allow-list anywhere in the diffed
files — membership in the authenticated surface is purely "was this route registered inside
`router_interno`". `test_salud_y_documentacion_fuera_de_la_frontera` proves `/salud`, `/docs`,
`/openapi.json` all return 200 with no `Authorization` header present. Unaffected by the follow-up.

### 7. ADR 0019 — format and content, re-checked

`adrs/0019-frontera-autenticada-por-montaje.md` exists, unchanged by the follow-up. Structure
(`Estado`, `Contexto`, `Decisión`, `Alternativas consideradas`, `Consecuencias`) matches the section
set of `adrs/0016`–`0018` (0016 spells its decision section `## Decision` without the accent; 0019
uses `## Decisión` — a pre-existing minor inconsistency across the ADR series, not introduced by this
change, and not a defect of this change). Prose is neutral, professional Spanish throughout. Its
`Contexto` quotes ADR 0016's mechanism verbatim and states the reason it cannot satisfy the PRD;
its `Decisión` states ADR 0016 is not reverted, only its named mechanism is superseded.

## Design coherence

- Section 2.1's chosen option (bare APIRouter mounted with middleware=[...]) is what shipped.
- Section 4.3's placement decision (app/core/validacion_http.py as its own module) is what shipped.
- Section 4.4's required spec amendment (empty 422 body instead of the typed envelope) is present in
  specs/error-contract/spec.md verbatim as an "Amended after the design phase" callout.
- Section 12's "Recorded, not solved" item (registrar_manejador_errores(app) unwired) is now FALSE —
  the follow-up closed it. This is a design deviation in the direction of doing more than the design
  scoped, not less: the design explicitly parked this for the reception half, and the user chose to
  close it here instead. Recorded as a scope decision, not a defect; nothing in the design's other
  sections depended on this staying unwired.
- No other design deviation found beyond what Sections 4.4 and 13 already flagged and resolved.

## Issues

### CRITICAL
None found.

### WARNING
1. Service-token absence not actively exercised in the empty-422 test (carried forward unchanged from
   pass 1 — not reopened, not touched by the follow-up). `tests/test_validacion_http.py`'s test-only
   app has no token dependency, so the amended spec's "neither the submitted value nor the service
   token appears" scenario is proven for the sentinel only, not the token, in this specific test. This
   is a genuine false-green pattern, not a shipped defect: there is no token in play to leak in that
   test app, so the clause is proven vacuously rather than actively. It becomes actively provable once
   a real body-declaring route lands under `/interno`, which belongs to the parked reception half.

### SUGGESTION
None found this pass. Pass 1's SUGGESTION (registrar_manejador_errores(app) unwired) is CLOSED — see
"Judgment" and "Correctness #4" above. No new suggestion arises from the follow-up itself; the two new
tests are proportionate to the claim they prove and add no new debt.

## Verdict

PASS WITH WARNINGS. All 14 original tasks plus the authorised follow-up are complete, 108/108 tests
pass, ruff/mypy clean, all three of the change's obligations are now wired with genuine runtime
evidence (including the previously-parked typed-error handler), the single-401-construction-site
invariant still holds, rejection-before-body-read is still proven rather than asserted, and the
amended empty-422 requirement is implemented exactly as amended. One WARNING remains (token-absence
coverage gap in the 422 test, structurally unavoidable until a real route lands in the parked second
half) — unchanged from pass 1, not a regression, does not block archiving this change. Zero CRITICAL,
zero open SUGGESTION.
