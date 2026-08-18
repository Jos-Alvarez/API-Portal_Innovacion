"""Contrato de errores tipificados (ADR 0014, ítem #3 del backlog).

Objetivo de diseño (design.md §1): los cinco tipos son un conjunto cerrado
en el sistema de tipos, no una convención. Añadir un sexto tipo exige cuatro
ediciones coordinadas y visibles en el diff: un miembro del enum, un
`TypedDict`, una subclase y una entrada en el mapa de estados.

Nada de este módulo se cablea en `crear_app()`; lo consume el router de
pruebas de `tests/test_errores_tipificados.py` (design.md §6).

Este módulo importa únicamente la biblioteca estándar más `fastapi`/
`starlette`; no importa nada de `app/procesadores/` (invariante de ADR 0011).
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import ClassVar, Final, Literal, TypedDict

from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


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


class ContextoContenido(TypedDict):
    archivo: str
    motivo: Literal["columna_faltante", "cero_filas"]
    columna: str | None


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
    | ContextoContenido
    | ContextoCantidad
    | ContextoClaveInexistente
)


class ErrorTipificado(Exception):
    """Base de los cinco tipos del ADR 0014. Un solo manejador la cubre (V2)."""

    tipo: ClassVar[TipoError]
    contexto: Contexto


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
    tipo = TipoError.TAMANO
    contexto: ContextoTamano

    def __init__(self, *, archivo: str, limite_bytes: int, recibido_bytes: int) -> None:
        super().__init__()
        self.contexto = ContextoTamano(
            archivo=archivo, limite_bytes=limite_bytes, recibido_bytes=recibido_bytes
        )


class ErrorContenido(ErrorTipificado):
    tipo = TipoError.CONTENIDO
    contexto: ContextoContenido

    def __init__(
        self,
        *,
        archivo: str,
        motivo: Literal["columna_faltante", "cero_filas"],
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


_ESTADO_HTTP: Final[Mapping[TipoError, int]] = MappingProxyType(
    {
        TipoError.FORMATO: 422,
        TipoError.TAMANO: 422,
        TipoError.CONTENIDO: 422,
        TipoError.CANTIDAD: 422,
        TipoError.CLAVE_INEXISTENTE: 500,  # ADR 0018
    }
)


def responder_error_tipificado(request: Request, exc: Exception) -> Response:
    if not isinstance(exc, ErrorTipificado):  # V4: la firma debe ser `Exception`
        raise exc
    return JSONResponse(
        status_code=_ESTADO_HTTP[exc.tipo],
        content={"tipo": exc.tipo.value, "contexto": exc.contexto},
    )


def registrar_manejador_errores(app: FastAPI) -> None:
    app.add_exception_handler(ErrorTipificado, responder_error_tipificado)  # V2, V3
