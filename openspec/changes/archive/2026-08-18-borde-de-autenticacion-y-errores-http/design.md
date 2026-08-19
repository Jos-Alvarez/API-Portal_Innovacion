# Design: Borde de autenticación y errores HTTP

- **Change**: `borde-de-autenticacion-y-errores-http` (first half of BACKLOG item #6, split 2026-08-18)
- **Inputs**: `proposal.md` (**authoritative**), `exploration.md`, `adrs/0014`, `adrs/0016`,
  `adrs/0017`, `PRD.md`, `TECH-DESIGN.md`, `app/main.py`, `app/core/seguridad.py`,
  `app/core/errores.py`, `app/salud.py`, `tests/test_seguridad_token.py`, `openspec/config.yaml`,
  Engram `#98`/`#100`, and the archived designs of items #1–#3 for house style.
- **Authority**: ADRs outrank every other document, including this design and the spec. Inherited
  `L:\App_Portal\adrs\0001`–`0010`; local `adrs\0011`–`0018`.
- **Methodology**: Strict TDD **disabled**. No AST/structural tests, no chaos tests, no
  perturb-and-restore. Behavioural tests, `ruff` and `mypy --strict` still run. Full SDD chain runs.
- **Shape note**: §2 is long because obligation 3 is genuinely hard. §3 and §4 are short because
  their problems are small — except for one subtlety in §4 that is not small at all.

## 0. Verified facts this design rests on

Items #1 and #2 each shipped a false library claim and had to add a corrections section; item #3
avoided a third by reading installed bytes instead of recalling. **No shell was available this
session (no `Bash` tool), so nothing was executed.** Every claim below was read in
`L:\API-Portal\.venv\Lib\site-packages` — the same interpreter `uv run` uses, and *not* the system
`python` (`C:\Python312`, FastAPI 0.115.14). Each row cites file and lines.

| # | Claim | Evidence |
|---|---|---|
| V1 | The request body is read **before** dependency solving: `get_request_handler` has a `# Read body and auto-close files` block calling `await request.form()` / `await request.body()`, and only later raises from `solved_result.errors`. A `Depends()` therefore cannot produce a pre-body 401. | `fastapi/routing.py:425-450`, `:752-755` |
| V2 | `add_exception_handler` has **no** late-registration guard; `add_middleware` raises `RuntimeError` once the stack is built. Registering a handler after the first request silently no-ops. | `starlette/applications.py:104-107` (guard) vs `:109-114` (no guard) |
| V3 | FastAPI's default `RequestValidationError` handler returns `{"detail": jsonable_encoder(exc.errors())}`; `errors()` returns the raw list; those dicts are built with `exc.errors(include_url=False)` and **no** `include_input=False`, and FastAPI even writes `"input"` explicitly in one branch. It is installed via `setdefault`, so a later `add_exception_handler` overrides it. | `fastapi/exception_handlers.py:20-26`; `fastapi/exceptions.py:190-191`; `fastapi/_compat/v2.py:187`; `fastapi/routing.py:452-458`; `fastapi/applications.py:1003-1010` |
| V4 | Dispatch of a non-`HTTPException` is a pure `type(exc).__mro__` walk; the status-code table is consulted **only** behind `isinstance(exc, HTTPException)`. `TokenInvalido`, `ErrorTipificado` and `RequestValidationError` cannot collide. | `starlette/_exception_handler.py:16-20`, `:44-53` |
| V5 | `Router.app` matches routes and calls `route.handle(scope, receive, send)`; `Mount.handle` is `await self.app(scope, receive, send)`. **Routing never calls `receive()`.** The body is first pulled inside the endpoint (V1), not on the way to it. | `starlette/routing.py:672-691`, `:454-455` |
| V6 | `Mount(path, app=..., middleware=[...])` wraps the mounted app in that middleware **while keeping `_base_app` intact**, and `Mount.routes` reads `getattr(self._base_app, "routes", [])`. Wrapping by hand (`app.mount(p, Middleware(Router()))`) would hide `.routes`; the `middleware=` argument does not. | `starlette/routing.py:377-386`, `:390-392` |
| V7 | The app's `ExceptionMiddleware` publishes its handler tables into `scope["starlette.exception_handlers"]`, builds `conn = Request(scope, receive, send)` and wraps **the Router** — so everything reached through routing, mounts included, is inside that wrapper. | `starlette/middleware/exceptions.py:47-63`; `starlette/_exception_handler.py:23-65` |
| V8 | `Request(scope)` defaults `receive=empty_receive`, which **raises** `RuntimeError` if anything tries to read. It asserts `scope["type"] == "http"`. `headers` is read from `scope` only. | `starlette/requests.py:206-207`, `:214-224`, `:133` |
| V9 | Route walkers descend into `_IncludedRouter` and **never into `Mount`**: `_iter_routes_with_context` has exactly two branches. So routes inside a mount are invisible to the outer OpenAPI schema. | `fastapi/routing.py:1842-1850`, `:1828-1839`; `fastapi/openapi/utils.py:558`, `:628` |
| V10 | `Mount` defines **no** `methods` attribute and no `original_router`. Item #2's `_rutas_efectivas` skips anything without either, so **a `Mount` is silently invisible to the pinned route-set test** — it does not turn it red. | `starlette/routing.py:363-463`; `tests/test_seguridad_token.py:245-263` |
| V11 | `fastapi_inner_astack` is set by `get_request_handler` itself, not by an app-level middleware, so an `APIRoute` still works when it lives inside a mounted bare router. | `fastapi/routing.py:141`, `:178` |
| V12 | The PRD already names the internal route shape: `POST /interno/procesadores/contado-carga/ejecutar`. The `/interno` prefix is **not invented here**. | `PRD.md:76-77` |
| V13 | `anyio` is installed (Starlette dependency), so an async ASGI-level test needs **no new dependency and no pytest plugin** — `anyio.run(...)` inside a sync test is enough. | `.venv/Lib/site-packages/anyio/__init__.py` |

## 1. Technical approach

Three obligations, three independent mechanisms, one shipped app:

```
crear_app()
  ├─ registrar_manejador_401(app)          obligación 1  (una línea)
  ├─ registrar_manejador_validacion(app)   obligación 2  (una línea + módulo nuevo)
  ├─ include_router(router_salud)          público — fuera del montaje, por construcción
  └─ Mount("/interno", app=router_interno, middleware=[AutenticacionDeBorde])
                                           obligación 3  (la superficie autenticada)
```

`/salud` and the four FastAPI doc routes stay on the outer app. `/interno/...` is the only
authenticated surface. **There is no path list anywhere**: a route is authenticated if and only if it
was registered inside `router_interno`.

## 2. Obligation 3 — the pre-body 401

### 2.1 Why `Depends()` is out, and what the real option set is

V1 settles it: FastAPI reads the whole multipart body before it solves a single dependency, for both
route-level `Depends(...)` and router-level `dependencies=[...]`. A 26 MB upload from an
unauthenticated caller would be fully parsed to disk-or-memory before the token was ever looked at.

| Option | Rejects pre-body? | `/salud` outside without a list? | 401 construction sites | Cost |
|---|---|---|---|---|
| `Depends(exigir_token)` on processor routers | **No** (V1) | Yes | 1 | Cannot satisfy the PRD. This is ADR 0016's named mechanism, and it is the thing that must change |
| Global `add_middleware` + path allow-list | Yes | **No** — needs the list | 1 | **ADR 0016 forbids it in words**: *"nunca como middleware global con una lista de rutas permitidas… Un allow-list es un error tipográfico de distancia de abrir todo el servicio"* |
| Mount a nested `FastAPI` sub-app, auth in `Mount(middleware=)` | Yes | Yes | 1 function, **2 registration sites** | The sub-app installs its own `ExceptionMiddleware`, which overwrites `scope["starlette.exception_handlers"]` (V7) for everything inside it. Every handler would need registering on both apps. Also adds its own `/interno/docs` set |
| **Mount a bare `APIRouter`, auth in `Mount(middleware=)`** | **Yes** | **Yes** | **1** | Routes inside the mount are absent from the outer OpenAPI schema (V9) |

**Chosen: the fourth.** It is the only option that is pre-body, structural, and leaves item #2's
single-construction-site property untouched. §2.4 proves the last point rather than asserting it.

### 2.2 Where the authenticated surface begins

At the `Mount` prefix `/interno`, taken from `PRD.md:76-77` (V12), not invented here.

`/salud` is **not excluded** from authentication — it is registered on the outer app and therefore was
never inside the authenticated surface, which is exactly the wording ADR 0016 uses. The same is true
of `/openapi.json`, `/docs`, `/docs/oauth2-redirect` and `/redoc`: FastAPI creates them on the outer
app, and nothing in this change moves or names them.

The failure mode changes shape, and honestly so: under ADR 0016's dependency mechanism the mistake was
*"someone forgot `dependencies=[Depends(exigir_token)]` on a new router"*, which nothing detected.
Under the mount the mistake is *"someone registered a processor route outside `/interno`"* — and §5's
route-set pin is exactly the detector for that. The new mistake is caught; the old one was not.

### 2.3 The mechanism, and how it avoids `receive()`

```python
# app/core/seguridad.py  (ilustrativo)
class AutenticacionDeBorde:
    """Middleware ASGI del montaje autenticado.

    Decide con `scope["headers"]` y nada más: nunca llama a `receive()`, así que
    el 401 sale antes de que exista un solo byte de cuerpo (PRD: "401 antes de
    leer el cuerpo del request"). El `Request` que construye lleva el `receive`
    vacío por defecto, que *lanza* si alguien intenta leer: la imposibilidad de
    consumir el cuerpo es estructural, no una convención (V8).
    """

    __slots__ = ("app",)

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            await exigir_token(Request(scope))  # único sitio de `raise` (ítem #2)
        await self.app(scope, receive, send)
```

Four properties, each load-bearing:

- **No `receive()` call.** The middleware only reads `scope["headers"]` through `Request.headers`
  (V8). Nothing upstream reads the body either: routing hands `receive` along untouched (V5).
- **The `Request` physically cannot read a body.** `Request(scope)` gets `empty_receive`, which raises
  (V8). A future regression that tried to inspect the body here would blow up loudly instead of
  quietly consuming it.
- **The `scope["type"] == "http"` guard is required, not defensive.** `Request.__init__` asserts it
  (V8). Lifespan never reaches a mount (it is handled before route matching, `starlette/routing.py:678`),
  so in practice this only lets a websocket scope fall through to the mounted router, which has no
  websocket routes.
- **The comparison is not reimplemented.** The middleware calls `exigir_token` — item #2's single
  `raise` site — which calls `_es_valida` → `_credencial_presentada` + `_coincide`
  (`hmac.compare_digest`) → `_token_esperado` (the single secret unwrap). Zero new header parsing,
  zero new comparison, zero new secret unwrapping. This is why the middleware lives **inside
  `app/core/seguridad.py`**: the reuse is intra-module and needs no private symbol to become public.

### 2.4 The 401 response — one construction site, proven

This was the real risk: if rejection happens before the FastAPI app is entered, item #2's handler
might be unreachable and a second `Response(401, …)` would have to be built at the ASGI layer. That
would undo item #2's whole design.

**It does not happen.** The mount lives inside the outer app's routing, and the outer app's
`ExceptionMiddleware` wraps the Router (V7). The exception therefore unwinds straight into it:

```
FastAPI.__call__
  └─ ServerErrorMiddleware
      └─ ExceptionMiddleware        ← publica las tablas en el scope y envuelve al Router (V7)
          └─ AsyncExitStackMiddleware
              └─ Router.app                                   (V5: no toca receive)
                  ├─ Route "/salud"  … público
                  └─ Mount "/interno"
                      └─ AutenticacionDeBorde   ── raise TokenInvalido ──┐
                          └─ APIRouter (vacío hoy)                       │
                                                                         │
   type(exc).__mro__ → TokenInvalido (V4) ───────────────────────────────┘
                    → responder_token_invalido()  ← ÚNICO sitio de construcción, sin cambios
                    → 401, cuerpo vacío, WWW-Authenticate: Bearer   (ADR 0017)
```

`responder_token_invalido` ignores its `request` argument (`app/core/seguridad.py:35-37`), so the
`Request` that `ExceptionMiddleware` builds is never read and no body is pulled on the rejection path
either. **No second construction site appears, and `app/core/seguridad.py` is unmodified in that
respect** — only extended.

This property is exactly what the third option in §2.1 would have broken: a nested `FastAPI` overwrites
the handler table for everything inside it (V7), so the same three handlers would need registering
twice, in two places, forever. One construction site survives that, but "one registration" does not.

### 2.5 The mount is created empty, today

`router_interno = APIRouter()` with no routes. Consequences, all of them good:

- **The boundary is fully testable now.** `GET /interno/lo-que-sea` with no token → **401** (the
  middleware ran). With the correct token → **404** (the middleware passed through and the empty
  router fell to `Router.not_found`, which raises `HTTPException(404)` because `scope["app"]` is set —
  `starlette/routing.py:616-629`). The 401/404 pair is a sharper proof than either alone: it shows the
  middleware both rejects *and* gets out of the way.
- **No production route is added.** The change ships zero new endpoints, consistent with the proposal's
  "no upload route yet".
- **The parked half plugs into it.** Reception adds `@router_interno.post(...)` and nothing about the
  boundary moves.

Two things the parked half must verify when the first real route lands, flagged now rather than
discovered later: (a) an `APIRoute` inside a mounted bare router (V11 says the exit stack is fine, but
nothing in this change exercises it), and (b) that the route is absent from `/openapi.json` (V9) —
accept it, or revisit §2.1's third option then.

## 3. Obligation 1 — wiring the 401 handler

One line inside `crear_app()`, before the app is returned. V2 is the whole reason it must be there and
not anywhere else: registering late silently no-ops. Nothing else changes.

Obligation 3 makes this behaviourally provable end to end for the first time: `GET /interno/x` without
a token now returns ADR 0017's 401 from the **shipped** app, not an unhandled 500.

## 4. Obligation 2 — `RequestValidationError`

### 4.1 The subtle part: no `tipo` in ADR 0014's enum fits

ADR 0014 closes the vocabulary at five values (`adrs/0014:46`), and this design does not widen it.
Checked one by one against the `contexto` shapes item #3 shipped in `app/core/errores.py`:

| `tipo` | What it means | Fits a request-shape failure? |
|---|---|---|
| `formato` | the uploaded file's format vs the accepted list | No — a missing form field has no format |
| `tamano` | bytes vs the row's limit | No |
| `contenido` | missing column / zero rows in a sheet | No — nothing was parsed |
| `cantidad` | file count vs `entradas_min`/`entradas_max` | **Nearly** — but those bounds live in the SQL Server row, and an exception handler has no row. Filling `minimo`/`maximo` from `exc.errors()` would be invention |
| `clave_inexistente` | registry ↔ database desync | No |

**A `RequestValidationError` maps to none of the five, and the reason is structural, not a gap.**
ADR 0014's enum names failures of the *content* of an accepted request; a validation error is a
failure of the request's *shape*, one layer earlier — precisely the distinction ADR 0017 drew when it
put the 401 outside this same enum: *"no es un error sobre el contenido de una petición ya
autenticada, es el rechazo previo a considerar esa petición"* (`adrs/0017:29-32`).

### 4.2 Decision

**HTTP 422 with an empty body**, produced by a handler registered in `crear_app()`.

| Option | Widens the enum? | Echoes input? | Verdict |
|---|---|---|---|
| FastAPI's default | n/a | **Yes** (V3) | The thing being closed |
| `{"tipo": <one of five>, "contexto": …}` | No, but **lies** | No | Rejected — the portal would paint a file-format or file-count banner for a malformed request |
| `{"tipo": "peticion_invalida", …}` | **Yes**, on the wire | No | Rejected — the enum is closed; a sixth wire value is a contract change ADR 0014 says must be treated as one |
| A third envelope (`{"errores": [...]}`) | No | Configurable | Rejected — a whole new shape the portal must learn, for a case that should not occur |
| **422, empty body** | No | **Impossible — there is nothing to leak** | **Chosen** |

```python
# app/core/validacion_http.py  (ilustrativo)
def responder_validacion_invalida(request: Request, exc: Exception) -> Response:
    # Sin cuerpo a propósito: ADR 0014 cierra el vocabulario en cinco tipos y
    # ninguno describe una petición mal formada (design §4.1). Mismo criterio
    # estructural que ADR 0017 aplicó al 401. Sin cuerpo no hay eco posible del
    # valor rechazado, que es la fuga que FastAPI trae por defecto (V3).
    return Response(status_code=422)


def registrar_manejador_validacion(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, responder_validacion_invalida)  # V3
```

**Why the empty body is not a loss of information.** The informative 422 is produced by the pipeline,
not by this handler. PRD and ADR 0006 already require every processor route to *"declarar su propia
forma de entrada y delegar de inmediato en el pipeline común"*; the pipeline holds the SQL Server row
and can emit a truthful `cantidad`/`formato`/`tamano` envelope with real bounds. This handler is the
**residual** case — a request that never became a pipeline call at all. Guidance the parked half
should follow so the residual stays residual: declare upload parameters permissively (e.g.
`list[UploadFile]` with a default) so that "wrong number of files" reaches the pipeline as `cantidad`
instead of being intercepted by FastAPI's validator.

The portal is unaffected: ADR 0014's *Consecuencias* already makes a fallback branch **mandatory** in
item #10, and an unparseable 422 lands there.

### 4.3 Where it lives — its own module

`app/core/validacion_http.py`, not `app/core/errores.py`.

`errores.py`'s stated design goal is that *"los cinco tipos son un conjunto cerrado en el sistema de
tipos, no una convención"*. Dropping in a handler that returns a 422 with **no** `tipo` weakens exactly
that reading for every future reader. The repository already splits error responses by contract rather
than by mechanism — `seguridad.py` owns the auth rejection, `errores.py` owns the ADR 0014 envelope —
so a request-shape rejection is a third contract and gets a third file. ~38 lines, docstring included.

### 4.4 Conflict with the spec — flagged, not silently resolved

Engram `#100` (`sdd/borde-de-autenticacion-y-errores-http/spec`, written in parallel) and the
proposal's scope bullet both say the handler must produce *ADR 0014's `{"tipo", "contexto"}`
envelope*. §4.1 shows that is unsatisfiable without either inventing a `tipo` or widening the closed
enum, and **ADRs outrank the spec and this design**.

The spec's actual intent — not FastAPI's `{"detail": [...]}` shape, and no echo of the submitted value
or the token — is fully met. **One spec amendment is required** before `sdd-verify`: the requirement
*"Request validation failures use the typed envelope, not FastAPI's default"* and its first scenario
must assert an empty 422 body rather than a `{"tipo", "contexto"}` body. `sdd-tasks` must carry this
as an explicit task; verification will fail against the current wording.

## 5. The pinned route set — a measured correction

The brief expected `test_rutas_de_produccion_no_cambian` to go **red** when the mount is added. It
does not. V10: `_rutas_efectivas` recurses only through `original_router` and otherwise requires a
`methods` attribute; a `Mount` has neither, so it is **silently skipped** and the test stays green
against the unchanged five-entry literal. This is the same blind spot FastAPI's own OpenAPI walker has
(V9) — both descend into `_IncludedRouter` only.

That is worse than red: the pin quietly stops covering the new production surface.

**Correct response — strengthen the helper, do not touch the literal:**

```python
def _rutas_efectivas(rutas, prefijo=""):    # ilustrativo
    ...
    sub_router = getattr(ruta, "original_router", None)   # _IncludedRouter (ya existía)
    if sub_router is not None:
        resultado |= _rutas_efectivas(sub_router.routes, prefijo)
        continue
    if isinstance(ruta, Mount):                            # NUEVO: baja al montaje (V6)
        resultado |= _rutas_efectivas(ruta.routes, prefijo + ruta.path)
        continue
    ...
```

New expectations after the change:

```python
esperado = {                                   # sin cambios: el montaje está vacío hoy
    ("/salud", ("GET",)),
    ("/openapi.json", ("GET", "HEAD")),
    ("/docs", ("GET", "HEAD")),
    ("/docs/oauth2-redirect", ("GET", "HEAD")),
    ("/redoc", ("GET", "HEAD")),
}
esperado_montajes = {"/interno"}               # NUEVO: la superficie autenticada, con cero rutas
```

**Why this is not weakening the pin.** The literal is unchanged because the authenticated surface is
genuinely empty, and it is now green for a *verified* reason instead of a blind one. The one thing the
pin exists to prevent — a production route appearing without a diff-visible edit — is now covered on
both sides of the boundary: an unauthenticated route reddens the first set, an authenticated one
reddens it too (with the `/interno` prefix), and the mount itself is pinned by name. Rewriting the
literal to accept whatever `crear_app()` happens to return would have inverted the test's purpose.
V6 matters here: this only works because `Mount(middleware=[...])` preserves `_base_app`, so
`Mount.routes` still reports the mounted router's routes.

## 6. ADR 0019 — outline only (`tasks` schedules the writing)

`adrs/0019-frontera-autenticada-por-montaje.md`. MADR matching siblings 0011–0018, neutral
professional Spanish, sections **Estado / Contexto / Decisión / Alternativas consideradas /
Consecuencias**.

This ADR is **not optional**. ADR 0016's *Decisión* names the mechanism verbatim — *"el token se
adjunta como dependencia únicamente a los routers de procesadores"* — and V1 proves that mechanism
cannot meet the PRD. Changing a mechanism an accepted ADR names requires a written decision.

- **Contexto** — the PRD's *"401 antes de leer el cuerpo del request"*; V1; ADR 0016's two rules
  (structural exemption, no allow-list) and its named mechanism.
- **Decisión** — the authenticated surface is the `/interno` mount (`PRD.md:76-77`); a mount-scoped
  ASGI middleware authenticates from `scope["headers"]` before any `receive()`; `/salud` and the doc
  routes are outside it by construction, with no path list anywhere; the 401 is still built only by
  `responder_token_invalido`. **ADR 0016's invariant is preserved; only its named mechanism is
  superseded.**
- **Alternativas consideradas** — `Depends` (cannot meet the PRD, V1); global middleware + allow-list
  (ADR 0016 forbids it); nested `FastAPI` sub-app (duplicates the handler table, V7).
- **Consecuencias** — routes inside the mount are invisible to the outer OpenAPI schema (V9); the
  route-set pin must descend into `Mount` (§5); every processor route MUST live under `/interno`, and
  a route registered outside it is unauthenticated — the pin is the guard for that.

**Numbering**: the parked half reserved `0019` for the temporary-lifecycle decision. This change takes
`0019`; **that one becomes `0020`.** Flagged in §13 because it edits a parked proposal's expectation.

## 7. File changes

| File | Action | Description |
|---|---|---|
| `app/core/seguridad.py` | Modify | Add `AutenticacionDeBorde` (§2.3) and export it. Update the module docstring: it currently says *"Nada de este módulo se cablea en `crear_app()`"*, which stops being true |
| `app/core/validacion_http.py` | Create | `responder_validacion_invalida`, `registrar_manejador_validacion` (§4) |
| `app/main.py` | Modify | `registrar_manejador_401(app)`, `registrar_manejador_validacion(app)`, `router_interno = APIRouter()`, and `app.router.routes.append(Mount("/interno", app=router_interno, middleware=[Middleware(AutenticacionDeBorde)]))`. Replace the two stale `# costura #2` comments |
| `adrs/0019-frontera-autenticada-por-montaje.md` | Create | §6 |
| `tests/test_borde_autenticacion.py` | Create | §8 rows 1–5 |
| `tests/test_validacion_http.py` | Create | §8 rows 6–7 |
| `tests/test_seguridad_token.py` | Modify | `_rutas_efectivas` descends into `Mount`; new mount assertion (§5) |

**Not touched**: `app/core/errores.py`, `app/core/configuracion.py`, `app/salud.py`,
`app/arranque.py`, `pyproject.toml` (no new dependency — V13).

Note on the mount construction: `app.mount(...)` cannot pass `middleware=`, and hand-wrapping the app
would hide `Mount.routes` from the pin (V6). The `Mount` is therefore built explicitly and appended to
`app.router.routes`.

## 8. Testing strategy

Behavioural only. **No AST/structural tests, no chaos tests, no perturb-and-restore.**

| # | Layer | What to test | Approach |
|---|---|---|---|
| 1 | ASGI | **Rejection consumes no body byte** | Drive `crear_app()` directly with a hand-built `http` scope for `POST /interno/procesadores/x/ejecutar` (headers announcing a large multipart body) and a `recibir_espia` that appends to a list. Run it with `anyio.run(...)` in a sync test (V13 — no plugin, no dependency). Assert the spy list is **empty** and the response is 401 / empty body / `WWW-Authenticate: Bearer`. Deterministic; preferred over the spec's timing-based streaming variant, which is flaky |
| 2 | Integration | 401 from the **shipped** app, not a 500 | `TestClient(crear_app())`, `GET /interno/x` with no header, with a wrong token, and with a malformed header → 401, empty body, `WWW-Authenticate: Bearer` in all cases |
| 3 | Integration | The middleware gets out of the way | Same route **with the correct token** → 404 (empty mount, §2.5). Proves the boundary is not a blanket denial |
| 4 | Integration | `/salud` and the doc routes are outside the surface | No `Authorization` header: `GET /salud` → 200 `{"estado": "vivo"}`; `GET /docs` and `GET /openapi.json` → 200 |
| 5 | Integration | Route-set pin (§5) | Extended `_rutas_efectivas`; unchanged five-entry literal plus `{"/interno"}` mounts |
| 6 | Integration | Validation failure returns an empty 422 and echoes nothing | Test-only app in the test module (item #3's pattern), one route with a declared body + `registrar_manejador_validacion`. POST a body containing a recognisable sentinel value → 422, `respuesta.content == b""`, and the sentinel absent from the full raw response bytes |
| 7 | Unit | Both handlers are registered by the shipped factory | `crear_app().exception_handlers[TokenInvalido] is responder_token_invalido` and `[RequestValidationError] is responder_validacion_invalida`. Two dict reads — the only available proof for obligation 2, since the shipped app has no body-bearing route |
| 8 | Integration | Token still absent from captured output on the new path | One variant of item #2's existing sentinel/subprocess test, driven through `/interno` |
| 9 | Static | Whole change | `uv run ruff check . && uv run ruff format --check . && uv run mypy app tests` |

Fixtures `token_sentinela` + `limpiar_cache_configuracion` are required by rows 1–3 and 8. Row 1
bypasses lifespan, which is harmless: `_token_esperado()` calls the `lru_cache`d
`obtener_configuracion()` directly.

## 9. Threat matrix

The reference matrix's rows are VCS/PR-shaped and all **N/A**: no shell, no subprocess (beyond item
#2's existing sentinel helper, unchanged in mechanism), no Git/PR automation, no executable-file
classification. This change *does* alter routing, so the real boundaries are listed instead:

| Boundary | Applicability | Design response | Planned test |
|---|---|---|---|
| A route added outside the authenticated mount is unauthenticated | **Applicable** — this is the mount's new failure mode (§2.2) | Every processor route lives under `/interno`; ADR 0019 states it; the route-set pin descends into `Mount` and reddens on either side | §8 row 5 |
| Body read before the token check | **Applicable** — the obligation itself | Mount-scoped ASGI middleware; `Request(scope)` with a raising `receive` (V8); routing never pulls the body (V5) | §8 row 1 |
| A second 401 construction site diverging from ADR 0017 | **Applicable** | The raise unwinds into the outer `ExceptionMiddleware` (V7, §2.4); `responder_token_invalido` unchanged | §8 rows 1–2 assert the full 401 contract |
| Echo of rejected input in a 422 | **Applicable** | Empty body — nothing to leak (§4.2) | §8 row 6, sentinel absent from raw bytes |
| Secret leaking through the new layer | **Applicable** | The middleware never unwraps the secret itself; `_token_esperado` remains the single unwrap site | §8 row 8 |
| Path allow-list creeping in | **Applicable** — ADR 0016 | No list exists; membership is registration, not matching | Reviewable by construction; §8 rows 4–5 |
| Handler collision between 401, typed errors and validation errors | N/A — disjoint by V4 | Three distinct classes, none an `HTTPException` subclass except `RequestValidationError`, which V4 still routes by MRO | Existing item #2/#3 suites stay green |
| Shell / subprocess / VCS / PR / executable classification | N/A — none in this change | — | — |

## 10. Review budget forecast

| Artifact | Est. changed lines |
|---|---|
| `app/main.py` | 12–18 |
| `app/core/seguridad.py` | 35–45 |
| `app/core/validacion_http.py` | 30–40 |
| `adrs/0019-*.md` | 55–70 |
| `tests/test_borde_autenticacion.py` | 150–190 |
| `tests/test_validacion_http.py` | 70–95 |
| `tests/test_seguridad_token.py` | 20–30 |
| **Total** | **372–488** |

**Read the upper end.** The last three items all overran their forecast, always through the test file,
and row 1 here (a hand-built ASGI scope plus an `anyio` driver) is the most under-estimable thing in
the table. Plan for **~460**.

**400-line budget risk: High.** A clean two-slice chain exists and follows the change's own structure:

- **PR #1 — the two straightforward obligations** (`app/main.py` wiring, `validacion_http.py`,
  `tests/test_validacion_http.py`, §8 rows 6–7, spec amendment). ~140–180 lines. Ships and stands alone.
- **PR #2 — the pre-body boundary** (`seguridad.py`, the mount in `crear_app()`, ADR 0019,
  `test_borde_autenticacion.py`, the route-pin change, §8 rows 1–5 and 8). ~230–310 lines.

