# Proposal: Reception and Lifecycle of Temporary Files

> **Re-scoped 2026-08-18.** This proposal previously described the whole of BACKLOG #6. The three
> inherited HTTP-boundary obligations shipped in `borde-de-autenticacion-y-errores-http`
> (`122dfa0`, 108 tests green): `registrar_manejador_401`, `registrar_manejador_validacion`, and
> `registrar_manejador_errores` are all wired inside `crear_app()`; `RequestValidationError` returns
> 422 with an empty body, deliberately outside ADR 0014's closed vocabulary; and
> `Mount("/interno", app=router_interno, middleware=[Middleware(AutenticacionDeBorde)])` exists,
> recorded in ADR 0019. `router_interno` is currently **empty**. This document covers only what
> remains.

## Intent

`router_interno` has a mount and no routes. This change puts the first one in it, and in doing so
resolves the only open **Crítico** finding, H-02: the pipeline's documented `try/finally` deletes a
temporary file before ASGI streams it, breaking the happy path, not an edge case. Nothing can be
received or cleaned up correctly until this is fixed, and nothing proves the mount actually works
until a route lives inside it.

Why now: this is the natural continuation of the authentication-boundary half — the mount exists
specifically so a route can go inside it, and H-02 was already measured (not just described) during
exploration, so the fix is no longer speculative.

## Scope

### In Scope

- **H-02 fix**: `background=` cleanup attached to the response, plus an age-based sweeper for the
  client-disconnect gap neither `FileResponse` nor `StreamingResponse` covers on the pinned
  Starlette 1.6.0 / FastAPI 0.141.1 (measured, not assumed — see Approach).
- **File reception**: a route inside `/interno` that accepts a multipart upload and writes it to a
  per-request temporary location on disk.
- **Name sanitisation**: closing the path-traversal, accent, and duplicate-name cases PRD.md:283-285
  lists, concretely enough to implement.
- **The temporary-file lifecycle**: creation, cleanup on the happy path, and the sweeper's bound on
  the disconnect path.
- **ADR 0020**, recording the H-02 resolution with its measured evidence and rejected alternatives.

### Out of Scope

