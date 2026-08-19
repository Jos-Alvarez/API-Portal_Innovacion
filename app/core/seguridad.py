"""Token de servicio: autenticación por `Authorization: Bearer` (ítem #2).

Objetivo de diseño (design.md §1): la indistinguibilidad entre las ocho
variantes de rechazo es una propiedad del sistema de tipos y del flujo de
control, no de siete `return` que coinciden hoy por casualidad. Todo el
análisis vive en predicados `bool` (un canal de un bit), hay exactamente un
sitio de `raise` y exactamente un sitio de construcción de `Response`.

`registrar_manejador_401` se cablea en `crear_app()` (ítem #6, design.md §3).
`AutenticacionDeBorde` es el middleware ASGI de la frontera autenticada del
montaje `/interno` (ítem #6, design.md §2; ADR 0019): decide con
`scope["headers"]` y nada más, nunca llama a `receive()`, así que el 401 sale
antes de que exista un solo byte de cuerpo.
"""

from __future__ import annotations

import hmac
from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.configuracion import obtener_configuracion

_CABECERAS_401: Final[Mapping[str, str]] = MappingProxyType({"WWW-Authenticate": "Bearer"})


class TokenInvalido(Exception):
    """Sin campos y sin argumentos: no puede transportar el motivo del rechazo."""

    __slots__ = ()


def responder_token_invalido(request: Request, exc: Exception) -> Response:
    # Único lugar del repositorio donde se construye la respuesta 401.
    return Response(status_code=401, headers=dict(_CABECERAS_401))


def registrar_manejador_401(app: FastAPI) -> None:
    app.add_exception_handler(TokenInvalido, responder_token_invalido)


def _credencial_presentada(request: Request) -> str | None:
    match request.headers.getlist("authorization"):
        case [unico]:
            esquema, espacio, credencial = unico.partition(" ")
        case _:  # ausente, o repetida
            return None
    if esquema.lower() != "bearer" or espacio != " " or credencial == "":
        return None  # esquema erróneo, sin espacio, credencial vacía
    return credencial


def _coincide(presentado: bytes, esperado: bytes) -> bool:
    return hmac.compare_digest(presentado, esperado)


def _token_esperado() -> bytes:
    # ÚNICO desenvoltorio del secreto en todo el repositorio (ítem #13 lo verifica).
    # Una sola expresión: el str en claro nunca se liga a un nombre, así que no
    # existe ninguna variable que un logger o un f-string posterior pueda tomar.
    return obtener_configuracion().token_servicio.get_secret_value().encode("utf-8")


def _es_valida(request: Request) -> bool:
    credencial = _credencial_presentada(request)
    if credencial is None:
        return False
    return _coincide(credencial.encode("latin-1"), _token_esperado())


async def exigir_token(request: Request) -> None:
    """Cierra toda petición sin credencial válida. Único punto de rechazo."""
    if not _es_valida(request):
        raise TokenInvalido


class AutenticacionDeBorde:
    """Middleware ASGI del montaje autenticado (design.md §2.3; ADR 0019).

    Decide con `scope["headers"]` y nada más: nunca llama a `receive()`, así
    que el 401 sale antes de que exista un solo byte de cuerpo (PRD: "401
    antes de leer el cuerpo del request"). El `Request` que construye lleva
    el `receive` vacío por defecto, que *lanza* si alguien intenta leer: la
    imposibilidad de consumir el cuerpo es estructural, no una convención.

    No reimplementa la comparación: llama a `exigir_token`, el único sitio de
    `raise` del ítem #2. El `raise` se propaga al `ExceptionMiddleware` de la
    app exterior, que ya envuelve al `Router` -- por eso `TokenInvalido`
    sigue teniendo un único sitio de construcción de respuesta,
    `responder_token_invalido`, sin cambios.
    """

    __slots__ = ("app",)

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            await exigir_token(Request(scope))
        await self.app(scope, receive, send)
