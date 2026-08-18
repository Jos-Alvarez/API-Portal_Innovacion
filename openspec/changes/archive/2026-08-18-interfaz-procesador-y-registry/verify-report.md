# Verification Report — interfaz-procesador-y-registry

- **Change**: `interfaz-procesador-y-registry` (BACKLOG item #4)
- **Mode**: Full artifacts (proposal, specs, design, tasks) — full verification performed
- **Strict TDD**: Disabled per `openspec/config.yaml`. Absence of structural/AST tests, chaos
  tests, or RED-before-GREEN evidence is NOT reported as a defect, per methodology.

## Completeness — Tasks

All 22 tasks across 5 phases in `tasks.md` are marked `[x]`. Cross-checked against delivered
files; claim confirmed accurate — no unchecked or falsely-checked items found.

| Phase | Tasks | Status |
|---|---|---|
| 1. Foundation — Carrier Types | 1.1–1.2 | Done, matches `app/core/tipos.py` |
| 2. Core — `Procesador` ABC | 2.1–2.5 | Done, matches `app/core/interfaz.py` |
| 3. Registry | 3.1 | Done, matches `app/registry.py` |
| 4. Testing | 4.1–4.11 | Done, matches `tests/test_interfaz_procesador.py` |
| 5. Verification | 5.1–5.3 | Done — re-run independently below, all green |

## Command Evidence (executed independently, real output)

### `python -m uv run pytest`
```
collected 90 items
tests\test_arranque_spawn.py ...                                         [  3%]
tests\test_configuracion_token.py .......                                [ 11%]
tests\test_convenciones_pereza.py .                                      [ 12%]
tests\test_documentacion_contrato.py .......                             [ 20%]
tests\test_errores_tipificados.py ...................                    [ 41%]
tests\test_interfaz_procesador.py ................                       [ 58%]
tests\test_salud.py .....                                                [ 64%]
tests\test_seguridad_access_log.py .                                     [ 65%]
tests\test_seguridad_estructural.py ......                               [ 72%]
tests\test_seguridad_token.py .........................                  [100%]
...
90 passed, 1 warning in 3.73s
```
Coverage: `app/core/interfaz.py` 100%, `app/core/tipos.py` 100%, `app/registry.py` 100%.
16 new tests in `test_interfaz_procesador.py` (matches task 4.1–4.10's plan); 74 pre-existing
tests unaffected (90 = 74 + 16, matches apply-progress's claimed count).

Isolated re-run of `test_rutas_de_produccion_no_cambian` (spec's "Shipped route set unchanged"
scenario): `1 passed, 24 deselected` — confirmed still green. No new duplicate test was added;
correct per spec's explicit instruction not to duplicate it.

### `python -m uv run ruff check .`
```
All checks passed!
```

### `python -m uv run ruff format --check .`
```
39 files already formatted
```

### `python -m uv run mypy app tests`
```
Success: no issues found in 25 source files
```

All four commands exit 0. Task 5.1–5.3's claims are confirmed by independent re-execution, not
merely trusted from apply-progress.

### Repository state
`git diff --stat HEAD -- app/ tests/` → empty (no tracked file under `app/` or `tests/` modified).
`git status --porcelain` → only the four new untracked files (`app/core/interfaz.py`,
`app/core/tipos.py`, `app/registry.py`, `tests/test_interfaz_procesador.py`) plus the
`openspec/changes/...` directory. Confirms "no shipped file modified" and "all work
intentionally uncommitted."
## Spec Compliance Matrix (9 requirements, 11 scenarios)

| Requirement | Scenario | Status | Evidence |
|---|---|---|---|
| `Procesador` ABC matches ADR 0006 verbatim | validar returns instead of raising | PASS | `test_devuelve_error_tipificado_sin_levantar` — asserts `isinstance(resultado, ErrorTipificado)` with no `pytest.raises`, no `try/except` |
| " | validar returns None when valid | PASS | `test_devuelve_none_cuando_es_valido_un_elemento`, `..._varios_elementos` |
| `Procesador` is genuinely abstract | Direct or partial instantiation fails | PASS | `test_instanciacion_directa_o_parcial_falla`, parametrized over `Procesador`, `_ProcesadorSinValidar`, `_ProcesadorSinProcesar`, all `TypeError` |
| Both methods take/return lists unconditionally | One-element and multi-element lists both work | PASS | `TestValidar`/`TestProcesar` each have a 1-element and a multi-element case |
| `ArchivoEntrada`/`ArchivoSalida` frozen, slotted, picklable | Immutable and slotted | PASS (matches corrected scenario) | `TestInmutabilidad` — reassignment raises `FrozenInstanceError`, undeclared attribute raises `TypeError`, matching the spec's amended text, not the original `AttributeError` expectation |
| " | Pickle round-trip preserves equality | PASS | `TestPickle` — both types, `Path`-valued field |
| Concrete `Procesador` instance is registry-compatible | Fake processor populates a typed registry | PASS | `test_instancia_es_asignable_a_dict_local_tipado`; also implicitly `mypy` clean on the same file |
| `app/registry.py` ships a real, empty, typed registry | Registry imports empty | PASS | `test_registry_importa_vacio`; source inspection confirms `REGISTRY: dict[str, Procesador] = {}` |
| `interfaz.py` does not depend on `procesadores/` | interfaz.py imports without procesadores present | PASS | `test_interfaz_importa_sin_procesadores`; `app/procesadores/` does not exist anywhere in the repo (confirmed by search) |
| Docstring records item #8 open question | Docstring states the open question | PASS | `test_docstring_registra_pregunta_abierta_del_item_8`; docstring text present verbatim in `interfaz.py` |
| Shipped application route set is unchanged | Shipped route set unchanged | PASS | `test_rutas_de_produccion_no_cambian` (pre-existing, item #2) re-run in isolation, green — correctly not duplicated |

All 11 scenarios: PASS. All requirements: fully satisfied.

## Correctness Detail

1. **ADR 0006 signature verbatim** — `clave: str` (plain annotation, no `ClassVar`, no default);
   `validar(self, archivos: list[ArchivoEntrada]) -> ErrorTipificado | None`;
   `procesar(self, archivos: list[ArchivoEntrada]) -> list[ArchivoSalida]`. Confirmed by direct
   source read of `app/core/interfaz.py:44-52`, matching spec's Requirement 1 literally.
2. **Genuine abstractness** confirmed both statically (`mypy` clean) and at runtime (`TypeError`
   on direct/partial instantiation, tested).
3. **Carrier dataclasses** — `app/core/tipos.py` defines exactly the four documented fields on
   `ArchivoEntrada` and three on `ArchivoSalida`, both `@dataclass(frozen=True, slots=True)`, no
   extra fields, no methods. Matches spec's field table exactly.
4. **`REGISTRY`** lives in `app/registry.py`, outside `app/core/`, typed `dict[str, Procesador]`,
   empty. `app/registry.py` imports `Procesador` from `app/core/interfaz.py` only.
5. **Import direction** — `app/core/interfaz.py` imports only `abc`, `app/core/errores.py`, and
   `app/core/tipos.py`. No import of `app/procesadores/`, which does not exist in the repo.
6. **Docstring** — contains both the item #8 open-question caveat (verbatim Spanish text about
   the child process re-deriving vs. receiving a pickled instance) and the `clave`
   enforceability-gap note (mypy/`ABCMeta` cannot enforce it, design.md §0 V1/V2 citation).
7. **Not wired into `crear_app()`** — `app/main.py` has only a comment (`# costura #11:
   contrastar_registry_contra_bd(motor, registry)`), not an actual import or call. `git diff
   --stat HEAD -- app/` confirms zero shipped files modified.

## Design Coherence

- ABC-over-Protocol decision (design.md §2) followed exactly: `class Procesador(ABC)`.
- `clave` left as plain annotation with no enforcement machinery (design.md §3) — confirmed no
  `__init_subclass__`, no metaclass, no `ClassVar`, no `registrar()` helper anywhere in the three
  production files. Gap correctly recorded only in the docstring, not solved.
- Module layout (design.md §4) matches: `tipos.py` stdlib-only, `interfaz.py` → `errores.py` +
  `tipos.py`, `registry.py` → `interfaz.py` only. No reverse edges.
- Design's Addendum (mypy/`ClassVar` probe) is documentation only; nothing in the addendum
  required a code change, so there is nothing further to verify against implementation.

## Issues

### CRITICAL
None.

### WARNING
None.

### SUGGESTION

1. **Spec addendum's causal explanation for the `TypeError` is technically imprecise, though the
   observed behaviour and the test are correct.** `spec.md`'s "Immutable and slotted" scenario
   note claims the undeclared-attribute `TypeError` happens "before the frozen `__setattr__` is
   ever consulted" because slots leave no `__dict__`. Independent re-derivation from
   `dataclasses._frozen_get_del_attr` source and a live interpreter probe shows this is not quite
   what happens: the frozen `__setattr__` *is* entered (its `cls` closure variable is stale —
   `_add_slots` rebuilds the class object after `_frozen_get_del_attr` closed over the pre-slots
   one), so `type(self) is cls` is False, the field-name check also misses on an undeclared name,
   and execution falls through to `super(cls, self).__setattr__(...)` — which then raises
   `TypeError: super(type, obj): obj must be an instance or subtype of type` because `self`'s
   actual (slotted) type is not the stale `cls` closed over by `super()`. The end result
   (`TypeError`, not `AttributeError`) that the spec and the tests assert is correct; only the
   *why* in the spec's prose is inaccurate. Non-blocking — no test or code change follows from it,
   but worth a one-line correction next time `spec.md` is touched, so a future reader doesn't
   inherit the wrong mental model.
2. **Delivered 277 lines against a 133–182 forecast** (design.md §10) — the third consecutive
   item in this backlog where the forecast ran short of actual size. Still comfortably under the
   400-line review budget, so this is not a blocker, but recorded for calibration: forecasting is
   under-predicting by roughly 50-90% across three items in a row.

## Verdict

**PASS**

All 22 tasks complete and verified against delivered code. All 9 spec requirements / 11 scenarios
are satisfied with passing covering tests, re-executed independently (not merely trusted). All
four verification commands (`pytest`, `ruff check`, `ruff format --check`, `mypy`) exit 0 with
real output captured above. Design decisions (ABC choice, `clave` non-enforcement, module layout,
import direction) are followed exactly, including the two items explicitly rejected by design
(`registrar()` helper, `clave` enforcement guard) — correctly absent. No shipped file modified,
nothing wired into `crear_app()`. The `clave`-enforcement gap and the forecast-overrun are known,
recorded, and non-blocking. One documentation-accuracy SUGGESTION on the spec's technical
explanation, and one forecast-calibration SUGGESTION — neither blocks archive.
