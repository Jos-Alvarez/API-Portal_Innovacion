"""Pruebas del logging operativo estructurado (ítem #14, BACKLOG fila 14).

Behaviourales, sin AST ni inspección estructural (TDD estricto deshabilitado).

**Cero spawns reales.** Todos los campos de la línea de ejecución se calculan
en el proceso padre, así que `ejecutar_modulo` se sustituye dentro del espacio
de nombres de `app.core.pipeline` —el mismo patrón que ya usan
`tests/test_pipeline.py` y `tests/test_recepcion.py`— y ninguna prueba de acá
gasta del presupuesto de ≤6 spawns por entrega.

**Por qué hay una prueba de subproceso y por qué es la que importa.**
`caplog.at_level(...)` baja el nivel del logger raíz, así que una suite que
sólo use `caplog` pasa en verde aunque en producción no se emita ni una línea:
bajo `uv run uvicorn app.main:app` la raíz no tiene handler ni nivel fijado y
un `app.*` en INFO muere en el `lastResort` de nivel WARNING. `TestVisibilidad`
corre un intérprete fresco que reproduce el orden real de uvicorn (dictConfig
primero, import de la app después) y afirma que la línea llega de verdad a
`stderr`. Sin ella, este ítem entero podría ser un no-op silencioso.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from collections.abc import Awaitable, Callable, Iterator, MutableMapping
from datetime import timedelta
from types import MappingProxyType
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.types import Receive, Scope, Send

from app.core import contrato as contrato_modulo
from app.core import pipeline
from app.core.admision import AdmisionDeBorde, ServicioSaturado, obtener_semaforo
from app.core.contrato import CONTRATO_POR_DEFECTO
from app.core.ejecucion import (
    EjecucionExpirada,
    FalloDelModulo,
    HijoMuerto,
)
from app.core.registro import (
    EVENTO_EJECUCION,
    EVENTO_SATURACION,
    NOMBRE_LOGGER,
    FormateadorJsonLineas,
    ResultadoDeEjecucion,
)
from app.core.temporales import _EN_VUELO, _raiz
from app.core.tipos import ArchivoEntrada, ArchivoSalida
from app.main import crear_app
from tests.ayudas.subproceso import ejecutar_snippet

_CLAVE = "cualquiera"
_RUTA = f"/interno/procesadores/{_CLAVE}"

FabricaDeSalidas = Callable[[list[ArchivoEntrada]], list[ArchivoSalida]]
InstalarModulo = Callable[[FabricaDeSalidas], None]


def _cabecera(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _lineas(caplog: pytest.LogCaptureFixture, evento: str) -> list[logging.LogRecord]:
    """Los registros del evento pedido, en orden de emisión."""
    return [registro for registro in caplog.records if getattr(registro, "evento", None) == evento]


@pytest.fixture(autouse=True)
def _estado_de_temporales_limpio() -> Iterator[None]:
    """Mismo aislamiento que `tests/test_recepcion.py`: `_EN_VUELO` y la raíz
    dedicada son estado de módulo compartido."""
    _EN_VUELO.clear()
    shutil.rmtree(_raiz(), ignore_errors=True)
    yield
    _EN_VUELO.clear()
    shutil.rmtree(_raiz(), ignore_errors=True)


@pytest.fixture
def cliente_de_prueba(
    token_sentinela: str, limpiar_cache_configuracion: None
) -> Iterator[TestClient]:
    with TestClient(crear_app(), raise_server_exceptions=False) as cliente:
        yield cliente


@pytest.fixture
def contrato_registrado(monkeypatch: pytest.MonkeyPatch) -> None:
    """Da de alta `_CLAVE` con el contrato por defecto (sólo `xlsx`, 1 archivo)."""
    monkeypatch.setattr(
        contrato_modulo, "_TABLA_CONTRATOS", MappingProxyType({_CLAVE: CONTRATO_POR_DEFECTO})
    )


@pytest.fixture
def modulo_falso(monkeypatch: pytest.MonkeyPatch) -> InstalarModulo:
    """Sustituye `ejecutar_modulo` en el espacio de nombres de `app.core.pipeline`."""

    def _instalar(fabrica: FabricaDeSalidas) -> None:
        def _falso(
            *, clave: str, entradas: list[ArchivoEntrada], timeout: timedelta
        ) -> list[ArchivoSalida]:
            return fabrica(entradas)

        monkeypatch.setattr(pipeline, "ejecutar_modulo", _falso)

    return _instalar


def _passthrough(entradas: list[ArchivoEntrada]) -> list[ArchivoSalida]:
    """Una salida por entrada, sobre el archivo que ya está en disco."""
    return [
        ArchivoSalida(
            nombre_propuesto=entrada.ruta_temporal.name,
            ruta_temporal=entrada.ruta_temporal,
            tipo_mime="application/octet-stream",
        )
        for entrada in entradas
    ]


def _nombres_duplicados(entradas: list[ArchivoEntrada]) -> list[ArchivoSalida]:
    """Dos salidas que aplanan al mismo nombre: `empaquetar` real levanta
    `SalidaMalFormada`. No se simula la excepción, se provoca."""
    return [
        ArchivoSalida(
            nombre_propuesto="repetido.csv",
            ruta_temporal=entradas[0].ruta_temporal,
            tipo_mime="text/csv",
        )
        for _ in range(2)
    ]


def _fallar(falla: Exception) -> FabricaDeSalidas:
    def _fabrica(entradas: list[ArchivoEntrada]) -> list[ArchivoSalida]:
        raise falla

    return _fabrica


class TestRegistroDeEjecucionExitosa:
    def test_emite_una_linea_con_los_campos_de_la_fila_14(
        self,
        cliente_de_prueba: TestClient,
        token_sentinela: str,
        contrato_registrado: None,
        modulo_falso: InstalarModulo,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        modulo_falso(_passthrough)

        with caplog.at_level(logging.INFO, logger=NOMBRE_LOGGER):
            respuesta = cliente_de_prueba.post(
                _RUTA,
                files={"archivos": ("informe.xlsx", b"contenido-de-siete", "application/json")},
                headers=_cabecera(token_sentinela),
            )

        assert respuesta.status_code == 200
        (registro,) = _lineas(caplog, EVENTO_EJECUCION)
        assert registro.clave == _CLAVE  # type: ignore[attr-defined]
        assert registro.archivos == 1  # type: ignore[attr-defined]
        assert registro.bytes_recibidos == len(b"contenido-de-siete")  # type: ignore[attr-defined]
        assert registro.resultado == ResultadoDeEjecucion.EXITO.value  # type: ignore[attr-defined]
        assert registro.duracion_ruta_ms >= 0.0  # type: ignore[attr-defined]
        # Sin error, sin campos de error: la línea no lleva huecos vacíos.
        assert not hasattr(registro, "tipo_error")
        assert not hasattr(registro, "traza")

    def test_el_token_no_viaja_en_la_linea(
        self,
        cliente_de_prueba: TestClient,
        token_sentinela: str,
        contrato_registrado: None,
        modulo_falso: InstalarModulo,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        modulo_falso(_passthrough)

        with caplog.at_level(logging.INFO, logger=NOMBRE_LOGGER):
            cliente_de_prueba.post(
                _RUTA,
                files={"archivos": ("informe.xlsx", b"x", "application/octet-stream")},
                headers=_cabecera(token_sentinela),
            )

        (registro,) = _lineas(caplog, EVENTO_EJECUCION)
        renderizado = FormateadorJsonLineas().format(registro)
        assert token_sentinela not in renderizado
        assert "Authorization" not in renderizado
        assert "Bearer" not in renderizado


class TestRegistroDeLosDesenlacesQueFallan:
    """Cada falla registra su desenlace **y no cambia el código de estado**.

    El `except` de la ruta re-levanta siempre: los manejadores de `crear_app()`
    siguen siendo los únicos que construyen la respuesta. Por eso cada caso
    afirma las dos cosas juntas — desenlace registrado y estado intacto —; si
    el logging llegara a tragarse una excepción, el estado lo delataría.
    """

    def test_rechazo_tipificado_registra_y_deja_el_422_intacto(
        self,
        cliente_de_prueba: TestClient,
        token_sentinela: str,
        contrato_registrado: None,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        with caplog.at_level(logging.INFO, logger=NOMBRE_LOGGER):
            # `.csv` contra un contrato que sólo acepta `xlsx`: `ErrorFormato`.
            respuesta = cliente_de_prueba.post(
                _RUTA,
                files={"archivos": ("enero.csv", b"a;b", "application/octet-stream")},
                headers=_cabecera(token_sentinela),
            )

        assert respuesta.status_code == 422
        assert respuesta.json()["tipo"] == "formato"
        (registro,) = _lineas(caplog, EVENTO_EJECUCION)
        assert registro.resultado == ResultadoDeEjecucion.RECHAZO_TIPIFICADO.value  # type: ignore[attr-defined]
        assert registro.tipo_error == "formato"  # type: ignore[attr-defined]
        # Rechazo de fase 1: no se copió ni un byte, y la línea lo dice.
        assert registro.bytes_recibidos == 0  # type: ignore[attr-defined]

    @pytest.mark.parametrize(
        "falla,resultado_esperado,estado_esperado",
        [
            pytest.param(
                EjecucionExpirada(),
                ResultadoDeEjecucion.EJECUCION_EXPIRADA,
                504,
                id="ejecucion_expirada",
            ),
            pytest.param(
                HijoMuerto(exitcode=-9),
                ResultadoDeEjecucion.HIJO_MUERTO,
                500,
                id="hijo_muerto",
            ),
            pytest.param(
                FalloDelModulo(
                    clase="ValueError",
                    mensaje="el modulo se cayo",
                    traza='Traceback...\n  File "modulo.py", line 3\nValueError: el modulo se cayo',
                ),
                ResultadoDeEjecucion.FALLO_DEL_MODULO,
                500,
                id="fallo_del_modulo",
            ),
        ],
    )
    def test_cada_falla_no_tipificada_registra_su_desenlace(
        self,
        cliente_de_prueba: TestClient,
        token_sentinela: str,
        contrato_registrado: None,
        modulo_falso: InstalarModulo,
        caplog: pytest.LogCaptureFixture,
        falla: Exception,
        resultado_esperado: ResultadoDeEjecucion,
        estado_esperado: int,
    ) -> None:
        modulo_falso(_fallar(falla))

        with caplog.at_level(logging.INFO, logger=NOMBRE_LOGGER):
            respuesta = cliente_de_prueba.post(
                _RUTA,
                files={"archivos": ("informe.xlsx", b"entrada", "application/octet-stream")},
                headers=_cabecera(token_sentinela),
            )

        assert respuesta.status_code == estado_esperado
        (registro,) = _lineas(caplog, EVENTO_EJECUCION)
        assert registro.resultado == resultado_esperado.value  # type: ignore[attr-defined]
        assert registro.tipo_error is not None  # type: ignore[attr-defined]
        # La copia sí ocurrió antes de la falla: la línea lo refleja.
        assert registro.bytes_recibidos == len(b"entrada")  # type: ignore[attr-defined]

    def test_el_empaquetado_mal_formado_registra_su_propio_desenlace(
        self,
        cliente_de_prueba: TestClient,
        token_sentinela: str,
        contrato_registrado: None,
        modulo_falso: InstalarModulo,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        modulo_falso(_nombres_duplicados)

        with caplog.at_level(logging.INFO, logger=NOMBRE_LOGGER):
            respuesta = cliente_de_prueba.post(
                _RUTA,
                files={"archivos": ("informe.xlsx", b"entrada", "application/octet-stream")},
                headers=_cabecera(token_sentinela),
            )

        assert respuesta.status_code == 500
        (registro,) = _lineas(caplog, EVENTO_EJECUCION)
        assert registro.resultado == ResultadoDeEjecucion.EMPAQUETADO_MAL_FORMADO.value  # type: ignore[attr-defined]
        assert registro.tipo_error == "SalidaMalFormada"  # type: ignore[attr-defined]

    def test_una_excepcion_que_ninguna_rama_nombra_cae_en_no_clasificado(
        self,
        cliente_de_prueba: TestClient,
        token_sentinela: str,
        contrato_registrado: None,
        modulo_falso: InstalarModulo,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Ningún manejador cubre un `RuntimeError` desnudo, así que llega al
        500 del middleware de errores de Starlette. La línea igual sale, con el
        desenlace que corresponde y el nombre de la clase real."""
        modulo_falso(_fallar(RuntimeError("algo inesperado")))

        with caplog.at_level(logging.INFO, logger=NOMBRE_LOGGER):
            respuesta = cliente_de_prueba.post(
                _RUTA,
                files={"archivos": ("informe.xlsx", b"entrada", "application/octet-stream")},
                headers=_cabecera(token_sentinela),
            )

        assert respuesta.status_code == 500
        (registro,) = _lineas(caplog, EVENTO_EJECUCION)
        assert registro.resultado == ResultadoDeEjecucion.FALLO_NO_CLASIFICADO.value  # type: ignore[attr-defined]
        assert registro.tipo_error == "RuntimeError"  # type: ignore[attr-defined]

    def test_la_traza_del_hijo_llega_a_la_linea(
        self,
        cliente_de_prueba: TestClient,
        token_sentinela: str,
        contrato_registrado: None,
        modulo_falso: InstalarModulo,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """ADR 0022 designa la traza como material de logging: la respuesta es
        un 500 desnudo, así que la traza es lo único que hace diagnosticable la
        caída de un módulo."""
        traza = 'Traceback (most recent call last):\n  File "m.py", line 1\nKeyError: "col"'
        modulo_falso(_fallar(FalloDelModulo(clase="KeyError", mensaje="col", traza=traza)))

        with caplog.at_level(logging.INFO, logger=NOMBRE_LOGGER):
            respuesta = cliente_de_prueba.post(
                _RUTA,
                files={"archivos": ("informe.xlsx", b"entrada", "application/octet-stream")},
                headers=_cabecera(token_sentinela),
            )

        assert respuesta.content == b""  # la traza NO sale al cliente
        (registro,) = _lineas(caplog, EVENTO_EJECUCION)
        assert registro.traza == traza  # type: ignore[attr-defined]
        assert registro.tipo_error == "KeyError"  # type: ignore[attr-defined]


class TestLineaDeSaturacion:
    """Saturación por pre-adquisición del slot, igual que `tests/test_admision.py`:
    determinista, sin hilos en carrera y sin ningún hijo."""

    def test_el_503_emite_su_linea_sin_campos_de_cuerpo(
        self,
        monkeypatch: pytest.MonkeyPatch,
        cliente_de_prueba: TestClient,
        token_sentinela: str,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setenv("EJECUCIONES_MAX", "1")
        from app.core.configuracion import obtener_configuracion

        obtener_configuracion.cache_clear()
        obtener_semaforo.cache_clear()
        assert obtener_semaforo().acquire(blocking=False) is True
        try:
            with caplog.at_level(logging.INFO, logger=NOMBRE_LOGGER):
                respuesta = cliente_de_prueba.post(
                    _RUTA,
                    files={"archivos": ("x.xlsx", b"x", "application/octet-stream")},
                    headers=_cabecera(token_sentinela),
                )
        finally:
            obtener_semaforo().release()

        assert respuesta.status_code == 503
        (registro,) = _lineas(caplog, EVENTO_SATURACION)
        assert registro.metodo == "POST"  # type: ignore[attr-defined]
        assert registro.ruta_sin_validar == _RUTA  # type: ignore[attr-defined]
        assert registro.clave_sin_validar == _CLAVE  # type: ignore[attr-defined]
        assert registro.ejecuciones_max == 1  # type: ignore[attr-defined]
        # El cuerpo nunca se leyó: cualquiera de estos campos sería inventado.
        for campo in ("archivos", "bytes_recibidos", "duracion_ruta_ms"):
            assert not hasattr(registro, campo), f"la línea de saturación no debe traer {campo!r}"
        # Y la ejecución no ocurrió: no hay línea de ejecución que acompañarla.
        assert _lineas(caplog, EVENTO_EJECUCION) == []

    def test_una_ruta_con_salto_de_linea_no_forja_una_segunda_linea(
        self,
        semaforo_de_capacidad_uno_pre_adquirido: None,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Uvicorn percent-decodifica `scope["path"]` (`h11_impl.py:202`), así que
        un cliente puede meter un `%0a` y fabricar una línea de log falsa. Se
        ejercita el middleware directamente porque ningún cliente HTTP decente
        permite mandar una ruta con un salto de línea crudo."""
        ruta_forjada = '/interno/procesadores/clave\n{"evento": "saturacion", "falso": true}'

        with caplog.at_level(logging.INFO, logger=NOMBRE_LOGGER):
            with pytest.raises(ServicioSaturado):
                asyncio.run(
                    _correr_middleware(
                        {"type": "http", "method": "POST", "path": ruta_forjada},
                    )
                )

        (registro,) = _lineas(caplog, EVENTO_SATURACION)
        assert "\n" not in registro.ruta_sin_validar  # type: ignore[attr-defined]
        assert "\\x0a" in registro.ruta_sin_validar  # type: ignore[attr-defined]
        # Y una vez renderizada, la línea sigue siendo exactamente una línea.
        renderizado = FormateadorJsonLineas().format(registro)
        assert renderizado.count("\n") == 0
        assert json.loads(renderizado)["evento"] == EVENTO_SATURACION

    def test_un_scope_sin_metodo_ni_ruta_no_rompe_la_emision(
        self,
        semaforo_de_capacidad_uno_pre_adquirido: None,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """`scope.get`, nunca `scope[...]`: el log jamás debe ser lo que rompa
        la petición."""
        with caplog.at_level(logging.INFO, logger=NOMBRE_LOGGER):
            with pytest.raises(ServicioSaturado):
                asyncio.run(_correr_middleware({"type": "http"}))

        (registro,) = _lineas(caplog, EVENTO_SATURACION)
        assert registro.metodo == ""  # type: ignore[attr-defined]
        assert registro.ruta_sin_validar == ""  # type: ignore[attr-defined]


_ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


async def _receive() -> dict[str, Any]:
    return {"type": "http.request", "body": b"", "more_body": False}


async def _send(_mensaje: MutableMapping[str, Any]) -> None:
    return None


async def _app_interna(scope: Scope, receive: Receive, send: Send) -> None:
    return None


async def _correr_middleware(scope: Scope) -> None:
    await AdmisionDeBorde(_app_interna)(scope, _receive, _send)


@pytest.fixture
def semaforo_de_capacidad_uno_pre_adquirido(
    monkeypatch: pytest.MonkeyPatch, token_sentinela: str, limpiar_cache_configuracion: None
) -> Iterator[None]:
    """`EJECUCIONES_MAX=1` con el único slot ya ocupado: cualquier admisión
    posterior levanta `ServicioSaturado` sin depender de una carrera."""
    monkeypatch.setenv("EJECUCIONES_MAX", "1")
    assert obtener_semaforo().acquire(blocking=False) is True
    try:
        yield
    finally:
        obtener_semaforo().release()


class TestFormateadorJsonLineas:
    """`caplog.records` no pasa por ningún formateador, así que sin estas
    pruebas el renderizado quedaría sin cubrir por completo."""

    def test_un_objeto_json_parseable_por_linea_con_los_campos_de_extra(self) -> None:
        logger = logging.getLogger("app.prueba_del_formateador")
        logger.setLevel(logging.INFO)
        capturados: list[logging.LogRecord] = []

        class _Captura(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                capturados.append(record)

        manejador = _Captura()
        logger.addHandler(manejador)
        try:
            logger.info(
                "ejecucion terminada",
                extra={"evento": EVENTO_EJECUCION, "clave": "passthrough", "archivos": 3},
            )
        finally:
            logger.removeHandler(manejador)

        (registro,) = capturados
        renderizado = FormateadorJsonLineas().format(registro)
        assert renderizado.count("\n") == 0
        carga = json.loads(renderizado)
        assert carga["mensaje"] == "ejecucion terminada"
        assert carga["nivel"] == "INFO"
        assert carga["logger"] == "app.prueba_del_formateador"
        assert carga["evento"] == EVENTO_EJECUCION
        assert carga["clave"] == "passthrough"
        assert carga["archivos"] == 3
        assert isinstance(carga["ts"], str)

    def test_la_linea_de_ejecucion_real_se_renderiza_completa(
        self,
        cliente_de_prueba: TestClient,
        token_sentinela: str,
        contrato_registrado: None,
        modulo_falso: InstalarModulo,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        modulo_falso(_passthrough)

        with caplog.at_level(logging.INFO, logger=NOMBRE_LOGGER):
            cliente_de_prueba.post(
                _RUTA,
                files={"archivos": ("informe.xlsx", b"entrada", "application/octet-stream")},
                headers=_cabecera(token_sentinela),
            )

        (registro,) = _lineas(caplog, EVENTO_EJECUCION)
        carga = json.loads(FormateadorJsonLineas().format(registro))
        assert set(carga) >= {
            "ts",
            "nivel",
            "logger",
            "mensaje",
            "evento",
            "clave",
            "archivos",
            "bytes_recibidos",
            "duracion_ruta_ms",
            "resultado",
        }
        assert carga["resultado"] == ResultadoDeEjecucion.EXITO.value


_TOKEN_VISIBILIDAD = "sentinela-visibilidad-6d41ba"
_CENTINELA_SIN_CONFIGURAR = "CENTINELA-QUE-NO-DEBE-VERSE"

# Reproduce el arranque canónico del README (`uv run uvicorn app.main:app`) en
# el orden real de uvicorn: `Config.configure_logging()` corre `dictConfig` y
# recién después `Config.load()` importa `app.main:app`. La salida estándar se
# desvía a un sumidero durante toda la petición, así que cualquier línea que
# aparezca en la captura del subproceso llegó necesariamente por `stderr`.
_SNIPPET_VISIBILIDAD = f"""
import io, logging, logging.config, os
from contextlib import redirect_stdout
from types import MappingProxyType

os.environ["TOKEN_SERVICIO"] = {_TOKEN_VISIBILIDAD!r}

import uvicorn.config

logging.config.dictConfig(uvicorn.config.LOGGING_CONFIG)

# CONTROL. Sin la infraestructura del item #14 un logger `app.*` en INFO no
# emite nada: la raiz queda sin handler y sin nivel, y `lastResort` es WARNING.
# Si este centinela apareciera en la salida, el resto de la prueba no probaria
# absolutamente nada.
logging.getLogger("app.control").info({_CENTINELA_SIN_CONFIGURAR!r})

import app  # noqa: F401 - fija spawn primero, como en produccion
from fastapi.testclient import TestClient

from app.core import contrato as contrato_modulo
from app.core import pipeline
from app.core.contrato import CONTRATO_POR_DEFECTO
from app.core.tipos import ArchivoSalida
from app.main import app as aplicacion

def _modulo_falso(*, clave, entradas, timeout):
    return [
        ArchivoSalida(
            nombre_propuesto="salida.bin",
            ruta_temporal=entradas[0].ruta_temporal,
            tipo_mime="application/octet-stream",
        )
    ]


pipeline.ejecutar_modulo = _modulo_falso

sumidero = io.StringIO()
with redirect_stdout(sumidero):
    with TestClient(aplicacion) as cliente:
        # Se sustituye la tabla DENTRO del `with`, no antes: el item #11
        # contrasta `REGISTRY` contra los contratos durante el lifespan, y una
        # tabla que solo tuviera "visible" dejaria a los dos passthrough
        # registrados sin fila -- el arranque fallaria, que es exactamente lo
        # que ese chequeo tiene que hacer. Acá se parchea una vez arrancado,
        # igual que en las pruebas en proceso de este mismo archivo.
        contrato_modulo._TABLA_CONTRATOS = MappingProxyType({{"visible": CONTRATO_POR_DEFECTO}})
        respuesta = cliente.post(
            "/interno/procesadores/visible",
            files={{"archivos": ("informe.xlsx", b"abcde", "application/octet-stream")}},
            headers={{"Authorization": "Bearer {_TOKEN_VISIBILIDAD}"}},
        )

assert respuesta.status_code == 200, respuesta.status_code
"""


class TestVisibilidad:
    """La prueba que impide que este ítem sea un no-op silencioso.

    Todo lo demás en este archivo se apoya en `caplog`, que engancha un handler
    en la raíz y le baja el nivel — exactamente las dos cosas que producción no
    tiene. Ésta corre un intérprete fresco, aplica `LOGGING_CONFIG` de uvicorn
    igual que el servidor real, importa `app.main` (que es lo que aplica
    `configurar_logging()`) y dispara una petición completa contra la app de
    producción. Lo que afirma es que un operador ve la línea.
    """

    def test_la_linea_llega_a_stderr_con_la_configuracion_real(self) -> None:
        resultado = ejecutar_snippet(_SNIPPET_VISIBILIDAD)
        assert resultado.codigo_salida == 0, resultado.salida

        # El control: antes de `configurar_logging()` no se emite nada.
        assert _CENTINELA_SIN_CONFIGURAR not in resultado.salida

        cargas = []
        for linea in resultado.salida.splitlines():
            try:
                carga = json.loads(linea)
            except json.JSONDecodeError:
                continue
            if isinstance(carga, dict) and carga.get("evento") == EVENTO_EJECUCION:
                cargas.append(carga)

        assert cargas, (
            "ninguna linea de ejecucion llego a stderr con la configuracion real; "
            f"salida capturada:\n{resultado.salida}"
        )
        (carga,) = cargas
        assert carga["clave"] == "visible"
        assert carga["archivos"] == 1
        assert carga["bytes_recibidos"] == 5
        assert carga["resultado"] == ResultadoDeEjecucion.EXITO.value
        assert carga["duracion_ruta_ms"] >= 0.0
        assert _TOKEN_VISIBILIDAD not in resultado.salida
