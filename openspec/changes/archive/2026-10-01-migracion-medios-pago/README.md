# Migración de los procesadores de medios de pago — `medios-pago-reportes` and `medios-pago-bbva-hits`

| | |
|---|---|
| **Change** | `migracion-medios-pago` |
| **BACKLOG item** | — (same pattern as `flujo-caja-pagos`) |
| **Date** | 2026-10-01 |
| **Commits** | not committed yet |
| **Branch** | `main` (working tree) |
| **Mode** | Fast cycle (exploration → implementation → verification) |

## Summary

Two pandas scripts at the repository root become one package,
`app/procesadores/medios_pago/`, with two processors (two portal windows):

- `Procesador_MediosPago_Reportes.py` (240 lines) → **`medios-pago-reportes`**
  (`reportes.py`). Splits the raw Izipay reports (Mastercard `mc…`, AMEX
  `movi_amex…`, Diners `servicios…`, CSV) by payment date and by
  `Codigo == 4010761` into `{date}-{type}.csv` / `{date}-{type}-izipay.csv`,
  shifting AMEX dates past weekends and Peruvian holidays, and the SafetyPay
  `MPFinancialReport*.xlsx` into one `{date}-SafetyPay.xlsx` per settlement
  date.
- `Procesador_BBVA_Hits.py` (514 lines) → **`medios-pago-bbva-hits`**
  (`bbva_hits.py`). Categorizes the BBVA statement (`bbva.csv_`), optionally
  merged with the previous master `Abonos_BBVA.xlsx`, cross-matches it in two
  passes against the split Izipay CSVs, and writes
  `Abonos_BBVA_CATEGORIZADO.xlsx` plus one `HIST-{date}-….xlsx` per date and
  category.

The split logic is shared (`izipay.py`): the BBVA window splits the raw
Izipay CSVs it receives with the same code to build its cross-matching set.
Content detection lives in `deteccion.py`, the pandas emulation helpers,
NTFS order, xlsx writing and `observaciones.txt` in `comun.py`.

Verified against the real May 2025 samples: **all 99 Reportes outputs and all
119 BBVA outputs are identical** to the outputs of the original scripts
re-run today (CSV byte for byte, xlsx cell by cell with types, number formats
and header style), and the module also reproduces the 37 **historical** BBVA
outputs exactly.

## Exploration

Read both scripts and the samples (`Medio de pago_carpeta/`, not copied into
the repository). The `Salida` folders are not outputs of these inputs, so the
originals were re-run on copies of the inputs in a scratch directory,
patching only the paths and the final `input()`, with pandas 2.2.3 and with
pandas 3.0.6.

Findings that changed the work:

- **The holiday bug did not exist.** `holidays.PE(years=[2024, 2025])` has
  `expand=True` by default: asking about a 2026 date populates 2026. The
  script already used each date's own year. The module keeps that behaviour
  explicitly with `holidays.country_holidays("PE")`.
- **pandas 3 dropped the header style of `to_excel`** (bold, thin border,
  centered). The historical BBVA outputs have it, so the user runs pandas 2.
  Content is identical under both versions; the expected outputs were
  regenerated with **pandas 2.2.3** and the module emulates pandas 2.
- **The historical BBVA outputs are reproducible.** Re-running the BBVA
  script with the historical Reportes `Salida` (September/October 2025
  partitions) as the cross folder reproduces the historical CATEGORIZADO and
  the 36 SP/VISA `HIST` files exactly: no May row matched. That run is
  equivalent to a run with no Izipay reports, which became parity pair 02.
- **`read_csv` infers dtypes per 32768-row chunk** (`low_memory=True`); the
  7 MB Mastercard sample spans two chunks. Replicated
  (`izipay._filas_por_tramo`, `_inferir_columna`).
- **`to_csv` rewrites numbers**: `14.00` → `14.0`, an integer column with
  blanks → `4196.0`. The BBVA cross reads those CSVs back with
  `read_csv(dtype=str)`, so it sees the rendered text; the module computes the
  cross from the rendered text too.
- **`F. Valor` is text in the output** (with a date number format):
  `aplicar_formato_fechas_excel` parses it with `'%Y-%m-%d'` after it was
  already reformatted to `'%d/%m/%Y'`. `F. Operación` is a real date.
- **The `%#d` Windows-only format is not observable**: the intermediate
  `F. Operación` text is parsed back with `dayfirst=True`.
- **Mastercard rows without a payment date** (12 in the sample) are pending
  charges, normal operation.

## Decisions

Taken with the user before implementation:

1. Two portal windows, one package: keys `medios-pago-reportes` and
   `medios-pago-bbva-hits`, two classes in `app/procesadores/medios_pago/`.
   No architecture invariant forbids it (the invariants are about imports).
2. `medios-pago-reportes`: 1–10 files, formats `csv`, `xlsx`, any combination;
   several reports of the same Izipay type accumulate as in the script.
3. `medios-pago-bbva-hits`: exactly one statement, zero or more raw Izipay
   CSVs, optionally one master; 1–10 files, formats `csv_`, `csv`, `xlsx`.
   The cross set is only what is uploaded (documented limitation, below).
