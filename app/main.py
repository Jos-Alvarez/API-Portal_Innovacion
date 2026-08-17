"""Fábrica de la aplicación y ciclo de vida de arranque (D3/D5 del diseño).

Orden de arranque: `app/__init__.py` ya fijó `spawn` antes de que este
módulo pudiera importarse (ver `app/arranque.py`). Todo lo que sigue va
DESPUÉS de la verificación de configuración, para que un token faltante
falle siempre primero y una caída de base de datos nunca pueda enmascarar
un error de configuración.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.configuracion import obtener_configuracion
from app.salud import router_salud


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI) -> AsyncIterator[None]:
    obtener_configuracion()  # 1. falla cerrado; ADR 0012 paso 2
    # costura #5:  motor = obtener_motor()
    # costura #11: contrastar_registry_contra_bd(motor, registry)
    yield
    # costura: cierre ordenado del motor (ítem #5)


def crear_app() -> FastAPI:
    app = FastAPI(lifespan=ciclo_de_vida)
    app.include_router(router_salud)  # público, sin dependencias
    # costura #2: routers de procesadores con dependencies=[Depends(exigir_token)]
    # (nunca middleware global ni allow-list -- ver design.md D5)
    return app


app = crear_app()
