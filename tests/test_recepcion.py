"""Pruebas de `app.recepcion`: la ruta de recepción (ítem #6, segunda mitad).

Slice B (tasks.md fases B2-B5). Behaviourales, sin AST ni inspección
estructural (design.md, metodología: TDD estricto deshabilitado). La app de
producción se usa tal cual (`app.main.crear_app`), no un router de pruebas
aparte, porque esta ruta ya vive en `router_interno` y su cobertura de pin
está en `tests/test_seguridad_token.py`.

El estado modular de `app.core.temporales` (`_EN_VUELO`, la raíz dedicada)
se limpia antes y después de cada prueba, igual que en
`tests/test_temporales.py`.
"""

from __future__ import annotations

import logging
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core import temporales
from app.core.temporales import _EN_VUELO, _raiz
from app.main import crear_app
from app.recepcion import _formato

_RUTA = "/interno/procesadores/cualquiera"


@pytest.fixture(autouse=True)
def _estado_limpio() -> Iterator[None]:
    """`_EN_VUELO` y la raíz dedicada son estado de módulo compartido con
    `app.core.temporales`; no debe filtrarse entre pruebas."""
    _EN_VUELO.clear()
    shutil.rmtree(_raiz(), ignore_errors=True)
    yield
    _EN_VUELO.clear()
    shutil.rmtree(_raiz(), ignore_errors=True)


@pytest.fixture
def cliente_de_prueba(
    token_sentinela: str, limpiar_cache_configuracion: None
) -> Iterator[TestClient]:
    with TestClient(crear_app()) as cliente:
        yield cliente


