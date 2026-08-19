# Tasks: Bounded Admission and Dedicated-Process Execution (BACKLOG item #8)

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~1145–1493 (design §11; production ~450–578, tests ~695–915) |
| 600-line budget risk | High — resolved: total exceeds both 400 and 600; delivered as four chained slices, each independently under 600 |
| Chained PRs recommended | Yes |
| Suggested split | S1 (vocabulary + configuration) → S2 (admission) → S3 (process plumbing) → S4 (module composition) |
| Delivery strategy | ask-on-risk — risk already resolved by the user: proceed with the four-slice chain, no further question |
| Chain strategy | stacked-to-main |

Decision needed before apply: No — chain strategy and slicing already accepted by the user
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
600-line budget risk: High

Budget note: the session-passed 400 and `openspec/config.yaml:42`'s 600 conflict is resolved in favor of **600** (explicit user instruction, matches the raised project budget). S2 (~360–470) and S3 (~385–490) each sit comfortably under 600; splitting either further is rejected per design §11 — the middleware and its release proof must land together, and the plumbing plus the deliberate children that exercise it are one reviewable unit.

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| S1 | Config fields, `ErrorTipificado.__reduce__`, ADR 0022 | PR 1 | `uv run pytest tests/test_configuracion_ejecucion.py tests/test_errores_tipificados.py` | N/A — pure unit, no route, no subprocess | Revert commit; purely additive, no caller yet |
| S2 | Admission middleware, semaphore, 503 handler | PR 2 | `uv run pytest tests/test_admision.py` | `TestClient` against `crear_app()` with `EJECUCIONES_MAX=1`, real ASGI middleware stack, no subprocess | Revert commit; drops the Mount's second middleware entry and the 503 handler registration — route returns to today's unconditional behavior |
| S3 | Pipe plumbing, classifier, deliberate child harness | PR 3 | `uv run pytest tests/test_ejecucion.py` | `ejecutar_aislado` against real `multiprocessing.Process` targets in `tests/ayudas/hijos.py` (spawn, hang, `os._exit(N)`, silent exit, typed error, raise) | Revert commit; deletes the process half of `ejecucion.py`, no production caller depends on it |
| S4 | `_ejecutar_en_hijo`, `ejecutar_modulo`, `interfaz.py` docstring | PR 4 | `uv run pytest tests/test_ejecucion.py -k registry` | Real spawn against the empty production `REGISTRY` (V9) — no test hook | Revert commit; drops `ejecutar_modulo`/`_ejecutar_en_hijo`, restores `interfaz.py`'s prior caveat |

## Phase 1: S1 — Vocabulary and configuration (PR 1)

