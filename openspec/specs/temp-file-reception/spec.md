# Temp File Reception Specification

## Purpose

BACKLOG item #6 (second half): the first route inside the existing `/interno` mount, receiving a
multipart upload, writing it to a server-generated temporary location, and bounding how long any
temporary can survive — resolving H-02 (Crítico, Abierto). New domain — no prior
`openspec/specs/temp-file-reception/spec.md`.

Out of scope: contract validations (#7, including the `Content-Length` cutoff H-09 leaves open),
bounded admission and the child process (#8), output packaging (#9), the pipeline (#10), the
startup registry↔database check (#11), any concrete processor (#12, #16). No requirement here
changes `service-token-auth` or `error-contract`; this domain adds a consumer of the existing mount
and existing error types.

## Requirements

### Requirement: Upload is received and described verbatim
The route MUST accept one or more multipart file uploads. For each file, count and format MUST be
checked against the resolved contract before that file's second copy (spooled upload → per-request
temporary file) runs; a file whose format is rejected MUST NOT reach the second copy. Each
remaining file's second copy MUST be bounded, aborting once bytes written exceed
`tamano_max_bytes`. For every file that completes its second copy, the route MUST populate an
`ArchivoEntrada` whose `nombre_original` is the client-supplied name verbatim and whose
`ruta_temporal` is the server-generated path.
(Previously: every uploaded file was copied to disk unconditionally, with no count/format/size
check before or during the write.)

#### Scenario: Upload written and described
- GIVEN a multipart request with one file under the upload field, sent with a valid token, whose
  count/format/size all pass the resolved contract
- WHEN the route processes it
- THEN an `ArchivoEntrada` is produced whose `nombre_original` matches the submitted name exactly
  and whose `ruta_temporal` points to a file that exists inside the per-request temporary directory

#### Scenario: A rejected file never reaches the second copy
- GIVEN a multipart request whose file count, an extension, or a tracked size fails the resolved
  contract
- WHEN the route processes it
- THEN the offending file's bytes are never written to the per-request temporary directory, and the
  matching typed error is raised

#### Scenario: Second copy stops early on overrun
- GIVEN a file whose true byte stream exceeds `tamano_max_bytes` and that reached the copy because no
  tracked size was available to reject it earlier
- WHEN its second copy runs
- THEN writing stops once the limit is crossed, no more of that file's bytes reach the per-request
  temporary directory, and the output handle is closed before the typed error is raised

### Requirement: On-disk name is never derived from client input
The on-disk filename MUST be a server-generated identifier, never built from `nombre_original` or
any part of it. A `nombre_original` containing `..`, a path separator, a drive letter, or accented
characters MUST still write only inside the per-request temporary directory, never elsewhere, and
never under a path influenced by that string. Two uploads in the same request sharing the same
`nombre_original` MUST each get their own file, with neither overwriting the other's contents.

#### Scenario: Hostile name confined to the temporary directory
- GIVEN a multipart upload whose declared filename contains `../`, an absolute path, a drive
  letter, or accented characters
- WHEN the route processes it
- THEN the written file exists only inside the per-request temporary directory, and no file appears
  at any path derived from the declared filename

#### Scenario: Duplicate names in one request do not collide
- GIVEN a multipart request with two files both declaring the same `nombre_original`
- WHEN the route processes it
- THEN both are written as distinct files with distinct contents preserved, and each
  `ArchivoEntrada` still reports the shared `nombre_original` verbatim

### Requirement: Happy-path response leaves no temporary behind
After a request's response has completed sending, no temporary file or directory created for that
request MUST remain on disk.

#### Scenario: Nothing left after a completed response
- GIVEN a request that receives a complete response
- WHEN the response finishes sending
- THEN no file or directory from that request's temporary storage remains on disk

### Requirement: A mid-stream disconnect is bounded by the sweeper, not eliminated
A response that does not finish sending (the client disconnects mid-stream) MAY leave its temporary
files behind at the moment of disconnect. A periodic sweep MUST remove any temporary older than its
configured age threshold. No temporary from a disconnected request MUST survive past that
threshold plus one sweep interval.

#### Scenario: Disconnected request's temporary is eventually removed
- GIVEN a request whose client disconnects before the response finishes sending
- WHEN the temporary's age exceeds the sweeper's configured threshold and at least one further sweep
  runs
- THEN the temporary no longer exists on disk

### Requirement: Every request today resolves to the missing-processor error
Because the contract table has no entries, a request to this route for any `clave_procesador` MUST
resolve to `ErrorClaveInexistente` with `causa="fila_ausente"` and a 500 response.

#### Scenario: Any clave_procesador yields the same typed error
- GIVEN a valid-token request to the route with any `clave_procesador` value
- WHEN it is processed
- THEN the response is 500 with `tipo: "clave_inexistente"` and `contexto.causa: "fila_ausente"`

### Requirement: The route is unreachable without the mount's token
A request to this route without a valid service token MUST receive 401 before its multipart body is
read, per the existing authenticated-mount boundary.

#### Scenario: 401 arrives without the body being read
- GIVEN a request to this route with a missing or incorrect token, whose body is sent as a stream
  that never completes
- WHEN the request is sent
- THEN the 401 response is received before the incomplete body would have finished sending

### Requirement: Service token never appears in reception's responses or logs
The raw service token MUST NOT appear, even partially, in this route's responses or in captured
logs, on any path: successful reception, the missing-processor error, or a mid-stream disconnect.

#### Scenario: Token absent across reception outcomes
- GIVEN a valid upload, a request rejected for missing token, and a disconnected upload
- WHEN all responses and captured log output are inspected
- THEN the raw token string does not appear anywhere in them, even partially

### Requirement: Shipped route set changes deliberately, pin updated
This change MUST register the reception route inside `router_interno`, changing the mount's route
set from empty to non-empty. `tests/test_seguridad_token.py`'s pinned route-set expectation MUST be
updated to the new literal set, the same deliberate-pin convention `service-token-auth` already
establishes.

#### Scenario: Pinned route-set test updated, not merely passing
- GIVEN the pinned route-set test from the prior change
- WHEN this change ships
- THEN its literal has been updated to include the new route, and the test passes against that
  updated literal

### Requirement: ADR 0020 documents the H-02 resolution
This change MUST add `adrs/0020-*.md`, MADR format matching `adrs/0011`-`0019`, documenting the
`background=` cleanup plus sweeper decision, its measured evidence (both response classes skip
cleanup on mid-stream disconnect), and its rejected alternatives (response-class swap, early-unlink,
read-into-memory).

#### Scenario: ADR present with required content
- GIVEN this change is complete
- WHEN `adrs/0020-*.md` is inspected
- THEN it documents the decision, its measured evidence, and its rejected alternatives, in MADR
  format
