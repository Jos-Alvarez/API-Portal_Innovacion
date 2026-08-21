# Invariantes de arquitectura verificados en CI — BACKLOG item #13

| | |
|---|---|
| **Change** | `invariantes-de-arquitectura` |
| **BACKLOG item** | #13 — depends on #12 |
| **Date** | 2026-08-20 |
| **Commit** | `f57f36c` |
| **Branch** | `item-13/invariantes-de-arquitectura` |
| **Mode** | Fast cycle (exploration → implementation → verification) |

## Summary

Three architecture rules that until now lived only in prose —
`TECH-DESIGN.md:288-298`, the docstrings of `app/registry.py` and
`app/core/pipeline.py` — now fail the build when someone breaks them.

## Exploration

Read `TECH-DESIGN.md`'s "Invariantes de arquitectura" checklist,
`app/registry.py`, `app/main.py`, `app/recepcion.py`, `app/core/pipeline.py`
and the existing AST-based suites used as a style precedent
(`tests/test_seguridad_estructural.py`, `tests/test_salud.py`).

Three findings decided the shape of the work:

1. **The two import rules do not share scope, and that is not an oversight.**
   `TECH-DESIGN.md:291` qualifies the `core.db` rule with "ni directa **ni
   transitivamente**"; `:289` does **not** qualify the `core/` → `procesadores/`
   rule that way. The asymmetry is textual, and `app/registry.py` had already
   recorded the corresponding decision: since item #12,
   `app/core/ejecucion.py` → `app.registry` → `app.procesadores…` is an
   unavoidable transitive edge, because the `spawn` child must find its
   processor in `REGISTRY`. So rule 1 is checked on **direct** imports and
   rule 2 on the **transitive** closure.
2. **`app.core.db` does not exist yet** (item #5 deviated). The rule is
   written anyway and passes vacuously today — which raised the question of
   how to prove the checker has teeth.
3. **One `TECH-DESIGN` checkbox is currently unreachable, and not because of a
   bug.** "Searching for any processor name inside `core/` returns zero
   results" returns results: `app/core/contrato.py` holds `_TABLA_CONTRATOS`
   with the literal keys `passthrough` and `passthrough_multi`, because item #5
   deviated and those rows do not live in SQL Server yet. They are *data*, not
   imports. Left out of the test, with the reason documented.

## Implementation

`tests/test_invariantes_arquitectura.py`, 7 tests:

- `core/` does not import `procesadores/` — direct imports, honouring the
  scope already decided in `app/registry.py`.
- No processor reaches `app.core.db`, directly or transitively — the internal
  import graph is closed with a BFS, resolving relative imports and ancestor
  packages (CPython initializes the parent before the child, so those are real
  edges).
- Every route mounted under `/interno` delegates to `ejecutar_pipeline` and
  calls neither `ejecutar_modulo` nor `empaquetar` on its own.
- Two guards that make the other three non-vacuous: one asserting the module
  map actually contains `core/` and `procesadores/` modules, and one asserting
  at least one route was found.

Two details that cost a red run each:

- **The delegation check looks for a name *reference* (`ast.Name`), not a
  call.** `app/recepcion.py` passes `ejecutar_pipeline` to `run_in_threadpool`
  instead of calling it, so searching for `ast.Call` produced a false negative
  on the only route that exists.
- **FastAPI 0.141.1 interposes a lazy `_IncludedRouter` between the `Mount`
  and the `Route`s.** `mount.routes` returns that wrapper; `mount.app` is the
  middleware, `mount._base_app` the `APIRouter`. None of that is public
  contract. Solved with a generic walker that descends through
  `routes`/`original_router`/`_base_app`/`app`/`router` with `id()` dedup —
  plus the guard test, so that a future version silently returning zero routes
  fails instead of passing.

`test_el_recorrido_transitivo_ve_aristas_indirectas` gives the transitive rule
its teeth against a real edge: `app.core.ejecucion` reaches
`app.procesadores.passthrough.modulo` via `app.registry` without importing it
directly. A checker that can never fail is worth nothing.

## Verification

- 7 new tests; full suite at **343 passing**, 97 % coverage.
- `ruff` and `mypy --strict` clean.
- The transitive rule was additionally sanity-checked out of band by injecting
  a fake `app.registry → app.core.db` edge into a copy of the graph and
  confirming the closure reports it. No repository file was perturbed.

## Notes on CI

This repository has **no CI workflow** and no configured remote. "Verified in
CI" materialises as the pytest suite plus `ruff` and `mypy`, which is the only
gate that exists. Stated explicitly in the test module's docstring so the next
reader does not go looking for a workflow that is not there.
