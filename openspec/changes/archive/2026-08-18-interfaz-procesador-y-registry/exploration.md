# Exploration — Interfaz `Procesador`, tipos de archivo y registry

- **Change**: `interfaz-procesador-y-registry`
- **Source**: `BACKLOG.md` item #4
- **Phase**: explore (read-only; no proposal, no implementation)
- **Artifact store**: hybrid (this file + Engram `sdd/interfaz-procesador-y-registry/explore`)
- **Depends on**: item #3 `contrato-de-errores-tipificados`, archived and shipped
- **Methodology**: Strict TDD disabled. The full SDD chain still runs.

## Current state

`main` at `210d709`, clean, 74 tests green. Shipped: `app/arranque.py`, `app/core/configuracion.py`,
`app/core/seguridad.py`, `app/core/errores.py`, `app/salud.py`, `app/main.py`. Nothing exists under
`app/procesadores/` and there is no `app/registry.py`.

Precedent from items #1–#3: every deliverable ships as a library plus a test-only surface, with
nothing wired into `crear_app()`.

## The ABC signature is fixed by an inherited ADR — verified verbatim

From `L:\App_Portal\adrs\0006-procesadores-registro-modulos.md`, which **outranks** every local ADR:

```python
class Procesador(ABC):
    clave: str

    @abstractmethod
    def validar(self, archivos: list[ArchivoEntrada]) -> ErrorTipificado | None:
        """Valida el conjunto (cantidad, formato, tamaño, contenido); None si es válido."""

    @abstractmethod
    def procesar(self, archivos: list[ArchivoEntrada]) -> list[ArchivoSalida]:
        """Ejecuta la transformación y devuelve uno o más archivos resultantes."""

REGISTRY: dict[str, Procesador] = {...}
```

Two things follow that are not negotiable:

- **`validar` RETURNS `ErrorTipificado | None`. It does not raise.** This is easy to get wrong,
  because item #3 shipped a raise-based mechanism with a class-keyed handler. Both are correct at
  their own layer: `validar` hands the error back, and the pipeline (item #10) is what raises it so
  the HTTP handler can serialise it. Item #4 must not "fix" the signature to match item #3.
- **Both methods take and return lists**, always. ADR 0006 is explicit that this exists to keep one
  code path with no special branches; cardinality is not an attribute of the module, it is declared
  in the `procesador` row.

## The file types — what is actually written down

`TECH-DESIGN.md`, verbatim, and nothing more anywhere:

- **`ArchivoEntrada`** — nombre original, ruta del temporal en disco, tamaño comprimido, formato.
- **`ArchivoSalida`** — nombre propuesto, ruta del temporal, tipo MIME.

Field *types* (`str` versus `Path`) are unspecified. That is an open decision, not a finding.

## The process boundary — the constraint that shapes everything

`TECH-DESIGN.md` states the entries cross to the child **"como rutas, no como bytes (ADR 0012)"**, and
ADR 0012 adds that the result returns through a `Pipe`, **"nunca bytes de archivo"**, and that
everything crossing to the child must be serialisable.

Verified by execution through `uv run` (the pinned interpreter), not by recall:

```
pickle round-trip on a frozen, slots dataclass holding str/Path/int/str: True
effective start method: spawn
```

So plain data satisfies the constraint. The types must never hold an open file handle, a socket, or
anything else unpicklable — paths and scalars only. Whatever item #4 decides here, **item #8
inherits it**, because item #8 is what actually crosses the boundary.

One question no document answers, and which item #4 does not have to solve: whether the child
re-derives the processor instance (re-import plus registry lookup) or receives a pickled live
instance. That belongs to `core/ejecucion.py` in item #8. It is worth a docstring caveat on the ABC so
item #8 does not discover it late.

## The ADR 0011 invariant versus the registry — resolved by placement

ADR 0011, verbatim: *"`core/` nunca importa nada de `procesadores/`… `procesadores/` conoce a `core/`;
`core/` no sabe que `procesadores/` existe."*

A registry mapping `clave -> Procesador` must reference concrete processors, so it cannot live in
`core/`. Both ADR 0011's file tree and `TECH-DESIGN.md`'s place it at **`app/registry.py`**, a sibling
of `core/` and `procesadores/`. That is the only placement where both constraints hold: `registry.py`
may import the ABC from `core/` and the concrete modules from `procesadores/`, while `core/` stays
ignorant of both.

Item #13's CI check will police exactly this, so the placement decided here is what that check
encodes. `registry.py` itself is legitimately outside the rule.

## What item #4 can honestly ship

No concrete processor exists — those are items #12 and #16 — so the registry ships **real but empty**:
`REGISTRY: dict[str, Procesador] = {}`. The deliverable is the ABC, the two file types, and the typed
empty registry, proven by a test-only fake `Procesador` that demonstrates abstractness, list shapes,
and that it type-checks into `dict[str, Procesador]`.

That matches items #1–#3 exactly, including item #3's own note that it imports nothing from
`app/procesadores/`, preserving ADR 0011's invariant by construction.

## Open decisions for the proposal

1. **`dataclass` versus pydantic `BaseModel`** for the file types. A frozen stdlib dataclass is
   trivially picklable, dependency-free, and matches `errores.py`'s precedent of not adding a runtime
   validation layer for internal carriers. Recommended.
2. **Where the file types live** — inside `interfaz.py` (the literal reading of the file tree) or a
   separate `core/tipos.py`.
3. Field types: `str` versus `Path` for the temporary-file paths.

## Adversarial review

`REVISION-ADVERSARIAL.md` has no open finding disputing the ABC signature, the file-type fields, or
the registry placement — ADR 0011's two-package split is recorded as having survived the review.
H-11 (`salida_esperada` read and unused) touches a postcondition on what `procesar` returns, but it is
pipeline territory, item #10, not this one.

## Minor documentation drift, non-blocking

`TECH-DESIGN.md`'s file-tree comments label the passthrough processor "ítem #11" and `Contado_Carga`
"ítem #12", which does not match `BACKLOG.md`'s numbering (#12 and #16). Worth knowing if a later
phase cites those lines.
