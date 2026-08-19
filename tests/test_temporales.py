"""Pruebas de `app.core.temporales`: propiedad, reserva y barrendero.

Slice A (tasks.md fases A1-A3). Behaviourales, sin AST ni inspección
estructural (design.md, metodología: TDD estricto deshabilitado). No hay
ruta de producción todavía -- `_formato` y la ruta de recepción son de la
Fase B y no se prueban acá (design.md §5).

El estado modular (`_EN_VUELO`, la raíz dedicada) se limpia antes y después
de cada prueba para que no se filtre entre ellas: son globales de módulo, y
otra prueba del mismo proceso no debe ver sus sobras.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import time
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.responses import FileResponse

from app.core.temporales import (
    _EN_VUELO,
    _PREFIJO_PETICION,
    _raiz,
    barrer,
    ciclo_de_vida,
    preparar_raiz,
    reservar,
)
from app.main import crear_app


@pytest.fixture(autouse=True)
def _estado_limpio() -> Iterator[None]:
    """`_EN_VUELO` y la raíz dedicada son estado de módulo: no debe
    filtrarse entre pruebas."""
    _EN_VUELO.clear()
    shutil.rmtree(_raiz(), ignore_errors=True)
    yield
    _EN_VUELO.clear()
    shutil.rmtree(_raiz(), ignore_errors=True)


def _backdatar(ruta: Path, hace_segundos: float) -> None:
    momento = time.time() - hace_segundos
    os.utime(ruta, (momento, momento))


class TestReservaYCesion:
    def test_ceder_limpieza_pospone_el_borrado_a_la_respuesta(self) -> None:
        app = FastAPI()

        @app.get("/prueba-ceder")
        def _endpoint() -> FileResponse:
            with reservar() as reserva:
                archivo = reserva.directorio / "archivo.txt"
                archivo.write_text("contenido")
                return FileResponse(archivo, background=reserva.ceder_limpieza())

        with TestClient(app) as cliente:
            respuesta = cliente.get("/prueba-ceder")

        assert respuesta.status_code == 200
        # El `BackgroundTask` ya corrió dentro del ciclo síncrono de
        # `TestClient`: el directorio, dueño de `archivo.txt`, ya no existe.
        directorios = list(_raiz().iterdir()) if _raiz().is_dir() else []
        assert directorios == []

    def test_sin_ceder_el_finally_limpia(self) -> None:
        with reservar() as reserva:
            directorio = reserva.directorio
            assert directorio.is_dir()
        assert not directorio.exists()


class TestBarrer:
    def test_no_borra_un_directorio_en_vuelo_aunque_su_mtime_sea_viejo(self) -> None:
        preparar_raiz()
        with reservar() as reserva:
            _backdatar(reserva.directorio, hace_segundos=3600)
            momento_registro = _EN_VUELO[reserva.directorio]
            barrer(umbral=timedelta(0), ahora=momento_registro)
            assert reserva.directorio.is_dir()
            reserva.ceder_limpieza()  # evita que el `finally` intente borrar de nuevo

    def test_desaloja_una_entrada_vieja_de_en_vuelo_y_borra_su_directorio(self) -> None:
        preparar_raiz()
        with reservar() as reserva:
            _EN_VUELO[reserva.directorio] = time.monotonic() - 3600
            _backdatar(reserva.directorio, hace_segundos=3600)
            barrer(umbral=timedelta(0), ahora=time.monotonic())
            assert not reserva.directorio.exists()
            assert reserva.directorio not in _EN_VUELO
            reserva.ceder_limpieza()  # barrer() ya lo borró; evita un segundo intento

    def test_no_toca_nada_fuera_de_su_raiz_dedicada(self) -> None:
        hermano = Path(tempfile.gettempdir()) / "api-portal-prueba-hermana.txt"
        hermano.write_text("no soy del servicio")
        _backdatar(hermano, hace_segundos=3600)
        try:
            preparar_raiz()
            barrer(umbral=timedelta(0))
            assert hermano.exists()
        finally:
            hermano.unlink(missing_ok=True)

    def test_el_agujero_de_desconexion_es_real_y_el_barrendero_lo_cierra(self) -> None:
        # Simula una petición que se desconectó a mitad de envío y nunca
        # corrió su propia limpieza (V11 del design.md): el directorio queda
        # registrado en `_EN_VUELO`, pero nadie llama a `Reserva.limpiar()`.
        preparar_raiz()
        directorio = Path(tempfile.mkdtemp(prefix=_PREFIJO_PETICION, dir=_raiz()))
        momento = time.monotonic()
        _EN_VUELO[directorio] = momento

        # Inmediatamente después de la desconexión, sigue vivo.
        barrer(umbral=timedelta(0), ahora=momento)
        assert directorio.is_dir()

        # Pasado el umbral, el barrendero lo recupera: primero desaloja la
        # entrada de `_EN_VUELO`, luego lo borra por mtime.
        _backdatar(directorio, hace_segundos=3600)
        barrer(umbral=timedelta(0), ahora=momento + 3600)
        assert not directorio.exists()
        assert directorio not in _EN_VUELO


class TestCicloDeVida:
    def test_la_pasada_de_arranque_borra_un_huerfano_preexistente(
        self, token_sentinela: str, limpiar_cache_configuracion: None
    ) -> None:
        preparar_raiz()
        huerfano = Path(tempfile.mkdtemp(prefix=_PREFIJO_PETICION, dir=_raiz()))
        _backdatar(huerfano, hace_segundos=20 * 60)  # > UMBRAL_DE_EDAD (15 min)

        app = crear_app()
        with TestClient(app):
            pass

        assert not huerfano.exists()

    def test_el_apagado_cancela_la_tarea_y_no_cuelga(
        self,
        token_sentinela: str,
        limpiar_cache_configuracion: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        tareas: list[asyncio.Task[None]] = []
        creador_original = asyncio.create_task

        def _creador_que_registra(
            coro: object, *args: object, **kwargs: object
        ) -> asyncio.Task[None]:
            tarea: asyncio.Task[None] = creador_original(coro, *args, **kwargs)  # type: ignore[arg-type]
            tareas.append(tarea)
            return tarea

        monkeypatch.setattr("app.core.temporales.asyncio.create_task", _creador_que_registra)

        app = FastAPI(lifespan=ciclo_de_vida)
        with TestClient(app):
            pass

        assert len(tareas) == 1
        assert tareas[0].done()
