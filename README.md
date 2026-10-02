# API Portal — Servicio de Procesadores

FastAPI service. Item #9 of the Portal de Innovacion master backlog. See
`PRD.md`, `TECH-DESIGN.md`, `BACKLOG.md`, and `adrs/` for the authoritative
design and decisions.

## Running the service

Canonical single-worker invocation:

```
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

`--workers` and Gunicorn are explicitly **forbidden** (ADR 0012 — "Un solo
worker de API"). `EJECUCIONES_MAX` is the service's only concurrency knob;
running more than one Uvicorn worker, or fronting the service with Gunicorn,
breaks that invariant.

**No deployment scaffolding ships in this change.** There is no Dockerfile,
no run script, and no systemd/NSSM service unit in this repository yet. The
deployment target (Linux container vs. native Windows service) is an
unresolved prerequisite tracked in `BACKLOG.md` (prerequisite #0); this
absence is stated here explicitly rather than left implicit.

## Development commands

```
uv sync                          # install dependencies
uv run pytest                    # run the test suite with coverage
uv run ruff check .              # lint
uv run ruff format --check .     # format check
uv run mypy app tests tools      # type check
```

## Measurement and calibration

```
FIXTURES_PARIDAD=<share> uv run python -m tools.medicion --repeticiones 15
```

Measures child-process startup cost, end-to-end p95, the child's memory
footprint, and how latency degrades under concurrency. It is a **tool, not a
test**: the numbers depend on the machine and its load, so nothing in the
suite asserts a measured millisecond. `tests/test_rendimiento.py` guards the
PRD's 15-second ceiling and the absence of heavy imports in the child's
chain — order-of-magnitude regressions, not drift.

Results from the reference run, plus the formula for `EJECUCIONES_MAX` on a
real instance, are in `MEDICIONES.md`.

## Parity fixtures

Every real processor is validated against **3 real input/output pairs**. Those
files are financial extracts and they do **not** live in this repository (ADR
0015): committing them would leave real amounts and account numbers in Git
history permanently, replicated to every clone and every runner. The
repository stores only `tests/paridad/manifiesto.toml` — filenames, expected
`sha256`, and the **provenance** of each expected output.

### Where the fixtures live

**Outside the repository, next to it — never inside it.** The convention is a
sibling folder named after the checkout:

```
T:\API-Portal                     ← this repository
T:\API-Portal_fixtures_paridad    ← the fixtures (real data, not in Git)
```

A folder inside the checkout is one `git add .` away from publishing real
financial data. On a new development machine, copy the fixtures folder next to
the new checkout the same way. The production servers never need it: the
service runs without fixtures, and only the parity suite reads them.

Point `FIXTURES_PARIDAD` at that folder when running the suite:

```
$env:FIXTURES_PARIDAD = "T:\API-Portal_fixtures_paridad"   # PowerShell
uv run pytest tests/paridad
```

Inside it there is one subdirectory per processor, named exactly like its
manifest section, holding the files the manifest lists:

```
$FIXTURES_PARIDAD/prepago_carga/01_entrada.xlsx  01_salida.xlsx  01_salida.txt
```

Keep a backup copy elsewhere (a company share): the folder is the only place
these pairs exist outside the people's own `C:\Automatizacion` folders.

### Pairs per processor

| Manifest section | Pairs | In `T:\API-Portal_fixtures_paridad` |
|---|---|---|
| `contado_carga` | 1 | **no** — stored separately when it was registered |
| `asientos_contables` | 7 (one per card type) | yes |
| `prepago_carga` | 1 | yes |
| `registro_sencillo` | 1 | yes |
| `flujo_caja_ingresos` | 1 | yes |
| `flujo_caja_pagos` | 1 | yes |
| `medios_pago_reportes` | 1 | yes |
| `medios_pago_bbva_hits` | 2 | yes |

The PRD asks for 3 real pairs per processor; most have 1. Every registered
pair passes: the modules reproduce the legacy scripts exactly (TXT byte for
byte, Excel cell by cell).

Read each pair's provenance comment in `manifiesto.toml` before trusting it.
Several expected outputs were **regenerated** by running the legacy script on
the sample inputs, not recovered from the system that consumes them. They
prove the module matches the script as it stands — not that it matches what
the consumer has been receiving historically.

A section declared empty and a section that is missing are **not** the same
thing. Empty means "this processor exists, its pairs are not ready" — that is
absence of fixtures, so it skips locally and fails in CI. Missing means a typo
or a processor whose manifest nobody wrote, and that fails everywhere.

### Adding a pair

Deliberate friction, at the one moment where this kind of test can be
corrupted. A hash proves a file did not change; it does not prove the file is
*correct*. Provenance is what records where the expected output came from, so
that a byte-for-byte failure six months from now is diagnosable.

1. Copy the files to the share, under the processor's directory.
2. Hash every file, plus the exact `.py` that produced the expected output:
   ```
   uv run python -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" <file>
   ```
3. **Observe** the TXT's line ending — do not assume it:
   ```
   uv run python -c "import sys;d=open(sys.argv[1],'rb').read();print('CRLF' if b'\r\n' in d else 'LF')" <file>
   ```
4. Add the `[[<procesador>.pares]]` block to `tests/paridad/manifiesto.toml`
   with all five provenance fields. The commented template in that file is the
   exact shape the validator expects.

Updating an existing fixture means replacing the file **and** updating both
its hash and its provenance, in one reviewable change. A hash that moves while
the provenance stays put is the signature of a reference file tweaked to make
a test pass.

### What fails and what skips

`tests/paridad/manifiesto.py` enforces three severities, and they are not
interchangeable:

| Situation | Local | CI |
|---|---|---|
| Malformed manifest, or a pair with incomplete provenance | **fail** | **fail** |
| Manifest section missing for the processor | **fail** | **fail** |
| `FIXTURES_PARIDAD` pointing inside the repository | **fail** | **fail** |
| Fixture present but `sha256` does not match | **fail** | **fail** |
| Section declared with zero pairs | skip, with a loud warning | **fail** |
| Fixtures absent (variable unset, share not mounted) | skip, with a loud warning | **fail** |

"CI" is detected through the conventional `CI` environment variable, which
GitHub Actions, GitLab CI, CircleCI and Jenkins all set on their own. This
repository has **no CI workflow today** — the gate is `uv run pytest` on a
developer machine — so in practice the skip branch is the one taken. The rule
is in place for the day a runner exists.

## Testing notes

- The service enforces `multiprocessing.set_start_method("spawn", force=True)`
  at package-import time (`app/__init__.py` -> `app/arranque.py`), and enforces
  a fail-closed startup when `TOKEN_SERVICIO` is unset or empty.
- Some tests run a snippet in a **fresh interpreter subprocess**
  (`tests/ayudas/subproceso.py`) because the pytest process's own
  `multiprocessing` state, module cache, and coverage instrumentation would
  otherwise produce a false pass. **Coverage gotcha**: code that only executes
  inside those subprocess tests (`app/arranque.py`, the configuration
  sentinel test, the end-to-end Uvicorn test) is *not* measured by
  `pytest-cov` unless `COVERAGE_PROCESS_START` is wired to propagate coverage
  into the child interpreter. This is harmless today
  (`coverage_threshold: 0` in `openspec/config.yaml`), but it will silently
  understate coverage once a coverage gate is added.
