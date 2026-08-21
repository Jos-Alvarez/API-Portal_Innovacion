"""Guardián del techo de latencia del PRD (ítem #17).

**Lo que esta prueba es y lo que a propósito no es.** El PRD fija que el p95
de `Contado_Carga` no supera los 15 segundos de punta a punta. Esa es la
afirmación que se defiende acá, y nada más: no se afirma ningún número
medido. Los números viven en `MEDICIONES.md` y se reproducen con
`uv run python -m tools.medicion`, que es una herramienta y no una prueba.

La diferencia importa. Una prueba que afirmara "el p95 es de 1,9 s" sería una
prueba intermitente esperando su turno: mide una máquina compartida, bajo
carga variable, con otras suites corriendo al lado. Se pondría roja por
motivos que no son una regresión y alguien terminaría subiéndole el umbral
hasta volverla inútil, que es la peor forma de morir de una prueba.

Lo que sí atrapa este guardián es una regresión de **orden de magnitud**: que
alguien vuelva a meter pandas en la cadena de importación del hijo, que el
procesamiento pase a ser cuadrático en la cantidad de filas, o que el
empaquetado empiece a leer el archivo entero en memoria varias veces. Contra
los ~1,9 s medidos hay un 8x de margen; hace falta romper algo de verdad para
gastarlo.
"""

from __future__ import annotations

import io
import time
from datetime import datetime

from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.procesadores.contado_carga.modulo import COLUMNAS
from tests.ayudas.subproceso import ejecutar_snippet

TECHO_DEL_PRD_S = 15.0
_REGISTROS = 1000
_PLAZA = "PROSEGUR - P5 - El Pino"


def _libro(registros: int) -> bytes:
    libro = Workbook()
    hoja = libro.active
    assert hoja is not None
    hoja.append(
        [
            COLUMNAS.fecha_contabilizacion,
            COLUMNAS.fecha_documento,
            COLUMNAS.referencia,
            COLUMNAS.importe,
            COLUMNAS.texto,
            COLUMNAS.fecha_entrada,
        ]
    )
    for indice in range(registros):
        hoja.append(
            [
                datetime(2026, 3, 14),
                datetime(2026, 3, 10),
                4500001234 + indice,
                -1250.5 - indice,
                _PLAZA,
                datetime(2026, 3, 12),
            ]
        )
    memoria = io.BytesIO()
    libro.save(memoria)
    return memoria.getvalue()


def test_una_ejecucion_completa_entra_en_el_techo_del_prd(token_sentinela: str) -> None:
    """Un extracto de 1 000 registros, treinta veces el archivo real, bajo 15 s."""
    from app.main import crear_app

    contenido = _libro(_REGISTROS)

    with TestClient(crear_app()) as cliente:
        inicio = time.perf_counter()
        respuesta = cliente.post(
            "/interno/procesadores/contado_carga",
            files={"archivos": ("contado.xlsx", contenido, "application/octet-stream")},
            headers={"Authorization": f"Bearer {token_sentinela}"},
        )
        transcurrido = time.perf_counter() - inicio

    assert respuesta.status_code == 200, respuesta.text
    assert transcurrido < TECHO_DEL_PRD_S, (
        f"{_REGISTROS} registros tardaron {transcurrido:.1f} s, por encima del techo de "
        f"{TECHO_DEL_PRD_S} s del PRD. La referencia medida es ~1,9 s (MEDICIONES.md): "
        "esto no es ruido de la máquina, es una regresión de orden de magnitud."
    )


_SNIPPET_CADENA_DEL_HIJO = """
import sys

import app.core.ejecucion  # noqa: F401 - el modulo del objetivo de spawn

PROHIBIDOS = ("pandas", "numpy", "fastapi", "starlette", "pydantic_settings")
presentes = [m for m in PROHIBIDOS if m in sys.modules]
assert not presentes, f"la cadena del hijo importa {presentes}"
print("OK")
"""


def test_el_hijo_no_importa_librerias_pesadas() -> None:
    """La regresión de rendimiento más probable, convertida en comprobación.

    El hijo de `spawn` reimporta el árbol entero en CADA petición (ADR 0012),
    así que un import de más no cuesta una vez: cuesta siempre.

    Dos decisiones medidas dependen de esta lista. El ítem #16 eligió openpyxl
    sobre pandas porque `import pandas` cuesta ~590 ms en esta máquina. El
    ítem #17 mudó la admisión a `app/core/admision.py` y el borde HTTP de los
    errores a `app/core/errores_http.py` para sacar FastAPI, Starlette y
    pydantic-settings de esta cadena: el arranque del hijo bajó de 877 ms a
    428 ms y su pico de memoria de ~46 MB a ~28 MB (`MEDICIONES.md`).

    Deshacer cualquiera de las dos es fácil y silencioso —un import
    "inofensivo" en un procesador nuevo, un `from fastapi import ...` para
    tipar algo— y no rompe ninguna prueba de comportamiento.

    **Corre en un intérprete fresco, y esto es obligatorio, no una
    precaución.** `sys.modules` es del proceso: para cuando este test corre,
    otras suites del mismo pytest ya importaron FastAPI, y comprobarlo en
    proceso daría rojo siempre —diciendo la verdad sobre pytest y una mentira
    sobre producción—. Se parte de `app.core.ejecucion`, que es el módulo que
    `spawn` reimporta de verdad por contener el objetivo, y se mira el árbol
    ya importado en vez del texto del código: un import transitivo escondido
    detrás de un tercer módulo cuenta igual.
    """
    resultado = ejecutar_snippet(_SNIPPET_CADENA_DEL_HIJO)
    assert resultado.codigo_salida == 0, resultado.salida
    assert "OK" in resultado.salida
