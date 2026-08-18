# Proposal — Interfaz `Procesador`, tipos de archivo y registry

- **Change**: `interfaz-procesador-y-registry`
- **Source**: `BACKLOG.md` item #4, authority `L:\App_Portal\adrs\0006-procesadores-registro-modulos.md`
  (inherited, outranks local ADRs) plus local ADR 0011 (placement).
- **Depends on**: item #3 (`contrato-de-errores-tipificados`), archived and shipped. `main` at
  `210d709`, clean, 74 tests green.
- **Methodology**: Strict TDD disabled. Full SDD chain still runs.

## Proposal question round

This item's shape is fixed almost entirely by two inherited/authoritative documents (ADR 0006's
verbatim ABC signature, ADR 0011's placement rule) and by two facts already verified by execution
(pickling, ADR 0011 placement conflict resolution). The only genuinely open questions are
implementation-detail choices (dataclass vs pydantic, file location, field types), which this
proposal settles below with stated rationale rather than deferring them. There is no business-rule
ambiguity left to ask about — no permissions, thresholds, or user-facing behavior are decided here;
this ships an internal interface with no route. If you disagree with any of the three decisions
below (dataclass, file placement, `Path` fields) or want to reopen whether a local ADR is warranted,
say so before this proceeds to `spec`/`design`; otherwise it proceeds as written.

## Intent

