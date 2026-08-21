"""Logging operativo estructurado del servicio (ítem #14, BACKLOG fila 14).

**El nombre del módulo es una elección de esta entrega, no de un ADR.** Ningún
ADR previo nombra un archivo para el logging operativo, así que se elige
`registro.py` acá y se deja dicho: "registro" en el sentido de *asiento de
bitácora*, no en el de `app/registry.py` (que es la tabla de procesadores).
Los dos nombres conviven porque viven en paquetes distintos y ninguno importa
al otro.

**Por qué vive en `app/core/`.** Sus llamadores son `app.core.admision`
(la línea de saturación), `app.recepcion` (la de ejecución) y, desde el ítem
#16, `app/procesadores/contado_carga/` (la de descartes, emitida desde el
hijo). Ninguno de ellos puede importar módulos de nivel superior de `app.*`
salvo `app.registry`, así que un módulo de logging colgado de `app/` los
dejaría fuera de alcance. No importa nada de
`app/procesadores/` (invariante de ADR 0011).

**Restricciones que este módulo cumple por construcción:**

- *Sólo biblioteca estándar.* Ningún tipo de Starlette/FastAPI aparece en
  ninguna firma: quien llama extrae del scope los primitivos (`str`, `int`,
  `float`) y los pasa sueltos. Así el borde HTTP no se filtra al núcleo y
  este módulo se puede probar sin levantar una app.
- *Sin efecto de importación.* No se llama a `dictConfig` ni se toca ningún
  logger al importar. La configuración es **explícita**: `configurar_logging()`
  la aplica desde `crear_app()`. Esto es obligatorio, no estético:
  `app/core/ejecucion.py` es reimportado por cada hijo de `spawn` (ADR 0012) y
  su docstring garantiza que importarlo no lee configuración y no tiene efecto
  de importación; un módulo con efecto colgando de esa cadena rompería esa
  garantía.

**Por qué hace falta infraestructura y no sólo llamadas a `logger.info`.**
Bajo el arranque canónico del README (`uv run uvicorn app.main:app`), un
`logging.getLogger("app…").info(...)` no emite **nada**. Verificado contra
este entorno: `LOGGING_CONFIG` de uvicorn configura únicamente `uvicorn`,
`uvicorn.error` y `uvicorn.access`; no agrega ningún handler a la raíz y no
fija el nivel de la raíz. El nivel efectivo de un logger `app.*` queda
entonces en WARNING (heredado de la raíz vacía) y el `logging.lastResort` que
lo atajaría también es de nivel WARNING. Sin `configurar_logging()` este ítem
entero sería un no-op silencioso en producción, verde en las pruebas que usen
`caplog` (que baja el nivel de la raíz y por eso miente sobre producción).

**El token de servicio nunca entra acá.** Ninguna función de este módulo
recibe encabezados, credenciales ni el scope crudo; los llamadores pasan
campos nombrados uno por uno. Esa forma es lo que mantiene cerradas las
comprobaciones de `tests/test_seguridad_estructural.py` y
`tests/test_seguridad_token.py`.
"""

from __future__ import annotations

import json
import logging
import sys
from enum import StrEnum
from typing import Any, Final, TextIO

# Nombre del logger de la aplicación entera, no sólo de este módulo. Se elige
# la raíz del espacio de nombres (`app`) a propósito: `configurar_logging()`
# le fija nivel y handler una sola vez y cualquier `app.*` futuro queda
# visible sin repetir el cableado. Las dos líneas de este ítem se emiten por
# acá, distinguidas por el campo `evento`.
NOMBRE_LOGGER: Final[str] = "app"

EVENTO_EJECUCION: Final[str] = "ejecucion"
EVENTO_SATURACION: Final[str] = "saturacion"
EVENTO_DESCARTES: Final[str] = "descartes"

# Techo de longitud para todo texto de origen no confiable (la ruta y la clave
# que se recortan de ella). Acota el tamaño de la línea y, con él, el daño de
# una ruta larga fabricada por el cliente.
LARGO_MAX_TEXTO_SIN_VALIDAR: Final[int] = 200

# Marca sobre el handler que instala este módulo, para poder reemplazarlo sin
# duplicarlo cuando `crear_app()` se llama más de una vez (las pruebas lo
# hacen por fixture, una vez por prueba).
_MARCA_DEL_HANDLER: Final[str] = "_handler_de_app_portal"

