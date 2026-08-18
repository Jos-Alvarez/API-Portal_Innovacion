# Design: Interfaz `Procesador`, tipos de archivo y registry

- **Change**: `interfaz-procesador-y-registry` (BACKLOG item #4)
- **Inputs**: `proposal.md` (**authoritative**, especially its four numbered Decisions),
  `exploration.md`, inherited `L:\App_Portal\adrs\0006`, local `adrs/0011`, `adrs/0012`,
  `app/core/errores.py`, `TECH-DESIGN.md`, `openspec/config.yaml`, item #3's archived `design.md`
- **Authority**: ADRs outrank every other document. Inherited ADR 0006 fixes the ABC signature
  verbatim and outranks local ADRs. **This change authors no ADR** (proposal, Decision 4).
- **Methodology**: Strict TDD is **disabled**. No structural/AST tests, no chaos tests, no
  deliberate-RED procedure, no assertion machinery. Behavioural tests, `ruff` and `mypy --strict`
  still run. The full SDD chain still runs.
- **Size note**: deliberately shorter than item #3's design, which was shorter than #1's and #2's.
  This change is an ABC, two dataclasses and an empty typed dict. Nothing here is subtle; padding it
  would be a disservice. Sections with nothing to decide say so in one line.

## 0. Verified facts this design rests on

**No `Bash` tool was available this session, so nothing was executed.** Every claim below was read
in installed source: the pinned venv at `L:\API-Portal\.venv\Lib\site-packages` and the CPython
**3.12.0** stdlib at `C:\Python312\Lib` (`\.venv\pyvenv.cfg`). `uv run` is the only acceptable
interpreter for re-checking any of it — bare `python` is a different environment (item #2's design).
The proposal's pickle claim was *additionally* verified by execution during `explore`; §0 re-derives
it from source so it rests on two independent checks.

| # | Claim | Evidence |
|---|---|---|
| V1 | **On a plain `ABC`, an annotation-only member is never an abstract attribute for mypy.** `Var.is_abstract_var` is set only inside a `Protocol` body; `calculate_class_abstract_status` promotes a `Var` to `abstract_attributes` only when that flag is set. So `clave: str` on an ABC produces **no** mypy error when a subclass omits it, and none at instantiation. | `mypy/semanal.py:3927-3941`; `mypy/semanal_classprop.py:87-92` |
| V2 | **ABCMeta cannot enforce it either.** `__abstractmethods__` is built from *namespace values* carrying `__isabstractmethod__`. A bare annotation puts no value in the class namespace, so there is nothing to inspect. The two `@abstractmethod` methods *are* enforced. | `C:\Python312\Lib\_py_abc.py:35-46` |
| V3 | **A `Protocol` would enforce `clave`.** Same two sites, positive branch: an annotated-only Protocol member becomes an abstract attribute, so a class that omits it fails at the point it is typed as a `Procesador`. | V1's sites |
| V4 | **A `frozen=True, slots=True` dataclass is picklable.** `_add_slots` installs `_dataclass_getstate`/`_dataclass_setstate` when `is_frozen`, which is exactly the case that would otherwise fail. | `C:\Python312\Lib\dataclasses.py:1155-1166, 1228-1233` |
| V5 | **`pathlib.Path` pickles and round-trips to its own concrete class.** `PurePath.__reduce__` returns `(self.__class__, self.parts)`. | `C:\Python312\Lib\pathlib.py:353-356` |
| V6 | **A subclass writing `clave = "falso"` against a base `clave: str` raises no ClassVar-override error.** Both mypy branches are guarded by `is_classvar`; with neither side a `ClassVar`, the check returns `True` unconditionally. | `mypy/checker.py:3886-3897` |
| V7 | **The shipped route set is already pinned by a green test** against a literal five-entry set, and `include_router` does not flatten routes (item #2's correction, item #3's V6/V7). | `tests/test_seguridad_token.py` — `test_rutas_de_produccion_no_cambian` |
| V8 | Environment: `.venv` is CPython 3.12.0; `pyproject.toml` sets `requires-python >=3.11`, `mypy.strict = true`, `python_version = "3.11"`, `ruff line-length = 100`. | `.venv/pyvenv.cfg`; `pyproject.toml:7,30-52` |

**Deliberately not asserted**: how mypy treats a `ClassVar` base declaration overridden by an
unannotated subclass assignment. §3 rejects `ClassVar` on contract grounds and never depends on it.

## 1. Technical approach

Three new production modules, no shipped file touched, nothing wired into `crear_app()` — exactly
items #1–#3's shape. `app/core/tipos.py` holds the two carriers, `app/core/interfaz.py` holds the
ABC alone, `app/registry.py` holds the empty typed registry. One test module proves the behaviour
with a test-only fake processor.

## 2. Decision — `ABC`, not `Protocol`

| Option | Enforces the two methods | Enforces `clave` | Matches ADR 0006 |
|---|---|---|---|
| `Protocol` (structural) | Statically, at the point of use | **Yes** (V3) | **No** — ADR 0006 writes `class Procesador(ABC)` literally |
| **`ABC` + `@abstractmethod`** | Statically **and** at instantiation (V2) | No (V1/V2) | **Yes**, verbatim |

**Chosen: `ABC`.** ADR 0006 is inherited and outranks a local stylistic preference; ADR 0011's file
tree independently names `interfaz.py  # ABC Procesador`. Beyond authority, the nominal base is what
ADR 0006's own reasoning assumes — it calls `Procesador` "la costura que permite extraer un
procesador a su propio servicio", a seam concrete modules inherit from and declare. `ABC` also buys
runtime enforcement of the two methods, which is the failure that actually threatens items #12/#16;
`Protocol`'s only extra coverage is `clave`, and §3 closes that elsewhere. Switching to `Protocol`
would contradict an inherited ADR and therefore require an ADR of its own — which the proposal
explicitly declined to write.

## 3. Decision — `clave` stays a plain annotation, and the gap is recorded

| Form | mypy catches an omitting subclass | Runtime catches it | Changes ADR 0006's contract |
|---|---|---|---|
| **`clave: str`** (ADR 0006 verbatim) | No (V1) | No (V2) | **No** |
| `clave: ClassVar[str]` | No (V1 — the flag is protocol-only, `ClassVar` is irrelevant to it) | No (V2) | Yes — forbids per-instance assignment, and buys **zero** enforcement in exchange |
| `@property @abstractmethod def clave` | Yes | Yes | Yes — a data attribute becomes a method-shaped member; every processor writes three lines instead of `clave = "passthrough"` |
| `__init_subclass__` guard | No | Yes, at import time | No, but it false-positives on any intermediate abstract base that legitimately defers `clave` |

**Chosen: `clave: str`, verbatim.** Item #3 used `ClassVar[TipoError]` for `tipo` because there it
named something true and useful in a hierarchy this repo owns end to end. Here the same shape buys
nothing measurable (V1: the enforcement is identical either way) and narrows an inherited contract.
The abstract property does enforce — and is the one thing this change is not allowed to do, because
it re-shapes the ADR-fixed signature.

**The gap, recorded not solved.** A `Procesador` subclass that forgets `clave` type-checks and
instantiates; it fails as `AttributeError` the first time anything reads `p.clave`. This design
closes it with a docstring line (§5), not machinery. Two related notes for later items:

- The registry key and `p.clave` are **two sources of one truth** — ADR 0006's own literal shows
  `{"maestro-excel": MaestroExcel()}`. Whoever registers the first real processor (#12/#16) should
  add `all(k == p.clave for k, p in REGISTRY.items())` as a test. It cannot be written today against
  an empty dict, and a `registrar()` helper is rejected: ADR 0006 shows a dict literal, and the
  helper would only pre-check what that assertion already covers.
- No `registrar()` helper, no import-time guard, in this change.

## 4. Module layout and import direction

Arrows point at what a module imports. Nothing under `core/` points outward, so ADR 0011's
invariant — *"`core/` no sabe que `procesadores/` existe"* — holds by construction, not by
discipline. `registry.py` is the join point and is deliberately outside `core/`, exactly where
ADR 0011's tree and `TECH-DESIGN.md` place it. Item #13's CI check encodes this placement.

```
app/core/tipos.py      (stdlib only: dataclasses, pathlib)
        ▲
        │
app/core/interfaz.py ──► app/core/errores.py      (ErrorTipificado, item #3)
        ▲
        │
app/registry.py                                   (later also ──► app/procesadores/*)
```

**No sequence diagram.** `openspec/config.yaml` asks for one on *complex flows*. This change has no
flow: it is a base class and two records, with no call site anywhere in the repository yet.

## 5. Interfaces

```python
# app/core/tipos.py  (illustrative)
@dataclass(frozen=True, slots=True)
class ArchivoEntrada:
    nombre_original: str
    ruta_temporal: Path
    tamano_comprimido: int
    formato: str


@dataclass(frozen=True, slots=True)
class ArchivoSalida:
    nombre_propuesto: str
    ruta_temporal: Path
    tipo_mime: str
```

Both carry only `str`/`int`/`Path`: picklable (V4, V5) and free of file handles, sockets or any
other unserialisable state, which is the standing requirement of ADR 0012. `from __future__ import
annotations` per `errores.py`'s house style.

```python
# app/core/interfaz.py  (illustrative)
class Procesador(ABC):
    """Interfaz común de los módulos de procesamiento (ADR 0006, verbatim).

    `validar` DEVUELVE el error tipificado; no lo levanta. Quien lo levanta es
    el pipeline (ítem #10), para que el manejador del ítem #3 lo serialice.
    Ambos métodos trabajan siempre con listas: un solo camino de código, sin
    ramas por cardinalidad (ADR 0006).

    CAVEAT ABIERTO — ítem #8, `core/ejecucion.py`: ningún documento define si el
    proceso hijo re-deriva la instancia (re-import más búsqueda en el registry)
    o recibe una instancia serializada. Lo que sí está fijado es que solo cruzan
    rutas y escalares, nunca bytes de archivo (ADR 0012). Quien implemente
    `core/ejecucion.py` decide esto y actualiza esta nota.

    `clave` es una anotación sin valor: ni mypy ni ABCMeta obligan a la subclase
    a definirla (design.md §0, V1/V2). Cada procesador DEBE fijarla y su valor
    DEBE coincidir con su llave en `REGISTRY`.
    """

    clave: str

    @abstractmethod
    def validar(self, archivos: list[ArchivoEntrada]) -> ErrorTipificado | None:
        """Valida el conjunto (cantidad, formato, tamaño, contenido); None si es válido."""

    @abstractmethod
    def procesar(self, archivos: list[ArchivoEntrada]) -> list[ArchivoSalida]:
        """Ejecuta la transformación y devuelve uno o más archivos resultantes."""
```

```python
# app/registry.py  (illustrative)
REGISTRY: dict[str, Procesador] = {}
```

Real, typed and empty: no concrete processor exists until items #12/#16. `registry.py` imports
`Procesador` from `core/` and nothing else today.

## 6. Testing strategy

One new module, `tests/test_interfaz_procesador.py`. Behavioural only.

| Layer | What to test | Approach |
|---|---|---|
| Unit | `Procesador` cannot be instantiated; neither can a fake missing `validar`, nor one missing `procesar` | `pytest.raises(TypeError)` on the three, parametrised |
| Unit | A complete fake honours list-in / list-out | `procesar([entrada])` returns a `list[ArchivoSalida]`; assert length and element type |
| Unit | `validar` **returns** the error, never raises | Fake returns `ErrorFormato(...)`; assert `isinstance(resultado, ErrorTipificado)` with no `pytest.raises` around it, and that the valid case returns `None` |
| Unit | Both carriers cross the process boundary | `assert pickle.loads(pickle.dumps(x)) == x` for one `ArchivoEntrada` and one `ArchivoSalida`. **A plain round-trip assertion — no subprocess, no `multiprocessing`, no fixtures.** The fake processor itself is not pickled, so it needs no module-scope home |
| Unit | The carriers are frozen | `pytest.raises(dataclasses.FrozenInstanceError)` on one attribute assignment |
| Unit | The shipped registry is real and empty, and accepts a `Procesador` | `assert REGISTRY == {}`; the fake goes into a **local** `dict[str, Procesador]`, never into `app.registry.REGISTRY` — mutating a module global leaks across tests |
| Static | Whole change | `uv run ruff check . && uv run ruff format --check . && uv run mypy app tests` |

**No route-set test.** V7: `test_rutas_de_produccion_no_cambian` already pins `crear_app()` and turns
red the moment anything is wired in. `tasks` must **not** duplicate it.

## 7. Threat matrix

| Boundary | Applicability | Design response | Planned test |
|---|---|---|---|
| Serialisation across the future process boundary (#8, ADR 0012) | **Applicable by anticipation** — this change fixes the types that will cross it | `str`/`int`/`Path` only, frozen + slots; no handles, no sockets (V4, V5) | pickle round-trip, §6 |
| ADR 0011 import direction | **Applicable** | §4 layout; `core/` imports nothing from `registry.py` or `procesadores/` | Item #13 owns the automated CI check; **not built here** |
| New public route / shipped route set | N/A — this change adds none | — | Already pinned (V7) |
| Routing, shell, subprocess, VCS/PR automation, executable-file classification, process integration | N/A — none exists in this change. It starts no process; it only types what one will carry | — | — |

## 8. Recorded, not solved

Carried forward unchanged from item #3's design §9. This change addresses none of them.

1. `registrar_manejador_401(app)` is still not wired into production — item #6, or whoever ships the
   first route with `Depends(exigir_token)`.
2. FastAPI's default `RequestValidationError` handler still returns `{"detail": ...}` rather than
   `{"tipo", "contexto"}`, and still echoes `input` unfiltered — item #6, or the first body-bearing
   route.
3. `TECH-DESIGN.md`'s file-tree comments mislabel the passthrough and `Contado_Carga` processors as
   items "#11"/"#12" instead of `BACKLOG.md`'s #12/#16. Non-blocking documentation drift.
4. New here: the `clave` enforcement gap and the key↔`clave` duplication (§3).

## 9. File changes

| File | Action | Description |
|---|---|---|
| `app/core/tipos.py` | Create | `ArchivoEntrada`, `ArchivoSalida` (§5) |
| `app/core/interfaz.py` | Create | `Procesador` ABC with the ADR 0006 signature verbatim and the three docstring notes (§5) |
| `app/registry.py` | Create | `REGISTRY: dict[str, Procesador] = {}` (§5) |
| `tests/test_interfaz_procesador.py` | Create | Fake processor + the behavioural tests (§6) |

**Not touched**: every shipped file under `app/`, `crear_app()`'s route set, `adrs/` (no ADR 0019).

## 10. Review budget forecast

| Artifact | Est. changed lines |
|---|---|
| `app/core/interfaz.py` | 30–40 |
| `app/core/tipos.py` | 25–35 |
| `app/registry.py` | 8–12 |
| `tests/test_interfaz_procesador.py` | 70–95 |
| **Total** | **133–182** |

Consistent with the proposal's ~120–180, at the upper half because the ABC docstring now carries
three notes rather than one. Comfortably under the 400-line budget; a single PR is appropriate and
no chained slices are needed. `sdd-tasks` owns the formal guard lines.

## 11. Migration / rollout

No migration. Three new files plus one test module; nothing wired into `crear_app()`; no route, no
schema, no runtime state, no dependency added. Rollback is deleting the four files or a `git revert`
of the commit. No feature flag.

## 12. Open questions

- [ ] None blocking. The design proceeds to `tasks`.
- [ ] `tasks` must **not** add a duplicate "shipped route set unchanged" test (V7), and must not add
      a `registrar()` helper or an import-time `clave` guard (§3) — both were considered and rejected.
- [ ] `clave` is unenforced by design (§3). If a reviewer prefers enforcement over ADR 0006's
      verbatim shape, that is an ADR-level decision against an inherited ADR, not an implementation
      tweak — raise it now rather than at `apply`.

## Addendum — the two unverified claims, executed

The design phase had no shell and said so, deliberately declining to assert how mypy treats a
`ClassVar` base declaration overridden by an unannotated subclass assignment. The orchestrator ran
both checks on the pinned interpreter through `uv run`. Recorded here so the next reader inherits an
answer instead of an open question.

Probe: a plain-annotation ABC (`clave: str`) with a subclass that never sets `clave`, and a
`ClassVar[str]` ABC with a subclass assigning `clave = "x"` unannotated — the exact shape
`app/core/errores.py` already ships.

```
python -m uv run mypy --strict  ->  Success: no issues found in 1 source file
python -m uv run python         ->  <OlvidaClave object at 0x...>
```

Two conclusions:

1. **The `clave` gap is real and is not a mypy configuration problem.** A subclass that forgets
   `clave` passes `mypy --strict` and instantiates at runtime without complaint. Neither the type
   checker nor `ABCMeta` catches it, exactly as the design states.
2. **`ClassVar` would not have closed it either.** The unannotated-subclass-assignment shape
   typechecks cleanly, resolving the contradiction the design left open — but it buys no enforcement,
   so the choice between the two shapes was never an enforcement question. The design's rejection of
   `ClassVar` on contract grounds (it narrows a signature fixed by an inherited ADR) stands on its own
   and is unaffected by this result.

The gap is therefore accepted knowingly, recorded in the ABC docstring, and inherited by items #12 and
#16 — the first changes that will actually register a processor and could be bitten by it.
