# Output Packaging Specification

## Purpose

BACKLOG item #9, authority ADR 0011 (names `app/core/empaquetado.py` explicitly) and TECH-DESIGN.md
pipeline step 8. New domain — no prior `openspec/specs/output-packaging/spec.md`. Converts the
`list[ArchivoSalida]` item #8's `ejecutar_modulo()` already produces atomically into the single
`ArchivoSalida` the HTTP edge (item #10) can respond with: the sole input verbatim for one output, a
flat ZIP for two or more, a typed content error before any write for zero (PRD.md lines 286-290).

Out of scope: `app/recepcion.py` wiring, `Content-Disposition`/non-ASCII filename encoding, and
constructing any `Response` (all item #10); pipeline orchestration and its own `try/finally` (item
#10); a ceiling on aggregate output size (none exists today, none introduced here); ZIP container
byte-determinism (items #15/#16, no fixture requires it today).

This domain does not modify `error-contract`'s closed `contexto` shape table. The exact
`ContextoContenido` form for the zero-output case is deferred to design (proposal Decision 4,
possibly ADR 0023); this spec fixes only the observable contract `error-contract` already
establishes for `tipo: "contenido"` — a 422 response — not the internal shape of its `contexto`.

## Requirements

### Requirement: A single output is returned verbatim
When exactly one `ArchivoSalida` is supplied, the function MUST return it unchanged: the same
`nombre_propuesto`, the same `tipo_mime`, and the same `ruta_temporal`. It MUST NOT compress, copy,
or rename it.

#### Scenario: Single output passes through unchanged
- GIVEN a list containing exactly one `ArchivoSalida`
- WHEN packaging runs
- THEN the returned `ArchivoSalida` has the identical `nombre_propuesto`, `tipo_mime`, and
  `ruta_temporal` as the input, and no ZIP file is created

### Requirement: Two or more outputs are compressed into a single flat ZIP
When two or more `ArchivoSalida` are supplied, the function MUST produce exactly one ZIP file
containing every one of the N inputs, each under a flat `arcname` — no directory components, no
embedded path separators. The returned `ArchivoSalida` MUST point at that ZIP file and carry a ZIP
`tipo_mime`.

#### Scenario: Multiple outputs produce one complete flat ZIP
- GIVEN a list of two or more `ArchivoSalida` with distinct `nombre_propuesto` values
- WHEN packaging runs
- THEN exactly one ZIP file is returned, its members are exactly those N files under their
  `nombre_propuesto`, and no `arcname` contains a path separator or directory component

### Requirement: Zero outputs raise a typed content error before any file is written
When the input list is empty, the function MUST raise an `ErrorTipificado` of `TipoError.CONTENIDO`
(HTTP 422) and MUST NOT create any file — ZIP or otherwise — before raising.

#### Scenario: Empty input raises before touching disk
- GIVEN an empty list of `ArchivoSalida`
- WHEN packaging runs
- THEN a `TipoError.CONTENIDO` error is raised, translating to a 422 response, and no file was
  created in the target directory at any point during the call

### Requirement: The ZIP is atomic — fully written and closed, or never returned
The ZIP file MUST be completely written and closed (`ZipFile.close()` without exception) before the
function returns an `ArchivoSalida` referencing it. If writing fails at any point, the function MUST
raise instead of returning, and MUST NOT return an `ArchivoSalida` referencing a partial or unclosed
file.

#### Scenario: A write failure never yields a partial ZIP
- GIVEN two or more `ArchivoSalida` and a write failure injected partway through building the ZIP
- WHEN packaging runs
- THEN the function raises rather than returning, and no `ArchivoSalida` referencing that ZIP is
  produced

#### Scenario: A successful ZIP is closed before returning
- GIVEN two or more `ArchivoSalida` with no injected failure
- WHEN packaging runs
- THEN the returned `ArchivoSalida.ruta_temporal` points at a ZIP file already fully written and
  closed at the moment of return

### Requirement: Arcnames are sanitized and duplicate names are rejected
The function MUST sanitize every `arcname` defensively — stripping path separators and `..`
components — before adding it to the ZIP. When two or more supplied `ArchivoSalida` share the same
`nombre_propuesto`, the function MUST raise an error rather than silently keeping only the last one.

#### Scenario: A hostile nombre_propuesto is confined to a flat, safe arcname
- GIVEN an `ArchivoSalida` among two or more whose `nombre_propuesto` contains a path separator or
  `..`
- WHEN packaging runs
- THEN the resulting `arcname` inside the ZIP has no path separator or `..` component

#### Scenario: Duplicate nombre_propuesto values raise instead of silently colliding
- GIVEN two `ArchivoSalida` in the same call sharing the same `nombre_propuesto`
- WHEN packaging runs
- THEN the function raises an error, and no ZIP file is left on disk silently keeping only one of
  the two

### Requirement: The ZIP is written inside the caller's reserved directory
The ZIP file MUST be written inside the directory the caller supplies — the calling
`Reserva.directorio` — never elsewhere, so its lifecycle is covered by the existing `Reserva`/sweeper
cleanup machinery (ADR 0020).

#### Scenario: The ZIP lands inside the supplied directory
- GIVEN two or more `ArchivoSalida` and a target directory
- WHEN packaging runs
- THEN the returned `ArchivoSalida.ruta_temporal` is a path located inside that exact directory
