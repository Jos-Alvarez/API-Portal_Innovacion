"""Pruebas del manejador de `RequestValidationError` (ítem #6, design.md §4, §8 filas 6-7).

Router de pruebas: `crear_app_de_prueba()` vive únicamente en este módulo
(nunca en `app/`), igual que hicieron los ítems #2 y #3 -- el conjunto de
rutas embarcado ya está pinchado por `test_rutas_de_produccion_no_cambian`.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core.seguridad import TokenInvalido, registrar_manejador_401, responder_token_invalido
from app.core.validacion_http import registrar_manejador_validacion, responder_validacion_invalida
from app.main import crear_app

_SENTINELA = "sentinela-unico-de-validacion-9b1e4f2c7d"


class _CuerpoDeclarado(BaseModel):
    cantidad: int


def crear_app_de_prueba() -> FastAPI:
    """Router de pruebas: nunca se cablea en `app/main.py`."""
    app = FastAPI()
    registrar_manejador_validacion(app)

    @app.post("/con-cuerpo")
    def con_cuerpo(cuerpo: _CuerpoDeclarado) -> dict[str, int]:
        return {"cantidad": cuerpo.cantidad}

    return app


@pytest.fixture
def cliente_de_prueba() -> Iterator[TestClient]:
    with TestClient(crear_app_de_prueba()) as cliente:
        yield cliente


def test_cuerpo_malformado_responde_422_vacio(cliente_de_prueba: TestClient) -> None:
    respuesta = cliente_de_prueba.post("/con-cuerpo", json={"cantidad": _SENTINELA})
    assert respuesta.status_code == 422
    assert respuesta.content == b""


def test_sentinela_ausente_de_la_respuesta_completa(cliente_de_prueba: TestClient) -> None:
    respuesta = cliente_de_prueba.post("/con-cuerpo", json={"cantidad": _SENTINELA})
    cruda = respuesta.content + str(respuesta.headers).encode("utf-8")
    assert _SENTINELA.encode("utf-8") not in cruda
    assert b"detail" not in cruda
    assert b"tipo" not in cruda


def test_manejadores_registrados_en_la_app_embarcada() -> None:
    app = crear_app()
    from fastapi.exceptions import RequestValidationError

    assert app.exception_handlers[TokenInvalido] is responder_token_invalido
    assert app.exception_handlers[RequestValidationError] is responder_validacion_invalida


def test_registrar_manejador_401_no_se_omite() -> None:
    # Sanity check auxiliar: el registro sigue disponible tal como lo dejó el ítem #2.
    app = FastAPI()
    registrar_manejador_401(app)
    assert app.exception_handlers[TokenInvalido] is responder_token_invalido
