# Service Bootstrap Specification

## Purpose

BACKLOG item #1: FastAPI skeleton, tooling, and two non-negotiable startup guarantees (fail-closed
token, forced `spawn`), plus the public database-free health check resolving H-08. New domain.

Out of scope: per-request 401 / constant-time comparison (#2), error contract (#3), `Procesador`
ABC / registry (#4), SQL Server mirror (#5), registry↔database contrast (#11). `main.py` MAY
scaffold plug points but ships no live DB engine, no registry.

## Requirements

### Requirement: Tooling runs pytest end-to-end from a clean checkout
A `uv`-managed `pyproject.toml` + `uv.lock` MUST make `uv run pytest` collect, execute, and report
coverage from a clean checkout with no manual setup, and MUST wire `ruff`/`mypy` as `uv run` commands.

#### Scenario: Fresh checkout test run
- GIVEN a clean checkout with no build artifacts
- WHEN an operator runs `uv run pytest`
- THEN the suite collects, executes, and reports coverage without manual setup

### Requirement: Python version floor recorded independently of ADR 0012
`pyproject.toml` MUST declare `requires-python = ">=3.11"`; no comment/doc added here MAY cite ADR
0012 as the reason (ADR 0012 demotes 3.11 to an independent platform decision).

#### Scenario: Floor recorded without misattribution
- GIVEN `pyproject.toml` and its docs
- WHEN inspected
- THEN the floor is `>=3.11` and no comment attributes it to ADR 0012

### Requirement: Startup fails closed without a service token
The service MUST refuse to start — a raised exception or non-zero exit, never silent continuation —
when the service token environment variable is unset or empty.

#### Scenario: Token unset or empty
- GIVEN the service token environment variable is unset, or set to an empty string
- WHEN the application starts
- THEN startup fails and no HTTP server accepts requests

### Requirement: Token never appears in captured output
The service MUST NOT emit the raw service token value, in whole or in part, in logs, traces, or error
output, including the startup-failure message.

#### Scenario: Startup-failure output inspected
- GIVEN the service token is unset and startup fails
- WHEN all captured stdout/stderr/log output from that failed startup is inspected
- THEN the raw token string does not appear anywhere in it, even partially

### Requirement: `spawn` start method set before any process or connection
The effective start method MUST be `"spawn"` after importing **any** application module, not only the
entrypoint — no import path may reach application code with the method still unset. It MUST be fixed
before any process or connection is created, and repeated import (Strict TDD re-imports application
modules constantly) MUST NOT raise an unhandled error.

#### Scenario: Effective start method after any import path
- GIVEN a fresh interpreter that has imported any single application module
- WHEN `multiprocessing.get_start_method()` is queried
- THEN it returns `"spawn"`

#### Scenario: Nothing is created before the method is fixed
- GIVEN a fresh interpreter recording process, subprocess, and socket creation events from before the
  first application import
- WHEN an application module is imported
- THEN no such event was recorded while the effective start method was anything other than `"spawn"`

### Requirement: Health check is public and database-free
An unauthenticated `GET` health endpoint MUST exist, MUST require no service token, and MUST NOT
query SQL Server or any other external dependency.

#### Scenario: Succeeds without a token and with every dependency unreachable
- GIVEN no token header is supplied, and SQL Server and every other external dependency are
  unreachable
- WHEN a GET request hits the health path
- THEN the response is 200 and no connection attempt to any external dependency is made

### Requirement: Health response does not claim full functionality
The health contract MUST state that "healthy" (200 from this probe) and "fully functional" (able to
serve a processing request) are different claims, and MUST NOT treat a 200 as proof that the token
is valid beyond startup, SQL Server is reachable, registry/catalog agree, or a processor can execute.

#### Scenario: Divergence documented
- GIVEN the health endpoint's documented contract
- WHEN read by an operator
- THEN it lists each of those four things a 200 does not prove

### Requirement: No multi-worker deployment regression
Deployment scaffolding this change adds MUST NOT default to more than one Uvicorn worker
(`--workers N`) or introduce Gunicorn. If this change ships none, that absence MUST be stated
explicitly rather than left implicit.

#### Scenario: Single-worker default preserved
- GIVEN any run script, Dockerfile, or documented invocation this change adds
- WHEN inspected
- THEN none default to more than one Uvicorn worker or invoke Gunicorn

### Requirement: ADR 0016 resolves H-08
This change MUST add `adrs/0016-*.md` (MADR format matching `adrs/0011`–`0015`) documenting the
health check as a public, database-free liveness probe, and MUST update H-08's status row in
`REVISION-ADVERSARIAL.md`.

#### Scenario: ADR and tracker updated together
- GIVEN this change is complete
- WHEN `adrs/0016-*.md` and `REVISION-ADVERSARIAL.md` are inspected
- THEN the ADR documents the resolution and H-08's row no longer reads "Abierto"
