# Proposal: Output Packaging (ADR 0011 / BACKLOG item #9)

## Intent

TECH-DESIGN.md (line 67) and ADR 0011 (lines 27-50) already name the target module:
`app/core/empaquetado.py`, with no implementation yet. `app/recepcion.py:188-190` ends in
`raise NotImplementedError` with an explicit comment assigning the seam to items #9/#10.
Today there is no point in the pipeline that turns a module's list of outputs
(`list[ArchivoSalida]`, already produced atomically by shipped item #8) into the single entity the
HTTP layer can return. Without this module, item #10 (the full pipeline) has nothing to compose
step 8 from, and the seam documented in `recepcion.py` stays blocked. Why now: items #3 (typed
errors) and #6 (temp files) — its declared dependencies — are archived and shipped; item #8, its
natural caller even though it is not a formally declared dependency, has also already shipped
`ejecutar_modulo() -> list[ArchivoSalida]` with a guaranteed all-or-nothing output.

## Scope

### In Scope

- New `app/core/empaquetado.py`: a function that receives `archivos: list[ArchivoSalida]` and a
  target directory (the caller's `Reserva.directorio`) and returns a single `ArchivoSalida` — the
  input itself when there is only one output, or a new one pointing at a freshly written `.zip`
  when there are two or more.
- Zero outputs raises `ErrorTipificado` (`ErrorContenido`, exact shape pending — see Decision 4)
  before writing any file.
- The ZIP is assembled in a real temp file inside the caller's directory (not in memory), fully
  written and closed before the function returns (see Decisions 1 and 2).
- Flat names inside the ZIP (`arcname` with no path separators), with `nombre_propuesto`
  defensively sanitized (see Decision 3).
- An explicit policy for duplicate `nombre_propuesto` values across the outputs of a single call
  (see Decision 3).
- Behavioural tests: a single output passes through unchanged; multiple outputs produce a flat,
  complete ZIP; zero outputs raises the typed error before touching disk; a hostile name stays
  confined; a simulated failure during the write leaves no partial `.zip` visible or returned.

### Out of Scope

- `app/recepcion.py` is not touched. The seam documented at lines 188-190
  (`return FileResponse(salida, background=reserva.ceder_limpieza())`) is item #10's
  responsibility, just as item #8 left its own HTTP translation out of its scope.
- Building the HTTP response (`FileResponse`, the `Content-Disposition` header, encoding of
  non-ASCII names) — item #10's work, since it is the one that builds the final `Response`.
- Orchestrating the 9-step pipeline (item #10). This item ships a composable piece, not a second
  `try/finally` competing with the ones in `temporales.py`/`ejecucion.py`.
- Any ceiling on total output size (no output-side equivalent of `PRESUPUESTO_DE_RAM_BYTES` exists
  today; none is introduced in this item).
- Byte-level determinism of the ZIP container (fixed timestamps, pinned `external_attr`) — nothing
  in PRD/TECH-DESIGN requires it today, and no parity fixture demands it (items #15/#16 are not
  built). See Decision 6.
- A new formal ADR for Decision 4 is not written in this item — it is left named for `sdd-design`;
  the next free number verified against `adrs/` is **0023** (do not trust the stale comment in
  `openspec/config.yaml:8`, which says "0011-0015").

## Capabilities

### New Capabilities

- `output-packaging`: pure packaging of `list[ArchivoSalida]` into a single `ArchivoSalida`
  (passthrough or flat ZIP), including the typed zero-output error.

### Modified Capabilities

- `errores-tipificados`: `ContextoContenido`/`motivo` possibly gains a new shape to cover "the
  module returned no output at all" — the exact scope is Decision 4, closed in design, not here.

## Decisions

### Decision 1 — ZIP to a temp file, not in memory

The ZIP is written to a real file inside `reserva.directorio`; it is not assembled in an
`io.BytesIO`. Rationale: ADR 0020 already explicitly names "el ZIP intermedio" as a temporal that
must be cleaned up, and all the existing lifecycle machinery (`Reserva`, the sweeper) is disk-based
— building in memory would leave that artifact outside that coverage for no reason. The exact
mechanics (whether it reuses `_copiar`'s bounded-write pattern, the temp file name, whether it is
renamed on close) are left to `sdd-design`.

### Decision 2 — What "nunca un ZIP a medias" means for this item

Item #8 already guarantees that `procesar()` is all-or-nothing before packaging ever runs — the
"partial module output" risk is resolved upstream. The guarantee that *is* this item's
responsibility: the ZIP file must be completely written and closed (`ZipFile.close()` without an
exception) before the function returns an `ArchivoSalida` referencing it; if the write fails at any
point, the function raises before returning and never hands back a handle to a partial file. ZIP
bytes are never assembled directly into a response body — that is already ruled out because this
module never sees HTTP types.

### Decision 3 — Names inside the ZIP: defensive sanitization and duplicates as an error

`nombre_propuesto` is controlled by first-party code (the module), not by the client — unlike
`nombre_original` in `ArchivoEntrada`, which is deliberately never used to build paths (ADR 0020).
Even so, the decision is to defensively sanitize the `arcname` (strip separators and `..`) as
defense in depth, consistent with ADR 0020's general principle of not trusting any name for path
construction. For duplicate `nombre_propuesto` values across the outputs of a single call, the
decided policy is to **raise an error** (not `zipfile`'s silent *last-write-wins*) — losing an
output silently is worse than failing loudly, and it is consistent with the spirit of "nunca a
medias". The exact exception type is defined in `sdd-spec`/`sdd-design`.

### Decision 4 — Zero outputs: this item's scope, shape deferred to design (possible ADR 0023)

BACKLOG assigns zero outputs to `TipoError.CONTENIDO` (422) — that is decided here, it is explicit
in the BACKLOG and it is not ambiguous. What is **not** decided in this proposal is the exact shape
of `ContextoContenido`: whether it reuses `motivo="cero_filas"` (semantics today tied to
Contado_Carga's rows, item #16, not built), whether a new value is added to the closed `Literal`,
or whether a shape parallel to `ErrorTamano.total()` is introduced for the case with no single
culprit file. This weight is comparable to ADR 0021's (`ContextoTamanoTotal`) and is treated the
same way: left named for `sdd-design`, with the explicit suggestion that if the resolution changes
the shape of `Contexto`/`motivo` non-trivially, it be documented as **ADR 0023** (next free number
confirmed against `adrs/`).

### Decision 5 — Content-Disposition / non-ASCII names: outside this item

There is no precedent in the repository (search confirmed). This decision belongs to the HTTP layer
(the `Response` headers), which this item does not build — it is item #10's responsibility. This
item only has to guarantee that it introduces no artificial restriction on which characters
`nombre_propuesto` may contain; the header encoding is decided once a real `Response` exists.

### Decision 6 — Compression and determinism: `ZIP_DEFLATED`, no fixed timestamps

`ZIP_DEFLATED` (standard compression) is used by default; no timestamps or metadata are pinned for
binary determinism of the container. Nothing in PRD/TECH-DESIGN requires it today, and no parity
fixture (ADR 0015) compares whole ZIPs — only decompressed content, and those items (#15/#16) are
not even built. If a future parity fixture needs to compare the whole ZIP, this decision is
explicitly revisited then; it is not over-built now.

## Approach

`app/core/empaquetado.py` follows the already-established `core/` module pattern (`from __future__
import annotations`, a docstring referencing the item/ADR, keyword-only constructors, zero imports
from `procesadores/`, zero Starlette/FastAPI types). It exposes a single public function, analogous
to `ejecutar_modulo()`: it receives `list[ArchivoSalida]` + a directory and returns one
`ArchivoSalida`. Zero outputs raises before touching disk; one output returns the input verbatim;
two or more assemble the ZIP into a complete temp file before returning. Where applicable, it
reuses the bounded-write pattern `_copiar` (`recepcion.py:62-102`) already established as
precedent. It neither orchestrates the pipeline nor builds any `Response`.

## Affected Areas

| Area | Impact | Description |
|---|---|---|
| `app/core/empaquetado.py` | New | Passthrough/ZIP, zero-output error, `arcname` sanitization, duplicates policy |
| `app/core/errores.py` | Modified (possible) | Exact shape of `ContextoContenido`/`motivo` for zero outputs — closed in design |
| `tests/test_empaquetado.py` | New | Passthrough, flat multi-output ZIP, zero outputs, hostile name, duplicates, simulated write failure |

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Decision 4 (the shape of `ContextoContenido`) carries the most weight and stays open; if resolved badly, it reopens `errores.py` twice | Med | Explicitly named for `sdd-design`, with a possible dedicated ADR 0023 |
| No processor is registered (`REGISTRY` empty) to test end-to-end; tests are necessarily against hand-built `list[ArchivoSalida]` | Low | Already the pattern established by `validaciones.py`, no new risk |
| With no aggregate output-size ceiling, a misbehaving module could produce an arbitrarily large ZIP | Low | Declared out of scope; document as a known gap, not blocking for this item |
| Scope confusion with item #10 if `recepcion.py`'s seam is touched by mistake | Low | Explicitly out of scope above; no `recepcion.py` file appears in Affected Areas |

## Rollback Plan

`app/core/empaquetado.py` is a new, self-contained module: deleting it reverts the change
completely. No other module imports it yet (the seam with `recepcion.py`/`ejecucion.py` is item
#10's work), so there are no dependents to untangle. If `errores.py` gains a new shape for zero
outputs, that change is additive (a new `Literal` value or a new `Contexto` shape) and revertible
without affecting the five existing types.

## Dependencies

- `contrato-de-errores-tipificados` (#3, archived), `recepcion-y-ciclo-de-vida-de-temporales`
  (#6, archived) — both shipped, no open work.
- `admision-acotada-y-proceso-dedicado` (#8, archived) — not a formal BACKLOG dependency but the
  natural caller; its contract (`ejecutar_modulo() -> list[ArchivoSalida]`, all-or-nothing) is
  already shipped and needs no changes.
- No new external dependency. `zipfile` is standard library.

## Success Criteria

- [ ] A single-element `list[ArchivoSalida]` returns verbatim (same `Path`/MIME/name), with no ZIP
      produced.
- [ ] Two or more `ArchivoSalida` produce exactly one ZIP with the returned files under their
      names, with no directory components in any `arcname`.
- [ ] Zero `ArchivoSalida` raises `ErrorTipificado` before any ZIP file is created on disk.
- [ ] A hostile `nombre_propuesto` (with separators or `..`) stays confined to a flat, safe
      `arcname`.
- [ ] Duplicate names across the outputs of a single call raise an explicit error, not silent loss.
- [ ] A simulated failure during the ZIP write leaves no partial `.zip` visible or returned by the
      function.
- [ ] `TipoError` stays at 5 values or gains exactly one extension documented and decided in design
      — never an undocumented extension.

## Proposal question round

Auto execution mode — no interactive block was available, so these are decided-and-recorded rather
than asked live. Flagged here for explicit user review before `sdd-design` proceeds:

1. **Zero outputs and `ContextoContenido` (Decision 4).** The exact shape is deferred to design,
   with a suggested ADR 0023 if it changes `Contexto`/`motivo` non-trivially. If the business
   prefers a specific shape now (reusing `"cero_filas"` as-is, for example), saying so reverses
   this decision.
2. **Duplicate `nombre_propuesto` as an error, not *last-write-wins*.** Decided in Decision 3.
   If silent tolerance is preferred (last one wins), saying so reverses this decision.
3. **ZIP to a temp file, not in memory (Decision 1).** Decided by alignment with ADR 0020. If the
   business anticipates very small outputs where memory would be simpler/faster, saying so opens
   that alternative for design.
4. **No aggregate output-size ceiling in this item.** If there is a business expectation to limit
   the total size of an output ZIP now (not just in the future), saying so pulls that work into
   this item instead of leaving it as a known gap.
