"""Pruebas de la frontera autenticada por montaje (ítem #6, design.md §2, §8 filas 1-5, 8).

`crear_app()` monta `/interno` con `AutenticacionDeBorde` (design.md §2.3;
ADR 0019). Estas pruebas cubren el comportamiento contra la aplicación
embarcada, no una app de prueba propia: la frontera solo existe ahí.
"""

from __future__ import annotations

import anyio
import pytest
from fastapi.testclient import TestClient
from starlette.types import Message, Scope

from app.main import crear_app

pytestmark = pytest.mark.usefixtures("limpiar_cache_configuracion")


def test_rechazo_no_consume_el_cuerpo(token_sentinela: str) -> None:
    """Fila 1: cabeceras crudas de ASGI, `receive` espía, sin `TestClient`.

    Simula una petición grande cuyo cuerpo nunca se termina de enviar. Si el
    middleware llamara a `receive()` antes de rechazar, esta prueba se
    colgaría o la lista espía dejaría de estar vacía.
    """
    recibir_espia: list[bytes] = []

    async def receive() -> Message:
        recibir_espia.append(b"cuerpo-nunca-deberia-leerse")
        return {"type": "http.request", "body": b"x" * 1000, "more_body": False}

    mensajes_enviados: list[Message] = []

    async def send(mensaje: Message) -> None:
        mensajes_enviados.append(mensaje)

    scope: Scope = {
        "type": "http",
        "method": "POST",
        "path": "/interno/procesadores/contado-carga/ejecutar",
        "headers": [
            (b"content-type", b"multipart/form-data; boundary=x"),
            (b"content-length", b"26214400"),
        ],
        "app": crear_app(),
    }

    async def ejecutar() -> None:
        aplicacion = crear_app()
        await aplicacion(scope, receive, send)

    anyio.run(ejecutar)

    assert recibir_espia == []
    inicio = next(m for m in mensajes_enviados if m["type"] == "http.response.start")
    cuerpo = next(m for m in mensajes_enviados if m["type"] == "http.response.body")
    assert inicio["status"] == 401
    assert cuerpo["body"] == b""
    cabeceras = dict(inicio["headers"])
    assert cabeceras.get(b"www-authenticate") == b"Bearer"


@pytest.fixture
def cliente() -> TestClient:
    return TestClient(crear_app())


_VARIANTES_SIN_TOKEN_VALIDO = [
    ("sin_cabecera", {}),
    ("token_incorrecto", {"Authorization": "Bearer credencial-incorrecta"}),
    ("cabecera_malformada", {"Authorization": "Basic algo"}),
]


@pytest.mark.parametrize(
    "nombre,headers", _VARIANTES_SIN_TOKEN_VALIDO, ids=[v[0] for v in _VARIANTES_SIN_TOKEN_VALIDO]
)
def test_rechazo_desde_la_app_embarcada(
    cliente: TestClient, token_sentinela: str, nombre: str, headers: dict[str, str]
) -> None:
    """Fila 2: 401 real, desde la app embarcada, no un 500 sin manejar."""
    respuesta = cliente.get("/interno/x", headers=headers)
    assert respuesta.status_code == 401
    assert respuesta.content == b""
    assert respuesta.headers.get("www-authenticate") == "Bearer"


def test_token_correcto_atraviesa_la_frontera(cliente: TestClient, token_sentinela: str) -> None:
    """Fila 3: con token correcto, el middleware deja pasar -> 404 (montaje vacío)."""
    respuesta = cliente.get("/interno/x", headers={"Authorization": f"Bearer {token_sentinela}"})
    assert respuesta.status_code == 404


def test_salud_y_documentacion_fuera_de_la_frontera(cliente: TestClient) -> None:
    """Fila 4: sin cabecera Authorization, /salud y las rutas de documentación siguen en 200."""
    assert cliente.get("/salud").status_code == 200
    assert cliente.get("/docs").status_code == 200
    assert cliente.get("/openapi.json").status_code == 200


_SENTINELA_TOKEN_BORDE = "sentinela-unico-de-borde-4a7d1c9e02"

_SNIPPET_SENTINELA_AUSENTE_EN_SALIDA = f"""
import os
os.environ["TOKEN_SERVICIO"] = {_SENTINELA_TOKEN_BORDE!r}
import app  # noqa: F401 - fija spawn primero, como en producción
from fastapi.testclient import TestClient
from app.main import crear_app

with TestClient(crear_app()) as cliente:
    aceptada = cliente.get(
        "/interno/x", headers={{"Authorization": "Bearer {_SENTINELA_TOKEN_BORDE}"}}
    )
    assert aceptada.status_code == 404
    rechazada = cliente.get(
        "/interno/x", headers={{"Authorization": "Bearer credencial-incorrecta"}}
    )
    assert rechazada.status_code == 401
"""


def test_sentinela_ausente_de_salida_combinada_en_la_frontera() -> None:
    """Fila 8: el token no aparece en la salida capturada, ahora también por /interno."""
    from tests.ayudas.subproceso import ejecutar_snippet

    resultado = ejecutar_snippet(_SNIPPET_SENTINELA_AUSENTE_EN_SALIDA)
    assert resultado.codigo_salida == 0, resultado.salida
    assert _SENTINELA_TOKEN_BORDE not in resultado.salida
