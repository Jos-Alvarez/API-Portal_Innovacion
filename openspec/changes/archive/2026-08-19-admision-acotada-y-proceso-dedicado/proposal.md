# Proposal: Bounded Admission and Dedicated-Process Execution (ADR 0012)

## Intent

`app/core/configuracion.py:4` reserves `EJECUCIONES_MAX`/`TIMEOUT_EJECUCION` for this item and
nothing implements them yet; `app/core/interfaz.py:33-37` carries an open caveat addressed to this
item; `app/recepcion.py` has no admission gate at all. Today every accepted request runs
unconditionally — there is no ceiling on concurrent executions and no isolation between one
module's execution and another's. ADR 0012 (revised — the original `ProcessPoolExecutor` mechanism
was replaced after an adversarial review found it does not isolate a hung/OOM-killed child) fixes
the target mechanism: a non-blocking admission semaphore that rejects with an immediate 503 instead
of queueing, and one `multiprocessing.Process` per execution, spawned fresh, joined with a hard
timeout, and really killed — never pooled, never reused. Why now: items #3 (typed errors), #4
(`Procesador` interface), #6 (temp-file reception) are archived and shipped; this is the next
backlog item and item #10 (the pipeline) depends on it.

## Scope

### In Scope

- `app/core/configuracion.py`: add `EJECUCIONES_MAX` (positive int) and `TIMEOUT_EJECUCION`
  (duration), both conservative placeholders — not measured data (item #17 owns calibration).
- New `app/core/ejecucion.py`: the admission semaphore, spawn/`Pipe`/`join`/`kill` mechanics as
  composable primitives, slot release guaranteed on all four paths, exitcode inspection, and the
  exception types for "no cupo" (503), timeout, and anomalous child death.
- An ASGI middleware that makes admission run strictly before body-reading, registered in
  `app/main.py`'s `crear_app()`.
- The 503 exception + handler pair, parallel to the existing 401/422 bare-status pattern.
- Resolving `interfaz.py`'s open caveat on how the child obtains its `Procesador` instance, and
  updating that docstring.
- Behavioural tests for: 503 with no body read and no temp file on saturation; slot release across
  success, typed error, module exception, and timeout; real process termination on timeout (not a
  client-side `.join()` return); anomalous child exitcode not wedging remaining capacity.

### Out of Scope

- The 9-step pipeline and its owning `try/finally` (item #10). `ejecucion.py` ships primitives item
  #10 composes into that single `try/finally` — not a competing one.
- The final HTTP shape for timeout/child-death (item #10 decides; see Decision 2).
- Structured operational logging of saturation rejections (item #14).
- Calibrating `EJECUCIONES_MAX` or measuring `spawn`'s real cost (item #17).
- A real RAM ceiling on the child (Job Object / cgroup / `RLIMIT_AS`) — ADR 0012 Consequences is
  explicit this mechanism does not impose one by itself; the ZIP declared-size check (item #7)
  remains the first line of defense.
- Portal-side 503 UX (different repository).

## Capabilities

### New Capabilities

- `bounded-execution`: admission gate (semaphore, non-blocking, before body-reading) and
  dedicated-process execution (spawn per request, `Pipe` result channel, hard `join`+`kill`
  timeout, exitcode-based failure translation, guaranteed slot release on all four exit paths).

### Modified Capabilities

- `configuration`: `Configuracion` gains `EJECUCIONES_MAX`/`TIMEOUT_EJECUCION`, both required,
  positive, with `TIMEOUT_EJECUCION` constrained below the portal's 2-minute cutoff.
- `processor-interface`: `Procesador`'s docstring caveat on child-instance derivation is resolved
  and rewritten (no behavioral change to the ABC's two abstract methods).

## Decisions

### Decision 1 — Admission mechanism and its position relative to auth

**Ship a raw ASGI middleware**, following the exact precedent of `AutenticacionDeBorde`
(`app/core/seguridad.py:83-107`, mounted at `app/main.py:39-43`): it is the only mechanism in this
codebase proven to produce a response before Starlette touches the request body. A FastAPI
`Depends()` runs after multipart parsing has already started binding `archivos: list[UploadFile]`
— too late by ADR 0012's own wording ("antes de leer el cuerpo"). Restructuring `recepcion.py` to
parse the body manually was rejected: it duplicates logic `File()` already gives for free and adds
risk to a module item #7 already restructured once.

**Admission is checked after the token check, not before.** Both checks are body-free (the token
check reads only `scope["headers"]`; the semaphore is `acquire(blocking=False)`, no I/O), so
ordering them costs no extra latency and both still satisfy "before reading the body." Checking
admission first would let an unauthenticated caller consume a scarce execution slot merely by
sending a request with no valid token — a free denial-of-service surface against a resource this
ADR exists to protect. Checking auth first means only authenticated callers can ever occupy a slot,
consistent with `AutenticacionDeBorde` already being the outermost boundary for `/interno`. The
exact wiring (whether admission is a second middleware inside the same `Mount`, or a shared
middleware with a path guard so `/salud` is untouched, and how the slot releases when the inner ASGI
app finishes) is handed to `sdd-design`.

### Decision 2 — Failure reporting split (503 now, timeout/child-death deferred)

ADR 0012 is explicit: saturation-503, timeout, and child-death have no slot in the closed 5-value
`TipoError` enum and must not be forced into it (Consequences, lines 199-212). **This item ships
the 503 exception + handler pair only** (BACKLOG.md's scope line for item #8 names the 503
explicitly). For timeout and anomalous child death, this item ships **distinguishable non-`TipoError`
exception types** (e.g. one for timeout, one for anomalous exitcode) that guarantee the slot always
releases and the failure is never silently swallowed or re-raised as a generic 500 — but the final
HTTP status/body for those two cases is deferred to item #10, which BACKLOG.md's dependency table
already places downstream of this item. No sixth `TipoError` member is added.

### Decision 3 — How the child obtains its `Procesador` instance

**The child re-imports and looks up the registry by `clave`**, not a serialized instance. Rationale:
ADR 0012 Consequences already requires the application module tree be importable without
side-effects for `spawn` to work at all (`REGISTRY` is a plain module-level dict, empty until items
#12/#16, with no import-time side effects); re-deriving via `clave` means only a `str` — already a
scalar guaranteed picklable — crosses the process boundary as the "which processor" argument,
alongside the file paths. Serializing a `Procesador` instance would require every future concrete
processor to also be pickle-safe by construction (an invariant nothing currently enforces and that
could silently break when a processor gains a non-picklable attribute, e.g. a cached pandas object).
`interfaz.py:33-37`'s caveat is updated to record this as resolved, pointing at `core/ejecucion.py`.

### Decision 4 — `EJECUCIONES_MAX`/`TIMEOUT_EJECUCION` defaults are placeholders

Any default value shipped in `Configuracion` is a **conservative placeholder**, not measured data —
item #17 owns real calibration against infrastructure that does not exist yet. `TIMEOUT_EJECUCION`
must be constrained (via a pydantic validator, not a comment) to be strictly less than the portal's
2-minute cutoff, so the relationship is enforceable and verifiable by configuration
(TECH-DESIGN.md:259), not just documented.

## Approach

`app/core/ejecucion.py` ships as independently-testable primitives — not one monolithic
"handle everything" function — analogous to how item #6 shipped `temporales.reservar()` as a
composable context manager: (1) admission acquire/release, (2) run-module-in-child (spawn, `Pipe`,
`join(TIMEOUT_EJECUCION)`, `kill()` on timeout, exitcode translation), (3) the three exception types
(saturation, timeout, child-death). The admission middleware wraps only processor routes (never
`/salud`), sits alongside `AutenticacionDeBorde` inside/around the same `Mount`, checked after the
token. Item #10 later composes these primitives inside its own `try/finally` that also owns temp
cleanup — this item does not build a second, competing `try/finally`.

## Affected Areas

| Area | Impact | Description |
|---|---|---|
| `app/core/configuracion.py` | Modified | `EJECUCIONES_MAX`, `TIMEOUT_EJECUCION` fields + validator enforcing the 2-minute relationship |
| `app/core/ejecucion.py` | New | Admission semaphore, spawn/`Pipe`/`join`/`kill` primitives, exitcode translation, three exception types |
| `app/core/seguridad.py` or a new module | New/Modified | Admission ASGI middleware (exact placement resolved in design) |
| `app/main.py` | Modified | Register admission middleware after `AutenticacionDeBorde`; register the 503 handler |
| `app/core/interfaz.py` | Modified | Docstring caveat resolved (registry-lookup-by-`clave` decision recorded) |
| `tests/test_ejecucion.py` | New | Behavioural tests: 4 slot-release paths, real kill-on-timeout, anomalous exitcode, saturation 503 with no body/temp read |

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| No existing fixture spins up a real child with a controlled hang or anomalous exit; these tests are slower/flakier than the suite's current fast tests | Med | Configure `TIMEOUT_EJECUCION` very small in test env; a deliberate child calling `os._exit(N)` proves exitcode-handling without simulating real OOM |
| `Process.kill()` exitcode conventions differ Windows (`TerminateProcess` code) vs. POSIX (negative signal number); dev/CI here is Windows Server 2019, so POSIX paths cannot be exercised locally | Med | Exitcode-translation logic handles both conventions; POSIX-specific behavior documented as unverified-locally, not untested-in-principle |
| Admission-middleware placement (which `Mount`, path-scoping so `/salud` is unaffected, slot release when the inner ASGI app finishes) is still open at proposal time | Med | Explicitly handed to `sdd-design` as the concrete mechanics to lock down before implementation |
| Item #10's not-yet-built pipeline could be forced into an awkward composition if `ejecucion.py`'s surface is too rigid (one big function instead of narrow primitives) | Low | Approach section commits to narrow, independently-testable primitives, not a monolithic handler |
| Review budget (400 changed lines) is likely exceeded — see estimate below | High | Flagged for `ask-on-risk`; `sdd-tasks` must forecast and, if confirmed, recommend chained/stacked PR slices |

## Rollback Plan

Each piece is independently revertible: remove the admission middleware registration in
`app/main.py` (route returns to today's unconditional-execution behavior); delete
`app/core/ejecucion.py`; revert the `Configuracion` field additions (additive, so nothing downstream
in this item depends on their absence — item #10 is not yet wired to call `ejecucion.py`); revert
the `interfaz.py` docstring update. No schema, no migration, no persisted state.

## Dependencies

- `contrato-de-errores-tipificados` (#3, archived), `interfaz-procesador-y-registry` (#4, archived),
  `recepcion-y-ciclo-de-vida-de-temporales` (#6, archived) — all shipped, no open work needed from
  them.
- `spawn` fixation (`app/arranque.py`, item #1, archived) — already satisfied and tested; this item
  needs zero work there.
- No new runtime dependency. `multiprocessing`, `threading` are standard library.

## Changed-lines estimate

| Piece | Estimate |
|---|---|
| `app/core/configuracion.py` (2 fields + validator) | ~30-40 |
| `app/core/ejecucion.py` (semaphore, spawn/Pipe/join/kill primitives, exitcode translation, 3 exception types) | ~180-230 |
| Admission middleware + `app/main.py` wiring | ~60-90 |
| 503 exception + handler | ~25-35 |
| `interfaz.py` docstring update | ~10-15 |
| `tests/test_ejecucion.py` (4 release-path tests, real kill-on-timeout, anomalous exitcode, saturation-before-body/temp) | ~230-300 |
| **Total** | **~535-710** |

Above the 400-line session budget, consistent with this project's logged pattern of design-phase
forecasts running short. This is a first-pass proposal-phase estimate; `sdd-tasks` must re-forecast
against the actual work breakdown and apply the review-workload guard — chained/stacked PR slices
under `delivery_strategy: ask-on-risk`, or an explicit accepted `size:exception`.

## Success Criteria

- [ ] With all slots occupied, a new request receives 503 with zero bytes of body read and zero temp
      files written, verified by a test that asserts neither `mkdtemp` nor a spooled multipart part
      was created.
- [ ] The 503 path is checked after the token check, and an unauthenticated request never occupies a
      slot (verified: sending an invalid-token request while saturated still returns 401, not 503).
- [ ] The admission slot releases on all four paths: clean success, module-raised typed error,
      module exception/traceback, and timeout — verified by acquiring, exercising each path, and
      asserting the slot is available again.
- [ ] On timeout, the child process is actually terminated (`Process.kill()`, not just a returned
      `.join()`), confirmed by inspecting the process is no longer alive after the call.
- [ ] An anomalous child exitcode (simulated via `os._exit(N)`) does not crash the API worker, does
      not wedge remaining capacity, and produces a distinguishable exception (not a generic 500 with
      no information).
- [ ] `TipoError` remains exactly 5 values; no sixth member is introduced for saturation, timeout, or
      child-death.
- [ ] `EJECUCIONES_MAX`/`TIMEOUT_EJECUCION` are documented as conservative placeholders in code
      comments/ADR, not measured data.
- [ ] `TIMEOUT_EJECUCION` strictly less than the portal's 2-minute cutoff is enforced by a
      `Configuracion` validator, not only documented.
- [ ] `interfaz.py`'s open caveat is resolved in the docstring: child re-imports and looks up the
      registry by `clave`.

## Proposal question round

Auto execution mode — no interactive block was available, so these are decided-and-recorded rather
than asked live. Flagged here for explicit user review before `sdd-design` proceeds:

1. **Admission-before-or-after-auth.** Decided: after auth (Decision 1). If the business preference
   is actually "reject saturation even for unauthenticated traffic, accepting the DoS-slot-consumption
   risk," say so and this reverses.
2. **Timeout/child-death final HTTP shape deferred to item #10.** Decided: this item only ships
   distinguishable exceptions (Decision 2), not a response. If the business wants a temporary 503 or
   500 shipped now rather than deferred, say so — this would pull a slice of item #10's scope
   forward.
3. **Child re-import vs. serialized instance (Decision 3).** Decided: re-import + registry lookup by
   `clave`. This is primarily a technical/maintainability tradeoff, included here because it commits
   future processor authors (items #12/#16) to being importable without side effects — flag if that
   constraint conflicts with a known upcoming processor's needs.
4. **Placeholder defaults for `EJECUCIONES_MAX`/`TIMEOUT_EJECUCION` (Decision 4).** No specific
   numbers are proposed here on purpose — deferred to `sdd-design` as literal placeholder values
   pending item #17's calibration. If a rough starting number is wanted now, say so.
