# Design: Esqueleto del servicio y arranque seguro

- **Change**: `esqueleto-servicio-arranque-seguro` (BACKLOG item #1)
- **Inputs**: `proposal.md` (authoritative, incl. "Decisions resolved after the proposal question round"), `exploration.md`, `specs/service-bootstrap/spec.md`, ADR 0011/0012, `PRD.md`, `TECH-DESIGN.md`, `REVISION-ADVERSARIAL.md` H-08
- **Authority**: ADRs outrank every other document. Inherited: `L:\App_Portal\adrs\0001`–`0010`. Local: `adrs\0011`–`0015`; this change authors `0016`.
- **Size note**: this design exceeds the usual 800-word artifact budget on purpose — `delivery_strategy` is `exception-ok` for this change and the spawn-ordering mechanism cannot be specified honestly in fewer words.

## Technical Approach

Ship the smallest package tree that makes the two non-negotiable startup guarantees *structural* rather than *conventional*, plus the tooling Strict TDD needs:

1. **`spawn` ordering** is enforced by the Python import system, not by statement order inside `main.py`: the guarded call lives in `app/arranque.py` and is invoked from `app/__init__.py`. CPython initialises a parent package before any of its submodules, so no `app.*` module can create a process or connection first — under `uvicorn`, under `pytest`, under a `pytest-xdist` worker, under a spawned child, or under an ad-hoc script.
2. **Fail-closed configuration** is a `pydantic-settings` model resolved lazily inside the FastAPI lifespan. Missing/empty token ⇒ startup aborts before Uvicorn binds a socket.
3. **The health check** is a router with zero application imports, so its independence from later items is a property of the import graph, not a promise.
4. Everything else is a **named seam**, not an empty package.

## Architecture Decisions

### D1 — Where `set_start_method` lives (the hard problem)

**Fact check first.** `multiprocessing.set_start_method(method, force=True)` does **not** raise on a repeat call: the documented `RuntimeError: context has already been set` is raised only when `force` is falsy. `force=True` reassigns the default context unconditionally, and it does not inspect whether processes already exist. So the proposal's premise ("calling it a second time … raises `RuntimeError`") is true for the unforced call only. The real hazard is therefore **not a loud exception under repeated imports — it is a silent ordering violation**: a module that opened a `pyodbc` connection or started a `Process` *before* the call gets no error at all, and ADR 0012's guarantee quietly stops being true. The mechanism below is designed against the silent failure; re-entrancy is a secondary, already-benign concern.

| Option | Ordering guarantee | Behaviour under repeated import / xdist | Verdict |
|---|---|---|---|
| First executable statement in `app/main.py` (proposal's plan) | Only orders imports *inside* `main.py`. A test that does `import app.core.configuracion` directly — which the suite does constantly — bypasses it entirely | Benign (idempotent), but the guarantee is already broken by then | **Rejected** |
| Inside the lifespan handler | Runs *after* every import, i.e. after the exact window where the violation happens; skipped whenever lifespan is not run (plain `TestClient(app)` without `with`, direct ASGI calls, scripts) | Benign | **Rejected** |
| `conftest.py` fixture only | Fixes the test process, does nothing in production | Benign | **Rejected** |
| **`app/arranque.py` called from `app/__init__.py`** | Importing `app.anything` runs `app/__init__.py` first — a language guarantee, not a convention. No entrypoint can skip it | Runs once per interpreter (`sys.modules` cache); guarded + `force=True` makes any re-execution a no-op. Each xdist worker is its own interpreter, so workers cannot interfere | **Chosen** |

```python
# app/arranque.py
import multiprocessing

METODO_REQUERIDO = "spawn"

class ArranqueInseguroError(RuntimeError):
    """El método de arranque de procesos no pudo fijarse en spawn."""

def fijar_metodo_arranque() -> bool:
    """Fija spawn (ADR 0012). Devuelve True si cambió algo. Idempotente."""
    actual = multiprocessing.get_start_method(allow_none=True)   # sin efecto secundario
    cambio = actual != METODO_REQUERIDO
    if cambio:
        multiprocessing.set_start_method(METODO_REQUERIDO, force=True)
    if multiprocessing.get_start_method() != METODO_REQUERIDO:   # poscondición
        raise ArranqueInseguroError(...)
    return cambio
```

`app/__init__.py` contains that call and **nothing else**. Rationale for keeping the guard even though `force=True` never raises: (a) the post-condition turns a hypothetical future semantics change into a loud startup failure instead of a silent one, (b) `get_start_method(allow_none=True)` is side-effect free (it does not materialise the default context), and (c) the boolean return gives the tests a deterministic observable.

**Relationship to ADR 0012 and to the spec.** ADR 0012 says "en el arranque de `main.py`, antes de crear cualquier proceso o conexión"; the spec says "at import time of the entrypoint module". Importing `app.main` *is* importing `app`, so both are satisfied — this placement is strictly stronger, never weaker. `uvicorn app.main:app` behaves exactly as ADR 0012 describes.

**Side effect in `__init__.py` — accepted cost.** Package-init side effects are normally bad practice. This one is justified because the requirement is literally "before anything else in this application runs", and the operation is pure in-process state mutation: no I/O, no process, no socket, sub-millisecond.

### D2 — How the ordering guarantee is *tested* (not just the call)

Three tests, all in a **fresh interpreter via `subprocess`**, because the pytest process's own multiprocessing state is already polluted and would produce a false pass.

| Test | Mechanism | Proves |
|---|---|---|
| `test_importar_app_fija_spawn` | `subprocess.run([sys.executable, "-c", "import multiprocessing as mp; import app; print(mp.get_start_method(allow_none=True))"])` | Importing the package alone — no factory call, no lifespan — fixes the method |
| `test_ninguna_creacion_previa_al_spawn` | Install `sys.addaudithook` **before** `import app`; record every `os.fork`, `os.posix_spawn`, `os.exec`, `subprocess.Popen`, `socket.connect`, `socket.__new__` event together with `get_start_method(allow_none=True)` at the moment it fired; fail if any event was recorded while the method was not yet `"spawn"` | The **temporal** invariant of ADR 0012, at OS-event level — this is the test that catches item #5 opening an engine at import time |
| `test_reimportacion_es_idempotente` | Same interpreter: `fijar_metodo_arranque()` twice; second call returns `False` and raises nothing | Re-entrancy under Strict TDD's repeated imports |

The audit-hook test asserts an **ordering** relation, not emptiness, so it stays valid when later items legitimately open connections during lifespan. `sys.addaudithook` exists on every supported platform and version (≥3.8); events that cannot fire on a platform (`os.fork` on Windows) simply never appear.

**`pytest-xdist`**: the suite must not *require* it. Each worker is a separate interpreter with separate module state, so the guarantee holds per worker, and every ordering assertion runs in its own throwaway subprocess anyway — immune to worker count and test order.

### D3 — Laziness convention (what makes D1 remain true for items #4, #5, #11)

**Rule**: no module under `app/` may, at module scope, construct configuration, a database engine, a connection, a pool, a thread, or a process. Every such object is reached through a memoised accessor:

```python
# app/core/configuracion.py
@lru_cache(maxsize=1)
def obtener_configuracion() -> Configuracion: ...
```

Why `functools.lru_cache` and not a module-level global: it makes laziness **observable**. `obtener_configuracion.cache_info().currsize == 0` after a fresh `import app.main` is a hard assertion that nothing built it at import time, and `cache_clear()` gives tests a clean reset without module reloading. Item #5's engine and item #11's startup check MUST use the same shape (`obtener_motor()`, memoised, called from lifespan).

**Enforcement seam for item #13** (design only, not built here): an AST check over `app/**/*.py` that fails CI when a `Call` node whose callee names a memoised factory appears at module scope, alongside the existing "`core/` never imports `procesadores/`" check. The audit-hook test in D2 is the runtime counterpart and is already CI-runnable today.

### D4 — Configuration shape and the token-leak surface

```python
class Configuracion(BaseSettings):
    model_config = SettingsConfigDict(extra="forbid", frozen=True)  # env only; no .env file → platform-neutral
    # NOTE: extra="forbid" rejects unknown keyword arguments passed directly to
    # Configuracion(...). It does NOT reject unrelated environment variables —
    # pydantic-settings only collects the environment keys it knows about, so a
    # stray FOO=bar in the environment is silently ignored. Do not rely on this
    # setting as an environment-hygiene guard.
    token_servicio: Annotated[SecretStr, Field(min_length=1)]       # env: TOKEN_SERVICIO, sin default
```

Env var name `TOKEN_SERVICIO` is a **new naming decision** (no document names it) chosen to match the existing Spanish operational vocabulary `EJECUCIONES_MAX` / `TIMEOUT_EJECUCION`.

**Failure path**: unset ⇒ pydantic `missing`; empty ⇒ `string_too_short`. Both raise `ValidationError` at construction, inside the lifespan, before Uvicorn binds a socket (Uvicorn runs lifespan startup before creating listening sockets), so the process exits non-zero and **no HTTP server ever accepts a connection**. Tests assert *non-zero*, not a specific exit code.

**The leak surface `SecretStr` does NOT cover**, and the concrete mitigation for each:

| Vector | Why `SecretStr` is not enough | Mitigation in this design |
|---|---|---|
| Third-party exception rendering | pydantic v2's `str(ValidationError)` includes `input_value=...`; a rejected value would be printed verbatim | The only rejected values are **absent** or **empty** (`min_length=1`, no regex, no length floor). The echo vector is closed *by construction*. **Item #2 MUST NOT add value-shaped validation to this field** without adding a sanitising layer first |
| Traceback chaining | Even a caught `ValidationError` is re-rendered via `__context__` | Catch at the single call site and `raise ConfiguracionInvalida(...) from None` (`from None` sets `__suppress_context__`), building the message from `loc`/`type` only — never `input`. Use `exc.errors(include_url=False, include_input=False)` where the installed pydantic exposes those flags |
| `model_dump()` | Python-mode dump returns the `SecretStr` object (masked `repr`); JSON mode serialises to `'**********'` — so dumps are *mostly* safe; the residual risk is code that unwraps first | Never log a dump of the settings object; the startup log line names the **field**, never a value |
| `.get_secret_value()` misuse | Unwraps to `str`, then any f-string leaks it | **This change ships zero call sites** — item #1 only needs presence. Item #2 gets exactly one, in `app/core/seguridad.py`. Item #13 seam: grep/AST check that `get_secret_value` appears in at most that module and never inside a logging or formatting call |
| Environment echoing | — | Never log `os.environ` or any mapping derived from it |

**Test**: run a fresh interpreter with `TOKEN_SERVICIO` set to a unique sentinel and force a startup failure by other means (and separately with it unset), capture combined stdout+stderr, assert the sentinel substring is absent. Plus a `caplog` assertion on the in-process path.

### D5 — Health check

| Item | Decision | Rationale |
|---|---|---|
| Path | `GET /salud` | Matches the service's Spanish route vocabulary (`/interno/procesadores/{clave}/ejecutar`). `/health`, `/healthz` rejected: no cross-service convention was supplied (proposal Q5) |
| Payload | `200 {"estado": "vivo"}` | Minimal. No version, no dependency status — anything else becomes a second truth (ADR 0006's warning) or a readiness claim this probe cannot back |
| Module | `app/salud.py` (an `APIRouter`), imported by `crear_app()` | Neither pipeline logic (`core/`) nor a processor (`procesadores/`), so a top-level module beside `main.py` keeps ADR 0011's two-package meaning intact |
| Imports | `fastapi` only — no `app.core.*`, no settings | Independence becomes an import-graph property; an AST test asserts `app/salud.py` has no `app.` imports |
| Auth exemption | Item #2 attaches its token dependency to the **processor routers**, never as global middleware with an allow-list | The exemption is then structural: `/salud` is not "excluded from auth", it is simply never inside the authenticated surface. An allow-list is one typo away from opening the whole service |
| HEAD | Free — Starlette adds `HEAD` to any route declaring `GET` | Probes that use HEAD work without extra code |

### D6 — Packaging, tooling, deployment

| Area | Decision | Rationale |
|---|---|---|
| Manager | `uv` — `pyproject.toml` + `uv.lock`; all commands `uv run …` | Settled in the proposal question round |
| Distribution | Real package: `[build-system] hatchling` + `[tool.hatch.build.targets.wheel] packages = ["app"]`; `uv sync` installs it editable | `import app` then resolves regardless of cwd. Rejected: `tool.uv.package = false` (virtual project) — it makes importability depend on cwd being on `sys.path`, exactly the platform-dependent assumption prerequisite #0 forbids |
| Python floor | `requires-python = ">=3.11"`; comment reads *"soporte vigente y tipado moderno"* | ADR 0012 explicitly demotes 3.11 to an independent platform decision. **No comment may cite ADR 0012** |
| Runtime deps | `fastapi`, `uvicorn[standard]`, `pydantic-settings` | Nothing else is needed by item #1 |
| Dev deps | `[dependency-groups] dev = ["pytest", "pytest-cov", "httpx", "ruff", "mypy"]` (PEP 735; `uv` installs `dev` by default) | Matches `openspec/config.yaml`'s recommendation |
| ruff | `target-version = "py311"`, `line-length = 100`; `lint.select = ["E","F","I","B","UP","S","ASYNC","T20"]`; per-file `tests/**: ["S101"]` | `T20` (no `print`) enforces the PRD's *"nada se imprime a stdout"*; `S` catches hardcoded secrets and unsafe subprocess use |
| mypy | `strict = true`, `python_version = "3.11"`, `warn_unreachable = true`; override `tests.*` with `disallow_untyped_defs = false` | Strict on `app/` from line one is cheapest now |
| pytest | `testpaths = ["tests"]`, `addopts = "--strict-markers --cov=app --cov-report=term-missing"`, no `--cov-fail-under` | `openspec/config.yaml` sets `coverage_threshold: 0`. **Gotcha to record**: code executed in the subprocess tests is not measured unless `COVERAGE_PROCESS_START` is wired — the coverage number will understate `arranque.py` |
| Commands | `uv sync` · `uv run pytest` · `uv run ruff check .` · `uv run ruff format --check .` · `uv run mypy app tests` | These become `openspec/config.yaml`'s `test_command` / `build_command` |
| Deployment scaffolding | **None ships** — no Dockerfile, no run script, no systemd/NSSM unit. `README.md` documents the single canonical invocation `uv run uvicorn app.main:app --host 0.0.0.0 --port 8000` and states that `--workers` and Gunicorn are forbidden (ADR 0012) | Prerequisite #0 (Linux container vs. native Windows service) is unresolved; the proposal requires this absence to be *stated*, not implicit |

### D7 — ADR 0016 (authored by this change)

Numbering is free: local ADRs are `0011`–`0015`, inherited portal ADRs are `0001`–`0010`. `0016` collides with nothing in the ecosystem.

`adrs/0016-health-check-publico-sin-base-de-datos.md`, MADR format matching 0011–0015 (**Estado / Contexto / Decisión / Alternativas consideradas / Consecuencias**), in Spanish like its siblings:

- **Contexto**: H-08 — the PRD demands a token on every request *without exception* and, in the same section, a health endpoint for monitoring; a probe carries no token.
- **Decisión**: `GET /salud` is public and database-free; it is the only unauthenticated route; the exemption is expressed by scoping auth to the processor routers (D5), not by an allow-list.
- **Alternativas**: probe configured to send the token (couples the orchestrator to a secret, and a rotation breaks liveness → restart loop); readiness probe querying SQL Server (a DB hiccup restarts healthy containers, and it duplicates item #11); no endpoint (deployment can never be declared healthy).
- **Consecuencias**: "healthy" ≠ "fully functional" — a 200 does not prove token validity, DB reachability, registry↔catalog agreement, or that any processor can execute; a DB outage will not restart an otherwise-healthy instance; a future readiness probe gets its own path and its own ADR.
- **`REVISION-ADVERSARIAL.md`**: H-08's status row `Abierto` → `Resuelto — ADR 0016`, plus a "Cómo se resolvió" paragraph appended to the H-08 entry in place. The document's section structure is not reorganised (minimal, reviewable diff), and its header disclaimer — it is not an architecture authority — stays true.

## Data Flow — startup sequence

```mermaid
sequenceDiagram
    autonumber
    participant OP as Operador / orquestador
    participant UV as Uvicorn (1 worker)
    participant PKG as app/__init__.py
    participant ARR as app/arranque.py
    participant MAIN as app/main.py (crear_app)
    participant CFG as core/configuracion.py
    participant SAL as app/salud.py

    OP->>UV: uv run uvicorn app.main:app
    UV->>PKG: import app.main  (el paquete se inicializa primero)
    PKG->>ARR: fijar_metodo_arranque()
    ARR->>ARR: get_start_method(allow_none=True)
    ARR->>ARR: set_start_method("spawn", force=True) si hace falta
    ARR-->>PKG: poscondición OK  (aún no existe proceso ni conexión)
    PKG->>MAIN: se ejecuta el módulo main
    MAIN->>SAL: include_router(salud)  (sin dependencias)
    MAIN-->>UV: app = crear_app()
    UV->>MAIN: lifespan startup
    MAIN->>CFG: obtener_configuracion()
    alt token ausente o vacío
        CFG--xMAIN: ValidationError
        MAIN--xUV: ConfiguracionInvalida (raise ... from None, sin valores)
        UV-->>OP: arranque abortado, salida distinta de cero, socket nunca abierto
    else token presente
        CFG-->>MAIN: Configuracion (token en SecretStr)
        Note over MAIN: costura: motor de BD (#5) y contraste registry↔BD (#11) van AQUÍ, después del chequeo
        MAIN-->>UV: startup completo
        UV-->>OP: socket abierto; GET /salud → 200 {"estado":"vivo"}
    end
```

Ordering rule for later items: **any new startup work goes after the configuration check**, so a missing token always fails first and a database outage can never mask a configuration error.

## File Changes

| File | Action | Description |
|---|---|---|
| `pyproject.toml` | Create | uv project, deps, dependency group, ruff/mypy/pytest config (D6) |
| `uv.lock` | Create | Generated by `uv sync`; committed |
| `.gitignore` | Create | `.venv/`, `__pycache__/`, `.pytest_cache/`, `.coverage`, `.ruff_cache/`, `.mypy_cache/` |
| `README.md` | Create | Canonical single-worker invocation, the `uv run` command set, explicit "no deployment scaffolding ships" |
| `app/__init__.py` | Create | Calls `fijar_metodo_arranque()` — the package's only side effect |
| `app/arranque.py` | Create | Guarded `spawn` fixation + post-condition + `ArranqueInseguroError` |
| `app/main.py` | Create | `crear_app()` factory, lifespan (config check + documented seams), `app = crear_app()` |
| `app/salud.py` | Create | `APIRouter` with `GET /salud`; imports `fastapi` only |
| `app/core/__init__.py` | Create | Empty |
| `app/core/configuracion.py` | Create | `Configuracion(BaseSettings)`, `obtener_configuracion()` (`lru_cache`), `ConfiguracionInvalida` |
| `tests/conftest.py` | Create | Sentinel-token fixture, `cache_clear()` reset, fresh-interpreter helper |
| `tests/ayudas/subproceso.py` | Create | Runs a snippet in a clean interpreter and returns exit code + combined output |
| `tests/test_arranque_spawn.py` | Create | The three D2 tests |
| `tests/test_configuracion_token.py` | Create | Fail-closed + sentinel-absence tests |
| `tests/test_salud.py` | Create | 200 payload, no-token, no-`app.`-imports AST assertion |
| `tests/test_convenciones_pereza.py` | Create | `cache_info().currsize == 0` after fresh import (D3) |
| `adrs/0016-health-check-publico-sin-base-de-datos.md` | Create | D7 |
| `REVISION-ADVERSARIAL.md` | Modify | H-08 status row + "Cómo se resolvió" paragraph |
| `openspec/config.yaml` | Modify | Fill `test_command` / `build_command` now that tooling exists |

**Not created** (seams only, per scope boundary): `app/procesadores/`, `app/registry.py`, `app/core/db.py`, `app/core/seguridad.py`, `app/core/errores.py`, `app/core/interfaz.py`.

## Interfaces / Contracts

```python
# app/main.py — the seam later items plug into
@asynccontextmanager
async def ciclo_de_vida(app: FastAPI) -> AsyncIterator[None]:
    obtener_configuracion()      # 1. fail-closed; ADR 0012 paso 2
    # seam #5:  motor = obtener_motor()
    # seam #11: contrastar_registry_contra_bd(motor, registry)
    yield
    # seam: cierre ordenado del motor

def crear_app() -> FastAPI:
    app = FastAPI(lifespan=ciclo_de_vida)
    app.include_router(router_salud)          # público, sin dependencias
    # seam #2: routers de procesadores con dependencies=[Depends(exigir_token)]
    return app

app = crear_app()
```

`GET /salud` → `200 application/json` `{"estado": "vivo"}`. No other route exists in this change.

## Testing Strategy

| Layer | What to test | Approach |
|---|---|---|
| Unit | `fijar_metodo_arranque()` idempotence, return value, post-condition failure | Direct call; monkeypatch `multiprocessing` for the post-condition branch |
| Unit | `Configuracion` rejects unset and empty token; accepts a valid one; is `frozen`; `extra="forbid"` | `monkeypatch.setenv` / `delenv` + `pytest.raises` |
| Unit | Laziness: `obtener_configuracion.cache_info().currsize == 0` after fresh import | Fresh-interpreter subprocess |
| Integration | Ordering invariant via `sys.addaudithook` (D2) | Fresh-interpreter subprocess |
| Integration | Token sentinel never present in combined startup output | Fresh-interpreter subprocess, substring assertion |
| Integration | `with TestClient(crear_app())` raises when the token is unset; succeeds when set | Starlette `TestClient` as a context manager (runs lifespan) |
| Integration | `GET /salud` → 200 payload, no auth header, no outbound connection attempted | `TestClient` + audit-hook assertion that no `socket.connect` fired |
| Structural | `app/salud.py` imports no `app.` module | AST scan of the file |
| E2E | Uvicorn exits non-zero with the token unset, socket never bound | Subprocess `uv run uvicorn app.main:app`; assert non-zero exit + sentinel absent |

RED-first ordering under Strict TDD: tooling scaffolding → `arranque` tests → `configuracion` tests → `salud` tests → structural/laziness tests.

## Threat Matrix

Boundary trigger: this change touches **routing** (`/salud`) and **process integration** (`set_start_method`, subprocess-based tests). The reference matrix's own rows are VCS/PR-shaped and are `N/A` here; the two real boundaries are recorded below them.

| Boundary | Applicability | Design response | Planned RED tests |
|---|---|---|---|
| Documentation-like paths | N/A — no file is classified or executed by content type | — | — |
| Git repository selection | N/A — no VCS automation in this change | — | — |
| Commit state | N/A — no VCS automation | — | — |
| Push state | N/A — no VCS automation | — | — |
| PR commands | N/A — no PR automation | — | — |
| **Process start method** (project row) | **Applicable** | Guarded + post-checked `spawn` fixation in package init; failure to reach `spawn` aborts startup | D2's three tests, incl. the audit-hook ordering test |
| **Subprocess use in tests** (project row) | **Applicable** | Test helpers invoke `sys.executable` with a literal `-c` snippet and a list argv — never `shell=True`, never an interpolated command string; ruff `S` rules enforce it | Helper unit test asserting list-argv and `shell=False` |
| **New public route** (project row) | **Applicable** | `/salud` is the only unauthenticated route; auth is scoped to processor routers, so the surface cannot widen by accident | `GET /salud` without a token → 200; no other route exists |

## Migration / Rollout

No migration. New files only; no existing runtime, schema, or in-flight state. Rollback = revert the commit(s) / delete the added files, returning the repository to its documentation-only state. No external system is touched.

## Open Questions

- [ ] Deployment target (Linux container vs. native Windows service, prerequisite #0) — out of this change's control; every decision above is deliberately platform-neutral.
- [ ] `EJECUCIONES_MAX` / `TIMEOUT_EJECUCION` are **not** introduced here — they belong to item #8. Only `TOKEN_SERVICIO` exists in `Configuracion` after this change.
- [ ] Exact Uvicorn exit code on a failed lifespan startup is asserted as *non-zero*, not as a specific number, to avoid coupling the suite to a Uvicorn implementation detail.

## Post-implementation corrections

Two claims in this document were disproven empirically during implementation. They are corrected in
place above; this section records what they said and why they changed, so the correction is auditable
rather than silent.

| Claim as originally written | Reality | Evidence |
|---|---|---|
| `cache_info().currentsize == 0` proves nothing was built at import time | The attribute is **`currsize`**, not `currentsize`. `functools`'s `CacheInfo` namedtuple has exactly the fields `('hits', 'misses', 'maxsize', 'currsize')` | `lru_cache(maxsize=1)(lambda: 1).cache_info()._fields` on Python 3.12.0 |
| `extra="forbid"` was presented as part of the configuration's defensive shape, implying it guards the environment | `extra="forbid"` rejects unknown **keyword arguments** passed directly to `Configuracion(...)`. It does **not** reject unrelated environment variables: pydantic-settings only collects the environment keys it knows about, so a stray variable is silently ignored | Constructing `Configuracion()` with `TOKEN_SERVICIO=abc BASURA_INVENTADA=x` in the environment succeeds and returns a valid settings object |

The implementation and its tests were written against the verified reality, not against these two
sentences, so no code changed as a result of this correction. The lesson worth carrying to items #4,
#5 and #11: a defensive setting named in a design document is not a defense until a test exercises
it. `extra="forbid"` looked like environment hygiene and is not.
