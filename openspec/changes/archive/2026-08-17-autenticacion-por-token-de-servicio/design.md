# Design: Autenticación por token de servicio

- **Change**: `autenticacion-por-token-de-servicio` (BACKLOG item #2)
- **Inputs**: `proposal.md` (authoritative, incl. "Scope of the indistinguishability guarantee"),
  `specs/service-token-auth/spec.md`, `exploration.md`, item #1's archived `design.md` (D4, D5),
  `openspec/specs/service-bootstrap/spec.md`, `PRD.md`, `TECH-DESIGN.md`
- **Authority**: ADRs outrank every other document. Inherited: `L:\App_Portal\adrs\0001`–`0010`.
  Local: `adrs\0011`–`0016`. This change authors none; it *recommends* `0017` (§9).
- **Size note**: over the usual 800-word artifact budget, deliberately. The task names five hard
  problems and `openspec/config.yaml` mandates sequence diagrams plus per-decision rationale; the
  encoding and rejection-path decisions cannot be specified honestly in fewer words. Prose is kept
  to a minimum in favour of tables (`cognitive-doc-design`).

## 0. Verified facts this design rests on

Item #1's design shipped two false claims and had to add a "Post-implementation corrections"
section. To avoid repeating that, **every library claim below was read in the installed source**
(no shell was available this session — `Bash` is disabled — so nothing was executed; each row cites
the file and line that was read). Any row marked *documented* is a stdlib doc claim the design does
not depend on.

| # | Claim | Evidence (installed source) |
|---|---|---|
| V1 | `request.headers.get(k)` returns the **first** occurrence and silently discards later duplicates. `Headers` is a `Mapping`, defines no `get`, so `Mapping.get` → `__getitem__`, which returns on the first byte-key match. `getlist` returns all. | `starlette/datastructures.py:500,537,544-549` (starlette **1.6.0**) |
| V2 | Header values are decoded **latin-1**, so any presented credential is a `str` whose codepoints are all ≤ U+00FF, and `.encode("latin-1")` recovers the exact wire bytes without loss. | `datastructures.py:539,548`; `requests.py:133-136` |
| V3 | `Response(status_code=401, headers={"WWW-Authenticate": "Bearer"})` yields exactly `raw_headers == [(b"www-authenticate", b"Bearer"), (b"content-length", b"0")]` — `media_type` is `None` so no `content-type`; body is `b""` and 401 ∉ `(204, 304)` so `content-length: 0` **is** emitted. | `responses.py:29-31,45,55-81` |
| V4 | `Response.__call__` reads only `self.status_code/raw_headers/body` — sending is stateless. But `.headers` returns a `MutableHeaders` **view over the same list**, and `set_cookie` appends to it, so a shared instance is mutable across requests. | `responses.py:83-87,132,163-170` |
| V5 | `HTTPException` cannot produce an empty 401: `is_body_allowed_for_status_code(401)` → `not (401 < 200 or 401 in {204,205,304})` → `True`, so the handler returns `JSONResponse({"detail": ...})`. | `fastapi/exception_handlers.py:11-17`; `fastapi/utils.py:26-40` |
| V6 | **For any `HTTPException` subclass a status-code handler is consulted *before* the class handler.** Only after `status_handlers.get(exc.status_code)` misses does `_lookup_exception_handler` walk `type(exc).__mro__`. | `starlette/_exception_handler.py:16-20,46-50` |
| V7 | `request_validation_exception_handler` returns `jsonable_encoder(exc.errors())` with no `include_input=False` — confirms the settled raw-string parsing decision. | `fastapi/exception_handlers.py:20-26` |
| V8 | httpx encodes `str` header values as **ASCII** and passes `bytes` through untouched; duplicates survive when headers are given as a list of pairs. | `httpx/_models.py:74-82,158-162` |
| V9 | `TestClient` response headers are **exactly** the app's raw headers (`[(k.decode(), v.decode()) for k, v in message["headers"]]`) — no `date`, no `server` added. Request headers reach the ASGI scope via `multi_items()`, preserving duplicates. | `starlette/testclient.py:250,333` |
| V10 | Uvicorn's access line is `'%s - "%s %s HTTP/%s" %d'` (client addr, method, path **+ query string**, HTTP version, status) — no header values. Emission is gated on `self.access_logger.hasHandlers()`. | `uvicorn/protocols/http/h11_impl.py:56-57,481-488` |
| V11 | The `uvicorn.access` logger is configured `propagate: False` with its own handler, so **`caplog` cannot see it**. | `uvicorn/config.py:82,111` |
| V12 | `HTTPExceptionHandler = Callable[[Request, Exception], Response \| Awaitable[Response]]` — under `mypy strict` a handler must annotate `exc: Exception`, not a narrower subclass. | `starlette/types.py:24-26`; `applications.py:109-114` |
| V13 | `pydantic._SecretBase.__eq__` compares secret values, so `cfg.token_servicio == SecretStr(x)` works without a source-level `get_secret_value()` call. | `pydantic/types.py:1554-1555` |
| V14 | FastAPI's default route set adds `/openapi.json`, `/docs`, `/docs/oauth2-redirect`, `/redoc`. | `fastapi/applications.py:199,421,445,458` |
| D1 | *documented, not executed*: `hmac.compare_digest` raises `TypeError` for non-ASCII `str`. **This design never depends on it** — both operands are always `bytes` by construction (§5), so the branch is unreachable. | CPython `hmac` docs; `compare_digest` is a C symbol, unreadable here |

Environment: fastapi 0.141.1, starlette 1.6.0, uvicorn 0.52.3, httpx 0.28.1, pydantic 2.13.4.

## 1. Technical approach

One new production module, `app/core/seguridad.py`, exporting an `async` FastAPI dependency. Its
whole design goal is that **indistinguishability is a property of the type system and the control
flow, not of seven `return` statements that happen to agree today**:

1. All parsing lives in **pure predicates that return `bool`**. A `bool` is a one-bit channel: it
   *cannot* encode which of the eight failure modes occurred, so no future edit can make one branch
   leak more than another without first changing a signature.
2. There is **exactly one `raise` site** and **exactly one response-construction site**.
3. The exception type has **no fields**, so it cannot smuggle a reason to the handler.
4. The handler is typed `(Request, Exception) -> Response` (V12), so it *cannot* read anything off
   the exception even if someone tries.

Nothing is wired into the shipped `crear_app()`; a test-only router proves the behaviour (§7).

## 2. Decision — the single rejection path

| Option | Byte-identity guarantee | Failure mode it invites | Verdict |
|---|---|---|---|
| A `return`/`raise` per failure mode | None — seven sites that agree by coincidence | The eighth case added later diverges; nothing detects it | **Rejected** |
| One module-level singleton `Response`, reused | Object identity ⇒ trivially identical | Shared mutable state (V4): one `respuesta.headers[...] = ...` or `set_cookie` anywhere — including a careless test — poisons every future 401 process-wide. Cross-request aliasing is a real bug class, not a hypothetical | **Rejected** |
| **Immutable header constant + one construction site inside one handler** | Byte-identity comes from there being exactly one `Response(...)` expression reachable, reached through a fieldless exception | None material: per-call construction is ~1 µs and has no shared state | **Chosen** |

The singleton's apparent extra safety is illusory: once there is a single construction site, object
identity adds nothing that construction-site uniqueness has not already delivered — while its
shared-mutability hazard (V4) is real. So the design buys identity with *structure*, not with a
shared object.

```python
# app/core/seguridad.py  (illustrative)
_CABECERAS_401: Final[Mapping[str, str]] = MappingProxyType({"WWW-Authenticate": "Bearer"})

class TokenInvalido(Exception):
    """Sin campos y sin argumentos: no puede transportar el motivo del rechazo."""
    __slots__ = ()

def responder_token_invalido(request: Request, exc: Exception) -> Response:
    # Único lugar del repositorio donde se construye la respuesta 401.
    return Response(status_code=401, headers=dict(_CABECERAS_401))

def registrar_manejador_401(app: FastAPI) -> None:
    app.add_exception_handler(TokenInvalido, responder_token_invalido)
```

Per V3 the emitted response is exactly `401`, body `b""`, headers `www-authenticate: Bearer` and
`content-length: 0` — the same two headers for every variant.

### Why `TokenInvalido(Exception)` and not `HTTPException`

The settled decision ("a custom `Response`, not `HTTPException`") is honoured literally, and V6
supplies an independent reason to subclass `Exception` rather than `HTTPException`: for any
`HTTPException` subclass, `status_handlers.get(401)` is consulted **before** the class handler, so
an unrelated `add_exception_handler(401, ...)` registered later by item #3 would silently replace
this 401 with a typed body — exactly the ADR 0014 contamination the proposal forbids. A plain
`Exception` subclass never enters that lookup path.

**Cost, stated honestly**: the empty body now depends on `registrar_manejador_401` being called.
If it is forgotten, the exception is unhandled and the response degrades to Starlette's
`500 Internal Server Error`. That degradation is *safe* on both axes that matter — the request is
still rejected (it never reaches the endpoint), and it is still uniform across all eight variants
(one raise site, no fields, so nothing distinguishes them; V10 shows even the traceback carries no
value). Mitigations: the helper is exported next to the dependency so the two travel together; a
test asserts the pairing; and a missing registration fails loudly on the first protected request
rather than silently.

## 3. Decision — multiple `Authorization` headers (V1)

Starlette's behaviour, verified rather than assumed: `.get()` returns the **first** occurrence and
discards the rest. Inheriting that is unacceptable — "first wins" makes the service's view of the
credential depend on ordering that an intermediary can change, and RFC 9110 list-folding does not
apply to `Authorization`, which is not a list-valued field.

**Decision: read `request.headers.getlist("authorization")` and require exactly one element.**
Zero or two-or-more → reject, through the same predicate as every other variant. This keeps the
settled "raw unvalidated string" policy intact (it is still a plain string, never a typed FastAPI
parameter — decision 3 constrains *validation*, not *which accessor*), while making the outcome
independent of Starlette's iteration order.

"Exactly one" is expressed with structural pattern matching rather than a length comparison, so
that the AST rule in §6 can stay maximally simple (`len` must appear nowhere in the module):

```python
def _credencial_presentada(request: Request) -> str | None:
    match request.headers.getlist("authorization"):
        case [unico]:
            esquema, espacio, credencial = unico.partition(" ")
        case _:                       # ausente, o repetido
            return None
    if esquema.lower() != "bearer" or espacio != " " or credencial == "":
        return None                   # esquema erróneo, sin espacio, credencial vacía
    return credencial
```

| Sub-decision | Choice | Rationale |
|---|---|---|
| Scheme case | **Case-insensitive** (`.lower()`) | RFC 7235 §2.1 defines the scheme as case-insensitive. The scheme is public metadata, so lowering it leaks nothing. Per V2 the string is latin-1-bounded (≤ U+00FF), a range in which `str.lower()` has no ASCII-aliasing surprises — no character maps onto `b`, `e`, `a` or `r`. |
| Credential case | **Exact bytes, never lowered** | Lowering the credential would collapse the secret's case space. `.lower()` is applied to `esquema` only, never to `credencial` — an invariant the AST check in §6 pins. |
| Irregular whitespace | **No dedicated branch** | `"Bearer  x"` yields `credencial == " x"` and `"Bearer x "` yields `"x "`; both simply fail the constant-time comparison. Handling them by comparison instead of by branch removes two branches that could later diverge. |

## 4. Decision — where `get_secret_value()` is unwrapped

```python
def _token_esperado() -> bytes:
    # ÚNICO desenvoltorio del secreto en todo el repositorio (ítem #13 lo verifica).
    # Una sola expresión: el str en claro nunca se liga a un nombre, así que no
    # existe ninguna variable que un logger o un f-string posterior pueda tomar.
    return obtener_configuracion().token_servicio.get_secret_value().encode("utf-8")
```

| Property | Design response |
|---|---|
| Lifetime of the plaintext | One expression, one request. The `str` is an unnamed intermediate on the evaluation stack, freed as soon as `.encode` returns. |
| Why it cannot drift into a log | There is no bound name to log. A future `logger.debug(...)` would have to *add* the `get_secret_value()` call itself — which the item #13 check catches by construction. |
| Why not cache the bytes at module level | It would (a) resurrect import-time configuration construction, breaking item #1's D3 laziness invariant, and (b) keep plaintext resident for the process lifetime. Rejected. |
| Enforcement seam for item #13 | An AST check over `app/**/*.py`: `get_secret_value` appears in exactly one module, and no such `Call` node is an ancestor-argument of a `Call` to `print`/`logging.*`/`str.format`, nor inside a `JoinedStr` (f-string). `JoinedStr` is the concrete node a grep would miss. |

**Conflict found — must be resolved by the tasks phase.** The spec says
`app/core/seguridad.py` "MUST hold the only `get_secret_value()` call in the repository", but
`tests/test_configuracion_token.py:29` already contains one, shipped by item #1. The spec is
authoritative and must not be edited here. Recommended resolution: rewrite that line as
`assert configuracion.token_servicio == SecretStr(token_sentinela)`, which is equivalent (V13) and
removes the source-level call, letting the item #13 rule stay unqualified. Note honestly that this
is a *source-level* fix — `__eq__` still calls `get_secret_value` internally — and that
`SecretStr.__eq__` is **not** constant-time, so it must never be reused in production code.

## 5. Decision — encoding, and why a non-ASCII credential cannot 500

Two different encodings, on purpose:

| Side | Encoding | Why |
|---|---|---|
| Presented credential | `.encode("latin-1")` | Per V2, Starlette produced the `str` by latin-1-decoding the wire bytes, so latin-1 **recovers those exact bytes**. Every codepoint is ≤ U+00FF, therefore this encode is **total** — it cannot raise, so there is no 500 path to guard. |
| Configured token | `.encode("utf-8")` | The env var arrives as a real Python `str`; UTF-8 is its canonical wire form. |

Together these make the comparison "wire bytes vs. UTF-8 of the configured token", which is correct
for **any** token, including one containing non-ASCII or astral characters: a client that sends the
token UTF-8-encoded round-trips exactly. Using `.encode("utf-8")` on *both* sides — the phrasing in
the proposal — would silently break a non-ASCII token, because latin-1-decoded bytes re-encoded as
UTF-8 are mojibake (`b"clav\xc3\xa9"` → `"clavÃ©"` → `b"clav\xc3\x83\xc2\xa9"`). This is a
refinement of the settled decision's *mechanism*, not of its policy (still `hmac.compare_digest` on
UTF-8 bytes of the configured token, still no `len()` pre-check).

