# Migración de `flujoCaja_BancoNacion` + `flujoCaja_consolida_Ingresos` — processor `flujo-caja-ingresos`

| | |
|---|---|
| **Change** | `migracion-flujo-caja-ingresos` |
| **BACKLOG item** | — (same pattern as `asientos-contables`) |
| **Date** | 2026-09-30 |
| **Commits** | not committed yet |
| **Branch** | `main` (working tree) |
| **Mode** | Fast cycle (exploration → implementation → verification) |

## Summary

Two pandas scripts at the repository root, which the user ran one after the
other on the same input folder, become one processor,
`app/procesadores/flujo_caja_ingresos/`, registered under the key
`flujo-caja-ingresos`:

- `flujoCaja_BancoNacion.py` (197 lines) reads sheet `BCO NACION` of the
  **Operativas** workbook and writes `Banco_Nacion.xlsx`.
- `flujoCaja_consolida_Ingresos.py` (850 lines) reads six sheets of the
  **Fideicomisas** workbook and four of the **Operativas** workbook and writes
  `Consolidado_Ingresos.xlsx` (sheets `Consolidado Fideicomiso` and
  `Consolidado Operativas`, each only when it has rows).

The two logics stay separate inside the module (`_banco_nacion` on one side,
`_fideicomiso` / `_operativas` on the other); only the portal window is shared.

Verified against the real 2025 workbooks: the module reproduces both
**historical** outputs (August 2025) **cell by cell with exact equality** —
zero tolerance, including value types as read back and the row order of
pandas' unstable sort — in all three sheets.

## Exploration

Read both scripts, both real inputs (every configured sheet, its header row
and the cell types of every column read) and both historical outputs.

Findings that changed the work:

- **The historical outputs are reproducible today.** Re-running the original
  scripts (pandas 3.0.6, numpy 2.4.2) on the two inputs gives both historical
  files cell by cell, so the inputs were not edited after the outputs were
  produced. `flujoCaja_BancoNacion.py` is dated three hours *after* its output,
  but the re-run shows the rules did not change.
- **`sort_values('F. Operación')` is not stable, and the ties matter.** In the
  historical Fideicomiso sheet the first rows of 2 January are BCP rows,
  although IBK rows come first in concatenation order, so a stable sort does
  not reproduce it. On `datetime64` numpy uses its generic introsort
  (`aquicksort_`, `SMALL_QUICKSORT = 15`, median of three, heapsort fallback),
  not the SIMD path used for `int64`. That algorithm is deterministic and
  CPU-independent, which is why the author's machine and this one agree. It is
  replicated line by line in `_orden_de_pandas`; it matches pandas on both real
  sheets and on 400 random cases (up to 20,000 rows, with ties and nulls).
- **The configured `fila_inicio` does not always skip the header.** In
  Operativas the header is *inside* the range the script reads (row index 14
  in IBK, 10 in BBVA; the script comments say "row 7/9"). The script read it as
  a data row and dropped it because `"Cargos"` / `"Importe"` clean to 0. The
  module validates that row and skips it, with the same result.
- **Every configured sheet has a real header row at a fixed position**:
  two rows before `fila_inicio` in the six Fideicomiso sheets (IBK 14, BCP 4,
  BBVA 10, Santander 5), 14 / 10 in Operativas, and row 1 in `BCO NACION`
  (`header=1`). So positions are kept (as the scripts do) and the header label
  above every column read is validated.
- **`BCO NACION` is all text.** Dates are `"2025.01.02"` strings; `Cargo`
  holds thousands of `''` and `'\xa0'` cells. With `dtype=str` the output
  `F. Operación` is that text, not a date. The sheet declares 1,048,575 rows.
- **Rows without a date are balance lines** (`Saldo Final 02-01-2025`,
  hundreds per workbook), dropped on purpose by the date filter. They are not
  reported.
- **`str.replace('.', '-')` is literal only since pandas 2.0.** The historical
  output has `Semana` filled, so it was produced with pandas ≥ 2 (with the old
  regex default every date would have become `----------` and `Semana` empty).
- **Integers and integral floats are the same cell.** openpyxl writes `66.0`
  as `<v>66</v>`, so the file cannot distinguish them; the comparison
  normalises them, as in `asientos-contables`.

## Decisions

Taken with the user before implementation:

1. One portal window: contract row `entradas_min=1, entradas_max=2`, xlsx
   only, default size caps. Registered in `REGISTRY` and `_TABLA_CONTRATOS`.
2. Workbook type detected by sheet names (Fideicomiso sheets → Fideicomisas;
   Operativas sheets or `BCO NACION` → Operativas). Fallback: the scripts'
   filename substrings, case-insensitive. Sheets of both types, or no sheet
   and no usable name → `tipo_no_reconocido`; two workbooks of one type →
   `tipo_duplicado`. Both real samples are detected by their sheets.
3. Outputs: both workbooks → `Consolidado_Ingresos.xlsx` (two sheets) +
   `Banco_Nacion.xlsx`; Operativas only → `Consolidado_Ingresos.xlsx`
   (Operativas sheet) + `Banco_Nacion.xlsx`; Fideicomisas only →
   `Consolidado_Ingresos.xlsx` (Fideicomiso sheet). Plus `observaciones.txt`
   (CRLF, UTF-8) only when something was lost or skipped. The core packages
   single file vs ZIP.
4. Business rules verbatim, pandas semantics reproduced without pandas.
5. Hardening: no swallowed exceptions; a configured sheet that is missing is
   still skipped but reported (`hoja_ausente`), as is a present sheet that
   contributes no row (`hoja_sin_filas`); a workbook that contributes no row
   to any output is `cero_filas`; unreadable amounts and dates are reported.

