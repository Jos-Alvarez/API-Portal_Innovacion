# Verification Report: validaciones-de-contrato-y-defensa-de-memoria

**Change**: `validaciones-de-contrato-y-defensa-de-memoria` (BACKLOG item #7)
**Verdict**: PASS — 0 CRITICAL, 0 WARNING, 0 SUGGESTION
**Run**: 2026-08-19. Engram twin: observation #123, topic
`sdd/validaciones-de-contrato-y-defensa-de-memoria/verify-report`.
**Mode**: Full artifact verification (proposal, spec, design, tasks all present).
**Methodology**: Strict TDD disabled for this project since item #3 (`openspec/config.yaml:30`) —
the absence of AST/structural/chaos tests is the recorded methodology, not a defect.
**Delivery state**: four commits on `main`, HEAD `7cb58fc`. Clean tree at verification time.

No `apply-progress` artifact exists, and that is expected: this project's Fast Path implements
directly rather than through `sdd-apply`. Verification therefore traced the commits and the working
tree directly, independent of the orchestrator's `tasks.md` and Engram claims.

## Command Evidence (real output, run by the verifier)

```
$ uv run pytest
184 passed, 1 warning
Coverage 99%. app/recepcion.py 100% (54/54 stmts); app/core/validaciones.py 100% (30/30 stmts).

$ uv run ruff check .
All checks passed!

$ uv run ruff format --check .
53 files already formatted

$ uv run mypy app tests
Success: no issues found in 36 source files

$ git diff --stat 2b4f49c..HEAD -- app/core/temporales.py app/core/contrato.py
(empty output, exit 0)
```

All commands exit clean. The empty diff is design.md §2/§8's mechanical proof that item #6's
cleanup guarantee is untouched: `app/core/temporales.py` and `app/core/contrato.py` changed by zero
lines across the whole change.

`git show --stat` on all four commits matches the figures recorded in `tasks.md` exactly:
`7225aa9` 1348+/3− (9 files, SDD artifacts included), `9db1040` 402+ (2 files),
`9ca2d85` 478+/61− (2 files), `7cb58fc` 78+ (`tasks.md` only).

## Task Completion

25/25 units in `tasks.md` checked, across all four phases. No unchecked work.

## Requirement Coverage

Every requirement across the three delta specs is met by code and covered by a passing test:

| Requirement area | Implementation | Proof |
|---|---|---|
| Contract before write; count before per-file; format before size | `app/recepcion.py:137-148` | ordering regression + five failure-axis tests in `tests/test_recepcion.py` |
| Declared pre-pass gated on all sizes present | `app/recepcion.py:154-158` | `len(medidos) == len(archivos)` is genuinely equivalent to "every file reported a size": one `None` disables the whole pass |
| Measured total re-checked after EACH copy | `app/recepcion.py:180-186` | sits inside the per-file `for`, not after it — confirmed by direct code read, not inference |
| `ErrorTamano.total()` / `ContextoTamanoTotal` | `app/core/errores.py:55,124-155` | `tests/test_errores_tipificados.py::TestDosFormasDeTamano` — verbatim ADR-0014 shape preserved, sibling shape distinct, the `archivo=""` placeholder does not leak |
| Declared uncompressed size, no decompression | `app/core/validaciones.py:140-154` | central directory only via `is_zipfile`/`infolist()`; non-ZIP and `BadZipFile` are no-ops |
| `TipoError` stays at five values | `app/core/errores.py` | union gains `ContextoTamanoTotal` only |

## `_copiar` — all four spec-claimed properties scrutinised

`app/recepcion.py:62-102`, proven by `tests/test_recepcion.py::TestCopiaAcotada`. These are
direct-call unit tests rather than route-level ones because the ceiling is unreachable over HTTP —
Starlette always measures `carga.size`, so the phase-1 pre-check always wins. The test docstring
says so.

1. **Stops reading once bytes written exceed the limit** — `if escritos > limite_bytes: break`
   inside the chunked loop. `test_corta_al_cruzar_el_limite_y_reporta_la_cuenta_real` asserts the
   destination holds exactly one 1 MiB chunk from a 3 MiB source.
2. **Overshoot bounded to one chunk** — the crossing chunk is written whole, matching the recorded
   deviation.
3. **`recibido_bytes` is a real count strictly greater than the limit** — same test asserts
   `1024*1024` against `limite_bytes=1024`.
4. **Output handle closes before the raise** — the raise sits after the `with destino.open("wb")`
   block. Proven, not asserted around: `test_deja_el_manejador_cerrado_al_abortar` calls
   `destino.unlink()` immediately after the raised exception and asserts it succeeds. That is the
   Windows-relevant behaviour ADR 0020 depends on for synchronous cleanup.

## Static Facts Double-Checked

- `adrs/` holds 0011–0021 on disk; ADR 0021 exists as claimed.
- `openspec/config.yaml:8`'s "0011-0015 exist" comment is confirmed **stale**. Pre-existing wart,
  not introduced by this change and not this change's job to fix.
- `openspec/config.yaml:30` `strict_tdd: false` confirmed.

## Recorded Deviations and Open Items — all check out

1. SDD artifacts shipped with slice A1 — confirmed via `git show --stat 7225aa9`.
2. `_copiar` writes the limit-crossing chunk whole, spec reconciled — confirmed in both the code and
   the on-disk spec text.
3. `ContratoProcesador.activo` unenforced — confirmed out of scope; `app/core/contrato.py` has zero
   diff lines.
4. Declared-uncompressed sum is per-archive, not per-batch — confirmed in
   `validar_tamano_descomprimido`'s per-`ArchivoEntrada` signature; moot while `entradas_max = 1`.
5. H-09 open, H-04 partially open — confirmed recorded in ADR 0021's Consecuencias and in both
   delta specs' out-of-scope paragraphs.

No inaccuracy found in any recorded deviation or open item. No uncovered gap found.

## Verdict

**PASS.** All requirements met with real test coverage, all commands green with real output, both
hard-scrutiny points (the bounded copy and the two-total design) hold up under direct code and test
inspection, and every recorded deviation checks out against evidence. Recommended next phase:
`sdd-archive`.
