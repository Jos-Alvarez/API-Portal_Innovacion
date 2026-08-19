"""Objetivos de hijo deliberados para probar la plomería de S3 (ítem #8).

Todos son funciones a nivel de módulo -- picklables por nombre calificado,
la precondición de `spawn` sobre cualquier `target` de `Process` (ADR 0012).
`tests/` y `tests/ayudas/` son paquetes reales y `spawn` propaga `sys.path`
al hijo, así que estos objetivos son importables por un hijo spawneado sin
ningún gancho de producción (design.md V10).

La muerte anómala se simula de forma portable con `os._exit(N)`: esto prueba
el manejo del `exitcode`, no una condición real de OOM -- dicho honestamente
en vez de reclamar cobertura de OOM que esta suite no tiene.
"""

from __future__ import annotations

import os
import time
import traceback
from multiprocessing.connection import Connection

from app.core.ejecucion import ErrorDelHijo, ExcepcionDelHijo, SalidaDelHijo
from app.core.errores import ErrorCantidad


def hijo_normal(conexion: Connection) -> None:
    """Completa de inmediato y envía una `SalidaDelHijo` sin archivos."""
    conexion.send(SalidaDelHijo(archivos=[]))
    conexion.close()


def hijo_que_cuelga(conexion: Connection) -> None:
    """No envía nada y no termina por sí solo: fuerza el camino de timeout."""
    time.sleep(3600)


def hijo_exit_anomalo(conexion: Connection) -> None:
    """Sale con `os._exit(3)`, sin escribir nada en el `Pipe`.

    `os._exit` es portable; lo que NO es real es una condición de memoria
    agotada -- esto prueba únicamente la clasificación del `exitcode`.
    """
    os._exit(3)  # noqa: SLF001 - salida deliberada sin limpieza, es el punto de esta prueba


def hijo_silencioso(conexion: Connection) -> None:
    """Sale limpio (código 0) sin escribir nada en el `Pipe`.

    Distinto de `hijo_exit_anomalo`: prueba la fila "salida limpia sin
    mensaje" de la tabla de `clasificar_desenlace` (design.md §6), que
    también clasifica como `ANOMALO` -- un exitcode 0 sin mensaje no basta.
    """
    conexion.close()
    os._exit(0)  # noqa: SLF001 - ver docstring


def hijo_que_lanza(conexion: Connection) -> None:
    """Levanta una excepción sin tipificar y envía `ExcepcionDelHijo` con su
    traceback -- lo que un objeto de excepción vivo no puede garantizar al
    cruzar el `Pipe` (design.md §5)."""
    try:
        raise RuntimeError("fallo deliberado del módulo, sin tipificar")
    except RuntimeError as exc:
        conexion.send(
            ExcepcionDelHijo(
                clase=type(exc).__name__,
                mensaje=str(exc),
                traza=traceback.format_exc(),
            )
        )
    conexion.close()


def hijo_que_envia_error_tipificado(conexion: Connection) -> None:
    """Envía un `ErrorTipificado` real: prueba que el `__reduce__` de S1
    (`app/core/errores.py`) hace sobrevivir el pickle a través del `Pipe`."""
    conexion.send(ErrorDelHijo(error=ErrorCantidad(minimo=1, maximo=5, recibido=0)))
    conexion.close()