# Atributos que `logging.LogRecord` trae siempre. Todo lo que no esté acá vino
# de un `extra=` del llamador y es, por definición, campo estructurado.
# `taskName` sólo existe desde 3.12; nombrarlo acá es inocuo en 3.11.
_ATRIBUTOS_ESTANDAR: Final[frozenset[str]] = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)


class ResultadoDeEjecucion(StrEnum):
    """Desenlace de una petición, tal como lo ve el operador.

    **No reutiliza `Desenlace` de `app.core.ejecucion` a propósito.** Aquél
    clasifica el *ciclo de vida del hijo* (`normal`/`matado`/`anomalo`), se
    calcula dentro de `ejecutar_aislado` y se consume ahí mismo en dos
    `raise`; nunca se devuelve. No tiene miembro para un error tipificado del
    módulo, para un empaquetado mal formado, para un rechazo de contrato
    anterior al `spawn`, ni para una saturación. Este enum describe otra cosa:
    cómo terminó la petición completa.

    **La saturación no es miembro de este enum, deliberadamente.** Una
    petición rechazada por saturación no llega nunca a la ruta: muere en el
    middleware de admisión, con el cuerpo sin leer. No tiene cantidad de
    archivos, ni bytes, ni duración de ruta que registrar, así que compartir
    la forma del registro de ejecución obligaría a inventar ceros que se
    leerían como mediciones. Va por su propia línea (`EVENTO_SATURACION`).
    """

    EXITO = "exito"
    RECHAZO_TIPIFICADO = "rechazo_tipificado"
    EJECUCION_EXPIRADA = "ejecucion_expirada"
    FALLO_DEL_MODULO = "fallo_del_modulo"
    HIJO_MUERTO = "hijo_muerto"
    EMPAQUETADO_MAL_FORMADO = "empaquetado_mal_formado"
    FALLO_NO_CLASIFICADO = "fallo_no_clasificado"


def sanear_texto(texto: str, *, largo_max: int = LARGO_MAX_TEXTO_SIN_VALIDAR) -> str:
    """Deja `texto` seguro para una bitácora orientada a líneas.

    Dos peligros concretos, ambos reales en la ruta que llega al middleware de
    admisión: uvicorn **percent-decodifica** `scope["path"]` antes de que
    ningún código de la aplicación lo vea, así que un cliente puede colocar
    ahí saltos de línea y caracteres de control y fabricar una segunda línea
    de log falsa; y una ruta arbitrariamente larga infla la línea. Todo
    carácter no imprimible se reemplaza por su escape textual (`\\x0a`) y el
    resultado se recorta.
    """
    recortado = texto[:largo_max]
    return "".join(
        caracter if caracter.isprintable() else f"\\x{ord(caracter):02x}" for caracter in recortado
    )


def clave_sin_validar_de_la_ruta(ruta: str) -> str:
    """Último segmento de `ruta`, ya saneado. **Cadena del cliente, sin validar.**

    En el momento en que `admitir()` levanta `ServicioSaturado` la ruta todavía
    no se resolvió contra ninguna `Route`: el `Mount` de `/interno` deja
    `scope["path_params"]` vacío y no recorta `scope["path"]`. La única forma
    de nombrar el procesador que el cliente *pretendía* usar es recortar la
    ruta a mano, y lo que sale de ahí es texto arbitrario: puede no
    corresponder a ninguna clave del registro. El nombre del campo lo dice
    (`clave_sin_validar`) porque la cardinalidad de este valor la elige el
    cliente, no el servicio.
    """
    return sanear_texto(ruta.rstrip("/").rpartition("/")[2])


class FormateadorJsonLineas(logging.Formatter):
    """Un objeto JSON por línea, con los campos de `extra=` incorporados.

    Existe porque `extra=` por sí solo no produce ninguna salida: los campos
    viven en el `LogRecord` y un formateador que no los conozca los descarta.
    Y `caplog.records` no pasa por ningún formateador, así que sin una prueba
    que llame a `handler.format(record)` el renderizado quedaría sin cubrir.

    `default=str` cierra el caso de un valor no serializable: la línea sale
    igual, degradada, en vez de romper la emisión del log.
    """

    def format(self, record: logging.LogRecord) -> str:
        carga: dict[str, Any] = {
            "ts": self.formatTime(record),
            "nivel": record.levelname,
            "logger": record.name,
            "mensaje": record.getMessage(),
        }
        for clave, valor in vars(record).items():
            if clave not in _ATRIBUTOS_ESTANDAR:
                carga[clave] = valor
        return json.dumps(carga, ensure_ascii=False, default=str)


