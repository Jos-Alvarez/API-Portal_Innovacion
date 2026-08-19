# Design: Contract Validations and Memory Defense

- **Change**: `validaciones-de-contrato-y-defensa-de-memoria` (BACKLOG item #7)
- **Inputs**: `proposal.md` (**authoritative for decisions**; one factual premise inside it is corrected
  by V1 below), `app/recepcion.py`, `app/core/{contrato,errores,temporales,tipos}.py`,
  `tests/test_recepcion.py`, `adrs/0011`–`0020`, inherited `L:\App_Portal\adrs\0006`,
  `REVISION-ADVERSARIAL.md` (H-04, H-09), `openspec/config.yaml`, Engram
  `sdd/validaciones-de-contrato-y-defensa-de-memoria/{explore,hallazgo-starlette}`
- **Authority**: ADRs outrank every other document. Inherited `L:\App_Portal\adrs\0001`–`0010` outrank
  local `adrs\0011`–`0020`. **This change authors `adrs/0021`** — see V7 for the numbering evidence.
- **Methodology**: Strict TDD **disabled** (`openspec/config.yaml`). Behavioural tests only. `ruff` and
  `mypy --strict` still run. The full SDD chain still runs. Every command goes through `uv run`.
- **Review budget**: 600 lines. §13 shows this change does not fit, and names a three-slice chain
  rather than asking for a blanket exception.

## 0. Verified facts this design rests on

Item #6's design opened with this table because "four false library claims have already entered this
project's artifacts by recall". The same discipline applies here, and it earns its keep immediately:
**V1 contradicts a premise written into the proposal**. Each row cites what was read in
`L:\API-Portal\.venv\Lib\site-packages` or in a repository file.

| # | Claim | Evidence |
|---|---|---|
| V1 | **`UploadFile.size` is a measured byte count, not a client declaration.** The parser constructs every file part with `size=0` and `UploadFile.write()` does `self.size += len(data)` for each chunk it actually writes. `carga.size` therefore equals the bytes Starlette really spooled — it **cannot** carry a `Content-Length` lie. The proposal's Scope line *"closing the gap between a lying `carga.size`/`Content-Length` and what actually lands on disk"* rests on a false premise. The **decision** it justifies (bounded, early-aborting copy) is kept unchanged; §3 replaces its rationale with a true one | `starlette/formparsers.py:232-237` (`size=0`); `starlette/datastructures.py:451-454` |
| V2 | **`max_part_size` never applies to file parts.** `on_part_data` guards the ceiling behind `if self._current_part.file is None:`; file bytes go straight to `_file_parts_to_write` with no check. Re-confirmed here, not recalled | `starlette/formparsers.py:181-188` |
| V3 | **The unbounded resource is OS temp disk, not RAM.** `spool_max_size = 1024 * 1024` caps each part's memory footprint at 1 MB before it rolls to `gettempdir()`; `max_files` defaults to 1000 and caps counts only | `starlette/formparsers.py:147, 157` |
| V4 | **`obtener_contrato` returns `None` for every key.** `_TABLA_CONTRATOS` is an empty `MappingProxyType`. Decisive here: hoisting contract resolution above the copy loop makes that loop **unreachable in production today** | `app/core/contrato.py:63, 74` |
| V5 | **Three shipped tests assert that files land on disk**, via the `captura_de_limpieza` spy. Those assertions stop being reachable the moment V4 meets the reordering, so `tests/test_recepcion.py` is **restructured, not merely extended** | `tests/test_recepcion.py:95-96, 118-120, 138-139` |
| V6 | **No home exists for a RAM budget.** `ContratoProcesador` has six fields, none of them a memory ceiling; `Configuracion` carries only `token_servicio` and its docstring defers the rest to item #8 | `app/core/contrato.py:34-44`; `app/core/configuracion.py` |
| V7 | **The next local ADR is 0021, not 0016.** `adrs/` contains `0011`–`0020` on disk. `openspec/config.yaml`'s *"0011-0015 exist"* comment is **stale** — it was written at init, before items #2–#6 authored 0016–0020. The proposal's `adrs/0021` is right | `Glob adrs/*.md` → ten files, `0011`…`0020`; `openspec/config.yaml:8` |
| V8 | **`ErrorTamano.contexto` is annotated `ContextoTamano`.** A second context shape on the same class requires widening that annotation, or `mypy --strict` rejects the assignment | `app/core/errores.py:104-113` |
| V9 | **Item #6's cleanup guarantee is `reservar()`'s `finally`**, which calls `limpiar()` unless `ceder_limpieza()` transferred ownership. `ceder_limpieza()` is unreachable today (V4). Nothing in this change touches `temporales.py` | `app/core/temporales.py:91-110` |
| V10 | **`zipfile` reads the central directory without decompressing.** `ZipFile.infolist()` parses the end-of-central-directory record and returns `ZipInfo.file_size` — the *declared* uncompressed size. Standard-library documented behaviour, cited as such rather than as a line read | CPython `zipfile` docs; `ZipInfo.file_size` |

## 1. Technical approach

One new pipeline-agnostic module and one reordering.

- **`app/core/validaciones.py`** — five pure functions plus one `Final` constant. It compares numbers
  and strings against a `ContratoProcesador` and raises the shipped typed errors. It imports the
  standard library, `app.core.contrato`, `app.core.errores` and `app.core.tipos`, and **nothing from
  `app/procesadores/`** (ADR 0011's invariant, satisfied by construction). Decisively, it imports **no
  Starlette or FastAPI type** — see §4.
- **`app/recepcion.py`** — the per-file loop splits into two phases around `with reservar()`, and
  `_copiar` gains a byte ceiling.
- **`app/core/errores.py`** — the `Contexto` union grows one member. The `TipoError` enum does not.

The organising idea: **the contract is a precondition of the copy, not a postcondition.** Today's loop
reads as "receive everything, then find out whether we were allowed to". Every check this change adds
is cheaper than the copy it guards, and every one of them can be answered from data Starlette has
already produced. So the only real design work is deciding what may run before `reservar()`, what must
run inside it, and what remains true when the pre-check data is absent.

## 2. Decision — two phases around `reservar()`

**Chosen: gate on contract, count, format and declared size *before* entering `reservar()`; copy,
measure and inspect *inside* it.**

| Option | Cost of a rejected request | Item #6 `try/finally` | Verdict |
|---|---|---|---|
| Keep everything inside `reservar()`, validate after the loop (today) | Full copy of every file, then reject | Intact | Rejected: this *is* the defect |
| Keep everything inside `reservar()`, validate before the loop | `mkdtemp` + `rmtree` per rejected request, zero bytes written | Intact | Rejected — see below |
| **Phase 1 above `reservar()`, phase 2 inside it** | Zero syscalls, zero bytes | Intact, unchanged | **Chosen** |

**Why the middle option is rejected, and it is not a micro-optimisation.** Item #6's own design
rejected the ASGI-middleware alternative partly because *"it would create a temporary directory for
**every** request into `/interno`, including ones that upload nothing"*. A malformed-count or
unknown-key request is exactly such a request. Creating and removing a directory for a request that
was refused before it could write a byte contradicts a rejection this repository already made and
recorded; the cheapest failures are also the ones an attacker repeats hardest.

**How item #6's guarantee stays intact — stated per phase, because this is the regression to fear.**

- **Phase 1 raises before `with reservar()` is entered.** No `mkdtemp` ran, no `_EN_VUELO` entry
  exists, and there is nothing to clean. The guarantee is not weakened; it is not *needed*.
- **Phase 2 raises inside the `with`.** `finally: reserva.limpiar()` runs exactly as it does today
  (V9), including over a partially-written `entrada_{i}` left by an aborted copy. `ceder_limpieza()`
  is still never called, so the ceded branch is still unreachable.
- **`app/core/temporales.py` is not edited.** Zero lines. That is the mechanical proof.

**The honest consequence of V4 + this reordering.** `obtener_contrato` moves to the top, and it
returns `None` for every key. So **in production today, no upload is ever written to disk** — every
request now dies at `ErrorClaveInexistente` before phase 2. The route stops demonstrating reception
and starts demonstrating refusal. That is correct behaviour (an unknown key *should* not cost a
write), but it means item #6's shipped reception evidence survives only under an injected contract
(V5). This is a real, deliberate reduction in what the production route proves unaided, and §9 makes
the injection the mechanism that restores it rather than letting the coverage quietly lapse.

## 3. Decision — what the bounded copy actually defends

V1 removes the justification the proposal gave. The decision stands; here is the rationale that is
true.

`carga.size` is a truthful, free, pre-copy measurement (V1). A pre-check against it therefore already
prevents an oversized file from ever being copied into `reserva.directorio`. The bounded copy is
**not** the thing that stops a size lie — there is no size lie to stop. It is kept for three reasons,
each of which survives V1:

1. **`carga.size` is `int | None` in the type system.** The route must not assume the value that
   happens to be produced by one parser on one code path. When it is `None`, the bounded copy is the
   *only* enforcement, and it is complete.
2. **`tamano_comprimido` must remain "bytes that landed on disk".** ADR 0020 fixed that definition
   precisely so no client-declared number is propagated downstream. A ceiling enforced by the writer
   keeps that field bounded by construction, not by the caller's diligence.
3. **The next caller is not this one.** Items #9/#10 build the pipeline around this seam. A `_copiar`
   that cannot exceed its limit cannot be misused by a future call site that forgets the pre-check.

**And what it does not defend, restated because the proposal is right to insist on it.** This is a
**disk** defense, scoped to the *second* copy — the one into `reserva.directorio`. Starlette's *first*
parse has already spooled every byte to OS temp disk before `recibir()` receives control (V2, V3),
and no code inside this route can prevent it. H-09 stays **declared open**; `max_part_size` is
rejected on evidence (V2), the ASGI middleware is out of scope, and item #8 owns the memory ceiling.

**Mechanics, decided here so `tasks` does not improvise.** `_copiar(origen, destino, *, limite_bytes)`
keeps the 1 MB chunk loop and the defensive `origen.seek(0)`, accumulates the running count, and stops
reading the moment the count would exceed `limite_bytes`. It **closes the output handle first** — the
`raise` sits after the `with destino.open("wb")` block, not inside it — because on Windows `rmtree`
over an open handle raises `PermissionError`, which ADR 0020 tolerates only by deferring to the
sweeper. Closing first keeps cleanup synchronous. `recibido_bytes` is the real count at the abort, per
the proposal's success criterion.

**Where the two mechanisms meet.** Through the production route the pre-check normally wins, so
`recibido_bytes` is normally `carga.size` with zero bytes written — a *better* outcome than the
criterion asks for, reached by a different path than it describes. §14 flags this for spec
reconciliation rather than silently resolving it.

## 4. The public surface of `app/core/validaciones.py`

```python
PRESUPUESTO_DE_RAM_BYTES: Final[int] = 256 * 1024 * 1024

def validar_cantidad(*, recibido: int, contrato: ContratoProcesador) -> None: ...
def validar_formato(*, nombre_original: str, formato: str, contrato: ContratoProcesador) -> None: ...
def validar_tamano(*, nombre_original: str, tamano_bytes: int, contrato: ContratoProcesador) -> None: ...
def validar_tamano_total(*, nombres: list[str], total_bytes: int, contrato: ContratoProcesador) -> None: ...
def validar_tamano_descomprimido(
    entrada: ArchivoEntrada, *, presupuesto_bytes: int = PRESUPUESTO_DE_RAM_BYTES
) -> None: ...
```

Four decisions are compressed into those six lines.

| Decision | Choice | Rejected | Rationale |
|---|---|---|---|
| Failure signalling | Raise `ErrorTipificado` subclasses; return `None` | Return a result object the route translates | ADR 0014/0018 already ship one registered handler for these exceptions. A result type adds a second translation layer at the seam and a second place to get the mapping wrong |
| Parameter types | Primitives (`str`, `int`) plus `ContratoProcesador`; `ArchivoEntrada` only where a real file is needed | `list[ArchivoEntrada]` for every function | An `ArchivoEntrada` requires a `ruta_temporal`, which does not exist before the copy. Primitives are what makes the pre-copy phase possible at all — and they make the module unit-testable with hand-built values, closing the explore phase's open question about `_TABLA_CONTRATOS` being empty |
| Starlette types | **Never.** No `UploadFile` crosses into `app/core/validaciones.py` | Pass `carga` and read `.size`/`.filename` inside | `app/core/` is the pipeline; binding it to the HTTP surface's parser types would make every future non-multipart caller (item #10) drag Starlette with it. The route extracts, the core compares |
| `_formato()`'s home | Stays private in `app/recepcion.py` | Move it to `validaciones.py` | Extracting an extension from a client-declared filename is an HTTP-surface concern with its own ADR-shaped rule (`rpartition`, never `Path().suffix`). It is shipped, pinned by `TestFormato`, and moving it buys nothing |

**`validar_tamano_descomprimido`, and what it refuses to invent.** It opens `entrada.ruta_temporal`
with `zipfile`, sums `ZipInfo.file_size` across `infolist()`, and compares against
`presupuesto_bytes` — reading the central directory only, never decompressing (V10). Two edge cases
are decided here:

- **Not a ZIP** (`zipfile.is_zipfile()` is false): **no-op, not a failure.** There is no declared size
  to check. ADR 0006 claims such files are "bounded by the 25 MB compressed cap"; H-04 calls that
  claim false and item #8 owns the answer. This function does not pretend otherwise.
- **A corrupt ZIP** (`BadZipFile`): **no-op, not a failure.** Deciding whether a file is a valid
  `.xlsx` is *content* validation, and ADR 0014's closed enum has no vocabulary for it —
  `ContextoContenido.motivo` is `Literal["columna_faltante", "cero_filas"]`. Inventing a failure the
  enum cannot express is exactly the pressure ADR 0014 exists to resist. The processor (items
  #12/#16) fails on it properly.

**Per-archive, not per-batch.** The sum is taken *within one archive* — that is the shape of a zip
bomb. A cross-batch uncompressed sum is a natural extension and is deliberately not designed: the
default contract sets `entradas_max = 1` (`app/core/contrato.py:51`), which makes the batch and the
archive the same thing today. §14 records it.

## 5. Decision — the RAM budget: 256 MB, as a module `Final`

**Location** is settled by the proposal (module-level `Final`, not a `ContratoProcesador` field),
following `temporales.py`'s `UMBRAL_DE_EDAD`/`INTERVALO_DE_BARRIDO` precedent and ADR 0006's
worker-level framing (V6). This design adds the **value**, which the proposal left open.

**256 MB**, presented the way item #6 presented 15 minutes: a **choice with a sourced floor**, not a
citation. The floor: the budget must exceed the largest *legitimate* uncompressed payload, and
`tamano_max_bytes` caps a single upload at 25 MB compressed; `.xlsx` is XML in a ZIP and compresses at
roughly 5–20×, so 250 MB is the realistic top of the legitimate range. The ceiling: it must sit
*"holgadamente por debajo de la memoria del worker"* (ADR 0006), and 256 MB is comfortably below any
plausible host. It is one `Final` line, editable in one place, and `validar_tamano_descomprimido`
takes it as a defaulted keyword so tests set a small budget instead of building a 256 MB fixture.

**What it is not.** It bounds a number the attacker writes into a header. `zipfile` notices a lie only
after decompressing and checking the CRC, and the magnitude that actually exhausts RAM is the pandas
`DataFrame`, not the raw XML. This is the first line of defense H-04 says is necessary and
insufficient; item #8 owns the real ceiling.

## 6. Decision — the union grows, the enum does not

`TipoError` stays at five values (ADR 0014). `app/core/errores.py` changes in four coordinated places:

```python
class ContextoTamanoTotal(TypedDict):
    archivos: list[str]
    limite_bytes: int
    recibido_bytes: int


Contexto = ... | ContextoTamanoTotal          # el sexto miembro de la unión


class ErrorTamano(ErrorTipificado):
    tipo = TipoError.TAMANO
    contexto: ContextoTamano | ContextoTamanoTotal   # V8: la anotación se ensancha

    def __init__(self, *, archivo: str, limite_bytes: int, recibido_bytes: int) -> None: ...
    #   ^ sin cambios: ADR 0014 fija esta forma verbatim para el caso de un solo archivo

    @classmethod
    def total(cls, *, archivos: list[str], limite_bytes: int, recibido_bytes: int) -> ErrorTamano:
        error = cls(archivo="", limite_bytes=limite_bytes, recibido_bytes=recibido_bytes)
        error.contexto = ContextoTamanoTotal(
            archivos=archivos, limite_bytes=limite_bytes, recibido_bytes=recibido_bytes
        )
        return error
```

| Option | Tradeoff | Verdict |
|---|---|---|
| A sixth `TipoError` value | Reopens ADR 0014, which inherited authority closes | Rejected — settled |
| A `"(total)"` sentinel in `ContextoTamano.archivo` | Keeps one shape, but encodes a second meaning in a free-text field and breaks ADR 0014's verbatim shape by convention rather than by type | Rejected — settled in the proposal's question round |
| A new `ErrorTamanoTotal(ErrorTamano)` subclass | Cleanest construction, no placeholder — but two classes for one `TipoError`, and the proposal chose the `ErrorContenido.columna_faltante` classmethod pattern | Rejected: consistency with the shipped pattern outweighs one discarded argument |
| **`ErrorTamano.total()` classmethod** | `archivo=""` is constructed and immediately overwritten — one throwaway line, chosen over `cls.__new__` magic or an `__init__` that branches on which of two mutually exclusive arguments was passed. No invalid state escapes the method | **Chosen** |

`_ESTADO_HTTP` is untouched: both cases are `TipoError.TAMANO` → 422. The declared-uncompressed-size
failure uses the plain `ErrorTamano.__init__`, with `archivo` naming the offender, `limite_bytes` the
budget and `recibido_bytes` the declared size.

## 7. Sequence — the new `recibir()`

```
Cliente   Borde    Starlette      recibir()          validaciones      reservar()   disco
   │        │      (multipart)        │                    │               │          │
   ├─POST──►│                         │                    │               │          │
   │        ├──token ok──────────────►│                    │               │          │
   │        │      ┌──────────────────┴──────────────┐     │               │          │
   │        │      │ H-09: spool COMPLETO, sin cota, │     │               │          │
   │        │      │ a disco de SO (V2, V3). Abierto │     │               │          │
   │        │      └──────────────────┬──────────────┘     │               │          │
   │        │                         ├──[UploadFile]─────►│               │          │
   │        │                         │                    │               │          │
   │  ══ FASE 1 — sin `reservar()`, sin un solo byte escrito ══             │          │
   │                                  │  obtener_contrato  │               │          │
   │◄─── 500 clave_inexistente ───────┤  None (V4)         │               │          │
   │                                  ├───────────────────►│ validar_cantidad
   │◄─── 422 cantidad ────────────────┤◄── ErrorCantidad ──┤               │          │
   │                                  ├───────────────────►│ validar_formato   (×n)
   │◄─── 422 formato ─────────────────┤◄── ErrorFormato ───┤               │          │
   │                                  ├───────────────────►│ validar_tamano    (×n, si carga.size)
   │◄─── 422 tamano ──────────────────┤◄── ErrorTamano ────┤               │          │
   │                                  ├───────────────────►│ validar_tamano_total
   │◄─── 422 tamano (total) ──────────┤◄─ ErrorTamano.total┤               │          │
   │                                  │                    │               │          │
   │  ══ FASE 2 — dentro de `with reservar()`; el `finally` del ítem #6 cubre todo ══  │
   │                                  ├────────────────────┼──mkdtemp─────►│          │
   │                                  ├─ _copiar(limite) ──┼───────────────┼─entrada_i►
   │◄─── 422 tamano (aborto) ─────────┤  corta al cruzar el límite; cierra el handle,
   │                                  │  después levanta ─► finally: limpiar()
   │                                  ├─ total medido ─────┼───────────────┼──────────┤
   │◄─── 422 tamano (total medido) ───┤                    │               │          │
   │                                  ├───────────────────►│ validar_tamano_descomprimido
   │◄─── 422 tamano (zip bomb) ───────┤◄── ErrorTamano ────┤  sólo central directory (V10)
   │                                  │                    │               │          │
   │                                  ├─ [ArchivoEntrada] ─► costura de los ítems #9/#10
   │                                  │   raise NotImplementedError (inalcanzable hoy, V4)
```

Every arrow back to the client passes through the shipped ADR 0018 handler, and every one of them in
phase 2 passes through `finally: reserva.limpiar()` first (V9).

**Two totals, deliberately.** The declared pre-pass in phase 1 runs **only** when every part reported
a `size`; one `None` disables it and the measured post-copy total becomes the sole authority. The
measured total is re-checked after **each** file's copy, so the (n+1)th file is never copied once the
batch is already over budget. The pre-pass is an optimisation; the measured check is the contract.

## 8. File changes

| File | Action | Description |
|---|---|---|
| `app/core/validaciones.py` | Create | Five functions plus `PRESUPUESTO_DE_RAM_BYTES` (§4, §5). Stdlib + `app.core.{contrato,errores,tipos}` only |
| `app/recepcion.py` | Modify | Two-phase reordering (§2); `_copiar` gains `limite_bytes` (§3); the `del entradas` seam becomes the real consumption; docstring records the reordering |
| `app/core/errores.py` | Modify | `ContextoTamanoTotal`, the union member, the widened `ErrorTamano.contexto` annotation, `ErrorTamano.total()` (§6) |
| `adrs/0021-validaciones-de-contrato-y-presupuesto-de-memoria.md` | Create | §10. Number verified against disk (V7), **not** 0016 |
| `tests/test_validaciones.py` | Create | Unit tests over the five functions plus the budget boundary (§9) |
| `tests/test_recepcion.py` | Modify | **Restructured** (V5): a contract-injection fixture, existing reception assertions rebuilt on top of it, plus the five failure axes and the ordering regression |
| `tests/test_errores_tipificados.py` | Modify | `ErrorTamano.total()` → 422 body; `ContextoTamano`'s ADR-0014 shape pinned as a regression guard. **The proposal omits this file**; §13 prices it |
| `app/core/temporales.py` | **Untouched** | Zero lines. The mechanical proof that item #6's guarantee is unmodified (§2) |
| `app/core/contrato.py` | **Untouched** | Zero lines. ADR 0013's deviation module stays closed (proposal Decision 3) |

## 9. Testing strategy

Behavioural only. No AST/structural tests, no chaos tests, no perturb-and-restore.

| Layer | What to test | Approach |
|---|---|---|
| Unit | Each of the five functions accepts at the boundary and rejects one past it | Hand-built `ContratoProcesador`; no HTTP, no disk except the zip cases |
| Unit | Each rejection carries the right `tipo` and a fully populated context | Assert on `exc.contexto` as a whole dict, not field by field |
| Unit | `validar_tamano_total` populates `ContextoTamanoTotal.archivos` with every name in the batch | Three files, sum over the limit |
| Unit | A ZIP declaring a huge uncompressed size is rejected **without decompressing** | Build a small ZIP whose central directory declares far more than a tiny `presupuesto_bytes` |
| Unit | A non-ZIP file and a corrupt ZIP are both **no-ops** | Plain bytes, and ZIP-magic-with-garbage |
| Unit | `_copiar` aborts at `limite_bytes`, reports the real count, and leaves a closed handle | Direct call with an oversized `BytesIO`; assert the partial file can be deleted immediately (the Windows-handle property, §3) |
| Unit | `_copiar` without a ceiling breach is byte-identical to today | Regression guard on item #6's shipped behaviour |
| Integration | With an injected contract, an accepted upload still writes `entrada_0` verbatim | Contract-injection fixture; item #6's V5 assertions rebuilt on it |
| Integration | Each of the five failure axes returns 422 with the exact body | Full-body equality, the `tests/test_recepcion.py` convention |
| Integration | **The ordering regression** — a rejected batch writes nothing | Assert the per-request directory never existed for phase-1 failures, and holds only the files copied before the abort for phase-2 ones |
| Integration | An unknown key still returns 500 `clave_inexistente`, now **before** any write | The shipped assertion, plus "no directory was created" |
| Integration | Zero temporaries remain after every failure path | Assert the dedicated root has no `pet-*` children |
| Static | Whole change | `uv run ruff check . && uv run ruff format --check . && uv run mypy app tests` |

**The contract-injection fixture is the load-bearing piece**, decided here so `tasks` does not
improvise three variants of it: monkeypatch `app.core.contrato._TABLA_CONTRATOS` with a
`MappingProxyType` built from `CONTRATO_POR_DEFECTO`, adjusted per test. Patching the table rather
than `obtener_contrato` keeps the real function — and its `None` semantics — in the path under test.
This mirrors how `tests/test_recepcion.py` already monkeypatches `temporales.Reserva.limpiar`.

## 10. ADR 0021 — yes, and why

**Decision: write it.** `adrs/0021-validaciones-de-contrato-y-presupuesto-de-memoria.md`, MADR
matching siblings 0011–0020, neutral professional Spanish, sections Estado / Contexto / Decisión /
Alternativas consideradas / Consecuencias. `tasks` schedules the writing; this design does not create
the file.

The test for "does this warrant an ADR" in this repository is whether a future reader would otherwise
have to reconstruct a decision from archaeology. Three qualify:

1. **The union grows while the enum stays closed.** ADR 0014 is the standing authority that closes the
   error vocabulary. Someone diffing `errores.py` against ADR 0014 will see a sixth `Contexto` member
   and a widened annotation and must be able to find, in one place, that the **enum member set** is
   what 0014 closed and **context payloads** were never in that scope. Without this ADR, the next
   change either re-litigates it or quietly opens the enum.
2. **H-09 is deliberately left open.** A bounded copy was chosen, `max_part_size` was rejected **on
   evidence** (V2), and the ASGI middleware was scoped out. That is a decision with a rejected
   alternative and a live consequence for item #8 — precisely what ADR 0020 recorded about H-02's
   accepted degradation.
3. **The RAM budget is worker-level, not per-processor.** This constrains items #12/#16: a processor
   that needs a different ceiling triggers a second, deliberate design change rather than a field edit.

Outline:
- **Contexto** — the `app/recepcion.py:95` seam; `ContratoProcesador`'s four limits with no
  enforcement point; H-04 (Crítico, open) and H-09 (Advertencia, open); ADR 0014's closed enum;
  V1–V3 carried verbatim so the RAM/disk distinction is not re-derived by recall.
- **Decisión** — two phases around `reservar()` (§2); a bounded `_copiar` justified by V1's corrected
  rationale (§3); `validaciones.py` takes primitives and no Starlette type (§4);
  `PRESUPUESTO_DE_RAM_BYTES = 256 MB` as a module `Final` (§5); union grows, enum does not (§6).
- **Alternativas consideradas** — `request.form(max_part_size=...)` (rejected on evidence, V2); an
  ASGI byte-counting middleware (deferred: the only mechanism that closes H-09, out of scope by the
  user's explicit decision); a sixth `TipoError` value (rejected: ADR 0014); a `"(total)"` sentinel in
  `ContextoTamano.archivo` (rejected: encodes meaning in free text); an `ErrorTamanoTotal` subclass
  (rejected: two classes for one `TipoError`); a `ContratoProcesador` RAM field (rejected: ADR 0006
  heritage, and it would reopen ADR 0013's deviation module).
- **Consecuencias** — H-09 stays declared open and the exposed resource is named as OS temp disk, not
  RAM; H-04 gets a first line of defense only, with item #8 owning the ceiling; the production route
  no longer writes anything for an unknown key, so reception coverage now depends on an injected
  contract; 256 MB is a choice with a sourced floor and moves if a real processor contradicts it; a
  non-ZIP or corrupt-ZIP input is a deliberate no-op on this axis.

## 11. Threat matrix

This change modifies neither routing nor shell/subprocess/VCS surfaces — it reorders the body of a
route that already exists. The reference matrix's VCS/PR rows are all N/A; the boundaries actually
touched are below them.

| Boundary | Applicability | Design response | Planned test |
|---|---|---|---|
| Documentation-like paths | N/A — classifies no file by content type | — | — |
| Git repository selection / commit / push / PR commands | N/A — no VCS or PR automation anywhere in this change | — | — |
| Shell / subprocess | N/A — item #8 owns the child process; nothing here spawns one | — | — |
| New or modified route surface | N/A — no route added, removed or renamed; the shipped pin in `tests/test_seguridad_token.py` is unchanged | — | — |
| Path traversal from a client-supplied filename | **Applicable** | Unchanged from item #6 and preserved by the reordering: `nombre_original` never reaches a `Path()`; disk names stay `entrada_{indice}`. `validar_formato` compares an already-extracted string and never touches the filesystem | Hostile-name cases kept in the restructured `tests/test_recepcion.py` |
| Parsing an attacker-controlled archive | **Applicable** | Central directory only, never decompressed (V10); `BadZipFile` and non-ZIP are no-ops, so a malformed archive cannot drive an unexpected code path | Corrupt-ZIP and non-ZIP no-op tests; declared-size rejection without decompression |
| Unbounded resource growth from uploads | **Applicable, partially closed by design** | Bounded second copy plus per-file, batch and declared-uncompressed ceilings. Starlette's first spool stays unbounded (V2, V3) — H-09 open, on record | `_copiar` abort test; the five failure axes; the "rejected batch writes nothing" regression |
| Attacker-controlled number driving an allocation decision | **Applicable** | `ZipInfo.file_size` is treated as a **declaration**, compared against a budget, and never used to size a buffer or preallocate | Declared-size test asserts rejection, not allocation |
| Secret leakage into responses or logs | **Applicable** | Every new response body is a typed-error context containing only filenames and byte counts; no request data and no token is logged | Sentinel-token assertion extended across the new 422 paths |

## 12. Migration / rollout

No migration, no schema, no persisted state, no feature flag. Rollback is a code revert, per slice:
drop the phase split and restore the unconditional loop in `app/recepcion.py`; delete
`app/core/validaciones.py`; revert `app/core/errores.py`'s purely additive union member; revert
`adrs/0021`. Nothing depends on `ContextoTamanoTotal` outside this change, so reverting it removes one
union member and breaks no caller. Nothing on disk needs cleaning afterwards.

## 13. Review budget forecast

The proposal estimated ~690–880 and warned that this project's last five design-phase forecasts ran
30–50% short, always through the test file (`openspec/config.yaml`: 419 / ~500 / 419 / 277 / ~460
delivered). Three corrections are applied below rather than repeated as a warning:

1. **Test rows carry a +40% correction already applied**, the same convention item #6's design used.
   `tasks` must not apply it a second time.
2. **`tests/test_recepcion.py` counts deletions.** V5 shows it is restructured, not extended — the
   243-line shipped file has three assertions that stop being reachable. `additions + deletions` is
   the metric, so the proposal's 150–200 is low.
3. **`tests/test_errores_tipificados.py` was missing from the proposal entirely.** It is 219 lines
   today and must pin both the new `total()` path and ADR 0014's verbatim shape.

| Artifact | Est. changed lines |
|---|---|
| `app/core/validaciones.py` | 150–190 |
| `app/recepcion.py` (reorder + bounded `_copiar`, incl. deletions) | 75–95 |
| `app/core/errores.py` | 30–40 |
| `adrs/0021-*.md` | 95–120 |
| `tests/test_validaciones.py` (corrected) | 240–300 |
| `tests/test_recepcion.py` (corrected, incl. deletions) | 200–250 |
| `tests/test_errores_tipificados.py` (corrected) | 40–60 |
| **Total (authored)** | **830–1055** |

**Well over the 600-line budget — chained PRs are warranted**, and a real three-slice chain exists.
The seams are genuine: the error vocabulary is a precondition of the validation module, which is a
precondition of the route that calls it.

| Slice | Contents | Est. | Independently green? |
|---|---|---|---|
| **A1** | `app/core/errores.py`, `tests/test_errores_tipificados.py`, `adrs/0021` | ~165–220 | Yes — purely additive vocabulary plus the ADR that justifies it. No caller yet, no route change |
| **A2** | `app/core/validaciones.py`, `tests/test_validaciones.py` | ~390–490 | Yes — the module exists and is unit-proven against hand-built contracts; nothing calls it, so no shipped behaviour moves |
| **B** | `app/recepcion.py`, `tests/test_recepcion.py` | ~275–345 | Yes — wires A2 into the seam; the reordering and its regression land together, which is the only way the V5 restructure is reviewable |

All three sit under the 600-line budget with room. Splitting B further is **not** advisable: the
reordering and the test restructure that proves it must land in one diff, or the reviewer sees
assertions deleted with no replacement. `sdd-tasks` owns the formal guard lines (`Decision needed
before apply`, `Chained PRs recommended`, `600-line budget risk`) and the final
chained/`size:exception` recommendation.

## 14. Open questions

- [x] **Spec reconciliation — success criterion 3.** The proposal stated `recibido_bytes` must equal
      "the bytes actually copied before the bounded `_copiar` aborts, never the full file size". V1
      shows the pre-check normally fires first with `recibido_bytes = carga.size`, which **is** the
      full file size — truthfully measured, at zero disk cost. **Resolved 2026-08-19**: the proposal's
      Scope, Decision 1/2 and success criterion 3 were corrected, and the `contract-validation` /
      `temp-file-reception` deltas now state both paths — the pre-check reports the measured
      `carga.size` with zero bytes written; the bounded copy reports the real count and is the sole
      enforcement when `size` is `None`.
- [ ] **`ContratoProcesador.activo` is still unenforced.** The field exists, `CausaFila` already
      contains `"fila_inactiva"`, and both are unreachable today. Applying it here would be two lines,
      but it is outside the proposal's scope, which lists exactly five axes. Named rather than
      silently added or silently omitted — a reviewer will see it sitting next to the four limits this
      change **does** apply. Recommend a scope decision above this design.
- [ ] **The declared-uncompressed sum is per-archive, not per-batch** (§4). Moot while
      `entradas_max = 1`; it becomes real the first time a contract accepts more than one file.
- [ ] **256 MB is a choice with a sourced floor** (§5), not a requirement. It moves the moment a real
      processor's payload contradicts it, and only then does promoting it to `Configuracion` stop
      being speculative.
- [ ] **H-09 stays declared open** by explicit user decision and **H-04 stays partially open** by
      design. Neither is a question this design may resolve; both are recorded in ADR 0021's
      Consecuencias so they are discoverable from the decision record, not only from this file.

## 15. Environment blocker recorded during this phase — resolved

The `L:` volume ran out of space while `design.md` was first written: §0–§6 landed, §7–§15 did not,
and any further rewrite of the file failed with ENOSPC. The complete text lived in Engram
(`sdd/validaciones-de-contrato-y-defensa-de-memoria/design`) throughout. **Resolved 2026-08-19**: the
repository was migrated to `T:\API-Portal`, `uv sync` re-ran, the 134 shipped tests are green, and
§7–§15 were appended here from the Engram copy. The stray `.write-probe` file did not survive the
migration and no longer exists. Historical `L:\API-Portal\...` paths in §0's evidence column record
where those bytes were read at the time; the live checkout is `T:\API-Portal`. `L:\App_Portal` is
unrelated to this and is untouched.
