"""Pruebas del chequeo de arranque registry ↔ contratos (ítem #11).

Behaviourales, sin AST ni inspección estructural (metodología: TDD estricto
deshabilitado).

**Dónde se parchea cada mitad, y por qué no en el mismo lugar.** La tabla de
contratos se sustituye sobre `app.core.contrato._TABLA_CONTRATOS`, igual que en
`tests/test_recepcion.py`: `obtener_tabla_contratos()` lee ese global en cada
llamada, así que la sustitución vale. `REGISTRY`, en cambio, entra a
`app.coherencia` por `from app.registry import REGISTRY` —el mismo idioma que
usa `app/core/ejecucion.py:55`—, de modo que el nombre queda ligado en el
espacio de nombres del consumidor: parchear `app.registry.REGISTRY` no tendría
ningún efecto sobre el chequeo. Se parchea donde se usa,
`app.coherencia.REGISTRY`. Siempre con `monkeypatch` y nunca con una asignación
pelada: `tests/test_interfaz_procesador.py` ya advierte que mutar ese global se
filtra entre pruebas.

**Cero spawns reales.** Nada de acá crea un proceso hijo: el chequeo corre
entero en el padre y sólo lee dos diccionarios.
"""

from __future__ import annotations

import json
import logging
from types import MappingProxyType

import pytest
from fastapi.testclient import TestClient

from app import coherencia
from app.coherencia import (
    EVENTO_CONTRATO_INACTIVO,
    EVENTO_CONTRATO_SIN_REGISTRY,
    RegistrySinContrato,
    contrastar_registry_contra_contratos,
)
from app.core import contrato as contrato_modulo
from app.core.configuracion import ConfiguracionInvalida
from app.core.contrato import CONTRATO_POR_DEFECTO, ContratoProcesador
from app.core.interfaz import Procesador
from app.core.registro import NOMBRE_LOGGER, FormateadorJsonLineas
from app.main import crear_app
from app.procesadores.passthrough.modulo import Passthrough
from app.registry import REGISTRY

_CLAVE = "procesador_de_prueba"
_OTRA_CLAVE = "otro_procesador_de_prueba"

_CONTRATO_ACTIVO: ContratoProcesador = CONTRATO_POR_DEFECTO
_CONTRATO_INACTIVO: ContratoProcesador = ContratoProcesador(
    entradas_min=CONTRATO_POR_DEFECTO.entradas_min,
    entradas_max=CONTRATO_POR_DEFECTO.entradas_max,
    formatos_aceptados=CONTRATO_POR_DEFECTO.formatos_aceptados,
    tamano_max_bytes=CONTRATO_POR_DEFECTO.tamano_max_bytes,
    tamano_max_total_bytes=CONTRATO_POR_DEFECTO.tamano_max_total_bytes,
    activo=False,
)


def _fijar_registry(monkeypatch: pytest.MonkeyPatch, *claves: str) -> None:
    """Sustituye el registry que ve `app.coherencia` por las `claves` dadas."""
    registry: dict[str, Procesador] = {clave: Passthrough(clave=clave) for clave in claves}
    monkeypatch.setattr(coherencia, "REGISTRY", registry)


def _fijar_tabla(monkeypatch: pytest.MonkeyPatch, filas: dict[str, ContratoProcesador]) -> None:
    """Sustituye la tabla de contratos que lee `obtener_tabla_contratos()`."""
    monkeypatch.setattr(contrato_modulo, "_TABLA_CONTRATOS", MappingProxyType(filas))


class TestTablasEntregadas:
    """Lo que este repositorio tiene hoy en `main` tiene que pasar limpio."""

    def test_el_registry_y_los_contratos_entregados_coinciden(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING, logger=NOMBRE_LOGGER):
            contrastar_registry_contra_contratos()

        assert caplog.records == []

    def test_todas_las_claves_del_registry_tienen_fila_activa(self) -> None:
        tabla = contrato_modulo.obtener_tabla_contratos()
        for clave in REGISTRY:
            assert tabla[clave].activo is True