**Problem.** Nothing in this repository yet defines what a processor module *is*. Items #12/#16 need
a shared interface to implement against, and the pipeline (#10) needs one registry to look processors
up by key. Without this now, every later item invents its own shape.

**Why now.** Item #4 is next in dependency order; ADR 0006 already fixes the ABC signature verbatim,
so implementing it now is mechanical, not speculative.

**Success.** After this change: the `Procesador` ABC, `ArchivoEntrada`/`ArchivoSalida`, and a real
but empty `REGISTRY: dict[str, Procesador]` exist, type-check, and are proven by a test-only fake
processor — with nothing wired into `crear_app()`, matching items #1–#3's precedent.

## Scope

### In scope
- `app/core/interfaz.py`: the `Procesador` ABC exactly as ADR 0006 fixes it (`validar` returns
  `ErrorTipificado | None`; `procesar` returns `list[ArchivoSalida]`; both take `list[ArchivoEntrada]`).
- `app/core/tipos.py`: `ArchivoEntrada` and `ArchivoSalida`, frozen `slots` dataclasses.
- `app/registry.py`: `REGISTRY: dict[str, Procesador] = {}` — real, typed, empty.
- A test-only fake `Procesador` proving: the ABC is abstract (cannot instantiate without both
  methods), both methods honor list-in/list-out, and a fake instance type-checks into
  `dict[str, Procesador]`.
- A docstring caveat on the ABC recording the open question for item #8 (see below).
- Explicit recording of the two obligations inherited by item #6 (see below) and the `TECH-DESIGN.md`
  numbering drift.

### Out of scope
- SQL Server mirror (#5), temp-file lifecycle (#6), contract validations (#7), bounded admission and
  the child process (#8), output packaging (#9), the pipeline (#10), the registry↔database startup
  check (#11), any concrete processor (#12, #16). No shipped file under `app/` is modified.
- A new local ADR (see "Local ADR" below — not authored here, argued against).

## Capabilities

### New Capabilities
- `procesador-interface`: the `Procesador` ABC, `ArchivoEntrada`/`ArchivoSalida` carrier types, and
  the empty typed `REGISTRY`.

### Modified Capabilities
None.

## Decisions

**1. Frozen stdlib `dataclass`, not pydantic `BaseModel`.** These types cross a process boundary by
value (ADR 0012) and never need runtime validation of external input — `validar()` already exists
for content rules, and these carriers hold data already read from disk metadata. A frozen,
`slots=True` dataclass is trivially picklable (verified by execution), adds no dependency, and
matches `errores.py`'s precedent of not layering runtime validation onto internal carriers
(`ContextoFormato` etc. are plain `TypedDict`, not pydantic models).

**2. Location: `app/core/tipos.py`, not inside `interfaz.py`.** `ArchivoEntrada`/`ArchivoSalida` are
data shapes consumed by the ABC, the pipeline (#10), and eventually the child process (#8) — not the
literal interface contract itself. Splitting them keeps `interfaz.py` to the ABC alone (ADR 0011's
file tree names `interfaz.py` for "ABC Procesador" specifically) and gives #8/#10 a types-only import
with no ABC machinery attached.

**3. Field types: `pathlib.Path` for temp paths, not `str`.** Verified picklable under `spawn`
alongside `str`/`int`. `Path` is the more precise type for a filesystem location, gives #6/#8 path
methods (existence checks, suffix access) without re-wrapping a string, and costs nothing extra
across the pickle boundary.

Concrete fields:
```python
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

**4. No new local ADR.** The ABC signature is fixed verbatim by inherited ADR 0006; the registry
placement is fixed by local ADR 0011. Nothing decided here is a fresh architectural tradeoff with a
rejected alternative worth a MADR entry — dataclass-vs-pydantic and file placement are implementation
details, not decisions future readers will need to re-derive. Writing ADR 0019 to restate what 0006
and 0011 already say would add paper trail without adding information. Recommend not authoring one;
say so explicitly if you disagree.

## Docstring caveat (must ship on the ABC)

No document specifies whether the child process re-derives the processor instance (re-import +
registry lookup) or receives a pickled live instance. That is item #8's decision in
`core/ejecucion.py`. The `Procesador` docstring in `interfaz.py` MUST state this open question so
item #8 does not discover it late.

## Obligations already inherited (record, do not solve)

- `registrar_manejador_401(app)` is still not wired into production (item #6/#3's carry-forward).
- FastAPI's default `RequestValidationError` handler still returns `{"detail": ...}`, not
  `{"tipo", "contexto"}`, and echoes `input` unfiltered — item #6 or whoever ships the first
  body-bearing route must close this.
- `TECH-DESIGN.md`'s file-tree comments mislabel the passthrough and `Contado_Carga` items as
  "#11"/"#12" instead of `BACKLOG.md`'s actual #12/#16. Non-blocking; worth a line for whoever cites
  those lines next.

## Approach

Ship exactly what items #1–#3 shipped: library code plus a test-only proof surface, nothing wired
into `crear_app()`. `app/registry.py` is the only legitimate exception to ADR 0011's "core never
imports procesadores" rule, since it is the join point by design — item #13's CI check will encode
this placement.

## Affected Areas

| Area | Impact | Description |
|---|---|---|
| `app/core/interfaz.py` | New | `Procesador` ABC, docstring caveat for item #8 |
| `app/core/tipos.py` | New | `ArchivoEntrada`, `ArchivoSalida` frozen dataclasses |
| `app/registry.py` | New | empty typed `REGISTRY` |
| tests | New | test-only fake `Procesador` proving abstractness, list shapes, registry typing |

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| `Path` field choice complicates a future serialization boundary decision in #8 | Low | Already verified picklable under `spawn`; #8 inherits this, flagged explicitly |
| Docstring caveat gets missed/overwritten before item #8 | Low | Stated here and required by this proposal's scope, testable by presence-of-text review |
| Reviewer expects a new ADR and this proposal declines to write one | Low | Rationale stated plainly (Decision 4); easy to override at review |

## Rollback Plan

Three new files, zero modified shipped files, nothing wired into `crear_app()`. Revert is deleting
the three files and their tests — no migration, no data change, no coordination with any other item.

## Changed-lines estimate against the 400-line budget

- `interfaz.py` (ABC + docstring): ~25–35 lines.
- `tipos.py` (two dataclasses): ~25–35 lines.
- `registry.py`: ~5–10 lines.
- Tests (fake processor, abstractness, list-shape, registry-typing assertions): ~60–100 lines.
- Total estimate: **~120–180 lines**, comfortably under budget. No chained-PR mitigation needed.

## Dependencies
- Item #3 (`contrato-de-errores-tipificados`), archived and shipped — `validar`'s return type is
  `ErrorTipificado | None`, imported from `app/core/errores.py`.

## Success Criteria
- [ ] `Procesador` ABC exists with the ADR 0006 signature verbatim and a docstring caveat for item #8.
- [ ] `ArchivoEntrada`/`ArchivoSalida` exist as frozen, `slots` dataclasses with the documented fields.
- [ ] `REGISTRY: dict[str, Procesador] = {}` exists, typed, empty, in `app/registry.py`.
- [ ] A test-only fake processor proves abstractness, list-in/list-out, and registry-type compatibility.
- [ ] `crear_app()`'s route set is unchanged; no shipped file under `app/` is modified.
