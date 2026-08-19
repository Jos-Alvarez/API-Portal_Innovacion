# Tasks: Reception and Lifecycle of Temporary Files

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 760–895 (design §12) |
| 600-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | Slice A (~545–630) → Slice B (~235–285) |
| Delivery strategy | ask-on-risk |
| Chain strategy | stacked-to-main |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
600-line budget risk: High

Design §12 forecasts run 30–50% short every prior item, always through the test file; the ranges
above already include design's own +40% test correction — do not correct again.

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| Slice A | `Reserva` ownership model + sweeper, lifespan wiring, ADR 0020 — fully green alone | PR 1 | `uv run pytest tests/test_temporales.py` | `uv run pytest` (full suite, 108+N green, no route exists yet) | Remove the 3 lifespan lines from `app/main.py`, delete `app/core/temporales.py`, `tests/test_temporales.py`, `adrs/0020-*.md` |
| Slice B | `app/recepcion.py` route consuming Slice A, `python-multipart` dependency, route-pin update | PR 2 | `uv run pytest tests/test_recepcion.py` | `uv run pytest` (full suite, route reachable through `/interno`) | Remove `include_router` line from `app/main.py`, delete `app/recepcion.py`, `tests/test_recepcion.py`, drop `python-multipart` from `pyproject.toml` and re-lock, restore prior route-pin literal in `tests/test_seguridad_token.py` |

Both units land as stacked PRs to `main`, in order — PR 2 depends on PR 1 having merged (it imports
`app.core.temporales`). No feature/tracker branch is needed since only two slices exist and PR 2's
base is simply `main` after PR 1 merges.

## Slice A — `Reserva` ownership model and the sweeper

### Phase A1: `app/core/temporales.py` — root, ownership, sweeper

- [x] A1.1 Create `app/core/temporales.py` with module docstring citing ADR 0011 (module name
      inherited), ADR 0006 (ownership rationale), ADR 0020 (this change's own record). Import only
      stdlib plus `starlette.concurrency.run_in_threadpool` and `starlette.background.BackgroundTask`
      — no `app/procesadores/` import (ADR 0011 invariant).
- [x] A1.2 Define `_PREFIJO_PETICION` and `_raiz()` returning
      `Path(tempfile.gettempdir()) / "api-portal-temporales"` (design §3.1). Define
      `UMBRAL_DE_EDAD: Final[timedelta] = timedelta(minutes=15)` and
      `INTERVALO_DE_BARRIDO: Final[timedelta] = timedelta(minutes=5)` as adjacent named constants
      (design §3.3) — not `Configuracion`.
- [x] A1.3 Implement `preparar_raiz()` (`mkdir(parents=True, exist_ok=True)` on the dedicated root,
      design §3.1).
- [x] A1.4 Implement module-level `_EN_VUELO: dict[Path, float]` and the `Reserva` class
      (`directorio`, `_cedida`, `ceder_limpieza() -> BackgroundTask`, `limpiar()` — idempotent,
      pops `_EN_VUELO` then `shutil.rmtree(ignore_errors=True)`) exactly as design §2 specifies.
- [x] A1.5 Implement `reservar()` as a `@contextmanager`: `mkdtemp(prefix=_PREFIJO_PETICION,
      dir=_raiz())`, register in `_EN_VUELO` with `time.monotonic()`, `try/finally` that calls
      `reserva.limpiar()` only when `not reserva._cedida`, otherwise pops `_EN_VUELO` without
      deleting (design §2). Defensively call `_raiz().mkdir(...)` here too so a mid-test `rmtree`
      cannot break the service (design §3.1).
- [x] A1.6 Implement `barrer(*, umbral: timedelta = UMBRAL_DE_EDAD, ahora: float | None = None) ->
      None` as a plain synchronous function of `(root, threshold, now)` (design §3.3 testability
      hook): evict `_EN_VUELO` entries older than `umbral` first, then delete direct children of the
      root that are absent from `_EN_VUELO` and older than `umbral` by mtime (design §3.2's two-
      condition rule, both required). `ahora` defaults to `time.monotonic()`.
- [x] A1.7 Implement `_bucle_de_barrido()` (sleep first, then `await run_in_threadpool(barrer)`) and
      `ciclo_de_vida(app: FastAPI)` per design §3.5: `obtener_configuracion()`, `preparar_raiz()`,
      one startup `await run_in_threadpool(barrer)` pass, `asyncio.create_task(_bucle_de_barrido())`
      held in a local variable, `yield`, then in `finally`: `tarea.cancel()` wrapped in
      `with suppress(asyncio.CancelledError): await tarea`.

### Phase A2: Wire the lifespan into `app/main.py`

- [x] A2.1 Replace `app/main.py`'s inline `ciclo_de_vida` (currently only
      `obtener_configuracion()` + `yield`) with `app.core.temporales.ciclo_de_vida`, preserving the
      existing "fails closed first" ordering comment. Confirm no other lifespan seam comment
      (`# costura #5`, `# costura #11`) is disturbed.

