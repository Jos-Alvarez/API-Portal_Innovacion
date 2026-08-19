# Bounded Execution Specification

## Purpose

BACKLOG item #8, authority ADR 0012 (revised — no `ProcessPoolExecutor`, no pool of any kind). A
non-blocking admission gate that rejects with an immediate 503 instead of queueing, and one
dedicated `multiprocessing.Process` per execution: spawned fresh, joined with a hard timeout, and
really killed. New domain — no prior `openspec/specs/bounded-execution/spec.md`.

`app/core/ejecucion.py` ships composable primitives item #10 later orchestrates inside its own
`try/finally` — this domain does not own the request lifecycle.

Out of scope: the 9-step pipeline and its owning `try/finally` (#10); the final HTTP shape for
timeout/child-death (#10); structured operational logging of saturation rejections (#14);
calibrating `EJECUCIONES_MAX` or measuring `spawn` cost (#17); a real RAM ceiling on the child (Job
Object/cgroup/`RLIMIT_AS`); portal-side 503 UX.

## Requirements

### Requirement: Admission is rejected immediately when saturated, with no queueing and no cost paid
With every `EJECUCIONES_MAX` slot occupied, a new request MUST receive an immediate 503, MUST NOT
be queued or made to wait, MUST NOT have any of its request body read, and MUST NOT cause any
temporary file to be written.

#### Scenario: Saturated admission rejects before body or disk are touched
- GIVEN all `EJECUCIONES_MAX` admission slots are occupied
- WHEN a new request for a processor route arrives
- THEN the response is 503, no byte of that request's body is read, and no temporary file is
  created for it

#### Scenario: /salud is never subject to admission
- GIVEN all `EJECUCIONES_MAX` admission slots are occupied
- WHEN `GET /salud` is requested
- THEN the response is unaffected by admission state, exactly as when slots are free

### Requirement: Admission is checked after the token check
Admission MUST be evaluated only after the service-token check has already accepted the request, so
an unauthenticated caller can never occupy an execution slot.

#### Scenario: Invalid or absent token while saturated still returns 401, not 503
- GIVEN all `EJECUCIONES_MAX` admission slots are occupied
- WHEN a request with a missing or incorrect token is sent to a processor route
- THEN the response is 401, and no admission slot is acquired or consumed by that request

### Requirement: The admission slot releases on all four exit paths
An acquired admission slot MUST be released after clean success, after the module raises a typed
error, after the module raises an untyped exception, and after a timeout — with no path capable of
leaving the slot held.

#### Scenario: Slot released after clean success
- GIVEN an admission slot is acquired and the child module completes normally
- WHEN the execution finishes
- THEN the slot is available for a subsequent request

#### Scenario: Slot released after a module-raised typed error
- GIVEN an admission slot is acquired and the child module raises a typed error
- WHEN the execution finishes
- THEN the slot is available for a subsequent request

#### Scenario: Slot released after an untyped module exception
- GIVEN an admission slot is acquired and the child module raises an exception that is not a typed
  error
- WHEN the execution finishes
- THEN the slot is available for a subsequent request

#### Scenario: Slot released after a timeout
- GIVEN an admission slot is acquired and the child does not finish within `TIMEOUT_EJECUCION`
- WHEN the timeout is handled
- THEN the slot is available for a subsequent request

### Requirement: Each execution runs in its own dedicated, never-reused process
Every execution MUST run in one `multiprocessing.Process` created fresh under the `spawn` start
method, never drawn from or returned to a pool, and never reused for a later execution. Only file
paths and scalar values (never file bytes, never a serialized `Procesador` instance) MUST cross
into the child.

#### Scenario: Two concurrent executions get two independent processes
- GIVEN two executions admitted at the same time
- WHEN each runs
- THEN each is backed by its own `multiprocessing.Process`, and no process instance is shared or
  reused between them

#### Scenario: Only paths and scalars cross the process boundary
- GIVEN a request with uploaded files already saved to a per-request temporary directory
- WHEN the child process is started
- THEN the arguments it receives are file paths and scalar values only, never the raw file bytes

### Requirement: The result channel surfaces the child's outcome, including its traceback
The child MUST return its result to the parent through a `Pipe`: either the produced output file
paths, or a raised typed error, or the module's exception together with its traceback. The parent
MUST surface a raised exception and its traceback rather than swallowing it or replacing it with a
generic failure.

#### Scenario: Successful child returns output paths
- GIVEN a child module that completes and produces output files
- WHEN the parent reads the result channel
- THEN it receives the output file paths

#### Scenario: A module exception's traceback reaches the parent
- GIVEN a child module that raises an exception with a traceback
- WHEN the parent reads the result channel
- THEN the parent has access to that exception's traceback, not just a bare failure signal

### Requirement: A hung child is really terminated on timeout, not merely un-awaited
When a child does not finish within `TIMEOUT_EJECUCION`, the parent MUST call `join(TIMEOUT_EJECUCION)`
and, if the child has not finished, MUST call `kill()` on it. After that call, the child MUST be
confirmed no longer alive — a returned `.join()` alone MUST NOT be treated as termination.

#### Scenario: Child confirmed dead after a timeout kill
- GIVEN a child process that runs longer than `TIMEOUT_EJECUCION`
- WHEN the timeout elapses and the parent kills it
- THEN inspecting the process afterward shows it is no longer alive

### Requirement: An anomalous child exitcode produces a distinguishable, contained failure
When a child process terminates with a nonzero or otherwise anomalous exitcode (for example,
OOM-killed) without going through the normal result-channel path, this MUST produce a distinguishable
controlled failure. The API worker process MUST survive. Remaining admission capacity MUST NOT be
wedged. No other in-flight execution MUST be affected.

#### Scenario: An anomalous exitcode is contained to its own execution
- GIVEN a child process that terminates via `os._exit(N)` with a nonzero code, and a second,
  unrelated execution running concurrently
- WHEN the anomalous exitcode is handled
- THEN the API worker keeps serving requests, the admission slot the anomalous child held is
  released, and the concurrent execution completes unaffected

### Requirement: This domain introduces no sixth `TipoError` value
None of saturation, timeout, or anomalous child death MUST be represented as a `TipoError` member.
`TipoError` MUST remain exactly the five values fixed by ADR 0014 after this change.

#### Scenario: TipoError is unchanged by this domain
- GIVEN `TipoError` after this change ships
- WHEN its members are inspected
- THEN there are exactly five, none introduced by saturation, timeout, or child-death handling
