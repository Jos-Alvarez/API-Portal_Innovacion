# Exploration — Autenticación por token de servicio

- **Change**: `autenticacion-por-token-de-servicio`
- **Source**: `BACKLOG.md` item #2
- **Phase**: explore (read-only investigation; no proposal, no implementation)
- **Artifact store**: hybrid (this file + Engram topic `sdd/autenticacion-por-token-de-servicio/explore`)
- **Depends on**: item #1 `esqueleto-servicio-arranque-seguro` — complete, verified, archived

## Current state

Item #1 shipped and is on `main`. Verified by reading the code, not assumed:

- `app/core/configuracion.py` — `token_servicio: Annotated[SecretStr, Field(min_length=1)]`, with a
  durable comment forbidding regex or length-floor validation without a sanitising layer first.
  `get_secret_value()` has **zero** call sites today.
- `app/main.py` `crear_app()` includes only `router_salud`. The item #2 attach point exists as a
  comment, not code.
- `app/salud.py` imports `fastapi` only, proven by an AST scan test. The health exemption is
  structural — `/salud` is never inside the authenticated surface (ADR 0016).
- `app/core/seguridad.py` does not exist. It is this change's deliverable.
- No processor router exists. Items #4 and #12 are not built.
- Reusable test infrastructure: `tests/ayudas/subproceso.py` (fresh-interpreter runner),
  `tests/conftest.py` (`token_sentinela`, `limpiar_cache_configuracion`), and the caplog
  substring-absence pattern in `tests/test_configuracion_token.py`.

## Central finding — FastAPI reads the body before dependencies run

Verified against the installed FastAPI **0.141.1** source, and re-verified independently by the
orchestrator:

```
fastapi 0.141.1
index of  await request.form()      = 2438
index of  await request.body()      = 2577
index of  solve_dependencies(...)   = 4806
body read strictly before solve_dependencies: True
```

In `routing.get_request_handler`, the body-reading block runs unconditionally whenever the endpoint
declares a `Body` / `Form` / `File` parameter, and `solve_dependencies` — which executes **every**
dependency, whether declared per-route via `Depends(...)` or per-router via `dependencies=[...]` —
runs strictly afterwards. There is no ordering difference between the two attachment points, and no
arrangement of `Depends()` changes this; it is hard-coded.

Consequences:

- For routes with **no** body parameter — item #2's entire actual scope today — `Depends(exigir_token)`
  never touches the body, so "401 before reading the request body" is trivially satisfied.
- For item #6's future `UploadFile` routes, a `Depends()`-based check will **not** prevent FastAPI
  from parsing the full multipart upload before the dependency runs. This matches the known upstream
  issue `fastapi/fastapi#4941`.
- The only way to guarantee zero body bytes read for a body-bearing route is raw ASGI middleware, or a
  `Mount()`-scoped sub-app, inspecting `scope["headers"]` before calling `receive()`. Scoped around the
  processor sub-app rather than as a path allow-list, that would not violate ADR 0016's
  "never a global allow-list" intent.
- **This is item #6's design problem, not item #2's.** Record it now so it is not rediscovered late.

## Second finding — a parallel echo vector in a different subsystem

`fastapi/exception_handlers.py` (0.141.1), verified:

```python
async def request_validation_exception_handler(request, exc) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(exc.errors())})
```

No `include_input=False` filtering, unlike item #1's single manual catch site in `configuracion.py`,
which strips `input` and `url` explicitly. Pydantic v2's `ValidationError.errors()` includes `input`
by default.

Therefore: **if the token header is ever declared as a typed or validated FastAPI parameter** — for
example `Annotated[str, Header(min_length=..., pattern=...)]` — a validation failure echoes the
submitted token value back in the response body. This is the same echo-vector class that item #1's
`min_length=1` constraint closes for the configuration field, reappearing in a new subsystem.

Mitigation: read the header manually via `request.headers.get(...)` as an unvalidated plain string
inside `exigir_token`, and raise `HTTPException(401, detail=<generic literal>)`. Never attach pydantic
shape validation to the incoming header.

## Constant-time comparison

- `hmac.compare_digest(a, b)` requires both arguments to be the same type: both `str` (ASCII only) or
  both `bytes`. Encoding both sides to UTF-8 `bytes` explicitly sidesteps the ASCII constraint.
- Never add a manual `len()` pre-check before calling it — that reintroduces the length leak the
  stdlib function's documented behavior already avoids.
- An absent header may short-circuit to 401 without calling `compare_digest`. Presence is not secret;
  only content is.
- `get_secret_value()` gets exactly one call site, in `app/core/seguridad.py`, never inside a logging
  or formatting call — this is item #13's intended enforcement seam.

## What the documents actually mandate

- `PRD.md` — *"Token de servicio obligatorio: toda petición debe presentar el token en los headers.
  Sin token válido, se rechaza con 401 antes de leer el cuerpo del request."* Generic "en los
  headers"; **no exact header name or scheme is specified anywhere** — not in the PRD, TECH-DESIGN,
  local ADRs 0011–0016, or the readable inherited portal ADRs.
- `PRD.md` — *"Petición sin header de token, con token vacío, malformado o incorrecto → 401, sin
  pistas sobre el token esperado y sin leer el archivo."* The 401 body must give no hints.
- Constant-time comparison and "never in logs, traces or errors" are stated as explicit edge cases.
- `/salud` is the only exempt route (ADR 0016).
- **ADR 0014's closed error enum is exactly `formato`, `tamano`, `contenido`, `cantidad`,
  `clave_inexistente` — 401 is explicitly outside that vocabulary.** Item #2 must not force its 401
  into ADR 0014's `{"tipo": ..., "contexto": ...}` shape. The only hard constraint on the 401 body is
  "no hints".

## What item #2 can actually protect today

No processor router exists. The only legitimate production surface is `app/core/seguridad.py`
exporting `exigir_token`. Proving the behavior means exercising it as a plain callable against
constructed `Request` objects, and/or a throwaway `APIRouter`/app built **inside the test module
only** — never wired into the shipped `crear_app()`. This mirrors item #1's discipline of leaving
seams as comments rather than inventing routes the backlog does not authorize.

## New leak surfaces versus item #1

- An uncaught exception inside `exigir_token` must not reach Starlette's debug traceback renderer.
  The app must never be constructed with `debug=True`.
- Uvicorn's default access-log format does not include headers, but no existing test proves this for
  header-bearing requests. Item #2 should add one rather than assume it.

## Open questions

1. Exact header name and scheme (`Authorization: Bearer` versus a custom header). Unspecified anywhere.
2. Exact 401 body shape — constrained only by "no hints".
3. How to prove the pre-body 401 behavior without a real processor route. A test-only router is the
   recommended approach.
4. The middleware-versus-`Depends()` tension for item #6's `UploadFile` routes. Record now, solve in #6.
5. What a future sanitising layer for the token field would need to do if stronger validation is ever
   wanted — post-comparison validation, never a `Field` constraint pydantic can echo.

## Note on verification

The explore phase had no shell, so it could not confirm the repository state independently. The
orchestrator verified: `main` at `89af40b`, clean tree, and re-ran both FastAPI source checks above.
