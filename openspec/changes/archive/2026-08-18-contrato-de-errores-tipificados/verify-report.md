# Verification Report — contrato-de-errores-tipificados

**Change**: contrato-de-errores-tipificados (BACKLOG #3, authority ADR 0014)
**Mode**: Full artifact verification (proposal + spec + design + tasks + apply-progress all present)
**Strict TDD**: Disabled for this item (`openspec/config.yaml`, decided 2026-08-17). No structural/AST
tests, no chaos tests, no RED-before-GREEN evidence are expected or required. Behavioural tests, ruff,
mypy still apply and were judged.

## Task Completeness

All 26 tasks across 4 phases are marked `[x]` in `tasks.md`, matching apply-progress's own claim of
26/26. Spot-checked against the actual code/test/ADR content below — the claim holds; no task is
checked without matching evidence in the deliverables.

| Phase | Tasks | Status |
|---|---|---|
| 1 — `app/core/errores.py` | 1.1–1.8 | Complete, verified against source |
| 2 — test-only router + tests | 2.1–2.10 | Complete, verified against source |
| 3 — ADR 0018 | 3.1–3.6 | Complete, verified against source |
| 4 — static verification | 4.1–4.4 | Complete, re-run live below |

## Command Evidence (re-run live, this session)

```
$ python -m uv run pytest
74 passed, 1 warning in 3.80s
app\core\errores.py   82 stmts, 1 miss, 99% cover (line 169: `raise exc` re-raise branch, exercised
                       only when a non-ErrorTipificado exception reaches the handler — not hit by any
                       test-only-router case, which is expected since every case is a typed error)
```

```
$ python -m uv run ruff check .
All checks passed!
```

```
$ python -m uv run ruff format --check .
35 files already formatted
```

```
$ python -m uv run mypy app tests
Success: no issues found in 21 source files
```

```
$ python -m uv run pytest tests/test_seguridad_token.py -k test_rutas_de_produccion_no_cambian -v
1 passed, 24 deselected
```
The existing shipped-route-set test (item #2's `test_rutas_de_produccion_no_cambian`) still passes
unmodified after this change, per V7 in design.md and the "already-verified facts" note in the task
prompt — confirmed live, not just asserted.

```
$ git diff --stat HEAD -- app/ tests/ adrs/
(empty)
$ git status --porcelain
?? adrs/0018-codigo-de-estado-y-causa-de-clave-inexistente.md
?? app/core/errores.py
?? openspec/changes/contrato-de-errores-tipificados/
?? tests/test_errores_tipificados.py
```
No tracked file was modified. Only the three new deliverable files plus the openspec change folder
are untracked/new.

## Spec Compliance Matrix (7 requirements, spec.md)

| # | Requirement | Status | Evidence |
|---|---|---|---|
| 1 | Closed error vocabulary (exactly 5 `tipo` values) | PASS | `TipoError(StrEnum)` has exactly `formato/tamano/contenido/cantidad/clave_inexistente` (errores.py:27-34). `test_vocabulario_cerrado` asserts the closed set == ADR 0014's five values; passed live. |
| 2 | Error envelope shape (`{"tipo","contexto"}`, no `detail`) | PASS | `responder_error_tipificado` builds `JSONResponse({"tipo": ..., "contexto": ...})` (errores.py:170-173) — a plain dict literal, never `HTTPException`. `test_estado_y_cuerpo_documentados` does **full-body equality** (`respuesta.json() == cuerpo_esperado`) per case, which structurally proves no `detail` key and no extra key exists — passed live for all 7 parametrized cases. |
| 3 | `contexto` carries no composed prose | PASS (light check, as scoped) | Full-body equality (req. 2's test) pins every value verbatim, so no assembled string can be added without failing. `TestFormaDeContexto.test_campos_son_valores_crudos_o_enum_cerrado` additionally asserts every `contexto` value is `None`/`str`/`int`/`list` — a shape check, not a prose detector, exactly as the task scoped it ("do not build or demand a prose detector"). Judged genuine: it is the union of (a) exact literal comparison for known cases and (b) a runtime type-shape guard, not a rubber-stamp. |
| 4 | `contexto` shape + status fixed per type (table in spec.md) | PASS | `_ESTADO_HTTP` is the single status map (errores.py:156-164): 422×4, 500 for `clave_inexistente`. All 5 `contexto` `TypedDict`s match the spec table exactly, field-by-field (errores.py:37-79). `contenido`'s `columna` is populated only for `columna_faltante` and `None` for `cero_filas`, enforced by two classmethods (`columna_faltante`/`cero_filas`, errores.py:129-135) that make the invalid combination unconstructible. Both `clave_inexistente` `contexto` rows (`fila_ausente`/`fila_inactiva` vs `no_en_registry`/`no_en_bd`) share one `TypedDict`, distinguished only by `causa`'s `Literal` domain (errores.py:63-70) — matches spec exactly. All 7 cases asserted via full-body equality; `test_columna_refleja_el_motivo` and `test_causas_de_clave_inexistente_son_distinguibles` additionally target the two split-scenario requirements directly. All passed live. |
| 5 | Test-only router not wired into shipped `crear_app()` | PASS | `grep` for `errores`/`registrar_manejador_errores` in `app/main.py` returns no matches. `crear_app_de_prueba()` lives only in `tests/test_errores_tipificados.py` (never imported by `app/`). The pre-existing `test_rutas_de_produccion_no_cambian` (item #2, unmodified) still passes, which would fail immediately if anything had been wired in (V7's mechanism) — confirmed live above. |
| 6 | Shipped application route set is unchanged | PASS | Same evidence as #5: `test_rutas_de_produccion_no_cambian` passed live against the literal five-entry set, unmodified, plus `git diff --stat` on `app/` is empty. Per the task's already-verified-facts note, this pre-existing test satisfies the requirement; no new test was required or added, matching tasks.md 2.10's explicit decision not to duplicate it. |
| 7 | ADR 0018 present with required content | PASS | `adrs/0018-codigo-de-estado-y-causa-de-clave-inexistente.md` exists, MADR format (Estado/Contexto/Decisión/Alternativas consideradas/Consecuencias) matching sibling `adrs/0017` section-for-section, neutral professional Spanish throughout. Documents both decisions (500 for `clave_inexistente`; `contexto.causa` distinguishing desync without a sixth `tipo`), both rejected alternatives with reasons (503 reserved by item #8; sixth enum type would reopen ADR 0014's closed enum), and states explicitly in Consecuencias: "Este ADR cierra el requisito de distinguibilidad de TECH-DESIGN ... **no** H-05 en su totalidad" — the required honesty boundary is present verbatim in spirit and content. |

## Design Coherence

| Design decision | Followed in code? |
|---|---|
| One `ErrorTipificado` base + one subclass per type, `tipo: ClassVar`, single class-keyed handler (design §2) | Yes — errores.py:82-153, 176-177 |
| `TypedDict` per `contexto` shape, no `dict[str, object]` (design §3) | Yes |
| Single `_ESTADO_HTTP` mapping as the only status literal in the module (design §4) | Yes |
| Test-only router pattern mirroring item #2 (design §6) | Yes — loop-registered `/lanzar/{nombre}` routes, `_CASOS` mapping drives both routes and expectations |
| No new "route set unchanged" test; reuse V7's existing test (design §6, open question) | Yes — tasks.md 2.10 explicitly records this; confirmed no duplicate test was added |
| ADR 0018 outline (design §8) | Yes — content matches outline's Contexto/Decisión/Alternativas/Consecuencias points |

**Deviation**: each `ErrorTipificado` subclass redeclares `contexto` with its own narrower
`TypedDict` (e.g. `contexto: ContextoContenido` on `ErrorContenido`), not present in design's
illustrative snippet. Judged: this is a type-only narrowing, compatible with the base's union
annotation, with zero runtime effect — it exists solely because `mypy --strict` needs the narrower
type to check `contexto["campo"]` accesses in the test file without spurious `typeddict-item`
errors. The reasoning holds; this is a WARNING-tier documentation gap at most (design.md's
illustrative snippet doesn't show it), not a defect. Not blocking.

## Review Budget

**419 lines** across the three new files (`errores.py` 177 + `test_errores_tipificados.py` 185 +
`adrs/0018-*.md` 57), against design.md §12's own forecast of **295–355** and the 400-line PR review
budget. This is a real overshoot of both the forecast (+64 to +124 lines, ~18-35%) and the stated
400-line budget (+19 lines, ~5%). Recorded factually; not a blocker, and per the task's own framing
the user has not been asked to approve a split. The tasks.md-recorded risk assessment ("400-line
budget risk: Low", "Decision needed before apply: No") did not anticipate crossing the 400-line line
itself, only staying comfortably under the design's 295–355 estimate — that assumption did not hold
in the actual delivered size.

## Scope Check

- No items #4–#11 leaked in: `errores.py` imports only stdlib + `fastapi`/`starlette` (confirmed by
  reading the file; no import from `app/procesadores/`, no `Procesador` ABC, no SQL Server, no
  packaging/pipeline code).
- `app/core/configuracion.py`, `app/core/seguridad.py`, `app/salud.py`, `app/arranque.py`,
  `tests/test_seguridad_token.py`: confirmed unmodified via `git diff --stat HEAD -- app/ tests/
  adrs/` (empty) and `git status --porcelain` (only the 3 new files + openspec folder listed).
- `RequestValidationError` 422 collision and `registrar_manejador_401` wiring: correctly deferred to
  item #6, per user decision (Engram `sdd/contrato-de-errores-tipificados/decisions` #78) — both
  recorded as inherited obligations in ADR 0018's Consecuencias and in apply-progress. Not reported
  as a defect, per the task's explicit instruction.

## Issues

**CRITICAL**: None.

**WARNING**: None. (The 419-vs-295-355 line overshoot is recorded above under "Review Budget" as a
factual note per the task's instruction, not classified as a WARNING finding — it does not indicate
a spec/design/task compliance defect, only an estimation miss.)

**SUGGESTION**:
1. Design.md's illustrative subclass snippet (§2) does not show the per-subclass `contexto`
   redeclaration that the implementation needed for `mypy --strict`. A future design revision for a
   similar shape could note this up front to save the same mypy back-and-forth.

## Verdict

**PASS**

All 7 spec requirements are met with passing runtime evidence (74/74 tests green, including all
parametrized error-contract cases). All 26 tasks are complete and match the code state. Static
analysis (ruff check, ruff format --check, mypy --strict) is clean. No tracked file was modified;
scope stayed within item #3's boundary. The one deliberate design deviation (per-subclass `contexto`
narrowing) is type-only and does not affect runtime behavior or spec compliance. The 419-line actual
size against the 295–355 forecast is a real, factually-recorded overshoot but not a spec, design, or
task compliance defect, and does not block this verdict.
