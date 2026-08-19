"""Admisión acotada y plomería del proceso dedicado (ítem #8, BACKLOG).

Dos mitades independientes detrás de un solo módulo (design.md §1, ADR 0022).
S2 (PR 2 de 4) embarcó la mitad de admisión: el semáforo perezoso, el gestor
de contexto `admitir()` -- con la misma forma que `temporales.reservar()` --
y el middleware ASGI `AdmisionDeBorde`, que es el único sitio de adquisición
y el único sitio de liberación del slot en todo el repositorio (design.md
§3). S3 (PR 3 de 4) agregó la **mitad de proceso**: los tres mensajes que
cruzan el `Pipe`, el clasificador puro `clasificar_desenlace`, la jerarquía
de fallas no-`TipoError` y la plomería genérica `ejecutar_aislado`
(design.md §5-§7). Esta entrega (S4, PR 4 de 4) cierra el módulo con
`_ejecutar_en_hijo` y `ejecutar_modulo`: la composición delgada sobre
`REGISTRY` (Decisión bloqueada -- el hijo re-deriva su `Procesador` por
`clave`, nunca recibe una instancia serializada; ver `app/core/interfaz.py`).

El semáforo es perezoso (`@lru_cache(maxsize=1)`, igual que
`obtener_configuracion`): importar este módulo no lee configuración y no
tiene efecto de importación -- la precondición que `spawn` impone sobre todo
módulo que el hijo vuelve a importar (ADR 0012, Consecuencias). Ahora que la
mitad de proceso existe, esa disciplina es literal: el hijo reimporta este
módulo entero antes de invocar su objetivo.

`ServicioSaturado` viaja como un 503 desnudo -- igual que `TokenInvalido`
viaja como un 401 desnudo en `app/core/seguridad.py`, el precedente que este
módulo sigue -- sin cuerpo `tipo`/`contexto`: no es un error tipificado, y
`TipoError` sigue teniendo exactamente cinco miembros (design.md §7, spec
"This domain introduces no sixth `TipoError` value"). Las fallas de la mitad
de proceso (`EjecucionExpirada`, `HijoMuerto`, `FalloDelModulo`) tampoco son
`TipoError`: son excepciones propias que el ítem #10 traduce a HTTP.
"""

from __future__ import annotations

import multiprocessing
import threading
import time
import traceback
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from functools import lru_cache
from multiprocessing.connection import Connection

from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.configuracion import obtener_configuracion
from app.core.errores import ErrorClaveInexistente, ErrorTipificado
from app.core.tipos import ArchivoEntrada, ArchivoSalida
from app.registry import REGISTRY


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


# --- proceso: mensajes que cruzan el Pipe ------------------------------------


@dataclass(frozen=True, slots=True)
class SalidaDelHijo:
    """El hijo terminó y produjo archivos de salida (design.md §5)."""

    archivos: list[ArchivoSalida]


@dataclass(frozen=True, slots=True)
class ErrorDelHijo:
    """El hijo levantó un `ErrorTipificado`; cruza intacto gracias a S1's
    `ErrorTipificado.__reduce__` (design.md §5, V6)."""

    error: ErrorTipificado


@dataclass(frozen=True, slots=True)
class ExcepcionDelHijo:
    """El hijo levantó una excepción sin tipificar. `traza` es un `str`
    (`traceback.format_exc()`) porque un objeto de excepción vivo no cruza
    de forma confiable el `Pipe` -- puede llevar atributos no picklables y
    pierde su traceback al deserializarse (design.md §5)."""

    clase: str
    mensaje: str
    traza: str


MensajeDelHijo = SalidaDelHijo | ErrorDelHijo | ExcepcionDelHijo


# --- proceso: clasificación del desenlace ------------------------------------


class Desenlace(StrEnum):
    """Los tres desenlaces posibles de un hijo dedicado (design.md §6)."""

    NORMAL = "normal"
    MATADO = "matado"
    ANOMALO = "anomalo"


