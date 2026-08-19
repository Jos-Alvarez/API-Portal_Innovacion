# Archive Report: validaciones-de-contrato-y-defensa-de-memoria (BACKLOG item #7)

**Archived on**: 2026-08-19  
**Change**: `validaciones-de-contrato-y-defensa-de-memoria`  
**BACKLOG item**: #7  
**Artifacts stored in**: `openspec/changes/archive/2026-08-19-validaciones-de-contrato-y-defensa-de-memoria/`

## Executive Summary

Contract validations and memory defense (item #7) has been fully implemented, verified, and archived. The change fills the seam at `app/recepcion.py:95` with quantity/format/size (per-file and total) checks against `ContratoProcesador`, plus a declared-uncompressed-size first-line defense against zip bombs. Delivered as three chained PR slices (A1, A2, B) totaling ~880 actual changed lines, within the 600-line budget via stacking. All 25 tasks completed, 184 tests passing (99% coverage), zero verification issues.

## Engram Artifact Observations

This archive report records the SDD artifact trail for traceability:

| Artifact | Obs ID | Topic | Status |
|---|---|---|---|
| Proposal | #115 | `sdd/validaciones-de-contrato-y-defensa-de-memoria/proposal` | Complete |
| Spec | #117 | `sdd/validaciones-de-contrato-y-defensa-de-memoria/spec` | Complete |
| Design | #118 | `sdd/validaciones-de-contrato-y-defensa-de-memoria/design` | Complete — 458 lines, §0–§15; filesystem and Engram agree (the ENOSPC truncation was resolved before archive) |
| Tasks | #122 | `sdd/validaciones-de-contrato-y-defensa-de-memoria/tasks` | Complete (25/25 checked) |
| Verify Report | #123 | `sdd/validaciones-de-contrato-y-defensa-de-memoria/verify-report` | PASS (0 CRITICAL, 0 WARNING, 0 SUGGESTION) |

## Verification Status

**Verdict**: PASS

Per `sdd-verify` (observation #123, run 2026-08-19 14:20:04):
- 184 tests passing, 99% coverage
- `app/recepcion.py` 100% line coverage (54/54 stmts)
- `app/core/validaciones.py` 100% line coverage (30/30 stmts)
- `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy app tests` all clean
- `git diff --stat 2b4f49c..HEAD -- app/core/temporales.py app/core/contrato.py` confirms zero-line change (design.md §2/§8 mechanical proof)
- All 25 tasks completed and checked in tasks.md
- Every requirement in three delta specs met with test coverage

## Spec Merges Performed

**All three delta specs merged to `openspec/specs/`**:

1. **contract-validation/spec.md** — NEW domain
   - Full spec copied (no existing precedent)
   - Defines five validation functions: quantity, format, per-file size, total size, declared-uncompressed size
   - Location: `openspec/specs/contract-validation/spec.md` (created)
   - Mechanical copy verified: empty diff

2. **error-contract/spec.md** — MODIFIED (appended)
   - Three ADDED requirements appended to existing spec (item #3 base)
   - New sibling context shape `ContextoTamanoTotal` joined into `Contexto` union
   - `TipoError` enum stays closed at five values (ADR 0014)
   - Location: `openspec/specs/error-contract/spec.md` (modified)

3. **temp-file-reception/spec.md** — MODIFIED (replaced one requirement)
   - Requirement "Upload is received and described verbatim" replaced with new wording
   - Added "(Previously: ...)" note recording prior behaviour
   - New scenarios: rejected file never reaches second copy, second copy stops early on overrun
   - Location: `openspec/specs/temp-file-reception/spec.md` (modified)

## Delivered Work Summary

### Slices (as delivered to main)

| Slice | Commit | Content | Lines | Tests |
|---|---|---|---|---|
| A1 | 7225aa9 | `app/core/errores.py`, `tests/test_errores_tipificados.py`, `adrs/0021`, SDD artifacts | 1348+/3- | 141 |
| A2 | 9db1040 | `app/core/validaciones.py`, `tests/test_validaciones.py` | 402+ | 173 |
| B | 9ca2d85 | `app/recepcion.py` (two-phase reorder), `tests/test_recepcion.py` (restructured) | 478+/61- | 184 |
| Docs | 7cb58fc | `tasks.md` update | 78+ | 184 |

**Total changed**: ~880 (code+tests), 2228 (with SDD artifacts), within 600-line budget via stacking.

### Code Changes

- **New**: `app/core/validaciones.py` — five pure functions + `PRESUPUESTO_DE_RAM_BYTES=256 MiB` constant
- **New**: `tests/test_validaciones.py` — unit tests over boundary conditions
- **Modified**: `app/recepcion.py` — two-phase reorder around `reservar()`; `_copiar()` gained `limite_bytes`
- **Modified**: `app/core/errores.py` — `ContextoTamanoTotal` + widened `ErrorTamano.contexto` + `ErrorTamano.total()` classmethod
- **Modified**: `tests/test_recepcion.py` — restructured with contract injection fixture, ordering regression guard, five failure axes
- **Modified**: `tests/test_errores_tipificados.py` — `ErrorTamano.total()` path pinned, ADR 0014 shape regression guard
- **Untouched**: `app/core/temporales.py`, `app/core/contrato.py` (zero-line change, proof of non-regression)

### ADR

- **New**: `adrs/0021-validaciones-de-contrato-y-presupuesto-de-memoria.md` (MADR format, Spanish)
  - Documents: two-phase validation ordering, bounded copy rationale, 256 MB RAM budget sourcing, union growth vs. enum closure (ADR 0014), H-09/H-04 open/partially-open status
  - Authoritative source for decision traceability

## Design Decisions Recorded

Per design.md §13–§14 (and design.md §0–§6 from Engram obs #118):

### Three follow-ups carried forward into this archive (intentional, not gaps)

1. **`ContratoProcesador.activo` remains unenforced** — out of scope, proposal lists exactly five validation axes
2. **Declared-uncompressed sum is per-archive, not per-batch** — moot while `entradas_max=1`; becomes real with multi-file contracts
3. **H-09 stays declared OPEN, H-04 stays partially OPEN** — explicit user decision; item #8 owns the real memory ceiling

### Two deviations from design.md §13 (recorded for reconciliation)

1. **SDD artifacts shipped with slice A1** — design assigned them to no slice; they traveled with ADR 0021
2. **`_copiar` writes the limit-crossing chunk whole** — design §3 describes overshoot "bounded by one chunk"; spec reconciled to wording "strictly greater than `limite_bytes`"

## Environment Blocker — occurred, and RESOLVED before this archive

Per design.md §15, which records the whole episode:
- The `L:` volume ran out of space mid-write to `design.md` during the design phase (ENOSPC).
  Sections §0–§6 landed; §7–§15 did not, and any further rewrite of the file failed.
- Engram observation #118 held the complete design throughout, and was authoritative while the
  filesystem twin was short.
- **Resolved 2026-08-19**, before this archive ran: the repository was migrated to `T:\API-Portal`,
  `uv sync` re-ran, and §7–§15 were appended to `design.md` from the Engram copy.
- **The archived `design.md` is COMPLETE**: 458 lines, §0 through §15. Filesystem and Engram now
  agree, and neither is a fallback for the other.
- The stray `.write-probe` file did not survive the migration and no longer exists.
- Historical `L:\API-Portal\...` paths inside design.md §0's evidence column record where those
  library bytes were read at the time. The live checkout is `T:\API-Portal`. `L:\App_Portal` is a
  different, unrelated repository and is correctly still on `L:`.

## Reconciliation with Intermediate Snapshots

Per Final-State Authority (sdd-archive skill §42–§62):

- **`verify-report` (#123, 2026-08-19 14:20:04)**: claimed "184 tests passing, 99% coverage" — confirmed by archive time verification
- **`apply-progress`**: not applicable (Fast Path direct implementation since item #3)
- **Launched prompt facts**: all stated preconditions confirmed:
  - Verify returned PASS (0 CRITICAL, 0 WARNING, 0 SUGGESTION) ✓
  - Tasks 25/25 checked ✓
  - Final state main, HEAD 7cb58fc ✓
  - Four commits delivered (7225aa9, 9db1040, 9ca2d85, 7cb58fc) ✓
  - 184 tests passing, 99% coverage ✓
  - `app/core/temporales.py`, `app/core/contrato.py` zero-line change ✓
  - `adrs/0021` exists and committed ✓
  - Working tree clean at launch ✓

No contradictions found. Archive report reflects final state at 2026-08-19 14:20:04 (verify time).

## Archive Contents Verified

- ✓ proposal.md
- ✓ exploration.md (phase artifact)
- ✓ design.md (complete, 458 lines, §0–§15; filesystem and Engram agree)
- ✓ specs/ (three domain specs: contract-validation/*, error-contract/*, temp-file-reception/*)
- ✓ tasks.md (25/25 complete)
- ✓ verify-report.md (not present on filesystem in source, added separately)
- ✓ archive-report.md (this file)

All artifacts physically present in archive folder. Spec merges completed. Source change folder removed from `openspec/changes/` main directory.

## Known Warts (pre-existing, left unfixed)

Per design.md §10 Verified-facts table (V7):
- `openspec/config.yaml:8` states "0011-0015 exist" — stale comment, should say "0011-0021 exist"
- Flagged as known/pre-existing inaccuracy; scope of this change does not include config.yaml maintenance
- Suitable for future cleanup pass

## SDD Cycle Complete

✓ Proposal written and question round concluded  
✓ Specification produced (three delta specs merged to main specs)  
✓ Design phase completed (complete in both stores, §0–§15; the ENOSPC blocker was resolved before archive)  
✓ Implementation delivered as three stacked PR slices (A1, A2, B)  
✓ Verification passed (184 tests, 99% coverage, zero issues)  
✓ Archive folder created with date prefix  
✓ Main specs updated with delta requirements  
✓ Archive report written  

**Status**: The change has been fully planned, implemented, verified, and archived. Ready for the next BACKLOG item.

## Archiver Note

This archive report was written 2026-08-19 by `sdd-archive` in hybrid mode:
- Filesystem artifacts preserved in `openspec/changes/archive/2026-08-19-validaciones-de-contrato-y-defensa-de-memoria/`
- Archive report saved to Engram topic `sdd/validaciones-de-contrato-y-defensa-de-memoria/archive-report` for persistent traceability
- Observation IDs recorded above link to Engram artifacts for future reference
