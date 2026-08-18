# Proposal — Contrato de errores tipificados

- **Change**: `contrato-de-errores-tipificados`
- **Source**: `BACKLOG.md` item #3, authority `adrs/0014-contrato-de-errores-tipificados.md`
- **Phase**: propose (no specs, no design, no implementation)
- **Depends on**: item #1 (archived, shipped). Item #2 (archived, shipped).
- **Methodology**: Strict TDD disabled from this item onward (`openspec/config.yaml`, decided
  2026-08-17). Behavioural tests, ruff, and mypy still run. The full SDD chain still runs — no phase
  is skipped.

## Proposal question round

The question round this phase would normally open already happened during the `explore` phase for
this change (Engram `sdd/contrato-de-errores-tipificados/decisions`, observation #78, 2026-08-18):
the user was asked and answered the three business-shaping questions this proposal depends on — the
`clave_inexistente` status code, how to resolve the H-05 distinguishability contradiction without
widening the closed enum, and whether to solve the `RequestValidationError` collision now or defer
it. Those answers are restated as Decisions 1–3 below and are not re-opened here.

One decision remains genuinely open and is *not* settled: whether to write a new local ADR (0018)
recording the `clave_inexistente` → 500 mapping and the `contexto`-based H-05 resolution. This
proposal recommends yes (see "Local ADR 0018") but does not author it — that is a decision for
whoever reviews this proposal to confirm or override before `spec`/`design` proceeds. If you want to
run a second question round on that point, or correct any framing in Decisions 1–3, say so before
this proposal is accepted; otherwise it proceeds to `sdd-spec`.

## Intent

**Problem.** Nothing in this repository can currently tell a caller *why* a request failed in a
machine-readable way. ADR 0014 mandates a closed five-value error vocabulary
(`formato`/`tamano`/`contenido`/`cantidad`/`clave_inexistente`) with a `{"tipo", "contexto"}` envelope
at HTTP 422 for the four user-correctable types, and an unspecified server-error code for the fifth.
Items #6–#10 (temp-file lifecycle, contract validations, packaging, the pipeline, and the future
processor routes) all need this vocabulary to exist before they can raise a single typed error. The
portal (item #10, another repository) needs a stable, documented `contexto` shape per type before it
can build its banner-mapping and `evento_uso` logic.

**Why now.** Item #3 is next in dependency order (item #1 and #2 are shipped) and is the named
prerequisite for every later item that raises a domain error. ADR 0014 fixes the wire shape but
leaves two things genuinely open — the `clave_inexistente` status code and the H-05
distinguishability contradiction — that must be decided before any code is written, or every
downstream item inherits an ambiguous contract.

**Success.** After this change: (1) a Python exception type + enum exist for each of the five ADR
0014 types, each with a documented `contexto` shape; (2) a class-keyed exception handler produces the
`{"tipo", "contexto"}` envelope at 422 for the four correctable types and at 500 for
`clave_inexistente`; (3) a test-only router proves the shape and status code for all five types
without being wired into `crear_app()`; (4) the two obligations for item #6 (401 handler wiring,
`RequestValidationError` collision) are recorded prominently enough that whoever picks up item #6
cannot miss them, mirroring how item #2 recorded its own handoff.

## Scope

### In scope

- A Python exception hierarchy in `app/core/errores.py`: one exception type per ADR 0014 type
  (`formato`, `tamano`, `contenido`, `cantidad`, `clave_inexistente`), each carrying its `contexto`
  data as typed fields/attributes — not a single generic exception parameterized by a string `tipo`.
- A `tipo` enum with exactly the five closed ADR 0014 values.
- A concrete, documented `contexto` shape per type (see "The five types and their contexto shapes"
  below), distinguishing what ADR 0014 fixes from what this proposal recommends.
- One class-keyed exception handler (or one handler per exception type, registered on the shared
  base) that serializes `{"tipo": ..., "contexto": {...}}` — never `HTTPException(422, ...)` with a
  status-code handler.
