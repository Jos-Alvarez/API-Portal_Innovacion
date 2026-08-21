# Logging operativo estructurado — BACKLOG item #14

| | |
|---|---|
| **Change** | `logging-operativo-estructurado` |
| **BACKLOG item** | #14 — depends on #10 |
| **Date** | 2026-08-20 |
| **Commit** | `9d8365b` |
| **Mode** | Fast cycle (exploration → implementation → verification) |

> **This record was reconstructed after the fact**, from the commit message and
> the shipped code, not written during the session that produced the work. The
> facts below are verifiable in the tree; the narrative of *how* the decisions
> were reached is inferred from what the code and its docstrings state, and is
> therefore thinner than in the other four READMEs of this batch.

## Summary

Two independent log lines, no shared accumulator: one per execution, emitted
from the reception route, and one per saturation rejection, emitted from the
admission middleware. The item ships **infrastructure**, not just calls to
`logger.info`.

## Exploration

The finding that shaped the item: under the canonical startup documented in
the README (`uv run uvicorn app.main:app`), a `logging.getLogger("app…").info(...)`
call emits **nothing**. Verified against this environment — uvicorn's
`LOGGING_CONFIG` configures only `uvicorn`, `uvicorn.error` and
`uvicorn.access`; it adds no handler to the root logger and sets no root
level. An `app.*` logger therefore inherits WARNING from an empty root, and
`logging.lastResort` (also WARNING) does not catch INFO either.

Consequence: without an explicit configuration entry point the whole item
would have been a silent no-op in production, while passing any test based on
`caplog` — which lowers the root level and so lies about production.

Second constraint found: `app/core/ejecucion.py` is re-imported by every
`spawn` child (ADR 0012) and guarantees no import side effects. Any logging
module hanging off that chain must not configure logging at import time.

## Implementation

- **`app/core/registro.py`** (new): `FormateadorJsonLineas` (one JSON object
  per line, incorporating `extra=` fields, `default=str` so an unserializable
  value degrades the line instead of breaking emission), `configurar_logging()`
  (idempotent by replacement, not accumulation — `crear_app()` runs once per
  test in several suites), `ResultadoDeEjecucion` (a `StrEnum` describing how
  the *request* ended, deliberately not reusing `Desenlace`, which classifies
  the child's lifecycle), `registrar_ejecucion()` and `registrar_saturacion()`.
- **`app/recepcion.py`**: the route body wrapped in `try/except/finally`. Every
  `except` re-raises — the handlers registered in `crear_app()` remain the only
  constructors of responses, so no logging branch can change a status code. The
  `finally` emits exactly one line per request that entered the body.
- **`app/core/ejecucion.py`**: the saturation line emitted from
  `AdmisionDeBorde.__call__`, not from `admitir()` — the context manager is
  generic and unit tests invoke it with no HTTP scope in hand.
- **`app/main.py`**: `configurar_logging()` called explicitly from `crear_app()`,
  never at module import, to preserve the no-import-side-effect guarantee of
  the chain the child re-imports.

Two safety properties held by construction: untrusted text (the request path
and the key carved out of it) is sanitized against log-line forging, and the
service token never appears in any signature of the module.

## Verification

- `tests/test_registro_operativo.py` — 15 tests, 647 lines.
- Coverage of `app/core/registro.py`: 100 %.
- `ruff` and `mypy --strict` clean.
- The commit modified five files and none of them were the pre-existing
  structural security tests. That matters:
  `tests/test_seguridad_estructural.py` scans **every** module under `app/`
  (`test_get_secret_value_un_solo_sitio`), so a new module joining `app/`
  is subject to it without anyone opting in. That is what keeps the "the
  token never reaches the log" claim honest rather than asserted.

## Later corrections

Item #17 moved the saturation half to `app/core/admision.py`, so
`registro.py`'s docstring was updated: the emitter of the saturation line is
no longer `app.core.ejecucion`. Item #16 added a third caller,
`registrar_descartes()`, emitted from inside the `spawn` child.
