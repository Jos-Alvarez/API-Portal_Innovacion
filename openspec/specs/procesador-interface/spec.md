# Procesador Interface Specification

## Purpose

BACKLOG item #4, authority ADR 0006 (inherited, verbatim ABC signature) and local ADR 0011
(placement). Defines the `Procesador` ABC, the `ArchivoEntrada`/`ArchivoSalida` carriers, and a
real-but-empty typed registry that item #10's pipeline looks processors up through. New domain —
no prior spec.

Out of scope: #5–#12, #16. No shipped file under `app/` is modified; nothing is wired into
`crear_app()`.

## Requirements

### Requirement: `Procesador` ABC matches ADR 0006 verbatim
`app/core/interfaz.py` MUST define abstract class `Procesador` with `clave: str` and two abstract
methods: `validar(self, archivos: list[ArchivoEntrada]) -> ErrorTipificado | None` and
`procesar(self, archivos: list[ArchivoEntrada]) -> list[ArchivoSalida]`, using `ErrorTipificado`
from `app/core/errores.py`. `validar` MUST return the error, never raise it.

#### Scenario: validar returns instead of raising
- GIVEN a concrete subclass whose `validar` rejects a file set
- WHEN `validar` is called with that set
- THEN it returns an `ErrorTipificado` and raises nothing

#### Scenario: validar returns None when valid
- GIVEN a concrete subclass whose `validar` accepts a file set
- WHEN called with that set
- THEN it returns `None`

### Requirement: `Procesador` is genuinely abstract
Direct instantiation of `Procesador`, and instantiation of a subclass implementing only one of
`validar`/`procesar`, MUST both fail.

#### Scenario: Direct or partial instantiation fails
- GIVEN `Procesador` itself, and a subclass implementing only one abstract method
- WHEN either is instantiated
- THEN both raise `TypeError`

### Requirement: Both methods take and return lists unconditionally
`validar` and `procesar` MUST accept `list[ArchivoEntrada]` with no branch on length — one element
and several elements go through the same call shape.

#### Scenario: One-element and multi-element lists both work
- GIVEN a concrete subclass
- WHEN `validar`/`procesar` are each called with a one-element and a multi-element list
- THEN both calls succeed and return the documented shape in both cases

### Requirement: `ArchivoEntrada`/`ArchivoSalida` are frozen, slotted, picklable carriers
`app/core/tipos.py` MUST define these as `@dataclass(frozen=True, slots=True)`:

| Type | Fields |
|---|---|
| `ArchivoEntrada` | `nombre_original: str`, `ruta_temporal: Path`, `tamano_comprimido: int`, `formato: str` |
| `ArchivoSalida` | `nombre_propuesto: str`, `ruta_temporal: Path`, `tipo_mime: str` |

Instances MUST pickle-round-trip to an equal value and MUST NOT hold an open file handle or
socket.

#### Scenario: Immutable and slotted
- GIVEN an instance of either type
- WHEN an existing field is reassigned, and separately when an undeclared attribute is assigned
- THEN the first raises `FrozenInstanceError` and the second raises `TypeError`

> Corrected during implementation, verified by execution on the pinned interpreter. An earlier draft
> expected `AttributeError`; a second draft explained the real `TypeError` as "the instance has no
> `__dict__`". Both were wrong. The observed error is:
>
> ```
> TypeError: super(type, obj): obj must be an instance or subtype of type
> ```
>
> The cause is that `@dataclass(slots=True)` cannot add `__slots__` to an existing class, so it builds
> a replacement class — while the frozen `__setattr__` generated beforehand still closes over the
> *original* class. Assigning an undeclared attribute falls through to that stale `super(cls, self)`
> call, where `self` is an instance of the replacement class and therefore not a subtype of the closed
> over one. The failure is in the `super()` lookup, not in attribute storage.
>
> Reassigning an existing field never reaches that path and raises `FrozenInstanceError`, which is
> itself a subclass of `AttributeError` — most likely where the original expectation came from.
>
> The test asserts the observed `TypeError`. What matters for this contract is that neither assignment
> succeeds; the mechanism is recorded only so nobody re-derives it from plausibility, as two drafts of
> this note already did.

#### Scenario: Pickle round-trip preserves equality
- GIVEN an instance of each type holding a `Path` value
- WHEN each is pickled then unpickled
- THEN the result equals the original

### Requirement: A concrete `Procesador` instance is registry-compatible
A concrete subclass instance MUST be assignable as a value in `dict[str, Procesador]`.

#### Scenario: Fake processor populates a typed registry
- GIVEN a test-only concrete instance and an empty `dict[str, Procesador]`
- WHEN it is assigned under a string key
- THEN the assignment succeeds and it is retrievable by that key

### Requirement: `app/registry.py` ships a real, empty, typed registry
`app/registry.py` MUST define `REGISTRY: dict[str, Procesador] = {}`, with no processor registered
by this change.

#### Scenario: Registry imports empty
- GIVEN `app/registry.py`
- WHEN imported and `REGISTRY` inspected
- THEN it is a `dict` with zero entries

### Requirement: `app/core/interfaz.py` does not depend on `app/procesadores/`
Per ADR 0011, `app/core/interfaz.py` MUST import cleanly with `app/procesadores/` absent.

#### Scenario: interfaz.py imports without procesadores present
- GIVEN an environment where `app/procesadores/` does not exist
- WHEN `app/core/interfaz.py` is imported
- THEN the import succeeds

### Requirement: `Procesador`'s docstring records the item #8 open question
The class docstring MUST state that whether the child process re-derives the processor instance or
receives a pickled live instance is undecided and belongs to item #8.

#### Scenario: Docstring states the open question
- GIVEN `Procesador.__doc__`
- WHEN read
- THEN it states the child-process instantiation strategy is undecided, owned by item #8

> **Requirement removed on 2026-08-18.** This slot held "Shipped application route set is
> unchanged", worded as *"**This change** MUST NOT add any route…"* with a scenario comparing
> `crear_app()` *"before and after **this change**"*. That wording was correct inside the originating
> change's delta, where "this change" had a referent. Promoted into this permanent domain spec it
> refers to nothing, and read as a standing invariant it became **false** when
> `borde-de-autenticacion-y-errores-http` deliberately added the `/interno` authentication mount.
>
> It was an assertion about one change's diff, not a property of this domain. The living invariant is
> `service-token-auth`'s "Shipped application route set changes deliberately, for the authentication
> boundary only", which names the current surface and is pinned by a test. Do not restore this
> requirement here.
