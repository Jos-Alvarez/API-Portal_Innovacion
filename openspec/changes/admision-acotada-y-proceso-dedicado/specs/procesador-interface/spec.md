# Delta for Procesador Interface

## Purpose

BACKLOG item #8. Resolves the open caveat `procesador-interface` (item #4) left addressed to this
item: how the child process obtains its `Procesador` instance. No behavioral change to the ABC's two
abstract methods, `ArchivoEntrada`/`ArchivoSalida`, or the registry.

## MODIFIED Requirements

### Requirement: `Procesador`'s docstring records the child-instantiation resolution
The class docstring MUST state that the child process re-imports the application module tree and
looks up its processor instance from `REGISTRY` by `clave`, and MUST state that a serialized
(pickled) `Procesador` instance never crosses the process boundary — only `clave` (a string) and
file paths do.
(Previously: the docstring stated that whether the child re-derives the processor instance or
receives a pickled live instance was undecided and belonged to item #8.)

#### Scenario: Docstring states the resolved decision
- GIVEN `Procesador.__doc__`
- WHEN read
- THEN it states that the child process re-imports and looks up the processor by `clave` via
  `REGISTRY`, and that no serialized `Procesador` instance ever crosses the process boundary
