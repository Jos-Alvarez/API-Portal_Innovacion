# Delta for Service Token Auth

## Purpose

Extends item #2's domain into production, for BACKLOG item #6's first half
(`borde-de-autenticacion-y-errores-http`, split from item #6 on 2026-08-18). Wires the 401 handler
into the shipped application, adds the pre-body authentication boundary the PRD requires ("401 antes
de leer el cuerpo del request"), and updates the route-set invariant this change deliberately breaks.

Out of scope: file reception, name sanitisation, temporary directories and their lifecycle, the H-02
resolution, ADR 0019 (all parked in `openspec/changes/recepcion-y-ciclo-de-vida-de-temporales/`),
items #7-#12 and #16. No new runtime dependency.

## MODIFIED Requirements

### Requirement: Shipped application route set changes deliberately, for the authentication boundary only
This change MUST wire `registrar_manejador_401(app)` into `crear_app()` and MUST add the pre-body
authentication boundary (a `Mount()`-scoped sub-app or equivalent) to the shipped application. The
mount/route set MUST differ from the previous shipped state. Item #2's pinned
`test_rutas_de_produccion_no_cambian` MUST be updated to the new literal set — updating it is the
proof the surface changed deliberately, not by accident. `/salud` MUST remain outside the
authenticated mount, unauthenticated, and reachable exactly as before, by construction (ADR 0016),
never by a path allow-list.
(Previously: forbade any route/mount change; this is the first change to deliberately add one.)

#### Scenario: 401 handler wired into production
- GIVEN the shipped `crear_app()`
- WHEN it is constructed
- THEN `registrar_manejador_401` has been registered as an exception handler before the app is
  returned

#### Scenario: Pinned route-set test updated, not merely passing
- GIVEN `test_rutas_de_produccion_no_cambian` from item #2
- WHEN this change ships
- THEN its pinned literal route set has been updated to include the new mount/route(s), and the test
  passes against that new literal

#### Scenario: /salud unaffected by the new mount
- GIVEN the shipped application after this change
- WHEN `GET /salud` is requested with no `Authorization` header
- THEN the response is 200, exactly as before this change

### Requirement: Token never appears in captured output
The raw service token MUST NOT appear, even partially, in logs, traces, or error output, on any
rejection or acceptance path — including the pre-body authentication boundary this change adds.
(Previously: scoped only to `exigir_token`'s own rejection/acceptance paths.)

#### Scenario: Token absent from all captured output
- GIVEN a valid request and each rejection variant already covered by `service-token-auth`
- WHEN all captured stdout/stderr/log output from those requests is inspected
- THEN the raw token string does not appear anywhere in it, even partially

#### Scenario: Token absent from output on the pre-body boundary
- GIVEN a request rejected by the new pre-body authentication boundary before its body is read
- WHEN all captured stdout/stderr/log output from that request is inspected
- THEN the raw token string does not appear anywhere in it, even partially

## ADDED Requirements

### Requirement: Authentication failures on the authenticated surface never surface as 500
Any request reaching the authenticated surface that fails the token check MUST receive the 401
response ADR 0017 defines (empty body, `WWW-Authenticate: Bearer`), never an unhandled 500.

#### Scenario: Authentication failure returns the 401 contract, not 500
- GIVEN a route inside the authenticated surface in the shipped application
- WHEN a request without a valid token reaches it
- THEN the response is 401 with an empty body and `WWW-Authenticate: Bearer`, and no 500 is returned

### Requirement: Rejection happens before the request body is read
A request to the authenticated surface carrying a missing or incorrect token MUST be rejected without
the server having consumed its body. This MUST be observable behaviourally.

#### Scenario: 401 arrives without the full body being sent
- GIVEN a request to a route inside the authenticated surface, with a missing or incorrect token,
  whose body is sent as a stream that never completes (or completes only after a long delay)
- WHEN the request is sent
- THEN the 401 response is received before the incomplete/delayed body would have finished sending
