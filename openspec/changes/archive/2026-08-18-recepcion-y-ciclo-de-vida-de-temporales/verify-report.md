# Verification Report: recepcion-y-ciclo-de-vida-de-temporales

**Change**: `recepcion-y-ciclo-de-vida-de-temporales` (BACKLOG #6, second half)
**Mode**: Full artifact verification (proposal, spec, design, tasks all present)
**Methodology**: Strict TDD disabled for this change (per design.md and openspec/config.yaml) —
absence of AST/structural/chaos tests is not treated as a defect.
**Delivery state**: Slice A committed on `main` (`30cda5d`, `8d5190d`, `5389993`); Slice B present
in the working tree, uncommitted. This is the deliberate two-slice delivery, not an inconsistency.

## Command Evidence (real output, this session)

```
$ python -m uv run pytest
134 passed, 1 warning in 5.50s
Coverage: app/core/temporales.py 95% (138, 146-147, 156 missing — unreachable branches:
  FileNotFoundError race guard, empty-root early return); app/recepcion.py 97% (101 missing —
  the unreachable NotImplementedError line, expected per design).

$ python -m uv run ruff check .
All checks passed!

$ python -m uv run ruff format --check .
50 files already formatted

$ python -m uv run mypy app tests
Success: no issues found in 34 source files
```

All four commands exit clean. No claimed-green-not-observed.

## Task Completion

All checkboxes A1.1–A5.3 (Slice A) and B1.1–B6.3 (Slice B) in `tasks.md` are ticked `[x]`. Source
inspection confirms the code matches what each task claims:

- Phase A (temporales.py, lifespan wiring, `test_temporales.py`, ADR 0020): all present, matches
  design §2/§3, previously verified and committed.
- Phase B (recepcion.py, dependency, wiring, route-pin update, `test_recepcion.py`): all present in
  the working tree, matches design §4/§5/§6.
- No unchecked task found. No CRITICAL on task completion.

## Spec Compliance Matrix

| Requirement | Scenario | Covering test | Result |
|---|---|---|---|
| Upload received and described verbatim | Upload written and described | `test_recepcion.py::TestRecepcion::test_archivo_escrito_dentro_del_directorio_y_borrado_despues` | PASS |
| On-disk name never derived from client input | Hostile name confined | `test_nombre_hostil_confinado_al_directorio_temporal` (5 parametrized hostile names: `../../x`, `..\x.xlsx`, `C:\Windows\x`, `/etc/passwd`, accented) | PASS |
| On-disk name never derived from client input | Duplicate names don't collide | `test_nombres_duplicados_producen_archivos_distintos` | PASS |
| Happy-path response leaves no temporary behind | Nothing left after completed response | `test_no_quedan_temporales_tras_una_respuesta_completa` | PASS |
| Disconnect bounded by sweeper, not eliminated | Disconnected request's temporary eventually removed | `test_temporales.py::TestBarrer::test_el_agujero_de_desconexion_es_real_y_el_barrendero_lo_cierra` | PASS |
| Every request resolves to missing-processor error | Any clave_procesador yields same typed error | `test_cualquier_clave_procesador_produce_el_mismo_error` (parametrized) | PASS |
| Route unreachable without valid token | 401 before body read | `test_401_llega_sin_leer_el_cuerpo` (infinite generator body, never consumed) | PASS |
| Token never appears in responses/logs | Token absent across outcomes | `test_token_no_aparece_en_respuestas_ni_en_logs` (valid, rejected, disconnected paths; `caplog` DEBUG + response bodies) | PASS |
| Shipped route set changes deliberately, pin updated | Pinned route-set test updated | `test_seguridad_token.py::test_rutas_de_produccion_no_cambian` — `esperado` literal grew `("/interno/procesadores/{clave_procesador}", ("POST",))`; `esperado_montajes` unchanged `{"/interno"}` | PASS |
| ADR 0020 documents H-02 resolution | ADR present with required content | Manual inspection of `adrs/0020-ciclo-de-vida-de-los-temporales.md` | PASS |

Every scenario has a covering test that passed at runtime. No UNTESTED, no FAILING.

## Focused Checks (per verification brief)

**1. Sweeper's deletion rule — two conditions, both required.**
Code in `barrer()` (`app/core/temporales.py:141-149`): a directory is deleted only when
`hijo not in _EN_VUELO` **and** `antiguedad > umbral_segundos`. Read as adversarially as requested:
`test_no_borra_un_directorio_en_vuelo_aunque_su_mtime_sea_viejo` registers a directory via
`reservar()` (so it is genuinely in `_EN_VUELO`), backdates its mtime by 3600s, then calls
`barrer(umbral=timedelta(0), ahora=momento_registro)` — `umbral=0` means the age gate alone would
delete *anything*, and the 3600s backdate makes the directory maximally "old". The directory
survives, because `hijo in _EN_VUELO` short-circuits the loop (`continue`) before the age check ever
runs. This is not a same-instant coincidence test — the mtime is deliberately made old specifically
to prove age alone does not override registry membership. This genuinely proves the conjunction, not
only the age half. `test_desaloja_una_entrada_vieja_de_en_vuelo_y_borra_su_directorio` and
`test_el_agujero_de_desconexion_es_real_y_el_barrendero_lo_cierra` cover the complementary case where
both conditions become true together (eviction, then deletion). Verdict: PASS, rule proven correctly,
not merely asserted.

**2. Sweeper never scans the system temp directory.**
`_raiz()` returns `Path(tempfile.gettempdir()) / "api-portal-temporales"`, a dedicated subdirectory;
`barrer()` only ever calls `raiz.iterdir()` on that root, never on `tempfile.gettempdir()` directly.
`test_no_toca_nada_fuera_de_su_raiz_dedicada` plants a sibling file directly in `gettempdir()`,
backdates it, sweeps, and asserts it survives — this is the correct proof, not merely an assertion
that no exception was raised. Verdict: PASS.

**3. Registry evicted on the same threshold.**
`barrer()` evicts `_EN_VUELO` entries with `ahora_monotono - momento > umbral_segundos` using the
*same* `umbral` parameter passed to the age-based deletion check — one threshold, no second knob, as
design §3.2 states and ADR 0020 records. `test_desaloja_una_entrada_vieja_de_en_vuelo_y_borra_su_directorio`
proves eviction + deletion in the same pass. Verdict: PASS.

**4. Shutdown cancellation is bounded.**
`ciclo_de_vida`'s `finally` calls `tarea.cancel()` then `await tarea` inside
`suppress(asyncio.CancelledError)` — no explicit timeout wraps this await. This matches design §3.5's
stated, not hidden, reasoning: the loop is almost always parked in `asyncio.sleep`, which cancels
instantly; only a cancellation landing mid-`run_in_threadpool` would extend shutdown, bounded by one
sweep pass. `test_el_apagado_cancela_la_tarea_y_no_cuelga` empirically confirms the task reaches
`done()` within the test's own timeout. This is an accepted, documented risk (no enforced ceiling on
the threadpool hop), not a defect — the design explicitly chose not to add a timeout here and states
why. Verdict: PASS as designed; not a gap this verification should raise as new.