- Contract validations (#7), bounded admission and the child process (#8), output packaging (#9),
  the pipeline (#10), the startup check (#11), any concrete processor (#12, #16).
- Any change to the three shipped HTTP-boundary obligations, the mount mechanism itself, or ADR 0019.
- New runtime dependencies beyond the one justified below. No SQLAlchemy, no pyodbc (item #5 was
  deliberately bypassed — see `app/core/contrato.py`).

## Capabilities

### New Capabilities

- `temp-file-reception`: multipart reception, per-request temp storage, name sanitisation, and
  cleanup (background task + sweeper) for a route mounted inside `/interno`.

### Modified Capabilities

None. `service-token-auth` and `error-contract` are unaffected — this change adds a consumer of the
existing mount and existing error types; it does not touch their requirements.

## Decisions

### H-02 — measured, not re-derived

Verified on the pinned Starlette 1.6.0 / FastAPI 0.141.1 (see `exploration.md` for the exact
introspection):

- `FileResponse._handle_simple` has **no** OSError/disconnect guard around `send()`.
- `StreamingResponse.__call__` **does** guard the send loop, but converts the failure into
  `raise ClientDisconnect()` — the exception still propagates.
- Both classes call `self.background()` only **after** the send loop completes, and both propagate
  on disconnect, so **both skip cleanup on a mid-stream disconnect**. Swapping response classes
  fixes nothing — this is the obvious wrong fix and is rejected explicitly in ADR 0020.
- Early-unlink (open the handle, unlink the directory entry, keep streaming) is POSIX-only. ADR 0012
  leaves the deployment target (container vs. native Windows service) undecided, so nothing here may
  depend on a Windows-incompatible mechanism.

**Decision: `background=BackgroundTask(cleanup)` on the response, plus an age-based sweeper.** The
background task covers the normal path — the send loop completes, `background()` runs, the temporary
is gone. The sweeper covers the hole neither response class closes: a client that disconnects
mid-stream.

**Stated plainly, not glossed**: "zero temporaries after the response" holds on the happy path. It
degrades to "zero within N minutes" when a client disconnects mid-stream. This is a real, accepted
weakening of ADR 0006's inherited wording ("eliminar los temporales una vez enviada la respuesta
HTTP"), not a hidden one.

**Sweeper shape** (choices this proposal makes because no document supplies numbers):

| Parameter | Choice | Rationale |
|---|---|---|
| Mechanism | A periodic `asyncio` task started in `ciclo_de_vida`, plus one startup pass before the first `yield` | ADR 0012 fixes exactly **one API worker**; a single in-process periodic task has no cross-worker coordination problem, unlike a pool. The startup pass catches temporaries orphaned by a prior process death (crash, forced restart) before the periodic task's first tick. |
| Age threshold | 15 minutes | No PRD/TECH-DESIGN value exists. Chosen against the portal's 2-minute request cutoff (ADR 0012, `TECH-DESIGN.md:300`) with a wide margin: any legitimately in-flight temporary is long gone by 15 minutes even accounting for scheduling jitter. Marked explicitly as a value `sdd-design` may firm up, not a sourced requirement. |
| Sweep interval | 5 minutes | Bounds worst-case exposure to threshold + interval ≈ 20 minutes without sweeping so often it competes for the single worker's event loop. Same status as the threshold: a choice, not a citation. |
| Where the value lives | A named constant in `app/core/temporales.py`, not `Configuracion` | No operational need has been identified to tune it per environment; adding it to `Configuracion` before that need exists is speculative. Revisit if operations asks for it. |

### Temporary directory placement

**Decision**: a per-request subdirectory under `tempfile.gettempdir()`, created by the reception
route at the start of each request and named with a server-generated random identifier (not derived
from any client-supplied name). This is platform-neutral by construction — `tempfile.gettempdir()`
resolves correctly on both a Linux container and a native Windows service — which matters because
ADR 0012 leaves that choice undecided and nothing here may bind it.

### Name sanitisation — concrete rule

PRD.md:283 lists the risk: *"Nombres de archivo con caracteres especiales, acentos, espacios o rutas
embebidas — riesgo de path traversal al escribir temporales y al armar el ZIP de salida."*
PRD.md:285 adds: *"Dos archivos de entrada con el mismo nombre en una carga múltiple."*

**Decision**: disk filenames are always server-generated, never derived from
`ArchivoEntrada.nombre_original`. Concretely:

- **What is stripped**: nothing from `nombre_original` — it is never parsed for path components,
  never has characters stripped or replaced, because it never touches a filesystem path. The
  error-contract's verbatim-string rule (ADR 0014) needs the original name preserved exactly, and
  the cleanest way to guarantee no accidental leakage of a traversal payload into a path is to never
  let the string reach `Path()` construction at all.
- **What is replaced**: the entire on-disk name is replaced by a generated identifier (e.g. an
  index within the per-request directory, `entrada_0`, `entrada_1`, ...). `nombre_original` is
  stored unchanged in `ArchivoEntrada.nombre_original` for downstream consumers (the error contract,
  future contract validations); it is data, never a path.
- **How duplicates are disambiguated**: by construction — each `ArchivoEntrada` gets its own
  generated disk name from its position in the upload, so two client-supplied files sharing a
  `nombre_original` never collide on disk. Nothing needs deduplication logic because the generated
  names were never derived from the colliding input.
- **What happens to a name that sanitises to nothing**: this case cannot occur, because sanitisation
  never runs on the name — there is no code path where an empty or invalid string could reach a path
  operation. `nombre_original` is retained as given, including if it is empty or degenerate; nothing
  downstream in this change's scope treats an empty `nombre_original` as an error (that judgment, if
  needed, belongs to item #7's contract validations).

This closes traversal, accents, and duplicate names in one decision rather than three separate
escaping rules, and does not touch the error-contract's requirement that `nombre_original` stay
verbatim.

### The route

**Path**: `POST /interno/procesadores/{clave_procesador}` inside the existing mount.

**Tension flagged honestly**: ADR 0006 (heredado) decides the FastAPI service exposes "una ruta
interna por procesador" — a distinct, literally-named endpoint per processor
(`POST /interno/procesadores/maestro-excel/ejecutar` is its own example), explicitly rejecting "una
sola ruta genérica" as an alternative. That decision assumes at least one real processor to name.
None exists yet (`_TABLA_CONTRATOS` in `app/core/contrato.py` is empty on purpose — items #12/#16
populate it). Writing a literal per-processor route today would have no processor to route to.

This change therefore adds **one** parametrised route as reception scaffolding — proving the mount,
the reception mechanics, and the error wiring end-to-end — explicitly **not** the permanent shape
ADR 0006 specifies. It does not amend ADR 0006 and does not require a new ADR of its own for this
choice: it is a temporary, flagged deviation, not a competing architectural decision. Item #12/#16
is expected to replace it with the literal per-processor cascada routes ADR 0006 describes as real
processors are registered; this proposal does not decide that migration, it names the gap so it
isn't mistaken for the finished design.

**What this route can actually prove today**: `obtener_contrato(clave_procesador)` returns `None`
for every key — `_TABLA_CONTRATOS` is empty (item #5 was bypassed; items #12/#16 populate it later).
The only reachable outcome through this route, for any `clave_procesador`, is
`ErrorClaveInexistente(causa="fila_ausente")` — a 500 per ADR 0018's `_ESTADO_HTTP` mapping. This
proves: the mount's auth boundary sits in front of the route (a request without a valid token never
reaches it), multipart reception writes and later removes a temporary file, and the typed-error path
resolves to a real HTTP response. It does **not** prove any contract validation, any real processing,
or any success path — none of that exists yet. Framing this as an end-to-end demonstration of
reception and cleanup, not of processing, is deliberate and should not be oversold in review.

**Shape**: accepts one or more `UploadFile` values under a fixed field name, matching ADR 0006's
"lista de archivos" interface direction ahead of item #7 giving it real cardinality limits. Each
upload is streamed to its generated path inside the per-request directory (`ArchivoEntrada`
population), the contract lookup runs, finds nothing, and raises — the response is entirely handled
by the already-registered `ErrorTipificado` handler. Cleanup runs via `background=` regardless of
which path is taken, because the response's `background` argument is set unconditionally before
return/raise reaches the ASGI layer.

**New dependency required**: FastAPI's `File`/`UploadFile` machinery needs `python-multipart` at
import/request time — the project has no multipart-parsing package today (`pyproject.toml`:9-12
lists only `fastapi`, `uvicorn[standard]`, `pydantic-settings`). Without it, FastAPI raises at
startup or at first request. This is the one new runtime dependency this change requires, named
explicitly rather than added silently: it is required by the reception mechanism itself, not
optional tooling.

### H-09 — partially closed, stated explicitly

`REVISION-ADVERSARIAL.md` H-09 (Advertencia, Abierto) lists four undecided edge cases:

1. `Content-Length` ausente o mentido → cortar mientras se lee el stream. **Stays open.** Cutting
   mid-stream needs `tamano_max_bytes` from the processor's contract (`ContratoProcesador`), which
   is item #7's, not this change's. This change can write a file to disk; it has no size ceiling to
   enforce one against yet.
2. Nombres con caracteres especiales o rutas embebidas. **Closed** by the sanitisation decision
   above.
3. Dos archivos con el mismo nombre. **Closed** by the same decision.
4. El directorio temporal por petición que los criterios de aceptación mencionan pero ninguna
   decisión define. **Closed** by the temporary-directory decision above.

Three of four close here; the fourth is correctly item #7's, not artificially pulled forward.

## Affected Areas

| Area | Impact | Description |
|---|---|---|
| `app/core/temporales.py` | New | Per-request directory creation, cleanup, sweeper |
| new reception route module (e.g. `app/procesadores_ruta.py`) | New | The `/interno/procesadores/{clave_procesador}` scaffolding route |
| `app/main.py` | Modified | Register the new route inside `router_interno` |
| `pyproject.toml` | Modified | Add `python-multipart` to `dependencies` |
| `adrs/0020-*.md` | New | H-02 resolution record |
| `tests/test_seguridad_token.py` | Modified | Route-pin expectation grows a real route inside the `Mount` |

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Disconnect-window leak (measured, not eliminated) | Med | Sweeper bounds exposure to ~20 minutes worst case; stated plainly, not hidden |
| Sweeper threshold/interval unsourced | Low | Marked explicitly as this proposal's choices, not requirements; easy to retune, isolated to one module |
| Generic route reads as the finished per-processor design | Med | Flagged explicitly in this proposal and in the route module's own docstring; item #12/#16 replaces it |
| `python-multipart` addition surprises a reviewer expecting zero new deps | Low | Justified explicitly here rather than added silently |
| No real processor to prove a success path | Med | Scope states plainly what this route proves and doesn't |

## Rollback Plan

Each piece is independently revertible: remove the route registration in `main.py` (the mount and
its middleware are untouched, shipped separately), delete `app/core/temporales.py` and the route
module, remove `python-multipart` from `pyproject.toml`, revert the `test_seguridad_token.py` pin.
No schema, no migration, no persisted state — rollback is a code revert with no data cleanup.

## Dependencies

- `borde-de-autenticacion-y-errores-http` (archived, shipped, `122dfa0`): the mount and all three
  exception handlers this change builds on top of.
- New runtime dependency: `python-multipart` (justified above).

## Changed-lines estimate

Named honestly: the forecast has run short on the last four items in this project, each time through
the test file. Estimating conservatively with that pattern in mind:

| Piece | Estimate |
|---|---|
| `app/core/temporales.py` (dir creation, cleanup, sweeper, startup pass) | ~120 |
| Route module (`{clave_procesador}` scaffolding, multipart handling) | ~60 |
| `main.py` wiring | ~10 |
| `pyproject.toml` | ~1 |
| ADR 0020 | ~90 (prose, not code, but counted against the review budget per project convention) |
| Behavioural tests (reception, sanitisation, cleanup, sweeper, disconnect simulation, route pin update) | ~350–450 |
| **Total** | **~630–730** |

Above the 400-line review budget, as the last four items in this project also were. Recorded as
`size:exception`, following the same accepted pattern as the parked half of this item, and expected
to be accepted the same way rather than force an artificial split of a lifecycle fix that has to
land as one reviewable unit (partial cleanup logic without its sweeper, or vice versa, is not
independently safe to ship).

## Success Criteria

- [ ] `POST /interno/procesadores/{clave}` is reachable only through the authenticated mount (401
      before body read, per the shipped middleware).
- [ ] A multipart upload writes to a server-generated per-request temporary path; `nombre_original`
      never becomes part of that path.
- [ ] Path-traversal, accented, and duplicate-name inputs never touch the filesystem path.
- [ ] Happy-path requests leave zero temporaries after the response.
- [ ] A simulated mid-stream disconnect leaves zero temporaries within the sweeper's stated window.
- [ ] Every request through this route today resolves to `ErrorClaveInexistente(causa="fila_ausente")`
      and a 500, because no processor is registered — asserted explicitly, not incidentally.
- [ ] ADR 0020 records the H-02 resolution, its measured evidence, and its rejected alternatives.
- [ ] `tests/test_seguridad_token.py`'s route-pin expectation is updated for the new route inside the
      `Mount` and stays green.

## Proposal question round

Per SDD interactive protocol, these would normally be asked before finalizing; auto-mode and the
already-settled decisions in the launch brief let this proceed, but they remain open for correction:

1. Sweeper interval (5 min) and age threshold (15 min) are this proposal's choices, not sourced from
   any document. Flag if an operational SLA exists that should drive them instead.
2. This change adds `python-multipart` as the one new runtime dependency. Confirm that's acceptable,
   or say if reception should be deferred until a broader dependency decision is made elsewhere.
3. The route's parametrised shape (`{clave_procesador}`) is explicitly temporary scaffolding, not
   ADR 0006's final per-processor design. Confirm that framing is acceptable for review, versus
   preferring to wait for a first real processor before wiring any route into `/interno`.
