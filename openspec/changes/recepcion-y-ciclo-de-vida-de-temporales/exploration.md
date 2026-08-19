# Exploration — Recepción y ciclo de vida de temporales

- **Change**: `recepcion-y-ciclo-de-vida-de-temporales`
- **Source**: `BACKLOG.md` item #6
- **Depends on**: items #1 and #3, archived and shipped
- **Methodology**: Strict TDD disabled. Full SDD chain runs.
- **State**: `main` at `b4eff42`, clean, 95 tests green.

## H-02 — the critical open finding, now measured

`REVISION-ADVERSARIAL.md` H-02 (Crítico, **Abierto**) says the pipeline's `try/finally` deletes the
temporary before ASGI streams it, breaking the happy path rather than an edge case. The review ranks
it first to fix and notes that inherited ADR 0006 says to delete *"una vez enviada la respuesta
HTTP"*, which is not what a `try/finally` does.

Verified against the installed Starlette **1.6.0** / FastAPI **0.141.1** through `uv run`:

```
FileResponse._handle_simple      OSError guard: False   disconnect guard: False
StreamingResponse.__call__       OSError guard: True    disconnect guard: True
```

Both classes run `self.background()` **after** the send loop:

```python
# FileResponse.__call__ and StreamingResponse.__call__, both end with:
if self.background is not None:
    await self.background()
```

**The important nuance, which is easy to get wrong.** `StreamingResponse` does guard the send loop —
but it converts the failure into `raise ClientDisconnect()`. The exception still propagates, so
`self.background()` is still skipped. `FileResponse` has no guard at all and propagates the raw
`OSError`. **Both leak the temporary on a mid-stream client disconnect.** Switching response classes
does not fix this, and anyone "solving" H-02 by swapping `FileResponse` for `StreamingResponse` has
changed nothing about the hole.

### The real option set

| Option | Happy path | Client disconnects mid-stream | Cost |
|---|---|---|---|
| `try/finally` in the endpoint | **Broken** — file deleted before it is sent | n/a | This is the current documented design, and it does not work |
| `background=` cleanup on the response | Works — runs after the full body is sent | **Leaks** — the send loop raises, `background()` never runs | "Zero temporaries after the response" becomes conditional on a clean disconnect |
| Read the result into memory, then clean | Works | Works | Contradicts why temporaries are on disk at all (ADR 0006); reintroduces the RAM pressure the design exists to avoid |
| A sweeper independent of the response | Works | Works | "Zero temporaries after the response" weakens to "zero within N minutes"; needs an age policy and a place to run |

The first is broken. The second is what the review proposed and it has a hole nobody had measured.
The third and fourth each trade a different guarantee. **No option preserves the literal acceptance
criterion "after the response the directory has no files" without cost.** This is a product decision,
not a technical one.

Note also that early-unlink — open the handle, unlink the directory entry, keep streaming — is a POSIX
trick that does not work on Windows, and ADR 0012 leaves the deployment target undecided (container
versus native Windows service). Any option depending on it would bind that decision.

## The three inherited obligations, with source-level evidence

1. **`registrar_manejador_401(app)` is not wired into production.** Verified: FastAPI 0.141.1's
   `add_exception_handler` has **no runtime guard against late registration**, unlike
   `add_middleware`. Wiring it after the first request silently no-ops rather than raising. So the
   call must land inside `crear_app()`, not somewhere incidental.
2. **FastAPI's default `RequestValidationError` handler** calls `exc.errors(include_url=False)`
   **without** `include_input=False`, so raw rejected values appear in every 422 body by default.
   This item ships the first body-bearing route, so the leak goes live here. It also returns
   `{"detail": [...]}`, structurally unlike ADR 0014's `{"tipo", "contexto"}`.
3. **`Depends()` cannot block a pre-auth multipart parse.** Re-verified on 0.141.1:
   `routing.get_request_handler` reads the body before `solve_dependencies` runs, identically for
   route-level and router-level dependencies. The PRD requires 401 *"antes de leer el cuerpo del
   request"*, so a dependency alone cannot satisfy it. Options are raw ASGI middleware inspecting
   `scope["headers"]` before calling `receive()`, or a `Mount()`-scoped sub-app. ADR 0016 forbids a
   global path allow-list, so the exemption must stay structural.

## Open forks for the proposal

1. **Which H-02 exit** — see the table above. Each costs a different guarantee.
2. **Test-only surface versus a live route.** Items #1–#5 all shipped as libraries with test-only
   surfaces and nothing wired into `crear_app()`. This item is the first that could wire a real
   upload route, and doing so is what makes obligations 1 and 3 concrete rather than theoretical.
   Wiring it materially changes this item's scope.

## Risks

- H-02's disconnect hole is unresolved by every option except the sweeper and the read-into-memory
  variants.
- Early-unlink viability on the actual Windows target is unverified and should not be assumed.
- The route-wiring fork changes scope materially and should be settled before the proposal.
