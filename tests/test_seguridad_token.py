"""Pruebas del token de servicio (ítem #2 del backlog, design.md §2-§9).

Router de pruebas: `crear_app_de_prueba()` vive únicamente en este módulo
(nunca en `app/`) porque cablearlo en la aplicación embarcada añadiría una
ruta que el backlog no autoriza y rompería el requisito de la spec de que
el conjunto de rutas embarcado no cambia (design.md §7).
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.routing import Mount

from app.core.seguridad import _coincide, _credencial_presentada, _token_esperado

pytestmark = pytest.mark.usefixtures("limpiar_cache_configuracion")


def _peticion(headers: list[tuple[bytes, bytes]]) -> Request:
    """Construye un `Request` de Starlette con las cabeceras exactas dadas.

    Se arma el `scope` a mano, en vez de pasar por `TestClient`, porque
    estas pruebas unitarias necesitan cabeceras crudas (incluida una
    duplicada) sin que un cliente HTTP intermedie la codificación.
    """
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/protegido",
        "headers": headers,
    }
    return Request(scope)


class TestCredencialPresentada:
    def test_cabecera_ausente(self) -> None:
        assert _credencial_presentada(_peticion([])) is None

    def test_esquema_incorrecto(self) -> None:
        peticion = _peticion([(b"authorization", b"Basic algo")])
        assert _credencial_presentada(peticion) is None

    def test_sin_espacio_tras_el_esquema(self) -> None:
        peticion = _peticion([(b"authorization", b"Bearer")])
        assert _credencial_presentada(peticion) is None

    def test_credencial_vacia(self) -> None:
        peticion = _peticion([(b"authorization", b"Bearer ")])
        assert _credencial_presentada(peticion) is None

    def test_espacios_irregulares(self) -> None:
        peticion = _peticion([(b"authorization", b"Bearer  x")])
        assert _credencial_presentada(peticion) == " x"

    def test_credencial_no_ascii_como_bytes(self) -> None:
        # V8/V2: la cabecera cruda llega en bytes; Starlette la decodifica
        # como latin-1. "clavé" en UTF-8 es b"Bearer clav\xc3\xa9".
        peticion = _peticion([(b"authorization", "Bearer clavé".encode())])
        credencial = _credencial_presentada(peticion)
        assert credencial is not None
        assert credencial.encode("latin-1") == "clavé".encode()

    def test_cabeceras_authorization_duplicadas(self) -> None:
        peticion = _peticion(
            [
                (b"authorization", b"Bearer uno"),
                (b"authorization", b"Bearer dos"),
            ]
        )
        assert _credencial_presentada(peticion) is None

    def test_cabecera_bien_formada(self) -> None:
        peticion = _peticion([(b"authorization", b"Bearer credencial-valida")])
        assert _credencial_presentada(peticion) == "credencial-valida"

    def test_esquema_es_insensible_a_mayusculas(self) -> None:
        peticion = _peticion([(b"authorization", b"bearer credencial-valida")])
        assert _credencial_presentada(peticion) == "credencial-valida"


class TestCoincide:
    def test_bytes_iguales(self) -> None:
        assert _coincide(b"igual", b"igual") is True

    def test_bytes_distintos(self) -> None:
        assert _coincide(b"uno", b"otro") is False


class TestTokenEsperado:
    def test_devuelve_bytes_utf8_del_token_configurado(self, token_sentinela: str) -> None:
        assert _token_esperado() == token_sentinela.encode("utf-8")


def crear_app_de_prueba() -> FastAPI:
    """Router de pruebas: nunca se cablea en `app/main.py` (design.md §7)."""
    from app.core.seguridad import exigir_token, registrar_manejador_401

    app = FastAPI()  # debug omitido -> False
    registrar_manejador_401(app)
    router = APIRouter(dependencies=[Depends(exigir_token)])

    @router.get("/protegido")
    def protegido() -> dict[str, str]:
        return {"ok": "si"}

    app.include_router(router)
    return app


@pytest.fixture
def cliente_de_prueba(token_sentinela: str) -> Iterator[TestClient]:
    with TestClient(crear_app_de_prueba()) as cliente:
        yield cliente


def test_token_valido_alcanza_el_endpoint(
    cliente_de_prueba: TestClient, token_sentinela: str
) -> None:
    respuesta = cliente_de_prueba.get(
        "/protegido", headers={"Authorization": f"Bearer {token_sentinela}"}
    )
    assert respuesta.status_code == 200
    assert respuesta.json() == {"ok": "si"}


_TipoHeaders = dict[str, str] | dict[str, bytes] | list[tuple[str, str]]
_VARIANTES_MALFORMADAS: list[tuple[str, _TipoHeaders]] = [
    ("cabecera_ausente", {}),
    ("esquema_incorrecto", {"Authorization": "Basic algo"}),
    ("sin_espacio_tras_esquema", {"Authorization": "Bearer"}),
    ("credencial_vacia", {"Authorization": "Bearer "}),
    ("espacios_irregulares", {"Authorization": "Bearer  x "}),
    ("no_ascii", {"Authorization": "Bearer clavé".encode()}),
    (
        "cabeceras_duplicadas",
        [("Authorization", "Bearer uno"), ("Authorization", "Bearer dos")],
    ),
    ("bien_formada_pero_incorrecta", {"Authorization": "Bearer credencial-incorrecta"}),
]


@pytest.mark.parametrize(
    "nombre,headers", _VARIANTES_MALFORMADAS, ids=[v[0] for v in _VARIANTES_MALFORMADAS]
)
def test_respuestas_de_rechazo_son_identicas(
    cliente_de_prueba: TestClient,
    token_sentinela: str,
    nombre: str,
    headers: dict[str, str] | list[tuple[str, str]],
) -> None:
    if isinstance(headers, list):
        respuesta = cliente_de_prueba.get("/protegido", headers=headers)
    else:
        respuesta = cliente_de_prueba.get("/protegido", headers=headers)
    assert respuesta.status_code == 401
    assert respuesta.content == b""
    assert respuesta.headers.get("www-authenticate") == "Bearer"


def test_todas_las_respuestas_de_rechazo_son_byte_identicas(
    cliente_de_prueba: TestClient, token_sentinela: str
) -> None:
    huellas = set()
    for _nombre, headers in _VARIANTES_MALFORMADAS:
        if isinstance(headers, list):
            respuesta = cliente_de_prueba.get("/protegido", headers=headers)
        else:
            respuesta = cliente_de_prueba.get("/protegido", headers=headers)
        huellas.add(
            (respuesta.status_code, respuesta.content, tuple(sorted(respuesta.headers.items())))
        )
    assert len(huellas) == 1


def test_no_ascii_es_aceptado(
    cliente_de_prueba: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Spec: "A non-ASCII token is accepted". Token configurado con carácter
    # no-ASCII; el cliente lo envía exactamente como bytes UTF-8.
    from app.core.configuracion import obtener_configuracion

    obtener_configuracion.cache_clear()
    monkeypatch.setenv("TOKEN_SERVICIO", "clavé-secreta")
    obtener_configuracion.cache_clear()
    respuesta = cliente_de_prueba.get(
        "/protegido", headers={"Authorization": "Bearer clavé-secreta".encode()}
    )
    assert respuesta.status_code == 200
    obtener_configuracion.cache_clear()


_SENTINELA_TOKEN_SEGURIDAD = "sentinela-unico-de-seguridad-7cd39fa1e6"

# El sentinela viaja como token válido y también aparece, sin coincidir, en la
# petición rechazada (una credencial distinta). El intérprete es fresco (V. la
# nota de módulo de tests/ayudas/subproceso.py): el estado de un intérprete ya
# usado por pytest no sirve para probar ausencia de fuga. Aquí no se prueba
# solo el sitio de desenvoltorio (eso ya lo cubre TestTokenEsperado), sino que
# ninguna ruta -- incluidas las que este archivo no enumeró -- imprime el
# secreto: FastAPI, Starlette y TestClient también podrían hacerlo.
_SNIPPET_SENTINELA_AUSENTE_EN_SALIDA = f"""
import os
os.environ["TOKEN_SERVICIO"] = {_SENTINELA_TOKEN_SEGURIDAD!r}
import app  # noqa: F401 - fija spawn primero, como en producción
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient
from app.core.seguridad import exigir_token, registrar_manejador_401

