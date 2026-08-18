# Design: Contrato de errores tipificados

- **Change**: `contrato-de-errores-tipificados` (BACKLOG item #3)
- **Inputs**: `proposal.md` (**authoritative**, including its two closing sections, which supersede
  earlier wording), `exploration.md`, `adrs/0014`, `adrs/0011`, `adrs/0017`, `TECH-DESIGN.md`,
  `app/core/seguridad.py`, `app/main.py`, `tests/test_seguridad_token.py`,
  `openspec/specs/service-token-auth/spec.md`, item #2's archived `design.md`
- **Authority**: ADRs outrank every other document. Inherited `L:\App_Portal\adrs\0001`–`0010`;
  local `adrs\0011`–`0017`. **This change authors `adrs/0018`** (proposal, "Decision update").
- **Methodology**: Strict TDD is **disabled** from this item (`openspec/config.yaml`). No structural
  /AST tests, no chaos tests, no deliberate-RED procedure, no elaborate assertion machinery.
  Behavioural tests, `ruff` and `mypy --strict` still run. The full SDD chain still runs.
- **Size note**: deliberately much shorter than items #1 and #2. The core of this change is an enum,
  five typed envelopes, one exception hierarchy and one handler. Padding it would be a disservice.

## 0. Verified facts this design rests on

Items #1 and #2 each shipped a false library claim and had to add a "Post-implementation
corrections" section. To avoid a fourth, **every claim below was read in the installed source under
`L:\API-Portal\.venv\Lib\site-packages`**. No shell was available this session (no `Bash` tool), so
nothing was executed; each row cites the file and lines that were read. `uv run` is the only
acceptable interpreter for re-checking these — bare `python` is `C:\Python312` with FastAPI 0.115.14,
not the pinned 0.141.1 (recorded in item #2's design).

| # | Claim | Evidence |
|---|---|---|
| V1 | The **status-code handler table is consulted only behind `if isinstance(exc, HTTPException)`**. A plain `Exception` subclass never enters it; dispatch falls straight through to the class lookup. | `starlette/_exception_handler.py:44-53` (starlette 1.6.0) |
| V2 | The class lookup **walks `type(exc).__mro__`** and returns the first registered ancestor. So a handler registered on a *base* class serves every subclass, and **one** registration covers all five error types. | `starlette/_exception_handler.py:16-20` |
| V3 | `add_exception_handler(exc_class_or_status_code: int \| type[Exception], handler: ExceptionHandler)` — a class key is a first-class argument, not a workaround. | `starlette/applications.py:109-114` |
| V4 | A `(Request, Exception) -> Response` handler signature satisfies `mypy --strict`. Not a fresh claim: `responder_token_invalido` uses exactly that signature and is green today. | `app/core/seguridad.py:35-37`; 55 tests + `mypy app tests` currently pass |
| V5 | `JSONResponse.render` is `json.dumps(content, ensure_ascii=False, allow_nan=False, indent=None, separators=(",", ":"))`, `media_type = "application/json"`. Consequence: a raw non-ASCII value (a filename, a column name) is emitted as **literal UTF-8**, not `\uXXXX` — passed through unmodified, as ADR 0014 requires. | `starlette/responses.py:181-201` |
| V6 | `include_router` does **not** flatten routes into `app.routes`; it appends a `_IncludedRouter` wrapper. Any route-set comparison must recurse through `.original_router.routes`. | Item #2's post-implementation correction; shipped helper `_rutas_efectivas` at `tests/test_seguridad_token.py:245-263` |
| V7 | **The shipped route set is already pinned by a green test** against a literal five-entry set. If this change wired anything into `crear_app()`, that existing test fails without any new code. | `tests/test_seguridad_token.py:266-277` |
| V8 | Environment: `.venv` is CPython **3.12.0**; `pyproject.toml` sets `requires-python >=3.11`, `mypy.strict = true`, `python_version = "3.11"`. `enum.StrEnum`, `typing.Literal` and `typing.TypedDict` are available under both. | `.venv/pyvenv.cfg`; `pyproject.toml:7,45-48` |
| V9 | `app/core/errores.py` is the name the authoritative documents already use — *"errores.py # los 5 tipos tipificados"* — verified, not assumed. | `adrs/0011-estructura-core-procesadores.md:35`; `TECH-DESIGN.md:66` |

**Not verified, and nothing here depends on it**: mypy's tagged-union narrowing of `TypedDict`
unions. §3 deliberately avoids needing it.

## 1. Technical approach

One new production module, `app/core/errores.py`, containing the whole contract: the closed `tipo`
enum, one `TypedDict` per `contexto` shape, an exception base with one subclass per type, the single
`tipo → status` mapping, and one class-keyed handler. Its design goal is that **the five types are a
closed set in the type system, not a convention** — adding a sixth requires four coordinated,
diff-visible edits and immediately reddens the enum-driven test.

Nothing is wired into `crear_app()`; a test-only router in `tests/test_errores_tipificados.py`
proves the behaviour, exactly as item #2 did (§6).

`app/core/errores.py` imports only stdlib plus `fastapi`/`starlette`. It imports nothing from
`app/procesadores/` (which does not exist yet), preserving ADR 0011's invariant by construction.

## 2. Decision — the exception hierarchy shape

| Option | Closes the enum? | Binds a `contexto` to its `tipo`? | Handler | A sixth type by accident |
|---|---|---|---|---|
| One `ErrorTipificado(tipo=..., contexto=...)` | Enum closed, but `contexto` is free-form: any keys under any `tipo`, undetectable | **No** | One | Easy — one enum member and you are done. The proposal explicitly rules this out |
| Five independent subclasses, no common base | No enum forcing function | Yes | Five registrations, and the `tipo → status` map has no natural owner | A sixth class plus a sixth registration; nothing points at the enum |
| **Abstract base + one subclass per type; `tipo: ClassVar[TipoError]`, `contexto: Contexto`** | Yes | **Yes** — each subclass fixes its own `TypedDict` | **One**, registered on the base — V2's MRO walk delivers every subclass to it | Needs four edits: enum member, `TypedDict`, subclass, status entry. The enum-driven test fails on the first run if any is missing |

**Chosen: the third.** It is the only shape where the closed vocabulary and the per-type payload are
both enforced by the same structure, and where V2 lets one handler serve all five.

```python
# app/core/errores.py  (illustrative)
class TipoError(StrEnum):
    FORMATO = "formato"
    TAMANO = "tamano"
    CONTENIDO = "contenido"
    CANTIDAD = "cantidad"
    CLAVE_INEXISTENTE = "clave_inexistente"


class ErrorTipificado(Exception):
    """Base de los cinco tipos del ADR 0014. Un solo manejador la cubre (V2)."""
    tipo: ClassVar[TipoError]
    contexto: Contexto


class ErrorTamano(ErrorTipificado):
    tipo = TipoError.TAMANO

    def __init__(self, *, archivo: str, limite_bytes: int, recibido_bytes: int) -> None:
        super().__init__()
        self.contexto = ContextoTamano(
            archivo=archivo, limite_bytes=limite_bytes, recibido_bytes=recibido_bytes
        )
```

### Why a plain `Exception`, never `HTTPException` (settled — restated with its mechanism)

V1 is the reason, and it is the same reason in reverse as item #2's. For an `HTTPException`
subclass, `status_handlers.get(exc.status_code)` runs *first*; for a plain `Exception` it never runs
at all. So item #2's 401 and item #3's 422/500 **cannot collide in any registration order** — the
two live on disjoint dispatch paths:

```
raise  ──►  isinstance(exc, HTTPException)? ── yes ──►  status_handlers[exc.status_code]
                     │                                        (neither #2 nor #3 lands here)
                     no
                     ▼
            type(exc).__mro__ walk  ──►  TokenInvalido      → 401, empty body   (item #2)
                                    └──►  ErrorTipificado   → 422 | 500 + envelope (item #3)
```

**No sequence diagram.** `openspec/config.yaml` asks for one on *complex* flows. This flow is one
`raise`, no branches, no I/O, no ordering hazard. The dispatch sketch above carries the only
non-obvious information a diagram would; a `sequenceDiagram` here would be ceremony, not signal.

## 3. Decision — how `contexto` is typed

| Option | Under `mypy --strict` | Serialisation | Verdict |
|---|---|---|---|
| `dict[str, object]` | Typechecks and proves nothing: any key, any value | Direct | **Rejected** — the contract degrades to a comment |
| Frozen dataclass per type | Strong | Needs `dataclasses.asdict()` before `JSONResponse`; and `@dataclass` over an `Exception` subclass is a pattern this repo has never used and could not be executed this session | **Rejected** — an extra runtime step plus an unverifiable interaction |
| **`TypedDict` per type** | Closed key set with per-key types, checked at **every construction site** | **None needed — it *is* a `dict` at runtime**, so `JSONResponse` serialises it as-is (V5) | **Chosen** |

`TypedDict` is the only option where the typed thing and the wire thing are the same object; nothing
can drift between them because there is nothing in between.

```python
class ContextoContenido(TypedDict):
    archivo: str
    motivo: Literal["columna_faltante", "cero_filas"]
    columna: str | None

Contexto = (
    ContextoFormato | ContextoTamano | ContextoContenido
    | ContextoCantidad | ContextoClaveInexistente
)
```

### The two `clave_inexistente` variants

The proposal lists them as two shapes, but their **key sets are identical** (`clave_procesador`,
`causa`); only the closed domain of `causa` differs. So they are one `TypedDict` and two named
`Literal` aliases:

```python
CausaFila = Literal["fila_ausente", "fila_inactiva"]                 # TECH-DESIGN.md:268
CausaDesincronizacion = Literal["no_en_registry", "no_en_bd"]        # H-05, REVISION-ADVERSARIAL

class ContextoClaveInexistente(TypedDict):
    clave_procesador: str
    causa: CausaFila | CausaDesincronizacion
```

That **is** the static distinction, at the place it matters: item #6/#11 code that only inspects
database rows annotates its parameter `CausaFila` and cannot pass a desync cause, and vice versa.
*Rejected*: two `TypedDict`s discriminated by `causa` and narrowed as a tagged union — identical key
sets means the split buys no extra checking, and it would make the design depend on mypy narrowing
behaviour this session could not verify.

### Two small constructor decisions

| Point | Choice | Rationale |
|---|---|---|
| `columna` when `motivo == "cero_filas"` | Key **always present**, value `null` | A stable key set per `tipo` is one contract dimension. `NotRequired` adds a second (presence *and* value) for a consumer in another language and toolchain that ADR 0014 never asked for |
| `motivo`/`columna` correlation | Two classmethods: `ErrorContenido.columna_faltante(archivo=, columna=)` and `ErrorContenido.cero_filas(archivo=)` | Six lines make the invalid combination (`cero_filas` with a `columna`) unconstructible, instead of a comment saying not to |

## 4. Decision — where the envelope is serialised and how status is chosen

One dict literal directly under the enum is **the only place in the module where an HTTP status
appears**:

```python
_ESTADO_HTTP: Final[Mapping[TipoError, int]] = MappingProxyType({
    TipoError.FORMATO: 422,
    TipoError.TAMANO: 422,
    TipoError.CONTENIDO: 422,
    TipoError.CANTIDAD: 422,
    TipoError.CLAVE_INEXISTENTE: 500,   # ADR 0018
})


def responder_error_tipificado(request: Request, exc: Exception) -> Response:
    if not isinstance(exc, ErrorTipificado):   # V4: la firma debe ser `Exception`
        raise exc
    return JSONResponse(
        status_code=_ESTADO_HTTP[exc.tipo],
        content={"tipo": exc.tipo.value, "contexto": exc.contexto},
    )


def registrar_manejador_errores(app: FastAPI) -> None:
    app.add_exception_handler(ErrorTipificado, responder_error_tipificado)   # V2, V3
```

| Rejected alternative | Why |
|---|---|
| A `estado: ClassVar[int]` on each subclass | Five places, five chances to diverge, and no single artefact a reviewer can read to see the whole mapping |
| A status attached to each `TipoError` member | Couples the **wire vocabulary** to HTTP. ADR 0017 keeps the 401 outside this enum precisely because the enum names *content* failures, not statuses. An enum that carries statuses invites the 401 back in |

`.value` is used explicitly rather than relying on `StrEnum` being a `str` subclass — one character
of intent, zero reliance on serialiser behaviour.

**Totality is proven behaviourally, not by machinery**: the tests parametrise over `list(TipoError)`
(§7), so a sixth enum member with no status entry raises `KeyError` on the first run.

## 5. The five types and their `contexto` shapes

Exactly the proposal's table; `tamano` is ADR-fixed, the rest are the proposal's recommendation. No
field is composed prose: every value is a number, a raw string copied verbatim from input or the
database row, or a member of a closed literal enum.

| `tipo` | `contexto` | Status |
|---|---|---|
| `formato` | `{archivo: str, formato_recibido: str, formatos_aceptados: list[str]}` | 422 |
| `tamano` | `{archivo: str, limite_bytes: int, recibido_bytes: int}` (ADR 0014, verbatim) | 422 |
| `contenido` | `{archivo: str, motivo: "columna_faltante"\|"cero_filas", columna: str\|None}` | 422 |
| `cantidad` | `{minimo: int, maximo: int, recibido: int}` | 422 |
| `clave_inexistente` | `{clave_procesador: str, causa: CausaFila \| CausaDesincronizacion}` | **500** |

## 6. The test-only router

`tests/test_errores_tipificados.py`, never `app/`. A single mapping drives both the routes and the
expectations, so a type without a case is impossible to miss:

```python
_CASOS: Final[Mapping[str, ErrorTipificado]] = {
    "formato": ErrorFormato(archivo="enero.csv", formato_recibido="csv",
                            formatos_aceptados=["xlsx"]),
    "tamano": ErrorTamano(archivo="enero.xlsx", limite_bytes=26_214_400,
                          recibido_bytes=31_457_280),
    "contenido_columna": ErrorContenido.columna_faltante(archivo="enero.xlsx", columna="Fecha"),
    "contenido_cero_filas": ErrorContenido.cero_filas(archivo="enero.xlsx"),
    "cantidad": ErrorCantidad(minimo=1, maximo=2, recibido=5),
    "clave_fila": ErrorClaveInexistente(clave_procesador="contado_carga", causa="fila_ausente"),
    "clave_desync": ErrorClaveInexistente(clave_procesador="contado_carga", causa="no_en_registry"),
}

def crear_app_de_prueba() -> FastAPI:
    app = FastAPI()                       # debug omitido -> False
    registrar_manejador_errores(app)
    router = APIRouter()
    for nombre, error in _CASOS.items():
        router.add_api_route(f"/lanzar/{nombre}", _lanzador(error), methods=["GET"])
    app.include_router(router)
    return app
```

Loop-registered routes, not a `/lanzar/{caso}` path parameter: a typed FastAPI parameter is the one
thing that can summon `RequestValidationError`, which is explicitly out of scope (§9). No route here
declares a body, so FastAPI's own 422 never fires.

**No new route-set test is needed.** V7: the shipped `test_rutas_de_produccion_no_cambian` already
pins `crear_app()` against a literal five-entry set and turns red the moment anything is wired in.
If the spec states a "shipped route set unchanged" requirement, it is satisfied by that existing
test — `tasks` must **not** duplicate it, and must **not** move `_rutas_efectivas` (V6) out of
item #2's module. This change touches no shipped file.

## 7. Testing strategy

Behavioural only, per the disabled Strict TDD. **No AST/structural tests, no chaos tests, no
perturb-and-restore, no assertion machinery.**

| Layer | What to test | Approach |
|---|---|---|
| Integration | Each of the seven cases returns the documented status and the exact body | `TestClient(crear_app_de_prueba())`, parametrised over `_CASOS`; `assert respuesta.json() == {...}` **full-body equality**, so an extra or renamed field fails |
| Integration | The two `clave_inexistente` causes are distinguishable | Both 500, same `tipo`, different `contexto["causa"]` |
| Unit | The enum is exactly the five ADR 0014 values | `assert {t.value for t in TipoError} == {"formato", "tamano", "contenido", "cantidad", "clave_inexistente"}` — ADR 0014's own *"prueba que recorre el conjunto completo"* |
| Unit | Every type has a status, and every type has a case | `set(_ESTADO_HTTP) == set(TipoError)` and `{e.tipo for e in _CASOS.values()} == set(TipoError)` |
| Unit | `ErrorContenido.cero_filas` leaves `columna` `null` | Direct construction, one assertion |
| Static | Whole change | `uv run ruff check . && uv run ruff format --check . && uv run mypy app tests` |

Full-body equality is what enforces "no composed prose" — it pins every value, so a message string
cannot be added without a test failing.

## 8. ADR 0018 — outline only (`tasks` schedules the writing)

`adrs/0018-codigo-de-estado-y-causa-de-clave-inexistente.md`. MADR matching its siblings 0011–0017,
in **neutral professional Spanish**, sections **Estado / Contexto / Decisión / Alternativas
consideradas / Consecuencias**.

- **Contexto** — ADR 0014 says only *"un código de error de servidor"* and names none. TECH-DESIGN
  requires the registry↔database desync be distinguishable from "the processor does not exist",
  while ADR 0014's enum is closed at five values and `clave_inexistente` is already taken.
- **Decisión** — (a) `clave_inexistente` responds **500**; (b) the desync distinction lives in
  `contexto.causa`, a closed literal set, with `tipo` unchanged for both causes.
- **Alternativas consideradas** — **503** (rejected: item #8's bounded admission claims it for
  saturation; sharing it erases the portal's distinction between "try again later" and "this does
  not exist and retrying changes nothing"). **A sixth enum type** (rejected: ADR 0014 closes the
  enum at five, and the portal's `tipo`-keyed mapping would grow a case for a cause it cannot act
  on).
- **Consecuencias** — the portal keeps exactly one case for this `tipo`; an operator reads the cause
  from structured data with no prose; item #11's registry↔database startup check emits
  `no_en_registry`/`no_en_bd` through this same shape. **Honesty boundary, stated explicitly**: this
  closes TECH-DESIGN's distinguishability requirement, **not H-05 in full** — database-unavailable
  (ADR 0013) and child-process death/timeout (ADR 0012) remain exactly as unresolved as
  `REVISION-ADVERSARIAL.md` records them, and H-05's own text says it cannot be resolved from this
  repository alone.

## 9. Recorded, not solved — inherited obligations

Both belong to item #6 (or to whichever item first ships a body-bearing or authenticated route).
This change does **not** address either.

1. **`registrar_manejador_401(app)` is still not wired into production.** It is called only in
   `tests/test_seguridad_token.py`. Whoever wires the first processor route with
   `Depends(exigir_token)` MUST also call it in `crear_app()`, or every authentication failure
   surfaces as an unhandled 500 instead of ADR 0017's 401.
2. **FastAPI's default `RequestValidationError` handler is still active and still leaks.** It
   returns 422 with `{"detail": [...]}` — structurally unlike `{"tipo", "contexto"}` — and echoes
   `input` unfiltered, the same leak class items #1 and #2 each closed. Not live today (no shipped
   route declares a body). Item #6 MUST decide explicitly: override, scope, or otherwise close it.

Also recorded, and not this repository's to fix: inherited **ADR 0006** enumerates three portal
`evento_uso` error types while this service emits five, so `cantidad` and `clave_inexistente` have
no analytics destination. Item #10's owner must either grow ADR 0006's list or write down a
deliberate folding.

## 10. File changes

| File | Action | Description |
|---|---|---|
| `app/core/errores.py` | Create | `TipoError`, five `contexto` `TypedDict`s + the `Contexto` union, `ErrorTipificado` + five subclasses, `_ESTADO_HTTP`, `responder_error_tipificado`, `registrar_manejador_errores` (§2–§4) |
| `tests/test_errores_tipificados.py` | Create | `_CASOS`, the test-only router, the behavioural tests (§6–§7) |
| `adrs/0018-codigo-de-estado-y-causa-de-clave-inexistente.md` | Create | §8 |

**Not touched**: `app/main.py`, `app/core/seguridad.py`, `app/core/configuracion.py`,
`app/salud.py`, `tests/test_seguridad_token.py`, `crear_app()`'s route set.

## 11. Threat matrix

The reference matrix's rows are VCS/PR-shaped and are all **N/A** here: this change runs no shell,
no subprocess, no Git or PR automation, classifies no file by content type, and adds **no shipped
route** (V7). The real boundaries this change does touch:

| Boundary | Applicability | Design response | Planned test |
|---|---|---|---|
| Exception-handler collision with item #2's 401 | **Applicable** | Plain `Exception` subclass + class-keyed handler; V1 shows the two dispatch paths are disjoint in any registration order | Behavioural: item #2's 401 suite and item #3's case suite both stay green |
| Prose / user-facing copy leaking into the payload | **Applicable** | Every `contexto` field is a number, a verbatim raw value, or a closed `Literal` (§3, §5) | Full-body equality per case (§7) |
| New public route | N/A — this change adds none | — | Already pinned by the shipped route-set test (V7) |
| Unfiltered echo of request input | N/A here — deferred to item #6 (§9) | No route in this change declares a body or a typed parameter | — |
| Shell / subprocess / VCS / PR / executable classification | N/A — none exists in this change | — | — |

## 12. Review budget forecast

| Artifact | Est. changed lines |
|---|---|
| `app/core/errores.py` | 140–160 |
| `tests/test_errores_tipificados.py` | 100–125 |
| `adrs/0018-*.md` | 55–70 |
| **Total** | **295–355** |

**Under the 400-line budget**, and consistent with the proposal's ~300–410 estimate — the lower end,
because V7 removes the route-set test and its helper move (~25 lines) that the proposal had costed.
A single PR is appropriate; no chained slices are needed. `sdd-tasks` owns the formal guard lines.

## 13. Migration / rollout

No migration. New files only; nothing wired into `crear_app()`; no route, schema, or runtime state
changes; nothing calls `validar()`/`procesar()` yet. Rollback is `git revert` of the commit, or
deleting the three new files. No feature flag.

## 14. Open questions

- [ ] None blocking. The design proceeds to `tasks`.
- [ ] `tasks` must not add a duplicate "shipped route set unchanged" test — V7 shows one already
      exists and already covers this change. Flagged because the spec may state the requirement.
- [ ] The four recommended `contexto` shapes (`formato`, `contenido`, `cantidad`,
      `clave_inexistente`) are this project's invention beyond ADR 0014's text, which illustrates
      only `tamano`. If item #6/#7/#11 needs different fields, that is a **contract change** and must
      be treated as one, per ADR 0014's own Consecuencias.
