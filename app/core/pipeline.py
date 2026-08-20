"""Pipeline común de una ejecución (BACKLOG ítem #10; ADR 0011).

ADR 0011 nombra este archivo. Su contenido es el tramo interior de la
ejecución —los pasos 6, 7 y 8: validar, procesar y empaquetar— y **ninguna
referencia a un procesador concreto**: el único valor con forma de procesador
que cruza esta firma es `clave: str`, exactamente la misma disciplina que
`app.core.ejecucion` impone sobre la frontera del proceso hijo (ADR 0012).

Reparto de los nueve pasos, dicho honestamente en vez de reclamado:
`app/recepcion.py` conserva los pasos 1-5 (resolución del contrato,
validaciones de borde, reserva del temporal y copia acotada) y el paso 9 (la
respuesta), porque son justo los pasos que necesitan `UploadFile` y un tipo
de Starlette. El `try/finally` de la propiedad del temporal tampoco se muda
acá: ADR 0020 otorga esa propiedad a un único punto de transferencia
(`Reserva.ceder_limpieza`), y ese punto vive donde se construye la respuesta
que hereda el directorio. Reclamarlo también acá sería un segundo dueño.

Consecuencia directa de ese reparto: este módulo recibe un `Path` desnudo,
nunca una `Reserva` —el mismo contrato que `app.core.empaquetado` ya tiene—.
No importa ningún tipo de Starlette/FastAPI, no construye ninguna respuesta
HTTP, y no importa nada de `app/procesadores/` (invariante de ADR 0011).

Lo que este módulo **no** hace, también a propósito: no atrapa nada. Un
`ErrorTipificado` levantado por el módulo, un `FalloDeEjecucion` de la
plomería del proceso o una `SalidaMalFormada` del empaquetado se propagan
verbatim hasta los manejadores registrados en `crear_app()`
(`app.core.errores` y `app.core.fallos_http`). Tampoco toca el semáforo de
admisión: `AdmisionDeBorde` es el único sitio de adquisición y de liberación
en todo el repositorio (ítem #8, design.md §3).
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from app.core.ejecucion import ejecutar_modulo
from app.core.empaquetado import empaquetar
from app.core.tipos import ArchivoEntrada, ArchivoSalida


def ejecutar_pipeline(
    *,
    clave: str,
    entradas: list[ArchivoEntrada],
    directorio: Path,
    timeout: timedelta,
) -> ArchivoSalida:
    """Ejecuta el módulo de `clave` sobre `entradas` y empaqueta su salida.

    Dos llamadas, en este orden y sin nada en medio:

    1. `ejecutar_modulo` (pasos 6 y 7 fusionados en un solo hijo dedicado:
       `validar` y `procesar` corren en el mismo `spawn` para no pagar dos
       veces la reimportación del árbol de módulos — ítem #8, design.md §7).
    2. `empaquetar` (paso 8): cero salidas levanta `ErrorContenido.sin_salidas()`
       antes de tocar disco, una se devuelve verbatim, dos o más se comprimen
       en un único ZIP plano escrito dentro de `directorio`.

    `directorio` es el temporal exclusivo de la petición, ya reservado por
    quien llama. Este módulo escribe dentro de él a través de `empaquetar` y
    no lo crea ni lo borra: la propiedad sigue siendo de quien lo reservó.
    """
    archivos = ejecutar_modulo(clave=clave, entradas=entradas, timeout=timeout)
    return empaquetar(archivos=archivos, directorio=directorio)
