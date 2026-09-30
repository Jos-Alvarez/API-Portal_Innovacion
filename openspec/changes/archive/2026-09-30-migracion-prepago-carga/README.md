# Migración de `Prepago_Carga` — processor `prepago-carga`

| | |
|---|---|
| **Change** | `migracion-prepago-carga` |
| **BACKLOG item** | — (third real processor, same pattern as #16) |
| **Date** | 2026-09-30 |
| **Commits** | not committed yet |
| **Branch** | `main` (working tree) |
| **Mode** | Fast cycle (exploration → implementation → verification) |

## Summary

`Prepago_Carga.py` — the 252-line pandas script at the repository root —
becomes `app/procesadores/prepago_carga/`, registered under the key
`prepago-carga`, following the `contado_carga` precedent to the letter. One
Excel of transfers between accounts comes in; `resultado_transferencias.xlsx`
(sheet `Transferencias`) and `resultado_transferencias.txt` come out, plus
`descartes.txt` only when rows were discarded.

Verified against the real extract of February 2026 (33 records): the module
reproduces the **historical** outputs the script produced on 2026-03-20 — TXT
**byte for byte** (same `sha256`), Excel **cell by cell, types included**.

## Exploration

Read all of the script, the real input (every cell and its type) and both
historical outputs.

Findings that changed the work:

- **The script reads by position and skips one column.** `iloc[0..4]`,
  `iloc[6]` and `iloc[7]`; column 5 (`TIPO`) is ignored. The real header row
  gives the seven names, including **`COMISON`** — a typo in the source file,
  kept exactly.
- **Dates are text.** Both date columns hold strings like `13.02.2026`, so
  the `%d.%m.%Y` format is the normal case, not an edge case.
- **Year and month come from different columns.** The header year is from
  FECHA DOCUMENTO, the month from FECHA CONTABLE. Kept verbatim; it only
  shows across a year boundary.
- **The commission line is odd in two ways.** It is emitted when the
  commission is `!= 0.0` (negatives included, dumped with `abs()`), and,
  unlike the other two detail lines, it carries **no text** in column 25.
- **Three silent discards, one unreachable check.** BANCO ENTRADA empty is a
  bare `continue`; either date invalid is a `print` + `continue`. The
  `pd.isna(banco_salida)` check can never fire: the previous filter already
  removed those rows (`notna() & != ""`, and `read_excel` had already turned
  `""` into NaN).
- **Integer commissions become floats.** `limpiar_monto` always returns a
  `float`, so a commission of `20` is written `20.0` in the TXT. The
  historical TXT confirms it.

## Decisions

Taken with the user before implementation:

1. Key `prepago-carga`; contract row `CONTRATO_POR_DEFECTO` (one xlsx), in
   `app/registry.py` and `_TABLA_CONTRATOS`.
2. Outputs as the script names them, plus `descartes.txt` only when there are
   discards and a `registrar_descartes` log line.
3. Columns by name after `strip()`; missing → `columna_faltante`. First sheet.
4. Business rules verbatim, including the quirks above.
5. The header row and rows with an empty BANCO SALIDA are filtered before
   counting (not discards). BANCO ENTRADA empty, FECHA DOCUMENTO invalid and
   FECHA CONTABLE invalid are reported discards, with row number and value.
6. The per-row `try/except: print; continue` is gone. Zero processed rows →
   `cero_filas` before writing anything; unreadable workbook → `cero_filas`.
7. No balance check (50 vs 40 + commission) is added.

Taken during implementation, and documented in the module:

- **"Empty" means what pandas reads as NaN.** `None`, `""` and the default
  `na_values` strings (`"NA"`, `"nan"`, `"#N/A"`, …), for the pre-filter,
  BANCO ENTRADA and amounts — same set as `asientos_contables`.
- **A number in a date column is an invalid date.** `pd.to_datetime` read it
  as nanoseconds since 1970 and produced a `19700101` entry; here it is
  discarded as `fecha_*_invalida`. Same criterion as the other two
  processors. The real extract has none.
- **One reason per row**, checked in the script's order: BANCO ENTRADA, then
  FECHA DOCUMENTO, then FECHA CONTABLE.

## Implementation

- **`app/procesadores/prepago_carga/modulo.py`** — the processor,
  self-contained (no helpers shared with `contado_carga`). Descriptor-based
  `load_workbook(read_only=True, data_only=True)`, because temporaries are
  extensionless.
- **`app/core/contrato.py`**, **`app/registry.py`** — contract row and
  registration.
- **`tests/paridad/manifiesto.toml`** — pair `01` with provenance.

## Verification

- `tests/test_procesador_prepago_carga.py` — 70 behaviour tests on synthetic
  workbooks saved as extensionless `entrada_0`: the four-line layout, the
  year/month split, commission zero / empty / unparseable / negative, float
  banks, rounding, TXT formatting and CRLF, each discard reason with row and
  value, the log line, every missing column, `cero_filas`, unreadable files,
  and an HTTP end-to-end test across the `spawn` child.
- `tests/paridad/test_prepago_carga.py` — skips without `FIXTURES_PARIDAD`;
  **6 passed** with the pair in place.
- Full suite **551 passing** + 15 skipped; `ruff` and `mypy --strict` clean
  on the project (see "Still open" for the legacy script).

### Real-sample parity

| Output | Result |
|---|---|
| TXT | identical, `sha256` `33a650f0…458580c`, 141 lines, 141 CRLF |
| Excel | 141 × 26 cells, 0 differences in value or type |
| Discards | none |
| Balance | all 33 records balance (salida = entrada + comisión) |

The original script did not need to be re-run: the historical outputs and the
module agree exactly.

### Timings (this machine)

Direct call: `validar` 0.03 s, `procesar` 0.06 s. Over HTTP through the
`spawn` child: ~0.4 s per request.

## Still open

- **Pairs 02 and 03.** The PRD requires three.
- **The line ending is observed, not confirmed** (141 CRLF, zero lone LF).
- **The legacy script is not excluded from ruff.** `Prepago_Carga.py` is an
  untracked file at the root; `ruff check .` reports 30 findings and
  `ruff format --check .` one file, all in that script. The previous legacy
  scripts were deleted and removed from `extend-exclude`; this one is kept on
  purpose until the user decides.
- **The script version is inferred.** The manifest's `version_script` is the
  hash of the script handed over with the outputs; exact parity is the
  evidence that it is the one that ran.
