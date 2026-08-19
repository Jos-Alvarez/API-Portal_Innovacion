# Tasks: Contract Validations and Memory Defense (BACKLOG item #7)

**Status: RETROACTIVE — already implemented, committed, and merged to `main`** (`2b4f49c` → `9ca2d85`).
Every unit below is checked and describes what actually shipped, per design.md §13's three-slice chain.

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | Actual: ~2228 insertions / 64 deletions (13 files incl. artifacts); code+tests only: ~880 insertions / 64 deletions |
| 600-line budget risk | High — resolved by fact, delivered as three chained slices |
| Chained PRs recommended | Yes (already applied) |
| Suggested split | PR 1 (A1) → PR 2 (A2) → PR 3 (B), stacked-to-main |
| Delivery strategy | ask-on-risk |
| Chain strategy | stacked-to-main |

Decision needed before apply: No (apply is complete)
Chained PRs recommended: Yes (already applied)
Chain strategy: stacked-to-main
600-line budget risk: High

No `size:exception` was needed: each slice landed independently green and within the code-only budget.

### Suggested Work Units (as delivered)

| Unit | Goal | PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|----|-----------------------|------------------|--------------------|
| A1 `7225aa9` | Error vocabulary: `ContextoTamanoTotal`, widened `ErrorTamano.contexto`, `ErrorTamano.total()` | PR 1 | `uv run pytest tests/test_errores_tipificados.py` | N/A — pure unit, no route | Revert commit; purely additive union member, no caller yet |
| A2 `9db1040` | `app/core/validaciones.py`: five pure checks + `PRESUPUESTO_DE_RAM_BYTES` | PR 2 | `uv run pytest tests/test_validaciones.py` | N/A — hand-built `ContratoProcesador`, no HTTP/disk except zip cases | Revert commit; delete module, nothing calls it yet |
| B `9ca2d85` | Wire validaciones into `app/recepcion.py`'s two-phase seam | PR 3 | `uv run pytest tests/test_recepcion.py` | `uv run pytest` full route suite (multipart via TestClient) | Revert commit; restores unconditional `_copiar` loop |

## Phase 1: Error vocabulary (Slice A1, commit `7225aa9`)

- [x] 1.1 `app/core/errores.py`: add `ContextoTamanoTotal` TypedDict; join into `Contexto` union
- [x] 1.2 `app/core/errores.py`: widen `ErrorTamano.contexto` to `ContextoTamano | ContextoTamanoTotal` (V8)
- [x] 1.3 `app/core/errores.py`: add `ErrorTamano.total()` classmethod (mirrors `ErrorContenido` pattern)
- [x] 1.4 `tests/test_errores_tipificados.py`: add `tamano_total` case to `_CASOS`/`_CUERPOS_ESPERADOS`; add `TestDosFormasDeTamano`
- [x] 1.5 `adrs/0021-validaciones-de-contrato-y-presupuesto-de-memoria.md`: record Decisions 1–3, H-09/H-04 status
- [x] 1.6 Commit SDD artifacts (proposal/spec/design) alongside A1 — a deviation from design.md §13, recorded below

## Phase 2: Validation module (Slice A2, commit `9db1040`)

- [x] 2.1 `app/core/validaciones.py`: `validar_cantidad(*, recibido, contrato)` — entradas_min/max
- [x] 2.2 `app/core/validaciones.py`: `validar_formato(*, nombre_original, formato, contrato)`
- [x] 2.3 `app/core/validaciones.py`: `validar_tamano(*, nombre_original, tamano_bytes, contrato)`
- [x] 2.4 `app/core/validaciones.py`: `validar_tamano_total(*, nombres, total_bytes, contrato)` → `ErrorTamano.total()`
- [x] 2.5 `app/core/validaciones.py`: `validar_tamano_descomprimido(entrada, *, presupuesto_bytes=PRESUPUESTO_DE_RAM_BYTES)`; central-directory only (V10); non-ZIP/`BadZipFile` are no-ops
- [x] 2.6 `app/core/validaciones.py`: `PRESUPUESTO_DE_RAM_BYTES: Final[int] = 256 * 1024 * 1024`
- [x] 2.7 `tests/test_validaciones.py`: boundary case per function, full-context assertions, zip-bomb fixture (declared size, no decompression), non-ZIP/corrupt-ZIP no-op cases

