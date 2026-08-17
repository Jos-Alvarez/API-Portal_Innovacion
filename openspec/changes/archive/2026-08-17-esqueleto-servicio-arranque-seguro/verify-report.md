```yaml
schema: gentle-ai.verify-result/v1
pass: 2
supersedes: pass 1 (verdict fail, 4 critical)
evidence_revision: sha256:1c7e730fdef6377bbe778f8e18233a35db260fd1b12cbb48ef01ac81b1f24018
verdict: pass
blockers: 0
critical_findings: 0
requirements: 9/9
scenarios: 10/10
test_command: uv run pytest
test_exit_code: 0
test_output_hash: sha256:1c7e730fdef6377bbe778f8e18233a35db260fd1b12cbb48ef01ac81b1f24018
build_command: uv run ruff check . && uv run ruff format --check . && uv run mypy app tests
build_exit_code: 0
build_output_hash: sha256:468a3c21a03f13bbec1c4956d7c953c2cad0e85ce99ad87ea884bb346fa2a0e4
```

## Verification Report — PASS 2 (supersedes pass 1)

**Change**: esqueleto-servicio-arranque-seguro
**Version**: N/A (single spec file, no prior version)
**Mode**: Strict TDD

Pass 1 returned `verdict: fail` with 4 CRITICAL findings: 4/10 spec scenarios
(Python-floor misattribution, health-response-scope documentation, no-multi-worker
statement, ADR 0016/H-08 tracker) had no runtime-executed covering test, even though
their content was independently confirmed correct by direct file inspection. A
targeted follow-up added `tests/test_documentacion_contrato.py` (7 tests) covering
exactly those four requirements. No production file was touched by that follow-up.
This pass re-verifies the full spec against the current state, not only the four
closed findings.

### Completeness
| Metric | Value |
|--------|-------|
| Tasks total | 28 (task checkboxes recounted directly from tasks.md) |
| Tasks complete | 28 |
| Tasks incomplete | 0 |

### Build and Tests Execution

```text
$ uv run ruff check .
All checks passed!

$ uv run ruff format --check .
27 files already formatted

$ uv run mypy app tests
Success: no issues found in 15 source files
```
(15 source files, up from 14 in pass 1 -- the new test file adds one. Build: PASSED, unchanged from pass 1.)

```text
$ uv run pytest -v
tests/test_arranque_spawn.py::test_importar_app_fija_spawn PASSED
tests/test_arranque_spawn.py::test_ninguna_creacion_previa_al_spawn PASSED
tests/test_arranque_spawn.py::test_reimportacion_es_idempotente PASSED
tests/test_configuracion_token.py::test_token_ausente_falla PASSED
tests/test_configuracion_token.py::test_token_vacio_falla PASSED
tests/test_configuracion_token.py::test_token_valido_se_acepta PASSED
tests/test_configuracion_token.py::test_configuracion_es_frozen PASSED
tests/test_configuracion_token.py::test_configuracion_prohibe_campos_extra PASSED
tests/test_configuracion_token.py::test_token_no_deja_rastro_en_caplog_al_fallar_por_otra_via PASSED
tests/test_configuracion_token.py::test_sentinela_ausente_de_salida_combinada PASSED
tests/test_convenciones_pereza.py::test_cache_configuracion_vacio_tras_importar_app_main PASSED
tests/test_documentacion_contrato.py::test_piso_python_311_declarado PASSED
tests/test_documentacion_contrato.py::test_piso_python_no_atribuye_a_adr_0012 PASSED
tests/test_documentacion_contrato.py::test_docstring_salud_documenta_las_cuatro_limitaciones PASSED
tests/test_documentacion_contrato.py::test_invocacion_canonica_no_usa_workers_multiples_ni_gunicorn PASSED
tests/test_documentacion_contrato.py::test_ausencia_de_scaffolding_de_despliegue_declarada_explicitamente PASSED
tests/test_documentacion_contrato.py::test_adr_0016_existe_con_formato_madr_de_sus_hermanas PASSED
tests/test_documentacion_contrato.py::test_h08_resuelto_en_revision_adversarial PASSED
tests/test_salud.py::test_salud_responde_200_sin_token PASSED
tests/test_salud.py::test_salud_no_intenta_ninguna_conexion_de_red PASSED
tests/test_salud.py::test_salud_modulo_no_importa_nada_de_app PASSED
tests/test_salud.py::test_app_falla_al_arrancar_sin_token PASSED
tests/test_salud.py::test_app_arranca_con_token PASSED
23 passed, 1 warning in 1.97s
```
(1 warning is httpx-via-starlette.testclient deprecation noise, unrelated to this change. Was 16 tests in pass 1, now 23 -- all 7 new tests are additive, none of the original 16 changed or regressed.)

