# Tasks: Contrato de errores tipificados

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 295–355 (design §12) |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single PR, 3 work-unit commits |
| Delivery strategy | ask-on-risk |
| Chain strategy | pending (not applicable — single PR) |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Low

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | `app/core/errores.py`: enum, TypedDicts, hierarchy, status map, handler | PR 1 (commit 1/3) | `uv run mypy app tests` | N/A — pure library, not wired anywhere yet | Delete file; nothing else imports it |
| 2 | `tests/test_errores_tipificados.py`: test-only router + behavioural tests | PR 1 (commit 2/3) | `uv run pytest tests/test_errores_tipificados.py` | `TestClient(crear_app_de_prueba())` per `/lanzar/{caso}` | Delete file; unit 1 unaffected |
| 3 | `adrs/0018-*.md` | PR 1 (commit 3/3) | N/A — docs | N/A — static Markdown | Delete file; no code depends on it |

Under 400-line budget, so one PR, split into 3 commits at real file boundaries (`work-unit-commits`).

## Phase 1: Foundation — error contract module

- [x] 1.1 `app/core/errores.py`: `TipoError(StrEnum)` with exactly the 5 ADR 0014 values.
- [x] 1.2 Add 5 `contexto` `TypedDict`s (`tamano` fixed verbatim by ADR 0014) + `CausaFila`/
      `CausaDesincronizacion` `Literal` aliases + `Contexto` union (design §3, §5).
- [x] 1.3 `ErrorTipificado(Exception)` base (`tipo: ClassVar[TipoError]`, `contexto: Contexto`) + one
      subclass per type (design §2).
- [x] 1.4 On `ErrorContenido`: classmethods `columna_faltante(*, archivo, columna)` and
      `cero_filas(*, archivo)`; `columna` always present, `None` only for `cero_filas` (design §3).
- [x] 1.5 `_ESTADO_HTTP: Final[Mapping[TipoError, int]]` — 422 for four types, 500 for
      `clave_inexistente` — the module's only status literal (design §4).
- [x] 1.6 `responder_error_tipificado(request, exc)`: re-raise unless `isinstance(exc, ErrorTipificado)`;
      else `JSONResponse({"tipo": exc.tipo.value, "contexto": exc.contexto}, status_code=...)`.
- [x] 1.7 `registrar_manejador_errores(app)`: `app.add_exception_handler(ErrorTipificado, ...)` — one
      registration covers all subclasses via MRO (design V2).
- [x] 1.8 Confirm the module imports only stdlib + `fastapi`/`starlette`, nothing from
      `app/procesadores/` (ADR 0011 invariant).

## Phase 2: Test-only router and behavioural tests

- [x] 2.1 `tests/test_errores_tipificados.py`: `_CASOS` mapping with all 7 named cases (design §6).
- [x] 2.2 `crear_app_de_prueba()`: fresh `FastAPI()`, `registrar_manejador_errores(app)`, one
      loop-registered `GET /lanzar/{nombre}` per case. Never wired into `app/main.py`.
- [x] 2.3 Test: each of 7 cases via `TestClient` — full-body equality on `{"tipo", "contexto"}` and
      documented status (spec.md table).
- [x] 2.4 Test: `contenido_columna` vs `contenido_cero_filas` — `contexto["columna"]` is the raw
      column name vs `None`.
- [x] 2.5 Test: `clave_fila` vs `clave_desync` — both 500, same `tipo`, distinct `contexto["causa"]`.
- [x] 2.6 Test: `{t.value for t in TipoError} == {5 ADR values}` — closed vocabulary.
- [x] 2.7 Test: `set(_ESTADO_HTTP) == set(TipoError)` and every type has a `_CASOS` entry.
- [x] 2.8 Test: `ErrorContenido.cero_filas(...)` direct construction — `columna is None`.
- [x] 2.9 Light shape check: each `contexto` field is `str`/`int`/`None`/closed `Literal` member —
      not a prose detector (2.3's full-body equality carries most of this weight).
- [x] 2.10 No new test: `test_rutas_de_produccion_no_cambian` in `tests/test_seguridad_token.py`
      already pins the shipped route set (V7). Do not duplicate; do not move `_rutas_efectivas`.

## Phase 3: Documentation — ADR 0018

- [x] 3.1 Create `adrs/0018-codigo-de-estado-y-causa-de-clave-inexistente.md`, MADR format matching
      0011–0017, neutral professional Spanish (Estado/Contexto/Decisión/Alternativas/Consecuencias).
- [x] 3.2 Contexto: ADR 0014 names no status for `clave_inexistente`; TECH-DESIGN needs the
      registry↔database desync distinguishable from "processor absent" without widening the enum.
- [x] 3.3 Decisión: (a) `clave_inexistente` → HTTP 500; (b) `contexto.causa` distinguishes causes,
      `tipo` unchanged.
- [x] 3.4 Alternativas: 503 rejected (item #8 reserves it for saturation); sixth enum type rejected
      (ADR 0014 closes the enum).
- [x] 3.5 Consecuencias: state explicitly this closes TECH-DESIGN's distinguishability requirement,
      **not** H-05 in full — ADR 0012/0013 risks stay unresolved.
- [x] 3.6 Record the two obligations inherited by item #6: `registrar_manejador_401(app)` still not
      wired into production; FastAPI's default `RequestValidationError` handler still leaks
      `{"detail": [...]}` with unfiltered `input` (design §9).

## Phase 4: Static verification

- [x] 4.1 `uv run pytest` — new + existing suites green.
- [x] 4.2 `uv run ruff check .`
- [x] 4.3 `uv run ruff format --check .`
- [x] 4.4 `uv run mypy app tests`
