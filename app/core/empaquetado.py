"""Empaquetado de salidas (BACKLOG ítem #9; ADR 0011; ADR 0023).

Convierte la `list[ArchivoSalida]` que el ítem #8 ya produce de forma
atómica en el único `ArchivoSalida` que el borde HTTP (ítem #10) puede
responder: cero salidas levanta un error tipificado antes de tocar disco,
una salida se devuelve verbatim, dos o más se comprimen en un único ZIP
plano.

La idea organizadora, y la única que hace falta recordar para leer este
módulo (design.md §1): **toda comprobación que puede fallar es una
precondición de la escritura**. La misma forma de dos fases que ADR 0021 le
dio a `recepcion.py` — contrato primero, bytes después — aplicada al lado de
salida.

Este módulo importa únicamente la biblioteca estándar más `app.core.errores`
y `app.core.tipos`. **No importa nada de `app/procesadores/`** (invariante
de ADR 0011), **nada de `app.core.temporales`** y **nada de
`app.core.ejecucion`**: la ausencia es la prueba mecánica de que este
módulo no reclama una segunda vez la propiedad del ciclo de vida del
directorio temporal que ADR 0020 otorga a un único punto. No aparece ningún
tipo de Starlette/FastAPI en ninguna firma ni cuerpo.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Final

from app.core.errores import ErrorContenido
from app.core.tipos import ArchivoSalida

NOMBRE_DEL_ZIP: Final[str] = "salida.zip"
"""Nombre fijo, generado por el servidor — nunca derivado de una entrada (ADR 0020)."""

MIME_DEL_ZIP: Final[str] = "application/zip"


class SalidaMalFormada(Exception):
    """Un conjunto de salidas mal formado: nombres degenerados o duplicados.

    Deliberadamente **no** es un `ErrorTipificado` (design.md §3). ADR 0014
    describe los cuatro tipos 422 como los que el cliente puede provocar y
    corregir; un `nombre_propuesto` duplicado o degenerado es un bug de
    primera parte (el procesador, ítems #12/#16), no algo que el cliente
    causó o puede corregir. ADR 0018 ya mandó el único caso no-corregible
    (`CLAVE_INEXISTENTE`) a un 500 en vez de un 422, y ADR 0022 fijó la forma
    para "no es un `TipoError`; el ítem #10 es dueño de la traducción HTTP".
    Esta excepción sigue ese mismo camino.
    """


def _nombre_plano(nombre_propuesto: str) -> str:
    """Aplana `nombre_propuesto` a un `arcname` sin componentes de directorio.

    Manipulación de texto, nunca construcción de `Path` — la misma regla que
    `recepcion.py::_formato` fija verbatim para el lado de entrada (design.md
    §5). Ambos separadores se normalizan en ambas plataformas porque el
    nombre lo produce un procesador que puede haberse escrito en cualquiera.

    Un resultado `""`, `"."` o `".."` es degenerado y levanta
    `SalidaMalFormada` en vez de inventar un nombre de reemplazo: fabricar
    uno renombraría un archivo en silencio y podría colisionar él mismo.
    """
    plano = nombre_propuesto.replace("\\", "/").rpartition("/")[2]
    if plano in ("", ".", ".."):
        raise SalidaMalFormada(f"nombre_propuesto degenerado: {nombre_propuesto!r}")
    return plano


def _verificar(archivos: list[ArchivoSalida], destino: Path) -> list[str]:
    """Precondiciones puras de la escritura: ningún byte llega a disco acá.

    En orden: todo nombre aplanado es no degenerado (`_nombre_plano`);
    ningún par aplana al mismo nombre; ningún `ruta_temporal` de entrada es
    igual a `destino`; todo `ruta_temporal` existe. Las cuatro levantan
    `SalidaMalFormada` (spec: "Arcnames are sanitized and duplicate names
    are rejected").
    """
    nombres = [_nombre_plano(archivo.nombre_propuesto) for archivo in archivos]

    vistos: set[str] = set()
    for nombre in nombres:
        if nombre in vistos:
            raise SalidaMalFormada(f"nombre_propuesto duplicado tras aplanar: {nombre!r}")
        vistos.add(nombre)

    for archivo in archivos:
        if archivo.ruta_temporal == destino:
            raise SalidaMalFormada(
                f"ruta_temporal coincide con el destino del ZIP: {archivo.ruta_temporal}"
            )
        if not archivo.ruta_temporal.exists():
            raise SalidaMalFormada(f"ruta_temporal inexistente: {archivo.ruta_temporal}")

    return nombres


def empaquetar(*, archivos: list[ArchivoSalida], directorio: Path) -> ArchivoSalida:
    """Convierte N salidas en la única `ArchivoSalida` que el borde HTTP responde.

    La cardinalidad decide todo: cero levanta un error tipificado antes de
    construir ningún `Path`; una se devuelve verbatim, sin comprobar su
    nombre ni comprimir nada; dos o más se comprimen en un único ZIP plano
    escrito dentro de `directorio`.
    """
    if not archivos:
        raise ErrorContenido.sin_salidas()
    if len(archivos) == 1:
        return archivos[0]

    destino = directorio / NOMBRE_DEL_ZIP
    nombres = _verificar(archivos, destino)

    try:
        with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as contenedor:
            for archivo, plano in zip(archivos, nombres, strict=True):
                contenedor.write(archivo.ruta_temporal, arcname=plano)
    except Exception:
        # El handle ya está cerrado por `__exit__` antes de que corra este
        # `except` (design.md §4, V3), lo que hace seguro el `unlink` en
        # Windows: no hay un manejador abierto sobre el que borrar.
        destino.unlink(missing_ok=True)
        raise

    return ArchivoSalida(
        nombre_propuesto=NOMBRE_DEL_ZIP, ruta_temporal=destino, tipo_mime=MIME_DEL_ZIP
    )
