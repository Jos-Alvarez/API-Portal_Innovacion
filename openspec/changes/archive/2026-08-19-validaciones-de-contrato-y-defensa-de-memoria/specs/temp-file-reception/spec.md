# Delta for Temp File Reception

## Purpose

BACKLOG item #7 (`validaciones-de-contrato-y-defensa-de-memoria`). The per-file loop's shipped
behavior — every upload copied unconditionally — changes to: cheap checks (count, format, tracked
size) run before a file's second copy, and the second copy itself is now bounded, aborting early if
the running total exceeds `tamano_max_bytes`. The tracked size is Starlette's own measured count, so
the pre-check normally rejects an oversized file at zero disk cost; the bounded copy is the
enforcement that remains when no tracked size is available, and the ceiling that holds for any future
caller of the copy. See `contract-validation` for the check axes and their typed-error mapping.

Out of scope: the real memory ceiling (#8), output packaging (#9), the pipeline (#10). No change to
`try/finally` cleanup, the sweeper, on-disk name generation, or the token boundary — those
requirements are unaffected and are not reproduced here.

## MODIFIED Requirements

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
