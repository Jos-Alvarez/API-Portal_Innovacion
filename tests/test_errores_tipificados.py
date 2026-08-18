"""Pruebas del contrato de errores tipificados (ítem #3, design.md §6-§7).

Router de pruebas: `crear_app_de_prueba()` vive únicamente en este módulo
(nunca en `app/`), igual que hizo el ítem #2 (V7): el conjunto de rutas
embarcado ya está pinchado por `test_rutas_de_produccion_no_cambian` en
`tests/test_seguridad_token.py` y no se duplica aquí.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Final

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from app.core.errores import (
    _ESTADO_HTTP,
    ErrorCantidad,
    ErrorClaveInexistente,
    ErrorContenido,
    ErrorFormato,
    ErrorTamano,
    ErrorTipificado,
    TipoError,
    registrar_manejador_errores,
)

_CASOS: Final[Mapping[str, ErrorTipificado]] = {
    "formato": ErrorFormato(
        archivo="enero.csv", formato_recibido="csv", formatos_aceptados=["xlsx"]
    ),
    "tamano": ErrorTamano(archivo="enero.xlsx", limite_bytes=26_214_400, recibido_bytes=31_457_280),
    "contenido_columna": ErrorContenido.columna_faltante(archivo="enero.xlsx", columna="Fecha"),
    "contenido_cero_filas": ErrorContenido.cero_filas(archivo="enero.xlsx"),
    "cantidad": ErrorCantidad(minimo=1, maximo=2, recibido=5),
    "clave_fila": ErrorClaveInexistente(clave_procesador="contado_carga", causa="fila_ausente"),
    "clave_desync": ErrorClaveInexistente(clave_procesador="contado_carga", causa="no_en_registry"),
}

_CUERPOS_ESPERADOS: Final[Mapping[str, tuple[int, dict[str, object]]]] = {
    "formato": (
        422,
        {
            "tipo": "formato",
            "contexto": {
                "archivo": "enero.csv",
                "formato_recibido": "csv",
                "formatos_aceptados": ["xlsx"],
            },
        },
    ),
    "tamano": (
        422,
        {
            "tipo": "tamano",
            "contexto": {
                "archivo": "enero.xlsx",
                "limite_bytes": 26_214_400,
                "recibido_bytes": 31_457_280,
            },
        },
    ),
    "contenido_columna": (
        422,
        {
            "tipo": "contenido",
            "contexto": {
                "archivo": "enero.xlsx",
                "motivo": "columna_faltante",
                "columna": "Fecha",
            },
        },
    ),
    "contenido_cero_filas": (
        422,
        {
            "tipo": "contenido",
            "contexto": {
                "archivo": "enero.xlsx",
                "motivo": "cero_filas",
                "columna": None,
            },
        },
    ),
    "cantidad": (
        422,
        {"tipo": "cantidad", "contexto": {"minimo": 1, "maximo": 2, "recibido": 5}},
    ),
    "clave_fila": (
        500,
        {
            "tipo": "clave_inexistente",
            "contexto": {"clave_procesador": "contado_carga", "causa": "fila_ausente"},
        },
    ),
    "clave_desync": (
        500,
        {
            "tipo": "clave_inexistente",
            "contexto": {"clave_procesador": "contado_carga", "causa": "no_en_registry"},
        },
    ),
}


def _lanzador(error: ErrorTipificado) -> Callable[[], None]:
    def _lanzar() -> None:
        raise error

    return _lanzar


def crear_app_de_prueba() -> FastAPI:
    """Router de pruebas: nunca se cablea en `app/main.py` (design.md §6)."""
    app = FastAPI()  # debug omitido -> False
    registrar_manejador_errores(app)
    router = APIRouter()
    for nombre, error in _CASOS.items():
        router.add_api_route(f"/lanzar/{nombre}", _lanzador(error), methods=["GET"])
    app.include_router(router)
    return app


@pytest.fixture
def cliente_de_prueba() -> TestClient:
    return TestClient(crear_app_de_prueba())


class TestCasosDeError:
    @pytest.mark.parametrize("nombre", list(_CASOS))
    def test_estado_y_cuerpo_documentados(self, cliente_de_prueba: TestClient, nombre: str) -> None:
        respuesta = cliente_de_prueba.get(f"/lanzar/{nombre}")
        estado_esperado, cuerpo_esperado = _CUERPOS_ESPERADOS[nombre]
        assert respuesta.status_code == estado_esperado
        assert respuesta.json() == cuerpo_esperado

    def test_columna_refleja_el_motivo(self, cliente_de_prueba: TestClient) -> None:
        con_columna = cliente_de_prueba.get("/lanzar/contenido_columna")
        sin_columna = cliente_de_prueba.get("/lanzar/contenido_cero_filas")
        assert con_columna.json()["contexto"]["columna"] == "Fecha"
        assert sin_columna.json()["contexto"]["columna"] is None

    def test_causas_de_clave_inexistente_son_distinguibles(
        self, cliente_de_prueba: TestClient
    ) -> None:
        fila = cliente_de_prueba.get("/lanzar/clave_fila")
        desync = cliente_de_prueba.get("/lanzar/clave_desync")
        assert fila.status_code == desync.status_code == 500
        assert fila.json()["tipo"] == desync.json()["tipo"] == "clave_inexistente"
        assert fila.json()["contexto"]["causa"] != desync.json()["contexto"]["causa"]


def test_vocabulario_cerrado() -> None:
    assert {t.value for t in TipoError} == {
        "formato",
        "tamano",
        "contenido",
        "cantidad",
        "clave_inexistente",
    }


def test_todos_los_tipos_tienen_estado_y_caso() -> None:
    assert set(_ESTADO_HTTP) == set(TipoError)
    assert {caso.tipo for caso in _CASOS.values()} == set(TipoError)


def test_cero_filas_deja_columna_en_none() -> None:
    error = ErrorContenido.cero_filas(archivo="marzo.xlsx")
    assert error.contexto["columna"] is None


class TestFormaDeContexto:
    """Chequeo ligero de forma: cada campo es un tipo cerrado, no prosa (design.md §7)."""

    @pytest.mark.parametrize("nombre", list(_CASOS))
    def test_campos_son_valores_crudos_o_enum_cerrado(
        self, cliente_de_prueba: TestClient, nombre: str
    ) -> None:
        respuesta = cliente_de_prueba.get(f"/lanzar/{nombre}")
        contexto = respuesta.json()["contexto"]
        for valor in contexto.values():
            assert valor is None or isinstance(valor, str | int | list)