Consequences for failure handling:

- A non-ASCII credential produces a clean 401 through the ordinary comparison path — it is simply
  bytes that do not match. No exception, no special case, no branch.
- `TypeError` from `compare_digest` (D1) is unreachable: both operands are `bytes` by construction,
  enforced by `mypy strict`.
- The submitted bytes are never surfaced: they are bound to one local, passed to `compare_digest`,
  and never formatted, logged, or attached to the fieldless exception.
- **Test-authoring consequence (V8)**: httpx encodes `str` header values as ASCII, so a non-ASCII
  case written as a `str` raises `UnicodeEncodeError` *in the client*, before any request exists.
  The malformed matrix MUST supply non-ASCII variants as `bytes`
  (`headers={"Authorization": "Bearer clavé".encode()}`). Getting this wrong yields a test that
  looks red for the wrong reason and invites deleting the case — the exact muted-security-test
  failure the proposal warns about.

## 6. Decision — proving indistinguishability without measuring time

`TECH-DESIGN.md:221` is the mandate, verbatim: *"La comparación del token usa tiempo constante,
**verificable por inspección del código**."* The authoritative acceptance criterion itself asks for
inspection, not measurement — so the structural proof is the compliant choice, not a workaround.

The comparison is isolated into a function whose body is a single statement, so that "no length
check precedes it" becomes "**nothing** precedes it":

