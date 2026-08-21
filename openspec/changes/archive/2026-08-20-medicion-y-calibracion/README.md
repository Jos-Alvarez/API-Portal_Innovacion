# Medición y calibración — BACKLOG item #17

| | |
|---|---|
| **Change** | `medicion-y-calibracion` |
| **BACKLOG item** | #17 — depends on #16; last item of the backlog |
| **Date** | 2026-08-20 |
| **Commits** | `c933917` (measurement), `8d96468` (optimization applied) |
| **Branches** | `item-17/medicion-y-calibracion`, `item-17/sacar-fastapi-del-hijo` |
| **Mode** | Fast cycle (exploration → implementation → verification) |

## Summary

The three numbers the PRD and the TECH-DESIGN explicitly left as
**assumptions**, now measured — and the optimization the measurement
uncovered, applied. Full results in `MEDICIONES.md`.

## Exploration

Read the PRD's latency requirement, the TECH-DESIGN's "Riesgos técnicos
abiertos" (three of which are exactly this item's subject),
`app/core/configuracion.py`, and ADR 0021's RAM budget.

Findings:

- **The item's own backlog row says it "requires the instance of prerequisite
  #0"**, which does not exist. So the *final* value of `EJECUCIONES_MAX`
  cannot be chosen here; what can be delivered is a measured footprint plus a
  formula.
- **One TECH-DESIGN claim was already obsolete**: it describes the child
  re-importing "the module tree **with pandas inside**". Item #16 chose
  openpyxl precisely because of this cost.
- **A quick measurement before building anything** put child startup at
  ~795 ms — enough to know the order of magnitude and to justify building a
  proper harness rather than guessing.

## Implementation

- **`tools/medicion.py`** — the harness, four sections: child startup cost,
  end-to-end p95, memory footprint, and degradation under concurrency. New
  convention: `tools/` for development tooling, with `per-file-ignores` for
  `T20`/`S101` in `pyproject.toml`. The wheel packages only `app`, so nothing
  here ships.
- **`tools/hijo_de_huella.py`** — a separate module, run via `subprocess`, that
  measures its own RSS at three moments.
- **`MEDICIONES.md`** — reference run, analysis, and the calibration formula.
- **`tests/test_rendimiento.py`** — the guard.
- **Dev dependencies**: `psutil`, `types-psutil`.

### Measured (before the optimization)

| | |
|---|---|
| Child startup | p50 877 ms · p95 1002 ms |
| p95 end-to-end, real file | 1059 ms (ceiling: 15 s) |
| Child peak memory | 45,7 – 50,9 MB |

**The finding**: ~520 of the ~662 ms of the child's import cost was **FastAPI,
which the child never uses**. For the real file that was ~85 % of total
response time.

### Calibration

`ejecuciones_max` moved from 2 to **4**. The 2 assumed each child reaching ADR
0021's 256 MB budget; measured, a child peaks far below that. Not raised
further because the production instance does not exist and picking 16 would be
calibrating against the development server. The formula is documented in the
code and in `MEDICIONES.md`; **the ceiling is set by cores, not RAM** — the
child is CPU-bound parsing Excel.

A distinction that got written down: the measured peak is **not** ADR 0021's
`PRESUPUESTO_DE_RAM_BYTES`. That one is the *validation* ceiling — what gets
rejected as a ZIP bomb before processing. This one is *observed* consumption.
One bounds what is admitted; the other sizes how many executions fit.

### Optimization applied (`8d96468`)

**Two splits, not one.** Splitting `app/core/errores.py` alone would have
saved nothing: `app/core/ejecucion.py` — the module containing the `spawn`
target, therefore re-imported on every request — imported FastAPI, Starlette
and pydantic-settings on its own account, for the admission half.

| Module | Keeps | Moved out |
|---|---|---|
| `app/core/errores.py` | vocabulary, stdlib only | → `errores_http.py`: status map and handler |
| `app/core/ejecucion.py` | child plumbing, stdlib only | → `admision.py`: semaphore, `admitir()`, middleware, 503 |

No public signature changed shape and no behaviour moved: it is a split of
dependencies, not of contract.

| | Before | After | |
|---|---|---|---|
| Child startup p50 | 877 ms | **428 ms** | −51 % |
| Child import chain | 662 ms | **283 ms** | −57 % |
| p95 end-to-end, real file | 1059 ms | **586 ms** | −45 % |
| Module tree in memory | 26,5 MB | **8,9 MB** | −66 % |
| Child peak | 45,7 MB | **28,0 MB** | −39 % |

The memory saving was not the goal and changed the calibration: the formula's
divisor dropped from 64 to 48 MB per execution.

## Verification

- Full suite **410 passing** + 6 skipped (416 with `FIXTURES_PARIDAD`), 97 %
  coverage; `ruff` and `mypy --strict` clean.
- `tests/test_rendimiento.py` — 2 tests: the PRD's 15 s ceiling on a real
  request, and that `pandas`, `numpy`, `fastapi`, `starlette` and
  `pydantic_settings` stay out of the child's import chain.

**The guard runs in a fresh interpreter, and that is mandatory.** The first
version checked `sys.modules` in-process and went **red** — not because the
split failed, but because `sys.modules` is per-process and other suites in the
same pytest run had already imported FastAPI. It was telling the truth about
pytest and a lie about production. It now uses
`tests/ayudas/subproceso.ejecutar_snippet`, the helper this repository already
had for exactly this class of startup property.

Deliberately, **no test asserts a measured millisecond**: on a shared machine
that is a flaky test waiting its turn, and someone would eventually raise the
threshold until it meant nothing. The numbers live in `MEDICIONES.md` and are
reproduced with the harness.

### Three measurement traps, worth more than the numbers

1. **`spawn` re-imports the parent's `__main__` in the child.** The first
   version measured the module tree at **0.0 MB** — impossible. The re-imported
   `__main__` was the harness itself, which already had everything loaded.
   Hence the measuring process lives in its own module with stdlib-only
   module-level imports, importing the app tree *inside* the function, between
   two readings.
2. **Clearing `obtener_configuracion`'s cache is not enough.**
   `obtener_semaforo` is another `lru_cache` sized **at construction**, so the
   concurrency measurement ate a 503 from the third simultaneous request. It is
   exactly the trap documented by the `limpiar_cache_configuracion` fixture.
3. **`ejecutar_aislado` correctly rejected the measuring child.** Its protocol
   has three closed shapes (ADR 0012) and a raw tuple is a protocol violation.
   The protocol was not widened for a development tool: the harness builds its
   own `Process`/`Pipe`.

The harness also crashed with `UnicodeEncodeError` printing accents to a
cp1252 console — the same failure mode as `Contado_Carga.py`. Fixed inside the
tool with `sys.stdout.reconfigure(encoding="utf-8")`, not by asking whoever
runs it to export `PYTHONIOENCODING`.

## Still open

- **The production instance** (prerequisite #0). This run must be repeated
  there and the formula applied; on a Linux container the startup cost may
  differ substantially.
- **Only one real file exists**, of 31 records. The larger sizes in the tables
  are synthetic.
- **A second real processor would push the child's chain back up.** Every
  module registered in `app/registry.py` is re-imported on every request,
  whether that child uses it or not. It is the price of the registry being a
  literal; the alternative — importing by name inside `core/` — is what ADR
  0012 rules out.
