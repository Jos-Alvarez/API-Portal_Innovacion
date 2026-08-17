# Tasks: Esqueleto del servicio y arranque seguro

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~570 authored (excludes generated `uv.lock`) |
| 400-line budget risk | High |
| Chained PRs recommended | No — `size:exception` already accepted by user |
| Suggested split | Single PR, internally split into work-unit commits |
| Delivery strategy | exception-ok |
| Chain strategy | size-exception |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: size-exception
400-line budget risk: High

`size:exception` was explicitly accepted by the user in the proposal round (see "Decisions resolved after the proposal question round" #2). No further approval is required before `sdd-apply`; the forecast above is reported honestly per the review-workload guard, not as a blocker.

### Suggested Work Units (commits within the single accepted PR)

| Unit | Goal | Focused test command | Runtime harness | Rollback boundary |
|------|------|----------------------|-----------------|--------------------|
| 1 | Tooling scaffolding | `uv run pytest` (empty suite) | N/A — no app code yet | Delete `pyproject.toml`, `uv.lock`, `.gitignore`, `README.md` |
| 2 | `spawn` ordering (`arranque`) | `uv run pytest tests/test_arranque_spawn.py` | Fresh-interpreter subprocess import of `app` | Delete `app/__init__.py`, `app/arranque.py`, `tests/test_arranque_spawn.py`, `tests/ayudas/subproceso.py`, `tests/conftest.py` |
| 3 | Fail-closed configuration | `uv run pytest tests/test_configuracion_token.py` | Fresh-interpreter subprocess with sentinel `TOKEN_SERVICIO` | Delete `app/core/configuracion.py`, `app/core/__init__.py`, `tests/test_configuracion_token.py` |
| 4 | App factory + health | `uv run pytest tests/test_salud.py` | `uv run uvicorn app.main:app` (token unset → non-zero exit; token set → 200 `/salud`) | Delete `app/main.py`, `app/salud.py`, `tests/test_salud.py` |
| 5 | Laziness convention check | `uv run pytest tests/test_convenciones_pereza.py` | Fresh-interpreter subprocess | Delete `tests/test_convenciones_pereza.py` |
| 6 | ADR 0016 + H-08 tracker update | N/A (docs) | N/A — documentation only | Revert `adrs/0016-*.md`; revert H-08 row/paragraph in `REVISION-ADVERSARIAL.md` |

## Open Item — Not Actioned (flag only)

The rollback boundaries above and the design's "Migration / Rollout" section assume `git revert`, but `L:\API-Portal` is **not a git repository** (confirmed at `sdd-init`, no `git init` run since, per instruction). No task below runs any VCS command. **User decision needed**: initialize git before or during `sdd-apply`, or accept file-deletion rollback without VCS history until a later change sets up the repository.

## Phase 0: Tooling Scaffolding (Strict TDD prerequisite — no test runner exists yet)

- [x] 0.1 Create `pyproject.toml`: uv project, `[build-system] hatchling` + `packages = ["app"]`, `requires-python = ">=3.11"` (comment: "soporte vigente y tipado moderno" — MUST NOT cite ADR 0012), runtime deps `fastapi`, `uvicorn[standard]`, `pydantic-settings`, `[dependency-groups] dev = ["pytest","pytest-cov","httpx","ruff","mypy"]`, ruff (`target-version="py311"`, `line-length=100`, `lint.select=["E","F","I","B","UP","S","ASYNC","T20"]`, per-file `tests/**: ["S101"]`), mypy (`strict=true`, `python_version="3.11"`, `warn_unreachable=true`, override `tests.*` `disallow_untyped_defs=false`), pytest (`testpaths=["tests"]`, `addopts="--strict-markers --cov=app --cov-report=term-missing"`, no `--cov-fail-under`)
- [x] 0.2 Run `uv sync`; commit generated `uv.lock`
- [x] 0.3 Create `.gitignore`: `.venv/`, `__pycache__/`, `.pytest_cache/`, `.coverage`, `.ruff_cache/`, `.mypy_cache/`
- [x] 0.4 Create `README.md`: canonical single-worker invocation `uv run uvicorn app.main:app --host 0.0.0.0 --port 8000`; explicit statement that `--workers` and Gunicorn are forbidden (ADR 0012) and that no deployment scaffolding (Dockerfile/run script/service unit) ships in this change; document the `uv run` command set
- [x] 0.5 Update `openspec/config.yaml` `testing.test_command` / `testing.build_command` (and the `apply`/`verify` mirrors) to the D6 commands: `uv sync`, `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy app tests`
- [x] 0.6 Verify: `uv run pytest` collects an empty suite with coverage reporting and no manual setup (Requirement: "Tooling runs pytest end-to-end")

## Phase 1: `spawn` Ordering (RED → GREEN, design D1/D2)

- [x] 1.1 RED — Create `tests/ayudas/subproceso.py`: helper running a snippet in a clean interpreter via `sys.executable`, list argv, `shell=False` (never `shell=True`, never an interpolated string), returns exit code + combined stdout/stderr
- [x] 1.2 RED — Create `tests/conftest.py`: sentinel-token fixture, `obtener_configuracion.cache_clear()` reset fixture
- [x] 1.3 RED — Create `tests/test_arranque_spawn.py` with three failing tests (package does not exist yet): `test_importar_app_fija_spawn` (fresh interpreter, `import app`, asserts `mp.get_start_method(allow_none=True) == "spawn"`), `test_ninguna_creacion_previa_al_spawn` (`sys.addaudithook` installed **before** `import app`, records `os.fork`/`os.posix_spawn`/`os.exec`/`subprocess.Popen`/`socket.connect`/`socket.__new__` events with the start-method state at fire time; fails if any event predates `"spawn"`), `test_reimportacion_es_idempotente` (calling `fijar_metodo_arranque()` twice: second call returns `False`, raises nothing)
- [x] 1.4 GREEN — Create `app/arranque.py`: `ArranqueInseguroError`, `fijar_metodo_arranque()` — side-effect-free `get_start_method(allow_none=True)` check, guarded `set_start_method("spawn", force=True)`, postcondition check raising `ArranqueInseguroError` if not `"spawn"`, returns bool
- [x] 1.5 GREEN — Create `app/__init__.py`: calls `fijar_metodo_arranque()` as its only statement; add a comment marking this call as load-bearing (package-init side effect intentional — do not remove/refactor away, it is what makes `spawn` a language-level guarantee rather than a convention)
- [x] 1.6 Verify: `uv run pytest tests/test_arranque_spawn.py` green; `uv run ruff check .` and `uv run mypy app tests` clean for these files

## Phase 2: Fail-Closed Configuration (RED → GREEN, design D4)

- [x] 2.1 RED — Create `tests/test_configuracion_token.py`: unset `TOKEN_SERVICIO` → startup fails (raises, no silent continuation); empty string → fails; valid value → accepted; `Configuracion` is `frozen`, `extra="forbid"`; fresh-interpreter subprocess test with a unique sentinel token forcing failure by other means, asserting the sentinel substring is absent from combined stdout+stderr; a `caplog`-based in-process assertion for the same non-leak property
- [x] 2.2 GREEN — Create `app/core/__init__.py` (empty)
- [x] 2.3 GREEN — Create `app/core/configuracion.py`: `Configuracion(BaseSettings)` with `model_config = SettingsConfigDict(extra="forbid", frozen=True)`, `token_servicio: Annotated[SecretStr, Field(min_length=1)]` bound to env `TOKEN_SERVICIO` (no default), `obtener_configuracion()` decorated `@lru_cache(maxsize=1)`, `ConfiguracionInvalida` exception raised via `raise ConfiguracionInvalida(...) from None` at the single call site, message built from `loc`/`type` only — never `input` (use `exc.errors(include_url=False, include_input=False)` where available)
- [x] 2.4 Add a durable comment/docstring on `token_servicio` in `app/core/configuracion.py`: item #2 MUST NOT add value-shaped validation (regex, length floor beyond `min_length=1`, etc.) to this field without first adding a sanitising layer — `min_length=1` with no other constraint is what closes pydantic's `input_value` echo vector by construction (design risk #1)
- [x] 2.5 Verify: `uv run pytest tests/test_configuracion_token.py` green

## Phase 3: App Factory + Health Check (RED → GREEN, design D3/D5)

- [x] 3.1 RED — Create `tests/test_salud.py`: `GET /salud` → `200 {"estado": "vivo"}` with no token header; `TestClient` + audit-hook assertion that no `socket.connect` fires during the request; AST scan asserting `app/salud.py` imports no `app.*` module
- [x] 3.2 RED — Add integration test (same file or a dedicated one): `with TestClient(crear_app())` raises when `TOKEN_SERVICIO` is unset, succeeds when set (Starlette `TestClient` as context manager runs lifespan)
- [x] 3.3 GREEN — Create `app/salud.py`: `APIRouter` with `GET /salud`, `fastapi`-only imports, no `app.core.*`
- [x] 3.4 GREEN — Create `app/main.py`: `ciclo_de_vida()` lifespan calling `obtener_configuracion()` first (before any later-item seam), inline comments marking seam #5 (`motor = obtener_motor()`), seam #11 (`contrastar_registry_contra_bd(...)`), and ordered engine shutdown; `crear_app()` factory including `router_salud` and a comment marking the seam #2 auth-dependency attach point on processor routers (never global middleware/allow-list); module-level `app = crear_app()`
- [x] 3.5 Verify: `uv run pytest tests/test_salud.py` green; E2E — subprocess `uv run uvicorn app.main:app` with token unset asserts non-zero exit and sentinel absence from combined output; with token set, socket opens and `GET /salud` returns 200

## Phase 4: Structural / Laziness Verification (design D3)

- [x] 4.1 RED — Create `tests/test_convenciones_pereza.py`: fresh-interpreter subprocess asserting `obtener_configuracion.cache_info().currentsize == 0` immediately after `import app.main`
- [x] 4.2 Confirm (no production change expected if Phases 1–3 followed the laziness convention: no module-scope construction of config/engine/connection/pool/thread/process anywhere under `app/`) — `uv run pytest tests/test_convenciones_pereza.py` green
- [x] 4.3 Record the `COVERAGE_PROCESS_START` gotcha durably (comment near `[tool.pytest.ini_options]` in `pyproject.toml`, or a "Testing notes" subsection in `README.md`): code executed inside the fresh-interpreter subprocess tests (`arranque`, `configuracion` sentinel, E2E) is NOT measured by `pytest-cov` unless `COVERAGE_PROCESS_START` is wired; harmless today (`coverage_threshold: 0`) but will silently understate coverage once a coverage gate is added (design risk #2)

## Phase 5: ADR 0016 + H-08 Tracker (design D7)

- [x] 5.1 Create `adrs/0016-health-check-publico-sin-base-de-datos.md` in MADR format matching `adrs/0011`–`0015` (Estado / Contexto / Decisión / Alternativas consideradas / Consecuencias), in Spanish: Contexto = H-08 tension between "token en toda petición" and a token-free health probe; Decisión = `GET /salud` público y sin BD, único endpoint sin autenticación, exención expresada acotando el auth a los routers de procesadores (no allow-list); Alternativas = probe con token (acopla al orquestador, la rotación rompe liveness), readiness probe contra SQL Server (duplica el ítem #11, un hipo de BD reinicia contenedores sanos), sin endpoint; Consecuencias = "healthy" ≠ "fully functional" — un 200 no prueba validez del token, alcance de SQL Server, coincidencia registry↔catálogo, ni que un procesador pueda ejecutar; una futura sonda de readiness tendría su propia ruta y su propio ADR
- [x] 5.2 Update `REVISION-ADVERSARIAL.md`: change H-08's status cell from `Abierto` to `Resuelto — ADR 0016`; append a "Cómo se resolvió" paragraph to the H-08 entry in place (no reorganization of the document's section structure; header disclaimer about not being an architecture authority stays intact)

## Phase 6: Full Suite Verification

- [x] 6.1 Run `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy app tests` — all green across every file created in Phases 0–5