aplicacion = FastAPI()
registrar_manejador_401(aplicacion)
enrutador = APIRouter(dependencies=[Depends(exigir_token)])


@enrutador.get("/protegido")
def protegido() -> dict[str, str]:
    return {{"ok": "si"}}


aplicacion.include_router(enrutador)

with TestClient(aplicacion) as cliente:
    aceptada = cliente.get(
        "/protegido", headers={{"Authorization": "Bearer {_SENTINELA_TOKEN_SEGURIDAD}"}}
    )
    assert aceptada.status_code == 200
    rechazada = cliente.get(
        "/protegido", headers={{"Authorization": "Bearer credencial-incorrecta"}}
    )
    assert rechazada.status_code == 401
"""


def test_sentinela_ausente_de_salida_combinada() -> None:
    from tests.ayudas.subproceso import ejecutar_snippet

    resultado = ejecutar_snippet(_SNIPPET_SENTINELA_AUSENTE_EN_SALIDA)
    assert resultado.codigo_salida == 0, resultado.salida
    assert _SENTINELA_TOKEN_SEGURIDAD not in resultado.salida


def _rutas_efectivas(
    rutas: Sequence[object], prefijo: str = ""
) -> tuple[set[tuple[str, tuple[str, ...]]], set[str]]:
    """Aplana el árbol de rutas, incluyendo `_IncludedRouter` y `Mount`.

    `include_router` en starlette 1.6.0 ya no vuelca las rutas incluidas
    directamente en `app.routes`: las envuelve en un `_IncludedRouter` cuyo
    `original_router.routes` guarda las rutas reales. Sin aplanar, esta
    prueba pasaría vacuamente comparando un `_IncludedRouter` sin `path` ni
    `methods` contra el literal esperado.

    `Mount` tampoco tiene `methods` ni `original_router` (design.md §5, V10):
    sin este segundo caso, el montaje `/interno` sería silenciosamente
    invisible para esta prueba -- no la enrojecería, la dejaría pasar en
    blanco mientras aparece una superficie autenticada entera. Por eso se
    devuelve un segundo conjunto, solo de montajes, en vez de fundirlos con
    las rutas: la ausencia de `methods` en un `Mount` no es una ruta sin
    métodos, es una frontera distinta.
    """
    rutas_planas: set[tuple[str, tuple[str, ...]]] = set()
    montajes: set[str] = set()
    for ruta in rutas:
        sub_router = getattr(ruta, "original_router", None)
        if sub_router is not None:
            sub_rutas, sub_montajes = _rutas_efectivas(sub_router.routes, prefijo)
            rutas_planas |= sub_rutas
            montajes |= sub_montajes
            continue
        if isinstance(ruta, Mount):
            montajes.add(prefijo + ruta.path)
            sub_rutas, sub_montajes = _rutas_efectivas(ruta.routes, prefijo + ruta.path)
            rutas_planas |= sub_rutas
            montajes |= sub_montajes
            continue
        methods = getattr(ruta, "methods", None)
        if methods is not None:
            rutas_planas.add((prefijo + ruta.path, tuple(sorted(methods))))  # type: ignore[attr-defined]
    return rutas_planas, montajes


def test_rutas_de_produccion_no_cambian() -> None:
    from app.main import crear_app

    rutas, montajes = _rutas_efectivas(crear_app().routes)
    esperado = {
        ("/salud", ("GET",)),
        ("/openapi.json", ("GET", "HEAD")),
        ("/docs", ("GET", "HEAD")),
        ("/docs/oauth2-redirect", ("GET", "HEAD")),
        ("/redoc", ("GET", "HEAD")),
        # Actualización deliberada del pin (ítem #6, segunda mitad;
        # design.md §6): primera ruta registrada dentro del montaje
        # `/interno`. El rojo acá, tras B3.1, es la prueba de que la
        # superficie cambió a propósito -- la misma convención que
        # estableció `service-token-auth`.
        ("/interno/procesadores/{clave_procesador}", ("POST",)),
    }
    esperado_montajes = {"/interno"}
    assert rutas == esperado
    assert montajes == esperado_montajes
