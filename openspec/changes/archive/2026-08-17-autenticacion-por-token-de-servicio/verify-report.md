```yaml
schema: gentle-ai.verify-result/v1
evidence_revision: sha256:b16bc997bf7cb8dae0e6f4de1b7db7a3ee5f2ca75d16f3f5a7e1e2b3c4d5e6f7
verdict: pass
blockers: 0
critical_findings: 0
requirements: 8/8
scenarios: 9/9
test_command: python -m uv run pytest -q
test_exit_code: 0
build_command: python -m uv run mypy app tests
build_exit_code: 0
```

## Verification Report (PASS 2 -- supersedes PASS 1)

Change: autenticacion-por-token-de-servicio (BACKLOG item #2)
Mode: Strict TDD
Supersedes: PASS 1 verdict `pass_with_warnings` (1 WARNING, closed by targeted follow-up).

### What changed since pass 1

Pass 1's sole WARNING: the "token never appears in captured output" requirement was proven
structurally for `app/core/seguridad.py` but lacked a dedicated positive stdout/stderr
subprocess-capture test, unlike item #1's pattern for `configuracion.py`.

A targeted follow-up added `test_sentinela_ausente_de_salida_combinada` to
`tests/test_seguridad_token.py`. It spawns a fresh interpreter via `tests/ayudas/subproceso.py`
(`sys.executable`, argv list, `shell=False`), runs a real request/response cycle through
`exigir_token` end to end (one accepted, one rejected), asserts `codigo_salida == 0` first, and
then asserts the raw sentinel string is absent from the combined stdout+stderr. RED was
established by real perturbation before this pass: a deliberate `print` of the unwrapped secret
inside `_token_esperado()` made the test fail with the sentinel appearing twice in captured
output; the perturbation was reverted before this verification.

### Completeness
| Metric | Value |
|--------|-------|
| Tasks total | 17 |
| Tasks complete | 17 |
| Tasks incomplete | 0 |

### Build & Tests Execution (real output, this pass)

```text
$ python -m uv run pytest -q
.......................................................                  [100%]
55 passed, 1 warning in 3.80s
```

Coverage: 99% (89 stmts, 1 miss -- app/arranque.py line 40, pre-existing, out of scope)

```text
$ python -m uv run ruff check .
All checks passed!

$ python -m uv run ruff format --check .
32 files already formatted

$ python -m uv run mypy app tests
Success: no issues found in 19 source files
```

55 of 55 tests pass (was 54 in pass 1; +1 for the new capture test). All four gates clean.

### Regression check across the full spec (not just the closed warning)

- Rejection matrix byte-identity: `test_todas_las_respuestas_de_rechazo_son_byte_identicas`
  collects `(status_code, content, tuple(sorted(headers.items())))` for all 8 malformed variants
  into a `set` and asserts `len(huellas) == 1` -- genuine single-fingerprint collapse, re-confirmed
  unchanged.
- AST proofs inspect what they claim: `test_get_secret_value_un_solo_sitio` walks all of
  `app/**/*.py`, and `_es_argumento_de_logging_o_formato` explicitly walks `JoinedStr` ancestors
  (f-strings) in addition to logging/format/print call arguments -- re-read in full, unchanged
  from pass 1.
- Access-log test: `test_access_log_no_contiene_valores_de_cabecera` attaches a plain
  `logging.Handler` directly to `uvicorn.access` (not `caplog`, which would pass vacuously under
  `propagate: False`), drives a real background `uvicorn.Server` thread and a real `httpx`
  request, and asserts `captura.lineas` is non-empty before checking content -- re-confirmed.
- Route-set pin: `_rutas_efectivas` recursively unwraps `_IncludedRouter.original_router.routes`
  before flattening, matching starlette 1.6.0's wrapper reality -- re-confirmed, no vacuous pass.
- No wall-clock timing assertion anywhere in `app/core/seguridad.py`,
  `tests/test_seguridad_token.py`, `tests/test_seguridad_estructural.py`, or
  `tests/test_seguridad_access_log.py` -- confirmed absent by full re-read.
- Encoding split: `_es_valida` encodes the presented credential with `.encode("latin-1")` and the
  configured token with `.encode("utf-8")` inside `_token_esperado()`; `test_no_ascii_es_aceptado`
  exercises this end to end via `TestClient` with a non-ASCII configured token -- confirmed.
- `get_secret_value()`: exactly one call site repository-wide
  (`app/core/seguridad.py:63`), confirmed both by `grep -rn` across `app/` and `tests/` and by the
  AST test `test_get_secret_value_un_solo_sitio`.
- `app/core/configuracion.py`: `git diff --stat HEAD -- app/ adrs/` is empty; the file is not in
  the untracked/modified set at all -- unmodified.
- Nothing wired into shipped `crear_app()`: `app/main.py` contains only a seam comment
  (`# costura #2: routers de procesadores con dependencies=[Depends(exigir_token)]`), no import or
  call of `exigir_token`; `test_rutas_de_produccion_no_cambian` confirms the flattened production
  route set is exactly the 5 pre-existing routes.

### Spec Compliance Matrix

| Requirement | Scenario | Test | Result |
|-------------|----------|------|--------|
| Valid credential is accepted | Valid token accepted | test_token_valido_alcanza_el_endpoint | COMPLIANT |
| Every rejection path returns a byte-identical response | Identical response across all malformed variants | test_todas_las_respuestas_de_rechazo_son_byte_identicas (8-variant set collapse) + test_respuestas_de_rechazo_son_identicas | COMPLIANT |
| Comparison does not leak which credential is wrong | Structural proof of constant-time comparison | test_seguridad_estructural.py (4 AST tests) | COMPLIANT |
| Comparison does not leak which credential is wrong | A non-ASCII token is accepted | test_no_ascii_es_aceptado | COMPLIANT |
| Token never appears in captured output | Token absent from all captured output | test_sentinela_ausente_de_salida_combinada (NEW, fresh-interpreter subprocess capture) + test_access_log_no_contiene_valores_de_cabecera | COMPLIANT |
| get_secret_value has exactly one call site | Single, non-logging call site verified | test_get_secret_value_un_solo_sitio | COMPLIANT |
| No application instance is constructed with debug mode enabled | Debug traceback rendering disabled | test_sin_debug_true | COMPLIANT |
| Access log does not surface header values | Header-bearing request produces no header value in the access log | test_access_log_no_contiene_valores_de_cabecera | COMPLIANT |
| Shipped application route set is unchanged | Shipped route set unchanged | test_rutas_de_produccion_no_cambian | COMPLIANT |

Compliance summary: 9/9 scenarios fully compliant by direct, passing runtime test. The pass-1
structural-only gap is closed.

### Issues Found

CRITICAL: None.
WARNING: None (the sole pass-1 WARNING is closed).
SUGGESTION: None.

### Verdict
PASS

55 of 55 tests green, 99 percent coverage, ruff and mypy clean, 8 of 8 requirements and 9 of 9
scenarios directly test-covered by a passing runtime test, no CRITICAL or WARNING findings, all 17
tasks complete, scope boundary intact (`git diff --stat HEAD -- app/ adrs/` empty -- no tracked
production file changed by the follow-up), ADR present and correctly formatted.
