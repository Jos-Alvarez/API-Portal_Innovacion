"""Interfaz `Procesador` (ADR 0006, ítem #4 del backlog).

Objetivo de diseño (design.md §1-§2): `Procesador` es la costura que permite
extraer un procesador a su propio servicio (ADR 0006). Es un `ABC`, no un
`Protocol`, porque ADR 0006 fija la clase literalmente así y porque `ABC`
impone en tiempo de instanciación los dos métodos abstractos (design.md §2).

`clave` queda como anotación simple, sin `ClassVar` ni mecanismo de
exigencia (design.md §3) — la brecha queda documentada, no resuelta (ver
docstring de `Procesador`).

Este módulo importa `ErrorTipificado` de `app/core/errores.py` (ítem #3) y
los tipos portadores de `app/core/tipos.py`; no importa nada de
`app/procesadores/` (invariante de ADR 0011).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.core.errores import ErrorTipificado
from app.core.tipos import ArchivoEntrada, ArchivoSalida


class Procesador(ABC):
    """Interfaz común de los módulos de procesamiento (ADR 0006, verbatim).

    `validar` DEVUELVE el error tipificado; no lo levanta. Quien lo levanta es
    el pipeline (ítem #10), para que el manejador del ítem #3 lo serialice.
    Ambos métodos trabajan siempre con listas: un solo camino de código, sin
    ramas por cardinalidad (ADR 0006).

    RESUELTO — ítem #8, `core/ejecucion.py` (S4): el proceso hijo re-importa el
    árbol de módulos de la aplicación y busca su propia instancia en
    `REGISTRY` por `clave` (`app/core/ejecucion.py::_ejecutar_en_hijo`). Ninguna
    instancia de `Procesador` serializada cruza jamás la frontera del proceso:
    solo `clave` (`str`) y rutas de archivo lo hacen (ADR 0012). Esto obliga a
    que todo módulo de procesador concreto sea importable sin efectos de
    importación -- la misma precondición que `spawn` ya impone sobre
    `core/ejecucion.py`.

    `clave` es una anotación sin valor: ni mypy ni ABCMeta obligan a la subclase
    a definirla (design.md §0, V1/V2). Cada procesador DEBE fijarla y su valor
    DEBE coincidir con su llave en `REGISTRY`.
    """

    clave: str

    @abstractmethod
    def validar(self, archivos: list[ArchivoEntrada]) -> ErrorTipificado | None:
        """Valida el conjunto (cantidad, formato, tamaño, contenido); None si es válido."""

    @abstractmethod
    def procesar(self, archivos: list[ArchivoEntrada]) -> list[ArchivoSalida]:
        """Ejecuta la transformación y devuelve uno o más archivos resultantes."""
