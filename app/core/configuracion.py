"""Configuración de arranque cerrada por defecto (D4 del diseño).

`TOKEN_SERVICIO` (ítem #3) y, desde este cambio (ítem #8, BACKLOG),
`EJECUCIONES_MAX` y `TIMEOUT_EJECUCION`: la ventana de concurrencia acotada y
el plazo del proceso hijo dedicado. Ambos campos van **con valor por
defecto**, deliberadamente (design.md §4, corrige la propuesta original que
los pedía obligatorios): son placeholders conservadores hasta que el ítem
#17 los calibre con datos, nunca valores medidos.
"""

from __future__ import annotations

from datetime import timedelta
from functools import lru_cache
from typing import Annotated, Final

from pydantic import BeforeValidator, Field, SecretStr, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# El plazo de vida de una petición del portal (TECH-DESIGN.md:259), no una
# preferencia de este módulo. `TIMEOUT_EJECUCION` debe quedar estrictamente
# por debajo de este valor para dejar margen a la subida, el empaquetado y
# la transferencia (design.md §4).
CORTE_DEL_PORTAL: Final[timedelta] = timedelta(minutes=2)


def _segundos_o_iso8601(valor: object) -> object:
    """Acepta `TIMEOUT_EJECUCION` como segundos simples (`"60"`) o ISO 8601 (`"PT60S"`).

    Corrige, en código, una premisa falsa de design.md §4 ("pydantic parsea
    TIMEOUT_EJECUCION=60 como 60 segundos"): el parser de `timedelta` de
    pydantic instalado (verificado contra el entorno del proyecto) exige ISO
    8601 para una entrada de tipo `str`; una cadena numérica simple levanta
    `time_delta_parsing`. `TIMEOUT_EJECUCION=60` es la forma documentada y
    ergonómica para un operador, así que este `BeforeValidator` la admite sin
    reabrir el resto del parser: solo convierte una entrada numérica (`str`,
    `int` o `float`) a segundos; cualquier otro valor -- incluida una cadena
    ISO 8601 -- pasa intacto al validador estándar de pydantic.
    """
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, int | float):
        return timedelta(seconds=valor)
    if isinstance(valor, str):
        try:
            return timedelta(seconds=float(valor))
        except ValueError:
            return valor
    return valor


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

    # Techo de ejecuciones concurrentes (el semáforo del ítem #8). `le=32`
    # es la única cota que importa hoy: por encima, el limitador de hilos
    # de anyio (40 por defecto) pasaría a ser el número real de
    # concurrencia, no `EJECUCIONES_MAX` (design.md §4). `2` es un piso
    # conservador -- un worker de API con dos hijos, cada uno hasta el
    # presupuesto de 256 MB de ADR 0021 -- no una medición (ítem #17).
    ejecuciones_max: Annotated[int, Field(ge=1, le=32)] = 2

    # Plazo máximo del proceso hijo dedicado. `60s` es un placeholder
    # conservador: el objetivo p95 es 15s (TECH-DESIGN.md:320), así que 60s
    # deja 4x de margen sin exceder `CORTE_DEL_PORTAL` (ítem #17 calibra el
    # valor real). `gt=timedelta()` cierra el piso; el techo lo cierra el
    # validador de abajo contra `CORTE_DEL_PORTAL`.
    timeout_ejecucion: Annotated[
        timedelta, BeforeValidator(_segundos_o_iso8601), Field(gt=timedelta())
    ] = timedelta(seconds=60)

    @model_validator(mode="after")
    def _timeout_por_debajo_del_corte(self) -> Configuracion:
        """`TIMEOUT_EJECUCION` debe quedar estrictamente bajo el corte del portal.

        El mensaje se arma solo con `loc`/`type` en `obtener_configuracion`
        (nunca con el valor), así que este validador solo necesita levantar
        `ValueError` -- no arma el mensaje final él mismo.
        """
        if self.timeout_ejecucion >= CORTE_DEL_PORTAL:
            raise ValueError(
                "timeout_ejecucion debe ser estrictamente menor que el corte "
                "del portal de 2 minutos"
            )
        return self


@lru_cache(maxsize=1)
def obtener_configuracion() -> Configuracion:
    """Construye (una sola vez, perezosamente) la configuración de arranque.

    Falla cerrado: token ausente o vacío -> `ConfiguracionInvalida`, sin
    continuar. Único punto de llamada que atrapa el `ValidationError` de
    pydantic-settings; el mensaje se arma con `loc`/`type`/`msg`, nunca con
    `input`, y se relanza con `from None` para no encadenar el traceback
    original (que sí podría incluir el valor rechazado). `msg` es texto que
    este módulo escribe (los validadores de campo built-in de pydantic
    tampoco lo pueblan con el valor recibido, solo `input` lo hace) -- es lo
    que permite que un mensaje como el del validador de
    `timeout_ejecucion` nombre la relación violada sin filtrar el valor.
    """
    try:
        return Configuracion()  # type: ignore[call-arg]  # los valores vienen del entorno
    except ValidationError as exc:
        errores = exc.errors(include_url=False, include_input=False)
        detalle = "; ".join(f"{e['loc']}: {e['type']} ({e['msg']})" for e in errores)
        raise ConfiguracionInvalida(f"Configuración de arranque inválida: {detalle}") from None
