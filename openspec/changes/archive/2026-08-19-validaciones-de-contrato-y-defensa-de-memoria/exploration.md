# Exploration — Validaciones de contrato y defensa de memoria

- **Change**: `validaciones-de-contrato-y-defensa-de-memoria`
- **Source**: `BACKLOG.md` item #7
- **Depends on**: item #6 (`recepcion-y-ciclo-de-vida-de-temporales`), archived and shipped
- **Methodology**: Strict TDD disabled. Full SDD chain runs.

## Current State

No validation module exists yet. `app/core/validaciones.py` does not exist — it is only a name
reserved by TECH-DESIGN.md's structure diagram (line 65) and ADR 0011 (line 33): "validaciones.py
# cantidad, formato, tamaño, tamaño descomprimido". `app/core/errores.py` (ADR 0014) is the only
closed error vocabulary and must be reused, never redefined.

The exact seam is in `app/recepcion.py`, function `recibir()` (lines 66-101). Today:
1. The `for indice, carga in enumerate(archivos):` loop unconditionally copies every uploaded file
   to disk via `_copiar()` (a 1MB-chunked `shutil.copyfileobj`), building `entradas: list[ArchivoEntrada]`.
2. Line 95: `del entradas  # costura del ítem #7: consumido por la validación de contrato` — an
   explicit, deliberate placeholder marking exactly where item #7's validation call goes.
3. Lines 96-98: `contrato = obtener_contrato(clave_procesador)`; if `None`, raises
   `ErrorClaveInexistente(causa="fila_ausente")`.
4. Line 101: `raise NotImplementedError` — unreachable today, explicitly left as the seam for items
   #9/#10.

Critical structural fact: **all files are already fully copied to disk before `del entradas` runs.**
`_copiar()` runs unconditionally inside the loop, before any validation call exists.

`openspec/changes/archive/2026-08-18-recepcion-y-ciclo-de-vida-de-temporales/specs/temp-file-reception/spec.md`
(item #6, closed) explicitly excludes this: "Out of scope: contract validations (#7, including the
`Content-Length` cutoff H-09 leaves open)". Item #7 owns everything downstream of "file already on
disk, contrato not yet resolved."

## Where the limits come from

`app/core/contrato.py` `ContratoProcesador` (frozen dataclass) has exactly: `entradas_min`,
`entradas_max`, `formatos_aceptados: tuple[str, ...]`, `tamano_max_bytes`, `tamano_max_total_bytes`,
`activo`. `obtener_contrato(clave_procesador)` returns this or `None` (currently always `None`,
empty `_TABLA_CONTRATOS`). This covers cantidad, formato, tamaño-por-archivo, and tamaño-total —
four of item #7's five axes.

**Not present anywhere: a declared-uncompressed-size / RAM-budget field.** `ContratoProcesador` has
no such field, and `app/core/configuracion.py` has only `token_servicio`. ADR 0006 heritage
(`L:\App_Portal\adrs\0006-procesadores-registro-modulos.md` line 145-146) treats the RAM ceiling as
a global worker-level constant, not a per-processor row value. The existing precedent for this kind
of value is `app/core/temporales.py`'s `UMBRAL_DE_EDAD`/`INTERVALO_DE_BARRIDO`: adjacent `Final`
module constants, deliberately not `Configuracion` fields, "because no hay necesidad operativa
identificada de ajustarlas por entorno."

## The Content-Length problem — verified against installed library source

`app/recepcion.py` uses `Annotated[list[UploadFile], File()]`. Reading the installed
`starlette==1.6.0` source (`formparsers.py`, `MultiPartParser`):

- `max_part_size` (default 1MB) is checked in `on_part_data` only when `self._current_part.file is
  None` — i.e. only for non-file form *fields*. File-part bytes go straight to
  `self._file_parts_to_write` with zero size check anywhere in the write path
  (`UploadFile.write()` only tracks `self.size`, no ceiling).
- `max_files`/`max_fields` cap *counts*, never bytes.
- `Request.form()` accepts `max_part_size`, but FastAPI's `File()`/`UploadFile` dependency machinery
  does not expose or wire it.

**Conclusion, verified not guessed: today there is no enforced upper bound anywhere in this stack on
total bytes read for a file upload.** A client with a missing or lying `Content-Length` can stream
gigabytes; Starlette fully parses and spools it all before `recibir()` gets control, regardless of
what item #7 adds inside the route function. This is H-09 (Advertencia, `REVISION-ADVERSARIAL.md`
lines 327-345). No uvicorn-level body-size limit is wired either.

## The zip-bomb axis — scope boundary is explicit and narrow

ADR 0006 heritage (line 140-150): the defense is inspecting ZIP central-directory metadata (declared
uncompressed size, via `zipfile`, since `.xlsx`/`.docx` are ZIP containers) and summing against a
RAM-budget constant, before instantiating the processor module — never actually decompressing.
`REVISION-ADVERSARIAL.md` H-04 (Crítico, lines 226-250) calls the "25MB compressed cap is enough"
claim directly false: a declared-ZIP-size check is a number the attacker controls, and is not the
magnitude that actually exhausts RAM (the resulting `DataFrame`, not the raw XML). H-04's real fix —
a hard memory ceiling on the child process — belongs to item #8, not item #7. Item #7 owns exactly
one thing on this axis: the declared-size-vs-budget check as a first line of defense, necessary but
insufficient, with the real backstop deferred to #8.

