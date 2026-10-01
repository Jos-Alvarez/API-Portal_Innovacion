# Migración de `flujoCaja_consolida_pagos` — processor `flujo-caja-pagos`

| | |
|---|---|
| **Change** | `migracion-flujo-caja-pagos` |
| **BACKLOG item** | — (same pattern as `flujo-caja-ingresos`) |
| **Date** | 2026-09-30 |
| **Commits** | not committed yet |
| **Branch** | `main` (working tree) |
| **Mode** | Fast cycle (exploration → implementation → verification) |

## Summary

The pandas script `flujoCaja_consolida_pagos.py` (383 lines) at the
repository root becomes `app/procesadores/flujo_caja_pagos/`, registered under
the key `flujo-caja-pagos`. It consolidates one or more weekly "Pagos
Programados" workbooks (`.xlsm`) of two kinds, **LIMA EXPRESA** and **PEX**,
into `Consolidado_Pagos.xlsx` with sheets `Soles` and `Dolares` (each only
when it has rows).

It is the first processor that accepts macro-enabled workbooks.

Verified against the three real July 2025 LIMA EXPRESA workbooks: the module
reproduces the script's output **cell by cell with exact equality**, including
value types as read back, column order and row order, in both sheets.

## Exploration

Read the whole script, the three real inputs (every configured sheet, its
header row and the cell types of every column the script reads) and the
output. Re-ran the original script (pandas 3.0.6, numpy 2.5.3) on copies of
the inputs, patching only the paths and the final `input()`.

Findings that changed the work:

- **The "historical" output is recent.** Its docProps say openpyxl, created
  2026-09-30 20:43 UTC; the script is dated 2025-08-11. Re-running the script
  today reproduces it cell by cell, so it is the script's output for exactly
  these three inputs.
- **`dtype=str` shapes the whole output.** Every one of the 28 standard
  columns is text except the two amounts (converted with `to_numeric`) and
  `Fecha de pago BANCOS` (converted back to a date by
  `generar_columnas_mes_semana`). `Cuenta`, `Clase de documento`,
  `Período contable` etc. are written as text (`"3000019305"`, `"7"`).
- **`pd.to_datetime` infers one format from the first value of the column.**
  With `dayfirst=True` (the `Base p plazo pago` column), pandas reads a
  year-first string as year/**day**/month: `"2025-06-01"` → 6 January
  (`%Y-%d-%m`), verified against pandas 3.0.6. Two-digit years are never
  inferred (per-value dateutil fallback). Leading spaces become part of the
  format. All of this is replicated in `adivinar_formato`.
- **Headers vary in punctuation between sheets** (`Base p plazo pago`,
  `Base p, plazo pago`, `Base p/ plazo pago`), and some columns no rule reads
  have no label (`PLATAFORMA IBK` columns 16 and 18). The script ignores the
  header row entirely.
- **`PLATAFORMA BCP` is configured only for PEX, but the three LIMA EXPRESA
  workbooks also have it** (the script never reads it for them). It cannot
  decide the type.
- **Empty sheets are routine.** Five configured sheets of week 1, one of
  week 2 and two of week 3 have no row with `Cuenta` (the script printed
  "no contiene datos"). `REEMBOLSOS_SOL` declares 1,048,5xx rows.
- **The `-` suffix does not make an amount negative.** `"12,500.00-"` becomes
  `12500`; only `Clase de documento == '7'` makes it negative, every other
  class makes it positive (`abs`).

## Decisions

Taken with the user before implementation:

1. One portal window: contract row `entradas_min=1, entradas_max=10,
   formatos_aceptados=("xlsm", "xlsx")`, default size caps. Ten is a generous
   ceiling for a month of weekly files, not a rule of the script. Registered
   in `REGISTRY` and `_TABLA_CONTRATOS`.
2. Type detected by sheet names: LIMA EXPRESA = any of `SOLES`,
   `CAJA CHICA LE`, `REEMBOLSOS_SOL`, `DOLARES`, `REEMBOLSOS_DOL`, `PLANILLA`,
   `PLATAFORMA IBK`; PEX = `PEX SOL` or `PEX DOL`. `PLATAFORMA BBVA` and
   `PLATAFORMA BCP` do not decide. Fallback: the script's filename
   substrings, case-insensitive, on the base name. Sheets of both types, or
   no deciding sheet and a name with neither or both substrings →
   `tipo_no_reconocido`. Several workbooks of the same type are normal: there
   is no `tipo_duplicado`.
3. File order replicates the script: all LIMA EXPRESA first, then all PEX,
   each group in `glob.glob` order on Windows keyed by `nombre_original`.
4. Output `Consolidado_Pagos.xlsx` alone, plus `observaciones.txt` (CRLF,
   UTF-8) only when something was skipped or lost. No swallowed exceptions;
   zero rows overall → `cero_filas`.
5. Business rules verbatim, pandas semantics reproduced without pandas.

Taken during implementation, and documented in the module:

- **NTFS order.** `glob` uses `os.scandir`, which returns the NTFS directory
  index order: names compared as UTF-16 code units after upcasing each unit
  with the volume's `$UpCase` table (simple one-to-one Unicode uppercase;
  non-BMP characters untouched). `_clave_ntfs` encodes the upcased name as
  UTF-16-BE, whose byte order equals code-unit order. So `_` (0x5F) sorts
  after letters and `b` before `C`. Verified against the original script on
  an NTFS scratch directory with names `A lima…`, `b LIMA…`, `_LIMA…`. Ties
  (two uploads with the same name) keep upload order.
- **A filename containing both substrings.** The script put it in both glob
  lists; the second dictionary assignment overwrote the first without moving
  it, so the workbook was processed **once, as PEX, in the LIMA EXPRESA
  position**. The module does not guess that name: without deciding sheets it
  is `tipo_no_reconocido`.
