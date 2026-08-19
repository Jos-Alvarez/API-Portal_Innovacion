# Proposal: Reception and Lifecycle of Temporary Files

> **PARKED — split on 2026-08-18.** Item #6 was estimated at 700-900 lines because it held two
> unrelated jobs. The user split them. The three inherited HTTP-boundary obligations (wiring
> `registrar_manejador_401`, overriding FastAPI's `RequestValidationError` handler, and the pre-body
> 401 mechanism) moved to `openspec/changes/borde-de-autenticacion-y-errores-http/` and are being
> built first.
>
> What stays here, unstarted: file reception, name sanitisation against path traversal and accents
> and duplicates, the temporary-file lifecycle, the H-02 resolution (`background=` cleanup plus an
> age-based sweeper, with its stated degradation on client disconnect), and local ADR **0020** recording
> it — 0019 is taken by the authentication-boundary half, which needed one because ADR 0016's
> Decisión names the dependency mechanism verbatim and that mechanism provably cannot meet the PRD. The sections below still describe the whole of item #6 and must be re-scoped before this half
> proceeds.



## Intent

BACKLOG #6 closes the only open **Crítico** finding (H-02: `try/finally` deletes the temp file
before ASGI streams it — happy path is broken, not an edge case) and discharges three obligations
already inherited from items #1–#3: `registrar_manejador_401` unwired, the default
`RequestValidationError` handler leaking raw input, and `Depends()` being unable to satisfy
"401 before reading the body". This is also the first item to wire a real route into `crear_app()`,
which is what makes the three obligations concrete instead of theoretical.

## Scope

### In Scope
- H-02 fix: `background=` cleanup attached to the response, plus an age-based sweeper for the
  client-disconnect gap neither `FileResponse` nor `StreamingResponse` covers (measured, not assumed).
- A generic multipart reception route mounted for `{clave_procesador}`, structurally excluding `/salud`.
- Pre-auth 401 via a `Mount()`-scoped sub-app with ASGI middleware inspecting `scope["headers"]`
  before `receive()` — no path allow-list (ADR 0016).
- `registrar_manejador_401(app)` wired inside `crear_app()`.
- `RequestValidationError` override returning ADR 0014's `{"tipo","contexto"}` without leaking `input`.
- Per-request temp directory creation, name-safety for `ArchivoEntrada.nombre_original`.

