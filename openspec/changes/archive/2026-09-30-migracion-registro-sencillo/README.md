# Migración de `Registro_Sencillo` — processor `registro-sencillo`

| | |
|---|---|
| **Change** | `migracion-registro-sencillo` |
| **BACKLOG item** | — (fourth real processor, same pattern as `prepago-carga`) |
| **Date** | 2026-09-30 |
| **Commits** | not committed yet |
| **Branch** | `main` (working tree) |
| **Mode** | Fast cycle (exploration → implementation → verification) |

## Summary

`Registro_Sencillo.py` — the 218-line pandas script at the repository root —
becomes `app/procesadores/registro_sencillo/`, registered under the key
`registro-sencillo`, following the `prepago_carga` precedent. One Excel of
toll ("peaje sencillo") transfers between accounts comes in;
`resultado_transferencias.txt` comes out, plus `descartes.txt` only when rows
were discarded. With a clean input the TXT goes out on its own, not in a ZIP.

Verified against the real extract of September 2026 (10 records): the module
reproduces the **historical** TXT the script produced on 2026-09-14 **byte for
byte** (same `sha256`), both on a direct call and over HTTP.

## Exploration

Read all of the script, the real input (every cell and its type) and the
historical output.

Findings that changed the work:

- **It is `Prepago_Carga` with less.** Same header, same date handling, same
  TXT formatting. No Excel output, no commission line, and header text
  `PEAJE SENCILLO` instead of `TRANS ENTRE CUENTAS`.
- **Both detail lines carry IMPORTE SALIDA.** The 50 (outgoing bank) and 40
  (incoming bank) lines use the same amount; IMPORTE ENTRADA is never read.
- **The text in column 25 is a rule, not a constant.** First match wins:
  outgoing bank `1101015005` → `REMESAS IBK 223`, `1101015055` →
  `REMESAS BBVA 332`, then incoming bank `1101015006` → `REMESAS IBK 223`,
  `1101015056` → `REMESAS BBVA 332`, else `TRANSFERENCIA ENTRE CUENTAS`. The
  real extract exercises three branches.
- **The comparison is numeric.** A bank typed as text (`"1101015005"`) never
  matches in pandas and falls to the default text.
- **Dates are text** (`01.09.2026`) and **amounts are integers**, dumped as
  `63000.0` because `limpiar_monto` always returns a float.
- **Three silent discards, one unreachable check** — exactly as in
  `Prepago_Carga`.

## Decisions

Taken with the user before implementation:

1. Key `registro-sencillo`; contract row `CONTRATO_POR_DEFECTO` (one xlsx), in
   `app/registry.py` and `_TABLA_CONTRATOS`.
2. Output as the script names it, plus `descartes.txt` only when there are
   discards and a `registrar_descartes` log line. The module never builds a
   ZIP; `app.core.empaquetado` does when there are two outputs.
3. Columns by name after `strip()`: `BANCO SALIDA`, `BANCO ENTRADA`,
   `FECHA DOCUMENTO`, `FECHA CONTABLE`, `IMPORTE SALIDA`. Missing →
   `columna_faltante`. IMPORTE ENTRADA is **not** required. First sheet.
4. Business rules verbatim, including the quirks above and the year from
   FECHA DOCUMENTO / month from FECHA CONTABLE split.
5. Same hardening as `prepago-carga`: header row and rows with an empty
   BANCO SALIDA filtered before counting; BANCO ENTRADA empty, FECHA
   DOCUMENTO invalid and FECHA CONTABLE invalid reported as discards; no
   swallowed exceptions; zero processed rows or an unreadable workbook →
   `cero_filas`; CRLF and UTF-8 fixed explicitly.
6. **No validation to detect a `prepago-carga` file uploaded by mistake.**
   That extract has the same five columns, so it is processed without error
   (commission ignored). The user chose to cover it with the processor's
   description in the portal; the module docstring records it as a known
   limitation.
7. Self-contained module: no helpers shared with `prepago_carga` or
   `contado_carga`.

## Implementation

- **`app/procesadores/registro_sencillo/modulo.py`** — the processor.
  Descriptor-based `load_workbook(read_only=True, data_only=True)`, because
  temporaries are extensionless. The glosa rule lives in two ordered tables
  (`REGLAS_BANCO_SALIDA`, `REGLAS_BANCO_ENTRADA`).
- **`app/core/contrato.py`**, **`app/registry.py`** — contract row and
  registration.
- **`tests/paridad/manifiesto.toml`** — pair `01` with provenance. Only
  `entrada` and `salida_txt`; the manifest already accepted pairs without an
  Excel output, so it needed no change.

## Verification

- `tests/test_procesador_registro_sencillo.py` — 63 behaviour tests on
  synthetic workbooks saved as extensionless `entrada_0`: the three-line
  layout and separator, all five glosa branches and their precedence, the
  truncated-float and text-bank cases, IMPORTE SALIDA on both lines,
  IMPORTE ENTRADA ignored and not required, the year/month split, TXT
  formatting and CRLF, single output when clean, each discard reason with row
  and value, the log line, every missing column, `cero_filas`, unreadable
  files, and HTTP end-to-end tests across the `spawn` child (clean input
  returns the TXT itself; discards return a ZIP).
- `tests/paridad/test_registro_sencillo.py` — skips without
  `FIXTURES_PARIDAD`; **4 passed** with the pair in place.
- Full suite **614 passing** + 19 skipped; `ruff check`, `ruff format --check`
  (legacy scripts excluded on the command line) and `mypy --strict app tests`
  clean.

### Real-sample parity

| Output | Result |
|---|---|
| TXT | identical, `sha256` `dba10fef…b568ef`, 40 lines, 40 CRLF |
| Discards | none |
| Glosa branches hit | outgoing IBK (5), incoming IBK (4), incoming BBVA (1) |

The original script did not need to be re-run: the historical output and the
module agree exactly.

### Timings (this machine)

Direct call: `validar` 0.02 s, `procesar` 0.01 s. Over HTTP through the
`spawn` child: ~0.3 s per request.

## Still open

- **Pairs 02 and 03.** The PRD requires three.
- **The line ending is observed, not confirmed** (40 CRLF, zero lone LF).
- **A prepago file is accepted silently** (decision 6).
- **The legacy script is kept.** `Registro_Sencillo.py` and
  `Registro_Sencillo_carpeta/` stay untracked at the root until the user
  decides; `ruff` needs `--extend-exclude Registro_Sencillo.py` on the
  command line meanwhile.
- **The script version is inferred.** The manifest's `version_script` is the
  hash of the script handed over with the output, and `generado_el` is the
  output file's modification date.
