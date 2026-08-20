# Configuration Specification

## Purpose

BACKLOG item #8. `app/core/configuracion.py`'s `Configuracion` class already exists (shipped by
item #1, holding `token_servicio`) but its docstring explicitly reserves `EJECUCIONES_MAX` and
`TIMEOUT_EJECUCION` for this item and neither field exists yet. This is a new domain spec — no
prior `openspec/specs/configuration/spec.md` — covering only these two new fields and the
relationship between them and the portal's request-lifetime cutoff; it does not restate
`token_servicio`'s existing behavior, which belongs to `service-bootstrap` and `service-token-auth`.

Out of scope: calibrating real values for either field (item #17); any change to `token_servicio`'s
existing fail-closed startup behavior.

## Requirements

### Requirement: `EJECUCIONES_MAX` is a bounded positive integer with a conservative default
`Configuracion` MUST expose `EJECUCIONES_MAX` as a positive integer bounded at both ends, carrying a
conservative placeholder default so an unset value does not block startup. Startup MUST fail when it
is present but non-numeric, zero, negative, or above the upper bound.

Unlike `token_servicio`, this field is NOT required: a secret has no safe default, a concurrency
ceiling does. Forcing every deployment to declare a number nobody has measured yet (item #17 owns
calibration) only invites an invented one. The upper bound is what makes `EJECUCIONES_MAX` the
service's real concurrency knob — above it, anyio's default thread limiter would become the true
ceiling instead.

#### Scenario: Absent value falls back to the placeholder default
- GIVEN the `EJECUCIONES_MAX` environment variable is unset
- WHEN the application starts
- THEN startup succeeds using the conservative placeholder default

#### Scenario: A present but invalid value fails startup
- GIVEN `EJECUCIONES_MAX` is set to zero, a negative number, a non-numeric string, or a value above
  the upper bound
- WHEN the application starts
- THEN startup fails and no HTTP server accepts requests

#### Scenario: A valid value starts successfully
- GIVEN `EJECUCIONES_MAX` is set to a positive integer within bounds, and every other required
  configuration value is valid
- WHEN the application starts
- THEN startup succeeds

### Requirement: `TIMEOUT_EJECUCION` is a positive duration strictly below the portal's 2-minute cutoff, with a conservative default
`Configuracion` MUST expose `TIMEOUT_EJECUCION` as a positive duration carrying a conservative
placeholder default, so an unset value does not block startup. A `Configuracion` validator MUST
reject any value that is not strictly less than the portal's 2-minute request cutoff — this
relationship MUST be enforced in code, not only documented.

The field MUST accept both a bare number of seconds and an ISO 8601 duration. Pydantic's own
`timedelta` parser accepts only ISO 8601, and rejecting `TIMEOUT_EJECUCION=60` — the form an
operator would reach for first — would surface as a failed startup at deployment time.

#### Scenario: Absent value falls back to the placeholder default
- GIVEN the `TIMEOUT_EJECUCION` environment variable is unset
- WHEN the application starts
- THEN startup succeeds using the conservative placeholder default

#### Scenario: Present but non-positive value fails startup
- GIVEN `TIMEOUT_EJECUCION` is set to zero or a negative value
- WHEN the application starts
- THEN startup fails and no HTTP server accepts requests

#### Scenario: Both a bare seconds value and an ISO 8601 duration are accepted
- GIVEN `TIMEOUT_EJECUCION` is set to a bare number of seconds, or to the equivalent ISO 8601
  duration, both strictly below the cutoff
- WHEN the application starts
- THEN startup succeeds and both forms resolve to the same duration

#### Scenario: A value at or above the portal's 2-minute cutoff fails startup
- GIVEN `TIMEOUT_EJECUCION` is set to a value equal to or greater than 2 minutes
- WHEN the application starts
- THEN startup fails with a validation error naming the violated relationship

#### Scenario: A value strictly below the cutoff starts successfully
- GIVEN `TIMEOUT_EJECUCION` is set to a positive value strictly less than 2 minutes, and every other
  required configuration value is valid
- WHEN the application starts
- THEN startup succeeds

### Requirement: Both fields are documented as conservative placeholders, not measured data
Any default or example value shipped for `EJECUCIONES_MAX` or `TIMEOUT_EJECUCION` MUST be documented
as a conservative placeholder pending item #17's calibration, never presented as measured or tuned
data.

#### Scenario: Placeholder status is documented
- GIVEN `Configuracion`'s source and its accompanying documentation for these two fields
- WHEN inspected
- THEN both are described as conservative placeholders pending calibration, not measured values