- [x] 1.1 `app/core/configuracion.py`: add `CORTE_DEL_PORTAL: Final[timedelta] = timedelta(minutes=2)`, `ejecuciones_max: Annotated[int, Field(ge=1, le=32)] = 2`, `timeout_ejecucion: timedelta = timedelta(seconds=60)`; document both as conservative placeholders pending item #17 (`configuration` spec, Requirement "Both fields are documented as conservative placeholders")
- [x] 1.2 `app/core/configuracion.py`: add `@model_validator(mode="after") _timeout_por_debajo_del_corte` enforcing `timeout_ejecucion < CORTE_DEL_PORTAL`, message built from `loc`/`type` only, no value leaked (`configuration` spec, Requirement "TIMEOUT_EJECUCION is a required, positive duration strictly below the portal's 2-minute cutoff")
- [x] 1.3 `app/core/errores.py`: add module-level `_reconstruir(cls) -> ErrorTipificado` (`cls.__new__(cls)`, bypasses keyword-only `__init__`) and `ErrorTipificado.__reduce__` returning `(_reconstruir, (type(self),), dict(self.__dict__))` (design §5, verified fact: current subclasses raise `TypeError` on `pickle.loads`)
- [x] 1.4 `tests/test_configuracion_ejecucion.py` (new): `EJECUCIONES_MAX` missing/zero/negative fails startup; positive value starts; `le=32` bound; `TIMEOUT_EJECUCION` missing/zero/negative fails startup; value `>=` 2 minutes fails with a validator message naming the relationship; value strictly below 2 minutes starts; assert no raw value appears in the error message
- [x] 1.5 `tests/test_errores_tipificados.py`: add a pickle round-trip test for every concrete `ErrorTipificado` subclass (`ErrorClaveInexistente`, `ErrorFormato`, `ErrorTamano` — both context shapes, `ErrorContenido`, `ErrorAutenticacion`) asserting `tipo` and full `contexto` survive `pickle.loads(pickle.dumps(e))` intact
- [x] 1.6 `adrs/0022-admision-acotada-y-plomeria-del-proceso-dedicado.md` (new, next free number confirmed against `adrs/` on disk — 0011 through 0021 exist, `openspec/config.yaml:8`'s "0011-0015 exist" comment is stale): MADR format matching 0011–0021, records the five decisions in design §12 (slot lifetime/single release site, ADR 0012's module-exception row not implemented as written, `matado`-flag discrimination with the Windows exitcode-normalization evidence, `daemon=True` and its `joblib`/`n_jobs>1` constraint on #12/#16, `ErrorTipificado` pickling guarantee)
- [x] 1.7 Verify: `uv run ruff check . && uv run ruff format --check . && uv run mypy app tests && uv run pytest`

## Phase 2: S2 — Admission (PR 2)

- [x] 2.1 `app/core/ejecucion.py` (new file, admission half): `obtener_semaforo() -> threading.BoundedSemaphore` as `@lru_cache(maxsize=1)` reading `ejecuciones_max` from config — lazy so import has no side effect (spawn precondition)
- [x] 2.2 `app/core/ejecucion.py`: `class ServicioSaturado(Exception)`, `responder_servicio_saturado(request, exc) -> Response` (bare 503, no body — 401/422 pattern), `registrar_manejador_503(app: FastAPI) -> None`
- [x] 2.3 `app/core/ejecucion.py`: `@contextmanager admitir() -> Iterator[None]` — `acquire(blocking=False)` raises `ServicioSaturado` before `try:` on failure (no release pairs with it); success enters `try/finally: semaphore.release()` as the only `release()` call in the repository (design §3)
- [x] 2.4 `app/core/ejecucion.py`: `class AdmisionDeBorde` ASGI middleware — passthrough for non-`http` scope types, otherwise wraps `await self.app(...)` in `with admitir():`
- [x] 2.5 `app/main.py`: add `Middleware(AdmisionDeBorde)` as the **second** entry on the existing `Mount("/interno", ...)`'s `middleware=[...]` list (auth outermost — V1); register `registrar_manejador_503(app)`
- [x] 2.6 `tests/conftest.py`: extend the config/cache-clear fixture to cover `ejecuciones_max`/`timeout_ejecucion` env vars and clear `obtener_semaforo`'s `lru_cache` between tests
- [x] 2.7 `tests/test_admision.py` (new): unit — `admitir()` releases on return and on exception; failed `acquire(blocking=False)` raises `ServicioSaturado` and releases nothing
- [x] 2.8 `tests/test_admision.py`: integration — slot released on every inner-app outcome (200, `ErrorTipificado`, `RuntimeError`, `EjecucionExpirada`, `NotImplementedError`, cancelled task) via a tiny inner ASGI app wrapped directly in `AdmisionDeBorde` (`bounded-execution` spec, Requirement "The admission slot releases on all four exit paths")
- [x] 2.9 `tests/test_admision.py`: 503 end-to-end, deterministic — real `crear_app()` + `TestClient(raise_server_exceptions=False)`, `EJECUCIONES_MAX=1`, pre-acquire the slot before the request (saturation by pre-acquisition, never racing threads) (`bounded-execution` spec, Requirement "Admission is rejected immediately when saturated")
- [x] 2.10 `tests/test_admision.py`: saturation reads no body and writes no temp file — pre-acquired slot + malformed multipart body; assert 503 not 422 (proves the parser never ran) and zero `pet-*` temp directories created
- [x] 2.11 `tests/test_admision.py`: auth outranks admission — slot pre-acquired **and** bad/missing token → 401, not 503, and the slot is not consumed by that request (`bounded-execution` spec, Requirement "Admission is checked after the token check")
- [x] 2.12 `tests/test_admision.py`: `/salud` unaffected while saturated — slot pre-acquired → `GET /salud` still 200 (V3) (`bounded-execution` spec, Requirement "/salud is never subject to admission")
- [x] 2.13 Verify: `uv run ruff check . && uv run ruff format --check . && uv run mypy app tests && uv run pytest`

## Phase 3: S3 — Process plumbing (PR 3)

- [ ] 3.1 `app/core/ejecucion.py` (process half): pipe message dataclasses `SalidaDelHijo`, `ErrorDelHijo`, `ExcepcionDelHijo` (frozen, slots) and the `MensajeDelHijo` union
- [ ] 3.2 `app/core/ejecucion.py`: `class Desenlace(StrEnum)` with `NORMAL`/`MATADO`/`ANOMALO`; pure `clasificar_desenlace(*, exitcode, matado, hubo_mensaje) -> Desenlace` — `matado` wins over the exitcode number (design §6, verified fact: Windows normalizes `TerminateProcess` back to `-SIGTERM`, so raw exitcode cannot distinguish our `kill()` from an external SIGTERM)
- [ ] 3.3 `app/core/ejecucion.py`: exception hierarchy `FalloDeEjecucion` (base, never `TipoError`), `EjecucionExpirada`, `HijoMuerto(exitcode: int | None)`, `FalloDelModulo(clase: str, mensaje: str, traza: str)`
- [ ] 3.4 `app/core/ejecucion.py`: `ejecutar_aislado(objetivo, argumentos, *, timeout) -> MensajeDelHijo` — `Pipe(duplex=False)`; `Process(target=objetivo, args=(hijo, *argumentos), daemon=True).start()`; parent closes its child-end handle immediately (load-bearing: lets a dead child EOF instead of burning the timeout); `poll(timeout)` then `recv()` or treat `EOFError`/timeout as no message; close the pipe; only then `join(restante)`; `kill()` if still alive; confirm `is_alive()` is False; narrow the received object via `isinstance` against the three dataclasses only — anything else is a protocol violation
- [ ] 3.5 `tests/ayudas/hijos.py` (new): deliberate child targets — normal completion, hangs past timeout, `os._exit(N)` nonzero, silent exit with no message, raises a typed `ErrorTipificado`, raises an untyped exception
- [ ] 3.6 `tests/test_ejecucion.py` (new, plumbing half): unit — `clasificar_desenlace` over the full §6 table including POSIX rows exercised as pure data on Windows CI
- [ ] 3.7 `tests/test_ejecucion.py`: process — success path returns `SalidaDelHijo`; module exception surfaces `ExcepcionDelHijo` with a non-empty traceback; typed error crosses intact via `__reduce__` and equals the original `contexto`; timeout kills the child and `is_alive()` is False afterward (`bounded-execution` spec, "A hung child is really terminated on timeout"); `os._exit(3)` and silent-exit both classify as `ANOMALO` and the API worker keeps running (`bounded-execution` spec, "An anomalous child exitcode produces a distinguishable, contained failure")
- [ ] 3.8 `tests/test_ejecucion.py`: capacity not wedged after anomalous death — run an anomalous child, assert the caller-owned capacity is free and a second execution completes successfully
- [ ] 3.9 Verify: `uv run ruff check . && uv run ruff format --check . && uv run mypy app tests && uv run pytest`

## Phase 4: S4 — Module composition (PR 4)

- [ ] 4.1 `app/core/ejecucion.py`: module-level `_ejecutar_en_hijo(conexion: Connection, clave: str, entradas: list[ArchivoEntrada]) -> None` — picklable by qualified name; re-derives the processor via `REGISTRY[clave]`; a miss raises `ErrorClaveInexistente(causa="no_en_registry")`; sends exactly one `MensajeDelHijo`, closes, returns
- [ ] 4.2 `app/core/ejecucion.py`: `ejecutar_modulo(*, clave: str, entradas: list[ArchivoEntrada], timeout: timedelta) -> list[ArchivoSalida]` — thin composition calling `ejecutar_aislado(_ejecutar_en_hijo, (clave, entradas), timeout=timeout)`; re-raises the crossed `ErrorTipificado` as-is, else translates to `FalloDelModulo`/`EjecucionExpirada`/`HijoMuerto`
- [ ] 4.3 `app/core/interfaz.py`: rewrite the docstring caveat at lines 33-37 to state the resolved decision — the child re-imports the application module tree and looks up its `Procesador` instance from `REGISTRY` by `clave`; no serialized `Procesador` instance ever crosses the process boundary, only `clave` (`str`) and file paths (`procesador-interface` spec, MODIFIED Requirement "Procesador's docstring records the child-instantiation resolution")
- [ ] 4.4 `tests/test_ejecucion.py`: `ejecutar_modulo` against the empty production `REGISTRY` → `ErrorClaveInexistente(causa="no_en_registry")` re-raised in the parent (V9 — real spawn, real child import, real lookup, real `__reduce__` round-trip, zero production test hooks)
- [ ] 4.5 `tests/test_ejecucion.py`: assert `Procesador.__doc__` states the resolved child-instantiation decision (docstring content check, mirrors the `procesador-interface` scenario)
- [ ] 4.6 Verify: `uv run ruff check . && uv run ruff format --check . && uv run mypy app tests && uv run pytest`

## Out of scope (explicitly not this item)

The 9-step pipeline and its owning `try/finally` (#10); the final HTTP shape for timeout/child-death (#10); structured logging of saturation rejections (#14); calibrating `EJECUCIONES_MAX` or measuring `spawn` cost (#17); a real RAM ceiling on the child; portal-side 503 UX. `app/recepcion.py`, `app/core/temporales.py`, `app/registry.py`, `app/arranque.py`, and `tests/test_seguridad_token.py` stay untouched by every slice in this chain.
