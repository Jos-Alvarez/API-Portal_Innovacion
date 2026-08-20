# Verification Report: admision-acotada-y-proceso-dedicado

Change: admision-acotada-y-proceso-dedicado (BACKLOG item #8)
Verdict: FAIL -- 1 CRITICAL (2 scenarios), 4 WARNING, 2 SUGGESTION
Run: 2026-08-19, on item-8/s4-composicion-del-modulo (HEAD 2d2b142), working tree clean.

## Command Evidence

```
$ uv run ruff check .
All checks passed!

$ uv run pytest --cov=app --cov-report=term-missing
241 passed, 1 warning (unrelated httpx/starlette deprecation, pre-existing) in 11.08s
TOTAL coverage: 95% (570 stmts, 31 missing)
app/core/ejecucion.py: 83% (138 stmts, 24 missing: 136-137, 239-242, 339-361, 382, 385)
```

```
$ grep -c "^\- \[x\]" tasks.md   -> 35
$ git diff main..item-8/s4-composicion-del-modulo --stat -- app/recepcion.py app/core/temporales.py \
      app/registry.py app/arranque.py tests/test_seguridad_token.py
```

## Judgement call

Partially -- the framing handed to this verifier is materially incomplete, though the underlying
conclusion (nothing here is a real gap to fix) still holds.

1. Lines 382, 385, and 239-242 -- genuinely REGISTRY-tied, and the stated reasoning is correct.
   These run in the parent process (ejecutar_modulo SalidaDelHijo/FalloDelModulo branches,
   and FalloDelModulo.__init__). With REGISTRY empty, the only reachable child outcome today is a
   KeyError -> ErrorClaveInexistente -> ErrorDelHijo, so the SalidaDelHijo and
   ExcepcionDelHijo -> FalloDelModulo branches are truly unreachable end-to-end until items #12/#16
   populate the registry. Confirmed by direct read of app/core/ejecucion.py:380-385.

2. Lines 339-361 -- the entire executable body of _ejecutar_en_hijo -- are NOT explained by
   REGISTRY emptiness alone. They are unmeasurable by design of the test harness, independent of
   REGISTRY content. _ejecutar_en_hijo is the target of a multiprocessing.Process under
   spawn: it executes in a separate interpreter, and pyproject.toml:57-61 already documents,
   for exactly this reason, that the code running inside fresh-interpreter subprocess tests is NOT
   measured by pytest-cov unless COVERAGE_PROCESS_START is wired -- no such wiring exists (confirmed:
   no .coveragerc, no sitecustomize.py, no concurrency = multiprocessing anywhere in pyproject.toml).

### Domain: bounded-execution (8 requirements, 13 scenarios)

| # | Requirement / Scenario | Status | Evidence |
|---|---|---|---|
| 1a | Saturated admission rejects before body/disk touched | PASS | app/core/ejecucion.py:88-105 (admitir raises before any await self.app); tests/test_admision.py::test_saturacion_no_lee_cuerpo_ni_escribe_temporal -- malformed multipart returns 503 not 422 (proves parser never ran) and asserts zero pet-* dirs |
| 4a | Two concurrent executions get two independent processes | WARNING (untested at runtime) | No test starts two children concurrently and asserts distinct Process identity. Structurally guaranteed by inspection: ejecutar_aislado (app/core/ejecucion.py:248-310) instantiates multiprocessing.Process(...) fresh inline on every call -- no pool, no cache, no module-level state holding a Process anywhere in the file (confirmed by full-file read). TestCapacidadNoQuedaAtascada runs two executions sequentially, not concurrently, and does not assert object identity. See W4. |
| 4b | Only paths/scalars cross the process boundary | PASS (indirect) | mypy --strict enforces args=(hijo, *argumentos) types; every real-spawn test passes only clave: str + entradas: list[ArchivoEntrada]. ArchivoEntrada/ArchivoSalida are path/scalar dataclasses (app/core/tipos.py) -- no raw bytes field exists |

### Domain: configuration (3 requirements, 6 scenarios)

Finding C1 (CRITICAL). The configuration spec Requirements 1 and 2, as written and saved to
openspec/changes/admision-acotada-y-proceso-dedicado/specs/configuration/spec.md, say both fields
are required and that startup MUST fail when either is absent. The shipped implementation
(app/core/configuracion.py:83,90-92) gives both fields defaults (ejecuciones_max = 2,
timeout_ejecucion = timedelta(seconds=60)), and the shipped test suite proves the opposite of the
spec scenario: TestEjecucionesMax::test_ausente_usa_el_placeholder_por_defecto and
TestTimeoutEjecucion::test_ausente_usa_el_placeholder_por_defecto both assert that startup
succeeds with the documented default when the env var is unset.

design.md section 15 even flags it as an open item: proposal correction -- the two config fields
ship defaulted, not required (section 4). Flagged for spec reconciliation; the proposal
both-required line should be updated. That reconciliation targeted the proposal and was never
propagated to the delta spec that sdd-spec actually wrote.

### Domain: procesador-interface (1 requirement, 1 scenario)

Procesador.__doc__ states the resolved child-instantiation decision -- PASS.
app/core/interfaz.py:33-40 (rewritten RESUELTO block, states REGISTRY/clave, no serialized instance
crosses); tests/test_ejecucion.py::TestProcesadorDocstringResuelveElCaveat and the updated
tests/test_interfaz_procesador.py::test_docstring_registra_la_resolucion_del_item_8.

## Additional findings

W2 -- AdmisionDeBorde non-http scope passthrough (app/core/ejecucion.py:135-137) is untested and
possibly dead code under current routing (no websocket routes exist on router_interno; lifespan
events never reach Mount middleware). Low risk, undisclosed in apply-progress.

W3 -- adrs/0022 does not record the V8 open risk (child inherits TOKEN_SERVICIO via os.environ)
that design.md section 13 explicitly promised to mirror into the ADR Consecuencias. It IS recorded
in design.md itself, so nothing is silently hidden, but the ADR-specific commitment was not honored.

S1 (SUGGESTION) -- S3 shipped 7 spawning test functions vs design "<=6" guidance, already disclosed
accurately in tasks.md and test_ejecucion.py; no action needed.

S2 (SUGGESTION) -- wire COVERAGE_PROCESS_START, or document next to pyproject.toml:57-61, so future
readers do not misattribute the _ejecutar_en_hijo coverage gap solely to REGISTRY emptiness.

## Scope Discipline -- confirmed clean

No pipeline, no HTTP shape for timeout/child-death, no saturation logging, no EJECUCIONES_MAX
calibration, no RAM ceiling on the child: confirmed by full-file read of app/core/ejecucion.py.
app/recepcion.py NotImplementedError seam (line 190) untouched. git diff main..HEAD --stat for
app/recepcion.py, app/core/temporales.py, app/registry.py, app/arranque.py,
tests/test_seguridad_token.py is empty across all four slices. core/ imports no procesadores/
symbol anywhere; ADR 0011 invariant holds by construction.

## Locked decisions -- all confirmed

1. Admission after token check -- app/main.py:50 list order (V1); test_token_invalido_da_401...
2. Only the 503 ships; TipoError still exactly 5 members -- test_vocabulario_cerrado.
3. Child re-imports and looks up REGISTRY by clave -- TestEjecutarModuloRegistryMiss.
4. TIMEOUT_EJECUCION below 2 minutes enforced by a validator -- _timeout_por_debajo_del_corte.

## Deviations recorded during implementation -- all checked, all handled correctly

S1 numeric-seconds BeforeValidator, no value leak confirmed. S2 _TimeoutSimulado stand-in,
correctly scoped. S3 seven spawning test functions vs design guidance, disclosed. S4 old
open-caveat docstring pin updated to the resolved wording, confirmed correct.

## Verdict

FAIL -- not because of a code defect, but because the configuration domain spec on disk directly
contradicts the shipped, tested, design-justified implementation on two Requirements
(EJECUCIONES_MAX and TIMEOUT_EJECUCION required, fails when absent vs the actual defaulted, bounded,
validated behavior). This is design.md own flagged, unresolved open item that was never carried
through to the spec file. Everything else -- build, mypy, tests, task completion, scope discipline,
the four locked decisions, and the subprocess-coverage judgement call -- holds up under direct,
independent inspection.

Recommended path: reconcile specs/configuration/spec.md two Requirements (and their four
missing/absent scenarios) to state the defaulted/bounded/validated behavior that design.md
section 4 justifies and the implementation/tests already prove -- this is a spec-text edit, not new
application code. Once reconciled, re-run this verification; nothing else found here should block
sdd-archive.
