# Tasks: Output Packaging (BACKLOG item #9)

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~494-604 (this apply's diff, `adrs/0023` included) |
| 600-line budget risk | **High** — the top of the range already touches 600, and this repo's documented 30-50% test-file overrun lifts the stress scenario to ~722 |
| 400-line budget risk | High — every scenario exceeds the archived format's 400 label; this session's governing budget is 600, not 400 |
| Chained PRs recommended | **Yes** |
| Delivery strategy | `ask-on-risk` — risk trigger reached, the user was asked, and chose to split |
| Chain strategy | `stacked-to-main` |
| Decision needed before apply | Resolved — two stacked PRs, S1 then S2 |

**Correction to this document's first forecast.** The original forecast recorded ~345-455 and a Low
risk verdict, reasoning that `adrs/0023-cero-salidas-y-fallas-de-empaquetado.md` was already
committed and therefore contributed zero lines to this change's diff. That premise is false and was
verified against the repository:

```
$ git status --short
?? adrs/0023-cero-salidas-y-fallas-de-empaquetado.md
?? openspec/changes/empaquetado-de-la-salida/
```

The ADR is **untracked**, never committed, and 149 lines long (not the 135 the design phase
estimated). It counts in full. Adding it back to the original bottom-up range gives 494-604, which
converges with design's independent 475-585 rather than contradicting it. The original stress check
(+50% on the test file alone, holding every other row at its top estimate) was computed on the
ADR-less total; carrying the ADR through gives 573 + 149 = **722**, well over budget.

| Artifact | Est. changed lines | Slice |
|---|---|---|
| `adrs/0023-cero-salidas-y-fallas-de-empaquetado.md` (new, untracked) | 149 (actual) | S1 |
| `app/core/errores.py` (modified) | 20-30 | S1 |
| `tests/test_errores_tipificados.py` (modified) | 20-35 | S1 |
| **S1 subtotal** | **189-214** | |
| `app/core/empaquetado.py` (new) | 120-155 | S2 |
| `tests/test_empaquetado.py` (new) | 185-235 | S2 |
| **S2 subtotal** | **305-390** | |
| **Total** | **494-604** | |

**The two slices.** The seam is design §9's, and it is clean: S1 is additive with no caller, so it is
independently green before S2 begins.

- **S1 — Phase 1** (`errores.py` + `adrs/0023` + error tests, tasks 1.1-1.5): ~189-214 lines. Targets
  `main`. Ships the `ContextoSinSalidas` vocabulary and the ADR that records why `"cero_filas"` is
  deliberately not reused.
- **S2 — Phase 2** (`empaquetado.py` + its tests, tasks 2.1-2.14): ~305-390 lines. Targets S1's
  branch. Depends on `ErrorContenido.sin_salidas()` existing.

Even under the 50% test-overrun scenario, S2 lands at ~460 and S1 is unaffected — both stay inside
the 600-line budget with real margin.


### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| WU1 | `ContextoSinSalidas`, `sin_salidas()`, error-side tests, `adrs/0023` | PR 1 (S1, targets `main`) | `uv run pytest tests/test_errores_tipificados.py` | N/A — pure unit, no route, no subprocess, no filesystem | Revert commit; additive-only, `TipoError` and `_ESTADO_HTTP` untouched, no caller yet |
| WU2 | `app/core/empaquetado.py` + `tests/test_empaquetado.py` | PR 2 (S2, targets PR 1's branch) | `uv run pytest tests/test_empaquetado.py` | `tmp_path`-only; no subprocess, no HTTP client, no `Reserva` | Revert commit; new self-contained module, nothing imports it yet (item #10 wires the seam) |

## Phase 1: Vocabulary — `ContextoSinSalidas` and `sin_salidas()`

- [x] 1.1 `app/core/errores.py`: add `class ContextoSinSalidas(TypedDict): motivo: Literal["sin_salidas"]` and add it as a sibling member of the `Contexto` union (design §2 — `output-packaging` spec, Requirement "Zero outputs raise a typed content error before any file is written")
- [x] 1.2 `app/core/errores.py`: widen `ErrorContenido.contexto` to `ContextoContenido | ContextoSinSalidas`; add `@classmethod sin_salidas(cls) -> ErrorContenido` taking no arguments and building `contexto={"motivo": "sin_salidas"}` (design §2). **Checkpoint (design V6) — outcome recorded**: `mypy --strict` DOES flag direct indexing of the widened two-shape union by a key present in only one member (`ContextoSinSalidas has no key "columna"`), contradicting V6's prediction from the `tests/test_errores_tipificados.py:275` precedent. Root cause isolated empirically: that precedent's `error.contexto["archivos"]` only typechecks because the preceding line (`assert "archivo" not in error.contexto`) is a mypy TypedDict-union narrowing guard (`"key" not in union` removes members that require that key) — it is not indexing an unnarrowed union at all. `ErrorContenido.contexto`'s two shapes share every field name (`motivo`) except the ones that differ, so no such negative-membership guard can isolate `ContextoContenido`. Fixed instead with the discriminant-literal guard `assert error.contexto["motivo"] == "cero_filas"` before indexing `"columna"` (mypy narrows tagged unions by a shared `Literal` field) — no `cast`, no `type: ignore`. Applied at `tests/test_errores_tipificados.py::test_cero_filas_deja_columna_en_none` (the line design flagged as needing to move) and the new `TestDosFormasDeContenido::test_cero_filas_conserva_la_forma_verbatim_de_adr_0014`
- [x] 1.3 `tests/test_errores_tipificados.py`: extend the pickle round-trip coverage to `ErrorContenido.sin_salidas()`, asserting `tipo is TipoError.CONTENIDO` and `contexto == {"motivo": "sin_salidas"}` survive `pickle.loads(pickle.dumps(e))` intact (design §8, mirrors the existing `TestDosFormasDeTamano` pattern) — done by adding `"contenido_sin_salidas": ErrorContenido.sin_salidas()` to `_CASOS`, which the existing `TestPickleRoundTrip.test_sobrevive_el_round_trip` parametrizes over; also added `TestDosFormasDeContenido` mirroring `TestDosFormasDeTamano` explicitly
- [x] 1.4 `tests/test_errores_tipificados.py`: assert the serialized 422 body for `ErrorContenido.sin_salidas()` is exactly `{"tipo": "contenido", "contexto": {"motivo": "sin_salidas"}}`, alongside the existing `CONTENIDO` handler cases (`output-packaging` spec scenario "Empty input raises before touching disk"; design §11 threat-matrix row "Secret or path leakage into a response") — done via `_CUERPOS_ESPERADOS["contenido_sin_salidas"]`, exercised by `TestCasosDeError.test_estado_y_cuerpo_documentados`
- [x] 1.5 Verify: `uv run ruff check . && uv run ruff format --check . && uv run mypy app tests && uv run pytest` — green: ruff clean, mypy strict clean (41 source files), 249/249 tests passing (baseline 242 + 7 new)

## Phase 2: `app/core/empaquetado.py`

- [x] 2.1 `app/core/empaquetado.py` (new): module docstring referencing item #9 / ADR 0011 / ADR 0023; imports stdlib (`zipfile`, `pathlib`, `typing`) plus `app.core.errores` and `app.core.tipos` only — **nothing from `app.core.temporales`, nothing from `app.core.ejecucion`, nothing from `app/procesadores/`**, and no Starlette/FastAPI type in any signature or body (design §7, V5). Define module constants `NOMBRE_DEL_ZIP: Final[str] = "salida.zip"` and `MIME_DEL_ZIP: Final[str] = "application/zip"`, and `class SalidaMalFormada(Exception): ...` (standalone, **not** an `ErrorTipificado` — design §3)
- [x] 2.2 `app/core/empaquetado.py`: `def empaquetar(*, archivos: list[ArchivoSalida], directorio: Path) -> ArchivoSalida` — zero-length input raises `ErrorContenido.sin_salidas()` before any `Path` is built (`output-packaging` spec, Requirement "Zero outputs raise a typed content error before any file is written"); single-element input returns `archivos[0]` verbatim, no ZIP, no name check (`output-packaging` spec, Requirement "A single output is returned verbatim")
- [x] 2.3 `app/core/empaquetado.py`: `def _nombre_plano(nombre_propuesto: str) -> str` — text manipulation only (`replace("\\", "/").rpartition("/")[2]`), never `Path` construction (design §5). A result of `""`, `"."`, or `".."` is degenerate and raises `SalidaMalFormada` — no fallback name is invented
- [x] 2.4 `app/core/empaquetado.py`: `def _verificar(archivos: list[ArchivoSalida], destino: Path) -> list[str]` — pure, no byte reaches disk. Checks, in order: every flattened name is non-degenerate (2.3); no two flatten to the same name; no input's `ruta_temporal` equals `destino`; every `ruta_temporal` exists. All four raise `SalidaMalFormada` (`output-packaging` spec, Requirement "Arcnames are sanitized and duplicate names are rejected")
- [x] 2.5 `app/core/empaquetado.py`: multi-output branch of `empaquetar` — `destino = directorio / NOMBRE_DEL_ZIP`; call `_verificar`; open `zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED)`, write each `(archivo, plano)` pair via `zip(archivos, nombres, strict=True)`; on any exception inside the `with` block, `destino.unlink(missing_ok=True)` then re-raise (the handle is already closed by `__exit__` before the `except` runs — design §4, V3); return the new `ArchivoSalida(nombre_propuesto=NOMBRE_DEL_ZIP, ruta_temporal=destino, tipo_mime=MIME_DEL_ZIP)` only after a clean `close()` (`output-packaging` spec, Requirements "Two or more outputs are compressed into a single flat ZIP", "The ZIP is atomic — fully written and closed, or never returned", "The ZIP is written inside the caller's reserved directory")
- [x] 2.6 `tests/test_empaquetado.py` (new): passthrough is verbatim — one `ArchivoSalida` + `tmp_path`; assert identity of the three fields and that the directory contents are unchanged (`output-packaging` spec scenario "Single output passes through unchanged")
- [x] 2.7 `tests/test_empaquetado.py`: two or more outputs produce exactly one flat ZIP whose members carry the proposed names and the original bytes; assert no member contains `/` or `\` and that `salida.zip` is the only new file (`output-packaging` spec scenario "Multiple outputs produce one complete flat ZIP")
- [x] 2.8 `tests/test_empaquetado.py`: zero outputs raises before disk — `pytest.raises` on `ErrorContenido` with `tipo is TipoError.CONTENIDO` and `contexto == {"motivo": "sin_salidas"}`; assert the directory is still empty afterward (`output-packaging` spec scenario "Empty input raises before touching disk")
- [x] 2.9 `tests/test_empaquetado.py`: hostile names are confined — parametrized over `"../../x.txt"`, `"a/b/c.txt"`, `"C:\\Windows\\x.txt"` — all become flat members with no path separator or `..` component (`output-packaging` spec scenario "A hostile nombre_propuesto is confined to a flat, safe arcname")
- [x] 2.10 `tests/test_empaquetado.py`: degenerate names raise — parametrized over `""`, `"."`, `".."`, `"/"` — each raises `SalidaMalFormada`, and the directory is empty afterward
- [x] 2.11 `tests/test_empaquetado.py`: duplicate `nombre_propuesto` values raise, including two different `ruta_temporal` paths whose names flatten to the same member (`output-packaging` spec scenario "Duplicate nombre_propuesto values raise instead of silently colliding")
- [x] 2.12 `tests/test_empaquetado.py`: an input whose `ruta_temporal` is `directorio / NOMBRE_DEL_ZIP` raises before the write, so `ZipFile(..., "w")` never truncates a file it is about to read
- [x] 2.13 `tests/test_empaquetado.py`: a simulated mid-write failure leaves no `.zip` — `monkeypatch` `zipfile.ZipFile.write` to raise on the second member; assert the exception propagates and `destino` does not exist afterward (`output-packaging` spec scenarios "A write failure never yields a partial ZIP", "A successful ZIP is closed before returning")
- [x] 2.14 Verify: `uv run ruff check . && uv run ruff format --check . && uv run mypy app tests && uv run pytest` — green: ruff clean, ruff format clean, mypy strict clean (43 source files), 268/268 tests passing (baseline 249 + 19 new: 18 in `tests/test_empaquetado.py` plus 1 extra coverage test for the missing-`ruta_temporal` branch of `_verificar`, not literally requested by 2.6-2.13 but needed for 100% coverage of `empaquetado.py`)

## Out of scope (explicitly not this item)

`app/recepcion.py` wiring (the `NotImplementedError` seam at lines 188-190 stays untouched — item #10);
building any `Response`, `Content-Disposition`, or non-ASCII filename encoding (item #10); orchestrating
the 9-step pipeline or its own `try/finally` (item #10); a ceiling on aggregate output size (declared
open in design §11/§13, no `PRESUPUESTO_DE_RAM_BYTES`-style field introduced); ZIP container
byte-determinism (items #15/#16, no fixture requires it today); re-authoring `adrs/0023` (the design phase already wrote it;
it is untracked and ships as part of S1, so no task writes it again).
`app/core/{temporales,ejecucion,tipos,contrato,validaciones}.py`, `app/main.py`, and `app/registry.py`
stay untouched by every task in this list.