Coverage: 98% (52 stmts, 1 miss) / threshold: 0% -> Above. Unchanged from pass 1 -- same
single miss at app/arranque.py line 40 (post-condition failure branch), same accepted
per orchestrator note. Confirms the follow-up touched only tests/, not app/.

### Spec Compliance Matrix (all 10 scenarios)
| Requirement | Scenario | Test | Result |
|-------------|----------|------|--------|
| Tooling runs pytest end-to-end | Fresh checkout test run | Direct command execution (this verification run) | COMPLIANT |
| Python version floor recorded independently of ADR 0012 | Floor recorded without misattribution | test_documentacion_contrato.py::test_piso_python_311_declarado, ::test_piso_python_no_atribuye_a_adr_0012 | COMPLIANT |
| Startup fails closed without a service token | Token unset or empty | test_configuracion_token.py::test_token_ausente_falla, ::test_token_vacio_falla | COMPLIANT |
| Token never appears in captured output | Startup-failure output inspected | test_configuracion_token.py::test_sentinela_ausente_de_salida_combinada, ::test_token_no_deja_rastro_en_caplog_al_fallar_por_otra_via | COMPLIANT |
| spawn start method set before any process or connection | Effective start method after any import path | test_arranque_spawn.py::test_importar_app_fija_spawn | COMPLIANT |
| spawn start method set before any process or connection | Nothing is created before the method is fixed | test_arranque_spawn.py::test_ninguna_creacion_previa_al_spawn | COMPLIANT |
| Health check is public and database-free | Succeeds without a token, dependencies unreachable | test_salud.py::test_salud_responde_200_sin_token, ::test_salud_no_intenta_ninguna_conexion_de_red | COMPLIANT |
| Health response does not claim full functionality | Divergence documented | test_documentacion_contrato.py::test_docstring_salud_documenta_las_cuatro_limitaciones | COMPLIANT |
| No multi-worker deployment regression | Single-worker default preserved | test_documentacion_contrato.py::test_invocacion_canonica_no_usa_workers_multiples_ni_gunicorn, ::test_ausencia_de_scaffolding_de_despliegue_declarada_explicitamente | COMPLIANT |
| ADR 0016 resolves H-08 | ADR and tracker updated together | test_documentacion_contrato.py::test_adr_0016_existe_con_formato_madr_de_sus_hermanas, ::test_h08_resuelto_en_revision_adversarial | COMPLIANT |

Compliance summary: 10/10 scenarios have a runtime-executed covering test that passed
on this verification run. All 4 previously-CRITICAL findings are closed.

### Judging the new tests

test_documentacion_contrato.py's 7 tests were read in full and judged for whether they
actually prove their Given/When/Then, not merely execute without error:

1. test_piso_python_311_declarado -- parses pyproject.toml with tomllib, asserts
   the literal requires-python == ">=3.11". Directly proves the "floor is >=3.11" half
   of the scenario. Sound.

2. test_piso_python_no_atribuye_a_adr_0012 -- scans the lowercased file text for a
   blacklist of 7 direct-attribution phrasings ("por adr 0012", "segun adr 0012",
   "consecuencia de adr 0012", etc.) and asserts none is present. This genuinely
   distinguishes "cites ADR 0012 as the reason" (forbidden) from "names ADR 0012 only to
   disclaim it" (the real comment's actual content, confirmed correct in pass 1's deep-dive
   item 6) -- it is not a trivial emptiness check. Weakness, self-documented in the test's
   own docstring: a blacklist cannot catch a novel attribution phrasing outside the 7
   listed patterns (e.g. a hypothetical future edit reading "this floor exists thanks to
   ADR 0012's spawn requirement" without matching one of the exact substrings). Judged: the
   scenario's Given/When/Then ("no comment attributes it to ADR 0012") is satisfied for the
   actual current file content, and the test would correctly fail if that exact content
   regressed to any of the 7 realistic phrasings a human would naturally write. This is
   proof against regression of the specific violation pattern the spec was written to
   prevent, not a tautology. Reported as WARNING, not a blocker -- see Issues.

3. test_docstring_salud_documenta_las_cuatro_limitaciones -- AST-parses
   app/salud.py, extracts obtener_salud's actual docstring (not the module docstring or
   a nearby comment), and asserts all four required terms (token, SQL Server, registry,
   catalogo, procesador) are present. Directly proves the "lists each of those four
   things" scenario requirement. Sound -- it reads the real source object, not a string copy.

4. test_invocacion_canonica_no_usa_workers_multiples_ni_gunicorn -- extracts only
   fenced code blocks containing both "uvicorn" and "run" from README.md (via regex),
   deliberately avoiding a naive full-text scan that would false-positive on the sentence
   that prohibits --workers/Gunicorn. Correctly scoped to "the invocation", matching the
   spec's "any run script ... this change adds" wording. Sound.

