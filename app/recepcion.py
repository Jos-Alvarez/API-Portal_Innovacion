"""Ruta de recepción de temporales (ítem #6, segunda mitad; design.md §4).

**Desviación deliberada de ADR 0006, marcada a propósito.** ADR 0006 decide
"una ruta interna por procesador" y rechaza explícitamente "una sola ruta
genérica". Esa decisión presumía al menos un procesador para nombrar, y
cuando este módulo se escribió no existía ninguno. Este módulo es por lo
tanto un andamiaje temporal de recepción: una única ruta parametrizada por
`clave_procesador`, no una decisión arquitectónica que compita con ADR 0006.
No enmienda ni reemplaza esa decisión. El ítem #12 dio de alta los dos
primeros procesadores (`passthrough`, `passthrough_multi`) **sin** tocar esta
ruta, a propósito: sustituirla por las rutas cáscara literales que ADR 0011
ubica bajo `app/procesadores/{clave}/` es un ítem aparte. Ver también
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

import time
from pathlib import Path
from typing import IO, Annotated, Final

from fastapi import APIRouter, File, UploadFile
from starlette.concurrency import run_in_threadpool
from starlette.responses import FileResponse, Response

from app.core.configuracion import obtener_configuracion
from app.core.contrato import obtener_contrato
from app.core.ejecucion import EjecucionExpirada, FalloDelModulo, HijoMuerto
from app.core.empaquetado import SalidaMalFormada
from app.core.errores import ErrorClaveInexistente, ErrorTamano, ErrorTipificado
from app.core.pipeline import ejecutar_pipeline
from app.core.registro import ResultadoDeEjecucion, registrar_ejecucion
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

    Mientras `_TABLA_CONTRATOS` estuvo vacía, la consecuencia honesta de subir
    la resolución del contrato por encima de la copia era que **ninguna subida
    llegaba a disco en producción**: toda petición moría en
    `ErrorClaveInexistente` antes de la fase 2. El ítem #12 dio de alta las dos
    primeras filas, así que ese tramo ya se recorre de verdad con una clave
    conocida. La regla no cambió y sigue siendo la correcta: una clave
    desconocida no cuesta ni un `mkdtemp` ni un byte.

    El ítem #10 cerró la costura que quedaba al final de la fase 2: donde
    había un `raise NotImplementedError` ahora corren los pasos 6-8
    (`app.core.pipeline.ejecutar_pipeline`) y el paso 9, la `FileResponse`
    que hereda la propiedad del directorio vía `reserva.ceder_limpieza()`.

    **El ítem #14 envuelve las dos fases en `try/except/finally` para emitir la
    línea de registro de la ejecución, y todo lo que atrapa lo re-levanta.**
    Ésa es la regla, no una precaución: los manejadores registrados en
    `crear_app()` siguen siendo los únicos que construyen respuestas, así que
    ningún `except` de acá puede cambiar un código de estado. Cada rama sólo
    anota qué pasó y vuelve a levantar; el `finally` emite una línea —y
    exactamente una— por cada petición que entró a este cuerpo.

    El reloj es **de la ruta**: arranca antes de resolver el contrato y para
    cuando la respuesta ya está construida. No mide el parseo multipart ni la
    admisión (ocurren antes de este cuerpo), ni el envío del cuerpo de
    respuesta, ni el hijo dedicado por separado. El ítem #17 necesita el reloj
    del hijo para calibrar `TIMEOUT_EJECUCION`; éste no es ése.

    `app/core/pipeline.py` sigue sin atrapar nada: su docstring lo promete y
    esta entrega no lo toca. El `try` vive acá, en el borde HTTP, que es donde
    ya vivía el reparto de responsabilidades del ítem #10.
    """
    inicio = time.perf_counter()
    # Arranca en el desenlace no clasificado, no en éxito: así una salida que
    # ninguna rama nombra —`asyncio.CancelledError` por desconexión del
    # cliente, que no es `Exception` y por lo tanto ningún `except` de acá
    # atrapa— se registra como lo que es, y no como un éxito falso.
    resultado = ResultadoDeEjecucion.FALLO_NO_CLASIFICADO
    tipo_error: str | None = None
    mensaje_error: str | None = None
    traza: str | None = None
    # Bytes efectivamente copiados a disco (la definición de `tamano_comprimido`,
    # ADR 0020). Vive fuera del `try` para que una falla a mitad de la fase 2
    # registre lo que sí se escribió; un rechazo de fase 1 registra `0` porque
    # no escribió nada.
    bytes_recibidos = 0
    try:
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
                validar_tamano(
                    nombre_original=nombre_original, tamano_bytes=tamano, contrato=contrato
                )
            validar_tamano_total(nombres=nombres, total_bytes=sum(medidos), contrato=contrato)

        with reservar() as reserva:
            entradas: list[ArchivoEntrada] = []
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
                bytes_recibidos += tamano_comprimido
                validar_tamano_total(
                    nombres=nombres[: indice + 1], total_bytes=bytes_recibidos, contrato=contrato
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
            respuesta = FileResponse(
                salida.ruta_temporal,
                filename=salida.nombre_propuesto,
                media_type=salida.tipo_mime,
                background=reserva.ceder_limpieza(),
            )
            resultado = ResultadoDeEjecucion.EXITO
            return respuesta
    except ErrorTipificado as error:
        # Los cinco tipos de ADR 0014, sea cual sea su código HTTP: los cuatro
        # corregibles (422) y `clave_inexistente` (500). `tipo` los distingue en
        # la línea; el desenlace no necesita un miembro por cada uno.
        resultado = ResultadoDeEjecucion.RECHAZO_TIPIFICADO
        tipo_error = error.tipo.value
        raise
    except EjecucionExpirada:
        resultado = ResultadoDeEjecucion.EJECUCION_EXPIRADA
        tipo_error = EjecucionExpirada.__name__
        raise
    except FalloDelModulo as fallo:
        # La traza del hijo es material de logging por decisión explícita
        # (ADR 0022, `app/core/fallos_http.py:23-24`): nunca sale al cliente,
        # pero sin ella un 500 desnudo es indiagnosticable. Ver el costo
        # aceptado en la docstring de `registrar_ejecucion`.
        resultado = ResultadoDeEjecucion.FALLO_DEL_MODULO
        tipo_error = fallo.clase
        mensaje_error = fallo.mensaje
        traza = fallo.traza
        raise
    except HijoMuerto as fallo:
        resultado = ResultadoDeEjecucion.HIJO_MUERTO
        tipo_error = HijoMuerto.__name__
        mensaje_error = f"exitcode={fallo.exitcode}"
        raise
    except SalidaMalFormada as fallo:
        resultado = ResultadoDeEjecucion.EMPAQUETADO_MAL_FORMADO
        tipo_error = SalidaMalFormada.__name__
        mensaje_error = str(fallo)
        raise
    except Exception as fallo:
        resultado = ResultadoDeEjecucion.FALLO_NO_CLASIFICADO
        tipo_error = type(fallo).__name__
        raise
    finally:
        registrar_ejecucion(
            clave=clave_procesador,
            archivos=len(archivos),
            bytes_recibidos=bytes_recibidos,
            duracion_ruta_ms=(time.perf_counter() - inicio) * 1000,
            resultado=resultado,
            tipo_error=tipo_error,
            mensaje_error=mensaje_error,
            traza=traza,
        )
