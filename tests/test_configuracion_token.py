"""Pruebas de arranque cerrado por falta de TOKEN_SERVICIO (D4 del diseño)."""

from __future__ import annotations

import logging

import pytest
from pydantic import SecretStr

from app.core.configuracion import ConfiguracionInvalida, obtener_configuracion

pytestmark = pytest.mark.usefixtures("limpiar_cache_configuracion")


def test_token_ausente_falla(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TOKEN_SERVICIO", raising=False)
    with pytest.raises(ConfiguracionInvalida):
        obtener_configuracion()


def test_token_vacio_falla(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TOKEN_SERVICIO", "")
    with pytest.raises(ConfiguracionInvalida):
        obtener_configuracion()


def test_token_valido_se_acepta(token_sentinela: str) -> None:
    configuracion = obtener_configuracion()
    assert configuracion.token_servicio.get_secret_value() == token_sentinela


def test_configuracion_es_frozen(token_sentinela: str) -> None:
    configuracion = obtener_configuracion()
    with pytest.raises(Exception):  # noqa: B017 - pydantic ValidationError en frozen
        configuracion.token_servicio = SecretStr("otro")


def test_configuracion_prohibe_campos_extra() -> None:
    # pydantic-settings solo lee del entorno los nombres que coinciden con
    # campos declarados, así que una variable de entorno desconocida no
    # llega a activar `extra="forbid"`. Se prueba por construcción directa,
    # que es como ítem #2 y el resto del código interactuarán con el
    # modelo.
    from app.core.configuracion import Configuracion

    with pytest.raises(Exception):  # noqa: B017 - ValidationError de pydantic
        Configuracion(
            token_servicio=SecretStr("algo-valido"),
            campo_inexistente="x",  # type: ignore[call-arg]  # el campo extra es lo que se prueba
        )


def test_token_no_deja_rastro_en_caplog_al_fallar_por_otra_via(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from app.core.configuracion import Configuracion

    sentinela = "sentinela-caplog-9a41ff"
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(Exception):  # noqa: B017 - ValidationError de pydantic
            Configuracion(
                token_servicio=SecretStr(sentinela),
                campo_que_no_existe_para_forzar_fallo="x",  # type: ignore[call-arg]  # es lo que se prueba
            )
    mensajes = "".join(record.getMessage() for record in caplog.records)
    assert sentinela not in mensajes


_SENTINELA_TOKEN = "sentinela-unico-de-token-b71ac0e2d4"

# El token en sí es válido (el sentinel bajo prueba). El fallo se fuerza por
# otra vía -- un campo extra prohibido por `extra="forbid"` -- para probar
# que un `ValidationError` que involucra al modelo, y que en principio no
# tiene nada que ver con el valor del token, tampoco lo deja escapar vía el
# `input_value=...` que pydantic incluye por defecto en su `repr`.
_SNIPPET_SENTINELA_AUSENTE_EN_SALIDA = f"""
import app  # noqa: F401 - fija spawn primero, como en producción
from app.core.configuracion import Configuracion

Configuracion(
    token_servicio={_SENTINELA_TOKEN!r},
    campo_que_no_existe_para_forzar_fallo="x",
)
"""


def test_sentinela_ausente_de_salida_combinada() -> None:
    from tests.ayudas.subproceso import ejecutar_snippet

    resultado = ejecutar_snippet(_SNIPPET_SENTINELA_AUSENTE_EN_SALIDA)
    assert resultado.codigo_salida != 0
    assert _SENTINELA_TOKEN not in resultado.salida
