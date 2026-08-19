"""Pruebas de `app.core.ejecucion`, mitad de admisión (ítem #8, S2, design.md §3/§7).

Behaviourales, sin AST ni inspección estructural (TDD estricto deshabilitado).

**Desviación deliberada, marcada a propósito**: la tarea 2.8 enumera
`EjecucionExpirada` entre las salidas del `finally` a probar, pero esa clase
pertenece a la mitad de proceso de `ejecucion.py`, que esta rebanada (S2) no
embarca -- llega en S3 (tasks.md, Fase 3). El diseño mismo explica por qué
esto no debilita la prueba: "the middleware does not know or care which one
happened" (design.md §3) -- el `finally` de `admitir()` cubre cualquier
excepción o retorno de `await self.app(...)` por igual, sin inspeccionar su
tipo. `_TimeoutSimulado`, definida localmente en este módulo, hace el mismo
papel de "excepción no tipificada que representa un timeout" sin depender de
código que S3 todavía no escribió; cuando S3 exista, esta clase se puede
sustituir por `EjecucionExpirada` sin que la prueba deba cambiar de forma.

Saturación siempre por pre-adquisición del slot, nunca por hilos en carrera
(design.md §10): la suite queda determinista y rápida.
"""

from __future__ import annotations

import asyncio
import shutil
from collections.abc import Awaitable, Callable, Iterator, MutableMapping
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.types import Receive, Scope, Send

from app.core.ejecucion import AdmisionDeBorde, ServicioSaturado, obtener_semaforo
from app.core.errores import ErrorCantidad
from app.core.temporales import _EN_VUELO, _raiz
from app.main import crear_app

_CLAVE = "cualquiera"
_RUTA = f"/interno/procesadores/{_CLAVE}"


