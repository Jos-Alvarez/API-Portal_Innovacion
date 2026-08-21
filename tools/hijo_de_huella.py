"""Proceso de medición de memoria (ítem #17). Se ejecuta como módulo.

    uv run python -m tools.hijo_de_huella <archivo.xlsx> [clave]

Imprime un JSON con tres lecturas de RSS y el tiempo del trabajo real.

**Por qué es un proceso aparte lanzado con `subprocess` y no un objetivo de
`multiprocessing`.** El primer intento usaba `Process(target=...)` y midió
que el árbol de módulos costaba 0.0 MB, que es imposible. La causa: `spawn`
reimporta en el hijo **el módulo `__main__` del padre**, y el padre era
`tools/medicion.py`, que a nivel de módulo importa openpyxl, FastAPI y el
árbol entero de `app`. Para cuando la primera lectura de RSS ocurría, todo lo
que se quería medir ya estaba cargado.

Como módulo propio, `__main__` es este archivo, cuyos imports de nivel de
módulo son sólo biblioteca estándar. El árbol de la aplicación se importa
**adentro** de `medir`, entre dos lecturas, y el número sale limpio.

**Lo que este proceso NO reproduce exactamente**: el hijo de producción,
además del árbol de `app`, reimporta el `__main__` del servidor (el runner de
uvicorn). Esa parte no está acá. Lo que se mide es la huella atribuible a
**este** servicio, que es la que se necesita para calibrar `EJECUCIONES_MAX`.

**Tampoco usa `app.core.ejecucion.ejecutar_aislado`, y eso es correcto.** Esa
función acepta exactamente tres formas de mensaje (`SalidaDelHijo`,
`ErrorDelHijo`, `ExcepcionDelHijo`) y trata cualquier otra cosa como
violación de protocolo. Es una frontera cerrada a propósito (ADR 0012) y no
se ensancha para acomodar una herramienta de desarrollo.
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


def medir(contenido: bytes, clave: str) -> dict[str, Any]:
    """Mide RSS en tres momentos y devuelve el informe.

    Los tres momentos se calibran distinto y por eso se informan por separado:

    - **base**: intérprete recién arrancado más `psutil`. Es el piso de
      cualquier proceso, no atribuible a este servicio.
    - **tras importar**: lo que cuesta el árbol de módulos que ADR 0012 obliga
      a reimportar en cada petición. Lo paga toda ejecución por existir,
      procese un registro o cinco mil.
    - **pico**: después de procesar. Lo que sube por encima del anterior es lo
      único que escala con el tamaño de la entrada.
    """
    import psutil

    proceso = psutil.Process()
    base = proceso.memory_info().rss

    # Import adentro de la función, deliberado: ver la docstring del módulo.
    # Es el mismo árbol que reimporta el hijo de producción, que llega acá por
    # `app.core.ejecucion` -> `app.registry`.
    from app.core.tipos import ArchivoEntrada
    from app.registry import REGISTRY

    tras_importar = proceso.memory_info().rss

    with tempfile.TemporaryDirectory() as temporal:
        ruta = Path(temporal) / "entrada_0"  # sin extensión, como app/recepcion.py
        ruta.write_bytes(contenido)
        entrada = ArchivoEntrada(
            nombre_original="contado.xlsx",
            ruta_temporal=ruta,
            tamano_comprimido=len(contenido),
            formato="xlsx",
        )
        inicio = time.perf_counter()
        salidas = REGISTRY[clave].procesar([entrada])
        duracion_ms = (time.perf_counter() - inicio) * 1000
        pico = proceso.memory_info().rss

    return {
        "base": base,
        "tras_importar": tras_importar,
        "pico": pico,
        "trabajo_ms": duracion_ms,
        "salidas": len(salidas),
    }


if __name__ == "__main__":
    archivo = Path(sys.argv[1])
    clave_procesador = sys.argv[2] if len(sys.argv) > 2 else "contado_carga"
    print(json.dumps(medir(archivo.read_bytes(), clave_procesador)))
