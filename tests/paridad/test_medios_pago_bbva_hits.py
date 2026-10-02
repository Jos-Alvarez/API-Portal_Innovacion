"""Paridad de `medios-pago-bbva-hits` contra la salida del script (ADR 0015).

**Estado: 2 pares sobre el mismo extracto real** (`bbva.csv_`, mayo de 2025):

- **01**: el extracto más los tres reportes crudos de Izipay del par de
  `medios_pago_reportes`; salida REGENERADA (Reportes y después BBVA Hits).
- **02**: el extracto solo; salida HISTÓRICA (el CATEGORIZADO y los 36
  `HIST-*` de SP y VISA que estaban en `BBVA - Hits/Salida`). Esa corrida
  cruzó contra particiones de otros meses: ningún abono cruzó, que es
  exactamente correr sin reportes de Izipay.

Las salidas viajan como un ZIP en el recurso compartido; se comparan celda por
celda con `tests/paridad/test_medios_pago_reportes.py::comparar`. Con
`FIXTURES_PARIDAD` sin definir, todo esto saltea con aviso, y falla en CI.
"""

from __future__ import annotations

from pathlib import Path

from app.procesadores.medios_pago.bbva_hits import MediosPagoBbvaHits
from tests.paridad.manifiesto import ParDeParidad, exigir_pares
from tests.paridad.test_medios_pago_reportes import comparar, esperadas, preparar

PROCESADOR = "medios_pago_bbva_hits"

NOMBRES_ORIGINALES: dict[str, str] = {
    "entrada_bbva": "bbva.csv_",
    "entrada_mc": "mc_052025009428105 (13).csv",
    "entrada_amex": "movi_amex052025009428105 (13).csv",
    "entrada_dinner": "servicios052025009428105 (13).csv",
}


def _pares() -> list[ParDeParidad]:
    """Compuerta de ADR 0015. Corta la prueba —fallando o salteando— si falta algo."""
    return exigir_pares(PROCESADOR)


def test_el_categorizado_y_los_hist_coinciden(tmp_path: Path) -> None:
    for par in _pares():
        entradas = preparar(par, NOMBRES_ORIGINALES, tmp_path, PROCESADOR)
        procesador = MediosPagoBbvaHits()
        assert procesador.validar(entradas) is None, f"par {par.id}: las entradas no validan"
        obtenidas = {s.nombre_propuesto: s.ruta_temporal for s in procesador.procesar(entradas)}
        comparar(obtenidas, esperadas(par, PROCESADOR), par)


def test_cada_par_declara_el_extracto_y_su_salida() -> None:
    """El manifiesto es el contrato: un par a medias no es un par."""
    for par in _pares():
        assert {"entrada_bbva", "salida_zip"} <= set(par.archivos), f"par {par.id}: incompleto"
