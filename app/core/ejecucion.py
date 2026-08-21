"""Plomería del proceso dedicado (ítem #8, BACKLOG; ADR 0012).

Los tres mensajes que cruzan el `Pipe`, el clasificador puro
`clasificar_desenlace`, la jerarquía de fallas no-`TipoError`, la plomería
genérica `ejecutar_aislado`, y la composición delgada sobre `REGISTRY`:
`_ejecutar_en_hijo` y `ejecutar_modulo`. El hijo re-deriva su `Procesador`
por `clave` y nunca recibe una instancia serializada (ver
`app/core/interfaz.py`).

**Este módulo es el que `spawn` reimporta en cada petición**, porque contiene
el objetivo `_ejecutar_en_hijo`. De ahí las dos disciplinas que gobiernan sus
imports, y que no son estéticas:

- *Sin efecto de importación.* Importarlo no lee configuración ni toca nada
  (ADR 0012, Consecuencias).
- *Sólo biblioteca estándar más `app/core/` liviano.* El ítem #17 mudó la
  mitad de admisión —el semáforo, `admitir()`, `AdmisionDeBorde` y el
  manejador 503— a `app/core/admision.py`, y el borde HTTP del vocabulario de
  errores a `app/core/errores_http.py`. Mientras convivían acá, cada hijo
  pagaba el import de FastAPI, Starlette y pydantic-settings para servir
  código HTTP que nunca ejecuta. Medido: el árbol pasó de 662 ms a 283 ms y
  el pico de memoria del hijo de ~46 MB a ~28 MB (`MEDICIONES.md`).

  **La regla que queda, y conviene decirla explícita: nada de lo que este
  módulo importe puede arrastrar un framework web ni un lector de
  configuración.** `tests/test_rendimiento.py` la vigila.

Las fallas de este módulo (`EjecucionExpirada`, `HijoMuerto`,
`FalloDelModulo`) no son `TipoError`: son excepciones propias que el ítem #10
traduce a HTTP. `TipoError` sigue teniendo exactamente cinco miembros
(ADR 0014).
"""

from __future__ import annotations

import multiprocessing
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from multiprocessing.connection import Connection

from app.core.errores import ErrorClaveInexistente, ErrorTipificado
from app.core.tipos import ArchivoEntrada, ArchivoSalida
from app.registry import REGISTRY

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
    propio `Procesador` en `REGISTRY[clave]`. Una ausencia -- desde el ítem
    #12 el registro ya no está vacío, así que ausencia significa clave
    desconocida y no "todavía no hay ninguno" -- se tipifica como
    `ErrorClaveInexistente(causa="no_en_registry")`, el mismo valor de
    `CausaDesincronizacion` que H-05 ya puso en el vocabulario.

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
