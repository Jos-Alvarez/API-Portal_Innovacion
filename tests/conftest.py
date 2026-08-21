"""Shared pytest fixtures.

NOTE on import ordering: ``app.core.configuracion`` does not exist until
Phase 2 of this change. The ``limpiar_cache_configuracion`` fixture below
imports it **inside the fixture body**, not at module scope, precisely so
that Phase 1's test collection (``tests/test_arranque_spawn.py``) does not
break on a module that has not been created yet.

``limpiar_cache_configuracion`` also clears ``obtener_semaforo``'s
``lru_cache`` (item #8, S2): the semaphore is sized from
``ejecuciones_max`` at construction time, so a stale cached instance from an
earlier test would silently keep the previous test's concurrency ceiling.
Same import-inside-fixture-body reasoning applies to ``app.core.ejecucion``.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator

import pytest

TOKEN_SENTINELA = "sentinela-token-de-pruebas-3f9c2a"


def pytest_sessionstart(session: pytest.Session) -> None:
    """Abortar si la suite corre fuera de un entorno virtual.

    En esta máquina el intérprete del sistema tiene instalado su propio
    stack de FastAPI, varias versiones por detrás del que el proyecto fija
    en ``uv.lock``. Correr contra él no falla: contesta, y contesta mal.
    Una suite verde contra la librería equivocada es peor que una roja.

    No se compara contra una ruta fija de ``.venv`` a propósito, para que un
    runner de CI con otra ubicación de entorno siga siendo válido. Lo único
    que se exige es no estar en el intérprete base.
    """
    if sys.prefix == sys.base_prefix:
        raise pytest.UsageError(
            "La suite se está ejecutando con el intérprete del sistema "
            f"({sys.executable}), no con el entorno del proyecto. Las "
            "versiones de FastAPI y Starlette no coinciden con uv.lock, así "
            "que los resultados no son válidos. Usá 'uv run pytest'."
        )


@pytest.fixture
def token_sentinela(monkeypatch: pytest.MonkeyPatch) -> str:
    """Fija TOKEN_SERVICIO a un valor sentinela conocido para la prueba."""
    monkeypatch.setenv("TOKEN_SERVICIO", TOKEN_SENTINELA)
    return TOKEN_SENTINELA


@pytest.fixture
def limpiar_cache_configuracion() -> Iterator[None]:
    """Limpia los caches de configuración y del semáforo de admisión.

    Ambos son ``@lru_cache(maxsize=1)`` derivados del entorno de proceso: un
    valor cacheado de una prueba anterior (``EJECUCIONES_MAX`` incluido)
    filtraría hacia la siguiente si no se limpiara acá, en el mismo lugar
    donde ya se limpiaba ``obtener_configuracion``.
    """
    from app.core.admision import obtener_semaforo
    from app.core.configuracion import obtener_configuracion

    obtener_configuracion.cache_clear()
    obtener_semaforo.cache_clear()
    yield
    obtener_configuracion.cache_clear()
    obtener_semaforo.cache_clear()