### Out of Scope
- Contract validations (#7), bounded admission/child process (#8), packaging (#9), the pipeline (#10),
  startup check (#11), any real processor (#12, #16).
- New runtime dependencies: none. No SQLAlchemy, no pyodbc (item #5 deliberately bypassed).

## Capabilities

### New Capabilities
- `temp-file-reception`: multipart reception, per-request temp storage, name safety, cleanup
  (background + sweeper), the mounted auth boundary, and the validation-error envelope override.

### Modified Capabilities
None — `service-token-auth` and `error-contract` gain wiring, not new requirements.

## Approach

| Decision | Choice | Why |
|---|---|---|
| H-02 | `background=BackgroundTask(cleanup)` on the response **+** an age sweeper | Covers happy path; sweeper covers disconnect leak. **"Zero temporaries after the response" holds on the happy path; it degrades to "zero within N minutes" only on mid-stream disconnect** — written down, not glossed. |
| Sweeper shape | Startup pass + periodic `asyncio` task inside `ciclo_de_vida`, threshold and interval TBD numeric choices (not sourced from any doc) | No document supplies numbers; proposal marks these as choices for `sdd-design` to fix concretely. |
| Pre-auth 401 | ASGI middleware inside a `Mount()` sub-app holding only processor routes | Swapping response classes fixes nothing (measured). Middleware-with-allowlist would violate ADR 0016; mounting keeps `/salud` outside by graph construction, not a list. |
| Validation errors | Custom `RequestValidationError` handler registered in `crear_app()`, built on `exc.errors(include_url=False, include_input=False)` | Prevents the default input leak; reshapes into ADR 0014's envelope. |
| Name safety | Disk filenames are server-generated (not derived from `nombre_original`); `nombre_original` stays verbatim (contract requires raw values) but never touches a path | Closes traversal, accents, and duplicate-name cases at once without touching the error-contract's verbatim-string rule. |
| Temp directory | `tempfile`-based per-request subdirectory, created by the reception route | Platform-neutral; ADR 0012 leaves container-vs-Windows-service undecided — this must not depend on that answer. |
| What's provable | Reception, temp write/cleanup, auth wiring, and typed-error wiring — proven via `obtener_contrato` returning `None` for every key today (item #3/#5 both empty), producing `ErrorClaveInexistente(causa="fila_ausente")` | No real processor exists yet; end-to-end processing is not claimed. |

**H-09**: partially closed. Per-request temp directory and name-traversal/duplicate handling are
settled here. The `Content-Length`-lie streaming cutoff stays open — it needs `tamano_max_bytes`
from the contract, which belongs to item #7, not #6.

**New ADR**: recommended. ADR 0020 for the H-02 resolution (0019 went to the authentication-boundary half) — a genuine architectural decision with
rejected alternatives (read-to-memory, early-unlink) and a stated, honest degradation.

## Affected Areas

| Area | Impact | Description |
|---|---|---|
| `app/main.py` | Modified | Mount sub-app, wire both exception handlers |
| `app/core/temporales.py` | New | Per-request dir, cleanup, sweeper |
| `app/core/seguridad.py` | Modified | ASGI-level check usable inside the mount |
| `app/core/errores.py` | Modified | `RequestValidationError` handler |
| new reception route module | New | Multipart intake for `{clave_procesador}` |

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Disconnect-window leak (measured, not eliminated) | Med | Sweeper bounds exposure to N minutes; documented, not hidden |
| Sweeper numeric thresholds unsourced | Low | Marked explicitly as `sdd-design` choices |
| Route exceeds 400-line review budget | High (certain) | Recorded as `size:exception`, accepted by user; estimate ~700–900 changed lines (route, mount, cleanup, sweeper, handlers, and behavioral tests) |
| No real processor to prove end-to-end flow | Med | Scope states plainly what is/isn't provable |

## Rollback Plan

Each piece is independently revertible: unmount the reception sub-app in `main.py` (removes the live
route, `/salud` unaffected), remove the two `add_exception_handler` calls, delete
`app/core/temporales.py`. No schema, no migration, no persisted state — rollback is a code revert.

## Dependencies

- Items #1 and #3 (archived, shipped).
- No new runtime packages.

## Success Criteria

- [ ] `registrar_manejador_401` runs inside `crear_app()`; a 401 fires before the body is read.
- [ ] `/salud` remains publicly reachable and unauthenticated by construction (no allow-list).
- [ ] A validation failure returns `{"tipo","contexto"}`, never leaks raw input, never `{"detail":...}`.
- [ ] Happy-path requests leave zero temporaries after the response.
- [ ] A simulated mid-stream disconnect leaves zero temporaries within the sweeper's window.
- [ ] Path-traversal/accented/duplicate names never touch the filesystem path.

## Proposal question round

Per SDD interactive protocol, these would normally be asked before finalizing; auto-mode and the
already-settled decisions in the launch brief let this proceed, but they remain open for correction:

1. Sweeper interval/age threshold — no document sources a number. Proposal defers exact values to
   `sdd-design`; flag if a specific SLA exists that should drive them.
2. Should the reception route accept a body at all when `obtener_contrato` returns `None`, or should
   the contract check gate access before any multipart parsing begins? Affects how much of H-09's
   streaming-cutoff question genuinely belongs to #6 versus #7.
3. Is `ErrorClaveInexistente(causa="fila_ausente")` the right causa for "no processor registered yet"
   versus a data-desync causa — confirm this reading of ADR 0018 is correct for the demo route.
