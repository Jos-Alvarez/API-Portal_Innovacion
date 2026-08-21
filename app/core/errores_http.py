"""Borde HTTP del contrato de errores tipificados (ADR 0014, ítem #3).

**Separado de `app/core/errores.py` por el ítem #17, y por una razón medida.**
El vocabulario de errores lo necesita todo el mundo, incluido el proceso hijo
de `spawn`, que lo alcanza por `app/core/interfaz.py`. El mapa a códigos HTTP
y su manejador los necesita **sólo el proceso padre**, una vez, al construir
la aplicación.

Mientras convivieron en un archivo, importar el vocabulario arrastraba
FastAPI y Starlette, y el hijo pagaba ese import en cada petición (ADR 0012
reimporta el árbol entero por ejecución): ~470 ms medidos, en
`MEDICIONES.md`. Ahora `app/core/errores.py` es biblioteca estándar pura y
este módulo es el único de la pareja que sabe qué es una respuesta HTTP.

Lo que NO cambió: los cinco tipos siguen siendo un conjunto cerrado, el mapa
sigue teniendo una entrada por miembro del enum y el manejador se sigue
cableando en `crear_app()` con `registrar_manejador_errores`. La partición es
de dependencias, no de contrato.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.errores import ErrorTipificado, TipoError

_ESTADO_HTTP: Final[Mapping[TipoError, int]] = MappingProxyType(
    {
        TipoError.FORMATO: 422,
        TipoError.TAMANO: 422,
        TipoError.CONTENIDO: 422,
        TipoError.CANTIDAD: 422,
        TipoError.CLAVE_INEXISTENTE: 500,  # ADR 0018
    }
)


def responder_error_tipificado(request: Request, exc: Exception) -> Response:
    if not isinstance(exc, ErrorTipificado):  # V4: la firma debe ser `Exception`
        raise exc
    return JSONResponse(
        status_code=_ESTADO_HTTP[exc.tipo],
        content={"tipo": exc.tipo.value, "contexto": exc.contexto},
    )


def registrar_manejador_errores(app: FastAPI) -> None:
    app.add_exception_handler(ErrorTipificado, responder_error_tipificado)  # V2, V3