```python
def _coincide(presentado: bytes, esperado: bytes) -> bool:
    return hmac.compare_digest(presentado, esperado)
```

What the tests actually inspect:

| Test | Mechanism | Proves |
|---|---|---|
| `test_comparacion_es_de_tiempo_constante` | `ast.parse(Path("app/core/seguridad.py").read_text())`; locate `FunctionDef` `_coincide`; assert `body` is exactly one `ast.Return` whose `value` is one `ast.Call` with `func` = `Attribute(value=Name("hmac"), attr="compare_digest")` | The stdlib comparison is used **and** no statement — length check or otherwise — can precede it |
| `test_no_hay_comparacion_por_longitud` | AST walk of the whole module: assert **zero** `Call` nodes whose `func` is `Name("len")` | The `len()` pre-check the proposal forbids does not exist anywhere, including in future edits |
| `test_compare_digest_se_usa_una_sola_vez` | AST walk: exactly one `compare_digest` `Call` in the module; `import hmac` present | No second, hand-rolled comparison path was added beside it |
| `test_la_credencial_nunca_se_normaliza` | AST walk: no `Call` to `.lower()`/`.upper()`/`.strip()` whose receiver is the `credencial` name | Case/whitespace normalisation is confined to the scheme (§3) |
| `test_respuestas_de_rechazo_son_identicas` | Parametrised over all eight variants; collect `(r.status_code, r.content, tuple(sorted(r.headers.items())))`; assert the set has **exactly one** element | Byte-identity of the whole response, not just the status code. Per V9 no `date`/`server` is injected, so **no header needs excluding** — the assertion is unconditional |
| `test_token_valido_alcanza_el_endpoint` | Correct `Bearer` → 200 and the endpoint body | The accepted path, so the matrix is not vacuously satisfied by rejecting everything |

