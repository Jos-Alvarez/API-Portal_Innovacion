# Contract Validation Specification

## Purpose

BACKLOG item #7. Fills the `app/recepcion.py:95` seam (`del entradas  # costura del ítem #7`) with
cantidad/formato/tamaño-per-file/tamaño-total checks against `ContratoProcesador`
(`app/core/contrato.py`), plus a first-line defense against declared-uncompressed-size zip bombs.
New domain — no prior `openspec/specs/contract-validation/spec.md`.

Out of scope: the real memory ceiling on the child process (Job Object/cgroup/`RLIMIT_AS`) — item
#8; this domain's declared-size check is a first line of defense only, H-04 stays partially open. A
true byte-level cutoff at the ASGI/`receive()` layer is deferred; H-09 stays declared open (Decision
1, proposal.md) — this domain defends disk, not Starlette's own unbounded first spool. Output
packaging (#9), pipeline orchestration (#10). No change to item #6's temporary-file lifecycle: a
validation failure raises a typed error mid-loop, already covered by the existing `finally:
reserva.limpiar()`. No sixth `TipoError` value (ADR 0014 stays closed at five).

## Requirements

### Requirement: Processor contract resolves before any per-file validation or write
The route MUST resolve `clave_procesador` via `obtener_contrato` and raise `ErrorClaveInexistente`
(`causa="fila_ausente"`) for a `None` result before evaluating count, format, size, or performing
any file's second copy (spooled upload → per-request temporary file).

#### Scenario: Unknown key rejected before any second copy
- GIVEN a request with an unregistered `clave_procesador` and one or more multipart files
- WHEN the request is processed
- THEN the response is 500 `clave_inexistente` and no file reaches the per-request directory's
  second copy

### Requirement: File count is checked before any per-file work
The route MUST compare the uploaded file count to the resolved contract's `entradas_min`/
`entradas_max` and raise `ErrorCantidad` for a count outside that range before any file's format,
size, or second copy is evaluated.

#### Scenario: Out-of-range count rejected before per-file checks
- GIVEN a resolved contract and a request whose file count is below `entradas_min` or above
  `entradas_max`
- WHEN the request is processed
- THEN the response is 422 `cantidad` reporting the contract's `minimo`/`maximo` and the received
  count, and no file reaches the second copy

### Requirement: File format is checked before size or the second copy
For each file, the route MUST compare its extension against `formatos_aceptados` and raise
`ErrorFormato` for the first non-matching file before that file's size is evaluated or its second
copy occurs.

#### Scenario: Rejected format stops before the second copy
- GIVEN a resolved contract and a file whose extension is not in `formatos_aceptados`
- WHEN the request is processed
- THEN the response is 422 `formato` naming that file and its extension, and that file's bytes
  never reach the second copy

### Requirement: Per-file size is checked using the tracked upload size before the second copy
For each file that passes format, the route MUST compare `carga.size` against `tamano_max_bytes`
before performing that file's second copy, whenever `carga.size` is present. `carga.size` is the
byte count Starlette measured while spooling the part — never a client declaration — so this check
is authoritative and costs no disk. `carga.size` is typed `int | None`; when it is `None` this check
MUST be skipped and the bounded second copy becomes the sole enforcement for that file.

#### Scenario: Oversize file rejected before the second copy
- GIVEN a resolved contract and a file whose `carga.size` exceeds `tamano_max_bytes`
- WHEN the request is processed
- THEN the response is 422 `tamano` naming that file with `contexto.recibido_bytes` equal to
  `carga.size`, and that file's second copy never runs — zero bytes reach the per-request directory

#### Scenario: Absent tracked size defers to the bounded copy
- GIVEN a resolved contract and a file whose `carga.size` is `None`
- WHEN the request is processed
- THEN no pre-check rejection occurs on size grounds, and the file's enforcement happens entirely
  inside the bounded second copy

### Requirement: The second copy is bounded and aborts early on overrun
The second copy MUST stop reading as soon as the bytes written exceed `tamano_max_bytes`,
independently of whether a pre-check ran, and MUST then raise `ErrorTamano`. Overshoot is bounded by
one chunk: the block that crosses the limit is written whole rather than split, so `recibido_bytes`
is a real count strictly greater than `limite_bytes` and the response says something true about what
arrived. `recibido_bytes` MUST never be an estimate. The ceiling MUST hold even for a call site that
performed no pre-check, and the output handle MUST be closed before the error is raised so the
partially-written file can be removed synchronously.

#### Scenario: Copy aborts mid-write when no tracked size was available
- GIVEN a file whose `carga.size` was `None` and whose true byte stream exceeds `tamano_max_bytes`
- WHEN the second copy runs
- THEN it stops writing once the limit is crossed, the response is 422 `tamano`, and
  `contexto.recibido_bytes` equals the bytes actually written

#### Scenario: The ceiling does not depend on the caller
- GIVEN the bounded copy is invoked directly with an oversized source and no prior size check
- WHEN it runs
- THEN it still stops at the limit, closes its output handle before raising, and reports the real
  byte count

### Requirement: Total size across all accepted files is checked against the contract
The route MUST raise `ErrorTamano.total()` when the batch's summed bytes exceed
`tamano_max_total_bytes`, even when every individual file is within `tamano_max_bytes`. Two passes
serve this: a declared pre-pass over `carga.size` before any copy, which MUST run only when every
file in the batch reported a size; and a measured pass over actually-copied bytes, re-evaluated
after each file's copy. The measured pass is the authority — it MUST run regardless of whether the
pre-pass ran — and the pre-pass is an optimisation that keeps a doomed batch from being written at
all.

#### Scenario: Sum over the total limit rejected before any copy
- GIVEN a batch of files each within `tamano_max_bytes`, all reporting a `carga.size`, whose sum
  exceeds `tamano_max_total_bytes`
- WHEN the request is processed
- THEN the response is 422 `tamano` with `ContextoTamanoTotal` populated (`archivos`,
  `limite_bytes`, `recibido_bytes`), not `ContextoTamano`, and no file reaches the second copy

#### Scenario: Sum over the total limit caught after copying when sizes were absent
- GIVEN a batch in which at least one file reports no `carga.size`, whose copied bytes sum over
  `tamano_max_total_bytes`
- WHEN the request is processed
- THEN the measured check raises `ErrorTamano.total()` after the offending file's copy, before any
  further file is copied

### Requirement: Declared uncompressed size is checked against a RAM budget without decompressing
For each file that passes count/format/size, the route MUST read its ZIP central-directory metadata
to sum declared uncompressed entry sizes and raise `ErrorTamano` when that sum exceeds a
module-level `Final` RAM-budget constant declared in `app/core/validaciones.py` (never a
`ContratoProcesador` field), without decompressing any entry's content.

#### Scenario: Declared-size zip bomb rejected without decompression
- GIVEN a file whose ZIP central directory declares an uncompressed size over the RAM-budget
  constant
- WHEN the request is processed
- THEN the response is 422 `tamano` naming that file, and no entry's compressed content is
  decompressed to reach that result

### Requirement: The declared-size check is a first line of defense, not a memory ceiling
This domain MUST NOT be represented as closing H-04 in full. A file whose ZIP central directory
understates its true decompressed size MAY still exceed the RAM budget once a downstream processor
decompresses it; that gap is closed by item #8, not this domain.

#### Scenario: Boundary documented, not oversold
- GIVEN this domain's ADR and tests
- WHEN they are inspected
- THEN neither claims this check prevents an OOM from a real decompression bomb