4. File type detected by content; the file name is only a fallback. Unknown →
   `tipo_no_reconocido`; two statements or two masters → `tipo_duplicado`.
5. Holidays from the `holidays` package (runtime dependency), imported lazily.
6. Hardening as in previous migrations (no swallowed exceptions, silent losses
   in `observaciones.txt`, zero rows → `cero_filas`).
7. Business rules verbatim.

Taken during implementation, and documented in the modules:

- **Detection** (`deteccion.py`). Izipay CSV = header with `Codigo` and a
  payment-date column; type by the columns only one sample has
  (`Comision_Merchant` without `Fecha_Abono_8Dig` → AMEX, `Comision_Afecta`
  → Mastercard, neither with `Fecha_Abono_8Dig` → Diners); both → the
  script's name rule (`mc`, `amex`, `servicios`). SafetyPay = `Merchant
  Settlement Date` in row 7. Master = `F. Operación` (or `F. Operación_dt`),
  `Importe` and `Concepto` in row 1. Statement = first line `00,` or any
  line starting with `22,`; name `bbva` as fallback. A missing column the
  script read is `columna_faltante`.
- **One SafetyPay per Reportes run**: the script processed only the first
  `MPFinancialReport` and silently ignored the rest; a second one is
  `tipo_duplicado`.
- **SafetyPay in the BBVA window is accepted and ignored** (the script's cross
  only read Mastercard/AMEX/Diners CSVs), so the same batch can be uploaded to
  both windows. A statement or master in the Reportes window is
  `tipo_no_reconocido`.
- **No statement** in the BBVA window is `cero_filas` naming every file; a
  statement whose rows are all filtered out is `cero_filas` too (the script
  wrote an empty CATEGORIZADO).
- **Order.** Raw files in NTFS order of their base names (the script's
  `os.listdir`; same rule as `flujo-caja-pagos`), ties in upload order. The
  cross iterates the generated partitions in NTFS order of their names.
- **Outputs are flat**: the CATEGORIZADO is not in a `BBVA/` subfolder.
- **The master is not deleted** (the script removed `Abonos_BBVA.xlsx`).
- **Observations** (`archivo`, `fila`, `motivo`, `valor`, CRLF, UTF-8), only
  for rows that reach the output: `linea_invalida` (a line with more fields
  than the header — `read_csv` failed and the script skipped the whole file —
  or a `22` line with more than 11 fields; dropped), `fecha_invalida` (a
  written payment/settlement date that does not parse, or a statement line
  with an unreadable or blank operation date: no `HIST`, no cross — the script
  crashed naming its `HIST`), `codigo_invalido` (a non-numeric `Codigo`: the
  script lost the rest of the file; the row is dropped), `importe_invalido`
  (statement amount, or an Izipay `Neto_Total` that cannot cross),
  `numero_invalido` (`Nº. Doc.`, `Oficina`, `Código` written but not numeric:
  they become 0), `columna_ausente` (an Izipay report without `Neto_Total`
  cannot cross). Blank Izipay dates are not reported.
- **A non-UTF-8 Izipay CSV** is `cero_filas` (the script skipped it with a
  print).
- **Empty `Concepto` is written `NAN`** (pandas 2 `astype(str).str.upper()`).

### Rules not migrated verbatim

Only the hardening above: dropped-and-reported lines/rows instead of skipped
files or crashes, one SafetyPay per run, `cero_filas` instead of an empty
CATEGORIZADO, the master not deleted, flat outputs. Everything else —
filters, keyword and code lists, categorization order, the cumcount matching,
`IZI`/`ANTIGUO`, the Monday shift, last-write-wins `HIST` files, file names,
column orders, date formats, `startrow=4`, the SafetyPay swap and numpy
rounding — is the script's.

### Cross-matching set (limitation)

The script crossed against the whole Reportes `Salida` folder, which grew run
after run. The module crosses only against the raw Izipay reports uploaded in
the same BBVA run: a deposit whose report was not uploaded stays without an
Izipay category. Upload every report of the period (and of the previous
working day for the second pass).

## Implementation

- **`app/procesadores/medios_pago/`** — `__init__.py`, `comun.py`,
  `izipay.py`, `deteccion.py`, `reportes.py`, `bbva_hits.py`.
- **`app/core/contrato.py`**, **`app/registry.py`** — two contract rows and
  two registrations.
- **`pyproject.toml`**, **`uv.lock`** — `holidays>=0.105` (adds
  `python-dateutil` and `six`).
- **`tests/test_rendimiento.py`** — `holidays` added to the modules the
  `spawn` child must not import at startup.
- **`tests/paridad/manifiesto.toml`** — `[medios_pago_reportes]` (one pair)
  and `[medios_pago_bbva_hits]` (two pairs). Expected outputs travel as one
  ZIP per pair (99 and 119 files); the tests compare file by file.

### pandas emulation

No pandas (the `spawn` child would re-import it on every request). Reproduced
and verified against pandas 2.2.3 and 3.0.6: `read_csv` NA strings, chunked
dtype inference and the chunk-merge rules, `Unnamed`/duplicate column names,
`to_csv` rendering (float `repr`, minimal quoting, CRLF), `pd.concat` column
union and dtype promotion, `read_excel`'s openpyxl reader (trailing empty
cells/rows, `header=6`, numeric strings converted by the Python parser,
`dtype=str` columns), `to_datetime` format inference (including SafetyPay's
`"Monday, 26 May 2025 00:00:00"`), `to_numeric`, numpy `round(2)`
(`rint(x*100)/100`, not Python's `round`), `groupby().cumcount()` with NaN
keys excluded, and `to_excel` cell formats and header style.

### `csv_` validation

No core change was needed. `app/recepcion.py::_formato` takes what follows
the last dot and lowercases it (`bbva.csv_` and `BBVA.CSV_` → `csv_`);
`validar_formato` compares strings against the contract row; a text file is
not a ZIP, so `validar_tamano_descomprimido` is a no-op. Covered by
`test_el_formato_csv_guion_bajo_lo_acepta_el_nucleo_sin_cambios` and by the
HTTP test that uploads `bbva.csv_` and `BBVA2.CSV_`.

### Holidays: package vs table

The package was kept: a hand-written table would have to track when each
Peruvian holiday was introduced (August 6 and December 9 since 2022, July 23
since 2023, June 7 since 2024, per `holidays` 0.105) and future changes. Measured in a fresh interpreter: the `spawn`
child starts in 0.37 s; importing `holidays` and building one year adds
**0.30 s** (0.17 s import + 0.25 s build cold). Not negligible, so it is
imported inside `procesar`, only when an AMEX report is present.

## Verification

- `tests/test_procesador_medios_pago_reportes.py` — 37 behaviour tests:
  detection by content and name fallback, unknown/duplicate/unreadable
  inputs, split by date and code, `to_csv` rendering, integer columns,
  8-digit extraction, NTFS accumulation with dtype promotion, AMEX shift
  (weekend, 2025 and 2026 holidays, Easter 2026, a year crossing into a
  holiday on 1 January 2029), observations, `cero_filas`, chunked inference,
  numpy rounding, SafetyPay grouping/columns/header style/bad dates/real
  dates/missing column, HTTP end-to-end through the `spawn` child.
- `tests/test_procesador_medios_pago_bbva_hits.py` — 49 behaviour tests:
  contract and `csv_`, batch composition, parsing, filters, categorization
  order, `NAN`, both cross passes (cumcount duplicates, Monday shift, first
  match wins in pass 1, last in pass 2, re-categorization of a VISA row,
  the CSV round trip of `Neto_Total`), master dedupe and order, `HIST` naming,
  row 5 headers, SAFETYPAY swap, VISA last-write-wins, observations, HTTP
  end-to-end.
- `tests/paridad/test_medios_pago_reportes.py`,
  `tests/paridad/test_medios_pago_bbva_hits.py` — skip without
  `FIXTURES_PARIDAD`; run against the fixtures outside the repository: pass.
- **Differential run against the original scripts** (pandas 2.2.3): 60 random
  batches (one or two reports per Izipay type with random NTFS-sensitive
  names, optional extra columns, blank and integer columns, quoted fields,
  dates around year end and 2025–2027 holidays, optional SafetyPay with bad
  dates, a statement with matching and shifted amounts, `ITF`, keywords,
  codes, empty concepts and bad dates, optional master in 12 of them):
  3,491 output files compared (392 of them MC/DN/AMEX `HIST` files from
  cross matches), all identical. The only differences were the intended
  deviations: `observaciones.txt` exists only in the module's output, and in
  two batches every statement row was filtered out, so the module raises
  `cero_filas` where the script wrote an empty CATEGORIZADO.
- Full suite, `ruff check`, `ruff format --check` and `mypy --strict app tests`
  clean (legacy root scripts excluded via CLI).

### Real-sample parity

| Window | Outputs | Differing files |
|---|---|---|
| `medios-pago-reportes` (regenerated) | 80 CSV + 19 SafetyPay | 0 |
| `medios-pago-bbva-hits` pair 01 (regenerated) | CATEGORIZADO (711 rows) + 118 HIST | 0 |
| `medios-pago-bbva-hits` pair 02 (historical) | CATEGORIZADO + 36 HIST | 0 |

No observations on the samples.

### Timings (this machine)

Real samples (7.8 MB): Reportes `validar` 0.18 s, `procesar` 3.4 s; BBVA
`validar` 0.05 s, `procesar` 3.2 s; peak working set ~103 MB in both (the
7 MB Mastercard CSV). Over HTTP through the `spawn` child: 5.2 s each.

## Still open

- **Fixtures must be copied to the share** under `medios_pago_reportes/` and
  `medios_pago_bbva_hits/` with the names in the manifest.
- **Size caps** stay at the default (25 MB per file and per batch). A month of
  Mastercard reports is ~7 MB; several months in one batch would hit the cap.
- **Detection columns** come from one sample of each report; a format change
  would show up as `tipo_no_reconocido`, not as a wrong split.
- **`entradas_max=10`** is a default, not a requirement.
