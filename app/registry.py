"""Registro de procesadores (ADR 0011, ítem #4 del backlog).

Punto de unión deliberadamente fuera de `core/`: es la única excepción
legítima al invariante de ADR 0011 ("`core/` no sabe que `procesadores/`
existe"), porque el registro necesita conocer procesadores concretos que
`core/` nunca debe importar. Real, tipado y vacío hasta los ítems #12/#16.
"""

from __future__ import annotations

from app.core.interfaz import Procesador

REGISTRY: dict[str, Procesador] = {}
