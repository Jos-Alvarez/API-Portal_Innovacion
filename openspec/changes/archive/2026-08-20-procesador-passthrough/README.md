# Procesador passthrough y su ruta cáscara — BACKLOG item #12

| | |
|---|---|
| **Change** | `procesador-passthrough` |
| **BACKLOG item** | #12 — depends on #10 |
| **Date** | 2026-08-20 |
| **Commit** | `5b3552c` |
| **Branch** | `item-12/procesador-passthrough` |
| **Mode** | Fast cycle (exploration → implementation → verification) |

> **This record was reconstructed after the fact**, from the commit and the
> shipped code, not written during the session that produced the work. The
> facts below are verifiable in the tree; the narrative of *how* the decisions
> were reached is inferred from what the code and its docstrings state.

## Summary

The first processor registered in the service. It exists to **prove the pipe**
— browser → portal → FastAPI → download — with no business rule in the way.
It is also the item that first populated `REGISTRY` and `_TABLA_CONTRATOS`,
which unblocked items #11 and #13.

## Exploration

Inputs: ADR 0006 (the `Procesador` interface and where cardinality lives),
ADR 0011 (`app/procesadores/{clave}/` layout), ADR 0012 (`spawn`
preconditions), ADR 0023 (malformed output), and the shipped
`interfaz.py`, `tipos.py`, `contrato.py`, `empaquetado.py`, `registry.py`.

Findings that decided the shape:

- **Cardinality is not an attribute of the module.** ADR 0006 fixes it in the
  `procesador` row (`entradas_min`/`entradas_max`) and forbids a processor
  branching on input count. So the multi-file variant is **another contract
  row, not another code path**: one `Passthrough` class registered twice.
- **`CONTRATO_POR_DEFECTO` accepted only `xlsx`**, chosen with the real
  processor of item #16 in mind. Requiring `.xlsx` from the processor that
  exists precisely to be exercised with a trivial file would have made it
  untestable — the opposite of its reason to exist.
- **"Marked output" is defined nowhere.** Neither the PRD, the BACKLOG nor any
  ADR says what it means; they only require no business rules and a result
  verifiably different from what was uploaded.
- **No ADR grants `procesar` an output directory.** Adding one to the
  signature would amend ADR 0006, not decide something inside this item.

## Implementation

- **`app/procesadores/passthrough/modulo.py`** — one `Passthrough` class, one
  output per input, no cardinality branch. The mark is the simplest observable
  one: the input bytes preceded by `MARCA`, so a test compares
  `MARCA + original` rather than a heuristic. Copying is chunked, never
  `read_bytes()`: the input can weigh up to `tamano_max_bytes` and the RAM
  budget of item #7 exists for that reason.
- **Output directory by convention, documented**: the processor writes
  *beside its inputs*, deriving the directory from
  `entradas[0].ruta_temporal.parent` — which is exactly `reserva.directorio`.
  Writing there is what makes the cleanup ceded to the `FileResponse` sweep
  the outputs too, without this module knowing anything about
  `app.core.temporales`.
- **`app/core/contrato.py`** — two rows built from `CONTRATO_POR_DEFECTO` with
  `dataclasses.replace`, differing **only** in `entradas_min`/`entradas_max`,
  and widening `formatos_aceptados` to csv/txt/xlsx.
- **`app/registry.py`** — registration is the literal and nothing else: no
  `registrar()`, no auto-registration imports, so a processor stays importable
  without side effects (`spawn` precondition, ADR 0012).

Two decisions recorded in docstrings rather than in a new ADR, following the
precedent item #10 set:

1. **The scope of ADR 0011's invariant.** Registering a concrete processor
   turns `app/core/ejecucion.py`'s `from app.registry import REGISTRY` into a
   **transitive** `core/` → `procesadores/` edge. The decision: the invariant
   — and the CI check item #13 would later write — is bounded to **direct**
   imports. The evidence is textual and asymmetric: `TECH-DESIGN.md:291`
   qualifies the `core.db` rule with "ni directa ni transitivamente";
   `:289` does not qualify this one that way. Without that scope, the only way
   for the child to find its processor would be an import by name inside
   `core/`, which is exactly what ADR 0012 rules out.
2. **A processor must flatten the output name BEFORE prefixing the uniqueness
   index.** `_nombre_plano` in `empaquetado.py` flattens again afterwards and
   would eat the prefix, restoring the very collision the index exists to
   prevent. `nombre_original` is chosen by the client and can repeat, and
   ADR 0023 makes two names that flatten alike blow up the whole request.

The scaffolding parametrized route in `app/recepcion.py` was **not** touched.
Replacing it with the per-processor shell routes ADR 0011 places under
`app/procesadores/{clave}/` was left as a separate item — a deviation already
marked in that module's docstring since item #6.

## Verification

- `tests/test_procesador_passthrough.py` — 19 tests, 261 lines: registry
  key ↔ `Procesador.clave` consistency, the module in isolation (one output
  per input, unique names with repeated `nombre_original`, outputs written
  beside the inputs), and **the repository's first two end-to-end successes
  with a real child process**, against the real contract, with nothing
  injected.
- Suite at **306 passing**, 96 % coverage; `ruff` and `mypy --strict` clean.
- Docstrings that claimed an empty `REGISTRY` or an empty `_TABLA_CONTRATOS`
  in production were updated — they had become false with this commit.

## What this item unblocked

- **Item #11** had been postponed for lack of substrate: both `REGISTRY` and
  `_TABLA_CONTRATOS` were empty, so a coherence check had nothing to compare.
- **Item #13** got a real transitive edge to test its import-graph walker
  against, which is what stops that check from passing by not looking.
