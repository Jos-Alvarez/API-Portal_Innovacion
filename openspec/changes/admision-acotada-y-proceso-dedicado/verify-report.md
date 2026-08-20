# Verification Report: admision-acotada-y-proceso-dedicado

Change: admision-acotada-y-proceso-dedicado (BACKLOG item #8)
Verdict: PASS WITH WARNINGS -- 0 CRITICAL (1 closed by reconciliation), 4 WARNING (1 closed, 1 new minor, 2 carried), 3 SUGGESTION
Run: 2026-08-19. Pass 1 verify on HEAD 2d2b142; re-verify pass 2 on HEAD a352f78 (branch item-8/s4-composicion-del-modulo), working tree clean both times.

## Re-verification note (pass 2, after the reconciliation commit a352f78)

Pass 1 of this report found CRITICAL finding C1: the configuration delta spec, as originally written,
said EJECUCIONES_MAX and TIMEOUT_EJECUCION were required and startup must fail when absent, while the
shipped code defaults both fields and the shipped tests proved startup succeeds when absent. The user
reviewed C1 and ruled in favor of the code: the two execution parameters keep their conservative
placeholder defaults; the delta spec text was stale, not the implementation. The spec text was
reconciled in a352f78 (docs only, zero code/test changes), and W3 (the ADR not recording the V8 open
risk that design.md promised to mirror into it) was closed in the same commit. This report is updated
in place to record both the original finding and its resolution, not to erase that something was wrong.

## Command Evidence (independently re-run against a352f78, not reused from the coordinator)

```
$ uv run ruff check .
All checks passed!

$ uv run ruff format --check .
59 files already formatted

$ uv run mypy app tests
Success: no issues found in 41 source files

$ uv run pytest --cov=app --cov-report=term-missing
241 passed, 1 warning (unrelated httpx/starlette deprecation, pre-existing) in 11.41s
TOTAL coverage: 95% (570 stmts, 31 missing)
app/core/ejecucion.py: 83% (138 stmts, 24 missing: 136-137, 239-242, 339-361, 382, 385)
```

Identical to pass 1 and to the coordinator re-run figures (241 passed, 95%, same missing-line ranges).
Expected: a352f78 touches only openspec/changes/.../specs/configuration/spec.md and
adrs/0022-admision-acotada-y-plomeria-del-proceso-dedicado.md -- markdown only, zero app/ or tests/
lines changed, confirmed by git show --stat a352f78.

## C1 -- re-checked against the reconciled spec text, CLOSED

Read specs/configuration/spec.md as it now stands, against app/core/configuracion.py and against
tests/test_configuracion_ejecucion.py, requirement by requirement.

EJECUCIONES_MAX -- spec now says: bounded positive integer with a conservative placeholder default;
startup fails only when PRESENT but non-numeric, zero, negative, or above the upper bound; absent
falls back to the default. This matches app/core/configuracion.py:83
(Annotated[int, Field(ge=1, le=32)] = 2) exactly.
- Absent falls back to default -- PASS, test_ausente_usa_el_placeholder_por_defecto asserts
  ejecuciones_max == 2 when unset.
- Present but invalid fails startup (zero, negative, non-numeric, above bound) -- PARTIALLY tested.
  Zero: test_cero_falla. Negative: test_negativo_falla. Above bound (33): test_por_encima_de_treinta_y_dos_falla.
  Non-numeric string: NO test exercises this exact example (e.g. EJECUCIONES_MAX="abc"). See new
  minor finding below -- this is a sub-case of one combined scenario, not a separate untested
  scenario, and pydantic built-in int coercion makes the outcome close to certain; still, the spec
  text now names it explicitly and no test proves it.
- Valid value starts successfully -- PASS, test_valor_positivo_arranca, test_limite_superior_treinta_y_dos_pasa.

TIMEOUT_EJECUCION -- spec now says: positive duration with a conservative placeholder default; must
accept both bare seconds and ISO 8601; validator enforces strictly-below-cutoff. This matches
app/core/configuracion.py:90-92 (BeforeValidator(_segundos_o_iso8601), Field(gt=timedelta()),
default timedelta(seconds=60)) and the model_validator at line 94.
- Absent falls back to default -- PASS, test_ausente_usa_el_placeholder_por_defecto (TimeoutEjecucion class).
- Present but non-positive fails startup -- PASS, test_cero_falla, test_negativo_falla.
- Both bare-seconds and ISO 8601 accepted, same resolved duration -- PASS, via two separate tests
  rather than one unified one: several tests set the env var to a bare-seconds string ("90") and get
  timedelta(seconds=90); test_formato_iso8601_tambien_se_acepta sets "PT90S" and gets the identical
  timedelta(seconds=90). Both forms are exercised against the same numeric example with the same
  resolved value -- this satisfies the scenario even though no single test parametrizes both forms
  together.
- At/above cutoff fails, names the relationship -- PASS, test_igual_al_corte_falla_y_nombra_la_relacion,
  test_por_encima_del_corte_falla.
- Strictly below cutoff starts -- PASS, test_estrictamente_debajo_del_corte_arranca.

Both fields documented as conservative placeholders -- PASS (source inspection, as the scenario itself
specifies): app/core/configuracion.py:77-92 comments say so explicitly; adrs/0022 and design.md
section 4 repeat it.

No scenario in the reconciled spec is now contradicted by a passing test. C1 is CLOSED. One new,
minor, low-severity gap surfaced during the re-check: see "New finding" below.

## W3 -- re-checked against adrs/0022, CLOSED

adrs/0022-admision-acotada-y-plomeria-del-proceso-dedicado.md Consecuencias section now includes an
open-risk paragraph: the child process inherits the parents whole os.environ, including
TOKEN_SERVICIO and any future database credentials item #5 might add; multiprocessing.Process
exposes no env parameter to narrow it; the impact is bounded today because the child runs
repository-owned code that never touches the database (ADR 0013); and it is recorded with no
mitigation and deliberately no test (a fabricated test would misrepresent an unmitigated risk as
covered). This mirrors design.md section 13 V8 threat-matrix row (environment inheritance,
TOKEN_SERVICIO, no env parameter, bounded impact via ADR 0013, deliberately no test) with no
contradiction. W3 is CLOSED.

## New finding (surfaced only by this re-check)

SUGGESTION (not CRITICAL, not WARNING) -- the reconciled EJECUCIONES_MAX scenario "A present but
invalid value fails startup" now explicitly names a non-numeric string as one of four disjunctive
examples, but no test sets EJECUCIONES_MAX to a non-numeric value (grepped tests/ for every
EJECUCIONES_MAX assignment: only "0", "-1", "1", "5", "32", "33" appear, never a non-numeric string).
This is a sub-case within one already-mostly-covered scenario, not a freestanding untested scenario,
and pydantic built-in int coercion makes the outcome close to certain -- low severity, but the spec
text is now more specific than the test suite. A single added test
(EJECUCIONES_MAX set to a non-numeric string -> ConfiguracionInvalida) would close it completely.

## Status of findings carried over from pass 1 (unchanged -- no code or test lines changed in a352f78)

WARNING W2 -- AdmisionDeBorde non-http scope passthrough (app/core/ejecucion.py:135-137) remains
untested and possibly dead code under current routing (router_interno carries only HTTP processor
routes; ASGI lifespan events never reach Mount middleware today). STILL OPEN, unaffected by a352f78.

WARNING (bounded-execution, "Two concurrent executions get two independent processes") -- still
untested at runtime; still structurally guaranteed by inspection (ejecutar_aislado instantiates
multiprocessing.Process fresh inline every call, no pool/cache anywhere in the file).
TestCapacidadNoQuedaAtascada still runs two executions sequentially, not concurrently. STILL OPEN.

WARNING (bounded-execution, "anomalous exitcode ... concurrent execution unaffected") -- still
approximated by a sequential second execution rather than a literal concurrent one. STILL OPEN, low
risk (no shared mutable state across calls except the semaphore, itself verified restored).

SUGGESTION S1 -- S3 shipped 7 spawning test functions vs design "<=6" guidance; already disclosed
accurately in tasks.md and test_ejecucion.py docstring. No action needed, unchanged.

SUGGESTION S2 -- wire COVERAGE_PROCESS_START, or document explicitly next to pyproject.toml:57-61
existing arranque.py note, so future readers do not misattribute _ejecutar_en_hijo coverage gap
(lines 339-361, unmeasurable regardless of REGISTRY content because it runs in a spawned child
interpreter under the current pytest-cov config) solely to REGISTRY emptiness. Unchanged, still
recommended.

## Task Completion, Scope Discipline, Locked Decisions, Deviations -- unchanged from pass 1, all still hold

35/35 tasks ticked and traced to real code/tests. Untouched-file list (app/recepcion.py,
app/core/temporales.py, app/registry.py, app/arranque.py, tests/test_seguridad_token.py) still
zero-diff against main. All four locked decisions (admission-after-token, TipoError stays at 5
members, child re-imports via REGISTRY, TIMEOUT_EJECUCION validator not a comment) still confirmed by
direct code and test inspection. All four recorded implementation deviations (S1 BeforeValidator with
no value leak, S2 _TimeoutSimulado stand-in, S3 seven spawning functions, S4 updated caveat-handoff
test) still check out. core/ still imports nothing from procesadores/.

## Verdict

PASS WITH WARNINGS. The one CRITICAL finding from pass 1 (spec/implementation divergence on the two
execution parameters required-vs-defaulted behavior) is CLOSED by the user explicit decision in favor
of the code and the subsequent spec reconciliation in a352f78 -- verified scenario by scenario against
the code and the test suite, with no remaining contradiction. W3 (ADR missing the V8 open risk) is
CLOSED, verified against the added Consecuencias paragraph. Remaining open items are all
WARNING/SUGGESTION severity: two genuinely untested-at-runtime concurrency scenarios (low risk, backed
by code-level structural guarantees), one untested and possibly-dead ASGI passthrough branch, one
newly-surfaced untested non-numeric-string sub-case (trivial, pydantic-guaranteed), and two
already-disclosed documentation/tooling suggestions. None of these block archive; none contradicts a
passing test the way C1 originally did.

Recommended next step: sdd-archive. If the team wants zero open WARNINGs before archiving, the cheapest
closures are: a direct-construction test for AdmisionDeBorde non-http branch, a concurrent-execution
test for "two independent processes", and a single EJECUCIONES_MAX non-numeric-string test -- all
small, optional, and not required by this verification to proceed.
