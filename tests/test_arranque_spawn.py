"""Pruebas del ordenamiento de fijación de spawn (D1/D2 del diseño).

Las tres pruebas corren en un intérprete fresco vía subprocess: el proceso
de pytest ya tiene su propio estado de multiprocessing contaminado y
produciría un falso positivo.
"""

from __future__ import annotations

from tests.ayudas.subproceso import ejecutar_snippet

_IMPORTAR_APP_FIJA_SPAWN = """
import multiprocessing as mp
import app
print(mp.get_start_method(allow_none=True))
"""


def test_importar_app_fija_spawn() -> None:
    resultado = ejecutar_snippet(_IMPORTAR_APP_FIJA_SPAWN)
    assert resultado.codigo_salida == 0, resultado.salida
    assert resultado.salida.strip().splitlines()[-1] == "spawn"


_NINGUNA_CREACION_PREVIA_AL_SPAWN = """
import sys
import multiprocessing as mp

eventos = []

def _hook(nombre, args):
    if nombre in (
        "os.fork",
        "os.posix_spawn",
        "os.exec",
        "subprocess.Popen",
        "socket.connect",
        "socket.__new__",
    ):
        eventos.append((nombre, mp.get_start_method(allow_none=True)))

sys.addaudithook(_hook)

import app  # noqa: F401 - el import es el efecto bajo prueba

violaciones = [(n, m) for (n, m) in eventos if m != "spawn"]
if violaciones:
    print("VIOLACIONES:", violaciones)
    sys.exit(1)
print("OK", len(eventos))
"""


def test_ninguna_creacion_previa_al_spawn() -> None:
    resultado = ejecutar_snippet(_NINGUNA_CREACION_PREVIA_AL_SPAWN)
    assert resultado.codigo_salida == 0, resultado.salida
    assert "OK" in resultado.salida


_REIMPORTACION_ES_IDEMPOTENTE = """
import app  # noqa: F401
from app.arranque import fijar_metodo_arranque

resultado = fijar_metodo_arranque()
print("SEGUNDA_LLAMADA", resultado)
"""


def test_reimportacion_es_idempotente() -> None:
    resultado = ejecutar_snippet(_REIMPORTACION_ES_IDEMPOTENTE)
    assert resultado.codigo_salida == 0, resultado.salida
    assert "SEGUNDA_LLAMADA False" in resultado.salida
