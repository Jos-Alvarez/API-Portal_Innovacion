# Delta for Error Contract

## Purpose

BACKLOG item #6's first half (`borde-de-autenticacion-y-errores-http`). Closes the inherited
obligation item #3 flagged but explicitly did not solve: FastAPI's default `RequestValidationError`
handler leaks the submitted value and returns `{"detail": [...]}` instead of ADR 0014's envelope.
This spec adds the requirement that closes it; item #3's closed five-value vocabulary is unchanged.

Out of scope: file reception, name sanitisation, temporary directories and their lifecycle, the H-02
resolution, ADR 0019, items #7-#12 and #16. No new runtime dependency. Does not add or change any
route.

## ADDED Requirements

### Requirement: Request validation failures are answered outside ADR 0014's vocabulary
A `RequestValidationError` raised during request parsing or validation MUST be answered by a handler
registered inside `crear_app()` with **422 and an empty body**. It MUST NOT return FastAPI's default
`{"detail": [...]}`, and the response MUST contain neither the value the client submitted nor the
service token.

It MUST NOT carry ADR 0014's `{"tipo", "contexto"}` envelope either.

**Amended after the design phase.** An earlier draft of this requirement demanded the typed envelope.
That is not satisfiable: ADR 0014's vocabulary is closed at five values — `formato`, `tamano`,
`contenido`, `cantidad`, `clave_inexistente` — and every one of them describes a *content* failure a
processor found in a file it could read. A `RequestValidationError` is a request whose shape never
parsed; it never reached the content layer. `cantidad` comes closest and still does not fit, because
its `contexto` carries `minimo`/`maximo` from the processor contract, which an exception handler at
this layer does not have.

The shipped `error-contract` spec states that no `tipo` other than the five MUST ever appear, so
inventing a sixth is barred. An empty body follows ADR 0017's existing precedent, where the 401 was
deliberately kept outside the enum and answered with no body at all: a status that says "this request
is unusable" without claiming a vocabulary that does not describe it. ADRs outrank a spec draft, so
the requirement is amended rather than the ADR bent.

#### Scenario: Malformed body is rejected with an empty 422
- GIVEN a route with a declared request body, protected by the service-token dependency
- WHEN a request carrying a valid token is sent with a body that fails validation
- THEN the response status is 422, its body is empty, and it contains neither `detail` nor `tipo`

#### Scenario: The rejection leaks neither the submitted value nor the token
- GIVEN the same request, carrying a distinctive sentinel value in the body
- WHEN the full response, including its headers, is inspected
- THEN neither the sentinel nor the service token appears anywhere in it

#### Scenario: Handler is active in the shipped application
- GIVEN the shipped `crear_app()`
- WHEN it is constructed
- THEN a handler for `RequestValidationError` has been registered before the app is returned