def configurar_logging(*, flujo: TextIO | None = None) -> logging.Logger:
    """Deja el logger `app` emitiendo JSON por líneas a `stderr`. Idempotente.

    Punto de entrada **explícito**: lo llama `crear_app()`. No se dispara al
    importar este módulo ni ninguno de `app/core/` (ver la docstring del
    módulo: el hijo de `spawn` reimporta esa cadena entera).

    No lee `Configuracion`: no toca `obtener_configuracion()` ni ninguna
    variable de entorno. Eso mantiene intacta la convención de pereza que
    `tests/test_convenciones_pereza.py` fija —importar `app.main` no debe
    construir la configuración— aun cuando `app.main` llame a esta función a
    nivel de módulo.

    `propagate` se deja en `True` a propósito: `caplog` engancha su handler en
    la raíz, así que cortar la propagación haría que toda prueba basada en
    `caplog` pasara vacuamente (el mismo modo de fallo que
    `tests/test_seguridad_access_log.py` documenta para `uvicorn.access`).

    Idempotente por reemplazo, no por acumulación: un handler propio previo se
    quita antes de instalar el nuevo. `crear_app()` corre una vez por prueba en
    varias suites, y sin esto cada llamada agregaría una copia más del handler
    —y una línea duplicada más por evento—.
    """
    logger = logging.getLogger(NOMBRE_LOGGER)
    for previo in list(logger.handlers):
        if getattr(previo, _MARCA_DEL_HANDLER, False):
            logger.removeHandler(previo)
            previo.close()

    manejador = logging.StreamHandler(sys.stderr if flujo is None else flujo)
    setattr(manejador, _MARCA_DEL_HANDLER, True)
    manejador.setFormatter(FormateadorJsonLineas())
    manejador.setLevel(logging.INFO)
    logger.addHandler(manejador)
    # LOAD-BEARING: sin esto el nivel efectivo lo hereda de la raíz, que
    # uvicorn deja sin fijar (WARNING), y ningún `info` saldría jamás.
    logger.setLevel(logging.INFO)
    logger.propagate = True
    return logger


def obtener_logger() -> logging.Logger:
    """El logger de la aplicación. Sin efecto: `getLogger` no configura nada."""
    return logging.getLogger(NOMBRE_LOGGER)


def registrar_ejecucion(
    *,
    clave: str,
    archivos: int,
    bytes_recibidos: int,
    duracion_ruta_ms: float,
    resultado: ResultadoDeEjecucion,
    tipo_error: str | None = None,
    mensaje_error: str | None = None,
    traza: str | None = None,
) -> None:
    """Emite la línea de registro de una ejecución (BACKLOG fila 14).

    `duracion_ruta_ms` es **el reloj de la ruta**: mide el trabajo dentro del
    cuerpo de `app.recepcion.recibir`, desde que el contrato se resuelve hasta
    que la respuesta queda construida. El nombre lleva `ruta` por eso. **No es
    la duración de la petición completa** —quedan fuera el parseo multipart,
    la admisión, la autenticación y el envío del cuerpo de respuesta— **ni la
    del hijo dedicado**. El ítem #17 necesita el reloj del hijo por separado
    para calibrar `TIMEOUT_EJECUCION`; éste no sirve para eso y no debe
    presentarse como si sirviera.

    `bytes_recibidos` cuenta los bytes efectivamente copiados a disco, la
    misma definición que `tamano_comprimido` (ADR 0020): una petición
    rechazada en la fase 1 registra `0` porque no escribió ni un byte, y eso
    es un dato, no un hueco.

    **La traza del hijo va al log, con un costo conocido.** `FalloDelModulo.traza`
    y el mensaje de `SalidaMalFormada` están explícitamente designados como
    material de logging (ADR 0022; `app/core/fallos_http.py:23-24`), que es lo
    que permite que la respuesta HTTP sea un 500 desnudo. El costo: una traza
    de Python lleva rutas absolutas del servidor y, en el peor caso, valores de
    datos del módulo que se cayó (un `repr` dentro de un mensaje de excepción).
    Un diseño archivado ya lo había marcado. Se acepta a conciencia —sin esa
    traza, un 500 desnudo es indiagnosticable— y queda escrito acá para que sea
    una decisión revisable y no un descuido descubierto más tarde.
    """
    # `clave` también es texto del cliente: FastAPI la toma del parámetro de
    # ruta ya percent-decodificado, así que un rechazo por clave inexistente
    # puede traer saltos de línea. Mismo saneo, mismo motivo que la ruta de la
    # línea de saturación; una clave legítima es imprimible y sale intacta.
    campos: dict[str, Any] = {
        "evento": EVENTO_EJECUCION,
        "clave": sanear_texto(clave),
        "archivos": archivos,
        "bytes_recibidos": bytes_recibidos,
        "duracion_ruta_ms": round(duracion_ruta_ms, 3),
        "resultado": resultado.value,
    }
    if tipo_error is not None:
        campos["tipo_error"] = tipo_error
    if mensaje_error is not None:
        campos["mensaje_error"] = mensaje_error
    if traza is not None:
        campos["traza"] = traza
    obtener_logger().info("ejecucion terminada", extra=campos)