The eight variants, exactly as the spec enumerates them: header absent · wrong scheme · missing
space · empty credential · irregular whitespace · non-ASCII bytes (as `bytes`, per §5) · two
`Authorization` headers (list-of-pairs, per V8/V9) · well-formed but incorrect.

**No wall-clock assertion exists anywhere in this change**, per the proposal's explicit scope.

## 7. The dependency, its consumption, and the test-only router

```python
async def exigir_token(request: Request) -> None:
    """Cierra toda petición sin credencial válida. Único punto de rechazo."""
    if not _es_valida(request):
        raise TokenInvalido

def _es_valida(request: Request) -> bool:
    credencial = _credencial_presentada(request)
    if credencial is None:
        return False
    return _coincide(credencial.encode("latin-1"), _token_esperado())
```

| Aspect | Decision | Rationale |
|---|---|---|
| `async def` | Yes | A `def` dependency is dispatched to a threadpool by FastAPI. The work is a dict lookup and one `compare_digest` — microseconds — so a threadpool hop per request is pure overhead. |
| Parameter | `request: Request` only | Any other parameter shape would be a typed/validated FastAPI parameter, which V7 shows echoes `input` back in a 422. |
| Return | `None` | Nothing is injected, so the natural attachment is router-level `dependencies=[...]`, which cannot be forgotten per route — matching `app/main.py`'s existing seam comment and ADR 0016's structural exemption. |
| Attachment | `APIRouter(dependencies=[Depends(exigir_token)])` on processor routers | Settled. Never global middleware with a path allow-list (ADR 0016). |
| Ordering inside | Shape first, secret last | The absent/malformed short-circuit never touches the secret. Presence is not secret; content is. |

