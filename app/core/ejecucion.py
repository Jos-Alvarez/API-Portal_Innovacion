"""Admisión acotada y plomería del proceso dedicado (ítem #8, BACKLOG).

Dos mitades independientes detrás de un solo módulo (design.md §1, ADR 0022).
Esta entrega (S2, PR 2 de 4) ships **solo la mitad de admisión**: el
semáforo perezoso, el gestor de contexto `admitir()` -- con la misma forma
que `temporales.reservar()` -- y el middleware ASGI `AdmisionDeBorde`, que es
el único sitio de adquisición y el único sitio de liberación del slot en todo
el repositorio (design.md §3). La mitad de proceso (`Pipe`, `Process`,
`clasificar_desenlace`, `ejecutar_aislado`, `ejecutar_modulo`) llega en S3/S4.

El semáforo es perezoso (`@lru_cache(maxsize=1)`, igual que
`obtener_configuracion`): importar este módulo no lee configuración y no
tiene efecto de importación -- la precondición que `spawn` impone sobre todo
módulo que el hijo vuelve a importar (ADR 0012, Consecuencias). Aunque la
mitad de proceso todavía no existe, este módulo ya vive donde el hijo lo
reimportará, así que la disciplina de importación perezosa empieza acá.

`ServicioSaturado` viaja como un 503 desnudo -- igual que `TokenInvalido`
viaja como un 401 desnudo en `app/core/seguridad.py`, el precedente que este
módulo sigue -- sin cuerpo `tipo`/`contexto`: no es un error tipificado, y
`TipoError` sigue teniendo exactamente cinco miembros (design.md §7, spec
"This domain introduces no sixth `TipoError` value").
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
    """

    __slots__ = ("app",)

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        with admitir():
            await self.app(scope, receive, send)
