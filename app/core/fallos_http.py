"""Traducción HTTP de las cuatro fallas no tipificadas del pipeline (ítem #10).

Cuatro excepciones pueden llegar al borde sin ser un `ErrorTipificado`:
`EjecucionExpirada`, `HijoMuerto` y `FalloDelModulo` de `app.core.ejecucion`
(ADR 0022) y `SalidaMalFormada` de `app.core.empaquetado` (ADR 0023).
Ninguna de las cuatro entra en el vocabulario de ADR 0014: `TipoError`
conserva exactamente cinco miembros y este módulo no agrega un sexto ni
reutiliza uno existente para describir algo que no describe.

Por eso la respuesta es un estado desnudo con cuerpo vacío, el patrón que ya
usan `responder_token_invalido` (401, `app.core.seguridad`) y
`responder_validacion_invalida` (422, `app.core.validacion_http`): un solo
lugar de construcción por código de estado, y nada que hacer eco de la falla.
En particular, la `traza` de `FalloDelModulo` **nunca** llega al cuerpo de la
respuesta (ADR 0022); es material de logging para el ítem #14.

Los manejadores se registran **por clase concreta**, nunca uno solo sobre
`FalloDeEjecucion` (ADR 0023). `SalidaMalFormada` está deliberadamente fuera
de esa jerarquía para que un bug de empaquetado no se reporte jamás como una
caída del módulo; colapsar los cuatro registros en uno borraría exactamente
esa distinción del código.

Este módulo importa `fastapi`/`starlette`, `app.core.ejecucion` y
`app.core.empaquetado`; no importa nada de `app/procesadores/` (invariante de
ADR 0011). Vive aparte de `app/core/pipeline.py` porque ese módulo tiene
prohibido nombrar un tipo de Starlette, y aparte de `empaquetado.py` porque
ese módulo no importa nada de HTTP.
"""

from __future__ import annotations

from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import Response

from app.core.ejecucion import EjecucionExpirada, FalloDelModulo, HijoMuerto
from app.core.empaquetado import SalidaMalFormada


def responder_ejecucion_expirada(request: Request, exc: Exception) -> Response:
    """Único lugar del repositorio donde se construye la respuesta 504.

    El plazo lo fija el servidor (`TIMEOUT_EJECUCION`), así que el cliente no
    provocó ni puede corregir este desenlace: 504 lo dice sin cuerpo.
    """
    return Response(status_code=504)


def responder_fallo_interno(request: Request, exc: Exception) -> Response:
    """Único lugar del repositorio donde se construye la respuesta 500 desnuda.

    Las tres fallas que llegan acá —el módulo se cayó, el hijo murió sin dejar
    un mensaje bien formado, o el conjunto de salidas está mal formado— son
    bugs de primera parte. El cuerpo vacío es deliberado: `FalloDelModulo`
    lleva `clase`, `mensaje` y `traza`, y ninguno de los tres sale al cliente.
    """
    return Response(status_code=500)


def registrar_manejadores_de_fallo(app: FastAPI) -> None:
    """Registra los cuatro manejadores, uno por clase concreta (ADR 0023)."""
    app.add_exception_handler(EjecucionExpirada, responder_ejecucion_expirada)
    app.add_exception_handler(FalloDelModulo, responder_fallo_interno)
    app.add_exception_handler(HijoMuerto, responder_fallo_interno)
    app.add_exception_handler(SalidaMalFormada, responder_fallo_interno)
