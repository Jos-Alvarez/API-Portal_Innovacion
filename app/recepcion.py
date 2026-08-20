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
propiedad/limpieza), `app.core.contrato`, `app.core.errores`,
`app.core.validaciones` y `app.core.pipeline`, pero nada de
`app/procesadores/` (invariante de ADR 0011). El tráfico va en un solo
sentido: ningún tipo de Starlette cruza hacia `app/core/` — la ruta extrae
`filename`/`size`/`file` y le pasa al pipeline un `Path` desnudo, el núcleo
compara (ADR 0021).
"""

from __future__ import annotations

from pathlib import Path
from typing import IO, Annotated, Final

from fastapi import APIRouter, File, UploadFile
from starlette.concurrency import run_in_threadpool
from starlette.responses import FileResponse, Response

from app.core.configuracion import obtener_configuracion
from app.core.contrato import obtener_contrato
from app.core.errores import ErrorClaveInexistente, ErrorTamano
from app.core.pipeline import ejecutar_pipeline
from app.core.temporales import reservar
from app.core.tipos import ArchivoEntrada
from app.core.validaciones import (
    validar_cantidad,
    validar_formato,
    validar_tamano,
    validar_tamano_descomprimido,
    validar_tamano_total,
)

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


def _copiar(origen: IO[bytes], destino: Path, *, limite_bytes: int, nombre_original: str) -> int:
    """Copia `origen` en `destino` con techo, devuelve los bytes escritos.

    `tamano_comprimido` cuenta lo que realmente llegó a disco, nunca
    `Content-Length` ni `UploadFile.size` (ADR 0020).

    El techo no está para atrapar una mentira de tamaño: `UploadFile.size` es
    una cuenta medida por el parser, no una declaración del cliente, así que no
    hay tal mentira (ADR 0021). Está porque `size` es `int | None` y ésta es la
    **única** aplicación cuando vale `None`; porque un techo del lado del
    escritor mantiene cierta por construcción la definición de
    `tamano_comprimido`; y porque los ítems #9/#10 son los próximos llamadores
    de esta costura y no deben poder excederse por olvidar la comprobación
    previa.

    El bloque que cruza el límite se escribe entero en vez de partirse: el
    desborde queda acotado a un trozo (1 MiB) y `recibido_bytes` sale como una
    cuenta real estrictamente mayor que el límite, en lugar de un número igual
    al tope que no explicaría el rechazo.

    El `raise` va **después** de cerrar el `with`, no adentro: en Windows,
    `rmtree` sobre un manejador abierto levanta `PermissionError`, que ADR 0020
    sólo tolera difiriendo al barrendero. Cerrar primero mantiene la limpieza
    síncrona.
    """
    origen.seek(0)  # defensivo: no depender de dónde dejó el cursor el parser
    escritos = 0
    with destino.open("wb") as salida:
        while trozo := origen.read(_TROZO):
            salida.write(trozo)
            escritos += len(trozo)
            if escritos > limite_bytes:
                break

    if escritos > limite_bytes:
        raise ErrorTamano(
            archivo=nombre_original,
            limite_bytes=limite_bytes,
            recibido_bytes=escritos,
        )
    return escritos


@router_recepcion.post("/procesadores/{clave_procesador}")
async def recibir(
    clave_procesador: str,
    archivos: Annotated[list[UploadFile], File()],
) -> Response:
    """Recibe uno o más archivos multipart y los valida contra el contrato de
    `clave_procesador` antes de escribir nada (ítem #7; ADR 0021).

    **El contrato es una precondición de la copia, no una postcondición.** El
    cuerpo corre en dos fases:

    - **Fase 1, fuera de `reservar()`**: resolución del contrato, cantidad,
      formato y tamaño declarado. Una petición rechazada acá no cuesta ni un
      `mkdtemp` ni un byte. El diseño del ítem #6 ya había rechazado el
      middleware ASGI en parte por crear un directorio temporal para cada
      petición, incluso las que no suben nada; una petición con la clave o la
      cantidad equivocada es exactamente una de ésas.
    - **Fase 2, dentro de `with reservar()`**: la copia acotada, el total
      medido y la inspección del ZIP. Todo lo que falle acá pasa por el
      `finally: reserva.limpiar()` del ítem #6, sin cambios: `temporales.py` no
      se toca en una sola línea.

    Consecuencia honesta de que `obtener_contrato` devuelva `None` para toda
    clave hoy: al subir la resolución del contrato por encima de la copia,
    **ninguna subida llega a disco en producción** — toda petición muere en
    `ErrorClaveInexistente` antes de la fase 2. Es el comportamiento correcto
    (una clave desconocida no debe costar una escritura), pero la evidencia de
    recepción del ítem #6 pasa a depender de un contrato inyectado en pruebas.

    El ítem #10 cerró la costura que quedaba al final de la fase 2: donde
    había un `raise NotImplementedError` ahora corren los pasos 6-8
    (`app.core.pipeline.ejecutar_pipeline`) y el paso 9, la `FileResponse`
    que hereda la propiedad del directorio vía `reserva.ceder_limpieza()`.
    """
    contrato = obtener_contrato(clave_procesador)
    if contrato is None:
        raise ErrorClaveInexistente(clave_procesador=clave_procesador, causa="fila_ausente")

    nombres = [carga.filename or "" for carga in archivos]
    validar_cantidad(recibido=len(archivos), contrato=contrato)
    for nombre_original in nombres:
        validar_formato(
            nombre_original=nombre_original,
            formato=_formato(nombre_original),
            contrato=contrato,
        )

    # Pasada declarada: `UploadFile.size` es la cuenta que Starlette midió al
    # volcar la parte, así que rechazar acá es gratis y verdadero. Es
    # `int | None`: un solo `None` desactiva toda la pasada y el total medido
    # de la fase 2 queda como única autoridad.
    medidos = [carga.size for carga in archivos if carga.size is not None]
    if len(medidos) == len(archivos):
        for nombre_original, tamano in zip(nombres, medidos, strict=True):
            validar_tamano(nombre_original=nombre_original, tamano_bytes=tamano, contrato=contrato)
        validar_tamano_total(nombres=nombres, total_bytes=sum(medidos), contrato=contrato)

    with reservar() as reserva:
        entradas: list[ArchivoEntrada] = []
        total_medido = 0
        for indice, (carga, nombre_original) in enumerate(zip(archivos, nombres, strict=True)):
            ruta_temporal = reserva.directorio / f"entrada_{indice}"
            tamano_comprimido = await run_in_threadpool(
                _copiar,
                carga.file,
                ruta_temporal,
                limite_bytes=contrato.tamano_max_bytes,
                nombre_original=nombre_original,
            )
            entrada = ArchivoEntrada(
                nombre_original=nombre_original,
                ruta_temporal=ruta_temporal,
                tamano_comprimido=tamano_comprimido,
                formato=_formato(nombre_original),
            )
            entradas.append(entrada)

            # Re-comprobado tras CADA copia, no al final: así el archivo (n+1)
            # nunca se copia si el lote ya está pasado de presupuesto.
            total_medido += tamano_comprimido
            validar_tamano_total(
                nombres=nombres[: indice + 1], total_bytes=total_medido, contrato=contrato
            )
            validar_tamano_descomprimido(entrada)

        # Pasos 6-8 (ítem #10). Va DENTRO del `with`, no después: `empaquetar`
        # escribe el ZIP dentro de `reserva.directorio`, así que el directorio
        # tiene que seguir vivo mientras corre el pipeline. Si algo de acá
        # levanta -- un `ErrorTipificado` del módulo, un `FalloDeEjecucion` de
        # la plomería, una `SalidaMalFormada` del empaquetado -- el `finally`
        # de `reservar()` borra, sin ninguna limpieza rival en este archivo.
        #
        # `run_in_threadpool` porque `ejecutar_pipeline` bloquea de verdad
        # (`poll`/`join` sobre el hijo dedicado): correrlo en el bucle de
        # eventos congelaría al worker entero. El semáforo del ítem #8 es un
        # `threading.BoundedSemaphore` justamente para seguir siendo válido
        # desde el threadpool; acá no se toca -- `AdmisionDeBorde` es el único
        # sitio que lo adquiere y lo libera.
        salida = await run_in_threadpool(
            ejecutar_pipeline,
            clave=clave_procesador,
            entradas=entradas,
            directorio=reserva.directorio,
            timeout=obtener_configuracion().timeout_ejecucion,
        )
        # Paso 9. `ceder_limpieza()` sólo acá, en el camino de éxito y después
        # de que el pipeline retornó: transfiere la propiedad del directorio a
        # la respuesta, que lo borra en su `BackgroundTask` una vez enviado el
        # último byte (ADR 0020). `filename` deja la codificación de
        # `Content-Disposition` en manos de Starlette -- ningún encabezado
        # armado a mano acá.
        return FileResponse(
            salida.ruta_temporal,
            filename=salida.nombre_propuesto,
            media_type=salida.tipo_mime,
            background=reserva.ceder_limpieza(),
        )
