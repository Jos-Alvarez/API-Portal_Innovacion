"""Contrato estático de procesador, sin base de datos (ítem #5 desviado; ADR 0013).

ADR 0013 fija que la fila `procesador` se lee en cada ejecución directamente
en SQL Server, vía SQLAlchemy Core sobre `pyodbc`, sin cache. Este módulo
**se desvía deliberadamente** de esa decisión para el caso de uso actual: no
hay instancia de SQL Server provista (prerrequisito #0, fuera de este
repositorio) y el caso de uso procesa el Excel subido directamente, sin
necesitar una fila por clave. La base de datos nunca fue el fin en sí misma
— era la fuente del contrato por clave que el ítem #7 aplica (cantidad de
archivos, formatos, tamaño por archivo y total). Este módulo conserva ese
contrato y sólo elimina la base: los valores pasan a vivir en código, en
`CONTRATO_POR_DEFECTO` y en la tabla `_TABLA_CONTRATOS`.

ADR 0013 no queda derogado: sigue describiendo el diseño de producción
previsto. Restaurar esa implementación significa reemplazar `obtener_contrato`
por una que consulte SQL Server (misma firma, mismo tipo de retorno) detrás
de esta función, sin tocar a quien la llama.

Este módulo importa únicamente la biblioteca estándar; no importa nada de
`app/procesadores/` (invariante de ADR 0011). No se elige llamarlo `db.py`
—el nombre que ADR 0013/TECH-DESIGN reservan para el futuro espejo de SQL
Server— precisamente porque no hay base de datos aquí: reutilizar ese nombre
confundiría este módulo con el que lo reemplazará, y la comprobación estática
de ADR 0011 ("`procesadores/` no importa `core.db`") queda libre para seguir
señalando ese nombre cuando el espejo real se implemente.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class ContratoProcesador:
    """Contrato de entrada/salida de un procesador (ADR 0006, fila `procesador`)."""

    entradas_min: int
    entradas_max: int
    formatos_aceptados: tuple[str, ...]
    tamano_max_bytes: int
    tamano_max_total_bytes: int
    activo: bool


# Ítem #5 (desviado): estos números no vienen de ningún documento ni fila de
# base de datos — son la elección conservadora de este cambio, revisable
# cuando se conozcan las necesidades de un procesador real (ver propuesta).
CONTRATO_POR_DEFECTO: ContratoProcesador = ContratoProcesador(
    entradas_min=1,
    entradas_max=1,
    formatos_aceptados=("xlsx",),
    tamano_max_bytes=25 * 1024 * 1024,
    tamano_max_total_bytes=25 * 1024 * 1024,
    activo=True,
)

# Tabla en código que sustituye la fila `procesador` de SQL Server (ADR 0013).
# Vacía a propósito: ningún procesador existe todavía (los ítems #12/#16 los
# añaden, igual que `app.registry.REGISTRY`). Una entrada futura se
# construiría a partir de `CONTRATO_POR_DEFECTO`, editado según ese
# procesador.
_TABLA_CONTRATOS: MappingProxyType[str, ContratoProcesador] = MappingProxyType({})


def obtener_contrato(clave_procesador: str) -> ContratoProcesador | None:
    """Devuelve el contrato de `clave_procesador`, o `None` si la clave no existe.

    `None` es una ausencia real, no un contrato permisivo o vacío: el ítem #7
    depende de límites verdaderos, y el ítem #3 ya define `clave_inexistente`
    para esta situación exacta — quien llama debe levantarlo, no inventar un
    contrato sin límites. No se accede a red ni a base de datos alguna.
    """
    return _TABLA_CONTRATOS.get(clave_procesador)
