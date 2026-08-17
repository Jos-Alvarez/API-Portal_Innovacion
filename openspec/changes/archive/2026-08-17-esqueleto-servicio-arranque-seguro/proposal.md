# Proposal — Esqueleto del servicio y arranque seguro

- **Change**: `esqueleto-servicio-arranque-seguro`
- **Source**: `BACKLOG.md` item #1
- **Phase**: propose (this document — no specs, no design, no code)
- **Artifact store**: hybrid (this file + Engram topic `sdd/esqueleto-servicio-arranque-seguro/proposal`)
- **Depends on**: nothing — root of the backlog dependency graph
- **Explore artifact**: `openspec/changes/esqueleto-servicio-arranque-seguro/exploration.md` (Engram `sdd/esqueleto-servicio-arranque-seguro/explore`, obs #54)

## Intent

### Problem

`L:\API-Portal` has documentation only: no `pyproject.toml`, no dependency manager, no test runner,
no application code, not even a git repository. Every later backlog item (#2 through #17) needs a
running FastAPI process, a configuration mechanism, and a way to run tests under Strict TDD before it
can add a single line of business logic. Nothing in the backlog can start without this item.

Separately, two hard, non-negotiable startup requirements exist in the PRD and are echoed by ADR
0012, and neither is implemented anywhere yet:

- The service MUST refuse to start when the service token is not configured — it must never come up
  "open" by default (`PRD.md` §"Autenticación y superficie", §"Casos límite").
- `multiprocessing.set_start_method("spawn", force=True)` MUST run before any process or connection
  is created, so that child processes never inherit the parent's `pyodbc` connection-pool descriptors
  (ADR 0012, "`spawn` explícito y forzado").

### Why now

This is backlog item #1 with no dependencies — the root of the dependency graph in `BACKLOG.md`. It
blocks items #2 (token auth), #3 (error contract), #5 (SQL Server mirror), #8 (process execution),
and transitively everything else. Strict TDD is enabled for this repository, so the tooling
scaffolding (pytest, ruff, mypy) is also unavoidable first work — there is no way to write item #1's
own tests without it.

### Success looks like

- `uvicorn app.main:app` starts successfully with a service token configured, and refuses to start
  (non-zero exit, clear operator-facing error) without one.
- The token never appears in any log line, trace, or error message, including the startup-failure
  message itself.
- `set_start_method("spawn", force=True)` is guaranteed to execute before any process or connection
  exists, and this guarantee survives Strict TDD's repeated test-suite imports of `app.main`.
- A `pytest` run works end-to-end (collection, execution, coverage reporting) against an empty test
  suite, so item #2 onward can write RED tests immediately.
- A GET health check endpoint exists, requires no token, and never touches SQL Server or any other
  external dependency.

## Scope

### In scope

1. **Tooling scaffolding** (first work, required by Strict TDD): `pyproject.toml`, a single chosen
   dependency manager, pytest + pytest-cov + httpx (FastAPI `TestClient`), ruff, mypy — wired so
   `pytest` and lint/type-check commands are runnable from a clean checkout.
2. **FastAPI application skeleton**: `app/main.py` with an app factory and lifespan hooks that later
   items (registry population, DB engine, routers) can plug into — without those items' content.
3. **Per-environment configuration** mechanism (recommendation below) that reads the service token
   and other startup-relevant settings from the environment.
4. **`set_start_method("spawn", force=True)`** as the first executable statement at module import
   time in `main.py`, before importing any application module that could transitively create a
   process or connection.
5. **Startup failure when the service token is absent** — the presence check only (not the
   per-request comparison, see out of scope).
6. **Public, database-free health check** — unauthenticated GET endpoint, liveness-only, no SQL
   Server query, no dependency on any later item's code.

### Out of scope (explicit — do not let these leak in)

| Excluded | Owner item |
|---|---|
| Per-request 401 rejection, constant-time token comparison | #2 |
| Typed error contract / closed 5-value error enum (ADR 0014) | #3 |
| `Procesador` ABC, `ArchivoEntrada`/`ArchivoSalida`, populated `registry.py` | #4 |
| SQL Server read-only mirror, `db.py`, SQLAlchemy Core engine | #5 |
| Registry ↔ database startup contrast check (`TECH-DESIGN.md` "Arranque del servicio" step 3) | #11 (depends on #4 and #5) |

`TECH-DESIGN.md`'s "Arranque del servicio" section describes three startup steps as a single block
(spawn method, token check, registry↔DB contrast). `BACKLOG.md` splits these across items; this
change owns steps 1 and 2 only. `main.py` may scaffold the app factory and lifespan hooks that steps
3, item #2's auth dependency, and item #4/#5's engine construction will later plug into, but ships
**no live database engine and no populated registry**.

## Decision: H-08 resolved as public, database-free liveness probe

`REVISION-ADVERSARIAL.md` finding H-08 ("El health check contradice 'token obligatorio'") is
**Abierto** as of this writing. This proposal resolves it as follows, and treats the resolution as
settled for this change:

- The health check route is **exempt from the service token**. It is the only unauthenticated route
  in the service.
- The health check **MUST NOT** query SQL Server or any other external dependency. It reports process
  liveness only.

**This is a deliberate, explicit divergence, not an oversight**: "healthy" (this probe returns 200)
and "fully functional" (the service can actually serve a processing request) are different claims.
A 200 from this endpoint proves the Uvicorn process is up and accepting connections. It does **not**
prove:

- that the service token is valid or even configured (token presence is checked once at startup —
  if the process is running, the check already passed, but a probe response says nothing new here);
- that SQL Server is reachable (relevant once item #5/#11 exist);
- that the registry and database catalog agree (item #11);
- that any processor module can actually execute.

A database outage or registry mismatch will not restart an otherwise-healthy container under this
design — that tradeoff is inherited from approach 3 in the exploration (`exploration.md`,
"Approaches considered") and accepted here for the same reason: a probe that carries no token cannot
be exempted from "toda petición debe presentar el token" any other way without contradicting the
PRD's explicit no-exceptions text, and a readiness probe that queries the database is not authorized
by any document and overlaps item #11's job.

**Recommendation, not a unilateral decision**: this resolution should be captured as a new local ADR,
numbered **0016**, since it settles an architecturally significant open finding (H-08) that the
existing ADRs (0011–0015) do not address. The design phase or a follow-up ADR-authoring step should
confirm the exact ADR number and content; this proposal does not create the ADR file itself.

## Approach

### 1. Tooling and dependency manager

Scaffold `pyproject.toml` with pytest, pytest-cov, httpx, ruff, and mypy as declared in
`openspec/config.yaml`'s testing recommendation (not yet installed/confirmed). **Open decision**:
pip vs. poetry vs. uv as the dependency manager — unresolved in every document read (`PRD.md`,
`TECH-DESIGN.md`, `BACKLOG.md`, exploration). Recommend resolving this at design/spec time rather
than here, since it affects lockfile format and CI wiring beyond this change's scope, but flag it as
a **blocking decision for the next phase** — the spec cannot describe concrete task commands without
it.

### 2. Configuration mechanism — recommend pydantic-settings with `SecretStr`

Recommended (from the exploration, approach 1): a `Settings` object built with pydantic-settings,
where the service token field is typed `SecretStr`. Rationale:

- A missing required field raises at construction time, which is the natural implementation of "fail
  at startup" — no hand-rolled presence check needed.
- `SecretStr` masks the value in `repr()`/`str()`, which is a structural defense (not just
  discipline) against the "never in logs" requirement — though not a complete one; see Risks.
- Item #2 (token auth) extends the same `Settings` object rather than inventing a second
  configuration path.

Trade-off acknowledged: this adds a dependency before the dependency-manager decision is finalized.
The alternative (plain `os.environ` reads with manual checks) has no new dependency but makes secret
masking manual discipline exactly where the PRD is strictest, and requires hand-rolling the
fail-at-startup message. This proposal recommends pydantic-settings; final confirmation belongs to
spec/design.

### 3. `spawn` start method placement and ordering

Place `multiprocessing.set_start_method("spawn", force=True)` as the first executable statement at
module import time in `main.py`, before importing any application module that could transitively
create a process or connection. This is a hard ADR 0012 requirement, not a preference.

**Convention this change establishes for later items**: the `spawn` ordering guarantee is only real
if configuration and engine construction stay **lazy** everywhere else in the app — inside a lifespan
handler or memoized on first use, never as a module-level side effect. Item #5 (SQL Server engine)
and item #4 (registry population) MUST follow this convention when they are built, or they risk
creating a connection before `set_start_method` runs, silently breaking the ADR 0012 guarantee this
change exists to establish. This proposal documents the convention; enforcing it in code belongs to
those later items (and to item #13's architecture-invariant CI checks).

**Re-entrancy under test**: Strict TDD means `app.main` will be imported repeatedly by the pytest
suite, and `set_start_method` called more than once (or after a process context is already active)
raises `RuntimeError`. This needs a deliberate approach — e.g., a guarded call
(`if multiprocessing.get_start_method(allow_none=True) != "spawn"`) or a test fixture that isolates
the call — to be worked out at spec/design time. This proposal flags it as a **must-resolve** design
question, not a decision made here.

### 4. Single Uvicorn worker

ADR 0012 ("Un solo worker de API") makes `EJECUCIONES_MAX` the sole concurrency knob. Any deployment
scaffolding this change adds (run scripts, documented Uvicorn invocation, Dockerfile if any) MUST NOT
default to `--workers N` or introduce Gunicorn. If this change ships no deployment scaffolding at
all, that MUST be stated explicitly rather than left implicit, since silence here is exactly the kind
of gap that produced H-08.

### 5. Python version floor

Python 3.11 is the floor. Per ADR 0012's own text ("Consecuencias"), this is **no longer a
consequence of the spawn/process mechanism** (that dependency, `max_tasks_per_child`, disappeared
with the pool rewrite) — it is retained "por soporte vigente y tipado moderno" as an independent
platform decision. `pyproject.toml`'s `requires-python` should record `>=3.11` and MUST NOT cite ADR
0012 as the reason in code comments or docs; the reasoning is "current support + modern typing," full
stop.

### 6. Health check implementation

An unauthenticated `GET` route returning 200 with a minimal liveness payload, wired through the app
factory so it does not depend on any router that later items add. No SQL Server call, no registry
lookup, no dependency injection of anything item #4/#5 will introduce.

### 7. Platform neutrality

`BACKLOG.md` prerequisite #0 (Linux container vs. native Windows service) is unresolved and explicitly
not this change's problem. Configuration and process-management code added here MUST stay
platform-neutral (no OS-specific paths, no assumption of a particular init system) so that decision
can resolve later without reopening this change.

## Acceptance concerns (explicit, non-negotiable)

- **Token secrecy**: the token MUST NOT appear in logs, traces, or error messages — not even
  partially — including the startup-failure message when the token is absent. This needs a concrete
  test asserting the token string never appears in captured startup output, not just reliance on
  `SecretStr`'s default masking (naive JSON serialization or `.get_secret_value()` misuse can still
  leak it).
- **Health check independence**: a test asserting the health check endpoint succeeds with zero
  external dependencies reachable (no DB connection attempted) is required, precisely because H-08's
  resolution depends on that independence holding structurally, not by convention.
- **Fail-closed startup**: a test asserting the app fails to start (raises/exits, does not silently
  continue) when the token environment variable is unset or empty.

## Open decisions to carry into spec/design (not settled here)

1. **Dependency manager**: pip / poetry / uv — recommend deciding before task-level commands are
   written, since it affects every subsequent change's task instructions.
2. **Configuration mechanism**: pydantic-settings + `SecretStr` recommended above; needs explicit
   confirmation at spec/design.
3. **`set_start_method` re-entrancy strategy under repeated test-suite imports**: flagged, not solved.
4. **ADR 0016 authorship**: recommend a new local ADR resolving H-08 as documented above; this
   proposal does not create it.
5. **Deployment target** (container vs. native Windows service, prerequisite #0): out of this
   change's control; configuration must stay neutral to it.
6. **Health check response shape** (path, exact payload): no document specifies these; spec phase
   should pick a concrete path (e.g. `/salud` or `/health`) and payload shape.

## Rollback plan

This change adds new files only (`pyproject.toml`, tooling config, `app/main.py`, `app/config.py` or
equivalent, and their tests) and touches no existing runtime, since none exists yet. Rollback is
`git revert` of the change's commit(s) or deletion of the added files — there is no data migration,
no schema change, and no in-flight state to reconcile. Risk is limited to leaving the repository
without a working skeleton again, i.e. reverting to the current documentation-only state that already
exists today. No external system (SQL Server, the portal) is touched by this change, so rollback has
no cross-system blast radius.

## Estimated size against the 400-line review budget

Rough estimate, tooling scaffolding included:

| Area | Estimated changed lines |
|---|---|
| `pyproject.toml` + tooling config (ruff/mypy/pytest sections) | ~60–90 |
| `app/main.py` (app factory, lifespan stub, `spawn` call, health route wiring) | ~40–70 |
| `app/config.py` or equivalent (Settings, token field) | ~30–50 |
| Health check route module | ~15–25 |
| Tests (startup failure, token-not-in-logs, health check independence, spawn ordering) | ~120–180 |
| Misc (`.gitignore`, README stub, CI-less local run docs if any) | ~20–40 |
| **Total** | **~285–455** |

This estimate straddles the 400-line budget. Given Strict TDD requires the test files themselves
(the largest single bucket above), recommend flagging this to the user at spec/design time as a
likely candidate for the `ask-on-risk` delivery strategy — either accept the overage explicitly or
split tooling scaffolding into its own reviewable unit ahead of the application skeleton. This
proposal does not decide that split; it surfaces the number honestly as required.

## Proposal question round

Per the interactive-mode contract, before finalizing scope and approach further, the following
product-shaping questions would sharpen this proposal. This session could not pause for a live
back-and-forth mid-execution, so they are recorded here for the user to answer, skip, or redirect
before spec/design proceeds — the assumptions below are what the proposal currently rests on absent
answers.

1. **Health check consumers**: who/what will actually poll this endpoint (container orchestrator
   liveness probe, a manual ops check, both)? This affects whether "liveness-only, no DB" is
   sufficient forever or whether a future readiness variant (item #11's territory) needs to be
   anticipated in the route's URL/versioning scheme now. *Assumption if unanswered*: a generic
   orchestrator liveness probe; no readiness variant is anticipated by this change.
2. **ADR 0016 ownership**: should this session draft ADR 0016 itself as a fast-follow once the
   proposal is accepted, or does ADR authorship belong to a separate, explicit request? *Assumption if
   unanswered*: ADR 0016 is recommended but not authored by this change; a separate step creates it.
3. **Dependency manager preference**: does the team already lean toward one of pip/poetry/uv for
   other reasons (existing CI runners, internal tooling, team familiarity) that this repo should
   match, or is this a green-field choice for the spec phase? *Assumption if unanswered*: left fully
   open for spec/design to decide on technical merits alone.
4. **Budget overage tolerance**: given the ~285–455 line estimate straddles the 400-line
   `ask-on-risk` budget, is a single change acceptable if it lands near or over 400 lines because the
   test suite legitimately needs that size under Strict TDD, or should tooling scaffolding be split
   into its own change ahead of the application skeleton? *Assumption if unanswered*: proceed as one
   change and flag the overage explicitly at delivery time per `ask-on-risk`.
5. **Health check path/shape**: any existing convention from the wider Portal ecosystem (e.g. a
   standard `/health` or `/healthz` path other Portal services use) that this service should match for
   consistency, or is this service free to choose? *Assumption if unanswered*: spec phase chooses a
   path with no cross-service convention constraint.

If the user wants a second round after answering these, or wants to correct the framing of any
question above, that is welcome before spec/design begins.

## Decisions resolved after the proposal question round

The user answered the round above. These answers are **settled** and supersede the corresponding
"Open decisions to carry into spec/design" entries and the "assumption if unanswered" defaults.

1. **Dependency manager: `uv`.** `pyproject.toml` plus `uv.lock`. Every task-level command in this
   change and in later changes is written against `uv` (for example `uv run pytest`). Open decision #1
   is closed.
2. **Delivery: one single change, size exception accepted.** The user explicitly accepted
   `size:exception` for this change rather than splitting the tooling scaffolding into its own unit.
   The session `delivery_strategy` is therefore `exception-ok` for this change: the tasks-phase
   forecast must still report the real number honestly, but it does not stop to ask again. Question 4
   of the round is closed.
3. **ADR 0016 is authored inside this change.** This change writes `adrs\0016-*.md` resolving
   `REVISION-ADVERSARIAL.md` finding H-08 as documented in the "Decision: H-08" section above, in the
   same MADR format as the existing local ADRs 0011–0015, and updates H-08's status in
   `REVISION-ADVERSARIAL.md` accordingly. Open decision #4 and question 2 of the round are closed.
   The ADR's line count counts toward this change's size.
4. **Configuration mechanism: pydantic-settings with `SecretStr`**, as recommended. Open decision #2
   is closed; design still owns the concrete `Settings` shape.
5. **Health check consumers and path**: no cross-service convention was supplied, so questions 1 and 5
   keep their stated assumptions — a generic orchestrator liveness probe, no readiness variant
   anticipated, and the spec chooses the concrete path and payload with no external constraint.

Still open and unchanged: `set_start_method` re-entrancy strategy under repeated test-suite imports
(open decision #3 — design must solve it), and the deployment target (open decision #5 — external
prerequisite #0; configuration stays platform-neutral).