- HTTP status mapping: 422 for `formato`/`tamano`/`contenido`/`cantidad`; 500 for
  `clave_inexistente` (Decision 1 below).
- A test-only router (never wired into `crear_app()`) exercising all five types, mirroring item #2's
  `tests/test_seguridad_token.py` pattern.
- A "shipped route set unchanged" requirement/test, mirroring `service-token-auth`'s spec.
- Explicit, prominent recording (in spec/design, not buried) of the two obligations for item #6 and
  whoever wires the first real processor route (see "Obligations for item #6" below).
- A recommendation on whether to author local ADR 0018 (not authoring it).

### Out of scope

- `Procesador` ABC and registry (item #4).
- SQL Server mirror (item #5).
- Temp-file lifecycle (item #6) — including actually wiring `registrar_manejador_401` into production
  and resolving the `RequestValidationError` collision. Both are recorded here as inherited
  constraints, not solved here.
- Contract validations that would call these exceptions in anger (item #7).
- Bounded admission / 503 saturation handling (item #8).
- Output packaging (item #9).
- The common pipeline (item #10).
- The registry↔database startup check (item #11).
- Any modification to `app/core/configuracion.py`'s `token_servicio` field.
- Any modification to `app/core/seguridad.py`'s shipped behavior (its exception, handler, and
  `exigir_token` dependency are read-only precedent for this change, not a target of it).
- Authoring local ADR 0018 itself (recommended, not delivered, by this proposal).
- Resolving H-05 in full. H-05 names three untyped system failures (database unavailable, registry↔
  database desync, child-process death/timeout); this change addresses only the second, and only to
  the extent TECH-DESIGN's distinguishability requirement demands, inside the existing
  `clave_inexistente` type. H-05's own text states resolving it fully "no se puede hacer solo desde
  este repositorio" — this proposal does not claim otherwise.

## Decisions (settled — restated from the explore-phase question round)

### Decision 1 — `clave_inexistente` maps to HTTP 500

ADR 0014 says only *"un código de error de servidor"* and names no status code. This proposal fixes
it at **500**.

Rationale: a missing or inactive `procesador` row in the database is a configuration/deployment
problem — retrying the same request will not fix it, because the problem is not in the request. 500
communicates that honestly. 503 was considered and rejected specifically because item #8's bounded
admission already claims 503 for saturation (ADR referenced in `REVISION-ADVERSARIAL.md`'s "Qué se
hizo" note under H-05); reusing 503 here would erase the distinction the portal needs between "try
again later, the system is busy" (503, item #8) and "this configuration does not exist and retrying
changes nothing" (500, item #3). This mirrors the precedent set by ADR 0017, which reserved a status
code (401, kept structurally separate from the ADR 0014 enum) for a class of failure that is not a
content error — the same discipline applies here in reverse: `clave_inexistente` stays inside the
ADR 0014 enum (its `tipo` value does not change) but claims a status code that is not shared with
another failure class that means something operationally different.

### Decision 2 — H-05's registry↔database desync distinguishability is resolved inside `contexto`

TECH-DESIGN requires the registry-desync case be "distinguible de: el procesador no existe" (line
266 of `REVISION-ADVERSARIAL.md`'s H-05 write-up). The ADR 0014 enum is closed at five values and
`clave_inexistente` already covers "row missing or inactive in the database." Adding a sixth type
would violate the closed enum ADR 0014 fixes.

Resolution: `tipo` stays `clave_inexistente` for both causes; `contexto` carries a field that
distinguishes them. Two concrete `contexto` shapes for `clave_inexistente` (not one — see "The five
types and their contexto shapes"):

1. **Row absent or inactive in the database** — the case `TECH-DESIGN.md` names directly ("Fila
   inexistente o con `activo = false`", line 268).
2. **Registry↔database desync** — a row exists and is active in the database, but the code has no
   corresponding entry in the processor registry (or vice versa) — the case
   `REVISION-ADVERSARIAL.md` line 266 names.

Both stay under `tipo: clave_inexistente` and both stay at HTTP 500. The portal's `tipo`-keyed
mapping does not change (it still has exactly one case to write for this type), and an operator
reading `contexto` can still tell the two causes apart from the structured data alone — no prose
needed.

**Honesty boundary, stated explicitly**: this satisfies TECH-DESIGN's distinguishability requirement
without widening the enum. It does **not** claim to close H-05 in full. H-05 names three untyped
system failures; this addresses one of them (the desync half), and H-05's own text says the finding
"no se puede hacer solo desde este repositorio" — full resolution needs a cross-repository
conversation with item #10's owner. Database-unavailable (ADR 0013) and child-process death/timeout
(ADR 0012) remain exactly as risky and exactly as unresolved as `REVISION-ADVERSARIAL.md` already
recorded them; this proposal does not touch them.

### Decision 3 — the `RequestValidationError` / FastAPI 422 collision is deferred to item #6

FastAPI's own `request_validation_exception_handler` already returns 422 with a structurally
different body (`{"detail": [...]}`), and pydantic v2's `errors()` includes unfiltered `input` by
default — the same unfiltered-echo leak class items #1 and #2 each closed for other surfaces. This is
a real problem, but it is not live today: no shipped route declares a request body, so FastAPI's
validator never fires. This proposal does not scope, override, or replace FastAPI's default handler.
It is recorded as an **inherited constraint** for item #6 (see "Obligations for item #6" below) and
for whichever item first ships a body-bearing route (items #6/#7).

## The five types and their `contexto` shapes

ADR 0014 illustrates only `tamano`'s shape. The rest are this proposal's recommendation, derived from
the fields `TECH-DESIGN.md`'s "Rechazo por contrato" checklist and "Modelo de datos" table already
name as required inputs to each validation. None of these fields are composed prose — all are raw
values already present in the request or the database row (see "Sin texto destinado al usuario"
below).

| `tipo` | Source | `contexto` shape | Status |
|---|---|---|---|
| `formato` | ADR 0014 (name only, no shape shown) | **Recommended**: `{"archivo": str, "formato_recibido": str, "formatos_aceptados": list[str]}` | Recommendation |
| `tamano` | ADR 0014 (shape given verbatim) | **Fixed by ADR 0014**: `{"archivo": str, "limite_bytes": int, "recibido_bytes": int}` | ADR-fixed |
| `contenido` | TECH-DESIGN "columna faltante en el `contexto`" (line 310); "cero filas procesadas" (line 313) | **Recommended**: `{"archivo": str, "motivo": Literal["columna_faltante", "cero_filas"], "columna": str \| None}` — `columna` populated only when `motivo == "columna_faltante"` | Recommendation |
| `cantidad` | TECH-DESIGN `entradas_min`/`entradas_max` (line 93, 183, 226) | **Recommended**: `{"minimo": int, "maximo": int, "recibido": int}` | Recommendation |
| `clave_inexistente` (fila ausente/inactiva) | TECH-DESIGN line 268 | **Recommended**: `{"clave_procesador": str, "causa": "fila_ausente" \| "fila_inactiva"}` | Recommendation |
| `clave_inexistente` (desync registry↔bd) | `REVISION-ADVERSARIAL.md` H-05, line 266 | **Recommended**: `{"clave_procesador": str, "causa": "no_en_registry" \| "no_en_bd"}` | Recommendation |

The two `clave_inexistente` shapes share the same `tipo` and status code (500) but are distinguished
by their `causa` field, per Decision 2. Both `causa` enums are closed and machine-readable — no free
text.

## "Sin texto destinado al usuario" — precise boundary

ADR 0014's decision text states: *"El servicio no emite texto destinado a un usuario final. Ni en
`tipo`, ni en `contexto`, ni en ningún campo adicional."*

This proposal reads that as forbidding **composed prose** — any string this service assembles,
concatenates, or writes with the intent of being read by an end user (a sentence, a phrase, a
message fragment, anything that answers "what should the user see"). It does **not** forbid **raw
data values** that were already present in the request or the database row and are passed through
unmodified: a filename, a byte count, a limit, a column name, a `clave_procesador`, or a closed enum
member. `columna_faltante: "Fecha"` is a raw value (the literal column name from the source file's
header, unchanged); `"falta la columna Fecha"` would be composed prose and is forbidden. The
`contexto` shapes above contain no composed prose; every field is either a number, a raw string
copied verbatim from input/database, or a member of a closed literal enum defined by this service
(never freely typed).

## What ships and how it is proven

Following item #2's precedent exactly: this change adds the exception hierarchy, the handler, and a
**test-only router**, never wired into `crear_app()`. `app/main.py`'s route set is unchanged before
and after this change — a requirement, proven by a test, mirroring `service-token-auth`'s "Shipped
application route set is unchanged" requirement.

Nothing in items #4–#11 exists yet, so nothing calls `validar()` or `procesar()` — there is no
production code path that could raise these exceptions today. This change proves the contract in
isolation: given each exception type raised deliberately by a test route, the handler produces the
documented envelope and status code.

## Obligations for item #6 (and whoever wires the first real processor route)

These are carried forward from item #2 and item #3's own construction, not new to this change, but
this proposal is the place they must be stated prominently because item #3 is what makes them
concrete:

1. **`registrar_manejador_401(app)` is still not wired into production.** It remains called only in
   `tests/test_seguridad_token.py`. This change does not wire it either (out of scope — it is not
   this change's dependency to add). Whoever wires the first real processor route with
   `Depends(exigir_token)` MUST also call `registrar_manejador_401(app)` in `crear_app()`, or every
   authentication failure surfaces as an unhandled 500 instead of the 401 ADR 0017 requires.
2. **FastAPI's default `RequestValidationError` handler is still active and still leaks.** It returns
   a body shaped nothing like `{"tipo", "contexto"}` and echoes `input` unfiltered — the third
   instance of an echo leak this project has had to close deliberately (items #1 and #2 closed the
   first two, for the configuration field and the auth header respectively). Item #6, or whichever
   item first ships a body-bearing route, MUST decide explicitly how to handle this: override the
   handler, scope it, or otherwise close the leak. It cannot be left as FastAPI's default once a real
   request body exists.

## Local ADR 0018 — SETTLED: authored by this change

Local ADRs run 0011–0017; 0018 is free. This proposal **recommends** writing ADR 0018 to record two
decisions that are otherwise only findable in this proposal, Engram, and `REVISION-ADVERSARIAL.md`:
the `clave_inexistente` → 500 mapping (Decision 1) and the `contexto`-based resolution of H-05's
distinguishability requirement (Decision 2). Both decisions have the shape of prior local ADRs
(0013–0017): a status-code or contract choice with a real alternative that was considered and
rejected for a stated reason. This proposal does not author ADR 0018; that is left for the `design`
phase or a maintainer to confirm.

## Rollback plan

This change adds new files only (`app/core/errores.py` and its test-only router/tests) and does not
modify `app/main.py`, `app/core/configuracion.py`, or `app/core/seguridad.py`. Because nothing calls
`validar()`/`procesar()` yet and the route set is provably unchanged, rollback is a plain revert of
the added files with no migration, no data change, and no coordination needed with any other item —
identical in shape to item #2's rollback story. No feature flag is needed because nothing is wired
into production.

## Changed-lines estimate against the 400-line budget

Rough estimate for `spec`/`design`/`tasks`/`apply` combined, based on item #2's actual shipped size
(`app/core/seguridad.py` is ~77 lines, its test router and tests substantially more):

- `app/core/errores.py` (5 exception types + enum + handler + contexto dataclasses/typed shapes):
  ~120–160 lines.
- Test-only router (mirroring `tests/test_seguridad_token.py`'s router fixture): ~30–50 lines.
- Tests (five types × status/shape assertions, plus the "route set unchanged" test, plus the
  desync-vs-absent `contexto` distinction): ~150–200 lines.
- Total estimate: **~300–410 lines**, close to but not confidently under the 400-line budget given
  five types instead of item #2's single exception. If `design`/`tasks` sizing confirms this is
  tight, splitting `apply` into two reviewable commits (exception hierarchy + handler; then the
  test-only router + tests) is the mitigation, consistent with `ask-on-risk` delivery strategy.

## Risks carried into `spec`/`design`

- The two `clave_inexistente` `contexto` shapes recommended above are new invention beyond ADR 0014's
  text; `design` should confirm they are sufficient for item #11 (registry↔database startup check),
  which is the other consumer of the desync distinction.
- H-05 remains only partially addressed, by design (see "Honesty boundary" in Decision 2). Database-
  unavailable and child-process-death/timeout stay unresolved and out of this change's scope.
- The `contexto` shapes for `formato`, `contenido`, `cantidad`, and both `clave_inexistente` variants
  are recommendations, not ADR-fixed text (only `tamano`'s is). If `design` or item #6/#7's actual
  implementation needs different fields, that is a contract change and should be treated as one, per
  ADR 0014's own consequences section.
- Local ADR 0018 is recommended but not committed to; if the maintainer declines it, Decisions 1 and
  2 exist only in this proposal and Engram, which is a weaker paper trail than the rest of this
  project's status-code decisions (0013, 0016, 0017 all got ADRs).

## Gap found while verifying the ADR 0006 citation

An earlier draft of this proposal attributed the closed enum to inherited ADR 0006. That attribution
was wrong and has been corrected above — ADR 0014 fixes the enum, not ADR 0006. Checking it surfaced
something worth recording, because **ADR 0006 is inherited and therefore outranks ADR 0014**.

ADR 0006 states verbatim that the portal *"mapea la respuesta del servicio al tipo de evento
(`ejecucion` en éxito; `error_formato`, `error_tamano` o `error_contenido` según el error tipificado
que reciba)"*.

That enumerates **three** error event types. This service is about to commit to **five**. Two of them
— `cantidad` and `clave_inexistente` — have no destination in the portal's `evento_uso` analytics
under the ADR that outranks ours.

What this does and does not mean:

- It does **not** invalidate ADR 0014's five-value enum. ADR 0006 describes what the portal records
  for analytics; it does not forbid the service from distinguishing more failure causes on the wire.
  The service's `tipo` and the portal's `evento_uso.tipo` are different vocabularies that happen to
  overlap on three values.
- It **does** mean that a rejection for `cantidad` or `clave_inexistente` will be invisible in the
  portal's usage analytics as anything more specific than "not one of the three". An operator asking
  "how many uploads were rejected for file count?" will find no answer, and will not be told why.

This is not this change's to fix — `evento_uso` belongs to the portal, and the mapping is item #10 of
the master backlog, in another repository. It is recorded here so that item #10's owner inherits a
stated question rather than discovering a silent gap: **either ADR 0006's event-type list grows to
cover all five, or the portal deliberately folds `cantidad` and `clave_inexistente` into an existing
event type and that folding is written down.** Choosing neither leaves the analytics quietly
incomplete.


## Decision update — ADR 0018 is in scope

The user settled this after the proposal was written: **this change authors
`adrs/0018-*.md`**, recording Decision 1 (`clave_inexistente` maps to HTTP 500) and Decision 2 (the
registry-desync distinguishability resolved inside `contexto` rather than by a sixth enum value).
The section above, which recommended it without delivering it, is superseded.

The ADR follows the MADR format of its siblings `adrs/0011`-`0017` and is written in neutral
professional Spanish like them. It must state the rejected alternatives with their reasons -- 503 for
`clave_inexistente` (rejected because item #8 claims it for saturation) and a sixth enum type
(rejected because ADR 0014 closes the enum) -- and it must state the honesty boundary explicitly:
this closes TECH-DESIGN's distinguishability requirement, not H-05 in full.

The ADR's line count counts toward this change's size estimate.
