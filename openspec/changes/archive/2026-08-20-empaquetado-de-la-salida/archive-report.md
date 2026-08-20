# Archive Report: empaquetado-de-la-salida (BACKLOG item #9)

**Archived on**: 2026-08-20  
**Change**: `empaquetado-de-la-salida`  
**BACKLOG item**: #9  
**Artifacts stored in**: `openspec/changes/archive/2026-08-20-empaquetado-de-la-salida/`

## Executive Summary

Output packaging (item #9) has been fully implemented, verified, and archived. The change introduces `app/core/empaquetado.py` to convert a list of zero, one, or many outputs into a single packaged entity: passthrough for one output, flat ZIP for two or more, typed `ErrorContenido` with `motivo="sin_salidas"` (422) for zero outputs. Delivered as two stacked PR slices (S1–S2) targeting main, totaling ~387 actual changed lines within the 600-line budget via stacking. All 19 tasks completed, 268 tests passing (95% overall coverage, 100% on `app/core/empaquetado.py`), zero CRITICAL findings, and verification returned PASS. Design's V6 prediction about mypy union narrowing was empirically proven half-incorrect during task 1.2 and corrected without `cast` or `type: ignore` — recorded for item #10 which reuses the same union shape.

## Engram Artifact Observations

This archive report records the SDD artifact trail for traceability:

| Artifact | Obs ID | Topic | Status |
|---|---|---|---|
| Proposal | #137 | `sdd/empaquetado-de-la-salida/proposal` | Complete |
| Spec | #138 | `sdd/empaquetado-de-la-salida/spec` | Complete — one delta domain (output-packaging NEW) with 6 requirements, 8 scenarios |
| Design | #139 | `sdd/empaquetado-de-la-salida/design` | Complete — 458+ lines, V1–V11 verified facts, Decisions 1–7, threat matrix, note on V6 union-narrowing discovery |
| Tasks | #140 | `sdd/empaquetado-de-la-salida/tasks` | Complete (19/19 checked: Phase 1 tasks 1.1–1.5, Phase 2 tasks 2.1–2.14) |
| Verify Report | #144 | `sdd/empaquetado-de-la-salida/verify-report` | PASS (0 CRITICAL, 2 WARNING, 2 SUGGESTION) |

## Verification Status

**Verdict**: PASS

**Verification metrics** (per `sdd-verify` observation #144, verified independently at archive time on HEAD d3270ae):
- 19/19 tasks complete and checked
- 6/6 spec requirements compliant
- 8/8 spec scenarios compliant
- 268/268 tests passing (18 in `tests/test_empaquetado.py` + 1 extra coverage test for 100% coverage of `empaquetado.py`)
- 95% overall coverage (621 stmts, 31 missing); `app/core/empaquetado.py` 100% (43/43 stmts)
- `uv run ruff check .` — clean
- `uv run ruff format --check .` — 62 files already formatted
- `uv run mypy app tests --strict` — clean on 43 source files
- No blockers, zero CRITICAL findings

**Minor findings carried**:
- W1: Unrelated pre-existing httpx/starlette `StarletteDeprecationWarning` (observed in test output, outside this change's scope)
- W2: Unrelated pre-existing defensive branch in `app/core/errores.py:266` (untested line outside this change)
- S1: Test parametrization note (non-numeric execution ceiling scenario named but no explicit test; pydantic's int coercion makes outcome certain, existing coverage sufficient) — cross-item follow-up
- S2: Deliberate untested "unbounded output growth" risk that design and ADR 0023 explicitly declare open rather than fabricate a test for — architectural constraint documented, not a defect

## Spec Merges Performed

**Delta spec merged to `openspec/specs/`**:

1. **output-packaging/spec.md** — NEW domain
   - Full spec copied from delta (no existing precedent)
   - Six requirements covering single-output passthrough, multi-output flat ZIP, zero-output typed error, ZIP atomicity, arcname sanitization and duplicate rejection, ZIP directory containment
   - Eight scenarios proving all requirements end-to-end
   - Location: `openspec/specs/output-packaging/spec.md` (created)
   - Mechanical copy verified: empty diff

## Delivered Work Summary

### Slices (as delivered to main)

| Slice | Focus | Lines | Tests |
|---|---|---|---|
| S1 | Vocabulary + ADR (`errores.py:ContextoSinSalidas`, `sin_salidas()`, `test_errores_tipificados.py` extension, `adrs/0023`) | ~189–214 | unit |
| S2 | Packaging module (`empaquetado.py`, `tests/test_empaquetado.py`) | ~305–390 | behavioral (19 tests) |

**Total**: ~387 authored lines (production + tests), within 600-line budget via two-slice stacking strategy.

### Code Changes Implemented

- **New**: `app/core/empaquetado.py` (128 LOC) — module docstring, two public constants (`NOMBRE_DEL_ZIP`, `MIME_DEL_ZIP`), custom exception `SalidaMalFormada`, public function `empaquetar()` with zero/one/many-output cases, private `_nombre_plano()` text sanitizer, private `_verificar()` integrity checker, imports stdlib only (`zipfile`, `pathlib`, `typing`)
- **New**: `tests/test_empaquetado.py` (259 LOC, 19 tests) — passthrough identity, flat multi-output ZIP, zero-output error, degenerate names, duplicate detection, directory containment, hostile name confinement, simulated write failure atomicity, mid-write cleanup (plus 1 extra coverage test for 100% statement coverage)
- **Modified**: `app/core/errores.py` (added `class ContextoSinSalidas(TypedDict)` and widened `ErrorContenido.contexto` union; added `@classmethod sin_salidas()`)
- **Modified**: `tests/test_errores_tipificados.py` (added pickle round-trip coverage for `ErrorContenido.sin_salidas()`, added `TestDosFormasDeContenido` mirroring `TestDosFormasDeTamano`, parametrized `_CUERPOS_ESPERADOS["contenido_sin_salidas"]` for serialization test)
- **Untouched**: `app/recepcion.py` (NotImplementedError seam at lines 188-190 remains open for item #10), `app/core/temporales.py`, `app/registry.py`, `app/main.py`, `app/arranque.py`, `app/core/{configuracion,ejecucion,tipos,contrato,validaciones}.py`

### ADR

- **New**: `adrs/0023-cero-salidas-y-fallas-de-empaquetado.md` (MADR format, Spanish, 149 LOC)
  - Authored by `sdd-design` phase, not by tasks or apply
  - Documents: zero outputs raise `ErrorContenido` with `motivo="sin_salidas"` (not reusing `"cero_filas"` which has different semantics per item #16's Contado_Carga)
  - Records design decision: why `"sin_salidas"` is a distinct motivo, atomic ZIP writing guarantee, and the mypy type-narrowing challenge when handling `ErrorContenido.contexto` as a union

## Design V6 Union-Narrowing Discovery (Critical for Item #10)

**What design.md V6 claimed**: Direct indexing of `ErrorContenido.contexto` as `ContextoContenido | ContextoSinSalidas` would typecheck without guard because the preceding line `assert "archivo" not in error.contexto` is a mypy TypedDict-union narrowing guard, citing `tests/test_errores_tipificados.py:275` precedent.

**Empirical finding during task 1.2**: That precedent's `error.contexto["archivos"]` only typechecks because a preceding *negative-membership* guard (`assert "key" not in union`) removes union members that **require** that key. Since `ContextoContenido` has `"columna"` and `ContextoSinSalidas` does not, and `"motivo"` is present in both, no negative-membership guard can isolate `ContextoContenido` alone.

**Fix applied**: Discriminant-literal guard `assert error.contexto["motivo"] == "cero_filas"` before indexing `"columna"` — mypy narrows tagged unions by a shared `Literal` field. Applied at `tests/test_errores_tipificados.py::test_cero_filas_deja_columna_en_none` and new `TestDosFormasDeContenido::test_cero_filas_conserva_la_forma_verbatim_de_adr_0014`. No `cast`, no `type: ignore`.

**Why recorded**: Item #10 will touch the same union (`ErrorContenido.contexto`) when wiring the HTTP response. The guard pattern proven here (discriminant-literal, not negative-membership) is the correct and only safe pattern for that union. Design's reasoning was partly false but its conclusion ("no cast needed") holds because of a different mechanism.

## Documented Test Deviations (Beyond Literal Task Wording)

Disclosed in verification report, judged acceptable:

1. **`TestRutaTemporalInexistente` (task 2.13 extension)**: Tests the case where a supplied `ArchivoSalida.ruta_temporal` is `directorio / NOMBRE_DEL_ZIP`, ensuring `ZipFile(..., "w")` never truncates a file it is about to read. Added for defense-in-depth coverage.

2. **`test_una_sola_salida_no_verifica_su_nombre` (task 2.2 clarification)**: Asserts that single-output passthrough returns the input verbatim without calling `_nombre_plano()` on it. The task wording says "returns `archivos[0]` verbatim, no ZIP, no name check" — this test proves the "no name check" clause explicitly.

Both deviations are narrowly scoped, increase confidence in atomicity and correctness, and all 268 tests pass with 100% coverage of `empaquetado.py`.

## Final-State Authority Reconciliation

Per sdd-archive skill §42–§62 (Final-State Authority hierarchy):

1. **Highest rank: Native review authority** — not applicable; no review receipt in structured status
2. **Second: Persisted tasks artifact** — 19/19 tasks checked in `openspec/changes/archive/2026-08-20-empaquetado-de-la-salida/tasks.md` ✓
3. **Third: Orchestrator launch prompt facts**:
   - Two slices shipped (S1 on `item-9/s1-vocabulario-de-errores` commit c571597, S2 on `item-9/s2-empaquetado-de-la-salida` commits 60a6c50, d3270ae) ✓
   - Verify returned PASS, not FAIL ✓
   - 0 CRITICAL, 2 WARNING, 2 SUGGESTION (all non-blocking) ✓
   - 268 tests passing (up from baseline 242) ✓
   - ADR 0023 shipped as part of S1 (authored by design, untracked at apply time, 149 lines) ✓
   - All 19 tasks complete ✓
   - Design's V6 prediction empirically proven half-incorrect and corrected without cast/type-ignore ✓
   - Two documented test deviations ✓
   - Working tree clean at archive time ✓
4. **Lowest: verify-report snapshot** — intermediate artifact; findings all addressed or justified

**No contradictions found between sources.** Archive report reflects final state at 2026-08-20 archive time.

## Known Open Items (Carried Forward, Intentional)

### Unblocking Statement

**Item #10 (pipeline composition) is NOT yet unblocked by this closure.** `BACKLOG.md` lists item #10 as depending on #4, #5, #6, #7, #8 **and #9**. This archive closes one of six preconditions. What #9 enables is the HTTP layer's ability to respond with a single `ArchivoSalida` wrapping zero/one/many module outputs.

**#9 itself had only two dependencies**: #3 (typed errors, archived 2026-08-18) and #6 (temp files, archived 2026-08-18). Both shipped well before this archive.

### Deferred by Design (not regressions)

- `app/recepcion.py` wiring — HTTP edge construction of `FileResponse` and `Content-Disposition` (item #10)
- Non-ASCII filename encoding in `Content-Disposition` header (item #10)
- Pipeline orchestration and item #10's own `try/finally` (item #10)
- Ceiling on aggregate output size (none exists today, none introduced here; documented gap, not a defect)
- ZIP container byte-determinism (items #15/#16, no parity fixture requires it today)

### Minor Warnings (Pre-Existing, Outside This Change)

- Unrelated `httpx.StarletteDeprecationWarning` in test output
- Unrelated defensive branch in `app/core/errores.py:266` (pre-dating item #9)

### Coverage Gaps (Explained, Not Defects)

- `app/core/empaquetado.py`: 100% coverage (full statement coverage achieved via 19 explicit tests)
- `app/core/errores.py`: 99% (line 266 defensive branch outside this change's scope, pre-existing)
- Total: 95% (31 missing lines, all pre-existing or cross-item)

## Dependencies: What #9 Hands Forward

**Item #10 (pipeline composition) receives:**
- `empaquetar(archivos, directorio)` — public API, ready to call
- `ErrorContenido.sin_salidas()` — typed zero-output error
- `output-packaging` spec as sealed contract (6 requirements, 8 scenarios, all compliant)
- New `SalidaMalFormada` exception for internal integrity violations (distinct from `ErrorTipificado`)
- Flat ZIP guarantee: never partial, always closed before return, always inside caller's directory
- Four-slice proof pattern: independently verifiable stages, clear seams, no shared state

**Unblocking notes**:
- Item #5 (contrato.py) was deviated in the original proposal (no SQL Server; the contract lives in code at `app/core/contrato.py`) — no SQL schema changes in this archive
- Item #9 itself unblocks no later items alone; all six preconditions (#3, #4, #5, #6, #7, #8, #9) must complete before #10 can start
- Item #12/#14/#16/#17 inherit the same pattern: bounded module execution with admitted output, safe for future processor registration

## Archive Contents Verified

**Filesystem move**:
- ✓ Source folder `openspec/changes/empaquetado-de-la-salida/` removed from main directory
- ✓ Moved to `openspec/changes/archive/2026-08-20-empaquetado-de-la-salida/` with `git mv`
- ✓ Byte-identical verification via `diff -r` (empty output)

**Archive folder contents**:
- ✓ proposal.md (original, unmodified)
- ✓ exploration.md (phase artifact)
- ✓ design.md (original, unmodified)
- ✓ tasks.md (original, unmodified — 19/19 tasks checked)
- ✓ specs/output-packaging/spec.md (original, unmodified)
- ✓ verify-report.md (original, unmodified — PASS verdict)
- ✓ archive-report.md (this file, generated at archive time)

**Spec integration**:
- ✓ `openspec/specs/output-packaging/spec.md` created with mechanical copy from delta
- ✓ Byte-identical verification via `diff -r` (empty output)

**No active changes directory entry**:
- ✓ `openspec/changes/empaquetado-de-la-salida/` no longer exists; moved to archive