**5. Disk names always server-generated.**
`app/recepcion.py`: `ruta_temporal = reserva.directorio / f"entrada_{indice}"` — never built from
`nombre_original`. `_formato()` uses `nombre_original.rpartition(".")`, never `Path(nombre_original)`.
Grep of `app/recepcion.py` and `app/core/temporales.py` confirms no `Path(...)` construction anywhere
takes client-controlled data as input. `nombre_original` is stored verbatim in `ArchivoEntrada`
(`nombre_original=nombre_original`, taken directly from `carga.filename or ""`). Five hostile-name
cases including `..`, absolute paths, a drive letter, and accents are all covered by
`test_nombre_hostil_confinado_al_directorio_temporal`; duplicate-name collision is covered separately.
Verdict: PASS.

**6. Happy-path cleanup and disconnect degradation both specified and proven; no absolute-zero claim.**
Spec's own requirement text states the disconnect case "MAY leave its temporary files behind" and
bounds recovery to "threshold plus one sweep interval" — an explicit, honest degradation, not a
zero-under-all-conditions claim. Both are tested (`test_no_quedan_temporales_tras_una_respuesta_completa`
for happy path; `test_el_agujero_de_desconexion_es_real_y_el_barrendero_lo_cierra` for disconnect).
Verdict: PASS.

**7. Route pin updated, not weakened.**
`tests/test_seguridad_token.py::test_rutas_de_produccion_no_cambian`'s `esperado` set now includes
`("/interno/procesadores/{clave_procesador}", ("POST",))` with an explanatory comment referencing the
`service-token-auth` pin-update convention; `esperado_montajes` is unchanged (`{"/interno"}`). The
pin grew, it was not loosened or removed. Verdict: PASS.