def _cabecera(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class _TimeoutSimulado(Exception):
    """Sustituto local de `EjecucionExpirada` (mitad de proceso, S3) -- ver
    docstring del módulo. El middleware no distingue su tipo, así que sirve
    igual de bien para probar el `finally` de `admitir()`."""


@pytest.fixture
def semaforo_de_capacidad_uno(
    monkeypatch: pytest.MonkeyPatch, token_sentinela: str, limpiar_cache_configuracion: None
) -> None:
    """`EJECUCIONES_MAX=1`: hace determinista cualquier aserción de capacidad
    sin depender del valor por defecto (2) de `configuracion.py`."""
    monkeypatch.setenv("EJECUCIONES_MAX", "1")


@pytest.fixture(autouse=True)
def _estado_de_temporales_limpio() -> Iterator[None]:
    """`_EN_VUELO` y la raíz dedicada son estado de módulo compartido; no debe
    filtrarse entre pruebas (mismo patrón que `tests/test_recepcion.py`)."""
    _EN_VUELO.clear()
    shutil.rmtree(_raiz(), ignore_errors=True)
    yield
    _EN_VUELO.clear()
    shutil.rmtree(_raiz(), ignore_errors=True)


class TestAdmitir:
    """Pruebas unitarias de `admitir()` (tarea 2.7): sin app, sin `TestClient`."""

    def test_libera_al_retornar_normalmente(self, semaforo_de_capacidad_uno: None) -> None:
        from app.core.ejecucion import admitir

        with admitir():
            pass
        # Capacidad restaurada: una segunda adquisición inmediata tiene éxito.
        assert obtener_semaforo().acquire(blocking=False) is True
        obtener_semaforo().release()

    def test_libera_al_propagar_una_excepcion(self, semaforo_de_capacidad_uno: None) -> None:
        from app.core.ejecucion import admitir

        with pytest.raises(RuntimeError):
            with admitir():
                raise RuntimeError("fallo dentro del cuerpo admitido")
        assert obtener_semaforo().acquire(blocking=False) is True
        obtener_semaforo().release()

    def test_adquisicion_fallida_levanta_servicio_saturado_y_no_libera_nada(
        self, semaforo_de_capacidad_uno: None
    ) -> None:
        from app.core.ejecucion import admitir

        # Slot único ya ocupado por esta prueba -- no por `admitir()`.
        assert obtener_semaforo().acquire(blocking=False) is True
        try:
            with pytest.raises(ServicioSaturado):
                with admitir():
                    pytest.fail("el cuerpo de admitir() no debe ejecutarse nunca")
            # El fallo de adquisición no liberó nada de más: el slot sigue
            # ocupado por la adquisición externa de esta prueba.
            assert obtener_semaforo().acquire(blocking=False) is False
        finally:
            obtener_semaforo().release()


_ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


async def _receive() -> dict[str, Any]:
    return {"type": "http.request", "body": b"", "more_body": False}


async def _send(_message: MutableMapping[str, Any]) -> None:
    return None


async def _correr_middleware(app_interno: _ASGIApp) -> None:
    middleware = AdmisionDeBorde(app_interno)
    await middleware({"type": "http"}, _receive, _send)


class TestAdmisionDeBordeLiberaEnTodaSalida:
    """Tarea 2.8: una app interna diminuta, envuelta directamente en
    `AdmisionDeBorde` -- sin pipeline, sin hijo, en milisegundos (design.md
    §10, spec "The admission slot releases on all four exit paths").
    """

    async def _app_exitosa(self, scope: Scope, receive: Receive, send: Send) -> None:
        return None

    async def _app_error_tipificado(self, scope: Scope, receive: Receive, send: Send) -> None:
        raise ErrorCantidad(minimo=1, maximo=5, recibido=0)

    async def _app_excepcion_sin_tipificar(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        raise RuntimeError("excepción de módulo sin tipificar")

    async def _app_timeout_simulado(self, scope: Scope, receive: Receive, send: Send) -> None:
        raise _TimeoutSimulado

    async def _app_not_implemented(self, scope: Scope, receive: Receive, send: Send) -> None:
        raise NotImplementedError

    @pytest.mark.parametrize(
        "app_interno,excepcion_esperada",
        [
            ("_app_exitosa", None),
            ("_app_error_tipificado", ErrorCantidad),
            ("_app_excepcion_sin_tipificar", RuntimeError),
            ("_app_timeout_simulado", _TimeoutSimulado),
            ("_app_not_implemented", NotImplementedError),
        ],
        ids=["exito", "error_tipificado", "excepcion_sin_tipificar", "timeout", "not_implemented"],
    )
    def test_libera_tras_cada_salida(
        self,
        semaforo_de_capacidad_uno: None,
        app_interno: str,
        excepcion_esperada: type[Exception] | None,
    ) -> None:
        app = getattr(self, app_interno)
        if excepcion_esperada is None:
            asyncio.run(_correr_middleware(app))
        else:
            with pytest.raises(excepcion_esperada):
                asyncio.run(_correr_middleware(app))
        # Capacidad de 1 restaurada tras cada una de las cinco salidas.
        assert obtener_semaforo().acquire(blocking=False) is True
        obtener_semaforo().release()

    def test_libera_tras_una_tarea_cancelada(self, semaforo_de_capacidad_uno: None) -> None:
        async def _app_que_cuelga(scope: Scope, receive: Receive, send: Send) -> None:
            await asyncio.sleep(10)

        async def _escenario() -> None:
            tarea = asyncio.ensure_future(_correr_middleware(_app_que_cuelga))
            await asyncio.sleep(0)  # deja que la tarea entre en el `with admitir():`
            tarea.cancel()
            with pytest.raises(asyncio.CancelledError):
                await tarea

        asyncio.run(_escenario())
        assert obtener_semaforo().acquire(blocking=False) is True
        obtener_semaforo().release()


@pytest.fixture
def cliente_de_prueba(
    token_sentinela: str, limpiar_cache_configuracion: None
) -> Iterator[TestClient]:
    with TestClient(crear_app(), raise_server_exceptions=False) as cliente:
        yield cliente


class TestSaturacionEndToEnd:
    """Tareas 2.9-2.12: app real, `TestClient`, saturación por pre-adquisición."""

    def test_503_con_todos_los_slots_ocupados(
        self,
        monkeypatch: pytest.MonkeyPatch,
        cliente_de_prueba: TestClient,
        token_sentinela: str,
    ) -> None:
        monkeypatch.setenv("EJECUCIONES_MAX", "1")
        from app.core.configuracion import obtener_configuracion

        obtener_configuracion.cache_clear()
        obtener_semaforo.cache_clear()
        assert obtener_semaforo().acquire(blocking=False) is True
        try:
            respuesta = cliente_de_prueba.post(
                _RUTA,
                files={"archivos": ("x.xlsx", b"x", "application/octet-stream")},
                headers=_cabecera(token_sentinela),
            )
            assert respuesta.status_code == 503
            assert respuesta.content == b""
        finally:
            obtener_semaforo().release()

    def test_saturacion_no_lee_cuerpo_ni_escribe_temporal(
        self,
        monkeypatch: pytest.MonkeyPatch,
        cliente_de_prueba: TestClient,
        token_sentinela: str,
    ) -> None:
        monkeypatch.setenv("EJECUCIONES_MAX", "1")
        from app.core.configuracion import obtener_configuracion

        obtener_configuracion.cache_clear()
        obtener_semaforo.cache_clear()
        assert obtener_semaforo().acquire(blocking=False) is True
        try:
            # Multipart deliberadamente malformado: si el parser llegara a
            # correr, un 422 (no un 503) lo delataría.
            respuesta = cliente_de_prueba.post(
                _RUTA,
                headers={**_cabecera(token_sentinela), "content-type": "multipart/form-data"},
                content=b"esto no es un cuerpo multipart valido",
            )
            assert respuesta.status_code == 503
            raiz = _raiz()
            hijos_de_peticion = (
                [h for h in raiz.iterdir() if h.name.startswith("pet-")] if raiz.is_dir() else []
            )
            assert hijos_de_peticion == []
        finally:
            obtener_semaforo().release()

    def test_token_invalido_da_401_no_503_pese_a_saturacion(
        self,
        monkeypatch: pytest.MonkeyPatch,
        cliente_de_prueba: TestClient,
    ) -> None:
        monkeypatch.setenv("EJECUCIONES_MAX", "1")
        from app.core.configuracion import obtener_configuracion

        obtener_configuracion.cache_clear()
        obtener_semaforo.cache_clear()
        assert obtener_semaforo().acquire(blocking=False) is True
        try:
            respuesta = cliente_de_prueba.post(
                _RUTA,
                files={"archivos": ("x.xlsx", b"x", "application/octet-stream")},
                headers=_cabecera("credencial-incorrecta"),
            )
            assert respuesta.status_code == 401
            # La petición nunca llegó a `admitir()`: el slot pre-adquirido por
            # esta prueba sigue siendo el único ocupado, ninguno se sumó.
            assert obtener_semaforo().acquire(blocking=False) is False
        finally:
            obtener_semaforo().release()

    def test_salud_no_se_ve_afectada_por_la_saturacion(
        self,
        monkeypatch: pytest.MonkeyPatch,
        cliente_de_prueba: TestClient,
    ) -> None:
        monkeypatch.setenv("EJECUCIONES_MAX", "1")
        from app.core.configuracion import obtener_configuracion

        obtener_configuracion.cache_clear()
        obtener_semaforo.cache_clear()
        assert obtener_semaforo().acquire(blocking=False) is True
        try:
            respuesta = cliente_de_prueba.get("/salud")
            assert respuesta.status_code == 200
        finally:
            obtener_semaforo().release()
