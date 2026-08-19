# Exploration — Admisión acotada y ejecución en proceso dedicado (ADR 0012)

- **Change**: `admision-acotada-y-proceso-dedicado`
- **Source**: `BACKLOG.md` item #8
- **Depends on**: #3 (`contrato-de-errores-tipificados`), #4 (`interfaz-procesador-y-registry`), #6 (`recepcion-y-ciclo-de-vida-de-temporales`) — all archived and shipped
- **Governing ADR**: `adrs/0012-ejecucion-en-procesos-dedicados.md` (rewritten mechanism — no `ProcessPoolExecutor`, no pool of any kind)
- **Methodology**: Strict TDD disabled. Behavioural tests only.

## Current State

### 1. `spawn` fixation — already done, item #1 shipped it

`app/arranque.py:20-43` (`fijar_metodo_arranque`) calls `multiprocessing.set_start_method("spawn", force=True)`, idempotently, and raises `ArranqueInseguroError` if the postcondition doesn't hold. It is invoked from `app/__init__.py:9-11`, which the docstring calls out as LOAD-BEARING: importing `app` (the package) runs this before any submodule (`main.py`, `recepcion.py`, etc.) can execute, which is a language guarantee (CPython initializes a parent package first), not an ordering convention. `tests/test_arranque_spawn.py` proves this in a fresh subprocess interpreter, including an audit-hook test (`test_ninguna_creacion_previa_al_spawn`) that fails if any `os.fork`/`socket.connect`/etc. happens under a start method other than `spawn`. **Item #8 needs zero work here — this precondition is fully satisfied and tested.**

### 2. `app/core/configuracion.py` — `EJECUCIONES_MAX`/`TIMEOUT_EJECUCION` do not exist yet

Current `Configuracion(BaseSettings)` (lines 21-40) exposes exactly one field: `token_servicio: Annotated[SecretStr, Field(min_length=1)]`. The module docstring (lines 3-6) explicitly says: *"the other operational parameters (`EJECUCIONES_MAX`, `TIMEOUT_EJECUCION`, etc.) belong to item #8 and are not introduced here."* Pattern to follow: `model_config = SettingsConfigDict(extra="forbid", frozen=True)`, values sourced from process env only (no `.env` file), validated by pydantic, and the single call site `obtener_configuracion()` (`@lru_cache(maxsize=1)`) that converts `ValidationError` into `ConfiguracionInvalida` without leaking `input_value`. Item #8 must add both fields to this same class (positive-int constraints; `TIMEOUT_EJECUCION` needs a documented/enforced relationship to "strictly less than the portal's 2-minute cutoff" — TECH-DESIGN.md:259 calls this "verifiable by configuration").

### 3. Typed-error contract and cross-process types

`app/core/errores.py`: `TipoError` (`StrEnum`, `errores.py:32-39`) is a **closed 5-value enum** — `FORMATO`, `TAMANO`, `CONTENIDO`, `CANTIDAD`, `CLAVE_INEXISTENTE` — with per-type `contexto` `TypedDict`s unioned into `Contexto` (lines 92-99), one `ErrorTipificado` exception base (`ClassVar[TipoError]` + `contexto`), one exception handler (`responder_error_tipificado`, lines 209-215) mapped through `_ESTADO_HTTP` (422 for the four correctable ones, 500 for `CLAVE_INEXISTENTE` per ADR 0018). **Item #8's failure modes (saturation 503, child death, timeout) have no slot in this enum and the ADR is explicit they must not get one** (see "Approaches / open questions" below).

`app/core/interfaz.py`: `Procesador(ABC)` with `clave: str`, abstract `validar(archivos) -> ErrorTipificado | None` and `procesar(archivos) -> list[ArchivoSalida]`. Its docstring (lines 33-37) has an **open caveat addressed explicitly to item #8/`core/ejecucion.py`**: no document decides whether the child process re-derives the `Procesador` instance (re-import + registry lookup) or receives a serialized instance. What is fixed: only paths and scalars cross, never file bytes (ADR 0012). Item #8 must resolve this and update that docstring note.

`app/core/tipos.py`: `ArchivoEntrada`/`ArchivoSalida` are `@dataclass(frozen=True, slots=True)` holding only `str`/`int`/`Path` fields — already `spawn`-picklable by construction, and the docstring (lines 6-7) says so explicitly ("so they can cross the future process boundary of item #8 without trouble").

`app/registry.py`: `REGISTRY: dict[str, Procesador] = {}` — empty until items #12/#16. Whatever the child does to obtain a `Procesador` instance must work against an *importable* registry module with **no import-time side effects** (ADR 0012 Consequences, last bullet: `spawn` obliga a que el módulo de la aplicación sea importable sin efectos secundarios).

