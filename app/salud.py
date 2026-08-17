"""Health check público y sin base de datos (H-08, ver adrs/0016).

Independencia estructural, no por convención: este módulo importa
únicamente `fastapi`. Un scan AST en las pruebas (`tests/test_salud.py`)
verifica que ningún `app.*` aparezca acá. La exención de token de esta
ruta se expresa acotando la autenticación a los routers de procesadores
(ítem #2), nunca como una lista de excepciones agregada acá.
"""

from __future__ import annotations

from fastapi import APIRouter

router_salud = APIRouter()


@router_salud.get("/salud")
def obtener_salud() -> dict[str, str]:
    """Liveness-only: no prueba validez del token, alcance de SQL Server,
    coincidencia registry<->catálogo, ni que un procesador pueda ejecutar
    (ver adrs/0016).
    """
    return {"estado": "vivo"}
