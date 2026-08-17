# Delta for Service Token Auth

## Purpose

BACKLOG item #2: request-level 401 enforcement for a service-wide bearer token, closing every
malformed-header path without leaking the expected token, the failure reason, or timing beyond what
the caller already knows (whether it sent a header).

New domain — no existing `openspec/specs/service-token-auth/spec.md`. `service-bootstrap`
(item #1) explicitly excludes this behavior from its scope.

Out of scope: typed error contract (#3), `Procesador` ABC/registry (#4), SQL Server mirror (#5),
temp-file lifecycle (#6), contract validations (#7), bounded admission (#8), packaging (#9), the
common pipeline (#10), registry↔database check (#11). No requirement here changes
`app/core/configuracion.py`'s `token_servicio` field.

**Timing scope note**: this spec does not require identical wall-clock timing between the
absent-header path and any wrong-credential path. The absent-header path legitimately short-circuits
before the comparison and is expected to be measurably faster — that leaks nothing, since the caller
already knows whether it sent a header. Proof of comparison safety is structural (see below), never
timing-based.

## ADDED Requirements

### Requirement: Valid credential is accepted
A request whose `Authorization` header is exactly `Bearer <token>`, where `<token>` matches the
configured service token, MUST be accepted and MUST reach the protected endpoint.

#### Scenario: Valid token accepted
- GIVEN a route protected by the service-token dependency
- WHEN a request carries `Authorization: Bearer <token>` with the correct token
- THEN the request reaches the protected endpoint

### Requirement: Every rejection path returns a byte-identical response
Header absent, wrong scheme, missing space after the scheme, empty credential, irregular/extra
whitespace, non-ASCII bytes, multiple `Authorization` headers, and a well-formed but incorrect token
MUST all be rejected with the same response: status 401, an empty body, and the same header set
including `WWW-Authenticate: Bearer`. No variant MAY produce a different status, body, or header set.

#### Scenario: Identical response across all malformed variants
- GIVEN each of: no `Authorization` header, wrong scheme, missing space after scheme, empty
  credential, irregular whitespace, non-ASCII bytes, multiple `Authorization` headers, and a
  well-formed but incorrect token
- WHEN each variant is sent to a route protected by the service-token dependency
- THEN every response is 401 with an empty body and an identical header set, including
  `WWW-Authenticate: Bearer`

### Requirement: Comparison does not leak which credential is wrong
The presented credential MUST be compared to the configured token using `hmac.compare_digest` on
bytes. No length check (e.g. `len()`) MAY precede or replace that comparison.

The two sides MUST be encoded differently, and this is deliberate:

- The **presented credential** MUST be encoded with **latin-1**. Starlette decodes header values as
  latin-1, so re-encoding with latin-1 recovers the exact bytes that arrived on the wire. It is also
  a total operation — every codepoint it can produce is at most U+00FF — so it cannot raise.
- The **configured token** MUST be encoded with **UTF-8**, which is the true byte representation of
  the value the operator configured.

Encoding the presented credential with UTF-8 instead MUST NOT be done: it double-encodes any
non-ASCII token (`b"clav\xc3\xa9"` on the wire becomes `b"clav\xc3\x83\xc2\xa9"`), which would reject
a correct token with an indistinguishable 401 and no way to diagnose it.

#### Scenario: Structural proof of constant-time comparison
- GIVEN the credential-comparison code path
- WHEN inspected for the comparison call and any code preceding it
- THEN `hmac.compare_digest` is the only comparison used, and no length check precedes it

#### Scenario: A non-ASCII token is accepted
- GIVEN a configured service token containing non-ASCII characters
- WHEN a request presents that exact token in `Authorization: Bearer`
- THEN the request is accepted

### Requirement: Token never appears in captured output
The raw service token MUST NOT appear, even partially, in logs, traces, or error output, on any
rejection or acceptance path.

#### Scenario: Token absent from all captured output
- GIVEN a valid request and each rejection variant from the previous requirement
- WHEN all captured stdout/stderr/log output from those requests is inspected
- THEN the raw token string does not appear anywhere in it, even partially

### Requirement: `get_secret_value()` has exactly one call site
`app/core/seguridad.py` MUST hold the only `get_secret_value()` call in the repository, and that
call MUST NOT be an argument to a logging or string-formatting call.

#### Scenario: Single, non-logging call site verified
- GIVEN the repository source tree
- WHEN searched for `get_secret_value()` call sites
- THEN exactly one exists, in `app/core/seguridad.py`, and it is not passed to a logging or
  string-formatting call

### Requirement: No application instance is constructed with debug mode enabled
No FastAPI/Starlette application instance this change creates — including any test-only app or
router fixture — MAY be constructed with `debug=True`.

#### Scenario: Debug traceback rendering disabled
- GIVEN every application instance this change constructs, including test-only fixtures
- WHEN their construction is inspected
- THEN none pass `debug=True`

### Requirement: Access log does not surface header values
Uvicorn's default access log format MUST NOT include header values for header-bearing requests.
This MUST be verified by test, not assumed.

#### Scenario: Header-bearing request produces no header value in the access log
- GIVEN a request carrying an `Authorization` header
- WHEN the request is processed and the resulting access-log line is inspected
- THEN the log line does not contain the header value

### Requirement: Shipped application route set is unchanged
This change MUST NOT wire the service-token dependency, or any new route, into the shipped
`crear_app()`. The shipped application's route set MUST be identical before and after this change.

#### Scenario: Shipped route set unchanged
- GIVEN the shipped `crear_app()` before and after this change
- WHEN their route sets are compared
- THEN they are identical
