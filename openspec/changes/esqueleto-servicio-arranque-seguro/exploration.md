# Exploration — Esqueleto del servicio y arranque seguro

- **Change**: `esqueleto-servicio-arranque-seguro`
- **Source**: `BACKLOG.md` item #1
- **Phase**: explore (read-only investigation; no proposal, no implementation)
- **Artifact store**: hybrid (this file + Engram topic `sdd/esqueleto-servicio-arranque-seguro/explore`)
- **Depends on**: nothing — root of the backlog dependency graph

## Current state

`L:\API-Portal` contains documentation only. No application code, no packaging, no tooling:

- No `pyproject.toml`, no `requirements*.txt`, no dependency manager decided (pip / poetry / uv).
- No test runner, linter, type checker, formatter, or CI configuration.
- Not a git repository.
- Present: `PRD.md`, `TECH-DESIGN.md`, `BACKLOG.md`, `REVISION-ADVERSARIAL.md`, `adrs/0011`–`adrs/0015`,
  `Contado_Carga.py` (legacy standalone script, out of scope for this change), and the scaffolded
  `openspec/` tree.

Strict TDD is enabled for this session, so tooling scaffolding is an unavoidable part of this change.

## Authority ordering

`PRD.md`, `TECH-DESIGN.md`, and `BACKLOG.md` each explicitly declare themselves subordinate to the
ADRs. No ADR-vs-document contradiction was found within item #1's scope. The one real conflict is an
internal PRD contradiction that no ADR resolves — finding H-08, see Open decisions.

## Hard constraints (ADR-sourced)

From `adrs/0012-ejecucion-en-procesos-dedicados.md`:

- `multiprocessing.set_start_method("spawn", force=True)` MUST run at startup, before any process or
  connection is created. Rationale: under `fork` the child inherits the parent's `pyodbc`
  connection-pool descriptors; `spawn` is what makes "children never touch the database"
  (ADR 0013) a structural guarantee rather than a matter of discipline.
- Single Uvicorn API worker. `EJECUCIONES_MAX` is intended to be the only concurrency knob, so
  deployment scaffolding must not default to `--workers N` or Gunicorn.
- Python 3.11 floor. Note the exact wording: ADR 0012 states the 3.11 requirement no longer derives
  from this mechanism (`max_tasks_per_child` disappeared with the pool) and is retained "por soporte
  vigente y tipado moderno" as an independent platform decision. Treat 3.11 as the floor, but record
  the version choice explicitly in the proposal rather than citing ADR 0012 as its authority.

## Hard constraints (PRD / TECH-DESIGN)

- The service MUST fail to start when the service token is not configured. It must never start "open"
  by default. This change owns the startup-time presence check only.
- The token MUST NOT appear in logs, traces, or error messages — not even partially. This applies to
  the startup failure message itself, not only to request-time handling.
- A health check endpoint is required for monitoring and deployment. No document specifies its path,
  method, authentication requirement, response shape, or whether it touches SQL Server.

## Scope boundary

`TECH-DESIGN.md`'s "Arranque del servicio" describes startup as three steps in a single block:
(1) spawn start method, (2) token presence check, (3) registry ↔ database contrast check.
`BACKLOG.md` splits these across items: **this change owns steps 1 and 2 only**.

Explicitly out of scope:

- Registry ↔ database startup contrast check → item #11 (depends on #4 and #5, neither exists).
- Constant-time token comparison and per-request 401 → item #2.
- Typed error contract → item #3.
- `db.py` / read-only SQL Server mirror → item #5.
- Populated `registry.py` → item #4.

`main.py` may scaffold the app factory and lifespan hooks that those items will later plug into, but
no live database engine and no populated registry belong here.

## Approaches considered

| # | Approach | Pros | Cons |
|---|---|---|---|
| 1 | Configuration via pydantic-settings with `SecretStr` for the token | Missing required field raises at construction, satisfying "fail at startup"; `SecretStr` masks the value in `repr()`/`str()`, defending "never in logs"; item #2 extends the same `Settings` object | Adds a dependency before the dependency-manager decision is made |
| 2 | Plain `os.environ` reads with manual checks | No dependencies | No secret masking — leak avoidance becomes manual discipline exactly where the PRD is strictest; failure messaging hand-rolled |
| 3 | Health check: unauthenticated, database-free liveness probe | A probe never carries the service token, so exempting the health path is the only way it can succeed; a database hiccup does not restart healthy containers | "Healthy" and "fully functional" diverge, and that divergence must be written down |
| 4 | Health check: database-aware readiness probe | Closer to "can actually serve traffic" | Not authorized by any document; H-08 flags it as risky; overlaps item #11 |

## Recommendation

- Place `set_start_method("spawn", force=True)` as the first executable statement at module import
  time in `main.py`, before importing any application module that could transitively create a process
  or connection at import time.
- Use pydantic-settings with `SecretStr` (approach 1).
- Implement the health check as an unauthenticated, database-free liveness probe (approach 3) — but
  surface this as an explicit decision in the proposal, since H-08 is an open finding in this
  repository's own adversarial review and must not be resolved silently.
- Keep configuration and engine construction lazy (inside a lifespan handler or memoized on first
  use), because the `spawn` ordering guarantee depends on it once item #5 adds the database engine.

## Open decisions for the proposal

1. **H-08 — health check versus mandatory token.** Status: Abierto in `REVISION-ADVERSARIAL.md`.
   The PRD requires the token on every request without exception, and in the same section requires a
   health check for monitoring. No document says whether the health path is auth-exempt, nor whether
   it queries SQL Server.
2. **Dependency manager**: pip / poetry / uv — unresolved anywhere.
3. **Python version**: 3.11 floor, no ceiling pinned.
4. **Configuration mechanism**: pydantic-settings versus plain environment reads.
5. **Test/lint/type tooling**: `openspec/config.yaml` records a recommendation from init
   (pytest + pytest-cov + httpx, ruff, mypy), not a decision.
6. **Deployment target**: Linux container versus native Windows service (external prerequisite #0).
   Not this change's problem to solve, but its configuration scaffolding must stay platform-neutral.

## Risks

- **Spawn ordering hazard**: module-level side effects (eager engine construction, thread pools) in
  any imported module silently break the "before any process or connection" ordering.
- **Multi-worker deployment violation**: default deployment configuration must not introduce a second
  API worker, or `EJECUCIONES_MAX` stops being the real concurrency number.
- **`set_start_method` re-entrancy under test**: strict TDD means `app.main` is imported repeatedly by
  the suite, possibly under `pytest-xdist`. Calling `set_start_method` more than once, or after a
  process has started under another context, is fragile and needs a deliberate fixture.
- **Token leak through structured logging**: even with `SecretStr`, `logger.info(settings.model_dump())`
  or naive JSON serialization can still emit the raw value. Needs an explicit test asserting the token
  never appears in captured startup logs.
- **Unverified prior context**: the explore phase could not read the Engram observations
  `sdd-init/api-portal` and `sdd/api-portal/testing-capabilities` directly (no search tool in that
  session) and reconstructed equivalent context from `openspec/config.yaml`. A later phase with full
  tool access should confirm.
