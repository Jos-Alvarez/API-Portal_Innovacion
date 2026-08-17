"""Shared pytest fixtures.

NOTE on import ordering: ``app.core.configuracion`` does not exist until
Phase 2 of this change. The ``limpiar_cache_configuracion`` fixture below
imports it **inside the fixture body**, not at module scope, precisely so
that Phase 1's test collection (``tests/test_arranque_spawn.py``) does not
break on a module that has not been created yet.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

TOKEN_SENTINELA = "sentinela-token-de-pruebas-3f9c2a"


@pytest.fixture
def token_sentinela(monkeypatch: pytest.MonkeyPatch) -> str:
    """Fija TOKEN_SERVICIO a un valor sentinela conocido para la prueba."""
    monkeypatch.setenv("TOKEN_SERVICIO", TOKEN_SENTINELA)
    return TOKEN_SENTINELA


@pytest.fixture
def limpiar_cache_configuracion() -> Iterator[None]:
    """Limpia el cache de obtener_configuracion() antes y después del test."""
    from app.core.configuracion import obtener_configuracion

    obtener_configuracion.cache_clear()
    yield
    obtener_configuracion.cache_clear()