5. test_ausencia_de_scaffolding_de_despliegue_declarada_explicitamente -- checks no
   Dockerfile/*.service/run.sh/run.ps1 exist, AND that README.md contains the exact
   explicit-absence sentence plus the words "forbidden"/"gunicorn"/"--workers". Proves both
   halves of the requirement (no scaffolding exists, AND the absence is stated explicitly
   rather than left implicit). Sound.

6. test_adr_0016_existe_con_formato_madr_de_sus_hermanas -- globs for exactly one
   adrs/0016-*.md, regex-extracts "## " headings, asserts the MADR set (Estado, Contexto,
   Alternativas consideradas, Consecuencias, Decision/Decision) is present. Proves "ADR
   documents the resolution" in the structural sense the spec asks for (format matching
   siblings 0011-0015). Sound.

7. test_h08_resuelto_en_revision_adversarial -- finds every line containing "H-08" in
   REVISION-ADVERSARIAL.md and asserts none contains "Abierto", plus that "ADR 0016" is
   referenced somewhere in the file. Directly proves "H-08's row no longer reads 'Abierto'"
   and the ADR/tracker cross-reference. Sound -- checking every H-08-bearing line (not just
   the first) means a second stale row cannot slip through.

Verdict on the batch: 6/7 tests are unambiguous, directly-coupled proof of their scenario.
1/7 (test_piso_python_no_atribuye_a_adr_0012) is a documented-limitation blacklist scan --
genuinely satisfies the scenario's Given/When/Then for current and realistic-regression
content, but is not exhaustive against arbitrary novel phrasing. This is a legitimate
engineering tradeoff for a natural-language-content assertion, not a test-quality defect,
and does not warrant reopening the scenario as UNTESTED.

### Regression check across the rest of the spec (not just the 4 closed findings)

Re-walked all 9 requirements / 10 scenarios against current source, not only the ones the
follow-up touched:

- Tooling (pytest/ruff/mypy wiring): unchanged, still green (see Build and Tests above).
- Fail-closed token requirement + non-leak requirement: app/core/configuracion.py and
  tests/test_configuracion_token.py are byte-identical to pass 1 (git diff shows no
  change under app/; tests/test_configuracion_token.py not touched by the follow-up
  batch per apply-progress obs #61). All 6 tests still pass.
- spawn ordering guarantee: app/__init__.py, app/arranque.py unchanged;
  tests/test_arranque_spawn.py unchanged, all 3 tests still pass.
- Health check public/database-free: app/salud.py, app/main.py unchanged;
  tests/test_salud.py unchanged, all 5 tests still pass.
- Scope boundary (app/procesadores/, app/registry.py, app/core/db.py,
  app/core/seguridad.py, app/core/errores.py, app/core/interfaz.py must not exist):
  re-confirmed absent.
- Coverage identical to pass 1 (98%, same single miss) -- direct proof no production line
  was added, removed, or exercised differently by the follow-up.

No regression found anywhere outside the 4 closed findings.

### Correctness (Static Evidence)
| Requirement | Status | Notes |
|------------|--------|-------|
| Tooling scaffolding | Implemented | Unchanged from pass 1 |
| App factory + lifespan seams | Implemented | Unchanged from pass 1 |
| Design doc drift: cache_info().currentsize vs .currsize | Documentation drift, not a code defect | Unchanged from pass 1 -- design.md prose still stale; code and test are correct. Not re-litigated per orchestrator instruction. |
| Design doc drift: extra="forbid" env-var rejection | Documentation drift, not a code defect | Unchanged from pass 1 -- same reasoning. Not re-litigated per orchestrator instruction. |

### Coherence (Design)
Unchanged from pass 1 -- D1 through D7 and the startup-ordering rule were all confirmed
followed in pass 1 against files the follow-up did not touch (production code untouched).
No new design decisions were introduced by the follow-up (it is entirely additive test
content against an already-approved design's documentation-content requirements).

### TDD Compliance
| Check | Result | Details |
|-------|--------|---------|
| TDD Evidence reported | Acceptable | apply-progress (Engram obs #61) documents genuine RED-then-GREEN per assertion: each of the 7 assertions was proven to fail first by temporarily perturbing the real target file (wrong requires-python, stripped docstring, injected --workers 4, removed the deployment-scaffolding sentence, renamed an ADR heading, flipped H-08 back to "Abierto"), then restored byte-for-byte (diff-verified) before the real GREEN. Equivalent evidence to a literal RED/GREEN table, matching pass 1's WARNING resolution path. |
| All tasks have tests | Yes | Unchanged from pass 1, plus the 4 newly-closed scenarios |
| RED confirmed | Yes | Per-assertion RED confirmed per apply-progress obs #61, not merely per-file |
| GREEN confirmed | Yes | 23/23 tests pass on this verification run |
| Triangulation adequate | Yes | Each of the 4 closed requirements now has 1-2 tests directly coupled to its Given/When/Then |
| Safety Net for modified files | Yes | No production file modified by the follow-up; tests/test_documentacion_contrato.py is new, not a modification requiring a safety net |

### Test Layer Distribution
| Layer | Tests | Files | Tools |
|-------|-------|-------|-------|
| Unit | 8 | 2 (test_configuracion_token.py, test_arranque_spawn.py idempotence case) | pytest, monkeypatch |
| Integration | 8 | 3 (test_arranque_spawn.py subprocess cases, test_salud.py TestClient/AST) | pytest, TestClient, subprocess, sys.addaudithook |
| Static content | 7 | 1 (test_documentacion_contrato.py, new) | pytest, tomllib, ast, regex, direct file read |
| E2E | 0 committed / 1 manual (per apply-progress) | -- | Manually run uv run uvicorn app.main:app |
| Total | 23 | 6 test files | |

### Changed File Coverage
| File | Line % | Uncovered Lines | Rating |
|------|--------|-----------------|--------|
| app/__init__.py | 100% | -- | Excellent |
| app/arranque.py | 92% | L40 | Acceptable (accepted per orchestrator note -- unchanged from pass 1) |
| app/core/__init__.py | 100% | -- | Excellent |
| app/core/configuracion.py | 100% | -- | Excellent |
| app/main.py | 100% | -- | Excellent |
| app/salud.py | 100% | -- | Excellent |

Average changed file coverage: 98% (52 stmts, 1 miss) -- identical to pass 1.

### Assertion Quality
| File | Line | Assertion | Issue | Severity |
|------|------|-----------|-------|----------|
| tests/test_configuracion_token.py | 34, 46, 60, 82 | pytest.raises(Exception) | Broad exception type instead of specific ValidationError/ConfiguracionInvalida | SUGGESTION (carried from pass 1, unchanged) |
| tests/test_documentacion_contrato.py | 33-54 | test_piso_python_no_atribuye_a_adr_0012 | Blacklist scan of 7 attribution phrasings cannot catch a novel phrasing outside the list; limitation self-documented in the test's docstring | WARNING |

No tautologies, no ghost loops, no assertions that skip production code, no mock-heavy
tests in the new file (only tomllib/ast/regex/direct file reads against real files).
All 7 new assertions exercise real file content, not synthetic fixtures.

### Quality Metrics
Linter: No errors (uv run ruff check . -- All checks passed!)
Type Checker: No errors (uv run mypy app tests -- Success: no issues found in 15 source files)

### Issues Found

CRITICAL: None. All 4 CRITICAL findings from pass 1 are closed -- each of the 4
previously-untested scenarios now has a runtime-executed, passing, directly-coupled test.

WARNING:
1. tests/test_documentacion_contrato.py::test_piso_python_no_atribuye_a_adr_0012 proves
   the scenario via a blacklist of 7 direct-attribution phrasings rather than an exhaustive
   semantic check. It correctly fails for the realistic set of phrasings a human would write
   and correctly passes for the actual current disclaiming comment, but a sufficiently novel
   attribution phrasing outside the list would not be caught. The limitation is self-documented
   in the test's own docstring. Not a blocker -- the scenario's Given/When/Then is genuinely
   satisfied for the current content and its realistic regressions.

SUGGESTION:
1. (Carried from pass 1, unchanged) pyproject.toml's Python-floor comment names "ADR 0012"
   explicitly, even though only to disclaim it. A reviewer grepping "ADR 0012" would get a
   false-positive hit. Not a defect.
2. (Carried from pass 1, unchanged) tests/test_configuracion_token.py uses
   pytest.raises(Exception) in four places instead of the specific exception type.
   Functionally correct; narrowing would be slightly more precise.
3. (Carried from pass 1, unchanged) The spawn-ordering scenario's "any application module"
   wording is exercised via two import paths, not a third redundant one; not a practical gap
   given the language-level guarantee.

### Verdict
PASS

23/23 tests green, build/lint/type-check clean, scope boundary respected, both
non-negotiable startup guarantees (fail-closed token, forced spawn) proven by tests that
assert real ordering/non-leak relations, and all 10/10 spec scenarios now have a
runtime-executed covering test that passed on this run. Coverage is bit-for-bit identical
to pass 1 (98%, same single accepted miss), confirming the follow-up batch touched only
tests/ and closed the gap without altering production behavior. One WARNING carried
forward on a documented test-completeness limitation in the new blacklist-scan test; not a
blocker. Three SUGGESTIONs carried forward unchanged from pass 1, all non-blocking polish
items. Ready for sdd-archive.
