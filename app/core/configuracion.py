"""Configuración de arranque cerrada por defecto (D4 del diseño).

Única responsabilidad de este módulo en este cambio: `TOKEN_SERVICIO`. Los
demás parámetros operativos (`EJECUCIONES_MAX`, `TIMEOUT_EJECUCION`, etc.)
pertenecen al ítem #8 del backlog y no se introducen acá.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from pydantic import Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfiguracionInvalida(RuntimeError):
    """La configuración de arranque no pudo construirse. Nunca lleva el valor."""


class Configuracion(BaseSettings):
    """Configuración de arranque, resuelta desde variables de entorno.

    Sin archivo `.env`: la fuente es exclusivamente el entorno del proceso,
    para mantenerse neutral entre plataformas de despliegue.
    """

    model_config = SettingsConfigDict(extra="forbid", frozen=True)

    # `min_length=1` y NADA MÁS. Este campo NO debe ganar validación con
    # forma de valor (regex, un piso de longitud más alto, un formato
    # esperado, etc.) sin agregar antes una capa de saneo previa a
    # cualquier mensaje de error. La razón: los únicos valores que este
    # campo puede rechazar hoy son "ausente" o "vacío" -- nunca un valor
    # parecido al token real -- así que el vector de fuga de pydantic
    # (`str(ValidationError)` incluye `input_value=...` para el valor
    # rechazado) queda cerrado por construcción. Agregar una regex, por
    # ejemplo, haría que un token casi-correcto pero inválido aparezca
    # completo en un traceback. Ver design.md D4, riesgo #1.
    token_servicio: Annotated[SecretStr, Field(min_length=1)]


@lru_cache(maxsize=1)
def obtener_configuracion() -> Configuracion:
    """Construye (una sola vez, perezosamente) la configuración de arranque.

    Falla cerrado: token ausente o vacío -> `ConfiguracionInvalida`, sin
    continuar. Único punto de llamada que atrapa el `ValidationError` de
    pydantic-settings; el mensaje se arma solo con `loc`/`type`, nunca con
    `input`, y se relanza con `from None` para no encadenar el traceback
    original (que sí podría incluir el valor rechazado).
    """
    try:
        return Configuracion()  # type: ignore[call-arg]  # los valores vienen del entorno
    except ValidationError as exc:
        errores = exc.errors(include_url=False, include_input=False)
        detalle = "; ".join(f"{e['loc']}: {e['type']}" for e in errores)
        raise ConfiguracionInvalida(f"Configuración de arranque inválida: {detalle}") from None