### Phase A3: `tests/test_temporales.py` — behavioural tests only

- [x] A3.1 Unit: `ceder_limpieza()` makes `Reserva.__exit__`/`reservar()`'s `finally` a no-op, and the
      returned `BackgroundTask` deletes the directory after it runs — via a **test-only**
      `FileResponse` route in this test module (design §8, items #2/#3 pattern). Assert the directory
      exists during the send and is gone after.
- [x] A3.2 Unit: `barrer(umbral=timedelta(0))` does **not** delete a directory registered in
      `_EN_VUELO`, even with a backdated mtime (design §3.2, §8).
- [x] A3.3 Unit: `barrer` evicts a stale `_EN_VUELO` entry (registered longer than `umbral` ago) and
      deletes its directory in the same pass — the registry cannot leak (design §3.2, §8).
- [x] A3.4 Unit: `barrer` touches nothing outside its dedicated root — create a sibling file directly
      in `tempfile.gettempdir()`, sweep, assert it survives (design §3.1, §8; this is the test that
      proves the sweeper is safely scoped).
- [x] A3.5 Unit: the disconnect hole is real and the sweeper closes it — abort a `reservar()`-owned
      directory mid-stream (or simulate via a directory left un-ceded and un-cleaned), assert it
      survives immediately after, then `barrer(umbral=timedelta(0))` and assert it is gone (design §8,
      "the one test that proves H-02's degradation is bounded rather than asserted").
- [x] A3.6 Unit: the startup pass removes a pre-existing orphan — plant an aged directory under the
      root before entering `ciclo_de_vida`, run the lifespan (e.g. via `TestClient` context entry),
      assert the orphan is gone.
- [x] A3.7 Unit: shutdown cancels the sweeper task and does not hang — enter and exit
      `ciclo_de_vida` (e.g. via `TestClient` context manager), assert completion within the test's
      own timeout and that the task is done/cancelled.
- [x] A3.8 Unit: `_formato` behaviour is Slice B's — do not test it here; `_formato` lives in
      `app/recepcion.py` per design §5.

### Phase A4: ADR 0020

- [x] A4.1 Write `adrs/0020-ciclo-de-vida-de-los-temporales.md`, MADR format matching
      `adrs/0011`–`0019`, neutral professional Spanish, sections **Estado / Contexto / Decisión /
      Alternativas consideradas / Consecuencias** (design §9):
      - Contexto: H-02 (Crítico, Abierto), ADR 0006's `try/finally` deletes before ASGI streams
        the response; quote ADR 0006's own "una vez enviada la respuesta HTTP" wording; carry V11's
        measurement verbatim (both `FileResponse` and `StreamingResponse` skip cleanup on mid-stream
        disconnect).
      - Decisión: ownership model with one transfer point (`Reserva.ceder_limpieza()`); dedicated
        root plus `_EN_VUELO`-and-age sweeper; the two named constants (15 min / 5 min); startup pass
        plus periodic task; on-disk names always server-generated.
      - Alternativas consideradas: response-class swap (rejected, fixes nothing per V11);
        early-unlink (rejected, POSIX-only, ADR 0012 leaves target undecided); read-into-memory
        (rejected, contradicts ADR 0006's reason temporaries are on disk); ASGI middleware inside the
        mount (rejected — moves cleanup out of the pipeline ADR 0006 makes its owner, creates a
        directory for every request including empty ones, still needs the startup pass); sanitising
        `nombre_original` (rejected — server-generated names close traversal/accents/duplicates in
        one decision instead of three escaping rules).
      - Consecuencias: acceptance criterion weakens honestly from "zero after the response" to
        "zero within 20 minutes" on a mid-stream disconnect; sweeper doubles as the retry path for a
        Windows `PermissionError` on `rmtree`; **`_EN_VUELO`'s soundness depends on ADR 0012's single
        API worker and must be revisited if item #0 ever chooses a multi-worker deployment**
        (verified fact 3 from the launch brief — this line is required, not optional); H-09 cases 2–4
        close here, case 1 (`Content-Length` lie) stays item #7's; the parametrised route (Slice B) is
        temporary scaffolding deviating from ADR 0006's per-processor design.

### Phase A5: Slice A verification

- [x] A5.1 Run `uv run pytest` — full suite green, including `tests/test_temporales.py`. No route
      exists yet, so no other test file changes.
- [x] A5.2 Run `uv run ruff check .` and `uv run ruff format --check .`.
- [x] A5.3 Run `uv run mypy app tests`.

## Slice B — the reception route

### Phase B1: Dependency

- [x] B1.1 Add `python-multipart` to `pyproject.toml`'s `[project].dependencies` (design §6, V1 —
      genuinely absent from `.venv` and `uv.lock`).
- [x] B1.2 Run `uv lock` to regenerate `uv.lock` (new `[[package]]` block plus dependency edge under
      `api-portal`). Generated lines, never hand-edited.

### Phase B2: `app/recepcion.py` — the route

- [x] B2.1 Create `app/recepcion.py` following the `app/salud.py` precedent (top-level router module,
      not under `app/procesadores/`, per design §1/V10). Module docstring flags the route as
      temporary reception scaffolding deviating from ADR 0006's per-processor design (design §4),
      pointing at ADR 0020.
- [x] B2.2 Define `router_recepcion = APIRouter()` and `_formato(nombre_original: str) -> str` using
      `nombre_original.rpartition(".")`, lowercased extension, **never** `Path(nombre_original).suffix`
      (design §5 — this is the exact rule the launch brief calls out).
- [x] B2.3 Define `_copiar(origen: IO[bytes], destino: Path) -> int`: `origen.seek(0)` defensively,
      `shutil.copyfileobj(origen, salida, _TROZO)` with `_TROZO: Final[int] = 1024 * 1024`, return
      `salida.tell()` (design §5). Wrap the actual write in `run_in_threadpool` at the call site so
      it never blocks the event loop (design §3.5's V9/blocking-I/O rationale applies equally here).
- [x] B2.4 Implement `POST /procesadores/{clave_procesador}` accepting
      `archivos: Annotated[list[UploadFile], File()]`: `with reservar() as reserva:` build one
      `ArchivoEntrada` per upload (`nombre_original` verbatim from `carga.filename or ""`,
      `ruta_temporal = reserva.directorio / f"entrada_{indice}"`, `tamano_comprimido` = bytes
      actually written, `formato` via `_formato`), call `obtener_contrato(clave_procesador)`, and
      `raise ErrorClaveInexistente(clave_procesador=clave_procesador, causa="fila_ausente")` when it
      returns `None` (always true today, V8) — matching design §4's illustrative route exactly,
      including the `entradas` list being built and then unused (the seam item #7 consumes).

### Phase B3: Wire the route

- [x] B3.1 In `app/main.py`, import `router_recepcion` from `app/recepcion.py` and call
      `router_interno.include_router(router_recepcion)` inside `crear_app()`, after
      `router_interno = APIRouter()` and before the `Mount` is appended (design §4/§6).

### Phase B4: Update the shipped route pin — will go red first

- [x] B4.1 In `tests/test_seguridad_token.py::test_rutas_de_produccion_no_cambian`, add
      `("/interno/procesadores/{clave_procesador}", ("POST",))` to the `esperado` set. Leave
      `esperado_montajes` unchanged (still `{"/interno"}`, per V5/V6). State explicitly in the task
      log/commit message that this shipped test **will go red** the moment B3.1 lands and turning it
      green here is the deliberate pin-update convention `service-token-auth` established (design §6,
      spec "Shipped route set changes deliberately, pin updated").

### Phase B5: `tests/test_recepcion.py` — behavioural tests only

- [x] B5.1 Integration: one multipart upload writes a file inside the per-request temporary
      directory; the response's typed-error path still fires (`ErrorClaveInexistente`,
      `causa="fila_ausente"`, 500) — assert on the directory via a test-only hook or by asserting the
      directory exists during the request and is gone after, matching design §8.
- [x] B5.2 Integration: hostile `nombre_original` values (`../../x`, `C:\x`, `/etc/x`, accented)
      write only inside the per-request directory; assert nothing exists at any path derived from the
      declared name (spec "On-disk name is never derived from client input").
- [x] B5.3 Integration: two uploads sharing one `nombre_original` in the same request produce two
      distinct files with distinct contents preserved (spec "Duplicate names in one request do not
      collide").
- [x] B5.4 Integration: any `clave_procesador` value returns 500 with full-body equality
      `{"tipo": "clave_inexistente", "contexto": {"clave_procesador": ..., "causa": "fila_ausente"}}`
      (spec "Every request today resolves to the missing-processor error").
- [x] B5.5 Integration: zero temporaries remain after a completed response — assert the dedicated
      root has no `pet-*` children once the response finishes (spec "Happy-path response leaves no
      temporary behind").
- [x] B5.6 Integration: a request missing the `archivos` field returns a bodiless 422 via the
      already-shipped `responder_validacion_invalida` handler (design V7 — first time this handler is
      reachable in production; worth a test because of that, not because it's new code).
- [x] B5.7 Integration: 401 arrives before the multipart body is read, extending the shipped mount
      coverage to this route's path (spec "The route is unreachable without the mount's token").
- [x] B5.8 Unit: `_formato` on `"a.b.XLSX"` → `"xlsx"`, `"sin-extension"` → `""`, `""` → `""`,
      `"..\\x.xlsx"` → `"xlsx"` — direct calls, no HTTP layer (design §5/§8).
- [x] B5.9 Security: the raw service token appears in no response body and no captured log across the
      valid-upload, missing-processor-error, and disconnected-upload paths — reuse the item #1/#2
      sentinel-token convention (`caplog` plus response bodies) already established in
      `tests/test_seguridad_token.py` (spec "Service token never appears in reception's responses or
      logs").

### Phase B6: Slice B verification

- [x] B6.1 Run `uv run pytest` — full suite green, including `tests/test_temporales.py`,
      `tests/test_recepcion.py`, and the updated `tests/test_seguridad_token.py` pin.
- [x] B6.2 Run `uv run ruff check .` and `uv run ruff format --check .`.
- [x] B6.3 Run `uv run mypy app tests`.

## Notes carried from design, not solved here

- `background=` cannot attach on today's error path because the response is built by the registered
  `ErrorTipificado` handler, which knows nothing about the request's temporaries — this is why the
  `finally`-cleans-unless-ceded ownership model (Phase A1) is the chosen shape, not a gap to close in
  Slice B. `ceder_limpieza()` is proven only by the test-only `FileResponse` route in
  `tests/test_temporales.py` (A3.1); items #9/#10 are the ones that change the route's `return` to
  use it for real.
