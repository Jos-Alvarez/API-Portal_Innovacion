"""Validaciones de contrato y presupuesto de memoria (ítem #7; ADR 0021).

Cinco funciones puras que comparan números y cadenas contra un
`ContratoProcesador` y levantan los errores tipificados ya embarcados. La idea
organizadora, y la única que hace falta recordar para leer este módulo: **el
contrato es una precondición de la copia, no una postcondición**. Toda función
de acá es más barata que la escritura que protege, y todas menos
`validar_tamano_descomprimido` se contestan sin tocar el disco.

Reciben primitivos (`str`, `int`) más el contrato; **nunca** un `UploadFile` ni
ningún otro tipo de Starlette. La ruta extrae, el núcleo compara. Así este
módulo es ejercitable con contratos construidos a mano —imprescindible,
porque `_TABLA_CONTRATOS` está vacía— y ningún llamador futuro no-multipart
(ítem #10) arrastra Starlette consigo.

Los límites se comparan con `>`: un valor exactamente igual al límite se
acepta; recién el siguiente byte (o archivo) rechaza.

Este módulo importa únicamente la biblioteca estándar más `app.core`; no
importa nada de `app/procesadores/` (invariante de ADR 0011).
"""

from __future__ import annotations

import zipfile
from typing import Final

from app.core.contrato import ContratoProcesador
from app.core.errores import ErrorCantidad, ErrorFormato, ErrorTamano
from app.core.tipos import ArchivoEntrada

PRESUPUESTO_DE_RAM_BYTES: Final[int] = 256 * 1024 * 1024
"""Techo del tamaño declarado sin comprimir de un archivo, por archivo.

Elección con piso fundado, no una cita (ADR 0021): `tamano_max_bytes` acota una
subida en 25 MB comprimidos y un `.xlsx` —XML dentro de un ZIP— comprime del
orden de 5–20×, así que 250 MB es el techo realista del rango legítimo; 256 MB
queda holgadamente por debajo de la memoria de cualquier worker plausible
(ADR 0006).

Constante de módulo y no campo de `ContratoProcesador`, siguiendo el precedente
de `UMBRAL_DE_EDAD`/`INTERVALO_DE_BARRIDO` en `app/core/temporales.py`: ADR 0006
trata el techo de memoria como asunto del worker, no como valor por procesador.

No es un techo de memoria de verdad. Acota un número que escribe quien sube el
archivo; `zipfile` nota una mentira recién después de descomprimir y verificar
el CRC, y lo que agota la RAM es el `DataFrame`, no el XML crudo. Primera línea
de defensa solamente: el techo real es del ítem #8 (H-04 sigue parcialmente
abierto).
"""


def validar_cantidad(*, recibido: int, contrato: ContratoProcesador) -> None:
    """Cantidad de archivos del lote contra `entradas_min`/`entradas_max`."""
    if not contrato.entradas_min <= recibido <= contrato.entradas_max:
        raise ErrorCantidad(
            minimo=contrato.entradas_min,
            maximo=contrato.entradas_max,
            recibido=recibido,
        )


def validar_formato(*, nombre_original: str, formato: str, contrato: ContratoProcesador) -> None:
    """Extensión ya extraída contra `formatos_aceptados`.

    Recibe el formato ya extraído en lugar de extraerlo: sacar la extensión de
    un nombre declarado por el cliente es asunto de la superficie HTTP, con su
    propia regla (`rpartition`, nunca `Path().suffix`), y vive pinchada en
    `app/recepcion.py`. Acá se compara una cadena; nunca se toca el sistema de
    archivos.
    """
    if formato not in contrato.formatos_aceptados:
        raise ErrorFormato(
            archivo=nombre_original,
            formato_recibido=formato,
            formatos_aceptados=list(contrato.formatos_aceptados),
        )


def validar_tamano(
    *, nombre_original: str, tamano_bytes: int, contrato: ContratoProcesador
) -> None:
    """Tamaño de un archivo contra `tamano_max_bytes`.

    `tamano_bytes` es siempre una cuenta real: la que Starlette midió al volcar
    la parte (`UploadFile.size` se construye en cero y se incrementa por trozo
    escrito, nunca desde `Content-Length`), o los bytes que la copia acotada
    alcanzó a escribir. Nunca un número declarado por el cliente.
    """
    if tamano_bytes > contrato.tamano_max_bytes:
        raise ErrorTamano(
            archivo=nombre_original,
            limite_bytes=contrato.tamano_max_bytes,
            recibido_bytes=tamano_bytes,
        )


def validar_tamano_total(
    *, nombres: list[str], total_bytes: int, contrato: ContratoProcesador
) -> None:
    """Suma del lote contra `tamano_max_total_bytes`.

    Ningún archivo es el culpable, así que el error lleva la forma hermana
    `ContextoTamanoTotal` con la lista completa sobre la que se sumó (ADR 0021).
    """
    if total_bytes > contrato.tamano_max_total_bytes:
        raise ErrorTamano.total(
            archivos=list(nombres),
            limite_bytes=contrato.tamano_max_total_bytes,
            recibido_bytes=total_bytes,
        )


def validar_tamano_descomprimido(
    entrada: ArchivoEntrada, *, presupuesto_bytes: int = PRESUPUESTO_DE_RAM_BYTES
) -> None:
    """Tamaño declarado sin comprimir contra el presupuesto de RAM.

    Lee **sólo el directorio central** del ZIP: `ZipFile.infolist()` devuelve el
    `ZipInfo.file_size` declarado de cada entrada sin descomprimir ni un byte de
    contenido. Ese número es una **declaración** del que armó el archivo; se
    compara contra un presupuesto y nunca se usa para dimensionar un buffer.

    Dos casos son no-ops deliberados, no fallos:

    - **No es un ZIP.** No hay tamaño declarado que comprobar. ADR 0006 afirma
      que tales archivos quedan "acotados por el tope de 25 MB comprimido";
      H-04 llama falsa a esa afirmación y el ítem #8 es el dueño de la
      respuesta. Esta función no finge lo contrario.
    - **ZIP corrupto** (`BadZipFile`). Decidir si un archivo es un `.xlsx`
      válido es validación de **contenido**, y `ContextoContenido.motivo` es un
      `Literal` cerrado sin vocabulario para expresarlo. Inventar un fallo que
      el enum cerrado no puede nombrar es exactamente la presión que ADR 0014
      existe para resistir; el procesador (ítems #12/#16) falla ahí como
      corresponde.

    La suma es **por archivo**, no por lote: ésa es la forma de una bomba ZIP.
    Hoy `entradas_max = 1` hace que lote y archivo sean lo mismo.
    """
    if not zipfile.is_zipfile(entrada.ruta_temporal):
        return

    try:
        with zipfile.ZipFile(entrada.ruta_temporal) as archivo:
            declarado = sum(info.file_size for info in archivo.infolist())
    except zipfile.BadZipFile:
        return

    if declarado > presupuesto_bytes:
        raise ErrorTamano(
            archivo=entrada.nombre_original,
            limite_bytes=presupuesto_bytes,
            recibido_bytes=declarado,
        )
