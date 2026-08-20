# Design: Output Packaging

- **Change**: `empaquetado-de-la-salida` (BACKLOG item #9)
- **Inputs**: `proposal.md` (**authoritative for Decisiones 1, 2, 3, 5 and 6**; Decisión 4 is closed
  here, as that proposal instructed), `exploration.md`, `adrs/0011` (names the target module),
  `adrs/0014` (closed enum, `contexto` contract), `adrs/0018` (correctable vs. non-correctable),
  `adrs/0020` (temp ownership, server-generated names), `adrs/0021` (**the governing precedent** —
  sibling context shape for a failure with no culprit file), `adrs/0022` (non-`TipoError` failures
  are item #10's translation), `TECH-DESIGN.md:102, 210-214`, `PRD.md:286-290`, plus the shipped code
  read for this phase: `app/core/{tipos,errores,temporales,ejecucion,validaciones}.py`,
  `app/recepcion.py`, `app/registry.py`, `tests/test_errores_tipificados.py`, `pyproject.toml`,
  and `C:\Python312\Lib\zipfile\__init__.py`.
- **Authority**: ADRs outrank every other document. Inherited `L:\App_Portal\adrs\0001`–`0010`
  outrank local `adrs\0011`–`0022`. **This change authors `adrs/0023`** — see §10 for the numbering
  evidence and for why an ADR is warranted rather than an amendment. The ADR is written in Spanish,
  matching every sibling; this design is written in English, matching every sibling `design.md`.
- **Methodology**: Strict TDD **disabled** since item #3. Behavioural tests only — no AST/structural
  tests, no chaos tests, no perturb-and-restore. `ruff` and `mypy --strict` still run. Every command
  goes through `uv run`.
- **Review budget**: 600, and for once there is no conflict — the orchestrator passed 600 and
  `openspec/config.yaml:42` says 600. §9 forecasts **435–575**, so one PR.
- **Length**: this document exceeds the generic 800-word design budget on purpose. The archived
  sibling it is modelled on runs far longer, and the phase brief asked for that depth.

## 0. Verified facts this design rests on

Item #6 opened its design with this table because "four false library claims have already entered
this project's artifacts by recall", and item #8's V4/V7 each corrected its own proposal. The
discipline earns its keep again: **V2 corrects a phrase in this change's own proposal, V4 and V5
each pre-empt a plausible reviewer objection, and V6 removes what would otherwise be a real
`mypy --strict` risk in `errores.py`.**

| # | Claim | Evidence |
|---|---|---|
| V1 | **`zipfile`'s own `arcname` normalization is partial, not a defence.** `ZipInfo.from_file` does `arcname = os.path.normpath(os.path.splitdrive(arcname)[1])` and then strips *leading* separators. `normpath` collapses interior `a/../b` but **preserves a leading `..`**, so `"../../x.txt"` survives as a relative escape inside the archive. Worse, an arcname of `"/"` normalizes to a bare separator, the strip loop empties the string, and the next iteration of `while arcname[0] in ...` raises **`IndexError`**. Defensive flattening (Decisión 3) is therefore not redundant with the stdlib | `zipfile/__init__.py:563-569` |
| V2 | **A duplicate `arcname` is a `UserWarning`, not an error — and not silence either.** `_writecheck` calls `warnings.warn('Duplicate name: %r')` and then writes the member anyway; both entries land and extraction yields the last. **The proposal's phrase "*last-write-wins* silencioso de `zipfile`" is imprecise**: it warns. The *decision* it justified (raise, never tolerate) survives untouched, because nothing in this suite turns warnings into errors — `pyproject.toml:62` sets no `-W error` — so the warning is invisible in practice | `zipfile/__init__.py:1782-1786`; `pyproject.toml:55-62` |
| V3 | **`ZipFile.close()` releases the underlying handle even when writing the end record fails.** The end-record write sits in a `try:` whose `finally:` runs `fp = self.fp; self.fp = None; self._fpclose(fp)`. So an `except` block placed **after** the `with` is guaranteed to run with no open handle — which is exactly what makes a Windows-safe `unlink` of the partial file possible, the same ordering `_copiar` already established | `zipfile/__init__.py:1918-1938`; `app/recepcion.py:83-85` |
| V4 | **`ZipFile.write` already streams; there is no in-memory member.** `with open(filename,"rb") as src, self.open(zinfo,'w') as dest: shutil.copyfileobj(src, dest, 1024*8)`. `_copiar`'s byte-counting loop has no RAM exposure to solve here — what is worth reusing from `_copiar` is its *ordering* discipline (V3), not its mechanism | `zipfile/__init__.py:1835-1836` |
| V5 | **The `core/` boundary this item must honour is about signatures, not the import graph.** `app/core/errores.py:27-29` imports `fastapi` and `starlette`, so *any* module importing `ErrorContenido` — `validaciones.py` today, `empaquetado.py` tomorrow — transitively imports Starlette. Item #8's design recorded the same correction. The obligation is that no Starlette/FastAPI **type** appears in this module's signatures or bodies (`validaciones.py:10-14`), verified by reading the surface, not by an import check | `app/core/errores.py:27-29`; `app/core/validaciones.py:10-14`; item #8 `design.md` §2 |
| V6 | **Indexing a two-shape `Contexto` union by a key present in only one member already typechecks in this repo.** `tests/test_errores_tipificados.py:275` does `error.contexto["archivos"]` where `ErrorTamano.contexto: ContextoTamano \| ContextoTamanoTotal`, and `pyproject.toml:46-49` sets `strict = true`, `warn_unreachable = true`, with no `disable_error_code`. The gate is green at 242 tests. A second sibling shape therefore needs no `cast` and no `type: ignore`, and the shipped `error.contexto["columna"]` at line 252 keeps typechecking | `tests/test_errores_tipificados.py:252, 275`; `pyproject.toml:46-53` |
| V7 | **Nothing in the repository bounds output size, and `ArchivoSalida` cannot even report it.** `ArchivoSalida` has exactly three fields and no size (`tipos.py:29-35`); `ContratoProcesador` has no output-side field; `PRESUPUESTO_DE_RAM_BYTES` is documented as a per-input-file declared-size ceiling. Recorded because the absence is a deliberate gap (proposal, Out of Scope), not an oversight this design should quietly fill | `app/core/tipos.py:29-35`; `app/core/validaciones.py:32-50` |

## 1. Technical approach

One new module, one additive context shape, one ADR. No existing module is touched except
`errores.py`, and nothing in the pipeline calls the new module yet.

- **`app/core/empaquetado.py`** (new) — one public function, `empaquetar`, plus two module constants
  and one non-typed exception. Cardinality decides everything: zero raises, one passes through
  verbatim, two-or-more become a flat ZIP written into the caller's directory.
- **`app/core/errores.py`** — a sibling `ContextoSinSalidas` joins the `Contexto` union and
  `ErrorContenido` gains a `sin_salidas()` classmethod. `TipoError` stays at exactly five values and
  `_ESTADO_HTTP` is untouched, so zero outputs is a 422 with no new mapping.
- **`adrs/0023`** — records the shape decision and, deliberately, why this module's *other* failure
  lands on the opposite side of the typed vocabulary.

The organising idea, and the only one needed to read the module: **every check that can fail is a
precondition of the write.** That is the same two-phase shape ADR 0021 gave `recepcion.py` — contract
first, bytes second — applied to the output side. Once it holds, "never half a ZIP" stops being an
argument about atomicity and becomes an ordering property of six lines.

## 2. Decision — zero outputs gets a sibling context shape, not a widened `motivo`

**This is the decision the proposal deferred here, and it is the reason this phase ran at high
effort.** What was already settled and is *not* reopened: zero outputs is `TipoError.CONTENIDO` →
422 (BACKLOG, `_ESTADO_HTTP`).

**Chosen: `ContextoSinSalidas` joins the `Contexto` union; `ErrorContenido.sin_salidas()` builds it.**

```python
class ContextoSinSalidas(TypedDict):
    motivo: Literal["sin_salidas"]

Contexto = ... | ContextoContenido | ContextoSinSalidas | ...

class ErrorContenido(ErrorTipificado):
    tipo = TipoError.CONTENIDO
    contexto: ContextoContenido | ContextoSinSalidas

    @classmethod
    def sin_salidas(cls) -> ErrorContenido: ...
```

| Option | What goes in `archivo`? | `motivo` semantics | Verdict |
|---|---|---|---|
| Reuse `ErrorContenido.cero_filas(archivo=…)` unchanged | **Nothing can.** Packaging holds an *empty* `list[ArchivoSalida]` and never sees an `ArchivoEntrada` — it has literally no filename in scope. Only a sentinel (`""`, `"(salida)"`) would fit | Conflates item #16's row-level fact ("no valid rows in the source data") with "the processor emitted no files". A filter that legitimately matched nothing has rows and no files; the portal's banner would state a falsehood | **Rejected** — ADR 0021 already rejected the sentinel move verbatim for `ContextoTamano.archivo`: it "codifica un segundo significado en un campo de texto libre y rompe por convención la forma que ADR 0014 fija por tipo" |
| Add a third value to the closed `Literal`, keep the three-field shape | Same sentinel problem, unchanged | Fixed | **Rejected** — solves the naming half and leaves the shape half exactly where it was |
| **Sibling shape + classmethod** | No such field exists to fill | New and disjoint | **Chosen** — this is the `ContextoTamanoTotal`/`ErrorTamano.total()` pattern applied to the very problem it was invented for: a failure with no culprit file |
| A non-typed exception, item #10 translates (the `FalloDelModulo` route) | — | — | **Rejected** — BACKLOG puts zero outputs in the client-visible vocabulary explicitly, and PRD.md:286-290 requires the portal to *distinguish* it from success. That is settled, not open |
| A sixth `TipoError` | — | — | **Rejected** — ADR 0014 closes the enum and inherited authority wins |

**Why the shape carries exactly one field.**

- `motivo` is already the key the portal branches on for both shipped `CONTENIDO` cases, so the new
  shape extends the existing branch rather than introducing a second mechanism. The coupling delta
  ADR 0014 warns about ("la forma de `contexto` varía según el tipo… ese conocimiento es un
  acoplamiento real entre los dos repositorios") is one sentence: *when `motivo` is `"sin_salidas"`
  there is no `archivo` and no `columna`.*
- Nothing else is true at the failure site. `clave_procesador` would have to be threaded into
  `empaquetar` purely to be echoed back, and the portal already knows it — it is in the URL it
  called. Rejected as redundant coupling that would put a diagnostic parameter in a pure function's
  signature.
- No count is available or meaningful: the list is empty, and no contract field declares an expected
  output count.
- Unlike `ErrorTamano.total()`, `sin_salidas()` takes no arguments, so there is **no placeholder to
  overwrite** — the "ningún estado inválido escapa de este método" concern that method's docstring
  records simply does not arise here.

**Cost, stated rather than discovered later**: the `Contexto` union reaches seven members and the
portal gains a third `CONTENIDO` branch to implement, plus the fallback ADR 0014 already makes
mandatory. V6 shows the mypy side costs nothing.

## 3. Decision — the public surface

```python
NOMBRE_DEL_ZIP: Final[str] = "salida.zip"       # server-generated, never derived from any input
MIME_DEL_ZIP:  Final[str] = "application/zip"

class SalidaMalFormada(Exception): ...          # NOT an ErrorTipificado — see below

def empaquetar(*, archivos: list[ArchivoSalida], directorio: Path) -> ArchivoSalida: ...

# private: _nombre_plano(...), _verificar(...), _escribir_zip(...)
```

| Decision | Choice | Rejected | Rationale |
|---|---|---|---|
| How it learns the target directory | `directorio: Path` | `reserva: Reserva` | `validaciones.py:10-14` — the core takes primitives. Accepting a `Reserva` would hand packaging `ceder_limpieza()`, i.e. a second claim on the ownership ADR 0020 grants to exactly one point. **`empaquetado.py` imports nothing from `temporales.py`; that is the mechanical proof, the same one item #7 used** |
| Return type | `ArchivoSalida` | `Path`; a `(Path, str, str)` tuple; a `Response` | Keeps one currency type across every `core/` boundary (ADR 0012/0022) and lets item #10 write a single `FileResponse(...)` call regardless of cardinality. A `Response` is impossible anyway (V5's signature rule) |
| Sync or async | **sync** | `async def` | `ejecucion.py` ships synchronous functions and the caller crosses with the repo's one idiom, `await run_in_threadpool(...)` (`recepcion.py:165`, `temporales.py:156`). Keeps this module testable with no event loop, and leaves the threading policy to item #10 |
| Argument style | keyword-only | positional | Every multi-argument function and constructor in `core/` is keyword-only |
| One public function or several | one, plus privates | separate `empaquetar_uno`/`empaquetar_varios` | Cardinality is not the caller's concern — the entire point is that item #10 writes the same two lines for one output and for five |
| Failure type for a malformed output set | `SalidaMalFormada(Exception)`, standalone | a subclass of `ejecucion.FalloDeEjecucion` | The child ran *fine*; this is not an execution failure, and item #10's broad `except FalloDeEjecucion` must not swallow a packaging bug as a module crash. It also keeps pipeline step 8 free of any dependency on step 7, so either is revertible alone. Precedent: `ServicioSaturado` is a standalone `Exception` inside `ejecucion.py` for the same reason. Note V5 — the rejection is on semantics, **not** on import cost, which does not exist |

**Why `SalidaMalFormada` is not an `ErrorTipificado`.** ADR 0014 describes the four 422 types as
"los cuatro tipos que el usuario puede provocar y corregir". `nombre_propuesto` is first-party code
(the processor, items #12/#16), unlike `nombre_original`: the client can neither cause a duplicate
nor correct one. ADR 0018 already sent the one non-correctable case — `CLAVE_INEXISTENTE` — to a 500
rather than a 422, and ADR 0022 established the shape for "not a `TipoError`; item #10 owns the HTTP
translation". So this failure follows 0018/0022, not 0014, and `TipoError` stays at five.

**The two failures in this module land on opposite sides of the typed vocabulary on purpose**, and
each side has its own reason: zero outputs is a fact about the *client's data* that BACKLOG puts in
the client's vocabulary; duplicate or degenerate names is a fact about *our* code that the client
cannot act on. §10 records the split so a later reader does not "fix" it into false consistency.

## 4. Decision — write mechanics: the whole function is an ordering

```python
def empaquetar(*, archivos: list[ArchivoSalida], directorio: Path) -> ArchivoSalida:
    if not archivos:                                  # 1. before any Path is built
        raise ErrorContenido.sin_salidas()
    if len(archivos) == 1:                            # 2. verbatim, no ZIP, no name check (§5)
        return archivos[0]

    destino = directorio / NOMBRE_DEL_ZIP
    nombres = _verificar(archivos, destino)           # 3. pure: no byte reaches disk

    try:                                              # 4. the only write
        with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as contenedor:
            for archivo, plano in zip(archivos, nombres, strict=True):
                contenedor.write(archivo.ruta_temporal, arcname=plano)
    except Exception:                                 # 5. the handle is already closed (V3)
        destino.unlink(missing_ok=True)
        raise

    return ArchivoSalida(                             # 6. only after a clean close()
        nombre_propuesto=NOMBRE_DEL_ZIP, ruta_temporal=destino, tipo_mime=MIME_DEL_ZIP
    )
```

Step 3 checks four things, all pure, all before any write: every flattened name is non-degenerate;
no two flatten to the same name; no input's `ruta_temporal` *is* `destino`; every `ruta_temporal`
exists. All four raise `SalidaMalFormada`.

| Question | Choice | Rejected | Rationale |
|---|---|---|---|
| Memory or disk | a real file inside `directorio` | `io.BytesIO` | Decisión 1, locked. ADR 0020 names "el ZIP intermedio" as a temporal that must be cleaned, and the whole lifecycle machinery (`Reserva`, sweeper) is disk-based |
| Name on disk | the fixed constant `salida.zip` | `mkstemp(suffix=".zip", dir=directorio)`; anything derived from a `nombre_propuesto` | ADR 0020's rule is that the **server** generates on-disk names, never a client — a module `Final` satisfies it and reads better in a directory listing and in a test. `mkstemp` would buy uniqueness that `mkdtemp` already provides per request; the one residual collision it would close (a processor that itself wrote `salida.zip` into the directory it was handed) is closed by step 3 instead, explicitly rather than by obscurity |
| Write-then-rename | **no** — write in place | `salida.zip.parcial` → `os.replace` | Nothing can observe the destination before the function returns: on the failure path the caller never learns the path at all, because the `ArchivoSalida` is constructed only after a clean `close()`. A rename would add a Windows `PermissionError` mode (ADR 0020, Consecuencias) to protect a reader that does not exist |
| Reuse `_copiar`'s bounded write | reuse the **ordering**, not the mechanism | a byte-counting loop against a limit | V4 — `ZipFile.write` already streams at 8 KiB, so there is no RAM exposure to bound; and V7 — there is no output ceiling to compare against, so a limit would have to be invented, which the proposal put out of scope. What *is* reused is the rule `_copiar` states verbatim: close the handle, **then** raise, because on Windows a delete over an open handle raises `PermissionError` that ADR 0020 tolerates only by deferring to the sweeper |
| Cleanup on failure | `unlink(missing_ok=True)` on the one file this module created | rely on `Reserva` alone | The `Reserva` remains the real guarantee and **this is not a second ownership claim**: `empaquetado.py` deletes exactly the path it created and never touches `directorio` itself. It earns its line because the acceptance criterion ("no partial `.zip` visible") then becomes provable against a bare `tmp_path`, with no `Reserva` anywhere in the test |
| Compression / determinism | `ZIP_DEFLATED`, default level, no pinned `date_time`/`external_attr` | `ZIP_STORED`; pinned metadata | Decisión 6, locked |

## 5. Decision — names inside the archive

```python
def _nombre_plano(nombre_propuesto: str) -> str:
    return nombre_propuesto.replace("\\", "/").rpartition("/")[2]
```

**Text manipulation, never `Path` construction** — the rule `recepcion.py::_formato` states verbatim
for the input side ("`rpartition`, NUNCA `Path(nombre_original).suffix`… Acá se manipula texto, nunca
una ruta"). Both separators are normalized on both platforms, because the name is produced by a
processor that may be authored on either. V1 is why this is not redundant with the stdlib.

- A result of `""`, `"."` or `".."` is **degenerate and raises**. No fallback name is invented:
  fabricating one would silently rename a file and could itself collide — and V1 shows `"/"` would
  otherwise reach an `IndexError` inside `from_file`.
- **Duplicates raise** (Decisión 3, locked). V2 is why this needs code rather than trust: the stdlib
  warns and writes both members, and this suite does not turn warnings into errors.
- `arcname` is always passed explicitly. The default is the *full source path*, which would embed
  the entire `mkdtemp` path in the archive and break TECH-DESIGN.md:210-214 ("sin rutas absolutas ni
  componentes de directorio embebidos") outright.

**The asymmetry with passthrough is deliberate, stated so a reviewer does not read it as an
oversight.** The single-output path returns its input untouched and checks no name. Flattening
exists because inside a ZIP a name becomes a **structural element** — an archive member path. In
passthrough it stays metadata that item #10 encodes into a header (Decisión 5, out of scope here).
Applying the check there would turn a harmless odd name into a 500 for no gain.

## 6. Sequence

```
item #10 pipeline (parent process)                 app/core/empaquetado.py
        │
        ├─ ejecutar_modulo(...) ──► list[ArchivoSalida]      (item #8: already all-or-nothing)
        │
        ├─ empaquetar(archivos=…, directorio=reserva.directorio)
        │       │
        │       ├─ 0 ─────────► raise ErrorContenido.sin_salidas()   ─► 422 {"tipo":"contenido",
        │       │               no Path built, no byte written           "contexto":{"motivo":
        │       │                                                        "sin_salidas"}}  (item #3
        │       │                                                        handler, unchanged)
        │       ├─ 1 ─────────► return archivos[0]            verbatim: same Path / MIME / name
        │       │
        │       └─ N ─┬─ (3) pre-write, pure: flatten names ─► degenerate? duplicate?
        │             │        destination collides with a source? source missing?
        │             │        └────────────► raise SalidaMalFormada ─► item #10 translates
        │             │
        │             ├─ (4) ZipFile(destino,"w",DEFLATED)
        │             │        write(ruta_temporal, arcname=plano) × N     (V4: streams at 8 KiB)
        │             │        └─ any failure ─► __exit__ closes the handle (V3)
        │             │                          ─► destino.unlink(missing_ok=True) ─► raise
        │             │
        │             └─ (6) clean close() ─► ArchivoSalida("salida.zip", destino,
        │                                                   "application/zip")
        │
        └─ FileResponse(salida.ruta_temporal, media_type=salida.tipo_mime,
                        filename=salida.nombre_propuesto,
                        background=reserva.ceder_limpieza())   ◄── item #10, NOT this item
```

Everything `empaquetar` writes lands under `directorio`, which `Reserva` already owns; this module
imports nothing from `temporales.py` and never calls `ceder_limpieza()`. The `ArchivoSalida` that
references the ZIP exists only on the path where `close()` returned without raising — so no caller
can ever hold a handle to a partial file, which is precisely Decisión 2's guarantee expressed as
control flow rather than as an assertion.

## 7. File changes

| File | Action | Description |
|---|---|---|
| `app/core/empaquetado.py` | Create | §3, §4, §5. Imports stdlib (`zipfile`, `pathlib`, `typing`) plus `app.core.errores` and `app.core.tipos`. **Nothing from `app/procesadores/`** (ADR 0011 invariant), **nothing from `app.core.temporales`** (§3), **nothing from `app.core.ejecucion`** (§3), and no Starlette/FastAPI type in any signature or body (V5) |
| `app/core/errores.py` | Modify | §2 — `ContextoSinSalidas`, its entry in the `Contexto` union, the widened `ErrorContenido.contexto` annotation, and the `sin_salidas()` classmethod. `TipoError` untouched — still exactly five values. `_ESTADO_HTTP` untouched |
| `adrs/0023-cero-salidas-y-fallas-de-empaquetado.md` | **Created this phase** | §10. Spanish, MADR matching siblings 0011–0022. Number verified against disk. Already on disk — `sdd-tasks` must **not** schedule a task to write it |
| `tests/test_empaquetado.py` | Create | §8 |
| `tests/test_errores_tipificados.py` | Modify | §8 — the new shape's pickle round-trip and its serialized 422 body, alongside the existing `TestDosFormasDeTamano` block |
| `app/recepcion.py` | **Untouched** | Zero lines. The `NotImplementedError` at 188-190 is item #10's seam; this item ships a composable piece, not a caller |
| `app/core/{temporales,ejecucion,tipos,contrato,validaciones}.py`, `app/main.py`, `app/registry.py` | **Untouched** | Zero lines. `ArchivoSalida` needs no field; no lifecycle change; no new configuration |

## 8. Testing strategy

Behavioural only. No child process is needed anywhere in this item, so every test is milliseconds.
`REGISTRY` is still empty (item #8's V9), so the whole suite runs against hand-built
`list[ArchivoSalida]` — the same standalone posture `validaciones.py` already has.

| Layer | What to test | Approach |
|---|---|---|
| Unit | **Passthrough is verbatim** — same `Path`, same MIME, same name — and writes nothing | One `ArchivoSalida` + `tmp_path`; assert identity of the three fields and that the directory contents are unchanged |
| Unit | **Two or more produce exactly one flat ZIP** whose members carry the proposed names and the original bytes | `namelist()` + `read()`; assert no member contains `/` or `\`, and that `salida.zip` is the only new file |
| Unit | **Zero outputs raises before disk** — `ErrorContenido` with `tipo is TipoError.CONTENIDO` and `contexto == {"motivo": "sin_salidas"}` | `pytest.raises`; then assert the directory is still empty. This is the §2 decision's load-bearing test |
| Unit | **Hostile names are confined** — `"../../x.txt"`, `"a/b/c.txt"`, `"C:\\Windows\\x.txt"` all become flat members | Parametrized. V1 is why this asserts on our output rather than trusting `from_file` |
| Unit | **Degenerate names raise** — `""`, `"."`, `".."`, `"/"` → `SalidaMalFormada`, nothing written | Parametrized; assert the directory is empty afterwards |
| Unit | **Duplicates raise**, including two different paths whose names *flatten* to the same member | V2 is why trust is not an option here |
| Unit | **An input that is the destination raises** before the write, so `ZipFile(..., "w")` can never truncate a file it is about to read | Build an `ArchivoSalida` at `directorio / "salida.zip"` |
| Unit | **A simulated mid-write failure leaves no `.zip`** and returns nothing | `monkeypatch` `zipfile.ZipFile.write` to raise on the second member; assert the exception propagates and `destino` does not exist. This is the direct exercise of Decisión 2 the proposal asked for |
| Unit | **The new context survives `pickle`** (so it can cross item #8's `Pipe`) and serializes to the documented 422 body | Extends the shipped round-trip and handler cases in `tests/test_errores_tipificados.py` |
| Static | Whole change | `uv run ruff check . && uv run ruff format --check . && uv run mypy app tests && uv run pytest` — baseline 242 tests, all green before and after |

Explicitly **not** written: AST/structural tests, chaos tests, deliberate-red perturbation, or an
assertion that `empaquetado.py`'s import list excludes Starlette. Strict TDD has been off since item
#3, and V5 shows the import assertion would be false anyway.

## 9. Review budget forecast

Test rows carry the repo's **+40% correction already applied** (items #6/#7/#8 convention);
`sdd-tasks` must not apply it twice.

| Artifact | Est. changed lines |
|---|---|
| `app/core/empaquetado.py` | 115–145 |
| `app/core/errores.py` | 25–35 |
| `adrs/0023-*.md` | **135 — actual, already written this phase** |
| **Production subtotal** | **275–315** |
| `tests/test_empaquetado.py` (corrected) | 175–230 |
| `tests/test_errores_tipificados.py` (corrected) | 25–40 |
| **Tests subtotal** | **200–270** |
| **Total (authored)** | **475–585** |

**Under 600 at the top of the range, so one PR** — but with only 15 lines of headroom, so the margin
is thin and honest rather than comfortable. Unlike item #8, the orchestrator's number and
`openspec/config.yaml:42` agree at 600, so there is nothing to reconcile. The last five changes ran
30–50% over their design-phase forecasts, always on the test file; if `sdd-tasks` judges that
history decisive, the natural seam is **`errores.py` + `adrs/0023` + the error tests first**
(~185–210, additive, no caller at all), then `empaquetado.py` + its tests (~290–375). That mirrors
item #8's S1 (vocabulary and ADR first) and item #7's A1. Both slices are independently green and
independently revertible. `sdd-tasks` owns the formal guard lines and the final call.

## 10. ADR 0023 — yes, and why

**Decision: write it — and it is written.** `adrs/0023-cero-salidas-y-fallas-de-empaquetado.md`
exists on disk as of this phase, MADR matching siblings 0011–0022, in neutral professional Spanish,
sections Estado / Contexto / Decisión / Alternativas consideradas / Consecuencias. This departs from
item #8, whose design left `adrs/0022` for `sdd-tasks` to schedule: the decision recorded here *is*
this phase's headline output, so deferring the record would have separated it from the reasoning
that produced it. `sdd-tasks` therefore schedules no ADR task — it schedules `errores.py`,
`empaquetado.py` and the tests only.

**Numbering evidence**: `adrs/` holds `0011`–`0022` on disk — twelve files, listed this phase.
`openspec/config.yaml:8` still says "0011-0015 exist"; it was already flagged as stale by item #7's
V7 and again by item #8's design, and it has drifted two further since. **Next free number is
0023**, exactly as the proposal and exploration independently concluded.

**Amendment or new ADR?** Neither predecessor is reopened. ADR 0014 keeps its five-member enum. ADR
0021 keeps `ContextoTamanoTotal` and `ErrorTamano.total()` byte-identical. What 0023 records are
three decisions made *under* both, each of which a future reader would otherwise have to
reconstruct by archaeology:

1. **`"cero_filas"` is deliberately not reused** even though the value exists and looks applicable.
   Anyone diffing the code against `errores.py:203-204` will ask exactly this; without a record the
   answer lives scattered across item #3's and item #16's scope.
2. **The `Contexto` union grows a second time.** ADR 0021 had to record once why that does not
   reopen ADR 0014. A second instance promotes an exception into a pattern, and that promotion
   deserves a record rather than being inferred from two unrelated classmethods.
3. **This module's two failures sit on opposite sides of the typed vocabulary on purpose** (§3):
   `ErrorContenido` for zero outputs, `SalidaMalFormada` for a first-party naming bug. That is the
   kind of asymmetry a later reader "fixes" into consistency unless the reason is findable from the
   decision record.

## 11. Threat matrix

None of the sdd-design skill's trigger boundaries exists in this change — no routing, no shell, no
subprocess, no VCS/PR automation, no executable-file classification, no process integration — so
`references/threat-matrix.md` was **not** loaded. The matrix below is item-specific, and it exists
because one genuine boundary does appear: a name becoming an archive member path.

| Boundary | Applicability | Design response | Planned test |
|---|---|---|---|
| `nombre_propuesto` → archive member path | **Applicable** | `_nombre_plano` flattens on both separators before `arcname`; degenerate results raise instead of receiving a fabricated fallback (§5). V1 shows the stdlib's own normalization is partial | Hostile-name and degenerate-name rows in §8 |
| `nombre_propuesto` → filesystem path | **N/A by construction** | No proposed name ever builds a path on disk. The only path this module creates is `directorio / NOMBRE_DEL_ZIP`, from a module constant (ADR 0020's server-generated-names rule) | The ZIP lands at exactly that path regardless of input names |
| Destination truncating one of its own sources | **Applicable** | Step 3 rejects an input whose `ruta_temporal` is `destino`, so `ZipFile(..., "w")` can never truncate a file it is about to read. **Honest limit**: `Path` equality catches the plausible case (a processor writing into the directory it was handed) and not symlink or relative-path aliasing | The destination-collision row in §8 |
| Unbounded output growth | **Applicable — declared open** | No output-side ceiling exists (V7) and this item does not invent one (proposal, Out of Scope). A misbehaving processor can produce an arbitrarily large ZIP inside the request directory, bounded only by `Reserva`'s eventual cleanup | **No test.** Manufacturing one for an unmitigated risk would misrepresent it; recorded in `adrs/0023` Consecuencias instead |
| Zip bomb | **N/A — direction reversed** | This module *writes* an archive from files the service already holds and decompresses nothing. `validar_tamano_descomprimido` remains the input-side defence | — |
| Secret or path leakage into a response | **Applicable** | `ContextoSinSalidas` carries one `Literal` and no free text, so no temp path and no module value can reach the 422 body. `SalidaMalFormada`'s message is operational-log material (item #14), never a body — the same constraint ADR 0022 placed on `FalloDelModulo.traza` | Assert the 422 body is exactly `{"tipo": "contenido", "contexto": {"motivo": "sin_salidas"}}` |
| Shell / subprocess / VCS / routing / auth | **N/A** — none exists in this change | — | — |

## 12. Migration / rollout

No migration, no schema, no persisted state, no feature flag, no configuration. Rollback is a code
revert: delete `app/core/empaquetado.py` and `tests/test_empaquetado.py`, and revert the additive
shape in `errores.py`. **Nothing imports the new module** — item #10 wires the seam — so there are
no dependents to unwind, and the `errores.py` change touches none of the five existing types.
Nothing on disk needs cleaning afterwards.

## 13. Open questions

- [ ] **Passthrough does not verify that the file exists or that it lies inside `directorio`.**
      Deliberate: packaging is not the processor's auditor. Item #8's design already records as an
      open question that the shipped `Procesador` ABC takes no output directory, so an output path
      outside `directorio` is legal today — and would simply escape `Reserva`'s cleanup. Owned by
      items #10/#12/#16, named here rather than silently assumed away.
- [ ] **No output-size ceiling** (V7, §11). If one is ever added it belongs as a documented `Final`
      in this module, following `PRESUPUESTO_DE_RAM_BYTES`, **not** as a `ContratoProcesador` field —
      ADR 0021 rejected that placement once already.
- [ ] **The ZIP's client-facing name is a constant** with no processor key and no timestamp in it.
      If the portal ever wants a per-processor download name, that is item #10's `Content-Disposition`
      decision (Decisión 5) and can be made without reopening this module: `nombre_propuesto` is a
      suggestion the HTTP edge may override.
- [ ] **Container determinism is deliberately not pinned** (Decisión 6). Revisit only if a parity
      fixture (ADR 0015, items #15/#16) ever hashes a whole ZIP rather than its unpacked contents.
- [ ] **Proposal correction — V2.** The proposal calls `zipfile`'s duplicate handling "*last-write-wins*
      silencioso"; it emits a `UserWarning`. The decision it justified is unaffected, but the phrase
      should be reconciled in the spec so the reason for the explicit check is stated accurately.
- [ ] **The portal now needs a third `CONTENIDO` branch** (§2). ADR 0014 already makes a fallback
      mandatory in item #10, so this is a scheduled cost rather than a new risk — but it is a
      cross-repository contract change and should be treated as one.
