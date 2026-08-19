"""Ciclo de vida y propiedad de los temporales de una petición.

Nombre de módulo heredado de ADR 0011 (`core/temporales.py # try/finally,
limpieza total`). La razón de ser de la propiedad de los temporales viene de
ADR 0006 (*"una vez enviada la respuesta HTTP"*). Este cambio registra su
propia decisión en ADR 0020: el modelo de propiedad con un único punto de
transferencia y el barrendero de la raíz dedicada.

Este módulo importa únicamente la biblioteca estándar más
`starlette.concurrency.run_in_threadpool` y `starlette.background.BackgroundTask`
-- nunca nada de `app/procesadores/` (invariante de ADR 0011).
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager, suppress
from datetime import timedelta
from pathlib import Path
from typing import Final

from fastapi import FastAPI
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from app.core.configuracion import obtener_configuracion

_PREFIJO_PETICION: Final[str] = "pet-"

# Design.md §3.3: dos constantes nombradas, adyacentes, editables en un solo
# lugar. Nunca `Configuracion` -- no hay necesidad operativa identificada de
# ajustarlas por entorno.
UMBRAL_DE_EDAD: Final[timedelta] = timedelta(minutes=15)
INTERVALO_DE_BARRIDO: Final[timedelta] = timedelta(minutes=5)

# Registro en proceso de directorios con dueño vivo (design.md §3.2). Su
# solidez depende de que ADR 0012 fije un único worker de Uvicorn -- ver
# adrs/0020, sección Consecuencias.
_EN_VUELO: dict[Path, float] = {}


def _raiz() -> Path:
    """La raíz dedicada del servicio -- nunca `tempfile.gettempdir()` a secas.

    Un barrendero que recorriera `gettempdir()` borraría los volcados propios
    de Starlette (`SpooledTemporaryFile` por encima de 1 MB) y los de
    cualquier otro proceso de la máquina. Ver adrs/0020.
    """
    return Path(tempfile.gettempdir()) / "api-portal-temporales"


def preparar_raiz() -> None:
    """Crea la raíz dedicada si no existe. Idempotente."""
    _raiz().mkdir(parents=True, exist_ok=True)


class Reserva:
    """Dueña del directorio temporal de una petición (design.md §2).

    Un único punto de transferencia: `ceder_limpieza()`. Antes de eso,
    `reservar()` borra en su `finally`; después, la respuesta es la dueña y
    ese `finally` no hace nada.
    """

    def __init__(self, directorio: Path) -> None:
        self.directorio = directorio
        self._cedida = False

    def ceder_limpieza(self) -> BackgroundTask:
        """Transfiere la propiedad a la respuesta.

        Tras esto, el `finally` de `reservar()` deja de borrar.
        """
        self._cedida = True
        return BackgroundTask(self.limpiar)

    def limpiar(self) -> None:
        """Borra el directorio. Idempotente a propósito: puede correr desde
        `reservar()`, desde el `BackgroundTask` cedido, o desde el
        barrendero -- nunca con consecuencias si corre más de una vez
        (`rmtree(..., ignore_errors=True)` no falla si ya no está).
        """
        _EN_VUELO.pop(self.directorio, None)
        shutil.rmtree(self.directorio, ignore_errors=True)


@contextmanager
def reservar() -> Iterator[Reserva]:
    """Reserva un directorio temporal exclusivo de esta petición.

    Borra en `finally` salvo que `ceder_limpieza()` haya transferido la
    propiedad a una respuesta (design.md §2). El nombre en disco lo genera
    siempre `mkdtemp`, nunca algo derivado de un cliente.
    """
    # Defensivo: un `rmtree` externo (o de una prueba) entre pasadas del
    # barrendero no debe dejar el servicio sin raíz (design.md §3.1).
    _raiz().mkdir(parents=True, exist_ok=True)
    reserva = Reserva(Path(tempfile.mkdtemp(prefix=_PREFIJO_PETICION, dir=_raiz())))
    _EN_VUELO[reserva.directorio] = time.monotonic()
    try:
        yield reserva
    finally:
        if reserva._cedida:  # noqa: SLF001
            _EN_VUELO.pop(reserva.directorio, None)
        else:
            reserva.limpiar()


def barrer(*, umbral: timedelta = UMBRAL_DE_EDAD, ahora: float | None = None) -> None:
    """Borra huérfanos bajo la raíz dedicada (design.md §3.2).

    Condición doble, ambas requeridas: un hijo directo de la raíz se borra
    únicamente si está AUSENTE de `_EN_VUELO` Y su antigüedad por mtime
    supera `umbral`. La edad de un hijo se mide siempre con el reloj de
    pared (`time.time()`), porque `Path.stat().st_mtime` es de reloj de
    pared; `ahora` (reloj monotónico, por defecto `time.monotonic()`)
    gobierna sólo el desalojo de `_EN_VUELO`, cuyas marcas se registran con
    ese mismo reloj -- mezclar ambos relojes daría comparaciones sin
    sentido. Función pura de `(raíz, umbral, ahora)` (design.md §3.3) para
    que las pruebas puedan controlar el tiempo sin dormir minutos reales.
    """
    ahora_monotono = ahora if ahora is not None else time.monotonic()
    umbral_segundos = umbral.total_seconds()

    # El registro no puede crecer sin límite: una petición desconectada
    # nunca corre su propia limpieza, así que su entrada quedaría inmune
    # para siempre si no se desaloja con el mismo umbral (design.md §3.2).
    for directorio, momento in list(_EN_VUELO.items()):
        if ahora_monotono - momento > umbral_segundos:
            del _EN_VUELO[directorio]

    raiz = _raiz()
    if not raiz.is_dir():
        return

    ahora_real = time.time()
    for hijo in raiz.iterdir():
        if hijo in _EN_VUELO:
            continue
        try:
            antiguedad = ahora_real - hijo.stat().st_mtime
        except FileNotFoundError:
            continue  # ya lo borró otro camino (idempotencia de `limpiar()`)
        if antiguedad > umbral_segundos:
            shutil.rmtree(hijo, ignore_errors=True)


async def _bucle_de_barrido() -> None:
    """Dormir primero: la pasada de arranque de `ciclo_de_vida` ya corrió."""
    while True:
        await asyncio.sleep(INTERVALO_DE_BARRIDO.total_seconds())
        await run_in_threadpool(barrer)


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI) -> AsyncIterator[None]:
    obtener_configuracion()  # 1. falla cerrado; ADR 0012 paso 2
    preparar_raiz()
    await run_in_threadpool(barrer)  # pasada de arranque (design.md §3.4)
    tarea = asyncio.create_task(_bucle_de_barrido())  # referencia dura mientras viva el lifespan
    try:
        yield
    finally:
        # Acotado a propósito: `await tarea` está en el camino crítico del
        # apagado (Uvicorn espera `shutdown.complete` -- design.md §3.5). El
        # bucle está casi siempre dormido en `asyncio.sleep`, que se cancela
        # al instante; nunca se espera una pasada de barrido completa acá.
        tarea.cancel()
        with suppress(asyncio.CancelledError):
            await tarea