### 4. `app/recepcion.py` / `app/core/temporales.py` — where admission must sit

`app/recepcion.py:106-190` (`recibir`) already implements a two-phase structure, explicitly designed for exactly this kind of "reject before paying any cost" precondition:

- **Phase 1, before `with reservar()`**: resolve contract, validate cantidad/formato/declared tamaño. A rejection here costs neither `mkdtemp` nor a byte written.
- **Phase 2, inside `with reservar()`** (`app/core/temporales.py:91-110`): bounded copy, measured total, ZIP inspection.

The route signature is `async def recibir(clave_procesador: str, archivos: Annotated[list[UploadFile], File()])` — **`archivos: list[UploadFile]` is a body parameter FastAPI resolves before the handler body runs**, i.e. before Phase 1's own code executes. This is the concrete conflict with ADR 0012's requirement that admission happen "before reading the body." The only place in this codebase that has ever produced a response strictly before body parsing is `app/core/seguridad.py`'s `AutenticacionDeBorde` — a raw ASGI middleware wrapped around the `/interno` `Mount` (`app/main.py:39-43`) that inspects the `headers` entry of the ASGI `scope` and never calls `receive()` (`seguridad.py:104-107`, docstring lines 12-13: decide con los headers del scope y nada más, nunca llama a `receive()`, así que el 401 sale antes de que exista un solo byte de cuerpo). A FastAPI `Depends()` on the route, by contrast, runs *after* Starlette has already started parsing `multipart/form-data` into `UploadFile`s to bind the `archivos` parameter — i.e. it is too late by the ADR's own ordering requirement.

