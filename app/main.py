"""Fábrica de la aplicación y ciclo de vida de arranque (D3/D5 del diseño).

Orden de arranque: `app/__init__.py` ya fijó `spawn` antes de que este
módulo pudiera importarse (ver `app/arranque.py`). Todo lo que sigue va
DESPUÉS de la verificación de configuración, para que un token faltante
falle siempre primero y una caída de base de datos nunca pueda enmascarar
un error de configuración.
"""

from __future__ import annotations

from fastapi import APIRouter, FastAPI
from starlette.middleware import Middleware
from starlette.routing import Mount

from app.core.errores import registrar_manejador_errores
from app.core.seguridad import AutenticacionDeBorde, registrar_manejador_401
from app.core.temporales import ciclo_de_vida
from app.core.validacion_http import registrar_manejador_validacion
from app.salud import router_salud


def crear_app() -> FastAPI:
    # `ciclo_de_vida` (app/core/temporales.py) llama primero a
    # `obtener_configuracion()` -- 1. falla cerrado; ADR 0012 paso 2 --,
    # antes de tocar la raíz de temporales o el barrendero.
    app = FastAPI(lifespan=ciclo_de_vida)
    # costura #5:  motor = obtener_motor()  (dentro de app.core.temporales.ciclo_de_vida)
    # costura #11: contrastar_registry_contra_bd(motor, registry)
    # costura: cierre ordenado del motor (ítem #5)
    app.include_router(router_salud)  # público, sin dependencias
    registrar_manejador_401(app)  # ítem #2, cableado en producción (design.md §3)
    registrar_manejador_validacion(app)  # ítem #6, obligación 2 (design.md §4)
    registrar_manejador_errores(app)  # ítem #3, cableado en producción (supera design.md §12)
    # Frontera autenticada: cualquier ruta de procesador vive dentro de este
    # montaje, nunca fuera de él. No hay lista de rutas en ningún lugar
    # (ADR 0016, ADR 0019); la pertenencia es el registro dentro del router.
    router_interno = APIRouter()
    app.router.routes.append(
        Mount("/interno", app=router_interno, middleware=[Middleware(AutenticacionDeBorde)])
    )
    return app


app = crear_app()