The test-only router lives in `tests/test_seguridad_token.py` and is built by a fixture:

```python
def crear_app_de_prueba() -> FastAPI:
    app = FastAPI()                      # debug omitido ⇒ False
    registrar_manejador_401(app)
    router = APIRouter(dependencies=[Depends(exigir_token)])
    @router.get("/protegido")
    def protegido() -> dict[str, str]:
        return {"ok": "si"}
    app.include_router(router)
    return app
```

**Why it lives only in the test module**: shipping it would add a route the backlog does not
authorize, and would break the spec's "shipped application route set is unchanged" requirement.
More importantly it would falsify ADR 0016's reasoning — the `/salud` exemption is structural
precisely because the authenticated surface is *exactly* the processor routers; a stray protected
route invented for testing makes that sentence untrue.

A companion test pins the shipped surface: `{(r.path, tuple(sorted(r.methods))) for r in
crear_app().routes}` compared against a literal set containing `/salud` plus FastAPI's four
defaults (V14) — `/openapi.json`, `/docs`, `/docs/oauth2-redirect`, `/redoc`.

## 8. The two capture-surface assertions — what they actually inspect

### `debug=False`

| Layer | What it inspects |
|---|---|
| Runtime | `crear_app().debug is False` and `crear_app_de_prueba().debug is False` |
| Structural | AST scan of `app/**/*.py` **and** `tests/**/*.py`: for every `Call` whose `func` is `Name("FastAPI")`/`Name("Starlette")` or an `Attribute` with that `attr`, assert no `keyword` named `debug` unless its value is `Constant(False)`. This is what makes the spec's "including any test-only app or router fixture" enforceable rather than aspirational. |

Note for the apply phase: `TestClient` defaults to `raise_server_exceptions=True`, which re-raises
server exceptions instead of rendering them. Any test that wants to observe a rendered error
response must pass `raise_server_exceptions=False`; a test that omits it is asserting on an
exception, not on a response.

### Access log

Per V10 the format string carries no header values, and per V11 `uvicorn.access` has
`propagate: False`, so **`caplog` cannot see it** — a `caplog`-based test would pass vacuously by
capturing nothing. `TestClient` never exercises uvicorn at all, so the line has to come from a real
server.

Design: run `uvicorn.Server` in a background thread bound to port 0; attach a plain
`logging.Handler` **directly to `logging.getLogger("uvicorn.access")`** (which per V10 also enables
emission, since the protocol gates on `hasHandlers()`); issue one request carrying
`Authorization: Bearer <sentinel>`; assert the captured line contains the method and path, and
contains **neither** the sentinel nor the substring `Bearer`. If no line is captured within a
bounded wait, the test **fails** — it must never skip, because a silently-skipped security test is
the failure mode this change exists to avoid.

