"""Tipos portadores de archivo (ADR 0006, ítem #4 del backlog).

`ArchivoEntrada` y `ArchivoSalida` son las formas de dato que cruza el
`Procesador` (`app/core/interfaz.py`): entrada leída de disco, salida
propuesta para escribirse. Ambas son `frozen=True, slots=True` — sólo
`str`/`int`/`Path`, sin manejadores de archivo ni sockets, para que crucen
sin problema el límite de proceso futuro del ítem #8 (ADR 0012).

Este módulo importa únicamente la biblioteca estándar; no importa nada de
`app/procesadores/` (invariante de ADR 0011).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ArchivoEntrada:
    """Un archivo de entrada ya leído de disco, listo para validar/procesar."""

    nombre_original: str
    ruta_temporal: Path
    tamano_comprimido: int
    formato: str


@dataclass(frozen=True, slots=True)
class ArchivoSalida:
    """Un archivo de salida propuesto por `Procesador.procesar`."""

    nombre_propuesto: str
    ruta_temporal: Path
    tipo_mime: str