def _cabecera(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def captura_de_limpieza(monkeypatch: pytest.MonkeyPatch) -> dict[Path, dict[str, bytes]]:
    """Espía sobre `Reserva.limpiar` que guarda el contenido del directorio
    justo antes de que se borre de verdad, y llama al original después --
    así ninguna prueba deja basura ni depende de inspeccionar un directorio
    a mitad de una petición síncrona de `TestClient`.
    """
    contenidos: dict[Path, dict[str, bytes]] = {}
    limpiar_original = temporales.Reserva.limpiar

    def _espia(self: temporales.Reserva) -> None:
        if self.directorio.is_dir():
            contenidos[self.directorio] = {
                hijo.name: hijo.read_bytes() for hijo in self.directorio.iterdir()
            }
        limpiar_original(self)

    monkeypatch.setattr(temporales.Reserva, "limpiar", _espia)
    return contenidos


class TestRecepcion:
    def test_archivo_escrito_dentro_del_directorio_y_borrado_despues(
        self,
        cliente_de_prueba: TestClient,
        token_sentinela: str,
        captura_de_limpieza: dict[Path, dict[str, bytes]],
    ) -> None:
        respuesta = cliente_de_prueba.post(
            _RUTA,
            files={
                "archivos": ("informe.xlsx", b"contenido-de-prueba", "application/octet-stream")
            },
            headers=_cabecera(token_sentinela),
        )
        assert respuesta.status_code == 500
        assert respuesta.json() == {
            "tipo": "clave_inexistente",
            "contexto": {"clave_procesador": "cualquiera", "causa": "fila_ausente"},
        }
        [(directorio, contenido)] = captura_de_limpieza.items()
        assert contenido == {"entrada_0": b"contenido-de-prueba"}
        assert not directorio.exists()  # el `finally` limpió, nada cedido

    @pytest.mark.parametrize(
        "nombre_hostil",
        ["../../x", "..\\x.xlsx", "C:\\Windows\\x", "/etc/passwd", "café con leche.xlsx"],
    )
    def test_nombre_hostil_confinado_al_directorio_temporal(
        self,
        cliente_de_prueba: TestClient,
        token_sentinela: str,
        captura_de_limpieza: dict[Path, dict[str, bytes]],
        nombre_hostil: str,
    ) -> None:
        respuesta = cliente_de_prueba.post(
            _RUTA,
            files={"archivos": (nombre_hostil, b"x", "application/octet-stream")},
            headers=_cabecera(token_sentinela),
        )
        assert respuesta.status_code == 500
        # Ningún archivo aparece en ninguna ruta derivada del nombre hostil.
        assert not Path(nombre_hostil).exists()
        [(directorio, contenido)] = captura_de_limpieza.items()
        # El único nombre en disco es el generado por el servidor.
        assert set(contenido) == {"entrada_0"}
        assert not directorio.exists()

    def test_nombres_duplicados_producen_archivos_distintos(
        self,
        cliente_de_prueba: TestClient,
        token_sentinela: str,
        captura_de_limpieza: dict[Path, dict[str, bytes]],
    ) -> None:
        respuesta = cliente_de_prueba.post(
            _RUTA,
            files=[
                ("archivos", ("reporte.xlsx", b"contenido-uno", "application/octet-stream")),
                ("archivos", ("reporte.xlsx", b"contenido-dos", "application/octet-stream")),
            ],
            headers=_cabecera(token_sentinela),
        )
        assert respuesta.status_code == 500
        [(_directorio, contenido)] = captura_de_limpieza.items()
        assert contenido == {"entrada_0": b"contenido-uno", "entrada_1": b"contenido-dos"}

    @pytest.mark.parametrize("clave_procesador", ["contado_carga", "otra-clave", "123"])
    def test_cualquier_clave_procesador_produce_el_mismo_error(
        self, cliente_de_prueba: TestClient, token_sentinela: str, clave_procesador: str
    ) -> None:
        respuesta = cliente_de_prueba.post(
            f"/interno/procesadores/{clave_procesador}",
            files={"archivos": ("x.xlsx", b"x", "application/octet-stream")},
            headers=_cabecera(token_sentinela),
        )
        assert respuesta.status_code == 500
        assert respuesta.json() == {
            "tipo": "clave_inexistente",
            "contexto": {"clave_procesador": clave_procesador, "causa": "fila_ausente"},
        }

    def test_no_quedan_temporales_tras_una_respuesta_completa(
        self, cliente_de_prueba: TestClient, token_sentinela: str
    ) -> None:
        cliente_de_prueba.post(
            _RUTA,
            files={"archivos": ("x.xlsx", b"x", "application/octet-stream")},
            headers=_cabecera(token_sentinela),
        )
        hijos = list(_raiz().iterdir()) if _raiz().is_dir() else []
        assert hijos == []

    def test_campo_archivos_ausente_da_422_sin_cuerpo(
        self, cliente_de_prueba: TestClient, token_sentinela: str
    ) -> None:
        respuesta = cliente_de_prueba.post(
            _RUTA,
            files={"otro_campo": ("x.xlsx", b"x", "application/octet-stream")},
            headers=_cabecera(token_sentinela),
        )
        assert respuesta.status_code == 422
        assert respuesta.content == b""

    def test_401_llega_sin_leer_el_cuerpo(self, cliente_de_prueba: TestClient) -> None:
        def _cuerpo_que_nunca_termina() -> Iterator[bytes]:
            # Un generador que jamás se agota: si la ruta llegara a leerlo,
            # la prueba colgaría en vez de fallar rápido.
            while True:
                yield b"0" * 1024

        respuesta = cliente_de_prueba.post(_RUTA, content=_cuerpo_que_nunca_termina())
        assert respuesta.status_code == 401
        assert respuesta.content == b""


class TestFormato:
    @pytest.mark.parametrize(
        "nombre_original,esperado",
        [
            ("a.b.XLSX", "xlsx"),
            ("sin-extension", ""),
            ("", ""),
            ("..\\x.xlsx", "xlsx"),
        ],
    )
    def test_formato_extrae_la_extension(self, nombre_original: str, esperado: str) -> None:
        assert _formato(nombre_original) == esperado


_SENTINELA_TOKEN_RECEPCION = "sentinela-recepcion-8b2f31cd"


def test_token_no_aparece_en_respuestas_ni_en_logs(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("TOKEN_SERVICIO", _SENTINELA_TOKEN_RECEPCION)
    from app.core.configuracion import obtener_configuracion

    obtener_configuracion.cache_clear()
    try:
        with caplog.at_level(logging.DEBUG):
            with TestClient(crear_app()) as cliente:
                exitosa = cliente.post(
                    _RUTA,
                    files={"archivos": ("x.xlsx", b"x", "application/octet-stream")},
                    headers=_cabecera(_SENTINELA_TOKEN_RECEPCION),
                )
                rechazada = cliente.post(
                    _RUTA,
                    files={"archivos": ("x.xlsx", b"x", "application/octet-stream")},
                    headers=_cabecera("credencial-incorrecta"),
                )

                def _cuerpo_que_nunca_termina() -> Iterator[bytes]:
                    while True:
                        yield b"0" * 1024

                desconectada = cliente.post(_RUTA, content=_cuerpo_que_nunca_termina())

        assert exitosa.status_code == 500
        assert rechazada.status_code == 401
        assert desconectada.status_code == 401

        cuerpos = exitosa.text + rechazada.text + desconectada.text
        mensajes = "".join(record.getMessage() for record in caplog.records)
        assert _SENTINELA_TOKEN_RECEPCION not in cuerpos
        assert _SENTINELA_TOKEN_RECEPCION not in mensajes
    finally:
        obtener_configuracion.cache_clear()
