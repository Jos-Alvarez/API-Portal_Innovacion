# Proposal — Borde de autenticación y errores HTTP

- **Change**: `borde-de-autenticacion-y-errores-http`
- **Source**: the first half of `BACKLOG.md` item #6, split by user decision on 2026-08-18
- **Depends on**: items #1, #2 and #3, all archived and shipped
- **Methodology**: Strict TDD disabled. Full SDD chain runs.
- **Exploration**: `exploration.md` in this folder (shared with the deferred second half)

## Why this change exists

Item #6 was estimated at 700–900 lines because it holds two unrelated jobs: closing three inherited
HTTP-boundary obligations, and building file reception with a temporary-file lifecycle. The user
split them so each is reviewable on its own subject.

**This change is the first half: the HTTP boundary.** It discharges the three debts items #2 and #3
deliberately deferred, and nothing else. The second half — reception, name sanitisation, the
temporary lifecycle, the H-02 resolution and ADR 0019 — stays parked in
`openspec/changes/recepcion-y-ciclo-de-vida-de-temporales/` with its own proposal already drafted.

## The three obligations, and why each is real

Each was measured against the installed Starlette 1.6.0 / FastAPI 0.141.1 through `uv run`, not
recalled.

### 1. `registrar_manejador_401(app)` is not wired into production

Item #2 built and proved the 401 handler, then wired it only in tests because no production route
needed it yet. Today, an authentication failure in production would surface as an unhandled 500.

FastAPI's `add_exception_handler` has **no runtime guard against late registration**, unlike
`add_middleware`: registering after the first request silently no-ops instead of raising. The call
must therefore land inside `crear_app()`, where it cannot be missed or ordered wrongly.

### 2. FastAPI's default `RequestValidationError` handler leaks and contradicts ADR 0014

It calls `exc.errors(include_url=False)` **without** `include_input=False`, so raw rejected values
appear in every 422 body — the same echo-leak class items #1 and #2 each closed for their own
surfaces. It also returns `{"detail": [...]}`, structurally unlike ADR 0014's `{"tipo", "contexto"}`.

This is not live today only because no shipped route declares a body. It goes live the moment one
does, so it is closed here, before reception exists rather than after.

### 3. `Depends()` cannot enforce "401 before reading the body"

`routing.get_request_handler` reads the request body **before** `solve_dependencies` runs, identically
for route-level and router-level dependencies. The PRD requires rejection *"con 401 antes de leer el
cuerpo del request"*, and a dependency alone cannot deliver that — FastAPI will have parsed the whole
upload first.

The mechanism must inspect `scope["headers"]` before calling `receive()`. **ADR 0016 forbids a global
path allow-list**, so the exemption for `/salud` must stay structural: `/salud` is not excluded from
authentication, it simply never sits inside the authenticated surface.

## Scope

### In scope

- Wiring `registrar_manejador_401(app)` inside `crear_app()`.
- A `RequestValidationError` handler producing ADR 0014's envelope with no `input` echo, registered in
  `crear_app()`.
- The pre-body authentication boundary — a `Mount()`-scoped sub-app or equivalent that authenticates
  from `scope["headers"]` before any body is read, with `/salud` outside it by construction.
- Behavioural tests proving each: a 401 shape from production, a validation failure that neither
  leaks nor uses the wrong envelope, and rejection that occurs without the body being consumed.

### Out of scope

- File reception, name sanitisation, temporary directories and their lifecycle — the parked second
  half.
- The H-02 resolution (`background=` plus sweeper) and ADR 0019, which belong with the lifecycle.
- Items #7–#12 and #16. No concrete processor, no upload route yet.
- Any new runtime dependency. The project runs on `fastapi`, `uvicorn[standard]` and
  `pydantic-settings`, and item #5 was bypassed, so there is no SQLAlchemy and no pyodbc.

## What can and cannot be proven here

The registry and the contract table are both empty, so `obtener_contrato` returns `None` for every
key. That does not limit this change: all three obligations are about the HTTP boundary, and the
boundary can be exercised with a route that carries a body without needing a processor behind it.

## Open decisions for design

- `Mount()`-scoped sub-app versus raw ASGI middleware for the pre-body boundary. Both can read
  `scope["headers"]` before `receive()`; the exploration leans toward the mount because it keeps the
  `/salud` exemption structural rather than conditional. Design decides with reasons.
- Whether the authenticated sub-app is created now with no routes inside it, or created when the
  upload route arrives. Creating it now is what makes the boundary testable today.
- Where the `RequestValidationError` handler lives — beside the typed-error handler in
  `app/core/errores.py`, or its own module.

## Rollback

Modifies `crear_app()` and adds new modules and tests. Reverting the commits restores the previous
behaviour exactly; no data, schema or external system is touched. The one behavioural change visible
outside the process is that authentication failures start returning 401 instead of 500 — which is the
point.

## Size

Roughly a third of the original 700–900 estimate. The forecast has run short on the last three items,
always through the test file, so read the design's number as a floor rather than a midpoint.
