"""Admisión acotada: el semáforo y su borde HTTP (ítem #8; ADR 0022).

**Separado de `app/core/ejecucion.py` por el ítem #17, y por una razón
medida.** Las dos mitades que ese módulo albergaba —admisión y proceso
dedicado— siempre fueron independientes, pero convivían en un archivo. El
problema es que `app/core/ejecucion.py` contiene `_ejecutar_en_hijo`, el
objetivo de `spawn`, y `spawn` reimporta el módulo del objetivo **en cada
petición** (ADR 0012). Con la admisión adentro, cada hijo pagaba el import de
FastAPI, Starlette y pydantic-settings para código HTTP que nunca ejecuta:
~470 ms de FastAPI más ~290 ms de pydantic-settings, medidos en
`MEDICIONES.md`.

Acá vive todo lo que necesita saber de HTTP y de configuración; del otro lado
queda la plomería del proceso, que sólo necesita biblioteca estándar. La
frontera no es estética: es la diferencia entre lo que se paga una vez al
arrancar el servicio y lo que se paga en cada petición.

`ServicioSaturado` viaja como un 503 desnudo —igual que `TokenInvalido` viaja
como un 401 desnudo en `app/core/seguridad.py`, el precedente que esto
sigue— sin cuerpo `tipo`/`contexto`: no es un error tipificado, y `TipoError`
sigue teniendo exactamente cinco miembros (ADR 0014).

El semáforo es perezoso (`@lru_cache(maxsize=1)`, igual que
`obtener_configuracion`): importar este módulo no lee configuración y no
tiene efecto de importación.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.configuracion import obtener_configuracion
from app.core.registro import registrar_saturacion


class ServicioSaturado(Exception):
    """Sin campos y sin argumentos, igual que `TokenInvalido`: no transporta
    ningún dato del rechazo -- no hay ninguno que transportar."""

    __slots__ = ()


def responder_servicio_saturado(request: Request, exc: Exception) -> Response:
    # Único lugar del repositorio donde se construye la respuesta 503.
    return Response(status_code=503)


def registrar_manejador_503(app: FastAPI) -> None:
    app.add_exception_handler(ServicioSaturado, responder_servicio_saturado)


@lru_cache(maxsize=1)
def obtener_semaforo() -> threading.BoundedSemaphore:
    """Construye (una sola vez, perezosamente) el semáforo de admisión.

    `threading.BoundedSemaphore`, no `asyncio.Semaphore` (ADR 0012 lo nombra
    así, y el contador debe ser observable también desde código de
    threadpool -- design.md §3). Perezoso por el mismo motivo que
    `obtener_configuracion`: importar este módulo no debe leer configuración.
    Las pruebas lo limpian con `obtener_semaforo.cache_clear()`, igual que ya
    hacen con `obtener_configuracion`.
    """
    return threading.BoundedSemaphore(obtener_configuracion().ejecuciones_max)


@contextmanager
def admitir() -> Iterator[None]:
    """Adquiere un slot de admisión sin bloquear, o levanta `ServicioSaturado`.

    Diseño (design.md §3): `acquire(blocking=False)` levanta **antes** del
    `try:` en caso de fallo, así que ningún `release()` puede emparejarse con
    una adquisición que nunca ocurrió. Al tener éxito, entra en
    `try/finally: semaforo.release()` -- el **único** sitio de `release()` en
    todo el repositorio. El `ValueError` de `BoundedSemaphore` ante una
    sobre-liberación se deja deliberadamente como el detector de un segundo
    sitio de liberación futuro, nunca evitado con un contador propio.
    """
    semaforo = obtener_semaforo()
    if not semaforo.acquire(blocking=False):
        raise ServicioSaturado
    try:
        yield
    finally:
        semaforo.release()


class AdmisionDeBorde:
    """Middleware ASGI de admisión del montaje `/interno` (design.md §3.4).

    Segunda entrada de la lista `middleware=[...]` del `Mount` existente,
    **después** de `AutenticacionDeBorde` (V1 del design: `Mount` aplica su
    lista de middlewares en orden inverso, así que la primera entrada queda
    más externa). Esto garantiza que la admisión se evalúa después del
    control del token: un llamador no autenticado nunca puede ocupar un slot
    (spec "Admission is checked after the token check").

    Envuelve `await self.app(...)` entero en `with admitir():`, así que el
    slot se mantiene durante toda la petición autenticada -- multipart,
    validación de contrato, copia acotada y (a partir de S3/S4 y del ítem
    #10) el hijo dedicado -- y se libera exactamente una vez sin importar
    cómo termine esa llamada: éxito, un error tipificado, una excepción sin
    tipificar, un timeout, o un `asyncio.CancelledError` por desconexión del
    cliente. Todos esos casos son, para este middleware, simplemente
    retornos o excepciones de `await self.app(...)`; el `finally` del
    `@contextmanager` los cubre a todos por igual (design.md §3).

    El ítem #14 agrega acá —y **no** dentro de `admitir()`— la línea de log
    del rechazo por saturación. `admitir()` es un gestor de contexto genérico
    que las pruebas unitarias invocan directamente, sin scope y sin ruta; el
    único sitio con un scope HTTP en la mano es este `__call__`. La emisión va
    por lo tanto en un `except ServicioSaturado:` alrededor del `with`, que
    **re-levanta siempre**: el manejador registrado en `crear_app()` sigue
    siendo el único constructor de la respuesta 503, y el log no puede cambiar
    un código de estado.
    """

    __slots__ = ("app",)

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        try:
            with admitir():
                await self.app(scope, receive, send)
        except ServicioSaturado:
            # `scope.get`, nunca `scope[...]`: un scope HTTP mínimo armado a
            # mano (las pruebas del middleware lo hacen) puede no traer
            # `method` ni `path`, y el log jamás debe ser lo que rompa la
            # petición. El saneo de ambos valores vive en `registrar_saturacion`.
            registrar_saturacion(
                metodo=str(scope.get("method", "")),
                ruta=str(scope.get("path", "")),
                ejecuciones_max=obtener_configuracion().ejecuciones_max,
            )
            raise
