"""Paquete de procesadores concretos (ADR 0011, ítem #12 del backlog).

Un subpaquete autocontenido por procesador, como fija el árbol de ADR 0011.
La dependencia es unidireccional: `procesadores/` conoce `core/`; `core/` no
sabe que `procesadores/` existe.

**Este archivo no importa ningún procesador, y no debe hacerlo.** El alta de
un procesador es una entrada en el literal de `app/registry.py` y nada más:
importar acá para "auto-registrar" convertiría este paquete en un efecto de
importación, exactamente lo que `app/core/interfaz.py` prohíbe — el proceso
hijo de ADR 0012 (`spawn`) reimporta el árbol de módulos entero antes de
buscar su `Procesador` en `REGISTRY`.
"""
