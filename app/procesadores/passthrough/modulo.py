"""Procesador passthrough: la salida marcada mínima (ítem #12 del backlog).

Es el procesador que existe para **probar la tubería**, no para procesar
nada: navegador → portal → FastAPI → descarga, sin una sola regla de negocio
de por medio (PRD, "Entregables de procesador"). Todo lo interesante ya lo
hacen `core/`: el contrato (`app.core.contrato`), las validaciones de borde
(`app.core.validaciones`), el hijo dedicado (`app.core.ejecucion`) y el
empaquetado (`app.core.empaquetado`).

**Una sola clase, dos claves.** ADR 0006 fija que "la cardinalidad no es un
atributo del módulo: se declara en la fila `procesador` (`entradas_min`,
`entradas_max`)" y que un procesador tiene "un único camino de código, sin
ramas especiales" por cantidad de entradas. Por eso acá hay una única
`Passthrough` —una salida por entrada, siempre— instanciada dos veces en
`app/registry.py` bajo dos claves cuyas filas de `_TABLA_CONTRATOS` difieren
**sólo** en `entradas_min`/`entradas_max`. La variante multi-archivo no es
otro código: es otra fila de contrato.

**Este módulo nunca construye un ZIP** (ADR 0006: "ningún procesador
construye su propio ZIP ni decide cómo se transporta su resultado").
Devolver dos o más `ArchivoSalida` alcanza: `app.core.empaquetado.empaquetar`
produce `salida.zip` por sí solo.

**De dónde sale el directorio de salida, y por qué.** `Procesador.procesar`
recibe `list[ArchivoEntrada]` y nada más — ningún ADR le otorga un directorio
de salida, y agregárselo a la firma sería una enmienda a ADR 0006, no una
decisión de este ítem. La convención deliberada, entonces: el procesador
escribe **al lado de sus entradas**, derivando el directorio de
`entradas[0].ruta_temporal.parent`, que es exactamente `reserva.directorio`,
el temporal exclusivo de la petición cuyo ciclo de vida ADR 0020 le otorga a
`app/recepcion.py`. Escribir ahí es lo que hace que la limpieza cedida a la
`FileResponse` barra también las salidas, sin que este módulo sepa nada de
`app.core.temporales`.

**Qué es una "salida marcada".** Ni el PRD ni el BACKLOG ni ningún ADR lo
definen: sólo exigen que no haya reglas de negocio y que el resultado sea
verificablemente distinto de lo que se subió. Se elige la marca observable
más simple posible: los bytes de la entrada, precedidos por `MARCA`. Es
byte-exacta (una prueba compara `MARCA + original`, no un heurístico), no
mira el contenido, no depende del formato y sobrevive al ZIP.

**Nombres de salida únicos, obligatoriamente.** ADR 0023 hace que dos
`nombre_propuesto` que aplanen al mismo nombre revienten la petición entera
con `SalidaMalFormada`. `nombre_original` lo elige el cliente y puede venir
repetido, así que la marca del nombre **incorpora el índice de la entrada**,
no sólo el nombre: `_nombre_de_salida` aplana primero y prefija después, con
lo que el resultado no contiene separadores y el índice garantiza unicidad.

Este módulo importa la biblioteca estándar más `app.core.errores`,
`app.core.interfaz` y `app.core.tipos`. **No importa `app.core.db`** ni nada
que lo alcance (invariante de ADR 0013/ADR 0011), no crea procesos ni hilos
—el hijo de ADR 0012 corre con `daemon=True` y no puede tener hijos propios—
y no tiene efecto de importación alguno.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from app.core.errores import ErrorTipificado
from app.core.interfaz import Procesador
from app.core.tipos import ArchivoEntrada, ArchivoSalida

MARCA: Final[bytes] = b"PASSTHROUGH\n"
"""Prefijo que distingue la salida de la entrada. Ver docstring del módulo."""

MIME_DE_SALIDA: Final[str] = "application/octet-stream"
"""El passthrough no inspecciona el contenido, así que no puede afirmar un
tipo más preciso que "bytes". Decirlo honestamente vale más que adivinar el
MIME a partir de la extensión que declaró el cliente."""

_TROZO: Final[int] = 1024 * 1024


def _nombre_de_salida(indice: int, nombre_original: str) -> str:
    """Nombre propuesto de la salida de la entrada `indice`.

    Dos pasos, en este orden y no en el otro: primero se aplana el nombre del
    cliente a su último componente —manipulación de texto con `rpartition`,
    nunca `Path(...)`, la misma regla que `app/recepcion.py::_formato` fija
    para el lado de entrada— y recién después se prefija el índice. Al revés,
    `"0_sub/a.csv"` volvería a aplanar a `"a.csv"` dentro de
    `app.core.empaquetado` y dos entradas en distintos subdirectorios podrían
    colisionar pese al índice.

    Con el índice delante, el resultado nunca es degenerado (`""`, `"."` o
    `".."`) ni duplicado, que son las dos formas de `SalidaMalFormada`.
    """
    plano = nombre_original.replace("\\", "/").rpartition("/")[2]
    return f"{indice}_{plano}"


def _escribir_marcado(origen: Path, destino: Path) -> None:
    """Copia `origen` en `destino` precedido por `MARCA`, por trozos.

    Por trozos y no con `read_bytes()`: la entrada puede pesar hasta
    `tamano_max_bytes`, y no hay ninguna razón para sostenerla entera en
    memoria del hijo cuando el presupuesto de RAM del ítem #7 existe
    justamente para eso.
    """
    with destino.open("wb") as salida:
        salida.write(MARCA)
        with origen.open("rb") as entrada:
            while trozo := entrada.read(_TROZO):
                salida.write(trozo)


class Passthrough(Procesador):
    """Una salida marcada por cada entrada. Sin ramas por cardinalidad.

    `clave` se recibe por constructor porque la misma clase se registra dos
    veces (`passthrough` y `passthrough_multi`): el valor DEBE coincidir con
    la llave bajo la que se registra la instancia, y `app/core/interfaz.py`
    advierte que ni mypy ni `ABCMeta` lo exigen. La prueba de consistencia de
    `tests/test_procesador_passthrough.py` es el único guardián de eso.
    """

    def __init__(self, clave: str) -> None:
        self.clave = clave

    def validar(self, archivos: list[ArchivoEntrada]) -> ErrorTipificado | None:
        """Siempre `None`: este procesador no tiene reglas de contenido.

        No es un stub pendiente. Cantidad, formato y tamaño ya los aplicó el
        borde contra la fila de `_TABLA_CONTRATOS` (ítem #7) antes de que el
        hijo existiera, y el passthrough por definición no mira lo que hay
        adentro del archivo. Inventar un rechazo acá sería inventar una regla
        de negocio en el procesador que existe para no tener ninguna.
        """
        return None

    def procesar(self, archivos: list[ArchivoEntrada]) -> list[ArchivoSalida]:
        """Una `ArchivoSalida` marcada por cada entrada, en el mismo orden.

        Un único camino: la cantidad de salidas es la cantidad de entradas, y
        la decisión de si eso viaja como archivo suelto o como ZIP es de
        `app.core.empaquetado`, no de acá (ADR 0006).

        El nombre en disco (`passthrough_0`, `passthrough_1`, ...) lo genera
        este módulo y nunca deriva del nombre del cliente, igual que
        `app/recepcion.py` genera `entrada_0`: `nombre_propuesto` es sólo la
        etiqueta que viajará en el `Content-Disposition` o como `arcname`.
        """
        directorio = archivos[0].ruta_temporal.parent
        salidas: list[ArchivoSalida] = []
        for indice, entrada in enumerate(archivos):
            ruta = directorio / f"passthrough_{indice}"
            _escribir_marcado(entrada.ruta_temporal, ruta)
            salidas.append(
                ArchivoSalida(
                    nombre_propuesto=_nombre_de_salida(indice, entrada.nombre_original),
                    ruta_temporal=ruta,
                    tipo_mime=MIME_DE_SALIDA,
                )
            )
        return salidas
