# Infraestructura de fixtures de paridad — BACKLOG item #15

| | |
|---|---|
| **Change** | `infraestructura-fixtures-paridad` |
| **BACKLOG item** | #15 — depends on #1; ADR 0015 |
| **Date** | 2026-08-20 |
| **Commits** | `0cb38e1`; refined by `332e274` (item #16) |
| **Branch** | `item-15/infraestructura-fixtures-paridad` |
| **Mode** | Fast cycle (exploration → implementation → verification) |

## Summary

The machinery item #16 consumes: manifest parsing and validation, `sha256`
verification, mandatory provenance, and the CI-vs-local gate. The real pairs
are financial extracts and live **outside** the repository (ADR 0015); the
repository stores only names, hashes and provenance.

## Exploration

Read ADR 0015 in full, `TECH-DESIGN.md`'s parity checklist, and
`app/core/configuracion.py` to decide where `FIXTURES_PARIDAD` belongs.

Findings:

- **The TOML shape in ADR 0015 parses exactly as written.** `[[contado_carga.pares]]`
  followed by `[contado_carga.pares.procedencia]` attaches the provenance to
  the last array element, and `generado_el` comes back as a native
  `datetime.date`. That made it possible to *require* a TOML date and reject a
  string — validation for free.
- **`FIXTURES_PARIDAD` is test-time configuration, not service configuration.**
  It does not belong in `Configuracion` (which is the service's startup
  contract); it belongs in `tests/paridad/`.
- **ADR 0015 states three rules with three different severities**, and the ADR
  is explicit that they are not interchangeable. That asymmetry became the
  core of the design.
- **There is no CI system**, so the "fails in CI" rule needs a signal. The
  conventional `CI` environment variable is the one GitHub Actions, GitLab CI,
  CircleCI and Jenkins all set unprompted.

## Implementation

- **`tests/paridad/manifiesto.py`** — dataclasses (`Procedencia`,
  `ParDeParidad`), `cargar_manifiesto()`, `resolver_raiz()`, `en_ci()` and the
  full gate `exigir_pares()`.
- **`tests/paridad/manifiesto.toml`** — shipped with the exact expected shape
  in a commented block.
- **README, "Parity fixtures"** — the procedure for registering a pair
  (hashing every file plus the exact `.py` that produced the output, observing
  the line ending instead of assuming it) and the severity table. ADR 0015 asks
  for this documentation twice, by name.

The three severities, implemented as three distinct outcomes:

| Situation | Local | CI |
|---|---|---|
| Malformed manifest, or incomplete provenance | **fail** | **fail** |
| Fixture present but `sha256` mismatch | **fail** | **fail** |
| Fixtures absent | skip, with a loud warning | **fail** |

The middle row is the one that matters: ADR 0015's barrier exists against
*tweaking the reference file until the test passes*. If that lifts on a
developer machine, it does not exist. "Fixture absent" means "I have no access
to the share"; "hash mismatch" is something else entirely.

**A fourth check was added that ADR 0015 does not enumerate**:
`FIXTURES_PARIDAD` may not point inside the repository. It is the only way a
configuration slip breaks the ADR's central promise — zero financial data in
Git history — *irreversibly*: put the share inside the working tree and one
`git add` carries it in.

The skip is loud on purpose: `warnings.warn` **plus** `pytest.skip`, so it
lands in the warnings summary rather than being one `s` in the dot line.

## Verification

- `tests/test_infraestructura_de_paridad.py` — 23 tests at the time of the
  commit (25 today, after item #16's refinement), all against synthetic
  manifests and fixture directories in `tmp_path`.
- Full suite at **366 passing**, 97 % coverage; `ruff` and `mypy --strict`
  clean.

Synthetic fixtures are deliberate, not a convenience: the real pairs are not
in this repository and cannot be, so machinery testable only against them
could never be tested — which is exactly the kind of infrastructure that
arrives broken on the day it is needed.

A pytest trap worth recording: **`pytest.warns` verifies nothing if an
exception passes through the block** — its `__exit__` skips the check when
`exc_type` is not `None`. Since `pytest.skip` raises, combining
`pytest.warns(...)` with `pytest.raises(...)` would have asserted the warning
vacuously. The tests use the `recwarn` fixture and assert after the
`pytest.raises`.

## Refinement forced by item #16

Item #16 was the first consumer and exposed a distinction the original design
collapsed: a section **declared empty** (`pares = []`) is "this processor
exists, its pairs are not ready" — absence of fixtures, so it skips locally
and fails in CI. A section **missing entirely** stays a hard failure
everywhere: that is a typo in the processor name, or a processor whose
manifest nobody wrote, and neither may skip.

Three tests in `test_infraestructura_de_paridad.py` had been pinned to the
shipped manifest being empty. They were moved to synthetic manifests: a test
tied to a transitory state of the repository starts passing for the wrong
reason the moment that state changes.
