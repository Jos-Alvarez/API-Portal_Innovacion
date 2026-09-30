"""Contrato de errores tipificados (ADR 0014, ítem #3 del backlog).

Objetivo de diseño (design.md §1): los cinco tipos son un conjunto cerrado
en el sistema de tipos, no una convención. Añadir un sexto tipo exige cuatro
ediciones coordinadas y visibles en el diff: un miembro del enum, un
`TypedDict`, una subclase y una entrada en el mapa de estados.

Lo que ADR 0014 cierra es el **conjunto de miembros del enum**, no las formas
de contexto: el ítem #7 añade `ContextoTamanoTotal` a la unión sin tocar
`TipoError`, y ADR 0021 registra por qué eso no reabre 0014.

El manejador se cablea en `crear_app()` vía `registrar_manejador_errores`; el
router de pruebas de `tests/test_errores_tipificados.py` ejercita cada caso
(design.md §6).

**Este módulo importa ÚNICAMENTE biblioteca estándar.** El ítem #17 sacó el
mapa de códigos HTTP y su manejador a `app/core/errores_http.py`: el hijo de
`spawn` alcanza este vocabulario en cada petición (ADR 0012) y no tiene por
qué pagar el import de FastAPI para hacerlo. No importa nada de
`app/procesadores/` (invariante de ADR 0011).
"""

from __future__ import annotations

from enum import StrEnum
from typing import ClassVar, Literal, TypedDict


class TipoError(StrEnum):
    """Vocabulario cerrado de ADR 0014: exactamente cinco valores."""

    FORMATO = "formato"
    TAMANO = "tamano"
    CONTENIDO = "contenido"
    CANTIDAD = "cantidad"
    CLAVE_INEXISTENTE = "clave_inexistente"


class ContextoFormato(TypedDict):
    archivo: str
    formato_recibido: str
    formatos_aceptados: list[str]


class ContextoTamano(TypedDict):
    # Forma fijada verbatim por ADR 0014.
    archivo: str
    limite_bytes: int
    recibido_bytes: int


class ContextoTamanoTotal(TypedDict):
    """Violación del límite total del lote: ningún archivo es el culpable.

    Hermano de `ContextoTamano`, no una ampliación suya (ADR 0021). ADR 0014
    cierra el conjunto de miembros del enum, no las formas de contexto: este
    `TypedDict` entra en la unión `Contexto` y `ContextoTamano` queda intacto
    para el caso de un solo archivo.
    """

    archivos: list[str]
    limite_bytes: int
    recibido_bytes: int


MotivoContenido = Literal[
    "columna_faltante",
    "cero_filas",
    "hoja_faltante",
    "tipo_no_reconocido",
    "tipo_duplicado",
]
"""Motivos cerrados de `ContextoContenido`.

Los tres últimos los agregó la migración de `AsientosContables_Carga`: es el
primer procesador que lee un libro de varias hojas y recibe varios archivos
por ejecución. La FORMA del contexto no cambió: `hoja_faltante` reutiliza
`columna` para nombrar la hoja ausente, y `tipo_no_reconocido` /
`tipo_duplicado` la dejan en `None`.
"""


class ContextoContenido(TypedDict):
    """`columna` lleva la columna faltante con `columna_faltante`, la HOJA
    faltante con `hoja_faltante`, y `None` con cualquier otro motivo."""

    archivo: str
    motivo: MotivoContenido
    columna: str | None


class ContextoSinSalidas(TypedDict):
    """Cero salidas del módulo: sin archivo culpable (ADR 0023).

    Hermano de `ContextoContenido`, no una ampliación suya, mismo patrón que
    `ContextoTamanoTotal` frente a `ContextoTamano` (ADR 0021). El empaquetado
    sostiene una lista vacía de `ArchivoSalida` en el punto de falla y no
    tiene ningún nombre de archivo en alcance.
    """

    motivo: Literal["sin_salidas"]


class ContextoCantidad(TypedDict):
    minimo: int
    maximo: int
    recibido: int


# TECH-DESIGN.md:268
CausaFila = Literal["fila_ausente", "fila_inactiva"]
# H-05, REVISION-ADVERSARIAL.md
CausaDesincronizacion = Literal["no_en_registry", "no_en_bd"]


class ContextoClaveInexistente(TypedDict):
    clave_procesador: str
    causa: CausaFila | CausaDesincronizacion


Contexto = (
    ContextoFormato
    | ContextoTamano
    | ContextoTamanoTotal
    | ContextoContenido
    | ContextoSinSalidas
    | ContextoCantidad
    | ContextoClaveInexistente
)


def _reconstruir(cls: type[ErrorTipificado]) -> ErrorTipificado:
    """Reconstructor de nivel de módulo para `ErrorTipificado.__reduce__`.

    Cada `__init__` de las subclases es solo-por-palabra-clave, así que
    `pickle` no puede volver a invocarlo con la tupla vacía que produce el
    `__reduce__` heredado de `Exception` (ítem #8, design.md §5, V6). Este
    reconstructor evita `__init__` por completo con `cls.__new__(cls)`;
    `pickle` restaura el resto del estado escribiendo `__dict__` encima.
    Debe vivir a nivel de módulo -- no como método ni función anidada --
    porque `pickle` lo referencia por nombre calificado.
    """
    return cls.__new__(cls)


