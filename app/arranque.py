"""Fijación segura del método de arranque de procesos (ADR 0012).

Este módulo es intencionalmente el único invocado desde ``app/__init__.py``:
importar cualquier submódulo de ``app`` ejecuta el paquete primero (garantía
del lenguaje, no una convención), así que ningún camino de import puede
crear un proceso o una conexión antes de que ``spawn`` quede fijado.
"""

from __future__ import annotations

import multiprocessing

METODO_REQUERIDO = "spawn"


class ArranqueInseguroError(RuntimeError):
    """El método de arranque de procesos no pudo fijarse en spawn."""


def fijar_metodo_arranque() -> bool:
    """Fija ``spawn`` como método de arranque de procesos (ADR 0012).

    Idempotente: llamadas repetidas (Strict TDD reimporta ``app`` sin
    parar) nunca lanzan una excepción. ``set_start_method(force=True)`` no
    lanza en una llamada repetida (solo la variante no forzada lo hace), así
    que el guardado acá no es para evitar una excepción sino para mantener
    la llamada libre de efecto cuando ya está en el valor correcto.

    Devuelve ``True`` si el método cambió, ``False`` si ya estaba en
    ``spawn``.
    """
    actual = multiprocessing.get_start_method(allow_none=True)  # sin efecto secundario
    cambio = actual != METODO_REQUERIDO
    if cambio:
        multiprocessing.set_start_method(METODO_REQUERIDO, force=True)

    # Poscondición: convierte un futuro cambio de semántica en una falla de
    # arranque ruidosa en vez de una silenciosa.
    if multiprocessing.get_start_method() != METODO_REQUERIDO:
        raise ArranqueInseguroError(
            f"No se pudo fijar el método de arranque en {METODO_REQUERIDO!r}."
        )
    return cambio