def registrar_saturacion(*, metodo: str, ruta: str, ejecuciones_max: int) -> None:
    """Emite la línea de un rechazo por saturación (503).

    Sin esta línea, un `EJECUCIONES_MAX` mal calibrado se ve exactamente igual
    que un servicio caído: 503 y nada más (BACKLOG fila 14).

    Lo que esta línea **no** lleva, y por qué: cantidad de archivos, tamaños y
    duración. En el punto donde `admitir()` rechaza, el cuerpo de la petición
    no se leyó, no se reservó ningún temporal y no se copió ningún byte —eso es
    justamente lo que `tests/test_admision.py` afirma—. Cualquiera de esos tres
    campos sería un número inventado.

    Tampoco se lee el contador interno del semáforo ni se lleva un contador
    paralelo: `app/core/ejecucion.py:95-97` lo prohíbe explícitamente y el
    `ValueError` de `BoundedSemaphore` es el detector que esa prohibición
    protege. `ejecuciones_max` viene de la configuración, que sí es pública.

    `metodo` y `ruta` se sanean acá adentro, no en quien llama: es la última
    frontera antes de la bitácora y sanear en un solo lugar es lo que hace
    honesta la afirmación de que nada sin sanear llega a la línea.
    """
    obtener_logger().info(
        "peticion rechazada por saturacion",
        extra={
            "evento": EVENTO_SATURACION,
            "metodo": sanear_texto(metodo),
            "ruta_sin_validar": sanear_texto(ruta),
            "clave_sin_validar": clave_sin_validar_de_la_ruta(ruta),
            "ejecuciones_max": ejecuciones_max,
        },
    )


def registrar_descartes(
    *,
    clave: str,
    archivo: str,
    filas_procesadas: int,
    descartes: list[tuple[str, int]],
) -> None:
    """Emite la línea de las filas que un procesador descartó (ítem #16).

    Tercer evento del módulo, con la misma forma que los otros dos: primitivos
    sueltos, nada de objetos del dominio, `evento` como discriminador.

    **La emite el proceso HIJO, no la ruta**, y eso tiene una consecuencia que
    conviene saber antes de leer una bitácora: no comparte contexto con la
    línea `ejecucion` que emite `app/recepcion.py`, así que las dos no están
    correlacionadas más allá de `clave` y de su cercanía en el tiempo.
    Correlacionarlas de verdad exigiría ensanchar el mensaje que cruza el
    `Pipe` de ADR 0012 —hoy son exactamente tres formas cerradas— y eso es una
    enmienda a esa frontera, no un detalle de este ítem.

    El hijo hereda el `stderr` del padre, de modo que la línea sale por el
    mismo flujo. Lo que el hijo NO hereda es la configuración de logging:
    quien llame a esta función desde un procesador tiene que haber llamado
    antes a `configurar_logging()`, siempre dentro del cuerpo de `procesar` y
    nunca al importar.

    `descartes` viaja como lista de `(motivo, fila)` en vez de un objeto del
    dominio para no atar este módulo a ningún procesador: `app/core/` no sabe
    que `app/procesadores/` existe (ADR 0011), y esta función vive en `core/`.
    """
    conteo: dict[str, int] = {}
    for motivo, _fila in descartes:
        conteo[motivo] = conteo.get(motivo, 0) + 1
    obtener_logger().info(
        "filas descartadas por el procesador",
        extra={
            "evento": EVENTO_DESCARTES,
            "clave": sanear_texto(clave),
            "archivo": sanear_texto(archivo),
            "filas_procesadas": filas_procesadas,
            "filas_descartadas": len(descartes),
            "por_motivo": conteo,
            # Las filas concretas, acotadas: el detalle completo ya viaja en
            # `descartes.txt` dentro de la respuesta. Acá alcanza con una
            # muestra para saber por dónde mirar sin inflar la bitácora.
            "filas": [fila for _motivo, fila in descartes[:20]],
        },
    )