## Error-enum mapping and a real gap the closed enum cannot express

| Item #7 failure | Maps to | HTTP |
|---|---|---|
| Count outside `entradas_min`/`entradas_max` | `ErrorCantidad` | 422 |
| Extension not in `formatos_aceptados` | `ErrorFormato` | 422 |
| One file over `tamano_max_bytes` | `ErrorTamano` | 422 |
| Sum over `tamano_max_total_bytes` | `ErrorTamano`, but `ContextoTamano` (`{archivo, limite_bytes,
  recibido_bytes}`, ADR 0014 verbatim shape) does not name a single `archivo` for a sum violation |
  422 |
| Declared-uncompressed-size over RAM budget | Best fit `ErrorTamano`; TECH-DESIGN step 5 says
  "tipo tamaño/contenido" without picking one | 422 |

`ContextoTamano` requires `recibido_bytes: int`. A mid-stream abort (client claims small size, sends
huge stream, cut mid-read) can reuse this shape with `recibido_bytes` as a best-effort count of
bytes actually read before the abort — documented as an approximation, not the true total. ADR 0012
already decided **not** to add new `TipoError` values (H-05). The context payloads are not closed by
that decision, only the enum is.

## Ordering

Cheap-before-expensive is architecturally blocked at the multipart layer: FastAPI/Starlette's
`File()` dependency has already spooled every byte of every file before `recibir()` runs. Within
what item #7 *can* control:
1. Cantidad (cheapest) — check `len(archivos)` against contrato before any per-file work.
2. Formato (cheap, string-only, uses existing `_formato()`).
3. Tamaño per-file and total — using `carga.size` (Starlette already tracks this from the spool
   phase) before calling `_copiar()` a second time, so a rejected file never gets copied into the
   per-request directory.
4. Declared-uncompressed-size (zip-bomb) — necessarily last, requires opening the on-disk file with
   `zipfile`.

Given item #6's `try/finally` guarantee, validation runs inside the same `with reservar() as
reserva:` block — no lifecycle changes needed.

## Testing

`pytest` + `pytest-cov`, `tests/test_recepcion.py` (behavioral, no AST/structural checks) and
`tests/test_contrato_estatico.py`. Command must be `uv run pytest` — the system `python` resolves to
a stale FastAPI install. `_TABLA_CONTRATOS` is empty, so tests need either monkeypatching
`app.core.contrato._TABLA_CONTRATOS` or exercising validation functions directly with a hand-built
`ContratoProcesador`.

## Risks / Open Questions (resolved in proposal.md)

1. How far item #7 closes H-09 given the confirmed Starlette parsing gap.
2. Which `TipoError`/`Contexto` shape a mid-stream-abort and a sum-violation map to.
3. Whether the RAM-budget constant lives in `core/validaciones.py` as a `Final`, or gets added to
   `ContratoProcesador`.

## Approaches

1. **Declarative `File()` stays; validation module inserted at the existing seam, Content-Length
   defense is best-effort per-chunk inside `_copiar`.** Smallest change, stays inside `app/core/` +
   `app/recepcion.py`. Does not close H-09's real gap — the first Starlette-level multipart parse
   still has zero ceiling.
2. **Add an ASGI-level byte-counting guard ahead of FastAPI's form parsing.** Closes the true H-09
   gap, but new middleware is new architectural surface competing with `AutenticacionDeBorde`, and
   reopens the closed-enum question. Effort Medium-High.
3. **Drop `Annotated[list[UploadFile], File()]`; parse the form manually with `await
   request.form(max_part_size=..., max_files=...)`.** Closes the gap with library-supported
   parameters, but changes the shipped `recibir()` signature/style from item #6 and needs
   re-verification against actual runtime behavior, not just static source reading.

### Recommendation

Approach 1 for the contract-based checks — matches the backlog line and the existing seam. Item #7
must explicitly scope out full closure of H-09 as a documented limitation. Approach 2 rejected as
disproportionate scope creep. Approach 3 evaluated in the proposal and explicitly deferred (see
`proposal.md`, Decision 1).

## Key Learnings

1. Starlette 1.6.0's `MultiPartParser.on_part_data` checks `max_part_size` only for non-file form
   fields, never for file parts — H-09's Content-Length gap is real and unclosed by the framework.
2. `app/recepcion.py` line 95 (`del entradas`) is an explicit seam comment marking exactly where
   item #7's validation call belongs.
3. `ContratoProcesador` has no field for the declared-uncompressed-size RAM budget; ADR 0006
   heritage treats it as a global worker-level constant, not a per-processor value.
4. ADR 0014's closed five-value error enum has no clean home for a mid-stream Content-Length abort
   or a total-sum size violation; the context payloads are not closed by that decision, only the
   enum member set is.