## Phase 3: Wire into recepcion (Slice B, commit `9ca2d85`)

- [x] 3.1 `app/recepcion.py`: split per-file loop into phase 1 (cantidad/formato/tamaño/tamaño-total pre-checks above `reservar()`) and phase 2 (copy + measured checks inside `with reservar()`), replacing the `del entradas` seam
- [x] 3.2 `app/recepcion.py`: `_copiar` gains `limite_bytes` and `nombre_original`; closes output handle before raising on abort (Windows `rmtree` safety)
- [x] 3.3 `tests/test_recepcion.py`: add `inyectar_contrato` fixture patching `app.core.contrato._TABLA_CONTRATOS`
- [x] 3.4 `tests/test_recepcion.py`: rebuild the three on-disk reception assertions (item #6 regression) on the injected fixture
- [x] 3.5 `tests/test_recepcion.py`: five failure-axis integration tests (cantidad/formato/tamaño/tamaño-total/zip-bomb), full-body 422 equality
- [x] 3.6 `tests/test_recepcion.py`: ordering regression — a batch rejected in phase 1 creates no directory at all (`captura_de_limpieza` stays empty, proving `reservar()` was never entered); a phase-2 failure leaves the copied file on disk and lets the `finally` remove it
- [x] 3.7 `tests/test_recepcion.py`: unknown-key request still returns 500 `clave_inexistente`, now before any write
- [x] 3.8 `tests/test_recepcion.py`: `TestCopiaAcotada` — five direct-call unit tests over `_copiar` (abort reports the real count, output handle closed so the partial file deletes immediately, verbatim copy below the ceiling, exact-limit acceptance, defensive cursor reposition). Tested by direct call rather than through the route because the ceiling is unreachable over HTTP: Starlette always measures `carga.size`, so the phase-1 pre-check always wins. That direct call is also the path items #9/#10 could take with no pre-check at all

## Phase 4: Verification (already run)

- [x] 4.1 Isolation check via `git stash push -u` between commits: A1 alone = 141 tests, A1+A2 = 173, all three = 184
- [x] 4.2 Final `main`: 184 tests passing (134 before), 99% coverage; `app/recepcion.py` and `app/core/validaciones.py` at 100% line coverage
- [x] 4.3 `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy app tests` all clean (36 files)
- [x] 4.4 Confirmed `app/core/temporales.py` and `app/core/contrato.py` changed by zero lines (design.md §2/§8 proof)

## Deviations from design.md §13 (recorded, not silently discovered)

1. SDD artifacts were assigned to no slice in §13; they shipped with A1 because A1 already carries ADR 0021 — same body of decisions.
2. `_copiar` writes the limit-crossing chunk whole, not split. Overshoot bounded at one 1 MiB chunk; `recibido_bytes > limite_bytes` on abort. Rejected alternative (stop before crossing) would report `recibido_bytes <= limite_bytes`, a 422 body unable to explain its own rejection. `contract-validation` spec reconciled to this wording.

## Non-blocking follow-ups (left open on purpose)

1. `ContratoProcesador.activo` remains unenforced; `CausaFila.fila_inactiva` unreachable — out of scope (proposal's five axes; design.md §14, ADR 0021 Consecuencias).
2. Declared-uncompressed sum is per-archive, not per-batch — moot while `entradas_max = 1`, becomes a real zip-bomb shape once a contract accepts more than one file.
3. H-09 stays declared open, H-04 stays partially open — explicit user decision (proposal Decision 1, ADR 0021 Consecuencias). Item #8 owns the real memory ceiling; the ASGI middleware is the only mechanism closing H-09, scoped out here.
