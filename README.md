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