- **Header validation.** Only the columns a rule reads are validated (`Cuenta`,
  `Base p plazo pago`, `Clase de documento`, `Moneda del documento`, both
  amounts, `Orden`, `Fecha de pago BANCOS`), by position, comparing letters
  and digits only (accents and case folded), and only the positions the sheet
  actually reaches: a narrower sheet is processed like the script does
  (missing columns are NaN). A mismatch is `columna_faltante` with
  `"<sheet>: <label>"`. `validar` reads only the header row, so a blank header
  row with data below is caught by `procesar`.
- **Observations** (`observaciones.txt`): `hoja_ausente` (configured sheet
  missing, still skipped), `importe_invalido` (non-blank amount that does not
  parse; left empty as the script did), `fecha_invalida` (non-blank payment
  or base date that does not parse, leaving `PPP`/`Mes`/`Semana` empty),
  `moneda_ausente` ("Por moneda" sheet without `Moneda del documento`; the
  script dropped the sheet) and `moneda_no_reconocida` (row of a "Por moneda"
  sheet whose currency is not exactly `PEN` or `USD`; the script dropped it).
  Blank dates and blank amounts are not reported.
- **`cero_filas` names every workbook** (`"a.xlsm, b.xlsm"`), in processing
  order: with zero rows overall, none contributed. An unreadable file is
  `cero_filas` for that file, as in the other processors.
- **`Excel` is the base name of `nombre_original`** (the script's
  `os.path.basename`).
- **Unknown first-value date shape.** pandas falls back to dateutil per value;
  the module parses each value with the same shapes it knows (year first or
  last, `-`/`/`/`.`, optional time, two-digit years allowed). The samples
  never reach this path.

## Implementation

- **`app/procesadores/flujo_caja_pagos/modulo.py`** — the processor.
  `validar` reads only the header row of each configured sheet (type,
  headers); `procesar` reads, orders, computes both sheets and only then
  writes, so `cero_filas` leaves nothing half-written.
- **`app/core/contrato.py`**, **`app/registry.py`** — contract row and
  registration.
- **`tests/paridad/manifiesto.toml`** — `[flujo_caja_pagos]` with one pair
  (three inputs, one output) and its provenance.

### `.xlsm` validation

No core change was needed:

- The format check is `validar_formato` against the contract row, on the
  extension that `app/recepcion.py::_formato` extracts and lowercases
  (`.XLSM` is accepted).
- There is no magic-byte check; `validar_tamano_descomprimido` reads the ZIP
  central directory, and an `.xlsm` is a ZIP like an `.xlsx`.
- openpyxl reads the macro-enabled workbook part
  (`application/vnd.ms-excel.sheet.macroEnabled.main+xml`) through a file
  descriptor; with a file object it never checks the extension, so the
  extensionless temporary files work. The VBA project is ignored (no
  `keep_vba`), and the output is a plain `.xlsx`.

The tests build synthetic workbooks with that exact package shape
(`vbaProject.bin`, its relationship and the macro-enabled content type).

## Verification

- `tests/test_procesador_flujo_caja_pagos.py` — 71 behaviour tests on
  synthetic macro-enabled workbooks saved as extensionless `entrada_N`: the
  `.xlsm` package and contract/format checks, detection (sheets, shared
  sheets, name fallback, ambiguity, missing sheets), NTFS ordering of five
  mixed-type uploads, `categorizar`, amount cleaning, the class-7 sign rule,
  format inference, `PPP`, empty/unparseable payment dates, the "Por moneda"
  split, the three totals without `Excel` in the grouping, column and row
  order, narrow sheets, header variants and shifts, errors, observations and
  their log line, and HTTP end-to-end across the `spawn` child (two `.xlsm`
  → the `.xlsx` directly, no ZIP; an unknown type → typed 422).
- `tests/paridad/test_flujo_caja_pagos.py` — the real pair compared by content
  with types; the inputs are handed over in reverse order. Skips without
  `FIXTURES_PARIDAD`; run against a copy of the fixtures outside the
  repository: passes.
- **Differential run against the original script**: 30 random batches of five
  synthetic workbooks (both types, missing and empty sheets, narrow sheets,
  blank rows, `NA`/`#N/A`, mixed date shapes and types, trailing `-`, `EUR`
  rows, class `7` as int/float/text) run through the script (pandas 3.0.6)
  and the module: identical output in every batch (header validation
  disabled for the run, since narrow random headers are not real layouts).
- Full suite (754 passed, 25 skipped), `ruff check`, `ruff format --check`
  and `mypy --strict app tests` clean (legacy root scripts excluded via CLI).

### Real-sample parity

| Sheet | Rows (incl. header) | Differing cells |
|---|---|---|
| Soles | 226 | 0 |
| Dolares | 68 | 0 |

No observations: the real sample comes back as `Consolidado_Pagos.xlsx`
alone. Its eight empty sheets (the ones the script reported as "no contiene
datos") are not reported — see below.

**Empty sheets are not reported (user decision).** The first version reported
them as `hoja_sin_filas`, which turned every normal week into a ZIP although
they never change the output: a week without petty cash or payroll is normal
operation, not a loss. A configured sheet that is *missing* is still reported.

### Timings (this machine)

Three workbooks (0.8 MB in total): `validar` 0.9–1.2 s, `procesar` 1.1 s,
peak working set 33 MB. Over HTTP through the `spawn` child: 2.5 s.

## Still open

- **No PEX sample.** The PEX branch is covered by synthetic tests and the
  differential run only.
- **`entradas_max=10`** is a default, not a requirement.
- **Fixtures must be copied to the share** under `flujo_caja_pagos/` with the
  names in the manifest for the parity suite to run there.