`temporales.py`'s `reservar()` context manager (lines 91-110) already has the exact `try/finally` shape item #8's semaphore release needs to compose with: acquire before `reservar()`, `try: ... finally: release`, with `reservar()` nested inside (or item #8's block wrapping `reservar()`).

### 5. Where 503 has to be produced

`app/core/validacion_http.py` currently only handles `RequestValidationError` -> bare 422 (no body, explicitly to avoid echoing rejected input — same pattern as the 401 handler). There is **no existing precedent for a bare-status response with no typed envelope other than 401 and this 422** — both are exactly the shape a 503 needs (status-only, no `tipo`/`contexto` JSON body), since ADR 0012's Consequences section is explicit that this 503 is not a typed error and cannot be one (PRD.md:139, ADR 0012 lines 199-204). The existing dispatch pattern (`app.add_exception_handler(SomeExceptionClass, handler_fn)`, one exception type -> one handler -> one response-construction site) is directly reusable: item #8 needs its own non-`ErrorTipificado` exception class (e.g. raised when `acquire(blocking=False)` fails) and its own handler registered in `crear_app()`, parallel to `registrar_manejador_401`/`registrar_manejador_validacion`/`registrar_manejador_errores` (`app/main.py:33-35`).

### 6. Existing test infrastructure

- `tests/ayudas/subproceso.py` (`ejecutar_snippet`) runs a code snippet in a **fresh `sys.executable` interpreter** via `subprocess.run(..., shell=False)` — built for proving ordering/leak invariants that the pytest process's own polluted `multiprocessing` state would falsely pass. It is generic (any snippet) and is a plausible pattern to reuse for a behavioural test of "spawn survives across the item #8 code path," but it does **not** address testing `Process.join()`/`kill()`/timeout/child-death directly — those need their own harness.
- `tests/conftest.py` has exactly two fixtures: `token_sentinela` (env var) and `limpiar_cache_configuracion` (clears the `obtener_configuracion` LRU cache). No dependency-override fixtures, no subprocess-timeout fixtures, no semaphore-state fixtures exist yet.
- `tests/test_recepcion.py` establishes the pattern item #8's HTTP-level tests will likely follow: build the real `app.main.crear_app()`, wrap in `TestClient(..., raise_server_exceptions=False)`, inject state by monkeypatching module-level tables (`contrato_modulo._TABLA_CONTRATOS`) rather than FastAPI `dependency_overrides` — there is **no existing use of `app.dependency_overrides` anywhere in the test suite** (confirmed via search across `tests/`), which is a data point against choosing a `Depends()`-based admission mechanism for testability parity with the rest of the suite (though it doesn't rule it out).
- Nothing in the repo today spins up a real `multiprocessing.Process`, calls `.join(timeout=...)`, or calls `.kill()`. Item #8 is the first place this pattern enters the codebase.

## What item #8 must add

Per BACKLOG.md item #8 scope line and ADR 0012's Decision section:

1. **Configuration**: `EJECUCIONES_MAX` (positive int) and `TIMEOUT_EJECUCION` (duration, strictly less than the portal's 2-minute cutoff) added to `Configuracion` in `app/core/configuracion.py`.
2. **Admission semaphore**: `threading.BoundedSemaphore(EJECUCIONES_MAX)`, acquired with `acquire(blocking=False)`. No free slot -> an exception/mechanism that resolves to an immediate 503, with the body never read and no temp file written. Must sit ahead of FastAPI's own body-parsing of `archivos: list[UploadFile]` — see open question A below on *how*.
3. **Spawn process per execution**: `multiprocessing.Process(target=..., args=...)` created fresh per request, never reused, never pooled. Relies on the already-fixed `spawn` start method (section 1 above) — no new work needed there beyond making sure whatever module the child imports at spawn time has no import-time side effects.
4. **Pipe result channel**: `multiprocessing.Pipe()` for the child -> parent result. ADR 0012 (lines 103-104): the result is either output-file paths, the typed error, or the module's exception plus traceback — **never file bytes**. Everything sent across the `Pipe` must be picklable under `spawn` (already true for `ArchivoEntrada`/`ArchivoSalida`, per section 3 above; the traceback-carrying exception case needs its own picklable wrapper, since arbitrary exception objects with live tracebacks or unpicklable attributes are not guaranteed to survive `Pipe` serialization).
5. **`join(TIMEOUT_EJECUCION)` with real `kill()`**: parent waits bounded, and on timeout calls `Process.kill()` (SIGKILL-equivalent — not `.terminate()`, which the ADR explicitly rejects as insufficient given the known limitation of `future.cancel()`, per REVISION-ADVERSARIAL.md H-07) and confirms real termination, not just a client-side timeout on `.join()`.
6. **Slot release on all four paths**: success, module-raised typed error (crossed via Pipe, re-raised in the parent so the existing `ErrorTipificado` handler serializes it), module exception/traceback, and timeout/kill. ADR 0012 and TECH-DESIGN.md (line 109) are explicit that this release lives in the **same** `try/finally` that also owns temp cleanup — meaning item #8's mechanism composes with (or is subsumed by) item #10's pipeline `try/finally`, not a second independent one.
7. **Child-death handling**: an anomalous `exitcode` (e.g. OOM-killed) must be distinguished from a clean `0` and from a `kill()`-induced termination, and turned into a controlled error where the response still arrives and the API worker does not die (ADR 0012's failure-translation table, lines 140-146) — not a re-raised `BrokenProcessPool`-style cascading failure (exactly the H-01 defect the pool mechanism had and this ADR replaces).
8. **A dedicated exception type plus handler for the 503** — parallel to `TokenInvalido`/`responder_token_invalido` in `seguridad.py` — registered in `crear_app()`.

TECH-DESIGN.md (line 69) and ADR 0011 (line 37) already name the target module: **`app/core/ejecucion.py`** — admission semaphore plus dedicated process (ADR 0012). This is a pre-existing architectural decision, not an open question for this exploration to resolve.

## Approaches / open questions

### A. Where does the semaphore acquire, given it must precede body-reading?

`app/recepcion.py`'s current route signature (`archivos: Annotated[list[UploadFile], File()]`) has FastAPI parse the multipart body to bind that parameter *before* the handler body's own two-phase logic runs — so a semaphore acquired as the first statement inside `recibir()` would already be too late by the ADR's own wording. Three real options:

1. **Raw ASGI middleware**, following the exact precedent of `AutenticacionDeBorde` (`app/core/seguridad.py:83-107`) — inspects the ASGI scope and decides with `blocking=False` before calling `receive()` and before delegating to the inner app, so no multipart parsing has started. Strongest match for "before reading the body," reuses an established pattern in this codebase, but needs to be scoped only to processor routes (not `/salud`), meaning it either needs its own `Mount` (alongside the existing `AutenticacionDeBorde` one — order matters: is admission checked before or after the token?) or a path-based guard inside a shared middleware.
2. **FastAPI `Depends()` on the route**: idiomatic, easy to unit-test, easy to override — but it runs after FastAPI has already resolved the other declared parameters, and this codebase has **no existing precedent** of `Depends()` gating admission before body parsing; recepcion.py's own two-phase design shows the ordering concern was already understood and expressed in route-body code, not in a dependency.
3. **Inline in the route function**, restructuring the parameter binding so the raw request is taken first (e.g. `request: Request` and parsing form data manually only after acquiring the semaphore) — avoids adding a new middleware layer but pushes multipart-parsing logic (currently handled implicitly by `UploadFile`/`File()`) into `recepcion.py`, a bigger and riskier change to a module that item #7 already restructured once.

Recommendation leaning: **(1), a middleware** — it is the only option proven in this codebase to produce a response before Starlette touches the request body, and it keeps `recepcion.py`'s existing two-phase structure untouched. This needs explicit resolution in the proposal, not assumed here.

### B. Standalone `core/ejecucion.py` vs. wiring into `recepcion.py`

Already decided by prior ADRs, not open: TECH-DESIGN.md's structure diagram and ADR 0011 both name `app/core/ejecucion.py` as the admission semaphore plus dedicated process (ADR 0012), parallel to `validaciones.py`, `empaquetado.py`, `temporales.py`. Item #8 should ship this as its own `core/` module (semaphore plus spawn/Pipe/join/kill mechanics as composable functions or context managers), analogous to how item #6 shipped `temporales.reservar()` as a context manager that item #7's `recepcion.py` then composed with. Item #10 (the pipeline) is the eventual *orchestrator* that calls into `ejecucion.py`'s primitives inside its own step sequence — item #8 must not itself build the 9-step pipeline or wire `ejecucion.py` into a route.

### C. How do timeout and child-death get reported, given they have no typed-error slot?

ADR 0012's Consequences section registers this as an **open risk it deliberately does not resolve**: the ADR does not invent a new type, because the vocabulary was fixed by the inherited ADR 0006, and it leaves the gap recorded as an open risk in the Technical Design. Concretely, item #8 needs *some* response shape for "the module hung and was killed" and "the child died anomalously (OOM)" that is neither one of the 5 `TipoError` values nor silently swallowed. Given the `TipoError` enum is explicitly closed (item #3's design goal: adding a sixth member requires four coordinated, visible edits) and ADR 0012 forbids stretching it, the two live options are:

- A **second, parallel exception plus handler pair** (like the proposed 503 one), distinct from `ErrorTipificado`, mapped to some server-error status (500 or 503, undecided) — consistent with how the 401/422/503 cases are already handled outside the `TipoError` vocabulary.
- **Defer the exact response shape and portal-facing contract entirely to item #10** — item #8 only needs to guarantee that `ejecucion.py`'s primitives *raise something distinguishable* (e.g. two new exception classes: one for timeout, one for anomalous child exitcode) and that the slot always releases; the pipeline (item #10) then decides the final HTTP translation, since ADR 0012 itself assigns the portal-facing handling of these cases to item #10 as mandatory work (line 204) and BACKLOG.md's dependency table has item #10 depending on #8, not the reverse.

This exploration recommends deferring the final HTTP status and body decision for timeout and child-death to item #10, while item #8 ships the distinguishable, non-`TipoError` exceptions that make that decision possible later without another refactor. This keeps item #8's proposal from silently absorbing item #10's scope.

## Scope boundary

**Belongs to item #8:**

- `app/core/configuracion.py`: add `EJECUCIONES_MAX`, `TIMEOUT_EJECUCION`.
- `app/core/ejecucion.py` (new): the admission semaphore, the spawn `Process`/`Pipe`/`join`/`kill` mechanics, slot release guaranteed on all four paths, child-exitcode inspection, and the exception types representing no free slot (503), timeout, and anomalous child death.
- Whatever mechanism (middleware, most likely — see Approach A) makes admission run before body-reading, registered in `app/main.py`'s `crear_app()`.
- The 503 exception plus handler pair, parallel to the existing 401/422 pattern.
- Resolving `interfaz.py`'s open caveat (how the child obtains a `Procesador` instance) and updating that docstring.
- Behavioural tests proving: 503 without body read and without temp file on saturation; slot release across success, typed error, exception, and timeout; real process termination on timeout (not just returned control); anomalous exitcode does not crash the API worker or wedge remaining capacity.

**Belongs to item #10 (pipeline, the 9 steps in order, owner of the `try/finally`):**

- Actually wiring `ejecucion.py`'s primitives into the full 9-step sequence (TECH-DESIGN.md lines 88-103) alongside contract lookup, validation, and packaging.
- The single top-level `try/finally` that unifies temp cleanup and slot release across the whole request lifecycle — item #8 must produce composable pieces, not its own competing `try/finally` that item #10 then has to unwind.
- Deciding the final response the portal receives for timeout and child-death (not just that they are distinguishable — see open question C).
- Wiring `recepcion.py`'s current `NotImplementedError` seam into a real response.

**Belongs to item #14 (operational logging):**

- Actually logging saturation rejections (TECH-DESIGN.md:261-262). Item #8 must make the 503 path reachable and observable (e.g. raise a distinguishable exception) but does **not** own structured logging output — item #14 depends on #10, which depends on #8.

**Explicitly out of scope for item #8** (per ADR 0012 Consequences and BACKLOG.md):

- Calibrating the actual value of `EJECUCIONES_MAX` (item #17, needs real infrastructure from item #0; until then it is a conservative estimate, not a measurement).
- Measuring the per-request cost of `spawn` on Linux (item #17).
- A real RAM ceiling on the child process (Job Object on Windows, cgroup or `RLIMIT_AS` on Linux) — ADR 0012 Consequences is explicit that this mechanism does not by itself impose a RAM ceiling on the child, and the ZIP-declared-size check (item #7, already shipped, H-04 still partially open) remains the first line of defense, not this item's job to replace.
- The portal-side 503 UX and messaging — PRD.md:355-357 and BACKLOG.md's prerequisites table assign that to the portal's own item #10 (a different repository and backlog, not to be confused with this repo's item #10).

## Risks

- **Testability of the `kill()`, timeout, and child-death paths.** No existing fixture spins up a real child process with a controlled hang or a controlled anomalous exit. These tests are inherently slower and flakier than the rest of the (currently 184-test, fast) suite; a naive `time.sleep(TIMEOUT_EJECUCION + 1)` test could make the suite meaningfully slower unless `TIMEOUT_EJECUCION` is configured very small for tests specifically. Simulating an anomalous exitcode (OOM) portably (Windows Server 2019, no Job Object today) needs a deliberate child that calls `os._exit(N)` with a nonzero code rather than actual memory exhaustion, which only proves exitcode handling, not real OOM behaviour.
- **Windows vs Linux `spawn` behaviour.** `spawn` is already the only start method in play (good — no fork-vs-spawn divergence to design around), but child-termination semantics still differ: `Process.kill()` maps to `TerminateProcess` on Windows and `SIGKILL` on POSIX; both are real kills, but exitcode conventions differ (Windows returns the exit code passed to `TerminateProcess`, POSIX encodes signal death as a negative number) — the exitcode-inspection logic in `ejecucion.py` needs to handle both without assuming a Linux-only convention, and the dev/CI environment here is Windows Server 2019, so Linux-specific exitcode paths cannot be exercised locally.
- **Cost of measuring nothing.** Item #17, not #8, owns calibrating `EJECUCIONES_MAX` and measuring `spawn` overhead against the 15s p95 budget — item #8 must not invent a default value under the illusion it is load-bearing; ADR 0012 and TECH-DESIGN.md both flag this as a conservative estimate, not data.
- **Interaction with item #10's not-yet-built `try/finally`.** Item #8 ships composable primitives, but if the proposal locks in a specific control-flow shape (e.g. a context manager whose `__exit__` both releases the slot and re-raises) too rigidly, item #10 might be forced into an awkward composition later. The design phase should keep the surface of `ejecucion.py` as a small number of narrow, independently testable primitives (acquire/release, run-in-child, translate-exitcode) rather than one monolithic handle-everything function.
- **The open caveat in `interfaz.py` is a real design decision, not a formality.** Deciding between "the child re-imports and does a registry lookup" and "the child receives a serialized `Procesador` instance" affects the signature of item #8's `Process` target function and what must be picklable; it should be resolved early in design, since it changes the shape of the args crossing to `multiprocessing.Process`.
- **CodeGraph unavailable during exploration.** `.codegraph/` does not exist in this repo and the exploration phase had no Bash tool to initialize it; all findings above came from direct file reads and searches, not from CodeGraph's call-graph or blast-radius view. A later phase with Bash access should initialize CodeGraph before further structural work on this change.

## Recommendation

Proceed to `sdd-propose` with scope limited to: the `app/core/configuracion.py` additions, the new `app/core/ejecucion.py` module, the admission-precedes-body-read mechanism (likely middleware), the 503 exception plus handler pair, and behavioural tests for the four release paths — explicitly excluding pipeline orchestration (#10) and saturation logging (#14). The open question about middleware vs alternatives for admission ordering (Approach A) and the child-instance-derivation caveat in `interfaz.py` should be resolved as explicit decisions in the proposal or design phase.

## Ready for Proposal

Yes. Dependencies (#3, #4, #6) are archived and shipped; the governing ADR (0012, revised) is unambiguous about the mechanism; the target module name is already fixed by prior ADRs (`app/core/ejecucion.py`); and the scope boundary against items #10 and #14 is clear enough to write a proposal without re-litigating architecture. The main decision still needed before `sdd-design` is *how* admission precedes body-reading (middleware recommended) and how the child obtains its `Procesador` instance.