**Verified constraint worth recording**: the access line includes the path *with query string*
(V10). The token therefore MUST NOT be accepted as a query parameter — not now, and not by item
#10's client. This design accepts it in the `Authorization` header only, which is also why the
header was chosen (proxies redact it by default).

## 9. Recommendation — local ADR 0017

**Recommend: yes.** `0011`–`0016` are taken locally and `0001`–`0010` are inherited, so `0017` is
free and collides with nothing. The tasks phase decides whether this change authors it.

Rationale for a durable record rather than a design-only note: the header/scheme and the empty-body
401 are **cross-repository contract decisions** that outlive this change. Item #10's portal client
must send exactly this header, and item #3 will define the typed error contract — at which point
the natural instinct is to "finish the job" by giving the 401 an ADR 0014 `{"tipo", "contexto"}`
body. ADR 0014's enum is closed and 401 is deliberately outside it; without a written decision that
boundary is one refactor away from disappearing. V6 shows the mechanism by which it would
disappear silently (a status-code handler registered for 401).

Outline — `adrs/0017-token-de-servicio-en-authorization-bearer.md`, MADR in Spanish matching its
siblings (**Estado / Contexto / Decisión / Alternativas consideradas / Consecuencias**):

- **Contexto**: the PRD requires a token "en los headers" with a 401 "sin pistas", but names no
  header and no scheme; ADR 0014's error vocabulary excludes 401.
- **Decisión**: `Authorization: Bearer <token>`; 401 with an empty body plus `WWW-Authenticate:
  Bearer`; the 401 is explicitly outside ADR 0014's enum and must never acquire a typed body.
- **Alternativas**: a custom header such as `X-Token-Servicio` (rejected — proxies and logging
  stacks redact `Authorization` by default and will not redact an invented name); an ADR 0014-shaped
  401 body (rejected — the enum is closed and any body is leak surface the PRD forbids); omitting
  `WWW-Authenticate` (rejected — RFC 7235 says a 401 SHOULD carry it, and it names only the scheme,
  which this ADR itself makes public).
- **Consecuencias**: the portal must send the header verbatim; the 401 is deliberately unlike every
  other error response the service emits, so item #3 must special-case it; an empty body means a
  client cannot distinguish auth failure modes — which is the point.

## 10. Sequence diagram — both paths

```mermaid
sequenceDiagram
    autonumber
    participant CL as Cliente (portal, ítem #10)
    participant ST as Starlette / FastAPI routing
    participant DEP as exigir_token (Depends)
    participant PAR as _credencial_presentada
    participant CMP as _coincide (hmac)
    participant CFG as obtener_configuracion (lru_cache)
    participant MAN as responder_token_invalido
    participant EP as Endpoint protegido

    CL->>ST: GET /interno/... con Authorization
    ST->>DEP: solve_dependencies (sin cuerpo que leer en este cambio)
    DEP->>PAR: getlist("authorization")
    alt ausente, repetida, esquema erróneo, sin espacio o credencial vacía
        PAR-->>DEP: None
        Note over DEP: cortocircuito: el secreto nunca se desenvuelve
    else exactamente una cabecera bien formada
        PAR-->>DEP: credencial (str, latin-1)
        DEP->>CFG: token_servicio.get_secret_value()
        CFG-->>DEP: bytes UTF-8 (único desenvoltorio del repo)
        DEP->>CMP: compare_digest(latin-1(credencial), esperado)
        CMP-->>DEP: True | False
    end
    alt _es_valida == False  (los ocho casos convergen acá)
        DEP--xST: raise TokenInvalido   (sin campos, sin argumentos)
        ST->>MAN: _lookup_exception_handler → MRO
        MAN-->>CL: 401 · cuerpo vacío · WWW-Authenticate: Bearer · content-length: 0
        Note over MAN,CL: única construcción de Response del repositorio;<br/>respuesta byte-idéntica para las ocho variantes
    else _es_valida == True
        DEP-->>ST: None (nada inyectado)
        ST->>EP: ejecuta el endpoint
        EP-->>CL: 200
    end
```

## 11. File changes

| File | Action | Description |
|---|---|---|
| `app/core/seguridad.py` | Create | `exigir_token`, `TokenInvalido`, `responder_token_invalido`, `registrar_manejador_401`, and the three private helpers (§2–§5) |
| `tests/test_seguridad_token.py` | Create | Test-only app fixture, eight-variant matrix, byte-identity assertion, accepted path, shipped-route-set pin |
| `tests/test_seguridad_estructural.py` | Create | The five AST assertions of §6 plus the `debug` scan of §8 |
| `tests/test_seguridad_access_log.py` | Create | Threaded uvicorn + `uvicorn.access` handler capture (§8) |
| `tests/test_configuracion_token.py` | Modify | One line: drop the second `get_secret_value()` call site (§4) |
| `adrs/0017-token-de-servicio-en-authorization-bearer.md` | Create *(recommended; tasks decides)* | §9 |