**8. ADR 0020 format and content.**
`adrs/0020-ciclo-de-vida-de-los-temporales.md` uses the exact MADR section set and header style as
`adrs/0011`–`0019` (`# ADR NNNN: Title`, `## Estado`, `## Contexto`, `## Decisión`,
`## Alternativas consideradas`, `## Consecuencias`), verified directly against `adrs/0019`. Prose is
neutral professional Spanish throughout. Contains: H-02 resolution and ADR 0006's own
"una vez enviada la respuesta HTTP" quote; V11's measurement carried verbatim (both `FileResponse`
and `StreamingResponse` skip cleanup on disconnect); the stated degradation ("cero... tras la
respuesta" → "cero dentro del umbral", 20 minutes worst case); and the required ADR 0012
single-worker dependency sentence in *Consecuencias* ("La solidez de `_EN_VUELO` depende de que
ADR 0012 fije un único worker de Uvicorn..."). Verdict: PASS.

**9. Dependency footprint.**
`git diff -- pyproject.toml` shows exactly one line added: `"python-multipart",`. `uv.lock` changed
correspondingly (generated, not hand-edited, per the task log). No other dependency was introduced.
Verdict: PASS.

## Assessment of the Known Finding: `del entradas` and contract-lookup ordering

`app/recepcion.py` builds `entradas: list[ArchivoEntrada]` from the uploads (writing each to disk
via `_copiar`), then does `del entradas` with a comment marking it as item #7's seam, before calling
`obtener_contrato(clave_procesador)`. The implementation follows design.md §4's illustrative snippet
exactly, in the same order (write, then look up the key).

**The orchestrator's proposed reordering — look up the key before touching disk — is technically
correct as an efficiency/abuse-surface observation, but it would conflict with this change's own
stated scope and demonstration goal, not merely cost something.**

- **Conflict with design intent.** Design §4 states explicitly what this route is built to prove
  today: *"la frontera de autenticación del montaje está delante de la ruta... la recepción
  multipart escribe y luego borra un temporal... y un error tipificado se resuelve en una respuesta
  HTTP real"* — three things, and the middle one (write-then-remove) is asserted as a deliberate,
  named goal of this scaffolding route, independent of whether a real processor exists. Moving the
  contract lookup before the write would mean that, for as long as the contract table stays empty
  (today, unconditionally — V8), **no upload would ever reach disk in production**, because every
  request would short-circuit at the lookup. The reception-and-cleanup demonstration this route
  exists to provide would become permanently unreachable through the shipped endpoint, contradicting
  the design's own "what this route can prove today" framing.
- **Conflict with spec testability, not spec text.** No requirement in `spec.md` literally mandates
  an order between "write the upload" and "resolve the contract key." But the *only* production
  path that currently exercises "Upload is received and described verbatim" and the hostile-name /
  duplicate-name requirements is the write-then-lookup order, precisely because the contract table
  is permanently empty in this change's scope. Reordering would force those requirements' behavioral
  proof to rely entirely on test-only routes or unit-level calls (as `test_temporales.py` already
  does for `ceder_limpieza()`), which is a real change to how this change proves itself, not a
  drop-in swap.
- **TECH-DESIGN.md's own future pipeline order actually agrees with the orchestrator.** Step 1
  ("Resuelve la fila `procesador`... por `clave_procesador`") precedes steps 2–6 (per-file
  validations) in the canonical 9-step pipeline item #10 will build. So reordering is not wrong for
  the *eventual* pipeline — it is premature for *this* scaffolding route, whose explicit, documented
  job (per design §4, not per the final pipeline) is to demonstrate reception mechanics end-to-end
  while no contract exists to check against yet.
- **Cost, if accepted.** Moving `obtener_contrato(clave_procesador)` before `with reservar()`,
  removing the `del entradas` line entirely, and rewriting `test_archivo_escrito_dentro_del_directorio_y_borrado_despues`
  plus the two "hostile name" / "duplicate name" integration tests, since they currently rely on the
  written-then-cleaned proof through the real HTTP path — those would need a different proof strategy
  (test-only route, or restructure once item #7 gives the table real rows). Estimated: touches
  `app/recepcion.py` (~10 lines), 3 tests in `tests/test_recepcion.py` (~40–60 lines), and the module
  docstring's "what this route proves" framing. Not large, but not free, and it changes what this
  route can honestly claim to demonstrate today.

**Recommendation**: this is a real, defensible tradeoff — a genuine future efficiency/abuse-surface
improvement versus this change's own stated demonstration goal — not a bug. It does not block
verification. Leaving it for item #7 (which gives the contract table real rows and a real reason to
validate before writing) avoids re-doing this exact restructuring twice. This is presented for the
user's decision, not treated as settled either way.

## Design Coherence

Implementation matches design.md decisions in §2 (Reserva ownership model), §3 (sweeper, both
conditions, dedicated root, two named constants, startup+periodic sweep), §4 (route shape, deviation
flagged), §5 (ArchivoEntrada field sourcing, `_formato` via `rpartition`), §6 (dependency/wiring/pin).
No undocumented deviation found. The parametrised-route deviation from ADR 0006 is flagged in both
the module docstring and ADR 0020, as design §4 requires.

## Issues

**CRITICAL**: None.

**WARNING**: None.

**SUGGESTION**:
1. Consider resolving `obtener_contrato(clave_procesador)` before writing uploads to disk, once item
   #7 gives the contract table real rows — this would align the route with TECH-DESIGN.md's final
   pipeline order (step 1 before steps 2–6) and close a minor abuse surface (forcing disk writes for
   a key that cannot exist). Deferred assessment above; not a defect in this change's scope.

## Verdict

**PASS**

All four command-line checks (pytest, ruff check, ruff format --check, mypy) are green with real
observed output. Every spec requirement has at least one passing covering test. All tasks are
checked and match the code. Design coherence holds. No CRITICAL or WARNING issues found.
