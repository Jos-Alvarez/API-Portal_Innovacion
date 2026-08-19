"""Ruta de recepción de temporales (ítem #6, segunda mitad; design.md §4).

**Desviación deliberada de ADR 0006, marcada a propósito.** ADR 0006 decide
"una ruta interna por procesador" y rechaza explícitamente "una sola ruta
genérica". Esa decisión presume al menos un procesador para nombrar; hoy no
existe ninguno (`app.core.contrato.obtener_contrato` devuelve `None` para
toda clave). Este módulo es por lo tanto un andamiaje temporal de recepción:
una única ruta parametrizada por `clave_procesador`, no una decisión
arquitectónica que compita con ADR 0006. No enmienda ni reemplaza esa
decisión; los ítems #12/#16 la sustituyen por las rutas literales por
procesador que ADR 0011 ubica bajo `app/procesadores/{clave}/`. Ver también
adrs/0020, sección Consecuencias.

Módulo de nivel superior siguiendo el precedente ya embarcado de
`app/salud.py` (V10 del design.md): la superficie HTTP vive en `app/`, no en
`app/core/`, que es el pipeline. Importa `app.core.temporales` (la
propiedad/limpieza), `app.core.contrato` y `app.core.errores`, pero nada de
`app/procesadores/` (invariante de ADR 0011).
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import IO, Annotated, Final

from fastapi import APIRouter, File, UploadFile
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

from app.core.contrato import obtener_contrato
from app.core.errores import ErrorClaveInexistente
from app.core.temporales import reservar
from app.core.tipos import ArchivoEntrada

router_recepcion = APIRouter()

_TROZO: Final[int] = 1024 * 1024


def _formato(nombre_original: str) -> str:
    """Extensión del nombre declarado por el cliente, en minúsculas, sin punto.

    `rpartition`, NUNCA `Path(nombre_original).suffix`: construir un `Path` a
    partir de una cadena del cliente es exactamente la operación que esta
    decisión prohíbe, aunque el resultado sólo se lea (design.md §5). Acá se
    manipula texto, nunca una ruta.
    """
    _nombre, punto, extension = nombre_original.rpartition(".")
    return extension.lower() if punto else ""


def _copiar(origen: IO[bytes], destino: Path) -> int:
    """Copia el contenido de `origen` a `destino`, devuelve los bytes escritos.

    `tamano_comprimido` cuenta lo que realmente llegó a disco, nunca
    `Content-Length` ni `UploadFile.size` (design.md §5) -- H-09's mentira de
    `Content-Length` sigue siendo del ítem #7.
    """
    origen.seek(0)  # defensivo: no depender de dónde dejó el cursor el parser
    with destino.open("wb") as salida:
        shutil.copyfileobj(origen, salida, _TROZO)
        return salida.tell()


@router_recepcion.post("/procesadores/{clave_procesador}")
async def recibir(
    clave_procesador: str,
    archivos: Annotated[list[UploadFile], File()],
) -> Response:
    """Recibe uno o más archivos multipart, los escribe bajo un directorio
    temporal propio de la petición, y resuelve contra el contrato de
    `clave_procesador` (design.md §4).

    Hoy `obtener_contrato` devuelve `None` para toda clave (V8): el único
    desenlace posible es `ErrorClaveInexistente(causa="fila_ausente")`. No se
    finge un camino de éxito que todavía no puede existir -- los ítems
    #9/#10 son los que cambian el `return` final por
    `FileResponse(..., background=reserva.ceder_limpieza())`.
    """
    with reservar() as reserva:
        entradas: list[ArchivoEntrada] = []
        for indice, carga in enumerate(archivos):
            nombre_original = carga.filename or ""
            ruta_temporal = reserva.directorio / f"entrada_{indice}"
            tamano_comprimido = await run_in_threadpool(_copiar, carga.file, ruta_temporal)
            entradas.append(
                ArchivoEntrada(
                    nombre_original=nombre_original,
                    ruta_temporal=ruta_temporal,
                    tamano_comprimido=tamano_comprimido,
                    formato=_formato(nombre_original),
                )
            )
        del entradas  # costura del ítem #7: consumido por la validación de contrato
        contrato = obtener_contrato(clave_procesador)
        if contrato is None:
            raise ErrorClaveInexistente(clave_procesador=clave_procesador, causa="fila_ausente")
        # Costura de los ítems #9/#10 -- el único cambio que necesitan acá:
        #   return FileResponse(salida, background=reserva.ceder_limpieza())
        raise NotImplementedError  # inalcanzable hoy (V8); el ítem #7 sigue desde acá
