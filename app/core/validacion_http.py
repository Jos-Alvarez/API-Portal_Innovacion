"""Rechazo de peticiones con forma inválida (ítem #6, design.md §4).

FastAPI instala por defecto un manejador para `RequestValidationError` que
responde `{"detail": [...]}` y hace eco del valor sometido (`input`), la
misma clase de fuga que los ítems #1 y #2 cerraron cada uno en su alcance.
Este módulo lo sobrescribe.

No amplía el vocabulario cerrado de ADR 0014 (cinco valores de `tipo`,
`app/core/errores.py`): ninguno de los cinco describe una petición cuya
*forma* nunca llegó a parsear -- describen fallas de *contenido* de una
petición ya aceptada. Inventar un sexto `tipo` para este caso reabriría un
enum que el propio contrato declara cerrado; ADR 0017 ya trazó la misma
frontera para el 401 (design.md §4.1). Por eso la respuesta es 422 con
cuerpo vacío: no hay envelope tipificado que decir, y un cuerpo vacío no
puede hacer eco de nada.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.requests import Request
from starlette.responses import Response


def responder_validacion_invalida(request: Request, exc: Exception) -> Response:
    # Sin cuerpo a propósito: ni `detail`, ni `tipo`, ni `contexto`. Nada que
    # hacer eco del valor rechazado ni del token (design.md §4.2).
    return Response(status_code=422)


def registrar_manejador_validacion(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, responder_validacion_invalida)
