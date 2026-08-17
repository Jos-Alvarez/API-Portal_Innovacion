"""Convención de pereza (D3 del diseño): nada se construye a nivel de módulo.

Corre en intérprete fresco: el cache de `obtener_configuracion` en el
proceso de pytest ya pudo haberse llenado por otros tests.
"""

from __future__ import annotations

from tests.ayudas.subproceso import ejecutar_snippet

_SNIPPET_CACHE_VACIO_TRAS_IMPORTAR = """
import app.main  # noqa: F401 - el import en sí es lo que se prueba
from app.core.configuracion import obtener_configuracion

assert obtener_configuracion.cache_info().currsize == 0, (
    "obtener_configuracion se construyo a nivel de import, rompe la pereza"
)
print("OK")
"""


def test_cache_configuracion_vacio_tras_importar_app_main() -> None:
    resultado = ejecutar_snippet(_SNIPPET_CACHE_VACIO_TRAS_IMPORTAR)
    assert resultado.codigo_salida == 0, resultado.salida
    assert "OK" in resultado.salida
