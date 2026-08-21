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
uv run mypy app tests            # type check
```

## Parity fixtures

Every real processor is validated against **3 real input/output pairs**. Those
files are financial extracts and they do **not** live in this repository (ADR
0015): committing them would leave real amounts and account numbers in Git
history permanently, replicated to every clone and every runner. The
repository stores only `tests/paridad/manifiesto.toml` — filenames, expected
`sha256`, and the **provenance** of each expected output.

Point `FIXTURES_PARIDAD` at the internal share. One subdirectory per
processor, named exactly like the manifest section:

```
$FIXTURES_PARIDAD/contado_carga/01_entrada.xlsx  01_salida.xlsx  01_salida.txt
```

**Nothing runs against parity fixtures today.** `manifiesto.toml` ships a
`[contado_carga]` section with **zero pairs**, on purpose: the processor is
implemented and behaviour-tested (`tests/test_procesador_contado_carga.py`),
but its three real pairs have not been produced yet. Filling in the manifest
is all that `tests/paridad/test_contado_carga.py` needs to start running.

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
