# Chequeo de arranque registry ↔ contratos — BACKLOG item #11

| | |
|---|---|
| **Change** | `chequeo-arranque-registry-contratos` |
| **BACKLOG item** | #11 — depends on #4, #5 |
| **Date** | 2026-08-20 |
| **Commit** | `dc30d02` |
| **Branch** | `item-11/chequeo-arranque-registry-contratos` |
| **Mode** | Fast cycle (exploration → implementation → verification) |

> **This record was reconstructed after the fact**, from the commit and the
> shipped code, not written during the session that produced the work. The
> facts below are verifiable in the tree; the narrative of *how* the decisions
> were reached is inferred from what the code and its docstrings state.

## Summary

The three-situation table from the TECH-DESIGN, implemented at startup: a
registry key with no contract row **fails** the boot naming the key; an
inactive row and an active row with no registry entry only **warn**.

## It was postponed first, and that is the interesting part

This item's number puts it before #12 and #13, but it shipped after both, and
after #14. When its turn first came it was **postponed, not discarded**,
because it had **no observable behaviour to implement**:

- `REGISTRY` and `_TABLA_CONTRATOS` were both empty — nothing to contrast.
- There was no `logging` or `warnings` anywhere in `app/`, and ruff's `T20`
  forbids `print`. The two *warning* rows of the table had no channel to
  reach.
- `ContratoProcesador.activo` was read by nobody.
- The "could not connect" branch was dead by construction: there is no
  database while item #5 stays deviated.
- The asymmetry the TECH-DESIGN justifies — fail for the code, warn for the
  portal's data — evaporates without an admin panel: today both dicts are
  edited by this repository, in the same commit.

Item #12 gave it substrate by populating both dicts; item #14 gave it the
warning channel. Only then was the item worth writing. Postponing it was the
right call and it is recorded here so the ordering does not look accidental.

## Exploration

Inputs: the TECH-DESIGN's three-situation table, `app/core/contrato.py`,
`app/registry.py`, `app/main.py`'s lifespan, and the item #1 rule that a
missing token must always fail first.

Findings:

- **`obtener_contrato` resolves one key; the check needs the opposite** —
  walking every row to find the ones with no registry entry. A per-key
  question cannot answer that.
- **The check belongs in `app/`, not in `app/core/`.** It needs `REGISTRY`,
  and hanging it off the core would add a *second* edge from the core to a
  top-level module. The only existing one (`app/core/ejecucion.py`) was
  granted because the `spawn` child must reach concrete processors; here
  there is no such need.
- **`FastAPI(lifespan=...)` accepts exactly one**, so the check had to be
  composed by wrapping `ciclo_de_vida`, not by editing it: temporaries and the
  sweeper have nothing to do with registry coherence.

## Implementation

- **`app/coherencia.py`** (new) — `contrastar_registry_contra_contratos()` and
  `RegistrySinContrato(RuntimeError)`.
- **`app/core/contrato.py`** — `obtener_tabla_contratos()`, the enumerable
  accessor. It reads the module global on **every call**, so the
  `monkeypatch.setattr(contrato_modulo, "_TABLA_CONTRATOS", ...)` several
  suites already used keeps working.
- **`app/main.py`** — `_arranque` wraps `ciclo_de_vida`, and the check runs
  **inside** the `async with`, never before: `ciclo_de_vida` calls
  `obtener_configuracion()` first, and that precedence is item #1's rule — a
  missing token always fails first, so no other startup problem can mask a
  configuration error. It is also not in `crear_app()`'s body, which would
  make it construction work instead of startup work and would run it even for
  a `TestClient` that never raises the lifespan.

Decisions of this item, recorded in the module docstring following the
repository's post-#10 pattern:

- **An INACTIVE row with no registry entry neither fails nor warns.** The
  design's table says "active row"; warning would turn every retired
  processor into permanent noise.
- **Two deviations written down rather than hidden**: the "could not connect"
  branch is omitted because it would be dead code under `warn_unreachable`
  while item #5 stays deviated; and the original rationale for the
  fail/warn asymmetry is empty today, though the behaviour is implemented
  anyway.

## Verification

- `tests/test_coherencia_arranque.py` — 15 tests, 299 lines.
- Suite at **336 passing** (baseline 321, +15), 97 % coverage;
  `app/coherencia.py` at 100 %. `ruff`, `ruff format` and `mypy --strict`
  clean.

Two traps this item hit, both recorded because they are easy to repeat:

1. **`app.coherencia` does `from app.registry import REGISTRY`, so patching
   `app.registry.REGISTRY` has no effect.** The patch must target
   `app.coherencia.REGISTRY` — patch where it is used, not where it is
   defined.
2. **A bare `TestClient(crear_app())` does not run the lifespan; only
   `with TestClient(...)` does.** The one test that broke was the subprocess
   snippet in `tests/test_registro_operativo.py` (`TestVisibilidad`), which
   substituted the contract table *before* raising the client. The
   substitution moved inside the `with`, matching the rest of that file.