`sdd-tasks` owns the formal guard lines and the final decision between one PR with `size:exception`
and this chain.

## 11. Migration / rollout

No migration, no schema, no external system, no feature flag. `git revert` restores the previous
behaviour exactly. Two behavioural changes are visible outside the process, both intended: an
authentication failure returns 401 instead of 500, and `/interno/*` exists as a 401/404 surface where
it previously 404'd for everyone. No existing client is affected — the portal (item #10) does not call
this service yet.

## 12. Recorded, not solved

- **`registrar_manejador_errores(app)` is still not wired into `crear_app()`.** Deliberately left
  alone: the proposal scopes this change to exactly three obligations, and nothing in the shipped app
  can raise `ErrorTipificado` today (no pipeline, no route). **The parked reception half MUST wire it
  in the same commit as the first upload route**, or the identical debt this change exists to pay is
  simply recreated. V2 applies to it verbatim: registering late silently no-ops.
- Inherited **ADR 0006** enumerates three portal `evento_uso` error types while this service emits
  five; `cantidad` and `clave_inexistente` still have no analytics destination. Item #10's problem,
  unchanged since item #3.

## 13. Open questions

- [ ] **Spec amendment required (§4.4).** The `RequestValidationError` requirement and its first
      scenario assert a `{"tipo", "contexto"}` body that ADR 0014's closed enum cannot supply.
      `sdd-tasks` must schedule the edit; `sdd-verify` will fail against the current wording.
- [ ] **ADR renumbering (§6).** This change takes `0019`; the parked temporary-lifecycle ADR becomes
      `0020`. Its proposal in `openspec/changes/recepcion-y-ciclo-de-vida-de-temporales/` names 0019
      and needs a one-line edit.
- [ ] **Accepted, not open — recorded so it is not rediscovered**: routes inside `/interno` will not
      appear in `/openapi.json` (V9). Nothing consumes that schema today; the parked half revisits it
      when the first upload route lands.
- [ ] Nothing else blocks. The design proceeds to `tasks`.
