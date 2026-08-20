"""Pruebas del contrato de errores tipificados (ítem #3, design.md §6-§7).

Router de pruebas: `crear_app_de_prueba()` vive únicamente en este módulo
(nunca en `app/`), igual que hizo el ítem #2 (V7): el conjunto de rutas
embarcado ya está pinchado por `test_rutas_de_produccion_no_cambian` en
`tests/test_seguridad_token.py` y no se duplica aquí.
"""

from __future__ import annotations

import pickle
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
    responder_error_tipificado,
)
from app.main import crear_app

_CASOS: Final[Mapping[str, ErrorTipificado]] = {
    "formato": ErrorFormato(
        archivo="enero.csv", formato_recibido="csv", formatos_aceptados=["xlsx"]
    ),
    "tamano": ErrorTamano(archivo="enero.xlsx", limite_bytes=26_214_400, recibido_bytes=31_457_280),
    "tamano_total": ErrorTamano.total(
        archivos=["enero.xlsx", "febrero.xlsx", "marzo.xlsx"],
        limite_bytes=26_214_400,
        recibido_bytes=31_457_280,
    ),
    "contenido_columna": ErrorContenido.columna_faltante(archivo="enero.xlsx", columna="Fecha"),
    "contenido_cero_filas": ErrorContenido.cero_filas(archivo="enero.xlsx"),
    "contenido_sin_salidas": ErrorContenido.sin_salidas(),
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
    "tamano_total": (
        422,
        {
            "tipo": "tamano",
            "contexto": {
                "archivos": ["enero.xlsx", "febrero.xlsx", "marzo.xlsx"],
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
    "contenido_sin_salidas": (
        422,
        {"tipo": "contenido", "contexto": {"motivo": "sin_salidas"}},
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


class TestPickleRoundTrip:
    """`ErrorTipificado.__reduce__` (ítem #8, design.md §5, V6).

    El `Pipe` entre el proceso padre y el hijo dedicado usa pickling; un
    error tipificado levantado por el módulo debe cruzar esa frontera
    intacto -- `tipo` y el `contexto` completo, sin invocar `__init__`.
    """

    @pytest.mark.parametrize("nombre", list(_CASOS))
    def test_sobrevive_el_round_trip(self, nombre: str) -> None:
        original = _CASOS[nombre]
        reconstruido = pickle.loads(pickle.dumps(original))  # noqa: S301
        assert type(reconstruido) is type(original)
        assert reconstruido.tipo == original.tipo
        assert reconstruido.contexto == original.contexto

    def test_es_instancia_de_error_tipificado(self) -> None:
        original = _CASOS["formato"]
        reconstruido = pickle.loads(pickle.dumps(original))  # noqa: S301
        assert isinstance(reconstruido, ErrorTipificado)

    def test_tamano_total_conserva_la_forma_hermana(self) -> None:
        original = _CASOS["tamano_total"]
        reconstruido = pickle.loads(pickle.dumps(original))  # noqa: S301
        assert isinstance(reconstruido, ErrorTamano)
        assert set(reconstruido.contexto) == {"archivos", "limite_bytes", "recibido_bytes"}
        assert "archivo" not in reconstruido.contexto


def test_manejador_registrado_en_la_app_embarcada() -> None:
    app = crear_app()
    assert app.exception_handlers[ErrorTipificado] is responder_error_tipificado


def test_manejador_activo_en_la_app_embarcada(
    token_sentinela: str, limpiar_cache_configuracion: None
) -> None:
    # Comportamiento, no solo registro: una ruta que lanza un error tipificado
    # en la app de producción debe recibir el sobre {"tipo", "contexto"}
    # documentado por ADR 0014, no un 500 sin tipificar.
    app = crear_app()
    error = ErrorFormato(archivo="enero.csv", formato_recibido="csv", formatos_aceptados=["xlsx"])

    @app.get("/prueba-error-tipificado")
    def _lanzar() -> None:
        raise error

    with TestClient(app, raise_server_exceptions=False) as cliente:
        respuesta = cliente.get("/prueba-error-tipificado")

    assert respuesta.status_code == 422
    assert respuesta.json() == {
        "tipo": "formato",
        "contexto": {
            "archivo": "enero.csv",
            "formato_recibido": "csv",
            "formatos_aceptados": ["xlsx"],
        },
    }


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
    # El discriminante `motivo` narrows la unión hacia `ContextoContenido`
    # (mypy V6 checkpoint, ADR 0023): sin esta guarda, indexar "columna" no
    # typechecka contra `ContextoContenido | ContextoSinSalidas`.
    assert error.contexto["motivo"] == "cero_filas"
    assert error.contexto["columna"] is None


class TestDosFormasDeTamano:
    """La unión crece, el enum no (ADR 0021, design.md §6)."""

    def test_un_solo_archivo_conserva_la_forma_verbatim_de_adr_0014(self) -> None:
        # Guarda de regresión: ADR 0014 fija estos tres campos, ni uno más ni
        # uno menos, para el caso de un solo archivo.
        error = ErrorTamano(archivo="enero.xlsx", limite_bytes=100, recibido_bytes=101)
        assert set(error.contexto) == {"archivo", "limite_bytes", "recibido_bytes"}
        assert error.contexto == {
            "archivo": "enero.xlsx",
            "limite_bytes": 100,
            "recibido_bytes": 101,
        }

    def test_el_total_usa_la_forma_hermana_sin_archivo(self) -> None:
        error = ErrorTamano.total(
            archivos=["enero.xlsx", "febrero.xlsx"], limite_bytes=100, recibido_bytes=150
        )
        assert set(error.contexto) == {"archivos", "limite_bytes", "recibido_bytes"}
        assert "archivo" not in error.contexto
        assert error.contexto["archivos"] == ["enero.xlsx", "febrero.xlsx"]

    def test_el_placeholder_de_construccion_no_escapa(self) -> None:
        # `total()` construye con `archivo=""` y lo sobrescribe: ningún estado
        # intermedio inválido debe ser observable desde afuera.
        error = ErrorTamano.total(archivos=["enero.xlsx"], limite_bytes=100, recibido_bytes=150)
        assert "" not in error.contexto.values()

    def test_ambas_formas_comparten_tipo_y_estado(self) -> None:
        uno = ErrorTamano(archivo="enero.xlsx", limite_bytes=100, recibido_bytes=101)
        total = ErrorTamano.total(archivos=["enero.xlsx"], limite_bytes=100, recibido_bytes=101)
        assert uno.tipo is total.tipo is TipoError.TAMANO
        assert _ESTADO_HTTP[uno.tipo] == _ESTADO_HTTP[total.tipo] == 422

    def test_total_es_la_misma_clase_de_excepcion(self) -> None:
        total = ErrorTamano.total(archivos=["enero.xlsx"], limite_bytes=100, recibido_bytes=101)
        assert isinstance(total, ErrorTamano)
        assert isinstance(total, ErrorTipificado)


class TestDosFormasDeContenido:
    """La unión crece una segunda vez, el enum no (ADR 0023)."""

    def test_cero_filas_conserva_la_forma_verbatim_de_adr_0014(self) -> None:
        error = ErrorContenido.cero_filas(archivo="marzo.xlsx")
        assert set(error.contexto) == {"archivo", "motivo", "columna"}
        # Narrowing por el discriminante `motivo` -- ver nota en
        # `test_cero_filas_deja_columna_en_none`.
        assert error.contexto["motivo"] == "cero_filas"
        assert error.contexto["columna"] is None

    def test_sin_salidas_usa_la_forma_hermana_sin_archivo(self) -> None:
        error = ErrorContenido.sin_salidas()
        assert set(error.contexto) == {"motivo"}
        assert "archivo" not in error.contexto
        assert error.contexto["motivo"] == "sin_salidas"

    def test_ambas_formas_comparten_tipo_y_estado(self) -> None:
        con_archivo = ErrorContenido.cero_filas(archivo="marzo.xlsx")
        sin_archivo = ErrorContenido.sin_salidas()
        assert con_archivo.tipo is sin_archivo.tipo is TipoError.CONTENIDO
        assert _ESTADO_HTTP[con_archivo.tipo] == _ESTADO_HTTP[sin_archivo.tipo] == 422

    def test_sin_salidas_es_la_misma_clase_de_excepcion(self) -> None:
        error = ErrorContenido.sin_salidas()
        assert isinstance(error, ErrorContenido)
        assert isinstance(error, ErrorTipificado)


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
