# Proposal and Spec — Contrato estático sin base de datos

- **Change**: `contrato-estatico-sin-base-de-datos`
- **Replaces**: `BACKLOG.md` item #5 ("Espejo de solo lectura de SQL Server", ADR 0013)
- **Depends on**: items #3 and #4, archived and shipped
- **Ceremony**: minimal chain by user decision — this single artifact stands in for proposal, spec and
  design; implementation, verification and archive follow normally.
- **Methodology**: Strict TDD disabled.

## Why this change exists instead of item #5

The user's use case processes the uploaded Excel directly and needs no database lookup. Item #5's
SQL Server mirror is therefore unnecessary for it, and its external prerequisite (#0 — a provisioned
instance with a read-only account) is unresolved and outside this repository.

The database was never the point on its own: it was the **source of the per-key contract** that item
#7 enforces — file count, accepted formats, per-file and total size caps. Returning empty data would
not defer item #7, it would **disable** it, leaving no limits to apply and no signal that they are
missing. The anti-zip-bomb and RAM-ceiling defences of ADR 0012 and TECH-DESIGN step 4 depend on
those numbers existing.

So this change keeps the contract and drops only the database: the values move into code.

## Explicitly NOT in this change

- **No SQLAlchemy. No pyodbc. No database driver of any kind.** No new runtime dependency.
- No connection string, no pool, no engine, no `activo` lookup against a live row.
- No implementation of items #6–#12 or #16.
- ADR 0013 is **not** repealed. It still describes the intended production design; this change
  documents a deliberate deviation for the current use case, reversible by restoring a real reader
  behind the same function signature.

## What ships

A single module exposing the lookup that items #7 and #11 will call, backed by an in-code table.

### Requirement: A contract lookup exists with a database-free implementation
The service MUST expose a function that returns the contract for a processor key, and it MUST resolve
it without any network or database access.

#### Scenario: Lookup resolves offline
- GIVEN no database is reachable and no driver is installed
- WHEN the contract for a known key is requested
- THEN it is returned, and no connection of any kind is attempted

### Requirement: The contract carries real, enforceable limits
The returned contract MUST provide `entradas_min`, `entradas_max`, `formatos_aceptados`,
`tamano_max_bytes`, `tamano_max_total_bytes` and `activo`. None MAY be empty or absent, because item
#7 enforces each of them.

#### Scenario: Every field is populated
- GIVEN the contract returned for any key the table resolves
- WHEN its fields are inspected
- THEN each is present, and the numeric limits are greater than zero

### Requirement: An unknown key is distinguishable from a permissive default
Requesting a key the table does not hold MUST NOT silently yield an unlimited or empty contract. The
lookup MUST report the key as absent, so the caller can raise `clave_inexistente` as item #3's
contract already defines.

#### Scenario: Unknown key reports absence
- GIVEN a key not present in the static table
- WHEN its contract is requested
- THEN the lookup reports absence rather than returning a default

### Requirement: The default contract is defined in one editable place
The limit values MUST live in a single named constant so they can be changed in one edit, and the
module MUST record that no document fixes these numbers — the database rows did.

#### Scenario: Limits are centralised
- GIVEN the module source
- WHEN the limit values are located
- THEN they come from one named constant rather than being repeated per key

### Requirement: The deviation from ADR 0013 is recorded where it will be found
The module MUST state in its docstring that it deliberately replaces ADR 0013's read-only mirror, why,
and what restoring the database implementation would involve.

#### Scenario: The deviation is documented
- GIVEN the module docstring
- WHEN it is read
- THEN it names ADR 0013, the reason for the deviation, and the restoration path

## Chosen limit values — a decision, not a finding

`TECH-DESIGN.md` names the fields (`tamano_max`, `tamano_max_total`, `entradas_min`, `entradas_max`)
but fixes **no values** anywhere; they lived in each `procesador` row. Moving them into code forces a
choice. These are deliberately conservative and trivially editable:

| Field | Value | Reasoning |
|---|---|---|
| `entradas_min` / `entradas_max` | 1 / 1 | The stated use case is a single uploaded Excel |
| `formatos_aceptados` | `("xlsx",)` | Same |
| `tamano_max_bytes` | 25 MiB | Comfortably above a large spreadsheet, far below anything that threatens the RAM ceiling ADR 0012 cares about |
| `tamano_max_total_bytes` | 25 MiB | Equal to the per-file cap while cardinality is 1 |
| `activo` | `True` | Nothing to deactivate without an admin panel |

**No document supplies these numbers.** They are this change's choice and should be revisited when a
real processor's needs are known.

## Rollback

New file only, plus its tests. Nothing existing is modified and no dependency is added. Reverting the
commit restores the previous state exactly. Restoring item #5 later means reimplementing the same
function signature against a real reader — the callers do not change.
