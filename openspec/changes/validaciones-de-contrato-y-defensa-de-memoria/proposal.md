# Proposal: Contract Validations and Memory Defense

## Intent

`app/recepcion.py:95` has an explicit seam — `del entradas  # costura del ítem #7` — left unfilled
since item #6 shipped. Today every uploaded file is copied fully to disk before anything checks its
count, format, size, or declared uncompressed size against the receiving processor's contract. This
change fills that seam: `app/core/validaciones.py` (a name already reserved in TECH-DESIGN.md and
ADR 0011) applies `ContratoProcesador`'s four existing limits, plus a first-line defense against
declared-uncompressed-size zip bombs, before `recibir()` reaches the `NotImplementedError` placeholder.

Why now: item #6 deliberately parked this ("Out of scope: contract validations (#7)") and left the
seam as the next concrete step. Nothing downstream (#9/#10, real processors #12/#16) can safely
accept arbitrary uploads without it.

## Scope

### In Scope

- `app/core/validaciones.py`: pure functions checking cantidad, formato, tamaño-por-archivo,
  tamaño-total against `ContratoProcesador`, plus a declared-uncompressed-size check against a
  global RAM-budget constant.
- Reordering `recibir()`'s per-file loop so cantidad/formato/tamaño-per-file use `carga.size`
  (already tracked by Starlette's spool) before the second copy into the per-request directory —
  cheap-before-expensive wherever the multipart layer allows it.
- A bounded, early-aborting `_copiar()` variant enforcing `tamano_max_bytes` while writing. It is
  **not** there to catch a size lie — `carga.size` is a measured count and cannot carry one (see the
  correction recorded under "Proposal question round"). It is there because `carga.size` is
  `int | None` and the copy is the **only** enforcement when it is `None`; because ADR 0020 fixes
  `tamano_comprimido` as "bytes that landed on disk", which a writer-side ceiling keeps true by
  construction; and because items #9/#10 are the next callers of this seam and must not be able to
  exceed the limit by forgetting the pre-check.
- Extending `app/core/errores.py`'s context payloads (not the closed `TipoError` enum) to fit a
  total-sum size violation.
- One new ADR recording the three decisions below.

### Out of Scope

- The real memory ceiling on the child process (Job Object / cgroup / `RLIMIT_AS`) — item #8. This
  change's declared-size check is a first line of defense only; it does not deliver "never an OOM."
- Output packaging (#9), pipeline orchestration (#10), startup check (#11), concrete processors
  (#12, #16).
- Any change to item #6's temporary-file lifecycle (`try/finally`, sweeper, background cleanup) —
  a validation failure raises a typed error mid-loop; the existing `finally: reserva.limpiar()`
  already covers it.
- A true byte-level cutoff at the ASGI/`receive()` layer (Approach 2, rejected) or replacing
  `File()` with manual `request.form(max_part_size=...)` (Approach 3, evaluated and deferred — see
  Decision 1).
- Adding a sixth `TipoError` value. ADR 0014 closes the enum at five; inherited ADRs outrank this
  repo's.

## Capabilities

### New Capabilities

- `contract-validation`: cantidad/formato/tamaño-per-file/tamaño-total checks against
  `ContratoProcesador`, plus the declared-uncompressed-size RAM-budget check, applied at the
  `del entradas` seam before any processor sees the upload.

### Modified Capabilities

- `temp-file-reception`: the per-file loop's requirement "every uploaded file is copied
  unconditionally" changes to "count/format/size are checked, using `carga.size`, before the second
  copy; the copy itself now aborts early if the running total exceeds the per-file limit."
- `error-contract`: `ContextoTamano`'s existing three fields remain untouched; a new sibling context
  shape is added for a total-sum violation (see Decision 2). `TipoError`'s five-value enum is
  unchanged.

## Decisions

### Decision 1 — How far this item closes H-09

Verified against installed `starlette==1.6.0` source (see `exploration.md`): file-part bytes have no
size ceiling anywhere in Starlette's own multipart parse path that FastAPI's `File()` dependency
uses. That parse completes — spooling every byte, rolling to OS temp disk past 1MB per part — before
`recibir()`'s body ever runs.

**Decision: ship Approach 1 only — a bounded, early-aborting `_copiar()` at the existing seam.**
Stated plainly, not glossed: **this is a disk defense, not a RAM defense.** It keeps
`reserva.directorio` from being filled past `tamano_max_bytes` during the *second* copy (spooled
temp → per-request temp file) and stops the request before returning success, but it runs strictly
after Starlette's own unbounded first parse has already spooled the bytes somewhere (memory, then OS
temp disk past 1MB per part). It does not, and cannot from inside `recibir()`, prevent that first
spool from happening.

What the ceiling is **not** for, corrected against the installed source: it is not a guard against a
lying `carga.size`. `starlette/formparsers.py:232-237` constructs every file part with `size=0` and
`starlette/datastructures.py:451-454` does `self.size += len(data)` on each chunk written, so
`carga.size` is a **measured** byte count. There is no size lie for the copy to catch. The ceiling
earns its place through the three reasons in Scope instead: `size` is `int | None`, ADR 0020's
"bytes that landed on disk" definition, and the future callers of this seam.

Approach 3 (`request.form(max_part_size=...)`, dropping the declarative `File()` dependency) is
**rejected on evidence**, not deferred. `starlette/formparsers.py:182-187` guards the
`max_part_size` check behind `if self._current_part.file is None:` — the ceiling applies to
non-file form fields only, never to file parts, which go straight to `_file_parts_to_write` with no
size check at all. Adopting it would change the shipped `recibir()` signature, lose FastAPI's
OpenAPI-declared parameter, and close nothing.

Approach 2 (a new ASGI middleware counting raw bytes in `receive()`) is therefore the only
mechanism that can abort before the parser writes anything. It was surfaced to the user as such,
with its full cost: new architectural surface beside `AutenticacionDeBorde`, a change to
`app/main.py`, and a fresh question about which typed error a mid-stream abort produces. **The user
chose the bounded loop and to leave H-09 declared open** — recorded here as a deliberate scope
decision, not an oversight.

**Net effect stated honestly**: after this change, a finite oversized body is refused before a single
byte reaches `reserva.directorio` — normally at the pre-check, on `carga.size`, at zero disk cost. A
client that streams an effectively unbounded body is still fully spooled by Starlette before this
code ever runs — that gap is named here, not closed here.

Scale of the exposure, measured rather than assumed: `formparsers.py:147` sets
`spool_max_size = 1024 * 1024`, capping each part's RAM footprint at 1MB before it rolls to OS temp
disk. The unbounded resource is therefore **disk**, across Starlette's default `max_files = 1000`
parts of unbounded size each — not RAM. The follow-up that closes it is the ASGI middleware or item
#8's memory-ceiling work; it is explicitly *not* Approach 3, which the evidence above rules out.

### Decision 2 — Error mapping for the two cases the closed enum doesn't fit cleanly

No sixth `TipoError` value is added (ADR 0014 stays closed at five). The context payloads are not
closed by that ADR — only the enum member set is.

- **Single-file size violation**: reuses `ErrorTamano`/`ContextoTamano` exactly as it exists today —
  `archivo` names the offending file, `limite_bytes` is `tamano_max_bytes`, and `recibido_bytes` is
  a real count on both paths, never an estimate. Which path fires decides which count it is: at the
  **pre-check** (the normal path) it is `carga.size`, Starlette's measured total, with zero bytes
  written; at the **bounded-copy abort** (the path taken when `carga.size` is `None`) it is the
  bytes actually copied before the ceiling was crossed. This case fits the existing shape without
  any change.
- **Total-sum violation** (every individual file passes, but the running sum exceeds
  `tamano_max_total_bytes`): no single `archivo` caused it, so `ContextoTamano`'s shape is left
  untouched (it stays ADR-0014-verbatim for the single-file case) and a new sibling TypedDict is
  added to `app/core/errores.py`: `ContextoTamanoTotal = {archivos: list[str], limite_bytes: int,
  recibido_bytes: int}`, joined into the existing `Contexto` union. `ErrorTamano` gains a
  `ErrorTamano.total(*, archivos, limite_bytes, recibido_bytes)` classmethod (same pattern as
  `ErrorContenido.columna_faltante`/`.cero_filas` already in that file) so both cases still raise the
  same exception class and map to the same `TipoError.TAMANO` / HTTP 422.
- **Declared-uncompressed-size over the RAM budget**: mapped to `ErrorTamano` too (a size failure,
  matching TECH-DESIGN step 5's own "tipo tamaño" framing), with `archivo` naming the offending file
  and `limite_bytes`/`recibido_bytes` holding the RAM budget and the declared uncompressed size.

### Decision 3 — Where the RAM-budget constant lives

**Decision: a global module-level `Final` constant in `app/core/validaciones.py`**, following
`app/core/temporales.py`'s precedent (`UMBRAL_DE_EDAD`/`INTERVALO_DE_BARRIDO`) rather than a new
field on `ContratoProcesador`. ADR 0006 heritage treats the memory ceiling as a worker-level concern,
not a per-processor value, and no operational need for per-processor tuning has surfaced. This keeps
`app/core/contrato.py` — already a deliberate deviation module (ADR 0013) — untouched. Revisit if a
real processor later needs a different ceiling; that would be a second, deliberate design change,
not an oversight here.

## Affected Areas

| Area | Impact | Description |
|---|---|---|
| `app/core/validaciones.py` | New | Cantidad/formato/tamaño/zip-bomb checks, RAM-budget constant |
| `app/recepcion.py` | Modified | Reordered loop (cheap checks before second copy), bounded `_copiar`, validation call at the seam |
| `app/core/errores.py` | Modified | `ContextoTamanoTotal` TypedDict, `ErrorTamano.total()` classmethod, `Contexto` union grows one member |
| `adrs/0021-*.md` | New | Records Decisions 1-3 above, with rejected alternatives |
| `tests/test_validaciones.py` | New | Unit tests for the validation functions in isolation |
| `tests/test_recepcion.py` | Modified | Route-level tests monkeypatching `obtener_contrato`, covering all five failure axes plus the reordering |

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| H-04 (Crítico) not fully closed — declared-size check alone does not prevent an OOM from a real decompression bomb | High (by design) | Stated explicitly in Scope and Decision 1; item #8 owns the real memory ceiling. Not sold as more than a first line of defense. |
| H-09 not fully closed — an unbounded streamed body still spools fully before this code runs; the exposed resource is OS temp disk (RAM stays capped at 1MB/part by `spool_max_size`), across up to `max_files=1000` parts | Med | Named honestly in Decision 1, with the user's decision to accept it for this item on record. Follow-up is the ASGI middleware or item #8 — not Approach 3, ruled out by `formparsers.py:182-187`. |
| `ContextoTamanoTotal` addition read as reopening the closed-error-vocabulary question | Low | ADR explicitly distinguishes "enum closed" from "context payloads open"; new ADR documents the distinction with rationale. |
| Reordering the per-file loop changes `_copiar`'s call contract, risking a regression in item #6's shipped behavior | Low | `tests/test_recepcion.py` already covers the loop; existing assertions extended, not replaced, to catch regressions. |
| `_TABLA_CONTRATOS` is still empty — no end-to-end test through the real route without monkeypatching | Med | Same pattern item #6 already used (monkeypatching `temporales.Reserva.limpiar`); applied here to `obtener_contrato`. |

## Rollback Plan

Each piece is independently revertible: remove the validation call at the seam in `app/recepcion.py`
and restore the unconditional `_copiar()` loop (reverting to today's shipped, tested behavior);
delete `app/core/validaciones.py`; revert `app/core/errores.py`'s `ContextoTamanoTotal` addition
(purely additive, so reverting drops one union member with no other code depending on it yet); revert
the new ADR. No schema, no migration, no persisted state — rollback is a code revert with no data
cleanup, same as item #6's precedent.

## Dependencies

- `recepcion-y-ciclo-de-vida-de-temporales` (archived, shipped): the seam this change fills, and the
  `try/finally` guarantee this change relies on without modifying.
- No new runtime dependency. `zipfile` is standard library.

## Changed-lines estimate

Named honestly, following the project's own logged pattern: the last five items' design-phase
forecasts ran 30-50% short, always because of the test file (`openspec/config.yaml`'s own note:
419/~500/419/277/~460 delivered against short forecasts). Estimating with that pattern priced in,
not repeating it:

| Piece | Estimate |
|---|---|
| `app/core/validaciones.py` (5 check functions + RAM-budget constant + docstrings) | ~150-180 |
| `app/recepcion.py` (reordered loop, bounded `_copiar`, seam wiring) | ~70-90 |
| `app/core/errores.py` (`ContextoTamanoTotal`, `ErrorTamano.total()`, union update) | ~30-40 |
| ADR 0021 (prose, counted against the review budget per project convention) | ~90-110 |
| `tests/test_validaciones.py` (unit tests, 5 axes x pass/fail, sum vs per-file, zip-bomb fixture) | ~200-260 |
| `tests/test_recepcion.py` additions (route-level, monkeypatched contract, all five failure paths, reordering regression) | ~150-200 |
| **Total** | **~690-880** |

Above the 600-line review budget most likely, consistent with every prior item in this project. This
is a first-pass estimate for the proposal phase, not a commitment — `sdd-tasks` must re-forecast with
the actual work breakdown and apply the review-workload guard (chained/stacked PR slices, or an
explicit `size:exception`), per `delivery_strategy: ask-on-risk`.

## Success Criteria

- [ ] A request with a file count outside `entradas_min`/`entradas_max` raises `ErrorCantidad`
      before any file in the batch is written to the per-request directory.
- [ ] A request with an unaccepted extension raises `ErrorFormato` using `carga.size`/name checks
      before the second copy, for at least the first offending file.
- [ ] A single file over `tamano_max_bytes` raises `ErrorTamano` with `recibido_bytes` holding a real
      count on whichever path fired: `carga.size` (measured by Starlette, zero bytes written) when the
      pre-check catches it, or the bytes actually copied before the bounded `_copiar` aborted when
      `carga.size` was `None`. Never an estimate, and never a client-declared number.
- [ ] With `carga.size` absent, the bounded `_copiar` is the sole enforcement: it stops writing at
      `tamano_max_bytes`, closes the output handle before raising, and reports the real byte count.
- [ ] A batch whose individual files each pass but whose sum exceeds `tamano_max_total_bytes` raises
      `ErrorTamano` via `ErrorTamano.total()`, with `ContextoTamanoTotal` populated correctly.
- [ ] A file whose ZIP central-directory declares an uncompressed size over the RAM-budget constant
      raises `ErrorTamano` without ever decompressing the file's contents.
- [ ] `ContextoTamano`'s existing three-field shape for the single-file case is unchanged (regression
      guard on ADR 0014's verbatim shape).
- [ ] `TipoError` remains exactly five values; no new enum member is introduced.
- [ ] ADR 0021 records all three decisions above, including the honestly-scoped H-09/H-04 status.

## Proposal question round — resolved

Answered by the user on 2026-08-19; recorded here so later phases do not reopen them.

1. **H-09 closure depth.** The user first chose to close H-09 fully in this change. Verification
   against the installed Starlette source before any rewrite showed the proposed mechanism
   (`request.form(max_part_size=...)`) does not bound file parts at all — `formparsers.py:182-187`.
   Re-asked with the corrected evidence, and with the RAM/disk distinction stated properly, the user
   chose **the bounded copy loop (Approach 1)**, with H-09 declared open until the ASGI middleware
   or item #8. Decision 1 above reflects this.
2. **`ContextoTamanoTotal` as a new context shape** rather than a `"(total)"` sentinel on
   `ContextoTamano.archivo`: **confirmed as proposed**.
3. **RAM-budget constant stays global**, not a per-processor `ContratoProcesador` field:
   **confirmed as proposed**. No known processor needs a different ceiling.

## Correction — the "lying `carga.size`" premise was false

Recorded rather than silently rewritten, because it was load-bearing prose in Scope, Decision 1 and
Decision 2 for one full phase.

The design phase's verification table (V1) read the installed `starlette==1.6.0` source and found
that `UploadFile.size` is **measured, not declared**: `formparsers.py:232-237` constructs every file
part with `size=0`, and `datastructures.py:451-454` does `self.size += len(data)` on every chunk
actually written. A client's `Content-Length` never reaches that field, so the original justification
for the bounded copy — "closing the gap between a lying `carga.size` and what actually lands on
disk" — described a gap that does not exist.

**The decision did not change.** The bounded, early-aborting `_copiar()` still ships, on three
rationales that survive the correction: `carga.size` is `int | None` and the copy is the only
enforcement when it is `None`; ADR 0020 fixes `tamano_comprimido` as bytes that landed on disk, which
a writer-side ceiling keeps true by construction; and items #9/#10 are the next callers of this seam.
Only the rationale, and the `recibido_bytes` wording it drove in success criterion 3, were rewritten.
`design.md` §3 carries the full argument; the `contract-validation` and `temp-file-reception` deltas
were reconciled to match.
