# Pipeline común: los 9 pasos en orden — BACKLOG item #10

| | |
|---|---|
| **Change** | `pipeline-comun` |
| **BACKLOG item** | #10 — depends on #4, #5, #6, #7, #8, #9 |
| **Date** | 2026-08-20 |
| **Commits** | `e11349b`, `435a973` |
| **Branch** | `item-10/pipeline-comun` |
| **Mode** | Fast cycle — **the first item delivered this way** |

> **This record was reconstructed after the fact**, from the commits and the
> shipped code, not written during the session that produced the work. The
> facts below are verifiable in the tree; the narrative of *how* the decisions
> were reached is inferred from what the code and its docstrings state.

## Summary

The seam that `app/recepcion.py` had been leaving open since item #6 —
literally a `raise NotImplementedError` with a comment naming items #9 and
#10 — is closed. Steps 6-8 become `app/core/pipeline.py`, and the four
non-typed failures get their HTTP translation.

## Methodology note

This is where the process changed. From this item on, the full SDD chain
(proposal → spec → design → tasks, with their reports) was dropped by the
user's decision in favour of a three-step cycle: exploration, implementation,
verification. Two consequences that shaped everything after it:

- **No ADR per item.** The agreement: if a genuine architectural decision
  appears, raise it and the user decides. The technical memory that used to
  go into an ADR now goes into **the docstring of the module where someone
  will look for it**.
- **This item set the precedent.** `app/core/fallos_http.py` records why the
  timeout maps to 504 and the rest to 500 — a decision no prior ADR fixes.
  Commit `435a973` exists for nothing else.

## Exploration

The inputs were ADR 0011 (which names `app/core/pipeline.py` explicitly),
ADR 0020 (temporary ownership), ADR 0022 and ADR 0023 (the non-`TipoError`
failures), and the shipped modules the pipeline had to compose:
`ejecucion.py`, `empaquetado.py`, `recepcion.py`.

The question that shaped the item was **how the nine steps are divided**, and
the answer was written down honestly rather than claimed: `app/recepcion.py`
keeps steps 1-5 and step 9, because those are precisely the steps that need
`UploadFile` and a Starlette type. The `try/finally` for temp ownership does
not move either — ADR 0020 grants that ownership to a single transfer point
(`Reserva.ceder_limpieza`), and that point lives where the response inheriting
the directory is built. Claiming it in the pipeline too would create a second
owner.

## Implementation

- **`app/core/pipeline.py`** — steps 6-8 as two calls in order and nothing
  between them: `ejecutar_modulo` then `empaquetar`. **No reference to any
  concrete processor**: the only processor-shaped value crossing the signature
  is `clave: str`. No Starlette/FastAPI type, no HTTP response, nothing from
  `app/procesadores/`. It receives a bare `Path`, never a `Reserva`.
- It **catches nothing**, on purpose: a typed error from the module, a
  `FalloDeEjecucion` from the plumbing or a `SalidaMalFormada` from packaging
  propagate verbatim to the handlers registered in `crear_app()`.
- **`app/core/fallos_http.py`** (new) — the four non-typed failures translated:
  **504** for `EjecucionExpirada`, bare **500** for `FalloDelModulo`,
  `HijoMuerto` and `SalidaMalFormada`. One construction site per status code,
  empty bodies, mirroring `validacion_http.py`. `FalloDelModulo`'s traceback
  never reaches the response (ADR 0022) — it is logging material, which item
  #14 later consumed.
- Handlers registered **per concrete class**, never one over
  `FalloDeEjecucion` (ADR 0023), so a packaging bug is never reported as a
  module crash. `SalidaMalFormada` sits deliberately outside that hierarchy.
- **`app/recepcion.py`** — the pipeline call runs **inside** the `reservar()`
  block, because `empaquetar` writes the ZIP into that directory;
  `ceder_limpieza()` only on the success path, when building the
  `FileResponse`. `Content-Disposition` encoding delegated to
  `FileResponse(filename=...)`, never hand-rolled.

`TipoError` keeps its five members. The item adds no sixth and reuses none to
describe something it does not describe.

## Verification

- `tests/test_pipeline.py` — 9 tests, 213 lines.
- `tests/test_recepcion.py` heavily reworked: requests that used to assert
  `500` because they *reached the `NotImplementedError` seam* now go through
  the whole pipeline and assert real behaviour. That is the kind of test edit
  worth flagging — the old assertions were green for a reason that had just
  stopped existing.
- `ruff`, `ruff format` and `mypy --strict` clean.

The suite total at this commit is not in the record; the next recorded
figure is 306 passing at `5b3552c` (item #12).

## Decision left open at the time

Whether the portal needs 504 and 500 separated at all. The module docstring
says so plainly: a uniform 500 would also be defensible, and if the portal
decides it does not need the distinction, the change is a single
`status_code` in that file.