class ErrorTipificado(Exception):
    """Base de los cinco tipos del ADR 0014. Un solo manejador la cubre (V2)."""

    tipo: ClassVar[TipoError]
    contexto: Contexto

    def __reduce__(self) -> tuple[object, ...]:
        """Garantiza que todo `ErrorTipificado` sobreviva a un `pickle` round-trip.

        Necesario porque el `Pipe` entre el proceso padre y el hijo dedicado
        (ítem #8) usa pickling para transportar el resultado, y un error
        tipificado levantado por el módulo debe cruzar esa frontera intacto.
        Sin este método, `self.args == ()` (cada subclase llama a
        `super().__init__()` sin argumentos) y `pickle.loads` intenta
        reconstruir con `cls()`, que falla porque `__init__` exige
        argumentos solo-por-palabra-clave.
        """
        return (_reconstruir, (type(self),), dict(self.__dict__))


class ErrorFormato(ErrorTipificado):
    tipo = TipoError.FORMATO
    contexto: ContextoFormato

    def __init__(
        self, *, archivo: str, formato_recibido: str, formatos_aceptados: list[str]
    ) -> None:
        super().__init__()
        self.contexto = ContextoFormato(
            archivo=archivo,
            formato_recibido=formato_recibido,
            formatos_aceptados=formatos_aceptados,
        )


class ErrorTamano(ErrorTipificado):
    """Un solo tipo (`TipoError.TAMANO`) con dos formas de contexto (ADR 0021).

    `__init__` conserva sin cambios la forma que ADR 0014 fija verbatim para el
    caso de un solo archivo. `total()` construye la variante de lote, siguiendo
    el patrón ya embarcado de `ErrorContenido.columna_faltante`.
    """

    tipo = TipoError.TAMANO
    contexto: ContextoTamano | ContextoTamanoTotal

    def __init__(self, *, archivo: str, limite_bytes: int, recibido_bytes: int) -> None:
        super().__init__()
        self.contexto = ContextoTamano(
            archivo=archivo, limite_bytes=limite_bytes, recibido_bytes=recibido_bytes
        )

    @classmethod
    def total(cls, *, archivos: list[str], limite_bytes: int, recibido_bytes: int) -> ErrorTamano:
        """Violación del límite total del lote, sin un `archivo` culpable.

        El `archivo=""` que construye `__init__` se sobrescribe de inmediato: es
        una línea de descarte deliberada, elegida sobre un `__init__` que se
        ramifique según cuál de dos argumentos mutuamente excluyentes recibió.
        Ningún estado inválido escapa de este método.
        """
        error = cls(archivo="", limite_bytes=limite_bytes, recibido_bytes=recibido_bytes)
        error.contexto = ContextoTamanoTotal(
            archivos=archivos, limite_bytes=limite_bytes, recibido_bytes=recibido_bytes
        )
        return error


class ErrorContenido(ErrorTipificado):
    """Un solo tipo (`TipoError.CONTENIDO`) con dos formas de contexto (ADR 0023).

    `__init__` conserva sin cambios la forma que ADR 0014 fija para el caso
    con archivo culpable. `sin_salidas()` construye la forma hermana sin
    argumentos, siguiendo el patrón ya embarcado de `ErrorTamano.total()`.
    """

    tipo = TipoError.CONTENIDO
    contexto: ContextoContenido | ContextoSinSalidas

    def __init__(
        self,
        *,
        archivo: str,
        motivo: MotivoContenido,
        columna: str | None,
    ) -> None:
        super().__init__()
        self.contexto = ContextoContenido(archivo=archivo, motivo=motivo, columna=columna)

    @classmethod
    def columna_faltante(cls, *, archivo: str, columna: str) -> ErrorContenido:
        return cls(archivo=archivo, motivo="columna_faltante", columna=columna)

    @classmethod
    def cero_filas(cls, *, archivo: str) -> ErrorContenido:
        return cls(archivo=archivo, motivo="cero_filas", columna=None)

    @classmethod
    def hoja_faltante(cls, *, archivo: str, hoja: str) -> ErrorContenido:
        """Falta una hoja obligatoria. Su nombre viaja en `columna` (ver `MotivoContenido`)."""
        return cls(archivo=archivo, motivo="hoja_faltante", columna=hoja)

    @classmethod
    def tipo_no_reconocido(cls, *, archivo: str) -> ErrorContenido:
        """El procesador no pudo decidir qué clase de archivo es éste."""
        return cls(archivo=archivo, motivo="tipo_no_reconocido", columna=None)

    @classmethod
    def tipo_duplicado(cls, *, archivo: str) -> ErrorContenido:
        """Otro archivo de la misma ejecución ya resolvió al mismo tipo."""
        return cls(archivo=archivo, motivo="tipo_duplicado", columna=None)

    @classmethod
    def sin_salidas(cls) -> ErrorContenido:
        """Cero salidas del módulo de empaquetado: sin `archivo` que reportar."""
        error = cls.__new__(cls)
        Exception.__init__(error)
        error.contexto = ContextoSinSalidas(motivo="sin_salidas")
        return error


class ErrorCantidad(ErrorTipificado):
    tipo = TipoError.CANTIDAD
    contexto: ContextoCantidad

    def __init__(self, *, minimo: int, maximo: int, recibido: int) -> None:
        super().__init__()
        self.contexto = ContextoCantidad(minimo=minimo, maximo=maximo, recibido=recibido)


class ErrorClaveInexistente(ErrorTipificado):
    tipo = TipoError.CLAVE_INEXISTENTE
    contexto: ContextoClaveInexistente

    def __init__(self, *, clave_procesador: str, causa: CausaFila | CausaDesincronizacion) -> None:
        super().__init__()
        self.contexto = ContextoClaveInexistente(clave_procesador=clave_procesador, causa=causa)
