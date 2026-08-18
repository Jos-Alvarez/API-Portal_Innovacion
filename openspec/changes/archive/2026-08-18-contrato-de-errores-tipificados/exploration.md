# Exploration — Contrato de errores tipificados

- **Change**: `contrato-de-errores-tipificados`
- **Source**: `BACKLOG.md` item #3, authority `adrs/0014-contrato-de-errores-tipificados.md`
- **Phase**: explore (read-only; no proposal, no implementation)
- **Artifact store**: hybrid (this file + Engram `sdd/contrato-de-errores-tipificados/explore`)
- **Depends on**: item #1 (archived). Item #2 is also archived and shipped.
- **Methodology**: Strict TDD is disabled from this item onward. The full SDD chain still runs.

## Current state

Nothing of item #3 exists. `app/` holds only `arranque.py`, `core/configuracion.py`, `core/seguridad.py`,
`salud.py` and `main.py`. There is no `app/core/errores.py`, no `interfaz.py`, no `registry.py`, no
`procesadores/`.

Notably: `crear_app()` wires only `router_salud`. **Item #2's auth dependency and its 401 handler are
not wired into production** — they exist and are proven, but only through the test-only router in
`tests/test_seguridad_token.py`. That was deliberate (no processor routes exist yet), and it is also a
trap; see Risks.

## What ADR 0014 mandates

- A closed enum of exactly five values: `formato`, `tamano`, `contenido`, `cantidad`,
  `clave_inexistente`.
- Wire shape `{"tipo": ..., "contexto": {...}}` at HTTP **422** for the four correctable types.
- `clave_inexistente` gets *"un código de error de servidor"* — **the ADR names no specific status
  code**. That is an open decision, not a settled one.
- `contexto` is explicitly **not** uniform across types: its shape depends on the type.
- *"Sin texto destinado al usuario"* forbids composed prose anywhere in the payload. It does not
  forbid raw data values.

## The `clave_inexistente` contradiction (finding H-05)

ADR 0014's own Contexto describes `clave_inexistente` as covering database↔registry desynchronisation.
`TECH-DESIGN.md` uses it only for "row missing or inactive in the database", and separately requires
that the registry-desync case be **distinguishable** from "the processor does not exist".

With the enum closed at five values and `clave_inexistente` already claimed by one of those meanings,
that requirement cannot be satisfied by adding a sixth type. This is not a new discovery — it is the
second bullet of `REVISION-ADVERSARIAL.md`'s finding **H-05** ("Tres fallos del sistema sin tipo de
error", severity Crítico, status *Registrado, sin resolver*).

H-05's three untyped system failures:

1. **Database unavailable.** ADR 0013 claims a typed error for this, and no such type exists.
2. **Registry↔database desync**, per above.
3. **Child-process death or timeout** (ADR 0012).

H-05's own text says resolving this *"no se puede hacer solo desde este repositorio"*. **Item #3 must
not widen the closed enum unilaterally.**

## Interaction with item #2's 401 — verified, not assumed

Read from the installed Starlette 1.6.0 (`_exception_handler.py`):

```python
if isinstance(exc, HTTPException):
    handler = status_handlers.get(exc.status_code)
```

The status-code handler table is consulted **only** when the raised exception is an `HTTPException`
instance. Otherwise dispatch falls through to `_lookup_exception_handler`, which walks
`type(exc).__mro__` looking for a class-keyed handler.

Item #2's `TokenInvalido` is a fieldless plain `Exception` with a class-keyed handler. Therefore **any
class-keyed handler item #3 registers is unconditionally safe with respect to the 401, in any
registration order.** No coordination is required.

Recommendation that follows: item #3 should use the same shape — its own exception type plus a
class-keyed handler — rather than `HTTPException(422, ...)` with a status-code handler. The latter
would make the 422 table a shared surface and reintroduce exactly the ambiguity item #2 designed away.

## Collision with FastAPI's own 422

FastAPI already returns 422 for request-validation failures, with body `{"detail": [...]}` produced by
`request_validation_exception_handler`, which returns `jsonable_encoder(exc.errors())` with no
`include_input=False` filtering — and pydantic v2's `errors()` includes `input` by default.

Two distinct problems, and only one of them is about dispatch:

- **Shape collision (real)**: two structurally different bodies both arrive at 422. A consumer keying
  on `tipo` would find no `tipo` in FastAPI's version.
- **Echo vector (real)**: unfiltered `input` is the same leak class that item #1 closed for the
  configuration field and item #2 closed for the auth header. Third appearance in this project.

Neither is triggered today, because no shipped route declares a body. It becomes live for the first
route that does — items #6 and #7.

## Who consumes this

The portal maps these errors to a banner and to `evento_uso`. That mapping is item #10 of the master
backlog, in another repository. What this service must guarantee: the closed five-value enum, a
documented `contexto` shape per type, and zero prose leakage. Only one `contexto` shape (`tamano`'s) is
illustrated anywhere in the documents. `cantidad` and `clave_inexistente` have no destination in the
portal's banner or `evento_uso` yet — that is the portal's problem to solve, recorded here so it is
not mistaken for this service's.

## What item #3 can ship and prove on its own

Nothing calls `validar()` or `procesar()` yet; items #4–#9 do not exist. So item #3 ships the error
vocabulary, the envelope, the exception type and its handler — and proves them through a **test-only
router**, never wired into `crear_app()`, exactly as item #2 did, with a test asserting the shipped
route set is unchanged.

## Open decisions for the proposal

1. **The HTTP status for `clave_inexistente`.** ADR 0014 says only "a server error code".
2. **The registry-desync distinguishability contradiction.** The enum cannot grow. Options include
   distinguishing inside `contexto` while keeping `tipo: clave_inexistente`, or an out-of-band signal
   in the style of ADR 0017, or escalating it as a cross-repository decision.
3. **Whether item #3 replaces or scopes FastAPI's `RequestValidationError` handler now**, or
   explicitly defers it to whichever item first ships a body-bearing route.
4. Whether resolving any part of H-05 belongs here at all, given its own text says it cannot be
   resolved from this repository alone.

## Risks

- **The 401 handler is not wired into production.** `registrar_manejador_401(app)` is called only in
  tests. Whichever item first wires real processor routes must wire the handler too, or authentication
  failures will surface as unhandled 500s instead of 401s. This deserves to be recorded somewhere a
  future item will actually read.
- The TECH-DESIGN registry-desync requirement is genuinely unsatisfiable under the current enum usage.
  It needs an explicit decision, not a silent choice.
- The unfiltered-`input` echo vector remains open for any future multipart or body-bearing route.

## Note on verification

The explore phase had no Engram search tools, so prior topics were not read directly; it compensated by
reading the authoritative documents and shipped code. The orchestrator independently re-verified the
Starlette dispatch gate quoted above against the installed source.