def clasificar_desenlace(*, exitcode: int | None, matado: bool, hubo_mensaje: bool) -> Desenlace:
    """Clasifica el desenlace de un hijo. Pura: sin E/S, sin `Process`.

    `matado` gana siempre (design.md §6, V4): en Windows, `TerminateProcess`
    se normaliza de vuelta a `-SIGTERM`, así que el número de `exitcode` no
    puede distinguir el `kill()` propio de una señal externa -- solo el
    padre sabe si fue él quien mató al hijo, y debe decírselo al
    clasificador en vez de intentar adivinarlo del número. Sin `matado`, un
    mensaje bien formado con `exitcode == 0` es `NORMAL`; cualquier otra
    combinación es `ANOMALO`.
    """
    if matado:
        return Desenlace.MATADO
    if hubo_mensaje and exitcode == 0:
        return Desenlace.NORMAL
    return Desenlace.ANOMALO


# --- proceso: jerarquía de fallas (nunca TipoError, design.md §7) -----------


class FalloDeEjecucion(Exception):
    """Base de las fallas que la mitad de proceso produce. Nunca `TipoError`:
    el ítem #10 las traduce a HTTP; este módulo no decide esa forma."""

    __slots__ = ()


class EjecucionExpirada(FalloDeEjecucion):
    """El hijo no terminó dentro de `timeout` y fue matado de verdad."""

    __slots__ = ()


class HijoMuerto(FalloDeEjecucion):
    """El hijo murió sin dejar un mensaje bien formado en el `Pipe`: EOF sin
    mensaje, o un objeto recibido que no es ninguna de las tres formas de
    `MensajeDelHijo` (violación de protocolo, design.md §5)."""

    __slots__ = ("exitcode",)

    def __init__(self, exitcode: int | None) -> None:
        super().__init__()
        self.exitcode = exitcode


class FalloDelModulo(FalloDeEjecucion):
    """Traducción, a cargo de `ejecutar_modulo` (S4), de un `ExcepcionDelHijo`
    recibido del hijo -- no la levanta esta mitad de proceso."""

    __slots__ = ("clase", "mensaje", "traza")

    def __init__(self, *, clase: str, mensaje: str, traza: str) -> None:
        super().__init__()
        self.clase = clase
        self.mensaje = mensaje
        self.traza = traza


# --- proceso: la plomería genérica -------------------------------------------


def ejecutar_aislado(
    objetivo: Callable[..., None], argumentos: tuple[object, ...], *, timeout: timedelta
) -> MensajeDelHijo:
    """Corre `objetivo` en un `multiprocessing.Process` dedicado y devuelve
    lo que llegue por el `Pipe`, o levanta una falla de plomería.

    Un proceso por llamada, nunca de un pool (ADR 0012 revisado). Orden
    exacto, no incidental (design.md §5):

    1. `Pipe(duplex=False)`, `Process(daemon=True).start()`.
    2. El padre cierra **su propia copia** del extremo del hijo de
       inmediato -- si no lo hiciera, la muerte del hijo nunca produciría
       EOF y `poll()` esperaría el `timeout` completo en vano.
    3. Se lee el `Pipe` **antes** de `join()`: un payload más grande que el
       buffer del sistema operativo puede hacer que el hijo bloquee en
       `send()` mientras el padre bloquea en `join()` -- un abrazo mortal.
    4. Solo entonces `join(restante)`; si el hijo sigue vivo, `kill()` y un
       segundo `join()` para confirmar que ya no está vivo -- un `join()`
       que retorna no es, por sí solo, terminación.

    Un mensaje bien formado es autoritativo (design.md §5): si llegó, se
    devuelve tal cual sin importar cómo salga el hijo después -- su trabajo
    ya está hecho. `recv()` no se confía a ciegas: el objeto recibido se
    reduce por `isinstance` contra las tres formas de `MensajeDelHijo`;
    cualquier otra cosa es una violación de protocolo (`HijoMuerto`).
    """
    padre, hijo = multiprocessing.Pipe(duplex=False)
    proceso = multiprocessing.Process(target=objetivo, args=(hijo, *argumentos), daemon=True)
    proceso.start()
    hijo.close()  # LOAD-BEARING -- ver docstring, paso 2

    limite = timeout.total_seconds()
    inicio = time.monotonic()

    def _restante() -> float:
        return max(0.0, limite - (time.monotonic() - inicio))

    mensaje: object | None = None
    try:
        if padre.poll(_restante()):
            try:
                mensaje = padre.recv()
            except EOFError:
                mensaje = None
    finally:
        padre.close()

    proceso.join(_restante())
    matado = False
    if proceso.is_alive():
        proceso.kill()
        matado = True
        proceso.join()  # confirma que ya no está vivo, no solo que kill() retornó

    if isinstance(mensaje, SalidaDelHijo | ErrorDelHijo | ExcepcionDelHijo):
        return mensaje

    desenlace = clasificar_desenlace(
        exitcode=proceso.exitcode, matado=matado, hubo_mensaje=mensaje is not None
    )
    if desenlace is Desenlace.MATADO:
        raise EjecucionExpirada
    raise HijoMuerto(proceso.exitcode)


