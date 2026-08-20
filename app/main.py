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

from app.core.ejecucion import AdmisionDeBorde, registrar_manejador_503
from app.core.errores import registrar_manejador_errores
from app.core.fallos_http import registrar_manejadores_de_fallo
from app.core.registro import configurar_logging
from app.core.seguridad import AutenticacionDeBorde, registrar_manejador_401
from app.core.temporales import ciclo_de_vida
from app.core.validacion_http import registrar_manejador_validacion
from app.recepcion import router_recepcion
from app.salud import router_salud


def crear_app() -> FastAPI:
    # Ítem #14, punto de entrada EXPLÍCITO del logging operativo. Va acá y no
    # a nivel de import de `app/core/registro.py`: `app/core/ejecucion.py` es
    # reimportado por cada hijo de `spawn` y garantiza no tener efecto de
    # importación, así que ningún módulo de esa cadena puede configurar
    # logging al importarse. `configurar_logging()` no lee `Configuracion`, de
    # modo que llamarla desde acá no rompe la convención de pereza (D3) aunque
    # este módulo construya `app` a nivel de módulo. Sin esta línea el ítem
    # entero sería un no-op: uvicorn no pone handler en la raíz ni le fija
    # nivel, así que un `app.*` en INFO no llegaría a ninguna parte.
    configurar_logging()
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
    registrar_manejador_503(app)  # ítem #8, mitad de admisión (design.md §3, §7)
    # ítem #10: las cuatro fallas no tipificadas del pipeline. Van por clase
    # concreta, nunca una sola sobre `FalloDeEjecucion` (ADR 0023).
    registrar_manejadores_de_fallo(app)
    # Frontera autenticada: cualquier ruta de procesador vive dentro de este
    # montaje, nunca fuera de él. No hay lista de rutas en ningún lugar
    # (ADR 0016, ADR 0019); la pertenencia es el registro dentro del router.
    # Orden de la lista: auth va primero -- V1 del design del ítem #8, `Mount`
    # aplica sus middlewares en orden inverso, así que la primera entrada
    # queda más externa y la admisión se evalúa después del token.
    router_interno = APIRouter()
    router_interno.include_router(router_recepcion)  # ítem #6, segunda mitad (design.md §4/§6)
    app.router.routes.append(
        Mount(
            "/interno",
            app=router_interno,
            middleware=[Middleware(AutenticacionDeBorde), Middleware(AdmisionDeBorde)],
        )
    )
    return app


app = crear_app()