class TestClaveDelRegistrySinFila:
    """Situación 1: falla el arranque y el mensaje nombra la clave."""

    def test_levanta_y_nombra_la_clave(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _fijar_registry(monkeypatch, _CLAVE)
        _fijar_tabla(monkeypatch, {})

        with pytest.raises(RegistrySinContrato) as capturado:
            contrastar_registry_contra_contratos()

        assert _CLAVE in str(capturado.value)

    def test_nombra_todas_las_claves_sin_fila_de_una_vez(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _fijar_registry(monkeypatch, _CLAVE, _OTRA_CLAVE)
        _fijar_tabla(monkeypatch, {})

        with pytest.raises(RegistrySinContrato) as capturado:
            contrastar_registry_contra_contratos()

        mensaje = str(capturado.value)
        assert _CLAVE in mensaje
        assert _OTRA_CLAVE in mensaje

    def test_una_clave_con_fila_no_arrastra_a_la_que_si_la_tiene(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _fijar_registry(monkeypatch, _CLAVE, _OTRA_CLAVE)
        _fijar_tabla(monkeypatch, {_CLAVE: _CONTRATO_ACTIVO})

        with pytest.raises(RegistrySinContrato) as capturado:
            contrastar_registry_contra_contratos()

        assert _OTRA_CLAVE in str(capturado.value)

    def test_el_fallo_gana_sobre_cualquier_advertencia(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Un despliegue incompleto no se acompaña de ruido: corta primero."""
        _fijar_registry(monkeypatch, _CLAVE)
        _fijar_tabla(monkeypatch, {_OTRA_CLAVE: _CONTRATO_ACTIVO})

        with caplog.at_level(logging.WARNING, logger=NOMBRE_LOGGER):
            with pytest.raises(RegistrySinContrato):
                contrastar_registry_contra_contratos()

        assert caplog.records == []


class TestFilaInactivaConRegistry:
    """Situación 2: arranca, con advertencia."""

    def test_no_impide_el_arranque_y_advierte_nombrando_la_clave(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        _fijar_registry(monkeypatch, _CLAVE)
        _fijar_tabla(monkeypatch, {_CLAVE: _CONTRATO_INACTIVO})

        with caplog.at_level(logging.WARNING, logger=NOMBRE_LOGGER):
            contrastar_registry_contra_contratos()  # no levanta

        assert len(caplog.records) == 1
        registro = caplog.records[0]
        assert registro.levelno == logging.WARNING
        assert getattr(registro, "evento", None) == EVENTO_CONTRATO_INACTIVO
        assert getattr(registro, "clave", None) == _CLAVE


class TestFilaSinEntradaEnElRegistry:
    """Situación 3, y la decisión sobre la fila inactiva huérfana."""

    def test_fila_activa_sin_registry_no_impide_el_arranque_y_advierte(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        _fijar_registry(monkeypatch)
        _fijar_tabla(monkeypatch, {_CLAVE: _CONTRATO_ACTIVO})

        with caplog.at_level(logging.WARNING, logger=NOMBRE_LOGGER):
            contrastar_registry_contra_contratos()  # no levanta

        assert len(caplog.records) == 1
        registro = caplog.records[0]
        assert registro.levelno == logging.WARNING
        assert getattr(registro, "evento", None) == EVENTO_CONTRATO_SIN_REGISTRY
        assert getattr(registro, "clave", None) == _CLAVE

    def test_fila_inactiva_sin_registry_no_levanta_ni_advierte(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Decisión de este ítem, pinchada acá para que no se pierda.

        La tabla de TECH-DESIGN advierte por una fila **activa** sin entrada en
        el registry. Una fila apagada sin código detrás es el estado final
        esperado de una baja, no un síntoma: advertir por ella convertiría cada
        procesador retirado en ruido permanente en la bitácora.
        """
        _fijar_registry(monkeypatch)
        _fijar_tabla(monkeypatch, {_CLAVE: _CONTRATO_INACTIVO})

        with caplog.at_level(logging.WARNING, logger=NOMBRE_LOGGER):
            contrastar_registry_contra_contratos()  # no levanta

        assert caplog.records == []


class TestFormaDeLaAdvertencia:
    """La advertencia sale por el logger del ítem #14, como línea JSON."""

    @pytest.mark.parametrize(
        ("filas", "claves_registradas", "evento_esperado"),
        [
            pytest.param(
                {_CLAVE: _CONTRATO_INACTIVO},
                (_CLAVE,),
                EVENTO_CONTRATO_INACTIVO,
                id="fila_inactiva_con_registry",
            ),
            pytest.param(
                {_CLAVE: _CONTRATO_ACTIVO},
                (),
                EVENTO_CONTRATO_SIN_REGISTRY,
                id="fila_activa_sin_registry",
            ),
        ],
    )
    def test_la_advertencia_se_renderiza_como_json_por_linea(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        filas: dict[str, ContratoProcesador],
        claves_registradas: tuple[str, ...],
        evento_esperado: str,
    ) -> None:
        _fijar_registry(monkeypatch, *claves_registradas)
        _fijar_tabla(monkeypatch, filas)

        with caplog.at_level(logging.WARNING, logger=NOMBRE_LOGGER):
            contrastar_registry_contra_contratos()

        (registro,) = caplog.records
        # `caplog.records` no pasa por ningún formateador: el renderizado se
        # ejercita a mano, igual que en `tests/test_registro_operativo.py`.
        carga = json.loads(FormateadorJsonLineas().format(registro))
        assert carga["nivel"] == "WARNING"
        assert carga["logger"] == NOMBRE_LOGGER
        assert carga["evento"] == evento_esperado
        assert carga["clave"] == _CLAVE
        assert carga["mensaje"]


class TestChequeoDentroDelLifespanReal:
    """El chequeo tiene que correr de verdad al levantar la app."""

    def test_un_registry_sin_fila_impide_levantar_la_app(
        self,
        monkeypatch: pytest.MonkeyPatch,
        token_sentinela: str,
        limpiar_cache_configuracion: None,
    ) -> None:
        _fijar_registry(monkeypatch, _CLAVE)
        _fijar_tabla(monkeypatch, {})

        # Starlette propaga una excepción de arranque del lifespan por el
        # `__enter__` del cliente.
        with pytest.raises(RegistrySinContrato):
            with TestClient(crear_app()):
                pass

    def test_las_tablas_entregadas_levantan_la_app_sin_advertir(
        self,
        caplog: pytest.LogCaptureFixture,
        token_sentinela: str,
        limpiar_cache_configuracion: None,
    ) -> None:
        with caplog.at_level(logging.WARNING, logger=NOMBRE_LOGGER):
            with TestClient(crear_app()) as cliente:
                assert cliente.get("/salud").status_code == 200

        assert [r for r in caplog.records if r.name.startswith(NOMBRE_LOGGER)] == []

    def test_una_fila_inactiva_no_impide_levantar_la_app(
        self,
        monkeypatch: pytest.MonkeyPatch,
        token_sentinela: str,
        limpiar_cache_configuracion: None,
    ) -> None:
        _fijar_registry(monkeypatch, _CLAVE)
        _fijar_tabla(monkeypatch, {_CLAVE: _CONTRATO_INACTIVO})

        with TestClient(crear_app()) as cliente:
            assert cliente.get("/salud").status_code == 200

    def test_la_configuracion_falla_antes_que_el_registry(
        self,
        monkeypatch: pytest.MonkeyPatch,
        limpiar_cache_configuracion: None,
    ) -> None:
        """Regla de orden del ítem #1: el token faltante gana siempre.

        Con las dos cosas rotas a la vez, el operador tiene que ver el error de
        configuración; si no, una desincronización del registry enmascararía un
        despliegue sin token.
        """
        monkeypatch.delenv("TOKEN_SERVICIO", raising=False)
        _fijar_registry(monkeypatch, _CLAVE)
        _fijar_tabla(monkeypatch, {})

        with pytest.raises(ConfiguracionInvalida):
            with TestClient(crear_app()):
                pass
