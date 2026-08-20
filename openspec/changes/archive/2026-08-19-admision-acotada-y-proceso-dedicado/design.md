# Design: Bounded Admission and Dedicated-Process Execution

- **Change**: `admision-acotada-y-proceso-dedicado` (BACKLOG item #8)
- **Inputs**: `proposal.md` (**authoritative for the four locked decisions**; two of its factual premises
  are corrected by V4 and V7 below), `exploration.md`, `adrs/0012` (revised mechanism — **no pool of
  any kind**), `adrs/0011`, `adrs/0019`, `adrs/0020`, `adrs/0021`, `REVISION-ADVERSARIAL.md` (H-01,
  H-05, H-07), `TECH-DESIGN.md:250-262, 353-368`, and the shipped code read for this phase:
  `app/main.py`, `app/core/{seguridad,configuracion,errores,interfaz,tipos,temporales}.py`,
  `app/recepcion.py`, `app/registry.py`, `app/arranque.py`, `tests/conftest.py`,
  `tests/ayudas/subproceso.py`, `tests/test_recepcion.py`, `tests/test_seguridad_token.py`
- **Authority**: ADRs outrank every other document. Inherited `L:\App_Portal\adrs\0001`–`0010` outrank
  local `adrs\0011`–`0021`. **This change authors `adrs/0022`** — see §12 for the numbering evidence
  and for why an ADR is warranted rather than an amendment.
- **Methodology**: Strict TDD **disabled**. Behavioural tests only — no AST/structural tests, no chaos
  tests, no perturb-and-restore. `ruff` and `mypy --strict` still run. Every command goes through
  `uv run`.
- **Review budget**: the orchestrator passed **400**; `openspec/config.yaml:42` says **600**, raised on
  2026-08-18 with data. §11 forecasts against both and flags the conflict rather than picking silently.
  The slicing recommendation is identical under either number.

## 0. Verified facts this design rests on

Item #6 opened its design with this table because "four false library claims have already entered this
project's artifacts by recall", and item #7's V1 contradicted its own proposal. The same discipline
earns its keep again immediately: **V4 and V7 each correct a claim written into this change's own
exploration or proposal**, and both corrections change code.

| # | Claim | Evidence |
|---|---|---|
| V1 | **`Mount(middleware=[...])` wraps in list order, outermost first.** `for cls, args, kwargs in reversed(middleware): self.app = cls(self.app, ...)` — the **first** entry ends up outermost. So `[Middleware(AutenticacionDeBorde), Middleware(AdmisionDeBorde)]` runs the token check first and admission second, with no path list anywhere | `starlette/routing.py:382-384` |
| V2 | **The route pin does not see `Mount` middleware.** `_rutas_efectivas` descends through `Mount.routes`, which is `getattr(self._base_app, "routes")` — the *unwrapped* router. Adding a second middleware to the existing `Mount` leaves the pinned route/mount sets byte-identical | `tests/test_seguridad_token.py:274-305`; `starlette/routing.py:390-392` |
| V3 | **`/salud` and the four doc routes are structurally outside `/interno`.** They are registered on the outer app; the mount contains processor routes only (ADR 0019's invariant). Scoping admission to the mount therefore needs **no path guard and no allow-list** — the same structural formulation ADR 0016 demands | `app/main.py:32-43`; `adrs/0019`, Decisión + Consecuencias |
| V4 | **On Windows, `Process.exitcode` after `kill()` is `-15`, not the `TerminateProcess` code.** CPython terminates with `TERMINATE = 0x10000` and then *normalizes it back*: `if code == TERMINATE: code = -signal.SIGTERM`. **The exploration's and proposal's risk row — "Windows returns the exit code passed to `TerminateProcess`" — is false for `multiprocessing`.** Also, `kill = terminate` on Windows: there is no harder kill | `C:\Python312\Lib\multiprocessing\popen_spawn_win32.py:17, 110-114, 121-129` |
| V5 | **EOF on the pipe is detectable and non-blocking on both platforms.** Windows: `_recv_bytes` turns `ERROR_BROKEN_PIPE` into `EOFError`, and `wait()` counts a broken pipe as ready, so `poll()` returns `True` immediately. POSIX: a zero-byte read raises `EOFError`. This is what stops the parent blocking when a child dies before writing | `C:\Python312\Lib\multiprocessing\connection.py:318-329, 380-382, 1012` |
| V6 | **`ErrorTipificado` subclasses do not survive pickle today.** Each `__init__` is keyword-only and calls `super().__init__()`, so `self.args == ()`; the default `Exception.__reduce__` yields `(cls, ())`, and unpickling calls `ErrorFormato()` → `TypeError: missing required keyword-only argument`. A typed error therefore **cannot** cross the `Pipe` unaided | `app/core/errores.py:113-121, 135-139, 184-186, 193-195`; `Connection.send` uses `_ForkingPickler.dumps` (`connection.py:201-205`) |
| V7 | **ADR 0012's failure-translation row "el módulo levanta una excepción → error tipificado de contenido" is not implementable as written.** `ContextoContenido.motivo` is `Literal["columna_faltante", "cero_filas"]` — a closed two-value literal with no room for "the module crashed", and `ContextoContenido` has no field for a traceback. Honouring that cell today would mean widening a closed literal, which is exactly the pressure ADR 0014 exists to resist | `app/core/errores.py:69-73`; `adrs/0012:143` |
| V8 | **The child inherits the parent's environment.** `spawn` gives a clean interpreter with no inherited *handles* (ADR 0012's claim, correct), but `os.environ` — including `TOKEN_SERVICIO` and any future DB credentials — is inherited by every child. `multiprocessing.Process` exposes no `env` parameter | `multiprocessing` process creation semantics; `app/core/configuracion.py:22-26` (env is the only source) |
| V9 | **`REGISTRY` is empty and stays empty until items #12/#16**, so the only registry outcome a child can reach today is a **miss**. That miss is a fully real end-to-end path, not a stub — §10 makes it the load-bearing child test | `app/registry.py:13` |
| V10 | **`tests/` and `tests/ayudas/` are real packages** (`__init__.py` in both), and `spawn` propagates `sys.path` to the child. A deliberate child target in `tests/ayudas/hijos.py` is therefore importable by a spawned child without any production hook | `Glob tests/**/*.py`; `multiprocessing/spawn.py` preparation data |
| V11 | **The repo has one established way to move blocking work off the loop**: `await run_in_threadpool(fn, ...)`, used for both `_copiar` and `barrer`. Nothing in the repo resizes anyio's thread limiter | `app/recepcion.py:165`; `app/core/temporales.py:156, 163` |

## 1. Technical approach

One new module, one middleware entry, one config pair, one pickling guarantee, one ADR.

- **`app/core/ejecucion.py`** (new) — two independent halves behind one module:
  the **admission half** (lazy semaphore, an `admitir()` context manager shaped exactly like
  `temporales.reservar()`, the `AdmisionDeBorde` ASGI middleware, and the `ServicioSaturado` →
  503 exception/handler pair) and the **process half** (pipe message types, the generic
  `ejecutar_aislado()` plumbing, the pure `clasificar_desenlace()`, and the thin `ejecutar_modulo()`
  composition plus its module-level child target).
- **`app/core/configuracion.py`** — `ejecuciones_max` and `timeout_ejecucion`, plus a validator that
  makes "strictly below the portal's 2-minute cutoff" a *configuration* property (TECH-DESIGN:259).
- **`app/core/errores.py`** — `ErrorTipificado` gains `__reduce__`. Ten lines that make the whole
  closed vocabulary cross a process boundary losslessly, present and future (V6).
- **`app/main.py`** — one list entry on the existing `Mount`, one handler registration.
- **`app/core/interfaz.py`** — the open caveat is resolved and rewritten.

The organising idea: **the slot is a property of the request, and the pipe payload is data, not
objects.** Everything hard in this item collapses once those two are fixed. Item #10 composes; it
never has to unwind anything this item built.

## 2. Decision — admission is a second middleware on the *existing* `Mount`

**Chosen: `Mount("/interno", app=router_interno, middleware=[Middleware(AutenticacionDeBorde), Middleware(AdmisionDeBorde)])`.**
One `Mount`, two middlewares, auth outermost (V1).

| Option | Where `/salud` stands | Auth-before-admission | Verdict |
|---|---|---|---|
| Second entry on the existing `Mount` | Structurally outside; no guard, no list (V3) | Guaranteed by list order (V1) | **Chosen** |
| A second, nested `Mount` for admission | Same, but adds a mount the route pin *does* see (V2) and a second frontier for no gain | Guaranteed | Rejected: a second boundary that means the same thing as the first |
| One shared app-level middleware with a path guard | Requires a path allow-list | Guaranteed | Rejected: ADR 0016 forbids the allow-list, verbatim, and ADR 0019 rejected this same shape once already |
| FastAPI `Depends()` on the route | n/a | n/a | Rejected on evidence: ADR 0019 shows dependencies resolve *after* the body is read |

**Module home: `app/core/ejecucion.py`, not `seguridad.py` and not a new module.** `seguridad.py` sets
the precedent that the ASGI edge lives next to the mechanism it guards (`AutenticacionDeBorde` sits
beside `exigir_token`, its only `raise` site). Admission's mechanism is the semaphore, so the
middleware belongs beside the semaphore. Putting it in `seguridad.py` would make a module about
*credentials* own a module about *capacity*.

There is no import-cost argument against co-locating a Starlette-dependent middleware with the child
target: `app.core.errores` already imports `fastapi` and `starlette`, and the child imports it
transitively via `app.registry` → `app.core.interfaz` → `app.core.errores`. A separate
`ejecucion_hijo.py` would buy zero milliseconds. Recorded here so it is not re-litigated.

**Consequence, stated rather than discovered later**: a request to `/interno/<unknown>` that 404s
still occupies a slot for its (very short) lifetime. Only authenticated callers can reach it (V1), so
this is a cost, not a surface.

## 3. Decision — the middleware owns the slot's entire lifetime, and is its only release site

**This is the hard part the proposal handed over, and the answer is that the slot's lifetime is the
authenticated request, not the child process.**

```python
@contextmanager
def admitir() -> Iterator[None]:
    if not obtener_semaforo().acquire(blocking=False):
        raise ServicioSaturado          # raised BEFORE the try: no release can pair with it
    try:
        yield
    finally:
        obtener_semaforo().release()    # the ONLY release() in the repository
```

```python
class AdmisionDeBorde:
    __slots__ = ("app",)
    def __init__(self, app: ASGIApp) -> None: self.app = app
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        with admitir():
            await self.app(scope, receive, send)
```

| Option | Release site(s) | Fails on | Verdict |
|---|---|---|---|
| **Acquire and release in the middleware, one `try/finally`** | Exactly one, lexically paired | Nothing — every exit from the inner app passes through it | **Chosen** |
| Acquire in middleware, release in item #10's pipeline `finally` | Two owners, one of which may never run | **Every 422**: `RequestValidationError` is raised by FastAPI *before* the route body runs, so the pipeline's `finally` never executes and the slot leaks permanently | Rejected — decisive |
| Acquire and release around the child only (inside `ejecutar_modulo`) | One, but admission then happens *after* the body is read | ADR 0012's own wording ("antes de leer el cuerpo") and the "no temp file on saturation" criterion | Rejected |
| An `asyncio.Semaphore` instead of `threading.BoundedSemaphore` | — | ADR 0012 names `threading.BoundedSemaphore`; and the counter must also be observable from threadpool code | Rejected |

**Why exactly-once holds on all eight paths.** Success, typed error, module exception, timeout,
anomalous child death and a `NotImplementedError` from the current seam are all just *exceptions or
returns from `await self.app(...)`* — the `@contextmanager`'s `finally` covers all of them
identically, because the middleware does not know or care which one happened. A client disconnect
mid-request surfaces as `asyncio.CancelledError` (a `BaseException`) thrown into the generator by
`__exit__`; `finally` still runs. And a failed acquire raises **before** `try:`, so the one release
site can never pair with a non-acquisition.

**`BoundedSemaphore`'s `ValueError` on over-release is kept deliberately as the detector, not
avoided.** ADR 0012 names the bounded variant; this design keeps it because with exactly one release
site, a `ValueError` in production can only mean someone added a second one. It is a tripwire on a
future edit, and the design's job is to make sure it never fires today — which it does by having no
second site to fire from.

**The cost, named**: a slot is held during multipart parsing and the bounded copy, not only during the
child. A slow-uploading client therefore holds capacity without ever spawning anything. This is
deliberate over-approximation (fewer concurrent children than `EJECUCIONES_MAX` allows, never more),
and the exposure is bounded to authenticated callers by V1. `TIMEOUT_EJECUCION` does **not** bound it;
only the portal's 2-minute cutoff does. §13 records it; a request-level deadline is not this item's.

**Crossing to the thread, and the 40-thread leak (ADR 0012 context point 1).** `ejecucion.py` ships
**synchronous** functions and imports no `asyncio`. The caller crosses the boundary with the repo's
one established idiom (V11): `await run_in_threadpool(ejecutar_modulo, ...)`, inside item #10. Two
consequences: `ejecucion.py` is testable with no event loop, and it does not decide its own threading
policy. anyio's default 40-thread limiter is **not** resized — it is shared with `_copiar` and
`barrer`, and shrinking it would starve them. Instead it is made **non-binding**: an admitted request
holds one slot for its whole life and uses at most one threadpool thread at a time, so concurrent
threadpool work from `/interno` can never exceed `EJECUCIONES_MAX`. §4 turns that from an argument
into a validator.

## 4. Decision — the two configuration fields ship **with defaults** (correcting the proposal)

The proposal says both fields are "required". **This design ships them defaulted**, and flags the
change rather than making it quietly.

| Option | Effect on today's suite and deployment | Verdict |
|---|---|---|
| Required, no default | `extra="forbid"` + a missing env var → `ConfiguracionInvalida` at first `obtener_configuracion()`, i.e. **every existing test and every existing deployment breaks** until an operator invents a number with strictly less information than this design has | Rejected |
| **Defaulted, bounded, validated** | Additive; nothing breaks; the placeholder is visible in one place and item #17 replaces it | **Chosen** |

`token_servicio` is required because there is no safe default for a credential. A concurrency ceiling
is the opposite: a conservative default is *safer* than a number a deployer guessed.

```python
CORTE_DEL_PORTAL: Final[timedelta] = timedelta(minutes=2)   # TECH-DESIGN.md:259 — not a preference

ejecuciones_max: Annotated[int, Field(ge=1, le=32)] = 2
timeout_ejecucion: timedelta = timedelta(seconds=60)

@model_validator(mode="after")
def _timeout_por_debajo_del_corte(self) -> Configuracion: ...   # < CORTE_DEL_PORTAL, else ValueError
```

- **`le=32` is load-bearing, not decoration.** At 40 or above, anyio's default limiter — not
  `EJECUCIONES_MAX` — becomes the real concurrency number, which is precisely H-03's "concurrencia
  real es el producto de dos números que nadie multiplicó". The ceiling makes §3's non-binding claim
  a configuration property. 32 leaves headroom for `barrer` and the copies.
- **`2` and `60s` are conservative placeholders, not measurements** (locked Decision 4; item #17 owns
  calibration). `2` because one API worker × two children each capable of the 256 MB budget of ADR
  0021 is the smallest number that is not "concurrency 1". `60s` because the p95 target is 15s
  (TECH-DESIGN:320), so 60s is 4× headroom while leaving half the portal's 120s window for upload,
  packaging and transfer.
- **`timedelta`, not a bare float**, following `UMBRAL_DE_EDAD`/`INTERVALO_DE_BARRIDO`. pydantic parses
  `TIMEOUT_EJECUCION=60` as 60 seconds; `Process.join` takes `.total_seconds()`.
- The validator raises a plain `ValueError`; `obtener_configuracion` already converts it to
  `ConfiguracionInvalida` using only `loc`/`type`, so **no value ever reaches the message** — the
  invariant `configuracion.py:30-39` protects is untouched.

**The semaphore itself is lazy**, `@lru_cache(maxsize=1)`-wrapped like `obtener_configuracion`, so
importing `app.core.ejecucion` reads no configuration and has **no import-time side effect** — the
precondition `spawn` imposes on every module the child re-imports (ADR 0012, Consecuencias). Tests
clear it exactly as `limpiar_cache_configuracion` already does.

## 5. Decision — the `Pipe` carries data; typed errors cross via `__reduce__`

Three message shapes, all frozen dataclasses of picklable primitives, mirroring `app/core/tipos.py`:

```python
@dataclass(frozen=True, slots=True)
class SalidaDelHijo:      archivos: list[ArchivoSalida]
@dataclass(frozen=True, slots=True)
class ErrorDelHijo:       error: ErrorTipificado
@dataclass(frozen=True, slots=True)
class ExcepcionDelHijo:   clase: str; mensaje: str; traza: str

MensajeDelHijo = SalidaDelHijo | ErrorDelHijo | ExcepcionDelHijo
```

`ExcepcionDelHijo` exists because a live exception object carries a traceback and possibly
unpicklable attributes; `traceback.format_exc()` is a `str` and always survives. `ErrorDelHijo` can
carry the real exception **only after V6 is fixed**:

```python
# app/core/errores.py
def _reconstruir(cls: type[ErrorTipificado]) -> ErrorTipificado:
    return cls.__new__(cls)          # bypasses the keyword-only __init__; pickle restores __dict__

class ErrorTipificado(Exception):
    def __reduce__(self) -> tuple[...]:
        return (_reconstruir, (type(self),), dict(self.__dict__))
```

| Option | Cost | Verdict |
|---|---|---|
| **`__reduce__` on the base class** | ~10 lines, generic over all five subclasses *and every future one*; the pickling guarantee lives with the vocabulary it guarantees | **Chosen** |
| Send `(tipo, contexto)` and rebuild in `ejecucion.py` | A per-shape mapping table — `ErrorTamano` alone needs two branches since ADR 0021 added `ContextoTamanoTotal` — that must be updated every time a context shape is added, in a module that has no business knowing them | Rejected |
| Send `(dotted_class_name, contexto)` and `getattr` the class | Same table problem plus name-based class resolution from a subprocess payload | Rejected |

**The parent never trusts the payload's type.** `Connection.recv()` is typed `Any`; the parent
narrows with `isinstance` against the three dataclasses and classifies anything else as a protocol
violation (→ `HijoMuerto`). This satisfies `mypy --strict` without a `cast`, and it means a buggy or
hostile child cannot steer the parent by sending an unexpected object.

**Ordering, and why the pipe is read before `join()`.**

```python
padre, hijo = Pipe(duplex=False)
proceso = Process(target=objetivo, args=(hijo, *argumentos), daemon=True)
proceso.start()
hijo.close()            # LOAD-BEARING: while the parent holds a copy of the write end,
                        # the child's death never produces EOF and poll() waits the full timeout
try:
    mensaje = padre.recv() if padre.poll(restante()) else None   # EOFError => child wrote nothing
finally:
    padre.close()
# only now: join(restante()); kill() if still alive; classify
```

- **`join()` first would risk a deadlock**: a payload larger than the OS pipe buffer blocks the child
  in `send()` while the parent blocks in `join()`. Today's payloads are small, but "small" is not a
  guarantee, and the ADR is explicit that this plumbing "corre solo en el peor día".
- **`poll(timeout)` never blocks forever**, and thanks to `hijo.close()` in the parent, a child that
  dies before writing yields EOF *immediately* rather than burning the whole timeout (V5).
- **A well-formed message is authoritative.** If a message arrived, the result stands even if the
  child then exits oddly: its work is done. It is joined with a short grace and killed if it lingers.
- **`daemon=True`**: TECH-DESIGN:257-258 requires "el proceso hijo muere de verdad, no queda huérfano
  consumiendo CPU"; a daemon child cannot outlive a crashed parent. **The cost is real and belongs in
  the ADR**: a daemonic process may not create children, so a future processor cannot use
  `joblib`/`n_jobs>1` or its own `multiprocessing`. That is consistent with ADR 0006's "estrictamente
  síncrono" and is named as a constraint on items #12/#16 rather than discovered by one of them.

## 6. Decision — exitcode translation: the `matado` flag decides, never the number

```python
class Desenlace(StrEnum):
    NORMAL = "normal"; MATADO = "matado"; ANOMALO = "anomalo"

def clasificar_desenlace(*, exitcode: int | None, matado: bool, hubo_mensaje: bool) -> Desenlace: ...
```

A **pure** function: `matado` wins; otherwise a message plus `exitcode == 0` is `NORMAL`; everything
else is `ANOMALO`.

| Platform | Situation | Observed `exitcode` | Classified | Exercisable on this Windows dev/CI box? |
|---|---|---|---|---|
| Windows | our `kill()` (= `terminate()`, V4) | **`-15`** — `TERMINATE` normalized to `-SIGTERM` | `MATADO` (by flag) | **Yes**, really killed |
| POSIX | our `kill()` → `SIGKILL` | `-9` | `MATADO` (by flag) | Classifier: yes, as data. Real signal: **no** |
| POSIX | OOM killer | `-9` — *identical to the row above* | `ANOMALO` (flag is `False`) | Classifier: yes. Real OOM: **no** |
| POSIX | external `SIGTERM` | `-15` — *identical to the Windows kill row* | `ANOMALO` | Classifier: yes. Real signal: **no** |
| both | module calls `os._exit(3)` | `3` | `ANOMALO` | **Yes**, `os._exit` is portable |
| Windows | access violation | `3221225477` (`0xC0000005`) | `ANOMALO` | Not deliberately provoked |
| both | clean exit, no message | `0`, `hubo_mensaje=False` | `ANOMALO` | **Yes** (`os._exit(0)`) |
| both | still alive after join | `None` | `ANOMALO` | Yes, as data |

Rows 1–4 are the whole argument: **`-9` and `-15` are each ambiguous between "we did it" and
"something else did it", on both platforms, and V4 shows the platform encodings collide rather than
separate.** The parent is the only code that can call `kill()`, so it already knows the answer and
must never reverse-engineer it. (A child calling `os._exit(0x10000)` on Windows would be misread as
`-15`; irrelevant in practice, and harmless because the flag still says we did not kill it.)

Because the classifier is pure, **every POSIX convention is unit-tested locally as data**; what cannot
be exercised on Windows is the *production* of those codes, not their handling. That distinction is
the honest form of the proposal's "unverified-locally, not untested-in-principle".

## 7. The public surface of `app/core/ejecucion.py`

```python
# --- admission ---------------------------------------------------------------
class ServicioSaturado(Exception): ...                     # 503, sibling of TokenInvalido
def responder_servicio_saturado(request: Request, exc: Exception) -> Response: ...
def registrar_manejador_503(app: FastAPI) -> None: ...
def obtener_semaforo() -> threading.BoundedSemaphore: ...  # @lru_cache(maxsize=1)
@contextmanager
def admitir() -> Iterator[None]: ...
class AdmisionDeBorde: ...                                 # ASGI middleware

# --- failures item #10 translates (never TipoError; the enum stays at 5) ------
class FalloDeEjecucion(Exception): ...
class EjecucionExpirada(FalloDeEjecucion): ...             # timeout + real kill
class HijoMuerto(FalloDeEjecucion):     exitcode: int | None
class FalloDelModulo(FalloDeEjecucion): clase: str; mensaje: str; traza: str

# --- process plumbing --------------------------------------------------------
def clasificar_desenlace(*, exitcode: int | None, matado: bool, hubo_mensaje: bool) -> Desenlace: ...
def ejecutar_aislado(
    objetivo: Callable[..., None], argumentos: tuple[object, ...], *, timeout: timedelta
) -> MensajeDelHijo: ...                                   # spawn/pipe/join/kill/classify
def _ejecutar_en_hijo(conexion: Connection, clave: str, entradas: list[ArchivoEntrada]) -> None: ...
def ejecutar_modulo(
    *, clave: str, entradas: list[ArchivoEntrada], timeout: timedelta
) -> list[ArchivoSalida]: ...
```

Four decisions are compressed into that surface.

| Decision | Choice | Rejected | Rationale |
|---|---|---|---|
| Plumbing vs. policy | Two layers: generic `ejecutar_aislado` + thin `ejecutar_modulo` | One `ejecutar_modulo` that also spawns | The risky code ("corre solo en el peor día") is the plumbing. Splitting lets **deliberate test children** in `tests/ayudas/hijos.py` drive the *real* plumbing through hang, crash, `os._exit` and silence (V10) — with a stub-free `ejecutar_modulo` covered separately by V9's registry-miss path |
| Failure signalling | `ejecutar_modulo` **raises**: the crossed `ErrorTipificado` as-is, or `FalloDelModulo`/`EjecucionExpirada`/`HijoMuerto` | Return a result union item #10 must destructure | Follows `validaciones.py`'s shipped precedent: the typed-error handler is already registered, so re-raising the crossed exception needs zero new translation. The three non-typed failures share one base so item #10 can catch broadly or narrowly, its choice |
| `timeout` as a parameter | Passed in, not read from `Configuracion` inside | Read `obtener_configuracion()` internally | Tests set 0.2s without touching global config, and item #10 keeps one place where the deadline is decided |
| One child runs `validar` **then** `procesar` | Both in a single spawn | One spawn per step, or an `operacion` argument | `spawn` re-imports pandas per child — the single largest cost in the request (ADR 0012, Consecuencias). Two spawns doubles it to split two CPU-bound steps over the same files. **This does constrain item #10**: its "validar" and "procesar" steps happen inside one child, and the pipe's three outcomes are what it branches on |

**The child target, and what `spawn` requires of it.** `_ejecutar_en_hijo` is module-level (picklable
by qualified name), takes only the `Connection` plus a `str` and a list of frozen dataclasses of
`str`/`int`/`Path` (locked Decision 3 — no `Procesador` instance ever crosses), and re-derives the
processor with `REGISTRY[clave]`. A miss raises `ErrorClaveInexistente(causa="no_en_registry")` — the
`CausaDesincronizacion` value H-05 already put in the vocabulary. It sends exactly one message, closes
the connection, and returns. `app/core/interfaz.py`'s caveat is rewritten to record this.

**Module exception → `FalloDelModulo`, not `ErrorContenido`** (V7). ADR 0012's table says
"error tipificado de contenido", and that is not expressible: `ContextoContenido.motivo` is a closed
two-value literal with no traceback field. Rather than widen a closed literal — the exact pressure
ADR 0014 exists to resist — this item raises a distinguishable non-`TipoError` exception and hands the
HTTP translation to item #10, which already owns the H-05 vocabulary gap. `adrs/0022` records the
deviation so it is discoverable from the decision record, not from this file.

## 8. Sequence

```
Cliente   AutenticacionDeBorde  AdmisionDeBorde   recibir()/pipeline#10   ejecucion.py      hijo
   │              │                    │                  │                    │             │
   ├─POST /interno/procesadores/{k}────┤                  │                    │             │
   │              │  scope["headers"] sólo; nunca receive()│                    │             │
   │◄─ 401 ───────┤ TokenInvalido      │                  │                    │             │
   │              ├───────────────────►│ admitir(): acquire(blocking=False)     │             │
   │◄─ 503 ───────┼────────────────────┤ ServicioSaturado — 0 bytes de cuerpo, 0 temporales   │
   │              │                    │  ── with admitir(): ────────────────┐  │             │
   │              │                    ├─►│ multipart, contrato, reservar()  │  │             │
   │              │                    │  │ await run_in_threadpool(ejecutar_modulo)          │
   │              │                    │  │                  ├── Pipe(duplex=False) ──────────┤
   │              │                    │  │                  ├── Process(daemon=True).start() ┤
   │              │                    │  │                  ├── hijo.close()  │   REGISTRY[k]│
   │              │                    │  │                  ├── poll(timeout) │   validar    │
   │              │                    │  │                  │                 │◄─ procesar   │
   │              │                    │  │  SalidaDelHijo ──┤◄────────────────┤  send(msg)   │
   │              │                    │  │  ErrorDelHijo  ──┤   (V6: __reduce__)             │
   │              │                    │  │  ExcepcionDelHijo┤   (traza: str)                 │
   │              │                    │  │  EOFError ───────┤   hijo murió sin escribir (V5) │
   │              │                    │  │  poll()==False ──┤   kill(); matado=True          │
   │              │                    │  │                  ├── join(restante) → exitcode    │
   │              │                    │  │                  ├── clasificar_desenlace(...)    │
   │◄─ 200 / 422 / (item #10 decide) ──┼──┤◄ archivos | raise ErrorTipificado | FalloDeEjecucion
   │              │                    │  └── finally: release()  ← ÚNICO sitio, siempre corre │
```

Every arrow leaving the inner app — including a client disconnect that never draws an arrow at all —
passes through that single `finally`.

## 9. File changes

| File | Action | Description |
|---|---|---|
| `app/core/ejecucion.py` | Create | §3, §5, §6, §7. Stdlib + `fastapi`/`starlette` + `app.core.{configuracion,errores,tipos}` + `app.registry`. **Nothing from `app/procesadores/`** (ADR 0011 invariant, satisfied by construction) |
| `app/core/configuracion.py` | Modify | Two defaulted fields, `CORTE_DEL_PORTAL`, the `model_validator`; docstring's "pertenecen al ítem #8" note resolved (§4) |
| `app/core/errores.py` | Modify | `_reconstruir` + `ErrorTipificado.__reduce__` (§5). `TipoError` untouched — still exactly five values |
| `app/main.py` | Modify | `Middleware(AdmisionDeBorde)` as the **second** list entry on the existing `Mount` (V1); `registrar_manejador_503(app)` |
| `app/core/interfaz.py` | Modify | The open caveat rewritten: the child re-imports and looks up `REGISTRY[clave]`; only `str` and paths cross |
| `adrs/0022-admision-acotada-y-plomeria-del-proceso-dedicado.md` | Create | §12. Number verified against disk (0011–0021 exist), **not** 0016 |
| `tests/ayudas/hijos.py` | Create | Deliberate child targets: normal, hangs, `os._exit(N)`, exits silently, sends a typed error, raises (V10) |
| `tests/test_admision.py` | Create | §10 — semaphore, `admitir`, middleware release paths, 503 end-to-end |
| `tests/test_ejecucion.py` | Create | §10 — classifier table, real plumbing paths, registry-miss end-to-end |
| `tests/test_configuracion_ejecucion.py` | Create | §10 — bounds, the 2-minute validator, no value in the message |
| `tests/test_errores_tipificados.py` | Modify | Pickle round-trip for all five subclasses plus `ErrorTamano.total()` (V6) |
| `tests/conftest.py` | Modify | Env + cache-clear fixture for the two new fields and the semaphore |
| `tests/test_seguridad_token.py` | **Untouched** | Zero lines — V2 is the mechanical proof that the route pin does not move |
| `app/recepcion.py`, `app/core/temporales.py`, `app/registry.py`, `app/arranque.py` | **Untouched** | Zero lines. Item #10 wires the seam; `spawn` needs nothing new (`arranque.py` already satisfies it) |

## 10. Testing strategy

Behavioural only. The suite is 184 fast tests at ~99% coverage; the budget for this item is
**≤ 6 spawning tests**, because each child pays a real `spawn` re-import (~0.5–1.5s on Windows).
Everything else is designed to need no child at all.

| Layer | What to test | Approach |
|---|---|---|
| Unit | `clasificar_desenlace` over §6's whole table, POSIX rows included | Pure function, exitcodes as data. **This is how POSIX conventions are covered on a Windows-only box** |
| Unit | `admitir()` releases on return and on exception; a failed acquire raises `ServicioSaturado` and releases nothing | Direct calls; assert capacity by a follow-up `acquire(blocking=False)` |
| Unit | All five `ErrorTipificado` subclasses plus `ErrorTamano.total()` survive `pickle.loads(pickle.dumps(e))` with `tipo` and `contexto` intact (V6) | No subprocess needed |
| Unit | The two config fields: bounds (`ge=1`, `le=32`, `gt=0`), the `< 2 minutes` validator, and that `ConfiguracionInvalida`'s message carries **no value** | Existing `limpiar_cache_configuracion` + `monkeypatch.setenv` pattern |
| Integration | **Slot release on every inner-app outcome** — 200, `ErrorTipificado`, bare `RuntimeError`, `EjecucionExpirada`, `NotImplementedError`, and a cancelled task | Wrap a tiny inner ASGI app in `AdmisionDeBorde` directly and assert capacity is restored each time. No child, no pipeline, milliseconds |
| Integration | **503 end-to-end, deterministically** | Real `crear_app()` + `TestClient(raise_server_exceptions=False)`; set `EJECUCIONES_MAX=1` and **pre-acquire the single slot** before issuing the request. Saturation by pre-acquisition, never by racing threads — no flakiness, no sleeps |
| Integration | Saturation reads **no body and writes no temp file** | Under the same pre-acquired slot, POST a *malformed* multipart body: a 503 (not a 422) proves the parser never ran; then assert the dedicated root has zero `pet-*` children |
| Integration | **Auth outranks admission** (locked Decision 1) | Slot pre-acquired **and** a bad token → **401**, not 503 |
| Integration | `/salud` is unaffected while saturated | Slot pre-acquired → `GET /salud` still 200 (V3, structurally) |
| Process | Success, module exception (traceback text present), typed error crossing intact, timeout with **real** kill, `os._exit(3)`, and a child that exits **silently** | `ejecutar_aislado` + `tests/ayudas/hijos.py` (V10), `timeout=0.2s`. Assert `proceso.is_alive()` is `False` after the timeout path — termination, not a returned `join()` |
| Process | `ejecutar_modulo` end-to-end against the **empty** production `REGISTRY` → `ErrorClaveInexistente(causa="no_en_registry")` re-raised in the parent | V9: the one child path that is fully real today — it exercises spawn, child import, lookup, `__reduce__`, pipe, and parent re-raise with **zero test hooks in production code** |
| Process | Capacity is not wedged after an anomalous child death | Run the anomalous path, then assert the slot is free and a second execution succeeds |
| Static | Whole change | `uv run ruff check . && uv run ruff format --check . && uv run mypy app tests && uv run pytest` |

**The pre-acquisition trick is the load-bearing test decision**, recorded here so `tasks` does not
improvise three variants: saturation is produced by taking the slot, not by concurrency. It also
explains why `obtener_semaforo()` is a cached accessor rather than a module constant — the test needs
a supported way to reach the same object the middleware uses, and `cache_clear()` between tests is
already this repo's idiom. **No `app.dependency_overrides` anywhere**, consistent with the suite.

## 11. Review budget forecast

The proposal estimated 535–710. That estimate omitted `errores.py`, `tests/ayudas/hijos.py`,
`tests/conftest.py`, `tests/test_errores_tipificados.py` and the ADR entirely. Test rows below carry
the repo's **+40% correction already applied** (item #6/#7 convention) — `tasks` must not apply it
twice.

| Artifact | Est. changed lines |
|---|---|
| `app/core/ejecucion.py` — admission half | 110–140 |
| `app/core/ejecucion.py` — process half | 170–210 |
| `app/core/configuracion.py` | 35–45 |
| `app/core/errores.py` | 20–30 |
| `app/core/interfaz.py` | 10–15 |
| `app/main.py` | 5–8 |
| `adrs/0022-*.md` | 100–130 |
| **Production subtotal** | **450–578** |
| `tests/test_admision.py` (corrected) | 210–265 |
| `tests/test_ejecucion.py` (corrected) | 265–335 |
| `tests/ayudas/hijos.py` (corrected) | 85–120 |
| `tests/test_configuracion_ejecucion.py` (corrected) | 65–90 |
| `tests/test_errores_tipificados.py` (corrected) | 35–50 |
| `tests/conftest.py` (corrected) | 35–55 |
| **Tests subtotal** | **695–915** |
| **Total (authored)** | **1145–1493** |

**Roughly double the proposal, and over both candidate budgets (400 and 600). Chained PRs are
warranted**, and four genuine seams exist — each is a precondition of the next, and each is
independently green and independently revertible.

| Slice | Contents | Est. | Independently green? |
|---|---|---|---|
| **S1 — vocabulary and configuration** | `configuracion.py`, `errores.py` (`__reduce__`), `adrs/0022`, `tests/test_configuracion_ejecucion.py`, `tests/test_errores_tipificados.py` | ~290–400 | Yes — purely additive, no caller. Mirrors item #7's A1 (vocabulary + ADR first) |
| **S2 — admission** | `ejecucion.py` admission half, `main.py`, `tests/test_admision.py`, `tests/conftest.py` | ~360–470 | Yes — and it **ships user-visible behaviour alone**: the 503 is reachable, auth-first is proven, release is proven on every inner-app outcome |
| **S3 — process plumbing** | `ejecucion.py` process half minus `ejecutar_modulo`, `tests/ayudas/hijos.py`, plumbing half of `tests/test_ejecucion.py` | ~385–490 | Yes — the plumbing is exercised end-to-end by deliberate children with no production caller |
| **S4 — module composition** | `_ejecutar_en_hijo`, `ejecutar_modulo`, `interfaz.py`, registry-miss test | ~145–190 | Yes — thin composition over S3, proven by V9's real path |

All four sit under 600; S2 and S3 exceed 400 at the top of their ranges. Splitting S2 or S3 further is
**not** advisable: the middleware and its release proof must land in one diff, and the plumbing and
the children that exercise it are one reviewable unit. `sdd-tasks` owns the formal guard lines and the
final chained/`size:exception` recommendation, and must first resolve the 400-vs-600 conflict named at
the top of this file.

## 12. ADR 0022 — yes, and why

**Decision: write it.** `adrs/0022-admision-acotada-y-plomeria-del-proceso-dedicado.md`, MADR matching
siblings 0011–0021, neutral professional Spanish, sections Estado / Contexto / Decisión / Alternativas
consideradas / Consecuencias. `tasks` schedules it; this design does not create the file.

**Numbering evidence**: `adrs/` contains `0011`–`0021` on disk (eleven files). `openspec/config.yaml:8`
still says "0011-0015 exist" and is stale — item #7's V7 already recorded this, and it has drifted one
further since.

**Amendment or new ADR?** ADR 0012 owns the *mechanism* and is not reopened: no pool, one process per
execution, spawn, pipe, join+kill, 503 instead of a queue — all unchanged. What a future reader would
otherwise have to reconstruct by archaeology are five decisions this design makes *inside* that
mechanism, one of which is a **deviation from an accepted ADR's own table**:

1. **The slot's lifetime is the authenticated request, not the child** (§3), with the single release
   site, the `BoundedSemaphore` tripwire, and the named cost that a slow upload holds capacity.
2. **The module-exception row of ADR 0012's failure table is not implemented as written** (V7). This
   is the deviation that alone justifies a record: a reader diffing the code against ADR 0012:143 must
   find, in one place, why `contenido` was not used and who owns the replacement (item #10).
3. **`matado`, never the exitcode, discriminates our kill** (§6), with V4's evidence that the platform
   encodings collide rather than separate.
4. **`daemon=True`** and its real constraint on items #12/#16: a processor may not spawn its own
   subprocesses (`joblib`, `n_jobs>1`).
5. **`ErrorTipificado` gains a pickling guarantee** (V6) — this touches ADR 0014's territory without
   opening the enum, exactly the distinction ADR 0021 already had to record once.

## 13. Threat matrix

This change adds a subprocess boundary, so the matrix is applicable. The reference matrix's VCS/PR
rows are all N/A; the boundaries actually touched are below them.

| Boundary | Applicability | Design response | Planned test |
|---|---|---|---|
| Documentation-like paths | N/A — classifies no file by content type | — | — |
| Git repository selection / commit state / push state / PR commands | N/A — no VCS or PR automation anywhere in this change | — | — |
| Shell command construction | **N/A by construction** — `multiprocessing.Process(target=..., args=...)`, never `subprocess`, never a shell, never a string. No client-controlled value ever becomes an argv element | Covered implicitly: no shell exists to test | — |
| Client-supplied `clave` reaching the child | **Applicable** | `REGISTRY[clave]` is a dict lookup on a `str`. It is **never** an import by name, a module path, or a filesystem path — which is the security half of locked Decision 3, not only its maintainability half. A miss is `ErrorClaveInexistente(causa="no_en_registry")` | The registry-miss end-to-end test (V9), with a hostile-looking key |
| Paths crossing the process boundary | **Applicable** | Only server-generated paths cross: `entrada_{i}` under `mkdtemp` (item #7, unchanged). No client-declared filename ever becomes a `Path` | Existing item #7 hostile-name tests remain green; new plumbing tests pass only `ArchivoEntrada` values built by the route |
| **Environment inherited by the child (V8)** | **Applicable — declared open** | `spawn` gives no inherited *handles*, but `os.environ` — including `TOKEN_SERVICIO` and any future DB credentials — **is** inherited, and `Process` exposes no `env` parameter. Scrubbing would mean mutating `os.environ` around `start()`, which is racy in a threaded server. Named here rather than left for someone to discover; the ADR 0013 invariant (children never reach the DB) is enforced by item #13's import check, not by this mechanism | No test — an honest open risk, recorded in `adrs/0022` Consecuencias. Manufacturing a test for an unmitigated risk would misrepresent it |
| Child traceback returning to the parent | **Applicable** | `ExcepcionDelHijo.traza` is a `str` that can contain absolute paths and, in the worst case, data values from the module. It is **operational-log material (item #14), never a response body** — this design constrains item #10 accordingly | Assert the traceback reaches `FalloDelModulo.traza`; no response-body assertion is possible or wanted here |
| Untrusted payload steering the parent | **Applicable** | `Connection.recv()` is `Any`; the parent narrows by `isinstance` against exactly three dataclasses and classifies anything else as a protocol violation → `HijoMuerto`. `mypy --strict` clean without a `cast` | A child sending an unexpected object is classified as anomalous, not unpacked |
| Unbounded resource growth | **Applicable, partially closed** | `EJECUCIONES_MAX` bounds concurrent executions; `le=32` keeps anyio's limiter non-binding (§4); `TIMEOUT_EJECUCION` bounds each child's life. **No RAM ceiling on the child** — explicitly out of scope per ADR 0012 Consecuencias; ADR 0021's declared-size check remains the first line | Bounds/validator tests; the timeout-kill test |
| Orphaned processes | **Applicable** | `daemon=True` plus a `kill()` on every non-completing path | `is_alive()` is `False` after the timeout path |
| Secret leakage into responses or logs | **Applicable** | The 503 is a bare status with no body, matching the shipped 401/422 pattern. The config validator's failure message is built from `loc`/`type` only, so no value reaches it | Sentinel-token assertion extended over the 503 path; validator-message test |

## 14. Migration / rollout

No migration, no schema, no persisted state, no feature flag. Rollback is a code revert, per slice, in
reverse order: drop `ejecutar_modulo`/`_ejecutar_en_hijo` and restore `interfaz.py`'s caveat (S4);
delete the process half (S3); remove the `Middleware(AdmisionDeBorde)` list entry and the 503
registration — the route returns to today's unconditional-execution behaviour (S2); revert the two
additive config fields and `__reduce__` (S1). Nothing outside this change depends on any of it: item
#10 is not yet wired to call `ejecucion.py`. Nothing on disk needs cleaning afterwards.

## 15. Open questions

- [ ] **Where the child writes its output files is undecided by the shipped ABC.** `Procesador.procesar`
      takes no output directory, so the paths in `ArchivoSalida` are the processor's choice. They must
      outlive the child and be readable by the parent. Item #10 (temp ownership) and #12/#16 own this;
      this design deliberately does **not** add a parameter to a shipped interface.
- [ ] **A slot is held for the whole authenticated request** (§3), so a slow upload consumes capacity
      without spawning anything. Accepted deliberately; only the portal's 2-minute cutoff bounds it. A
      request-level deadline would be a separate decision.
- [ ] **The child inherits `TOKEN_SERVICIO` and any future DB credentials** (V8, §13). Declared open,
      not mitigated here.
- [ ] **Proposal correction — the two config fields ship defaulted, not required** (§4). Flagged for
      spec reconciliation; the proposal's "both required" line should be updated.
- [ ] **Proposal/exploration correction — the Windows exitcode claim is false** (V4). Both documents
      say Windows returns the `TerminateProcess` code; `multiprocessing` normalizes it to `-15`. The
      *decision* it justified (handle both conventions) survives; only its rationale changes.
- [ ] **`EJECUCIONES_MAX = 2` and `TIMEOUT_EJECUCION = 60s` are placeholders with sourced floors**
      (§4), not measurements. Item #17 replaces them; `le=32` is the only bound that is load-bearing.
- [ ] **Review budget conflict: 400 (session) vs 600 (`openspec/config.yaml:42`, raised with data).**
      `sdd-tasks` must resolve it before apply. The four-slice recommendation is unchanged either way.
- [ ] **One child runs `validar` then `procesar`** (§7). This constrains item #10's step ordering. Named
      here so item #10 inherits it as a decision rather than as a surprise.
