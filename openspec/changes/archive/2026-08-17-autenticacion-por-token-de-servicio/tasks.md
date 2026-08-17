# Tasks: Autenticación por token de servicio

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 497–582 (per design §14) |
| 400-line budget risk | High |
| Chained PRs recommended | No — `size:exception` already accepted |
| Suggested split | Single PR, work-unit commits (below) |
| Delivery strategy | exception-ok |
| Chain strategy | size-exception |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: size-exception
400-line budget risk: High

`size:exception` was accepted by the user for this change (Engram `sdd/.../decisions-post-design`, item 4). No further approval is needed before `sdd-apply`. Reported for visibility only.

### Suggested Work Units

| Unit | Goal | Focused test | Runtime harness | Rollback boundary |
|---|---|---|---|---|
| 1 | Fix inherited `get_secret_value()` conflict in item #1 test | `uv run pytest tests/test_configuracion_token.py` | N/A — unit test only | Revert one line in `tests/test_configuracion_token.py` |
| 2 | `app/core/seguridad.py`: parsing + comparison + secret unwrap | `uv run pytest tests/test_seguridad_token.py -k presentada or coincide or esperado` | N/A — pure functions | Delete module |
| 3 | Dependency, exception, handler, test-app fixture, accepted path | `uv run pytest tests/test_seguridad_token.py -k valido` | `TestClient(crear_app_de_prueba())` GET `/protegido` with valid Bearer | Delete fixture + dependency wiring |
| 4 | Full rejection matrix + non-ASCII acceptance | `uv run pytest tests/test_seguridad_token.py` | Same TestClient, 8 malformed variants | Delete matrix test |
| 5 | Structural AST proofs + `debug` scan | `uv run pytest tests/test_seguridad_estructural.py` | N/A — static analysis | Delete file |
| 6 | Access-log leak test | `uv run pytest tests/test_seguridad_access_log.py` | Background `uvicorn.Server` on port 0, real HTTP request | Delete file |
| 7 | Route-set pin + ADR 0017 | `uv run pytest tests/test_seguridad_token.py -k rutas` | N/A | Delete route-set test + ADR file |

## Phase 1: Fix inherited get_secret_value() conflict

- [x] 1.1 Edit `tests/test_configuracion_token.py:29`: replace `configuracion.token_servicio.get_secret_value() == token_sentinela` with `configuracion.token_servicio == SecretStr(token_sentinela)` (design §4, V13). Not new behavior — no RED needed; run `uv run pytest tests/test_configuracion_token.py` before and after, confirm both green.

## Phase 2: Parsing, comparison, secret unwrap

- [x] 2.1 RED: create `tests/test_seguridad_token.py`; add unit tests for `_credencial_presentada(request)` covering: absent header, wrong scheme, missing space, empty credential, irregular whitespace, non-ASCII (as `bytes`, V8), duplicate `Authorization` headers, well-formed. Run `uv run pytest`; expect `ImportError` (module missing).
- [x] 2.2 GREEN: create `app/core/seguridad.py` with `_credencial_presentada` per design §3 (`match`/`getlist`, case-insensitive scheme only). Run tests; confirm pass.
- [x] 2.3 RED: add unit tests for `_coincide(a, b)` (equal/unequal bytes) and `_token_esperado()` (UTF-8 bytes of configured token, using `token_sentinela` + `limpiar_cache_configuracion`). Expect `AttributeError`.
- [x] 2.4 GREEN: add `_coincide`, `_token_esperado` per design §4–§5. Confirm pass.

## Phase 3: Dependency, exception, handler, accepted path

- [x] 3.1 RED: add `crear_app_de_prueba()` fixture (design §7, `debug` omitted) + `test_token_valido_alcanza_el_endpoint`. Expect `AttributeError` (missing `exigir_token`/`TokenInvalido`/`responder_token_invalido`/`registrar_manejador_401`).
- [x] 3.2 GREEN: add `exigir_token`, `TokenInvalido` (fieldless), `responder_token_invalido` (typed `(Request, Exception)`), `registrar_manejador_401`, `_es_valida` per design §2/§7. Confirm 200.

## Phase 4: Rejection matrix + non-ASCII acceptance

- [x] 4.1 Add `test_respuestas_de_rechazo_son_identicas`: parametrize the 8 variants; collect `(status, content, tuple(sorted(headers.items())))`; assert one-element set (design §6). Non-ASCII sent as `bytes` header.
- [x] 4.2 Add `test_no_ascii_es_aceptado`: configured token with non-ASCII chars, exact `Bearer` match, 200 (spec scenario "A non-ASCII token is accepted").

## Phase 5: Structural AST proofs + debug scan

- [x] 5.1 Create `tests/test_seguridad_estructural.py`: `test_comparacion_es_de_tiempo_constante`, `test_no_hay_comparacion_por_longitud`, `test_compare_digest_se_usa_una_sola_vez`, `test_la_credencial_nunca_se_normaliza` (design §6). RED: temporarily insert `if len(a) != len(b): return False` before `compare_digest` in `_coincide`; run; confirm the length-check test fails; revert.
- [x] 5.2 Add `test_get_secret_value_un_solo_sitio`: AST walk `app/**/*.py`, exactly one `get_secret_value` call, not inside logging/`str.format`/`JoinedStr`. RED: temporarily add a second `get_secret_value()` call in a scratch test file; confirm failure; remove.
- [x] 5.3 Add `test_sin_debug_true`: AST scan `app/**` + `tests/**` for `FastAPI(...)`/`Starlette(...)` with `debug=True`. RED: temporarily set `debug=True` in `crear_app_de_prueba()`; confirm failure; revert.

## Phase 6: Access-log leak test

- [x] 6.1 Create `tests/test_seguridad_access_log.py`: run `uvicorn.Server` in a background thread on port 0; attach a plain `logging.Handler` directly to `logging.getLogger("uvicorn.access")` (not `caplog` — `propagate: False` per V11 means `caplog` captures nothing and would pass vacuously); issue one request with `Authorization: Bearer <sentinel>`; assert the line has method+path, no sentinel, no `Bearer`; fail (never skip) if no line captured within a bounded wait.

## Phase 7: Route-set pin + ADR 0017

- [x] 7.1 Add `test_rutas_de_produccion_no_cambian` to `tests/test_seguridad_token.py`: compare `{(r.path, tuple(sorted(r.methods))) for r in crear_app().routes}` against the literal baseline (`/salud` + 4 FastAPI defaults, V14). RED: temporarily add a throwaway route to `crear_app()` in `app/main.py`; confirm failure; revert.
- [x] 7.2 Author `adrs/0017-token-de-servicio-en-authorization-bearer.md` (MADR, Spanish, matching 0011–0016 headers): `Authorization: Bearer` + empty-body 401 decision, per design §9 outline. Decision: authored now, not deferred — design §9 recommends it and the forecast already costs it.

## Phase 8: Full-suite verification

- [x] 8.1 Run `uv run pytest` (full suite) and `uv run ruff check . && uv run ruff format --check . && uv run mypy app tests`; confirm all green.
- [x] 8.2 Confirm `D1` (`compare_digest` `TypeError` on non-ASCII `str`) is unreachable in practice: both operands are `bytes` by construction — no new test, mypy strict already enforces it (design §17 open item).

## Out of scope — recorded, not solved

Item #6's `UploadFile` routes cannot get pre-body 401 from `Depends()` (FastAPI reads the body before `solve_dependencies`); needs raw ASGI or `Mount`-scoped middleware. Already recorded in `design.md` §15 — no task here.
