"""Prueba de fuga en el access log de uvicorn (design.md §8, V10/V11).

`caplog` no puede usarse: `uvicorn.access` se configura con
`propagate: False` (V11), así que un test basado en `caplog` capturaría
nada y pasaría vacuamente -- exactamente el modo de fallo que este cambio
existe para evitar. Por eso se levanta un `uvicorn.Server` real en un hilo
de fondo, en el puerto 0, y se adjunta un `logging.Handler` propio
directamente al logger `uvicorn.access`.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterator

import httpx
import pytest
import uvicorn
from fastapi import APIRouter, Depends, FastAPI

from app.core.seguridad import exigir_token, registrar_manejador_401

pytestmark = pytest.mark.usefixtures("limpiar_cache_configuracion")

_SENTINELA = "sentinela-access-log-4c19be"


def _crear_app_de_prueba() -> FastAPI:
    app = FastAPI()  # debug omitido -> False
    registrar_manejador_401(app)
    router = APIRouter(dependencies=[Depends(exigir_token)])

    @router.get("/protegido")
    def protegido() -> dict[str, str]:
        return {"ok": "si"}

    app.include_router(router)
    return app


class _CapturaLineas(logging.Handler):
    """Handler mínimo que guarda cada línea de log emitida."""

    def __init__(self) -> None:
        super().__init__()
        self.lineas: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lineas.append(record.getMessage())


@pytest.fixture
def servidor_uvicorn(token_sentinela: str) -> Iterator[str]:
    """Levanta un `uvicorn.Server` real en un hilo de fondo, puerto 0."""
    config = uvicorn.Config(
        _crear_app_de_prueba(),
        host="127.0.0.1",
        port=0,
        log_level="info",
        access_log=True,
    )
    servidor = uvicorn.Server(config)
    hilo = threading.Thread(target=servidor.run, daemon=True)
    hilo.start()
    try:
        # Espera activa acotada a que el socket esté listo.
        limite = time.monotonic() + 5.0
        while not servidor.started and time.monotonic() < limite:
            time.sleep(0.01)
        assert servidor.started, "el servidor uvicorn de prueba no arrancó a tiempo"
        (host, puerto) = servidor.servers[0].sockets[0].getsockname()[:2]
        yield f"http://{host}:{puerto}"
    finally:
        servidor.should_exit = True
        hilo.join(timeout=5.0)


def test_access_log_no_contiene_valores_de_cabecera(servidor_uvicorn: str) -> None:
    captura = _CapturaLineas()
    logger_access = logging.getLogger("uvicorn.access")
    logger_access.addHandler(captura)
    try:
        respuesta = httpx.get(
            f"{servidor_uvicorn}/protegido",
            headers={"Authorization": f"Bearer {_SENTINELA}"},
        )
        assert respuesta.status_code in (200, 401)

        limite = time.monotonic() + 5.0
        while not captura.lineas and time.monotonic() < limite:
            time.sleep(0.01)
    finally:
        logger_access.removeHandler(captura)

    assert captura.lineas, (
        "no se capturó ninguna línea del access log -- el test no debe pasar vacuamente"
    )
    texto = "\n".join(captura.lineas)
    assert "GET" in texto
    assert "/protegido" in texto
    assert _SENTINELA not in texto
    assert "Bearer" not in texto