Taken during implementation, and documented in the module:

- **Header validation.** Each column read must sit under its expected label
  (compared after trimming, removing accents and case-folding). A shifted
  layout fails with `columna_faltante`; since `ContextoContenido` has a single
  free field, the column travels as `"<sheet>: <label>"`, e.g.
  `"IBK 1106 FID: Abonos"`. A header row that is missing altogether fails the
  same way.
- **Detected by name but no configured sheet** → `hoja_faltante` naming the
  first configured sheet (the workbook cannot contribute anything).
- **Unreadable date in `BCO NACION`.** The script computed the month with
  `meses_es[m - 1]` on a column that becomes `float` as soon as one date is
  `NaT`, so it crashed and wrote no `Banco_Nacion.xlsx`. The module keeps the
  row with empty `Mes` / `Semana` (what the consolidated script does with an
  unreadable date) and reports `fecha_invalida`.
- **A number in a consolidated date column is an unreadable date.**
  `pd.to_datetime` read it as nanoseconds since 1970. Reported, left empty;
  same criterion as the previous migrations.
- **Dates written as text.** Parsed month first (`pd.to_datetime` without
  `dayfirst`), day first only when the "month" exceeds 12 (dateutil's
  fallback). Year-first text is silent; any other text date is reported as
  `fecha_texto`. pandas infers one format for the whole column when its first
  value is text; the module parses each value on its own, which is what pandas
  does when the first value is a real date (the case in both samples).
- **Amounts.** `pd.to_numeric(errors='coerce')` is emulated (ASCII spaces
  tolerated; no thousands separators, no non-breaking space, no `_`).
  `limpiar_valor_monetario` is copied verbatim, including Python's `float()`.
  An amount that is not blank and does not parse is reported as
  `importe_invalido` where the script turned it into 0 or dropped the row;
  blank cells (`''`, `'\xa0'`) are not.
- **`BCO NACION` with zero rows** still produces a header-only
  `Banco_Nacion.xlsx`, as the script did, plus a `hoja_sin_filas` observation.
- **Output styling.** Header cells bold, thin border, centred, and dates with
  `YYYY-MM-DD HH:MM:SS`, as `to_excel` wrote them. Content is what parity
  checks.
- **No change to `tests/paridad/manifiesto.py`.** It already accepted several
  `entrada*` / `salida*` roles per pair; the pair declares two inputs and two
  outputs. `version_script` holds one hash (the consolidated script's); the
  Banco Nación script's hash and both run dates are recorded in the comment.

## Implementation

- **`app/procesadores/flujo_caja_ingresos/modulo.py`** — the processor.
  `validar` reads only up to each header row (type, headers, duplicates);
  `procesar` computes every output before writing any, so a late `cero_filas`
  leaves nothing half-written.
- **`app/core/contrato.py`**, **`app/registry.py`** — contract row and
  registration.
- **`tests/paridad/manifiesto.toml`** — `[flujo_caja_ingresos]` with one
  pair and its provenance.

## Verification

- `tests/test_procesador_flujo_caja_ingresos.py` — 69 behaviour tests on
  synthetic workbooks laid out like the real sheets, saved as extensionless
  `entrada_N`: detection (sheets, name fallback, ambiguity, duplicates), the
  three input combinations, Fideicomiso filters and totals, Operativas
  cargos/abonos split, categories and export rounding, Banco Nación text
  handling, `calcular_semanas_mes` for months starting Sunday, Monday,
  Wednesday and Saturday, `categorizar` and `limpiar_valor_monetario`
  branches, the unstable sort, errors, observations and their log line, and
  an HTTP end-to-end test across the `spawn` child (both workbooks → ZIP with
  both xlsx; a duplicate → typed 422).
- `tests/paridad/test_flujo_caja_ingresos.py` — the real pair, compared by
  content with types; skips without `FIXTURES_PARIDAD`. Run against a copy of
  the fixtures outside the repository: passes.
- Full suite (683 passed, 22 skipped), `ruff check`, `ruff format --check`
  and `mypy --strict app tests` clean (legacy root scripts excluded via CLI).

### Real-sample parity

| Output | Sheet | Rows (incl. header) | Differing cells |
|---|---|---|---|
| `Consolidado_Ingresos.xlsx` | Consolidado Fideicomiso | 9,113 | 0 |
| `Consolidado_Ingresos.xlsx` | Consolidado Operativas | 7,054 | 0 |
| `Banco_Nacion.xlsx` | Banco Nacion | 10,727 | 0 |

No observations on the real pair.

### Timings (direct `procesar`, this machine)

Both workbooks: `validar` 0.31 s, `procesar` 6.7 s, peak working set 45 MB.
Fideicomisas alone 2.2 s; Operativas alone 4.3 s (most of it iterating the
1,048,575 declared rows of `BCO NACION`). Over HTTP through the `spawn`
child: 7.1 s. Both files are ~1.1 MB, well under the 25 MB caps.

## Still open

- **`columna_faltante` carries sheet and column in one string**, because the
  error context has a single free field.
- **The heapsort fallback of numpy's introsort** is translated but not
  exercised by any real or synthetic input (it needs an adversarial order);
  it is reviewed against numpy's source, not tested against numpy (whose
  `kind='heapsort'` no longer runs a pure heapsort).
- **`version_script` is inferred** and holds only one of the two scripts'
  hashes; exact parity is the evidence.
- **Fixtures must be copied to the share** under `flujo_caja_ingresos/` with
  the names in the manifest for the parity suite to run there.
