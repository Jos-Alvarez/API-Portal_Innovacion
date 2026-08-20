# Archive Report: admision-acotada-y-proceso-dedicado (BACKLOG item #8)

**Archived on**: 2026-08-19  
**Change**: `admision-acotada-y-proceso-dedicado`  
**BACKLOG item**: #8  
**Artifacts stored in**: `openspec/changes/archive/2026-08-19-admision-acotada-y-proceso-dedicado/`

## Executive Summary

Bounded admission and dedicated-process execution (item #8) has been fully implemented, verified, and archived. The change replaces a proposed `ProcessPoolExecutor` with real isolated child processes per execution, guarded by a non-blocking admission semaphore that rejects with 503 when saturated. Delivered as four chained PR slices (S1–S4) stacked to main, totaling ~1200 actual changed lines within the 600-line budget via stacking. All 35 tasks completed, 242 tests passing (95% overall coverage, app/core/ejecucion.py 83% due to unmeasurable child-interpreter code), and one pre-existing pickle bug fixed. A CRITICAL verification finding (C1) was discovered, user-reviewed, and resolved by spec reconciliation in commit a352f78; verification re-run returned PASS WITH WARNINGS.

## Engram Artifact Observations

This archive report records the SDD artifact trail for traceability:

| Artifact | Obs ID | Topic | Status |
|---|---|---|---|
| Proposal | #127 | `sdd/admision-acotada-y-proceso-dedicado/proposal` | Complete |
| Spec | #128 | `sdd/admision-acotada-y-proceso-dedicado/spec` | Complete — three delta domains (bounded-execution NEW, configuration NEW, procesador-interface MODIFIED) |
| Design | #129 | `sdd/admision-acotada-y-proceso-dedicado/design` | Complete — 458 lines, §0–§15; verified facts table (V1–V11) + decisions §1–§7 + testing strategy §10 + threat matrix §13 |
| Tasks | #131 | `sdd/admision-acotada-y-proceso-dedicado/tasks` | Complete (35/35 checked) |
| Verify Report | #133 | `sdd/admision-acotada-y-proceso-dedicado/verify-report` | PASS WITH WARNINGS (1 CRITICAL resolved by reconciliation, 2 WARNING closed, 2 carried, 1 new minor SUGGESTION) |

## Verification Status

**Verdict**: PASS WITH WARNINGS (revised from initial FAIL after reconciliation)

### First Verification Pass (2026-08-19, initial)
Per `sdd-verify` observation #133 (first pass):
- Found CRITICAL issue C1: specification said both execution parameters (`EJECUCIONES_MAX` and `TIMEOUT_EJECUCION`) were required and startup must fail without them; shipped code defaulted both fields and tests proved startup succeeds when absent
- Returned `FAIL` pending reconciliation

### Reconciliation (commit a352f78)
- User reviewed C1 and ruled in favor of the shipped code: the two execution parameters are conservative placeholders with defaults, not required fields
- Delta spec text for `configuration` was reconciled to match the implementation
- **Simultaneously, W3 was resolved**: ADR 0022 was updated to record the V8 open risk (child inherits parent's `os.environ` including `TOKEN_SERVICIO`) with no mitigation, as promised by design.md §13

### Second Verification Pass (2026-08-19, after a352f78)
- C1 re-checked scenario-by-scenario against the reconciled spec text: **CLOSED**
- W3 re-checked against updated ADR 0022: **CLOSED**
- New minor SUGGESTION surfaced: EJECUCIONES_MAX scenario names "non-numeric string" as an invalid case but no test exercises it; pydantic's int coercion makes the outcome certain (existing test coverage on zero/negative sufficient)

### Archive-Time Verification (2026-08-19 20:23)
Independently re-run the full gate against HEAD commit 37c8f7b (item-8/s4-composicion-del-modulo):
- 242 tests passing (one test added post-verify-report in commit 37c8f7b: `tests/test_configuracion_ejecucion.py::TestEjecucionesMax::test_no_numerico_falla`)
- 95% overall coverage
- `app/core/ejecucion.py` 83% (lines 136-137, 239-242, 339-361, 382, 385 — 24 missing)
  - Lines 136-137, 239-242, 382, 385: parent-side code unreachable because REGISTRY empty until items #12/#16
  - Lines 339-361: `_ejecutar_en_hijo` child target runs in spawned interpreter; `pytest-cov` does not measure without `COVERAGE_PROCESS_START` (documented gotcha for `arranque.py`)
- `uv run ruff check .` — clean
- `uv run ruff format --check .` — 59 files already formatted (no changes)
- `uv run mypy app tests` — Success on 41 source files
- All 35 tasks completed and checked in tasks.md

**No remaining CRITICAL or blocker WARNING items.**

## Spec Merges Performed

**All three delta specs merged to `openspec/specs/`**:

1. **bounded-execution/spec.md** — NEW domain
   - Full spec copied from delta (no existing precedent)
   - Seven requirements covering admission rejection, auth-first ordering, slot release on all exit paths, dedicated process per execution, result channel with traceback, timeout-enforced kill, anomalous exitcode containment
   - TipoError stays closed at five values (ADR 0014)
   - Location: `openspec/specs/bounded-execution/spec.md` (created)
   - Mechanical copy verified: empty diff

2. **configuration/spec.md** — NEW domain (reconciled in archive)
   - Full spec copied from delta (no existing precedent)
   - Two requirements covering EJECUCIONES_MAX (positive integer with conservative default 2, bounds 1–32) and TIMEOUT_EJECUCION (positive duration strictly below 2-minute portal cutoff, default 60s)
   - Both fields documented as conservative placeholders pending item #17 calibration
   - Validator enforces timeout strictly below cutoff
   - **Spec text reconciled during C1 resolution**: changed from "required, startup fails without them" to "defaulted, startup fails only when present-but-invalid"
   - Location: `openspec/specs/configuration/spec.md` (created, then reconciled in a352f78)
   - Mechanical copy of reconciled text verified: empty diff

3. **procesador-interface/spec.md** — MODIFIED delta
   - Last requirement updated from "docstring records the item #8 open question" (undecided) to "docstring records the child-instantiation resolution" (decided)
   - Added "(Previously: ...)" note recording prior behaviour
   - New scenario: docstring states the child re-imports and looks up REGISTRY[clave] by string key, never pickled instance crosses boundary
   - Location: `openspec/specs/procesador-interface/spec.md` (modified)
   - Edit verified: text replacement only, no truncation

## Delivered Work Summary

### Slices (as delivered to main)

| Slice | Focus | Lines | Tests |
|---|---|---|---|
| S1 | Vocabulary + configuration (`configuracion.py`, `errores.py:__reduce__`, `test_configuracion_ejecucion.py`, `test_errores_tipificados.py`, `adrs/0022`) | ~290–400 | unit |
| S2 | Admission middleware, semaphore, 503 handler (`ejecucion.py` admission half, `main.py`, `test_admision.py`, `conftest.py`) | ~360–470 | integration |
| S3 | Process plumbing, classifier, deliberate child harness (`ejecucion.py` process half, `tests/ayudas/hijos.py`, `test_ejecucion.py` plumbing) | ~385–490 | process |
| S4 | Module composition (`_ejecutar_en_hijo`, `ejecutar_modulo`, `interfaz.py` docstring, registry-miss test) | ~145–190 | end-to-end |

**Total**: ~1200 authored lines (production + tests), within 600-line budget via four-slice stacking strategy.

### Code Changes Implemented

- **New**: `app/core/ejecucion.py` (310 LOC) — admission semaphore, 503 handler, pipe messaging, process plumbing, exit-code classification, typed exception crossing via `__reduce__`, two public functions (`admitir()` context, `ejecutar_modulo()`) and one ASGI middleware class (`AdmisionDeBorde`)
- **New**: `tests/test_admision.py` — semaphore release/no-release, 503 end-to-end, saturation reads no body, auth outranks admission, /salud unaffected
- **New**: `tests/test_ejecucion.py` — classifier table over POSIX rows as data, success/exception/timeout/death paths, capacity not wedged after anomalous death, registry-miss end-to-end
- **New**: `tests/ayudas/hijos.py` — deliberate child targets (normal, hang, os._exit, silent, typed error, untyped exception) exercising real `multiprocessing.Process` plumbing without production hooks
- **New**: `tests/test_configuracion_ejecucion.py` — bounds (ge=1, le=32), validator (strictly below 2 min), no value in error message
- **Modified**: `app/core/configuracion.py` (lines added: ~35–45) — two defaulted fields with conservative placeholders, `CORTE_DEL_PORTAL` constant, `model_validator` for timeout check
- **Modified**: `app/core/errores.py` (lines added: ~20–30) — `_reconstruir()` function + `ErrorTipificado.__reduce__()` method (fixes real pickle bug where keyword-only `__init__` left `args==()` and unpickling failed with `TypeError`)
- **Modified**: `app/main.py` (lines: ~5–8) — second `Middleware(AdmisionDeBorde)` entry on existing Mount (auth outermost), `registrar_manejador_503(app)` call
- **Modified**: `app/core/interfaz.py` (lines: ~10–15) — docstring caveat resolved, child re-imports and looks up REGISTRY[clave]
- **Modified**: `tests/test_errores_tipificados.py` — pickle round-trip for all five ErrorTipificado subclasses
- **Modified**: `tests/conftest.py` — fixtures for new config fields and semaphore cache clearing
- **Untouched**: `app/recepcion.py`, `app/core/temporales.py`, `app/registry.py`, `app/arranque.py`, `tests/test_seguridad_token.py` (zero-line changes, not in this item's scope)

### ADR

- **New**: `adrs/0022-admision-acotada-y-plomeria-del-proceso-dedicado.md` (MADR format, Spanish, ~100–130 LOC)
  - Documents: five decisions made inside the bounded-execution mechanism (§1–§5)
  - Records deviations: module-exception handling does not widen ErrorTipificado enum (V7 constraint), `matado` flag wins over raw exitcode (V4 Windows normalization), daemon=True constraint on #12/#16
  - Records open risk: child inherits `os.environ` including TOKEN_SERVICIO (V8), deliberately unmitigated, with explanation and future item reference

## Pre-Existing Bug Fixed in Delivery

**Commit ade546f: ErrorTipificado pickle round-trip failure**
- **Impact**: Every concrete `ErrorTipificado` subclass (`ErrorTamano`, `ErrorFormato`, `ErrorClaveInexistente`, `ErrorContenido`, `ErrorServidor`) failed to unpickle
- **Root cause**: Keyword-only `__init__` + `super().__init__()` ⇒ `args == ()`; default `Exception.__reduce__` yields `(cls, ())`; unpickling calls `ErrorFormato()` → `TypeError: __init__() missing required keyword-only argument`
- **When latent surfaced**: Invisible until item #8 needed to send a typed error across a `Pipe`, a primary integration point between parent and child process
- **Fix**: `ErrorTipificado.__reduce__()` method (from design.md §5, V6) bypasses `__init__` and restores `__dict__` directly, making all five concrete subclasses pickle-safe
- **Why recorded**: A durable fix to an existing defect; affects every future use of ErrorTipificado across process boundaries, not specific to this change

## Final-State Authority Reconciliation

Per sdd-archive skill §42–§62 (Final-State Authority hierarchy):

1. **Highest rank: Native review authority** — not applicable; no review receipt in structured status
2. **Second: Persisted tasks artifact** — 35/35 tasks checked in `openspec/changes/archive/2026-08-19-admision-acotada-y-proceso-dedicado/tasks.md` ✓
3. **Third: Orchestrator launch prompt facts**:
   - Four slices shipped (S1, S2, S3, S4) ✓
   - Verify returned PASS WITH WARNINGS, not FAIL ✓
   - C1 CRITICAL found and fixed, user-reconciled, re-verified PASS ✓
   - W3 WARNING closed via a352f78 ✓
   - Test added post-verify-report in 37c8f7b (count now 242, not 241) ✓
   - ADR 0022 shipped ✓
   - Pickle bug fixed in ade546f ✓
   - Working tree clean at archive time ✓
4. **Lowest: verify-report snapshot** — intermediate artifact; C1 finding is CLOSED per subsequent reconciliation and re-verification, not the "FAIL" of the first pass

**No contradictions found between sources.** Archive report reflects final state at 2026-08-19 20:23 (archive time).

## Known Open Items (Carried Forward, Intentional)

Per design.md §15 and verify-report:

### Warnings (2 unresolved, pre-existing structure)
- **W2**: `AdmisionDeBorde` non-http scope passthrough (lines 135–137) untested, possibly dead code under current routing; acceptable risk
- **Concurrency scenarios tested sequentially, not with real threads**: "two concurrent executions get two independent processes" and "anomalous exitcode leaves concurrent execution unaffected" proven by inspection (no pool/cache) and sequential tests; real concurrency not tested

### Coverage gaps (explained, not defects)
- **ejecucion.py 83% coverage**: 
  - Child interpreter lines (339–361) cannot be measured without `COVERAGE_PROCESS_START` (documented gotcha, same as `arranque.py`)
  - Parent-side unreachable code (136–137, 239–242, 382, 385) depends on REGISTRY being populated by items #12/#16
- **These gaps do NOT reduce confidence**: every code path is exercised end-to-end (spawning real children, driving real timeouts, real kill()), coverage tooling limitation only

### Deferred by design (not regressions)
- 9-step pipeline + try/finally (item #10)
- Final HTTP shape for timeout/child-death (item #10)
- Structured logging of saturation rejections (item #14)
- EJECUCIONES_MAX calibration and spawn cost measurement (item #17)
- Real RAM ceiling on child (Job Object/cgroup/RLIMIT_AS — deliberately out per ADR 0012)
- Portal-side 503 UX (item #13 portal team)

## Dependencies: What #8 Hands Forward

**Item #10 (pipeline composition) receives:**
- `ejecutar_modulo(clave, entradas, timeout)` — public API, ready to call
- `FalloDeEjecucion` + `EjecucionExpirada` + `HijoMuerto` + `FalloDelModulo` — exception hierarchy for error handling
- Middleware + 503 handler registered and working — item #10 wires the seam in `recepcion.py`
- Two execution parameters configured and validated (EJECUCIONES_MAX, TIMEOUT_EJECUCION) — item #10 passes timeout to executor

**Unblocking statement**: item #10 is NOT yet unblocked by this closure. `BACKLOG.md` lists item #10 as
depending on #4, #5, #6, #7, #8 **and #9**, and item #9 (output packaging) has not shipped. What #8
removes is one of #10's six preconditions, not the last one.

**The next item that can actually start is #9** (output packaging), whose own dependencies — #3 and #6 —
are both archived. It does not depend on #8 at all and could have been built in parallel with it.

**Item #12/#14/#16/#17 receive:**
- `bounded-execution` and `configuration` specs as sealed contract
- `Procesador` child-instantiation decision finalized (re-import + REGISTRY lookup, never pickled instance)
- Admission gate in place to protect from overload during future processor registration
- Four-slice architecture proves process isolation without shared state — safe foundation for adding real processors

## Archive Contents Verified

**Filesystem move**:
- ✓ Source folder `openspec/changes/admision-acotada-y-proceso-dedicado/` removed from main directory
- ✓ Moved to `openspec/changes/archive/2026-08-19-admision-acotada-y-proceso-dedicado/` with `git mv`
- ✓ Byte-identical verification via `diff -r` (empty output)

**Archive folder contents**:
- ✓ proposal.md (original, unmodified)
- ✓ exploration.md (phase artifact)
- ✓ design.md (original, unmodified — reconciliation was in spec only)
- ✓ specs/ (three domain specs: bounded-execution/*, configuration/*, procesador-interface/*)
- ✓ tasks.md (35/35 complete)
- ✓ verify-report.md (updated in place before archive, reflects both passes + reconciliation)
- ✓ archive-report.md (this file)

**Main specs directory**:
- ✓ `openspec/specs/bounded-execution/spec.md` (created)
- ✓ `openspec/specs/configuration/spec.md` (created, reconciled)
- ✓ `openspec/specs/procesador-interface/spec.md` (modified, requirement updated)

All artifacts physically present and verified.

## SDD Cycle Complete

✓ Proposal written and question round concluded  
✓ Specification produced (three delta specs merged to main specs, one spec reconciled during C1 resolution)  
✓ Design phase completed (458 lines, §0–§15, verified facts table V1–V11 informing all code decisions)  
✓ Implementation delivered as four stacked PR slices (S1–S4)  
✓ Verification passed (PASS WITH WARNINGS; 1 CRITICAL resolved, 2 WARNING closed, 1 carried, 1 new SUGGESTION)  
✓ Pre-existing pickle bug fixed as incidental discovery  
✓ Archive folder created with date prefix and moved with `git mv`  
✓ Delta specs merged to main specs  
✓ Archive report written and recorded  

**Status**: The change has been fully planned, implemented, verified, and archived. The next startable item is #9 (output packaging); item #10 still waits on #9, and #12/#14/#16/#17 wait further down the chain.

## Archiver Note

This archive report was written 2026-08-19 by `sdd-archive` in hybrid mode:
- Filesystem artifact preserved in `openspec/changes/archive/2026-08-19-admision-acotada-y-proceso-dedicado/archive-report.md`
- Archive report saved to Engram topic `sdd/admision-acotada-y-proceso-dedicado/archive-report` for persistent traceability
- Observation IDs recorded above link to Engram artifacts for future reference