**Not touched**: `app/main.py`, `app/core/configuracion.py` (its `min_length=1` floor is
load-bearing), `app/salud.py`, `crear_app()`'s route set.

## 12. Testing strategy

| Layer | What to test | Approach |
|---|---|---|
| Unit | `_credencial_presentada` returns `None` for each malformed shape | Direct call with hand-built `Request(scope)`, including a raw `0xFF` byte to exercise the latin-1 boundary of §5 |
| Unit | `_coincide` returns `True`/`False` on equal/unequal bytes | Direct call |
| Integration | Eight-variant byte-identity + accepted path | `TestClient(crear_app_de_prueba())`, single-element set assertion (§6) |
| Integration | Shipped route set unchanged | Literal set comparison against `crear_app()` (V14) |
| Structural | Constant-time comparison, no `len`, single `compare_digest`, no credential normalisation | `ast.parse` over `app/core/seguridad.py` (§6) |
| Structural | Single `get_secret_value()` call site, never in a logging call or `JoinedStr` | AST walk over `app/**/*.py` (§4) |
| Structural | No `debug=True` anywhere, including test fixtures | AST walk over `app/**` and `tests/**` (§8) |
| E2E | Token absent from all captured output on every variant | Fresh-interpreter subprocess via the existing `tests/ayudas/subproceso.py`, sentinel substring assertion — the pattern item #1 established |
| E2E | Access log carries no header value | Threaded uvicorn + direct handler on `uvicorn.access` (§8) |

RED-first ordering under Strict TDD (`uv run pytest`): matrix/byte-identity → accepted path →
parsing units → structural AST → leak/output → access log.

## 13. Threat matrix

Boundary trigger: this change touches **routing** (a dependency that gates route execution). The
reference matrix's rows are VCS/PR-shaped and are `N/A` here; the real boundaries follow.

| Boundary | Applicability | Design response | Planned RED test |
|---|---|---|---|
| Documentation-like paths | N/A — no file is classified or executed by content type | — | — |
| Git repository selection / commit state / push state / PR commands | N/A — no VCS or PR automation | — | — |
| Shell / subprocess | Applicable (tests only) | Reuses `tests/ayudas/subproceso.py`: list argv, `shell=False`, no interpolation; ruff `S` enforces | Existing helper test; no new subprocess surface |
| **Auth bypass via header ambiguity** | **Applicable** | Exactly-one-`Authorization` rule (§3), independent of Starlette's first-wins ordering (V1) | Duplicate-header variant in the matrix |
| **Failure-mode disclosure** | **Applicable** | One `bool` channel, one raise site, one construction site, fieldless exception (§2) | Byte-identity assertion across all eight variants |
| **Secret disclosure via echo/render** | **Applicable** | Raw-string parsing (V7), no typed parameter, `debug=False` (§8), single unwrap site (§4), fieldless exception | Sentinel-absence E2E; AST checks; access-log test |
| **Timing disclosure between wrong credentials** | **Applicable** | `hmac.compare_digest`, no `len()` pre-check, comparison isolated to a one-statement function | Structural AST proof (§6) — never wall-clock |
| **New public route** | N/A — this change adds **no** shipped route | Route-set pin proves it | Shipped-route-set test |

## 14. Review budget forecast

Honest estimate; `sdd-tasks` owns the formal guard lines.

| Artifact | Est. changed lines |
|---|---|
| `app/core/seguridad.py` | 85–95 |
| `tests/test_seguridad_token.py` | 150–175 |
| `tests/test_seguridad_estructural.py` | 145–170 |
| `tests/test_seguridad_access_log.py` | 55–70 |
| `tests/test_configuracion_token.py` | 2 |
| `adrs/0017-*.md` (if authored here) | 60–70 |
| **Total** | **497–582** |

This **exceeds the 400-line budget**, and it exceeds the proposal's own 250–350 estimate. The
proposal's figure did not cost the access-log test, the six AST assertions, or the `debug` scan —
roughly 200 lines of test that the spec's last three requirements make mandatory. Recommended
split into two autonomous, independently verifiable slices:

