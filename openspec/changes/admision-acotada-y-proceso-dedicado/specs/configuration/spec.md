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

### Requirement: `EJECUCIONES_MAX` is a required, positive integer
`Configuracion` MUST expose `EJECUCIONES_MAX` as a required positive integer. Startup MUST fail when
it is absent, non-numeric, zero, or negative.

#### Scenario: Missing or non-positive value fails startup
- GIVEN the `EJECUCIONES_MAX` environment variable is unset, or set to zero or a negative number
- WHEN the application starts
- THEN startup fails and no HTTP server accepts requests

#### Scenario: A positive value starts successfully
- GIVEN `EJECUCIONES_MAX` is set to a positive integer, and every other required configuration value
  is valid
- WHEN the application starts
- THEN startup succeeds

### Requirement: `TIMEOUT_EJECUCION` is a required, positive duration strictly below the portal's 2-minute cutoff
`Configuracion` MUST expose `TIMEOUT_EJECUCION` as a required positive duration. A `Configuracion`
validator MUST reject any value that is not strictly less than the portal's 2-minute request cutoff
— this relationship MUST be enforced in code, not only documented.

#### Scenario: Missing or non-positive value fails startup
- GIVEN the `TIMEOUT_EJECUCION` environment variable is unset, or set to zero or a negative value
- WHEN the application starts
- THEN startup fails and no HTTP server accepts requests

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
