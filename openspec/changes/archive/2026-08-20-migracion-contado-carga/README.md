# Migración de `Contado_Carga` — BACKLOG item #16

| | |
|---|---|
| **Change** | `migracion-contado-carga` |
| **BACKLOG item** | #16 — depends on #12 and #15 |
| **Date** | 2026-08-20 |
| **Commits** | `332e274` (migration), `eb3aef9` (real column names + parity) |
| **Branches** | `item-16/migracion-contado-carga`, `item-16/cerrar-puntos-abiertos` |
| **Mode** | Fast cycle (exploration → implementation → verification) |

## Summary

`Contado_Carga.py` — the manual script at the repository root — becomes
`app/procesadores/contado_carga/`, with the five mandatory hardening points
the PRD requires. Verified against a real extract: the migrated module
reproduces the script's TXT **byte for byte**.

## Exploration

Read the 286 lines of `Contado_Carga.py`, plus the PRD's "Endurecimiento
obligatorio" section, the TECH-DESIGN's open risks, `app/core/interfaz.py`,
`tipos.py`, `errores.py`, `contrato.py` and the passthrough module as the
pattern.

Findings that changed the work:

- **There is dead code that contradicts the live code.** `crear_linea_base()`
  is never called, and its `linea1` layout is **shifted by one position**
  relative to the one the live code builds inline — the script's own comment
  says so. Migrating it would have migrated the wrong layout.
  `fecha_ent_str` and `mes_str` are computed and never used.
- **The entry-date column is only a filter.** It is read, parsed and required
  valid — an invalid value discards the row — but its **value enters no output
  line**. Migrating faithfully means keeping it as a mandatory column whose
  only observable effect is discarding rows.
- **There are TWO silent discards, not one.** The PRD names only the unmapped
  plaza. The other one comes first: any of the three dates invalid → a bare
  `continue`, without even a counter.
- **The TXT formatting rule is stranger than it looks.** The dump comes from
  the Python lists, not from the DataFrame, so the types are the original
  ones: an integral `float` above 1e9 loses its decimals, and **any other
  `float` is `str()`'d as is** — an amount of `1234.0` writes literally
  `"1234.0"`. Ledger accounts are `int`, not `float`, so they dodge that
  branch. Easy to "fix" by accident and break parity.
- **No Excel library was in the project.** Neither pandas nor openpyxl, in
  `pyproject.toml` or the venv.
- **The vocabulary was already there.** `ContextoContenido` already carries
  `motivo: Literal["columna_faltante", "cero_filas"]`; item #3 built it *for*
  this item. `errores.py` needed no change. And `app/core/validaciones.py:134`
  names item #16 by number as the owner of failing on a corrupt `.xlsx`.

One product decision was escalated rather than assumed: the service returns
files or a typed error, with no "success with warnings" envelope, so where do
the discards go? **The user chose**: a `descartes.txt` shipped in the ZIP
**only when there are discards**, plus a log line — a clean input keeps the
script's shape (one Excel and one TXT) and parity stays intact.

## Implementation

- **`app/procesadores/contado_carga/modulo.py`** — business rules migrated
  verbatim: the three-line layout plus separator, the ten plazas with their
  exact text, `round(abs(importe), 2)`, and the cell-by-cell TXT rule.
- **Hardening**: columns read by **name** (missing one → `columna_faltante`),
  `FIN_DE_LINEA` fixed explicitly, both discards counted and reported, zero
  processed rows → `cero_filas` raised **before** writing anything, and no
  exception swallowed.
- **`app/core/registro.py`**: `registrar_descartes()`, a third event. Emitted
  from the **child**, which inherits the parent's `stderr` but not its logging
  configuration — hence `configurar_logging()` is called inside `procesar()`,
  never at import, preserving the no-import-side-effect guarantee. Documented
  consequence: that line is not correlated with the route's `ejecucion` line;
  correlating them would require widening ADR 0012's `Pipe` message, which has
  exactly three closed shapes.
- **Dependency: openpyxl, no pandas.** The `spawn` child re-imports the module
  tree on **every** request (ADR 0012), so pandas' ~1–2 s import would be paid
  per request against item #17's 15 s p95 budget, and its ~100 MB against ADR
  0021's 256 MB per child. Parity is unaffected: ADR 0015 compares the TXT
  byte for byte and the Excel by normalized content. `types-openpyxl` went to
  the dev group — openpyxl 3.1.5 ships no `py.typed`.

## Verification

- `tests/test_procesador_contado_carga.py` — 40 tests, 547 lines.
- `tests/paridad/test_contado_carga.py` — 6 tests (skip without
  `FIXTURES_PARIDAD`).
- Full suite **408 passing** + 6 skipped at the time of the commit;
  `ruff` and `mypy --strict` clean.

**An integration bug that no unit test could see.** With all 37 unit tests
green, an end-to-end run through the real route returned **422**.
`openpyxl.load_workbook` validates the **file extension** before reading a
single byte, and `app/recepcion.py` writes temporaries as `entrada_0` — no
extension, on purpose, because the client's name never touches disk (ADR
0020). Every legitimate Excel died with a perfectly-formed, perfectly-wrong
`cero_filas` 422. Every unit test passed the module a path ending in `.xlsx`.
Fixed by opening a descriptor and passing the object; `TestPuntaAPunta` was
added so it cannot come back.

**General lesson for this repository**: every new processor needs a test that
uploads over HTTP and crosses the `spawn` child. The extensionless temporary
is a structural trap only visible there.

## Real-extract validation (`eb3aef9`)

The legacy script was run over a real extract and compared against the module.

**Three of the six column names were wrong**, including one that had been
labelled *confirmed*: the script's comment transcribes `Importe en moneda doc`
**without the trailing period** the real header carries. One character.
Reading by position that was invisible forever; reading by name the execution
dies with `columna_faltante` and nobody processes anything with the wrong
column. It is the best possible vindication of the PRD's hardening.

| Field | Was | Real |
|---|---|---|
| `fecha_documento` | `Fe.documento` | `Fecha de documento` |
| `fecha_entrada` | `Fecha entrada` | `Fecha de entrada` |
| `importe` | `Importe en moneda doc` | `Importe en moneda doc.` |

**Parity verified**: 31 records, **zero discards**, TXT identical byte for
byte (same `sha256`), Excel identical by content. The zero-discard result also
closes, for this pair, the TECH-DESIGN's open risk that byte-for-byte parity
and mandatory hardening might contradict each other.

Pair `01` is registered in `tests/paridad/manifiesto.toml` with full
provenance; the files live outside the repository.

## Still open

- **Pairs 02 and 03.** The PRD requires three.
- **The line ending is observed, not confirmed.** 124 CRLF and zero lone LF in
  the real output, so CRLF is what the consumer has been receiving. Nobody on
  the consuming side has confirmed they *require* it.
- **The expected output of pair 01 was regenerated**, not recovered from the
  consuming system, and with pandas 3.0.5 — almost certainly not the version
  that produced the historical outputs. Recorded in the manifest's provenance
  comment.
