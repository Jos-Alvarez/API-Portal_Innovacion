# Tasks: Interfaz `Procesador`, tipos de archivo y registry

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 133–182 (design.md §10) |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single PR |
| Delivery strategy | ask-on-risk |
| Chain strategy | pending |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Low

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | `Procesador` ABC + carriers + empty registry + tests, all in one PR (no file is shared across units, so no split is proposed) | PR 1 | `uv run pytest tests/test_interfaz_procesador.py` | N/A — no route, no call site; not wired into `crear_app()` | Delete `app/core/tipos.py`, `app/core/interfaz.py`, `app/registry.py`, `tests/test_interfaz_procesador.py`; no other file touched |

## Phase 1: Foundation — Carrier Types

- [x] 1.1 Create `app/core/tipos.py` (stdlib-only, `from __future__ import annotations`) with `@dataclass(frozen=True, slots=True) class ArchivoEntrada`: `nombre_original: str`, `ruta_temporal: Path`, `tamano_comprimido: int`, `formato: str`.
- [x] 1.2 In the same file, `@dataclass(frozen=True, slots=True) class ArchivoSalida`: `nombre_propuesto: str`, `ruta_temporal: Path`, `tipo_mime: str`.

## Phase 2: Core Implementation — `Procesador` ABC

- [x] 2.1 Create `app/core/interfaz.py` importing `ABC`/`abstractmethod` from `abc`, `ErrorTipificado` from `app/core/errores.py`, `ArchivoEntrada`/`ArchivoSalida` from `app/core/tipos.py`.
- [x] 2.2 Define `class Procesador(ABC)` with `clave: str` (plain annotation, no `ClassVar`, no default) and the three-note docstring from design.md §5 verbatim: `validar` returns not raises; item #8 child-process caveat; `clave` enforcement-gap note.
- [x] 2.3 Add `@abstractmethod def validar(self, archivos: list[ArchivoEntrada]) -> ErrorTipificado | None` with a one-line docstring.
- [x] 2.4 Add `@abstractmethod def procesar(self, archivos: list[ArchivoEntrada]) -> list[ArchivoSalida]` with a one-line docstring.
- [x] 2.5 Do NOT add: a `clave` enforcement mechanism (`__init_subclass__`, metaclass, `ClassVar`), a `registrar()` helper, or an import-time guard — rejected in design.md §3.

## Phase 3: Registry

- [x] 3.1 Create `app/registry.py` importing `Procesador` from `app/core/interfaz.py`; define `REGISTRY: dict[str, Procesador] = {}`. No processor registered.

## Phase 4: Testing

- [x] 4.1 Create `tests/test_interfaz_procesador.py` with a module-local test-only fake, e.g. `_ProcesadorFalso(Procesador)`, implementing both abstract methods, plus two deliberately incomplete fakes (one missing `validar`, one missing `procesar`) for the abstractness tests.
- [x] 4.2 Test (parametrized): instantiating `Procesador` directly, and each incomplete fake, raises `TypeError`.
- [x] 4.3 Test: `_ProcesadorFalso().validar(...)` called with a one-element and a multi-element `list[ArchivoEntrada]` returns `None` for an accepted set and an `ErrorTipificado` instance (e.g. `ErrorFormato`) for a rejected set, raising nothing in either case.
- [x] 4.4 Test: `_ProcesadorFalso().procesar(...)` called with a one-element and a multi-element `list[ArchivoEntrada]` returns a `list[ArchivoSalida]` of matching length in both cases.
- [x] 4.5 Test: plain pickle round-trip — `pickle.loads(pickle.dumps(x)) == x` for one `ArchivoEntrada` and one `ArchivoSalida` instance holding a `Path` value. No subprocess, no `multiprocessing`.
- [x] 4.6 Test: reassigning an existing field raises `dataclasses.FrozenInstanceError`; setting an undeclared attribute raises `AttributeError` — for both carrier types.
- [x] 4.7 Test: a `_ProcesadorFalso()` instance is assignable into a **local** `dict[str, Procesador]` under a string key and retrievable by it. Never mutate `app.registry.REGISTRY`.
- [x] 4.8 Test: `from app.registry import REGISTRY; assert REGISTRY == {}`.
- [x] 4.9 Test: `import app.core.interfaz` succeeds (no `app/procesadores/` package exists in this repo, satisfying ADR 0011's import-direction requirement by construction).
- [x] 4.10 Test: `Procesador.__doc__` contains the item #8 open-question language (child re-derives the instance vs. receives a pickled live instance), via a substring assertion.
- [x] 4.11 Do NOT add a "shipped route set unchanged" test — already satisfied by `test_rutas_de_produccion_no_cambian` in `tests/test_seguridad_token.py` (item #2); re-verified in Phase 5, not duplicated here.

## Phase 5: Verification

- [x] 5.1 Run `uv run pytest`; confirm the new module plus the full existing suite (including `test_rutas_de_produccion_no_cambian`) pass.
- [x] 5.2 Run `uv run ruff check .` and `uv run ruff format --check .`; fix any finding in the three new production files and the new test file.
- [x] 5.3 Run `uv run mypy app tests`; fix any finding in the three new production files and the new test file.
