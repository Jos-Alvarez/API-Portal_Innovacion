"""Pruebas de `GET /salud` (D3/D5 del diseño)."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.usefixtures("limpiar_cache_configuracion")


def test_salud_responde_200_sin_token(token_sentinela: str) -> None:
    from app.main import crear_app

    with TestClient(crear_app()) as cliente:
        respuesta = cliente.get("/salud")
    assert respuesta.status_code == 200
    assert respuesta.json() == {"estado": "vivo"}


def test_salud_no_intenta_ninguna_conexion_de_red(token_sentinela: str) -> None:
    """Ninguna conexión saliente *externa* durante `GET /salud`.

    En Windows, `socket.socketpair()` se emula con un par de sockets TCP
    loopback reales (el propio proceso conectándose a sí mismo) como parte
    de la maquinaria interna del event loop de asyncio/anyio -- eso dispara
    `socket.connect` sin que el código de la aplicación abra nada. Por eso
    el filtro excluye direcciones de loopback y solo falla ante una
    conexión saliente real (a un host que no es el propio proceso).
    """
    from app.main import crear_app

    eventos: list[tuple[str, object]] = []

    def _hook(nombre: str, args: object) -> None:
        if nombre == "socket.connect":
            eventos.append((nombre, args))

    sys.addaudithook(_hook)

    with TestClient(crear_app()) as cliente:
        respuesta = cliente.get("/salud")

    assert respuesta.status_code == 200

    conexiones_externas = [(nombre, args) for nombre, args in eventos if not _es_loopback(args)]
    assert conexiones_externas == []


def _es_loopback(args: object) -> bool:
    try:
        direccion = args[1]  # type: ignore[index]
        host = direccion[0] if isinstance(direccion, tuple) else direccion
    except (TypeError, IndexError):
        return True
    return host in ("127.0.0.1", "::1", "localhost")


def test_salud_modulo_no_importa_nada_de_app() -> None:
    """AST scan: `app/salud.py` no debe importar ningún `app.*` (D5)."""
    ruta = Path(__file__).resolve().parent.parent / "app" / "salud.py"
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))

    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            for alias in nodo.names:
                assert not alias.name.startswith("app"), (
                    f"app/salud.py no debe importar {alias.name!r}"
                )
        elif isinstance(nodo, ast.ImportFrom):
            modulo = nodo.module or ""
            assert not modulo.startswith("app"), f"app/salud.py no debe importar desde {modulo!r}"


def test_app_falla_al_arrancar_sin_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TOKEN_SERVICIO", raising=False)
    from app.main import crear_app

    with pytest.raises(Exception):  # noqa: B017 - ConfiguracionInvalida en el lifespan
        with TestClient(crear_app()):
            pass


def test_app_arranca_con_token(token_sentinela: str) -> None:
    from app.main import crear_app

    with TestClient(crear_app()) as cliente:
        respuesta = cliente.get("/salud")
    assert respuesta.status_code == 200