# --- proceso: la composición delgada sobre REGISTRY (S4) ---------------------


def _ejecutar_en_hijo(conexion: Connection, clave: str, entradas: list[ArchivoEntrada]) -> None:
    """Objetivo del `Process` dedicado (design.md §7-§8).

    Módulo-nivel y picklable por nombre calificado -- la precondición de
    `spawn` sobre todo `target` (ADR 0012). No recibe nunca una instancia de
    `Procesador`: solo `clave` (`str`) y las rutas ya envueltas en
    `ArchivoEntrada` cruzan la frontera del proceso (Decisión bloqueada,
    design.md §7 y §13 "Client-supplied `clave` reaching the child" -- es una
    búsqueda en un `dict`, nunca un import por nombre ni una ruta).

    El hijo re-importa el árbol de módulos de la aplicación (import normal de
    `app.registry`, que este módulo ya importa a nivel de módulo) y busca su
    propio `Procesador` en `REGISTRY[clave]`. Una ausencia -- el único
    desenlace real hoy, con `REGISTRY` vacío hasta los ítems #12/#16 (V9) --
    se tipifica como `ErrorClaveInexistente(causa="no_en_registry")`, el
    mismo valor de `CausaDesincronizacion` que H-05 ya puso en el vocabulario.

    Corre `validar` y, si no hay error, `procesar` -- ambos pasos en un solo
    hijo (design.md §7: spawnear dos veces duplicaría el costo de reimportar
    pandas por hijo, el mayor costo de la petición). Envía exactamente un
    `MensajeDelHijo` y cierra la conexión sin importar por cuál de las tres
    ramas salió.
    """
    try:
        try:
            procesador = REGISTRY[clave]
        except KeyError:
            raise ErrorClaveInexistente(clave_procesador=clave, causa="no_en_registry") from None

        error = procesador.validar(entradas)
        if error is not None:
            conexion.send(ErrorDelHijo(error=error))
            return

        archivos = procesador.procesar(entradas)
        conexion.send(SalidaDelHijo(archivos=archivos))
    except ErrorTipificado as error:
        conexion.send(ErrorDelHijo(error=error))
    except Exception as exc:  # noqa: BLE001 - frontera del proceso: todo cruza tipificado
        conexion.send(
            ExcepcionDelHijo(
                clase=type(exc).__name__, mensaje=str(exc), traza=traceback.format_exc()
            )
        )
    finally:
        conexion.close()


def ejecutar_modulo(
    *, clave: str, entradas: list[ArchivoEntrada], timeout: timedelta
) -> list[ArchivoSalida]:
    """Composición delgada sobre `ejecutar_aislado` (design.md §7).

    Spawnea `_ejecutar_en_hijo` con `clave` y `entradas`, y traduce lo que
    llegue: un `SalidaDelHijo` se devuelve como su lista de archivos; un
    `ErrorDelHijo` se re-levanta tal cual -- el manejador de `ErrorTipificado`
    (ítem #3) ya está registrado, así que no hace falta traducción nueva; un
    `ExcepcionDelHijo` se traduce a `FalloDelModulo` (V7 -- el motivo cerrado
    de `ContextoContenido` no tiene espacio para "el módulo se cayó", así que
    esto no se fuerza a un `ErrorTipificado`). `EjecucionExpirada` y
    `HijoMuerto` ya llegan levantadas por `ejecutar_aislado` y se propagan sin
    traducir. El ítem #10 decide, con esas cuatro formas, la traducción HTTP
    final; este módulo no la decide.
    """
    mensaje = ejecutar_aislado(_ejecutar_en_hijo, (clave, entradas), timeout=timeout)
    if isinstance(mensaje, SalidaDelHijo):
        return mensaje.archivos
    if isinstance(mensaje, ErrorDelHijo):
        raise mensaje.error
    raise FalloDelModulo(clase=mensaje.clase, mensaje=mensaje.mensaje, traza=mensaje.traza)