- **Slice A — the rejection guarantee** (~300 lines): `app/core/seguridad.py`, the eight-variant
  matrix, the accepted path, the shipped-route-set pin, and the constant-time AST proof. Delivers
  the spec's first three requirements in full.
- **Slice B — the capture surfaces** (~200 lines): the `get_secret_value` AST check, the `debug`
  scan, the access-log test, the `test_configuracion_token.py` line, and ADR 0017. Delivers the
  remaining four requirements.

Since `delivery_strategy` is `ask-on-risk`, this needs an explicit decision before apply.

## 15. Recorded, not solved — inherited forward constraint on item #6

FastAPI's `routing.get_request_handler` reads the request body (`await request.form()` /
`await request.body()`) **strictly before** `solve_dependencies` runs, identically for per-route
`Depends(...)` and per-router `dependencies=[...]` (verified in installed FastAPI 0.141.1; upstream
`fastapi/fastapi#4941`). No route in this change declares a body, so "401 before reading the
request body" is trivially satisfied today.

Item #6's `UploadFile` routes will **not** get that guarantee from `Depends()`: a full multipart
parse completes before `exigir_token` runs. Item #6 will need raw ASGI middleware or a
`Mount`-scoped sub-app inspecting `scope["headers"]` before calling `receive()` — scoped to the
processor sub-app, not a path allow-list, so ADR 0016 stays intact. **This is recorded as item #6's
design problem and is explicitly not addressed here.**

## 16. Migration / rollout

No migration. New files only; nothing wired into `crear_app()`; no route, schema, or runtime state
changes. Rollback = revert the commit(s) / delete `app/core/seguridad.py` and its tests (and revert
the one-line `test_configuracion_token.py` edit).

## 17. Open questions

- [ ] **Blocking for tasks**: the spec's "only `get_secret_value()` call in the repository"
      contradicts the shipped `tests/test_configuracion_token.py:29`. §4 proposes the one-line fix;
      the alternative is to scope the item #13 rule to `app/**/*.py`. The spec must not be edited
      here, so tasks must choose.
- [ ] **Needs a decision before apply**: the 497–582-line forecast exceeds the 400 budget under
      `ask-on-risk`. Two-slice split recommended (§14).
- [ ] Whether this change authors ADR 0017 or defers it to item #3, which will revisit the 401's
      relationship to ADR 0014's enum. §9 recommends authoring it now, because the boundary is
      easiest to erase precisely when item #3 is written.
- [ ] `D1` (`compare_digest` raising `TypeError` on non-ASCII `str`) is documented but was not
      executed here — no shell was available. The design does not depend on it (§5), but the apply
      phase runs with a shell and should confirm it in passing rather than inherit the claim.

## Post-implementation corrections

One claim in this document was disproven during implementation. It is recorded here rather than
silently patched, following the precedent set by item #1's archived design.

| Claim as originally written | Reality | Evidence |
|---|---|---|
| **V14** treated `crear_app()`'s route set as a flat list, so the shipped-route-set pin could compare `app.routes` entries directly by `.path` | `include_router` does **not** flatten included routes into `app.routes`. It appends a `_IncludedRouter` wrapper object that has no `.path` and no `.methods`, exposing the real routes under `.original_router.routes`. A direct comparison misclassifies the wrapper instead of inspecting the routes it holds | On FastAPI 0.141.1 / Starlette 1.6.0, building an app and calling `include_router` yields four plain `Route` objects (the FastAPI doc defaults, each with `.path`) plus one `_IncludedRouter` with `.path` absent and `.original_router` present |

The implementation therefore added a recursive flattening helper (`_rutas_efectivas`) before comparing
against the baseline literal. A second, smaller observation from the same check: `/salud`'s effective
methods are `{"GET"}` only — it does not gain an automatic `HEAD`, unlike the four FastAPI doc routes,
which do carry `GET` and `HEAD`. The baseline literal records the verified actual set.

### Environment hazard found while verifying

Bare `python` on this machine resolves to `C:\Python312\python.exe`, which carries FastAPI 0.115.14
and Starlette 0.46.2 — **not** the project's pinned FastAPI 0.141.1 / Starlette 1.6.0, which live in
`L:\API-Portal\.venv`. Every library-behavior claim in this design (the header-duplication semantics,
the latin-1 decoding, the response-header mutability, the exception-handler precedence, and the route
wrapper above) is true of the pinned versions and must be re-checked through `uv run` rather than a
bare interpreter. Verifying against the wrong interpreter is exactly how a design acquires claims that
are locally true and globally wrong.
