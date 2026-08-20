```yaml
schema: gentle-ai.verify-result/v1
evidence_revision: sha256:8e1dcfc8042b73eaea8d5b5b2dd10aef078758154c4fcfa56f944adc9034b3df
verdict: pass
blockers: 0
critical_findings: 0
requirements: 6/6
scenarios: 8/8
test_command: uv run pytest -q
test_exit_code: 0
test_output_hash: sha256:669771aa5b51136742d7e2dcbd13b3b877e6ec5785d8644cba3d3a20b5f6b264
build_command: uv run mypy app tests
build_exit_code: 0
build_output_hash: sha256:889dc4713d3c435dcb8cd60312ac6fe989302a34ed326393190be18eaa28e310
```

## Verification Report

**Change**: empaquetado-de-la-salida (BACKLOG item #9)
**Version**: N/A (new domain, no prior output-packaging spec)
**Mode**: Standard (Strict TDD disabled since item #3 -- behavioural tests only)
**Scope**: complete change, both slices -- S1 (item-9/s1-vocabulario-de-errores, commit c571597)
and S2 (item-9/s2-empaquetado-de-la-salida, commits 60a6c50, d3270ae). Verified on branch
item-9/s2-empaquetado-de-la-salida, HEAD d3270ae, working tree clean, nothing pushed, no PR open.

### Completeness
| Metric | Value |
|--------|-------|
| Tasks total | 19 (5 in Phase 1, 14 in Phase 2) |
| Tasks complete | 19 |
| Tasks incomplete | 0 |

All 19 tasks were independently re-verified against the shipped code and tests, not just their
[x] marks -- see Correctness and Deviations sections below.

### Build and Tests Execution
**Build**: PASSED
```text
$ uv run ruff check .
All checks passed!

$ uv run ruff format --check .
62 files already formatted

$ uv run mypy app tests
Success: no issues found in 43 source files
```

**Tests**: 268 passed / 0 failed / 0 skipped
```text
$ uv run pytest -q
........................................................................ [ 26%]
........................................................................ [ 53%]
........................................................................ [ 80%]
....................................................                     [100%]
268 passed, 1 warning in 11.84s
```
(The one warning is the pre-existing, unrelated httpx/starlette StarletteDeprecationWarning.)

**Coverage**: 95% total (621 stmts, 31 missing) / no fixed threshold declared in this project ->
Not available as a gate, reported informationally. app/core/empaquetado.py: 100% (43/43 stmts).
app/core/errores.py: 99% (1 line missing, unrelated to this change -- line 266,
"if not isinstance(exc, ErrorTipificado): raise exc", a defensive branch pre-dating item #9).

This independently reproduces the orchestrator measurement exactly: 268 passed, 95% total
coverage, mypy clean on 43 source files. No discrepancy to report.

### Spec Compliance Matrix
| Requirement | Scenario | Test | Result |
|-------------|----------|------|--------|
| A single output is returned verbatim | Single output passes through unchanged | tests/test_empaquetado.py::TestPassthrough::test_una_sola_salida_se_devuelve_verbatim | COMPLIANT |
| Two or more outputs are compressed into a single flat ZIP | Multiple outputs produce one complete flat ZIP | tests/test_empaquetado.py::TestMultiplesSalidas::test_dos_o_mas_producen_un_unico_zip_plano | COMPLIANT |
| Zero outputs raise a typed content error before any file is written | Empty input raises before touching disk | tests/test_empaquetado.py::TestCeroSalidas::test_levanta_antes_de_tocar_disco | COMPLIANT |
| The ZIP is atomic (fully written and closed, or never returned) | A write failure never yields a partial ZIP | tests/test_empaquetado.py::TestFalloDeEscritura::test_un_fallo_a_mitad_de_escritura_no_deja_zip_parcial | COMPLIANT (verified to observe the real mechanism, see note below) |
| The ZIP is atomic (fully written and closed, or never returned) | A successful ZIP is closed before returning | tests/test_empaquetado.py::TestFalloDeEscritura::test_sin_fallo_el_zip_devuelto_ya_esta_cerrado | COMPLIANT |
| Arcnames are sanitized and duplicate names are rejected | A hostile nombre_propuesto is confined to a flat, safe arcname | tests/test_empaquetado.py::TestNombreAplanado::test_nombres_hostiles_terminan_planos_dentro_del_zip (plus unit test_nombres_hostiles_se_confinan_a_un_arcname_plano) | COMPLIANT |
| Arcnames are sanitized and duplicate names are rejected | Duplicate nombre_propuesto values raise instead of silently colliding | tests/test_empaquetado.py::TestDuplicados::test_nombre_propuesto_duplicado_levanta (plus test_dos_rutas_distintas_que_aplanan_al_mismo_nombre_levantan) | COMPLIANT |
| The ZIP is written inside the callers reserved directory | The ZIP lands inside the supplied directory | tests/test_empaquetado.py::TestMultiplesSalidas::test_el_zip_queda_dentro_del_directorio_provisto | COMPLIANT |

**Compliance summary**: 8/8 scenarios compliant, 6/6 requirements compliant.

**Zero-output error contract cross-checked against error-contract (item #3), not just this spec.**
ErrorContenido.sin_salidas() serializes through the shared handler (app/core/errores.py:264-270) and
is proven byte-exact by
tests/test_errores_tipificados.py::TestCasosDeError::test_estado_y_cuerpo_documentados (parametrized
over _CUERPOS_ESPERADOS["contenido_sin_salidas"]), which asserts the 422 body is exactly
{"tipo": "contenido", "contexto": {"motivo": "sin_salidas"}} -- COMPLIANT, matching this
specs line "translating to a 422 response" verbatim.

### Note on the V3 atomicity test (design.md warning about tests that pass for the wrong reason)

test_un_fallo_a_mitad_de_escritura_no_deja_zip_parcial was checked specifically for this failure
mode. It does observe the real mechanism, not an accident:

- It builds three inputs and monkeypatches zipfile.ZipFile.write to succeed on the 1st call and
  raise RuntimeError on the 2nd, restoring the original implementation via a captured reference for
  any call that is not the 2nd.
- It asserts llamadas["n"] == 2 after the exception -- this rules out the failure being injected
  before any write happened (which would make the "no partial ZIP" assertion trivially true because
  no ZIP write had started at all) and proves the failure was genuinely mid-stream, after open() had
  already created the file on disk and one member had already been written.
- The subsequent assertion "not (tmp_path / NOMBRE_DEL_ZIP).exists()" succeeds only because
  empaquetar's "except Exception: destino.unlink(missing_ok=True); raise" runs after the with
  block __exit__ has already closed the handle (design.md V3, zipfile/__init__.py:1918-1938).
  On Windows, unlink over a file with an open handle raises PermissionError; if V3 were false (the
  handle still open when except runs), this exact test would fail with PermissionError, not merely
  leave a stray file. The tests Windows execution here is itself evidence for V3: it ran clean.
- Confirmed: this is not a test that goes green for an unrelated reason. It structurally cannot pass
  on Windows unless the handle really is released before unlink runs.

### Correctness (Static Evidence)
| Requirement / constraint | Status | Notes |
|------------|--------|-------|
| empaquetado.py imports only stdlib plus errores.ErrorContenido plus tipos.ArchivoSalida | Implemented | Import block (lines 26-31) is exactly zipfile, pathlib.Path, typing.Final, app.core.errores.ErrorContenido, app.core.tipos.ArchivoSalida. Bodies checked too: no dynamic import, no "from app.core import temporales/ejecucion", no app.procesadores reference anywhere in the 128-line file (grep confirms) |
| No Starlette/FastAPI type in any signature or body | Implemented | Only type annotations in the file are list[ArchivoSalida], Path, str, set[str]; ErrorContenido is imported but is a plain Exception subclass at the point of use here (no Starlette leak through it into this modules own signatures) |
| SalidaMalFormada is a standalone Exception, not ErrorTipificado, never a 422 | Implemented | "class SalidaMalFormada(Exception):" (line 39) -- no inheritance from ErrorTipificado. _ESTADO_HTTP in errores.py maps only the five TipoError members; SalidaMalFormada cannot reach that mapping. No test or handler translates it to a 422; item #10 owns its HTTP translation per ADR 0023, and it currently falls through to FastAPIs generic 500 handler if uncaught |
| ErrorContenido.sin_salidas() serializes to exactly the documented body, 422 | Implemented | tests/test_errores_tipificados.py::TestCasosDeError::test_estado_y_cuerpo_documentados proves the exact body; _ESTADO_HTTP[TipoError.CONTENIDO] == 422 (errores.py:257) unchanged from item #3 |
| app/recepcion.py untouched, NotImplementedError seam intact | Implemented | git log --oneline -- app/recepcion.py shows no commit from this change touching it; lines 188-190 still read "raise NotImplementedError  # inalcanzable hoy: no hay contrato registrado", preceded by the item #9/#10 seam comment |
| TipoError stays at exactly 5 members | Implemented | class TipoError(StrEnum) unchanged: FORMATO, TAMANO, CONTENIDO, CANTIDAD, CLAVE_INEXISTENTE |
| No cast/type: ignore smuggled in for the V6 fix | Implemented | grep -n "type: ignore" and "cast(" across app/core/empaquetado.py, app/core/errores.py, tests/test_errores_tipificados.py returns nothing. The V6 fix is exactly the discriminant-literal guard "assert error.contexto[\"motivo\"] == \"cero_filas\"" at tests/test_errores_tipificados.py:260,312, matching the design stated fix precisely. See WARNING W1 for one unrelated type: ignore found elsewhere |

### Coherence (Design)
| Decision | Followed? | Notes |
|----------|-----------|-------|
| Section 2 -- ContextoSinSalidas sibling shape, sin_salidas() classmethod, enum stays at 5 | Yes | Matches design code block verbatim; Contexto union now has 7 members as Section 2 predicted |
| Section 3 -- public surface: directorio: Path, ArchivoSalida return, sync, keyword-only, one public function, SalidaMalFormada standalone | Yes | empaquetar(*, archivos: list[ArchivoSalida], directorio: Path) -> ArchivoSalida matches exactly; no Reserva import; no async |
| Section 4 -- write-mechanics ordering (0/1/N branches, _verificar pure, try/except/unlink/re-raise, return only after clean close) | Yes | empaquetado.py lines 107-128 match the design code block line-for-line in structure |
| Section 4, V3 -- ZipFile.close() releases handle even on write failure, Windows-safe unlink | Yes, and empirically confirmed | See dedicated note above; the test is structurally incapable of passing on Windows if V3 were false |
| Section 5 -- _nombre_plano is text manipulation, never Path construction; degenerate names raise, no fallback name invented | Yes | nombre_propuesto.replace("\\", "/").rpartition("/")[2]; degenerate check raises SalidaMalFormada with no substitute name |
| Section 5 -- passthrough asymmetry: single-output path checks no name | Yes | test_una_sola_salida_no_verifica_su_nombre directly exercises a hostile nombre_propuesto through the 1-output branch and asserts it returns verbatim, unchecked |
| Section 6 -- 0/1/N sequence diagram matches control flow | Yes | Matches empaquetar actual branch order (0 -> N == 1 -> N >= 2) |
| Section 7 -- file changes list (only empaquetado.py created, errores.py modified, recepcion.py and the five other core/ modules untouched) | Yes | Confirmed by git show --stat on both commits and by git log -- app/recepcion.py |
| Section 10 -- ADR 0023 written this phase, MADR format, Spanish, matches siblings | Yes | adrs/0023-cero-salidas-y-fallas-de-empaquetado.md present with Estado/Contexto/Decision/Alternativas/Consecuencias sections, records the "cero_filas is not reused" and "opposite sides of the typed vocabulary" decisions exactly as designed |
| Checkpoint V6 (design section 0, task 1.2) -- the false precedent, the actual root cause, the discriminant-literal fix | Yes | Confirmed by direct read of tests/test_errores_tipificados.py:255-320: the fix is exactly assert error.contexto["motivo"] == "cero_filas" before indexing "columna", applied at both the flagged existing test and the new TestDosFormasDeContenido test. No cast, no type: ignore anywhere in errores.py or its test file |

### Deviations Assessed

1. TestRutaTemporalInexistente (beyond tasks 2.6-2.13 literal wording). Design section 4 lists
   "every ruta_temporal exists" as one of _verificar four checks, and the spec Requirement "Arcnames
   are sanitized and duplicate names are rejected" scenario table does not name a dedicated scenario
   for this specific check, but the requirement text implicitly covers it as part of _verificar
   precondition set. This test closes a real gap in the coverage of a shipped, spec-relevant code
   branch (_verificar line 93-94) rather than adding untested surface. Verdict: strengthens the
   contract, no distortion -- it tests a check the spec/design already describe, just under a task
   heading that did not spell it out by name.

2. test_una_sola_salida_no_verifica_su_nombre (beyond literal wording). Design section 5 states
   outright "the single-output path returns its input untouched and checks no name" and calls this
   asymmetry "deliberate, stated so a reviewer does not read it as an oversight." The added test
   makes that explicit design claim a directly tested assertion rather than an implication inferred
   from the other tests passing. Verdict: strengthens the contract by converting a stated design
   invariant into a runtime proof; does not distort scope, since it tests documented behavior, not a
   new requirement.

Both deviations were disclosed in apply-progress, not discovered silently by this verification --
consistent with the apply phase own accounting.

### Issues Found

**CRITICAL**: None.

**WARNING**:
- W1 -- one "# type: ignore[arg-type]" exists in tests/test_empaquetado.py line 242, inside
  TestFalloDeEscritura monkeypatch of zipfile.ZipFile.write. This is unrelated to the V6 checkpoint
  (which concerns errores.py Contexto union, not this file) and is a routine suppression for calling
  an unbound-method-shaped replacement through monkeypatch.setattr against a stdlib method whose exact
  overload signature mypy cannot match structurally. It is confined to test code, does not touch
  empaquetado.py or errores.py, and does not affect any spec-covered behavior. Low severity, but the
  task instruction explicitly asked to confirm no cast/type: ignore was smuggled in anywhere, so it is
  recorded rather than silently passed over.
- W2 -- the "unbounded output growth" risk design section 11 declares open (no ceiling on aggregate
  ZIP size) has, correctly, no test -- this is not a gap in this verification sense (design and ADR
  0023 both state explicitly that fabricating a test for an unmitigated risk would misrepresent it as
  covered). Recorded here only so the open risk is visible in the verification trail, not as a defect.

**SUGGESTION**:
- The Contexto union now has 7 members and item #10 will need a third CONTENIDO-branch banner in the
  portal per design section 2 stated cost; this is scheduled, cross-repository work already flagged in
  design.md section 13 and ADR 0023 Consecuencias, not a gap in this item.
- openspec/config.yaml:8 still says "0011-0015 exist" for the ADR count, a pre-existing staleness
  flagged by items #7 and #8 as well; out of scope for this item but worth a follow-up cleanup pass.

### Verdict
PASS. All 19 tasks complete and verified against shipped code; all 6 requirements and 8 scenarios have
real, correctly-targeted behavioural coverage (268/268 tests passing, 100% coverage on
app/core/empaquetado.py); the design V3 atomicity claim is confirmed to be observed by the test, not
merely passed incidentally; the V6 typing fix matches the documented discriminant-literal approach
with no cast/type: ignore in the two files it concerns; both apply-phase deviations strengthen rather
than distort the spec; app/recepcion.py remains untouched. No CRITICAL findings. Two low-severity
WARNINGs recorded for completeness (one incidental type: ignore in test code, one correctly-untested
declared-open risk) and two SUGGESTIONs (both pre-existing, cross-item follow-ups) -- neither blocks
archive.

Recommended next step: sdd-archive.
