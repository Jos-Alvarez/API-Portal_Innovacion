# Design: Reception and Lifecycle of Temporary Files

- **Change**: `recepcion-y-ciclo-de-vida-de-temporales` (BACKLOG item #6, second half)
- **Inputs**: `proposal.md` (**authoritative**), `exploration.md`, `REVISION-ADVERSARIAL.md` (H-02,
  H-09), `app/main.py`, `app/core/{tipos,errores,contrato,seguridad,validacion_http}.py`,
  `tests/test_seguridad_token.py`, `adrs/0011`, `adrs/0012`, `adrs/0016`, `adrs/0019`, inherited
  `L:\App_Portal\adrs\0006`, `PRD.md`, `TECH-DESIGN.md`, `openspec/config.yaml`, Engram
  `sdd/recepcion-y-ciclo-de-vida-de-temporales/{proposal,explore,decisions,spec}`
- **Authority**: ADRs outrank every other document. Inherited `L:\App_Portal\adrs\0001`–`0010`
  outrank local `adrs\0011`–`0019`. **This change authors `adrs/0020`.**
- **Methodology**: Strict TDD **disabled** (`openspec/config.yaml`). Behavioural tests only — no
  AST/structural tests, no chaos tests, no perturb-and-restore RED, no assertion machinery. `ruff`
  and `mypy --strict` still run. The full SDD chain still runs.
- **Review budget**: 600 lines (raised 2026-08-18 with recorded reasoning). See §12 — this change
  does not fit inside it, and §12 names a real split rather than asking for a blanket exception.

## 0. Verified facts this design rests on

No `Bash` tool was available this session, so **nothing was executed**. Every claim below was read
in the installed source under `L:\API-Portal\.venv\Lib\site-packages` or in a repository file, and
each row cites what was read. Four false library claims have already entered this project's
artifacts by recall; this table exists so a fifth does not. `uv run` is the only acceptable
interpreter for re-checking any of these — bare `python` is `C:\Python312` with FastAPI 0.115.14,
not the pinned 0.141.1.

| # | Claim | Evidence |
|---|---|---|
| V1 | **`python-multipart` is genuinely absent.** It is not installed under `.venv/Lib/site-packages` and it appears **nowhere** in `uv.lock`. So `uv.lock` **will** change: a new `[[package]]` block plus a new dependency edge under `api-portal`. Starlette asserts on it: `assert multipart is not None, "The \`python-multipart\` library must be installed to use form parsing."` | `Glob .venv/Lib/site-packages/*multipart*` → no files; `rg multipart uv.lock` → no matches; `starlette/formparsers.py:161` |
| V2 | **Starlette buffers every upload into its own temporary.** `MultiPartParser.spool_max_size = 1MB`; each file part gets `SpooledTemporaryFile(max_size=self.spool_max_size)`, which rolls over to a real file **in `tempfile.gettempdir()`** above 1 MB. These are FastAPI's to close, not ours: the form is closed on a request-scoped exit stack. | `starlette/formparsers.py:147,230`; `fastapi/routing.py:408-411,430-431`; `starlette/datastructures.py:494-497` |
| V3 | **A slow lifespan shutdown blocks the server.** Starlette sends `lifespan.shutdown.complete` only *after* `async with self.lifespan_context(app)` exits — i.e. after everything past `yield`. Uvicorn 0.52.3's `LifespanOn.shutdown()` then blocks on `await self.shutdown_event.wait()` until that message arrives. | `starlette/routing.py:648-664`; `uvicorn/lifespan/on.py:64-76` |
| V4 | **The response body is sent inside the route's own ASGI call.** FastAPI's `request_response` does `response = await f(request)` and then `await response(scope, receive, send)` in the same coroutine. Everything the endpoint function's own `try/finally` protects therefore runs **before** a single body byte is sent. | `fastapi/routing.py:137-147` |
| V5 | **`Mount.routes` bypasses the middleware wrapper.** `Mount.__init__` keeps `self._base_app = app` and rebinds `self.app` through the middleware list; the `routes` property returns `getattr(self._base_app, "routes", [])`. So the shipped route pin sees routes registered in `router_interno` even though `AutenticacionDeBorde` wraps it. | `starlette/routing.py:378-392` |
| V6 | **The shipped route pin recurses into `Mount` and into `_IncludedRouter`, carrying the prefix.** A route added under `router_interno` shows up as `("/interno/procesadores/{clave_procesador}", ("POST",))` in the `rutas` set, not in `montajes`. The current literal is five routes and `{"/interno"}`. | `tests/test_seguridad_token.py:246-299` |
| V7 | **The 422 handler is already shipped and this route makes it live.** `responder_validacion_invalida` returns a bodiless 422 for `RequestValidationError`, and `registrar_manejador_validacion(app)` is already called in `crear_app()`. This change ships the first body-bearing route, so that handler goes from unreachable to reachable with no new code. | `app/core/validacion_http.py:26-33`; `app/main.py:39` |
| V8 | **`obtener_contrato` returns `None` for every key.** `_TABLA_CONTRATOS` is an empty `MappingProxyType`. | `app/core/contrato.py:63-74` |
| V9 | **`run_in_threadpool` is importable and is what FastAPI itself uses** to keep sync work off the event loop. | `fastapi/routing.py:131`; `starlette/concurrency.py` present |
| V10 | **ADR 0011 already names the module.** `core/temporales.py # try/finally, limpieza total` is in its layout — the filename is inherited, not invented here. ADR 0011 lists no home for a non-per-processor route; `app/salud.py` is the shipped precedent for a top-level router module. | `adrs/0011-estructura-core-procesadores.md:29-50`; `app/salud.py` |
| V11 | **Measured, carried forward from `exploration.md`, not re-derived here**: `FileResponse._handle_simple` has no OSError/disconnect guard; `StreamingResponse` guards but re-raises `ClientDisconnect()`; **both** call `self.background()` only after the send loop, so **both skip cleanup on a mid-stream disconnect**. Swapping response classes fixes nothing. Early-unlink is POSIX-only and ADR 0012 leaves the deployment target undecided. | `exploration.md`; Engram `sdd/.../decisions` |

## 1. Technical approach

Two new production modules and one line of wiring.

- **`app/core/temporales.py`** owns the whole lifecycle: the root directory, per-request reservation,
  cleanup, and the sweeper. It is the only module in the change that contains a hard problem.
- **`app/recepcion.py`** is the reception route — a top-level router module following the shipped
  `app/salud.py` precedent (V10), deliberately **not** under `app/procesadores/`, because no
  processor exists to own it.
- **`app/main.py`** includes that router inside the existing, shipped `router_interno`.

`app/core/temporales.py` imports only the standard library plus `starlette.concurrency`; it imports
nothing from `app/procesadores/`, preserving ADR 0011's invariant by construction.

The design's organising idea is that **ADR 0006's `try/finally` is not wrong — it is wrong about
when.** A `finally` is correct exactly while nothing outside the endpoint function still needs to
read the temporary. It becomes wrong the moment the response body *is* the temporary (V4: the send
loop runs after the endpoint returns). So the lifecycle is modelled as **ownership**, with one
explicit transfer point, rather than as two competing cleanup mechanisms.

## 2. Decision — the lifecycle: one owner, one transfer point

**Chosen: a `Reserva` context manager that deletes on exit *unless* ownership was ceded to a
`BackgroundTask`.**

```python
# app/core/temporales.py (illustrative)
class Reserva:
    """Dueña del directorio temporal de una petición."""

    def __init__(self, directorio: Path) -> None:
        self.directorio = directorio
        self._cedida = False

    def ceder_limpieza(self) -> BackgroundTask:
        """Transfiere la propiedad a la respuesta. Tras esto, `__exit__` no borra."""
        self._cedida = True
        return BackgroundTask(self.limpiar)

    def limpiar(self) -> None:
        # Idempotente a propósito: puede correr desde `__exit__`, desde el
        # BackgroundTask, o desde el barrendero. Nunca desde dos a la vez con
        # consecuencias: `rmtree` con `ignore_errors` no falla si ya no está.
        _EN_VUELO.pop(self.directorio, None)
        shutil.rmtree(self.directorio, ignore_errors=True)


@contextmanager
def reservar() -> Iterator[Reserva]:
    reserva = Reserva(Path(tempfile.mkdtemp(prefix=_PREFIJO_PETICION, dir=_raiz())))
    _EN_VUELO[reserva.directorio] = time.monotonic()
    try:
        yield reserva
    finally:
        if not reserva._cedida:
            reserva.limpiar()
        else:
            _EN_VUELO.pop(reserva.directorio, None)
```

| Option | Happy path today (error response) | Future success path (#9/#10) | Verdict |
|---|---|---|---|
| `try/finally` only | Correct — the JSON body reads nothing from disk | **Broken** — deletes before the send loop (V4). This is H-02 verbatim | Rejected: ships code that item #9 must rewrite |
| `background=` only | **Cannot attach** — the route raises; the response is built by the registered `ErrorTipificado` handler, which knows nothing about temporaries | Correct on a clean send | Rejected: leaves today's error path with no cleanup at all |
| ASGI middleware inside the `Mount`, cleaning after `await self.app(...)` | Correct, and also survives a disconnect | Correct | Rejected — see below |
| **`Reserva` with an explicit transfer point** | Correct — nothing cedes, so `finally` cleans | Correct — `ceder_limpieza()` moves cleanup behind the send loop, and `finally` becomes a no-op | **Chosen** |

**Why the middleware alternative is rejected even though it is technically stronger.** A middleware
wrapping the mount would see the send loop complete (or raise) and could clean up on both paths,
apparently closing H-02 outright. It is rejected for three reasons, and this is recorded in ADR 0020
rather than buried: (a) inherited ADR 0006 makes the **pipeline** the single owner of temporary
cleanup — *"el pipeline común sigue siendo el único lugar donde viven las validaciones, los errores
tipificados y la limpieza de temporales"* — and a middleware moves that ownership out of the
pipeline that item #10 will build; (b) it would create a temporary directory for **every** request
into `/interno`, including ones that upload nothing; (c) it changes the shipped `Mount`'s middleware
list, which ADR 0019 fixes and the route pin covers. It does not remove the need for a sweeper
either: a process death still orphans directories, so the startup pass would be required regardless.

**What this means today, stated plainly.** Today the transfer point exists and is never taken,
because there is no success path — every request raises `ErrorClaveInexistente` (V8) and `finally`
cleans. `ceder_limpieza()` is therefore proven by a **test-only** route that returns a `FileResponse`
carrying it (§10), exactly the pattern items #2 and #3 used. Items #9/#10 change one line — the
`return` — and change nothing in `temporales.py`.

## 3. Decision — the sweeper

### 3.1 Where the temporaries live, and who creates the directory

A **dedicated root**, `Path(tempfile.gettempdir()) / "api-portal-temporales"`, with one
`mkdtemp(prefix="pet-", dir=raiz)` subdirectory per request.

This is not cosmetic. V2 shows Starlette writes its own upload spill files directly into
`tempfile.gettempdir()`, and every other process on the machine writes there too. **A sweeper that
scanned `gettempdir()` would delete an in-flight upload's spool file, or another application's
data.** Scoping the sweeper to a root this service created is the single most important safety
property in this section.

`tempfile.gettempdir()` is platform-neutral by construction — it resolves on a Linux container and
on a native Windows service alike — which is required because ADR 0012 leaves that choice undecided
and nothing here may bind it. It also keeps ruff's bandit rules quiet: no hard-coded `/tmp`.

The root is created by `preparar_raiz()` at lifespan startup with `mkdir(parents=True,
exist_ok=True)`, and defensively again by `reservar()` so a test or a manual `rmtree` cannot leave
the service broken. `mkdtemp` gives atomic creation, guaranteed uniqueness, and owner-only
permissions on POSIX — and, decisively, it derives nothing from client input.

### 3.2 What the sweeper is allowed to delete — the dangerous part

"It is older than 15 minutes so it must be dead" is exactly the assumption that deletes a slow
upload. The rule is therefore **two conditions, both required**:

> A direct child `d` of the root is deleted **iff** `d` is **not** in `_EN_VUELO` **and**
> `ahora - d.stat().st_mtime > UMBRAL_DE_EDAD`.

`_EN_VUELO` is a module-level `dict[Path, float]` (directory → registration instant) populated by
`reservar()` and emptied by `Reserva.limpiar()` or by the ceded-branch of `__exit__`. ADR 0012
mandates exactly **one** Uvicorn API worker, so this in-process registry is *complete*: a directory
absent from it has no living owner anywhere in the service. That is what makes an in-process set a
sound authority rather than a guess — and it is why this design would need rewriting, not just
retuning, if item #0 ever chose multiple API workers (§14).

Two failure modes this rule closes that a bare age check does not:

- **A slow request.** Its directory is in `_EN_VUELO` from before the first byte is written, so no
  age value can make it eligible while the endpoint is running.
- **An unbounded registry.** A disconnected request never runs its cleanup, so its entry would leak
  forever and permanently immunise the directory. The sweeper therefore **evicts** `_EN_VUELO`
  entries registered longer than `UMBRAL_DE_EDAD` ago *before* the eligibility check. One threshold
  governs both the registry and the disk; there is no second knob to get out of sync.

Past the threshold the design **does** assume the request is dead, and the justification is
sourced: ADR 0012 fixes `TIMEOUT_EJECUCION` strictly below the portal's 2-minute cutoff
(`TECH-DESIGN.md:300`), so the portal itself severed the connection roughly thirteen minutes before
the sweeper looks. The assumption is stated, not smuggled.

A third benefit falls out. On Windows, `shutil.rmtree` can raise `PermissionError` when a handle is
still open — a `FileResponse` mid-send, or an antivirus scanner. Cleanup uses
`rmtree(..., ignore_errors=True)`, so a failed delete is silent; the directory stays, ages past the
threshold, and the sweeper retries it. **The sweeper is the retry mechanism for a failed delete, not
only the answer to a disconnect** — which matters because the deployment target is undecided.

### 3.3 The two numbers, and where they live

| Parameter | Value | Status |
|---|---|---|
| `UMBRAL_DE_EDAD` | **15 minutes** | **Confirmed**, not merely inherited. Derivation: it must exceed the longest possible in-flight lifetime. The portal cuts at 2 minutes (ADR 0012, `TECH-DESIGN.md:300`) and `TIMEOUT_EJECUCION` is strictly below that, so 15 minutes is ~7.5× the real bound. A **choice**, with a sourced floor — no document specifies it |
| `INTERVALO_DE_BARRIDO` | **5 minutes** | **Confirmed.** Bounds worst-case disconnect exposure to threshold + interval = **20 minutes**, which is the number the spec's "threshold plus one sweep interval" requirement resolves to. A **choice**, not a citation |
| Where they live | Two `Final` constants at the top of `app/core/temporales.py` | **Confirmed** over `Configuracion`. No operational need to tune per environment has been identified; adding an environment variable before that need exists is speculative. One file, two adjacent lines, editable in one place |

**Testability hook, decided here so `tasks` does not improvise it.** A 15-minute threshold cannot be
waited out in a test. `barrer(*, umbral: timedelta = UMBRAL_DE_EDAD, ahora: float | None = None)` is
a plain synchronous function of `(root, threshold, now)`; the periodic task supplies the constants,
tests supply `umbral=timedelta(0)`. No monkeypatching of `time`, no `freezegun`, no new dependency.

### 3.4 Startup pass *and* periodic — both

**Both**, and they are the *same* function with the *same* threshold.

- The **startup pass** runs once before `yield`. A restart is exactly when the orphan population is
  highest: a crash, an OOM kill, or a forced restart leaves `_EN_VUELO` empty and every surviving
  directory unowned. Without it, those orphans wait a full interval for the first tick.
- The **periodic task** covers the steady state: disconnects and failed deletes during a long-lived
  process.
- The startup pass deliberately does **not** special-case "the registry is empty, delete
  everything". A second API process could exist — a stray old process, or a developer running the
  suite concurrently — and the age rule costs nothing while removing that whole class of accident.

### 3.5 Where the sweeper runs, and what shutdown costs

An `asyncio` task created inside `ciclo_de_vida`. ADR 0012's single API worker means there is no
cross-worker coordination problem, unlike a pool.

```python
async def _bucle_de_barrido() -> None:
    while True:
        await asyncio.sleep(INTERVALO_DE_BARRIDO.total_seconds())  # dormir primero:
        await run_in_threadpool(barrer)                            # la pasada de arranque ya corrió


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI) -> AsyncIterator[None]:
    obtener_configuracion()          # 1. falla cerrado; ADR 0012 paso 2
    preparar_raiz()
    await run_in_threadpool(barrer)  # pasada de arranque (§3.4)
    tarea = asyncio.create_task(_bucle_de_barrido())  # referencia dura mientras viva el lifespan
    try:
        yield
    finally:
        tarea.cancel()
        with suppress(asyncio.CancelledError):
            await tarea
```

Three decisions inside those ten lines, each answering a question the brief asked:

1. **What cancels the task, and when.** The `finally` past `yield`, on every shutdown path including
   an exception raised inside the application. The local `tarea` is also the hard reference that
   stops the task being garbage-collected mid-flight — the same precaution Uvicorn takes for its own
   lifespan task (`uvicorn/lifespan/on.py:51-53`).
2. **Can a slow sweep block shutdown? Yes — measured, so it is bounded on purpose.** V3: Uvicorn
   waits for `lifespan.shutdown.complete`, which Starlette sends only after the post-`yield` block
   returns. So `await tarea` is on the shutdown critical path. The loop is written so that it is
   almost always parked in `asyncio.sleep`, which cancels instantly. If cancellation lands during
   the threadpool hop, `run_in_threadpool` is not interruptible and the await waits for that thread
   — bounded by one `os.scandir` of the root plus the `rmtree` of whatever orphans it found, and
   independent of request traffic. Stated rather than hoped for.
3. **Why `run_in_threadpool` at all.** `scandir`/`stat`/`rmtree` are blocking syscalls, and this is
   the *single* API worker's event loop (ADR 0012). Blocking it stalls every concurrent request.
   `ruff`'s `ASYNC` rules are selected in `pyproject.toml` and independently discourage blocking I/O
   inside `async def`, but the event-loop argument stands on its own.

**The honest degradation, restated where a reviewer will see it**: "zero temporaries after the
response" holds on the happy path. On a mid-stream disconnect it becomes "zero within 20 minutes".

## 4. The route

```
POST /interno/procesadores/{clave_procesador}      campo multipart fijo: archivos
```

Registered as `router_interno.include_router(router_recepcion)` in `crear_app()`. V5 and V6 confirm
the shipped pin sees it as `("/interno/procesadores/{clave_procesador}", ("POST",))`.

**The ADR 0006 deviation, kept visible.** Inherited ADR 0006 decides the service exposes *"una ruta
interna por procesador"* — a literally-named endpoint per processor — and explicitly rejects *"una
sola ruta genérica"*. That decision presumes at least one processor to name; V8 shows there are
none. This change therefore ships **one parametrised route as reception scaffolding**. It is a
temporary, flagged deviation, **not** a competing architectural decision: it amends no ADR and
authors no ADR of its own for the route shape. Two places carry the flag so it cannot be mistaken
for the finished design: the module docstring of `app/recepcion.py`, and ADR 0020's *Consecuencias*.
Items #12/#16 replace it with the literal per-processor `ruta.py` cáscaras ADR 0011 locates under
`app/procesadores/{clave}/`.

**What the route can prove today, and what it cannot.** Every request, for every `clave_procesador`,
reaches exactly one outcome: `ErrorClaveInexistente(causa="fila_ausente")` → 500 via ADR 0018's
`_ESTADO_HTTP`. That proves three things end to end — the mount's auth boundary sits in front of the
route, multipart reception writes and then removes a temporary, and a typed error resolves to a real
HTTP response. It proves **no** contract validation, **no** processing, and **no** success path.
This is a demonstration of reception and cleanup, not of processing, and should not be oversold.

```python
# app/recepcion.py (illustrative)
@router_recepcion.post("/procesadores/{clave_procesador}")
async def recibir(
    clave_procesador: str,
    archivos: Annotated[list[UploadFile], File()],
) -> Response:
    with reservar() as reserva:
        entradas = [
            await _volcar(carga, reserva.directorio, indice)
            for indice, carga in enumerate(archivos)
        ]
        contrato = obtener_contrato(clave_procesador)
        if contrato is None:
            raise ErrorClaveInexistente(clave_procesador=clave_procesador, causa="fila_ausente")
        # Costura de los ítems #9/#10 — el único cambio que necesitan aquí:
        #   return FileResponse(salida, background=reserva.ceder_limpieza())
        raise NotImplementedError  # inalcanzable hoy (V8); el ítem #7 sigue desde aquí
```

`entradas` is deliberately built and then unused today. That is the seam item #7 consumes, and it is
what makes the reception requirement testable now rather than asserted.

**Already-shipped behaviour this route makes live, at zero cost** (V7): a request missing the
`archivos` field raises `RequestValidationError` and gets a bodiless 422 from the shipped
`responder_validacion_invalida`. No new code; worth one behavioural test because it is the first
time that handler is reachable in production.

## 5. Building `ArchivoEntrada`

| Field | Source | Why |
|---|---|---|
| `nombre_original` | `carga.filename or ""` — **verbatim**, unparsed, unsanitised | ADR 0014's verbatim-string rule. It is data, never a path |
| `ruta_temporal` | `reserva.directorio / f"entrada_{indice}"` | Server-generated from the upload's position. Traversal, accents and duplicate names are closed **structurally**: two files sharing a `nombre_original` cannot collide because neither name was ever derived from it |
| `tamano_comprimido` | **Bytes actually written to disk** | Not `carga.size`, not `Content-Length`. H-09's `Content-Length` lie stays item #7's to enforce a limit against, but counting what landed on disk means this design never propagates a client-declared size downstream |
| `formato` | Extension of the `nombre_original` **string**, lowercased, no dot | See below |

`formato` is the one place where client input is inspected, and it is the obvious place to get this
wrong:

```python
def _formato(nombre_original: str) -> str:
    # `rsplit`, NO `Path(nombre_original).suffix`: construir un `Path` a partir de
    # una cadena del cliente es exactamente lo que esta decisión prohíbe, aunque
    # el resultado sólo se lea. Acá se manipula texto, nunca una ruta.
    nombre, punto, extension = nombre_original.rpartition(".")
    return extension.lower() if punto else ""
```

The write itself is one threadpool hop per file, never an `open()` on the event loop:

```python
_TROZO: Final[int] = 1024 * 1024

def _copiar(origen: IO[bytes], destino: Path) -> int:
    origen.seek(0)  # defensivo: no dependemos de dónde dejó el cursor el parser
    with destino.open("wb") as salida:
        shutil.copyfileobj(origen, salida, _TROZO)
        return salida.tell()
```

`carga.file` is Starlette's `SpooledTemporaryFile` (V2). Reading from it and writing our own copy is
duplication of up to 25 MB on disk; it is accepted because that spool is FastAPI's to close on its
own schedule (V2) and we need a path we own, under a directory the sweeper governs.

## 6. Dependency, lockfile, wiring, and the route pin

| Item | Change |
|---|---|
| `pyproject.toml` | `python-multipart` added to `[project].dependencies` — the one new runtime dependency, required by the reception mechanism itself (V1) |
| `uv.lock` | **Yes, it changes** (V1): a new `[[package]]` block plus a dependency edge under `api-portal`. Regenerated by `uv`, never hand-edited. Generated lines, not authored |
| `app/main.py` | `preparar_raiz()`, the startup pass, and the sweeper task inside `ciclo_de_vida`; `router_interno.include_router(router_recepcion)` inside `crear_app()` |
| `tests/test_seguridad_token.py` | `esperado` grows one entry: `("/interno/procesadores/{clave_procesador}", ("POST",))`. `esperado_montajes` is unchanged (V5, V6). This is a **deliberate pin update**, the same convention `service-token-auth` established — the test going red is the mechanism working, not a failure |

## 7. Data flow

```
POST /interno/procesadores/{clave}
        │
        ▼  AutenticacionDeBorde  ── sin token válido ──►  401, cuerpo vacío, sin leer un byte
        │                                                  (ADR 0017/0019, ya entregado)
        ▼  FastAPI multipart parse ── campo ausente ──►  422 sin cuerpo (V7, ya entregado)
        │
        ▼  reservar()  ──►  mkdtemp bajo la raíz, alta en _EN_VUELO
        │
        ▼  _copiar() por archivo  ──►  entrada_0, entrada_1, ...  ──►  [ArchivoEntrada]
        │
        ▼  obtener_contrato(clave)  ──►  None  (V8, siempre hoy)
        │
        ▼  raise ErrorClaveInexistente ──► __exit__ limpia ──► manejador ADR 0018 ──► 500
                                                                       ▲
        (camino de éxito de los ítems #9/#10)                          │
        ▼  return FileResponse(..., background=reserva.ceder_limpieza())
             └─ __exit__ NO borra ──► bucle de envío ──► background() ──► limpieza

        (desconexión a mitad del envío — V11)
             └─ background() nunca corre ──► el barrendero lo toma a los ≤20 min
```

## 8. Testing strategy

Behavioural only. No AST/structural tests, no chaos tests, no perturb-and-restore, no assertion
machinery.

| Layer | What to test | Approach |
|---|---|---|
| Integration | An upload writes a file inside the per-request directory; `ArchivoEntrada` carries the name verbatim | Test-only route exposing `entradas`, or assert on the directory before the response |
| Integration | Hostile names (`../../x`, `C:\x`, `/etc/x`, accents) write only inside the per-request directory | `TestClient` upload; assert nothing exists at any path derived from the declared name |
| Integration | Two uploads sharing one `nombre_original` produce two distinct files with distinct contents | One request, two parts, same declared name |
| Integration | Any `clave_procesador` returns 500 with `{"tipo": "clave_inexistente", "contexto": {..., "causa": "fila_ausente"}}` | Full-body equality |
| Integration | Zero temporaries remain after the response | Assert the root has no `pet-*` children after the request |
| Integration | Missing `archivos` field → bodiless 422 (V7) | Multipart with no file part |
| Integration | 401 arrives without the body being read | Already covered by the shipped mount tests; extend with this route's path |
| Unit | `ceder_limpieza()` makes `__exit__` a no-op, and the `BackgroundTask` deletes after the send loop | **Test-only** `FileResponse` route in `tests/`, the items #2/#3 pattern. Assert the file exists during send and is gone after |
| Unit | The disconnect hole is **real** (V11), and the sweeper closes it | Abort mid-stream, assert the directory survives, then `barrer(umbral=timedelta(0))`, assert it is gone. This is the one test that proves H-02's degradation is bounded rather than asserted |
| Unit | The sweeper does **not** delete an in-flight directory regardless of age | Register a path in `_EN_VUELO`, backdate its mtime, `barrer(umbral=timedelta(0))`, assert it survives |
| Unit | The sweeper evicts stale `_EN_VUELO` entries so the registry cannot leak | Backdate a registration, sweep, assert both entry and directory are gone |
| Unit | The sweeper touches nothing outside its root | Create a sibling file directly in `gettempdir()`, sweep, assert it survives |
| Unit | The startup pass removes a pre-existing orphan | Plant an aged directory, run the lifespan, assert it is gone |
| Unit | Shutdown cancels the task and does not hang | Enter and exit the lifespan; assert the task is done/cancelled |
| Unit | `_formato` on `"a.b.XLSX"`, `"sin-extension"`, `""`, `"..\\x.xlsx"` | Direct calls |
| Unit | The raw token appears in no response body and no captured log on any of the three paths | `caplog` plus response bodies, the item #1/#2 sentinel convention |
| Static | Whole change | `uv run ruff check . && uv run ruff format --check . && uv run mypy app tests` |

## 9. ADR 0020 — outline only (`tasks` schedules the writing)

`adrs/0020-ciclo-de-vida-de-los-temporales.md`, MADR matching siblings 0011–0019, in **neutral
professional Spanish**, sections **Estado / Contexto / Decisión / Alternativas consideradas /
Consecuencias**.

- **Contexto** — H-02 (Crítico, Abierto): ADR 0006's `try/finally` deletes the temporary before ASGI
  streams it, breaking the happy path. ADR 0006's own wording is *"una vez enviada la respuesta
  HTTP"*, which is not what a `finally` does. Carry V11's measurement verbatim.
- **Decisión** — ownership with one transfer point (§2); a dedicated root plus a sweeper governed by
  `_EN_VUELO` **and** age (§3.2); 15 minutes / 5 minutes as named constants (§3.3); startup pass and
  periodic task (§3.4); on-disk names always server-generated (§5).
- **Alternativas consideradas** — swapping `FileResponse` for `StreamingResponse` (rejected: V11 —
  the obvious wrong fix; it changes nothing); early-unlink (rejected: POSIX-only, and ADR 0012
  leaves the target undecided); reading the result into memory before cleaning (rejected:
  contradicts why the temporaries are on disk at all, ADR 0006); an ASGI middleware inside the mount
  (rejected: moves cleanup out of the pipeline ADR 0006 makes its owner, and still needs the startup
  pass); sanitising `nombre_original` (rejected: server-generated names close traversal, accents and
  duplicates in one decision instead of three escaping rules that each need to be right).
- **Consecuencias** — the acceptance criterion weakens honestly from "zero after the response" to
  "zero within 20 minutes on a mid-stream disconnect"; the sweeper doubles as the retry path for a
  Windows `PermissionError` on `rmtree`; `_EN_VUELO`'s soundness **depends on ADR 0012's single API
  worker** and must be revisited if item #0 chooses otherwise; H-09 cases 2, 3 and 4 close here and
  case 1 (the `Content-Length` lie) stays item #7's; and the parametrised route is temporary
  scaffolding that deviates from ADR 0006's per-processor design.

## 10. Threat matrix

This change modifies routing, so the matrix applies. The reference matrix's rows are VCS/PR-shaped
and are all `N/A`; the boundaries this change actually touches are listed below them.

| Boundary | Applicability | Design response | Planned test |
|---|---|---|---|
| Documentation-like paths | **N/A** — classifies no file by content type | — | — |
| Git repository selection | **N/A** — no VCS invocation | — | — |
| Commit state | **N/A** — no VCS invocation | — | — |
| Push state | **N/A** — no VCS invocation | — | — |
| PR commands | **N/A** — no PR automation | — | — |
| Shell / subprocess | **N/A** — item #8 owns the child process; nothing here spawns one | — | — |
| **New authenticated route** | **Applicable** | Registered inside `router_interno`, so the shipped `Mount` middleware fronts it (ADR 0019); nothing is added outside the mount | Route pin updated (V6); 401-before-body against this path |
| **Path traversal from a client-supplied filename** | **Applicable** | `nombre_original` never reaches a `Path()`; disk names are `entrada_{indice}` under a `mkdtemp` directory. `_formato` uses `rpartition`, not `Path().suffix` | `../../x`, `C:\x`, `/etc/x`, accented, empty, extension-only names |
| **Destructive filesystem operation (`rmtree`) driven by age** | **Applicable** | Scoped to a root this service created; `_EN_VUELO` plus age, both required; stale registry entries evicted by the same threshold | Sibling file in `gettempdir()` survives; in-flight directory survives at any age; registry cannot leak |
| **Unbounded resource growth from uploads** | **Partly N/A here** — the size ceiling is item #7's (`ContratoProcesador.tamano_max_bytes`); H-09 case 1 stays open by design | Bytes written are counted, so no client-declared size is ever propagated | Counted size matches the payload |
| **Secret leakage into responses or logs** | **Applicable** | No response body or log line in this change carries request data; the 422 is bodiless (V7) and the 401 has no body | Sentinel-token assertion across all three paths |

## 11. Migration / rollout

No migration, no schema, no persisted state, no feature flag. Rollback is a code revert: remove the
`include_router` line and the three lifespan lines from `main.py`, delete `app/recepcion.py` and
`app/core/temporales.py`, drop `python-multipart` from `pyproject.toml` and re-lock, restore the
route-pin literal. Nothing on disk needs cleaning afterwards — and if a temporary survived the
revert, it is under a single dedicated root that can be deleted by hand.

## 12. Review budget forecast

Prior items delivered 419, ~500, 419, 277 and ~460 lines against design-phase forecasts that ran
30–50% short, **always through the test file**. The test rows below already include a **+40%
correction**; the correction is not something for `tasks` to apply again on top.

| Artifact | Est. changed lines |
|---|---|
| `app/core/temporales.py` | 120–140 |
| `app/recepcion.py` | 65–80 |
| `app/main.py` | 12–18 |
| `pyproject.toml` | 1 |
| `adrs/0020-*.md` | 85–100 |
| `tests/test_temporales.py` (corrected) | 320–370 |
| `tests/test_recepcion.py` (corrected) | 155–185 |
| `tests/test_seguridad_token.py` | 2 |
| **Total (authored)** | **760–895** |
| `uv.lock` | ~15, generated |

**Well over the 600-line budget**, and unlike the last two items this one has a real split rather
than needing a blanket exception. The proposal argued it must land whole because "partial cleanup
logic without its sweeper is not independently safe" — that is true, and it does not describe this
split. The seam is between the **lifecycle** and its **first consumer**, not inside the lifecycle:

| Slice | Contents | Est. | Independently green? |
|---|---|---|---|
| **A** | `app/core/temporales.py`, its lifespan wiring in `main.py`, `tests/test_temporales.py`, `adrs/0020` | ~545–630 | Yes — cleanup *and* sweeper together, proven through a test-only `FileResponse` route. No production route, no new dependency, route pin untouched |
| **B** | `app/recepcion.py`, `include_router`, `python-multipart` + `uv.lock`, route-pin update, `tests/test_recepcion.py` | ~235–285 | Yes — consumes slice A's finished module |

Slice A still sits near the budget ceiling because ADR 0020 and the sweeper's test surface are both
substantial; that is the honest number, not a manufactured fit. `sdd-tasks` owns the formal guard
lines (`Decision needed before apply`, `Chained PRs recommended`, `600-line budget risk`) and the
final chained/`size:exception` recommendation.

## 13. Open questions

- [ ] None blocking. The design proceeds to `tasks`.
- [ ] `_EN_VUELO`'s soundness rests on ADR 0012's **single** API worker. If item #0 ever chooses a
      multi-worker deployment, the in-process registry stops being complete and the sweeper's
      protection of in-flight requests degrades to age alone. Recorded in ADR 0020's *Consecuencias*
      so it is discoverable from the deployment decision, not only from this file.
- [ ] 15 minutes and 5 minutes are **choices** with a sourced floor (§3.3), not requirements. If an
      operational SLA appears, they move together — and only then does promoting them to
      `Configuracion` become justified rather than speculative.
- [ ] The parametrised route deviates from ADR 0006's per-processor design. It is flagged in the
      module docstring and in ADR 0020, and items #12/#16 are expected to replace it. If review
      prefers waiting for a real processor instead, that is a scope decision above this design.
