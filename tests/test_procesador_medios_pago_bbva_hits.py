"""Pruebas del procesador `medios-pago-bbva-hits`.

Extractos, reportes de Izipay y maestros sintéticos con el layout de las
muestras reales (`tests/ayudas/medios_pago.py`), guardados SIN extensión como
los escribe `app/recepcion.py`. Prueban las **reglas**; la paridad contra el
script es `tests/paridad/test_medios_pago_bbva_hits.py`.
"""

from __future__ import annotations

import io
import zipfile
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest

from app.core.contrato import obtener_contrato
from app.core.errores import ErrorContenido, ErrorFormato
from app.core.tipos import ArchivoEntrada
from app.core.validaciones import validar_formato, validar_tamano_descomprimido
from app.procesadores.medios_pago.bbva_hits import (
    CLAVE,
    NOMBRE_CATEGORIZADO,
    ORDEN_COLUMNAS,
    MediosPagoBbvaHits,
    convertir_a_datetime,
    fecha_corrida,
)
from app.procesadores.medios_pago.comun import NOMBRE_OBSERVACIONES
from app.recepcion import _formato
from tests.ayudas.medios_pago import (
    ANTIGUO,
    Fabrica,
    celdas_xlsx,
    csv_izipay,
    extracto_bbva,
    fecha_safetypay,
    fila_izipay,
    fila_safetypay,
    leer_xlsx,
    libro_maestro,
    libro_safetypay,
    linea_22,
)

_DOC, _DESCRIPCION, _OBSERVACION, _FECHA_ABONO = 6, 7, 8, 9


@pytest.fixture
def fabrica(tmp_path: Path) -> Fabrica:
    return Fabrica(tmp_path)


@pytest.fixture
def procesador() -> MediosPagoBbvaHits:
    return MediosPagoBbvaHits()


def _procesar(procesador: MediosPagoBbvaHits, *entradas: ArchivoEntrada) -> dict[str, Path]:
    assert procesador.validar(list(entradas)) is None
    return {s.nombre_propuesto: s.ruta_temporal for s in procesador.procesar(list(entradas))}


def _error(procesador: MediosPagoBbvaHits, *entradas: ArchivoEntrada) -> ErrorContenido:
    error = procesador.validar(list(entradas))
    assert isinstance(error, ErrorContenido)
    return error


def _categorizado(salidas: dict[str, Path]) -> list[list[Any]]:
    filas = leer_xlsx(salidas[NOMBRE_CATEGORIZADO])
    assert filas[0] == list(ORDEN_COLUMNAS)
    return filas[1:]


def _observaciones(ruta: Path) -> list[list[str]]:
    lineas = ruta.read_bytes().decode("utf-8").split("\r\n")
    return [linea.split("\t") for linea in lineas[3:] if linea]


def _extracto(fabrica: Fabrica, *lineas: str, nombre: str = "bbva.csv_") -> ArchivoEntrada:
    return fabrica(nombre, extracto_bbva(lineas))


def _mc(fabrica: Fabrica, *filas: dict[str, str], nombre: str = "mc.csv") -> ArchivoEntrada:
    return fabrica(nombre, csv_izipay("mastercard", list(filas)))


# --- Registro, contrato y el formato `csv_` -----------------------------------


def test_la_clave_coincide_con_el_registry_y_el_contrato() -> None:
    from app.registry import REGISTRY

    procesador = REGISTRY[CLAVE]
    assert procesador.clave == CLAVE == "medios-pago-bbva-hits"
    assert isinstance(procesador, MediosPagoBbvaHits)
    contrato = obtener_contrato(CLAVE)
    assert contrato is not None
    assert (contrato.entradas_min, contrato.entradas_max) == (1, 10)
    assert contrato.formatos_aceptados == ("csv_", "csv", "xlsx")


def test_el_formato_csv_guion_bajo_lo_acepta_el_nucleo_sin_cambios(fabrica: Fabrica) -> None:
    """`_formato` toma lo que sigue al último punto (`csv_`, en minúsculas);
    `validar_formato` compara texto; un texto no es un ZIP y el control de
    tamaño descomprimido no aplica."""
    contrato = obtener_contrato(CLAVE)
    assert contrato is not None
    assert _formato("bbva.csv_") == _formato("BBVA.CSV_") == "csv_"
    validar_formato(nombre_original="bbva.csv_", formato="csv_", contrato=contrato)
    with pytest.raises(ErrorFormato):
        validar_formato(nombre_original="bbva.txt", formato="txt", contrato=contrato)
    validar_tamano_descomprimido(_extracto(fabrica, linea_22("250502", 155464)))


# --- Composición del lote ---------------------------------------------------------


def test_dos_extractos_son_tipo_duplicado(procesador: MediosPagoBbvaHits, fabrica: Fabrica) -> None:
    uno = _extracto(fabrica, linea_22("250502", 155464))
    dos = _extracto(fabrica, linea_22("250503", 155464), nombre="otro.csv")
    assert _error(procesador, uno, dos).contexto == {
        "archivo": "otro.csv",
        "motivo": "tipo_duplicado",
        "columna": None,
    }


def test_dos_maestros_son_tipo_duplicado(procesador: MediosPagoBbvaHits, fabrica: Fabrica) -> None:
    maestro = libro_maestro([])
    error = _error(
        procesador,
        _extracto(fabrica, linea_22("250502", 155464)),
        fabrica("Abonos_BBVA.xlsx", maestro),
        fabrica("viejo.xlsx", maestro),
    )
    assert error.contexto == {"archivo": "viejo.xlsx", "motivo": "tipo_duplicado", "columna": None}


def test_sin_extracto_es_cero_filas(procesador: MediosPagoBbvaHits, fabrica: Fabrica) -> None:
    error = _error(procesador, _mc(fabrica, fila_izipay("mastercard", "20250506")))
    assert error.contexto == {"archivo": "mc.csv", "motivo": "cero_filas", "columna": None}


def test_un_extracto_sin_movimientos_es_cero_filas(
    procesador: MediosPagoBbvaHits, fabrica: Fabrica
) -> None:
    entrada = _extracto(fabrica, linea_22("250502", 155464, concepto="ITF"))
    assert procesador.validar([entrada]) is None
    with pytest.raises(ErrorContenido) as error:
        procesador.procesar([entrada])
    assert error.value.contexto["motivo"] == "cero_filas"


def test_safetypay_se_acepta_y_se_ignora(procesador: MediosPagoBbvaHits, fabrica: Fabrica) -> None:
    libro = libro_safetypay([fila_safetypay(fecha_safetypay(date(2025, 5, 2)))])
    con = _procesar(
        procesador,
        _extracto(fabrica, linea_22("250502", 155464)),
        fabrica("MPFinancialReport.xlsx", libro),
    )
    sin = _procesar(procesador, _extracto(fabrica, linea_22("250502", 155464)))
    assert list(con) == list(sin) == [NOMBRE_CATEGORIZADO]
    assert leer_xlsx(con[NOMBRE_CATEGORIZADO]) == leer_xlsx(sin[NOMBRE_CATEGORIZADO])


def test_el_extracto_se_reconoce_por_su_contenido(
    procesador: MediosPagoBbvaHits, fabrica: Fabrica
) -> None:
    salidas = _procesar(procesador, _extracto(fabrica, linea_22("250502", 155464), nombre="x.csv"))
    assert list(salidas) == [NOMBRE_CATEGORIZADO]


def test_un_archivo_desconocido_es_tipo_no_reconocido(
    procesador: MediosPagoBbvaHits, fabrica: Fabrica
) -> None:
    error = _error(procesador, fabrica("otro.csv", b"a,b\n1,2\n"))
    assert error.contexto == {
        "archivo": "otro.csv",
        "motivo": "tipo_no_reconocido",
        "columna": None,
    }


# --- Lectura, filtros y categorización ----------------------------------------------


@pytest.mark.parametrize(
    ("texto", "fecha"),
    [("250502", datetime(2025, 5, 2)), ("251399", None), ("2505", None), (None, None)],
)
def test_convertir_a_datetime(texto: str | None, fecha: datetime | None) -> None:
    assert convertir_a_datetime(texto) == fecha


def test_una_linea_como_la_deja_el_script(procesador: MediosPagoBbvaHits, fabrica: Fabrica) -> None:
    """Sólo los `22`, ceros a la izquierda fuera, importe en céntimos, `F.
    Operación` fecha y `F. Valor` TEXTO, los dos con formato `DD/MM/YYYY`."""
    salidas = _procesar(procesador, _extracto(fabrica, linea_22("250502", 155464)))
    assert _categorizado(salidas) == [
        [
            datetime(2025, 5, 2),
            "02/05/2025",
            118,
            1554.64,
            26498,
            "R20432405525PROCESOS DE MEDI",
            814,
            None,
            None,
            None,
        ]
    ]
    fila = celdas_xlsx(salidas[NOMBRE_CATEGORIZADO])[1]
    assert (fila[0].number_format, fila[1].number_format, fila[1].data_type) == (
        "DD/MM/YYYY",
        "DD/MM/YYYY",
        "s",
    )
    titulo = celdas_xlsx(salidas[NOMBRE_CATEGORIZADO])[0][0]
    assert (titulo.font.b, titulo.border.left.style) == (True, "thin")


@pytest.mark.parametrize(
    ("concepto", "codigo"),
    [
        ("ITF", 118),
        (" itf ", 118),
        ("ABONO / CTA", 118),
        ("COMISION X", 118),
        ("CAPITAL-INT PLAZO FIDUCIARIA", 118),
        ("OTRO", 15),
        ("OTRO", 612),
    ],
)
def test_filtros_de_concepto_y_codigo(
    procesador: MediosPagoBbvaHits, fabrica: Fabrica, concepto: str, codigo: int
) -> None:
    salidas = _procesar(
        procesador,
        _extracto(
            fabrica,
            linea_22("250502", 155464, concepto="QUEDA"),
            linea_22("250502", 155464, concepto=concepto, codigo=codigo),
        ),
    )
    assert [f[5] for f in _categorizado(salidas)] == ["QUEDA"]


@pytest.mark.parametrize(
    ("codigo", "concepto", "centimos", "descripcion"),
    [
        (10, "X", 100000, "EFECTIVO"),
        (1, "X", 100000, "SALDO NEGATIVO"),
        (507, "X", 100000, "SALDO NEGATIVO"),
        (260, "X", 100000, "VISA"),
        (260, "R2051 SAFTPAY DEL PERU", 100000, "SAFETYPAY"),
        (118, "COMPAÑIA DE SERV PERU", 100000, "AMEX"),
        (118, "X", 999, "SALDO NEGATIVO"),
        (260, "X", 999, "VISA"),
        (118, "X", 100000, None),
    ],
)
def test_categorizacion_directa_en_su_orden(
    procesador: MediosPagoBbvaHits,
    fabrica: Fabrica,
    codigo: int,
    concepto: str,
    centimos: int,
    descripcion: str | None,
) -> None:
    salidas = _procesar(
        procesador,
        _extracto(fabrica, linea_22("250502", centimos, codigo=codigo, concepto=concepto)),
    )
    assert _categorizado(salidas)[0][_DESCRIPCION] == descripcion


def test_concepto_vacio_sale_nan_como_en_pandas_2(
    procesador: MediosPagoBbvaHits, fabrica: Fabrica
) -> None:
    salidas = _procesar(procesador, _extracto(fabrica, linea_22("250502", 155464, concepto="")))
    assert _categorizado(salidas)[0][5] == "NAN"


# --- Cruce -----------------------------------------------------------------------------


def test_primera_pasada_cruza_por_fecha_e_importe(
    procesador: MediosPagoBbvaHits, fabrica: Fabrica
) -> None:
    salidas = _procesar(
        procesador,
        _extracto(
            fabrica,
            linea_22("250506", 1387),
            linea_22("250506", 24748),
            linea_22("250506", 5000),
        ),
        _mc(
            fabrica,
            fila_izipay("mastercard", "20250506", neto="13.87"),
            fila_izipay("mastercard", "20250506", neto="247.48", codigo=ANTIGUO),
        ),
        fabrica("movi_amex.csv", csv_izipay("amex", [fila_izipay("amex", "20250506", neto="50")])),
    )
    filas = _categorizado(salidas)
    assert [(f[_DESCRIPCION], f[_OBSERVACION], f[_FECHA_ABONO]) for f in filas] == [
        ("MC", "IZI", None),
        ("MC", "ANTIGUO", None),
        ("AMEX", "IZI", None),
    ]
    assert sorted(salidas) == [
        NOMBRE_CATEGORIZADO,
        "HIST-2025-05-06-AMEX-IZI.xlsx",
        "HIST-2025-05-06-MC-ANTIGUO.xlsx",
        "HIST-2025-05-06-MC-IZI.xlsx",
    ]


def test_el_contador_cruza_duplicados_uno_a_uno(
    procesador: MediosPagoBbvaHits, fabrica: Fabrica
) -> None:
    """Tres abonos iguales y dos filas de Izipay: cruzan los dos primeros."""
    salidas = _procesar(
        procesador,
        _extracto(fabrica, *[linea_22("250506", 1387, doc=f"{i:04d}") for i in (1, 2, 3)]),
        fabrica(
            "servicios.csv",
            csv_izipay(
                "dinner",
                [
                    fila_izipay("dinner", "20250506", neto="13.87"),
                    fila_izipay("dinner", "20250506", neto="13.87"),
                ],
            ),
        ),
    )
    filas = _categorizado(salidas)
    assert [(f[_DOC], f[_DESCRIPCION]) for f in filas] == [(1, "DN"), (2, "DN"), (3, None)]


def test_segunda_pasada_corre_la_fecha_y_la_deja_escrita(
    procesador: MediosPagoBbvaHits, fabrica: Fabrica
) -> None:
    """Un abono de Izipay del lunes 12 cruza con el viernes 9 del banco; uno
    del martes 13, con el lunes 12."""
    salidas = _procesar(
        procesador,
        _extracto(fabrica, linea_22("250509", 1387), linea_22("250512", 2000)),
        _mc(
            fabrica,
            fila_izipay("mastercard", "20250512", neto="13.87"),
            fila_izipay("mastercard", "20250513", neto="20.00"),
        ),
    )
    filas = _categorizado(salidas)
    assert [(f[_DESCRIPCION], f[_OBSERVACION], f[_FECHA_ABONO]) for f in filas] == [
        ("MC", "IZI", "12/05/2025"),
        ("MC", "IZI", "13/05/2025"),
    ]


@pytest.mark.parametrize(
    ("fecha", "corrida"),
    [(date(2025, 5, 12), date(2025, 5, 9)), (date(2025, 5, 13), date(2025, 5, 12))],
)
def test_fecha_corrida(fecha: date, corrida: date) -> None:
    assert fecha_corrida(fecha) == corrida


def test_una_fila_ya_categorizada_sin_observacion_se_recategoriza(
    procesador: MediosPagoBbvaHits, fabrica: Fabrica
) -> None:
    """VISA por código, pero sin observación: el cruce la vuelve MC (verbatim)."""
    salidas = _procesar(
        procesador,
        _extracto(fabrica, linea_22("250506", 1387, codigo=260)),
        _mc(fabrica, fila_izipay("mastercard", "20250506", neto="13.87")),
    )
    assert _categorizado(salidas)[0][_DESCRIPCION] == "MC"


def test_en_la_primera_pasada_gana_el_primer_csv_en_orden_ntfs(
    procesador: MediosPagoBbvaHits, fabrica: Fabrica
) -> None:
    """`…-amex-izipay.csv` va antes que `…-mastercard-izipay.csv`."""
    salidas = _procesar(
        procesador,
        _extracto(fabrica, linea_22("250506", 1387)),
        _mc(fabrica, fila_izipay("mastercard", "20250506", neto="13.87")),
        fabrica(
            "movi_amex.csv", csv_izipay("amex", [fila_izipay("amex", "20250506", neto="13.87")])
        ),
    )
    assert _categorizado(salidas)[0][_DESCRIPCION] == "AMEX"


def test_en_la_segunda_pasada_gana_el_ultimo_csv(
    procesador: MediosPagoBbvaHits, fabrica: Fabrica
) -> None:
    salidas = _procesar(
        procesador,
        _extracto(fabrica, linea_22("250505", 1387)),
        _mc(fabrica, fila_izipay("mastercard", "20250506", neto="13.87")),
        fabrica(
            "movi_amex.csv", csv_izipay("amex", [fila_izipay("amex", "20250506", neto="13.87")])
        ),
    )
    assert _categorizado(salidas)[0][_DESCRIPCION] == "MC"


def test_el_cruce_ve_el_neto_como_lo_relee_pandas(
    procesador: MediosPagoBbvaHits, fabrica: Fabrica
) -> None:
    """Un `Neto_Total` entero (`247`) y uno con ceros (`13.870`) cruzan igual."""
    salidas = _procesar(
        procesador,
        _extracto(fabrica, linea_22("250506", 24700), linea_22("250507", 1387)),
        _mc(fabrica, fila_izipay("mastercard", "20250506", neto="247"), nombre="a mc.csv"),
        _mc(fabrica, fila_izipay("mastercard", "20250507", neto="13.870"), nombre="b mc.csv"),
    )
    assert [f[_DESCRIPCION] for f in _categorizado(salidas)] == ["MC", "MC"]


def test_un_neto_cero_o_ilegible_no_cruza(procesador: MediosPagoBbvaHits, fabrica: Fabrica) -> None:
    salidas = _procesar(
        procesador,
        _extracto(fabrica, linea_22("250506", 0), linea_22("250506", 1500)),
        _mc(
            fabrica,
            fila_izipay("mastercard", "20250506", neto="0.00"),
            fila_izipay("mastercard", "20250506", neto="15,00"),
        ),
    )
    assert [f[_DESCRIPCION] for f in _categorizado(salidas)] == ["SALDO NEGATIVO", None]
    assert _observaciones(salidas[NOMBRE_OBSERVACIONES]) == [
        ["mc.csv", "3", "importe_invalido", "15,00"]
    ]


# --- Maestro -------------------------------------------------------------------------


def test_el_maestro_manda_en_sus_fechas_y_va_primero(
    procesador: MediosPagoBbvaHits, fabrica: Fabrica
) -> None:
    maestro = libro_maestro(
        [
            [datetime(2025, 5, 5), "05/05/2025", 118, 50.5, 26000, "VIEJO", 814, "MC", "IZI", None],
        ]
    )
    salidas = _procesar(
        procesador,
        _extracto(fabrica, linea_22("250505", 155464), linea_22("250506", 2000)),
        fabrica("Abonos_BBVA.xlsx", maestro),
    )
    filas = _categorizado(salidas)
    assert [(f[0], f[5], f[_DESCRIPCION], f[_OBSERVACION]) for f in filas] == [
        (datetime(2025, 5, 5), "VIEJO", "MC", "IZI"),
        (datetime(2025, 5, 6), "R20432405525PROCESOS DE MEDI", None, None),
    ]
    assert "HIST-2025-05-05-MC-IZI.xlsx" in salidas


def test_un_maestro_sin_fecha_de_operacion_es_columna_faltante(
    procesador: MediosPagoBbvaHits, fabrica: Fabrica
) -> None:
    error = _error(
        procesador,
        _extracto(fabrica, linea_22("250502", 155464)),
        fabrica("Abonos_BBVA.xlsx", _libro_sin_fecha()),
    )
    assert error.contexto == {
        "archivo": "Abonos_BBVA.xlsx",
        "motivo": "columna_faltante",
        "columna": "F. Operación",
    }


def _libro_sin_fecha() -> bytes:
    from openpyxl import Workbook

    libro = Workbook()
    hoja = libro.active
    assert hoja is not None
    hoja.append(["Importe", "Concepto"])
    salida = io.BytesIO()
    libro.save(salida)
    return salida.getvalue()


# --- HIST ----------------------------------------------------------------------------


def test_hist_titulos_en_la_fila_5_e_intercambio_de_safetypay(
    procesador: MediosPagoBbvaHits, fabrica: Fabrica
) -> None:
    salidas = _procesar(
        procesador,
        _extracto(
            fabrica,
            linea_22(
                "250502",
                6420315,
                concepto="R205 SAFTPAY DEL PERU",
                doc="0437",
                oficina="0000026527",
            ),
            linea_22("250502", 100000, codigo=10),
        ),
    )
    assert sorted(salidas) == [NOMBRE_CATEGORIZADO, "HIST-2025-05-02-SP.xlsx"]
    filas = leer_xlsx(salidas["HIST-2025-05-02-SP.xlsx"])
    assert filas[:4] == [[None] * 10] * 4
    assert filas[4] == list(ORDEN_COLUMNAS)
    assert filas[5][4] == 437 and filas[5][_DOC] == 26527
    assert len(filas) == 6
    categorizado = _categorizado(salidas)
    assert (categorizado[0][4], categorizado[0][_DOC]) == (26527, 437)


def test_visa_el_filtro_de_la_ultima_fila_gana(
    procesador: MediosPagoBbvaHits, fabrica: Fabrica
) -> None:
    """Tres VISA del mismo día en el maestro, con y sin observación: el nombre
    no la lleva, el filtro sí, y el archivo final es el de la ÚLTIMA fila."""
    maestro = libro_maestro(
        [
            [datetime(2025, 5, 2), "02/05/2025", 260, 100.0, 1, "A", 1, "VISA", "ANTIGUO", None],
            [datetime(2025, 5, 2), "02/05/2025", 260, 200.0, 2, "B", 2, "VISA", None, None],
            [datetime(2025, 5, 2), "02/05/2025", 260, 300.0, 3, "C", 3, "VISA", "ANTIGUO", None],
        ]
    )
    salidas = _procesar(
        procesador,
        _extracto(fabrica, linea_22("250503", 100000)),
        fabrica("Abonos_BBVA.xlsx", maestro),
    )
    filas = leer_xlsx(salidas["HIST-2025-05-02-VISA.xlsx"])[5:]
    assert [f[5] for f in filas] == ["A", "C"]


# --- Observaciones -------------------------------------------------------------------


def test_perdidas_del_extracto_se_reportan_solo_si_llegan_a_la_salida(
    procesador: MediosPagoBbvaHits, fabrica: Fabrica
) -> None:
    salidas = _procesar(
        procesador,
        _extracto(
            fabrica,
            linea_22("251399", 155464),
            linea_22("251399", 155464, concepto="ITF"),
            linea_22("250502", 155464, doc="0X1"),
            "22,0011,0814,250502,250502,00,118,2,00000000155464,0000026498,DEMASIADO,LARGA",
        ),
    )
    assert _observaciones(salidas[NOMBRE_OBSERVACIONES]) == [
        [
            "bbva.csv_",
            "9",
            "linea_invalida",
            "22,0011,0814,250502,250502,00,118,2,00000000155464,0000026498,DEMASIADO,LARGA",
        ],
        ["bbva.csv_", "3", "fecha_invalida", "251399"],
        ["bbva.csv_", "7", "numero_invalido", "0X1"],
    ]
    filas = _categorizado(salidas)
    assert [(f[0], f[_DOC]) for f in filas] == [(None, 814), (datetime(2025, 5, 2), 0)]
    assert sorted(salidas) == [NOMBRE_CATEGORIZADO, NOMBRE_OBSERVACIONES]


def test_un_extracto_completo_no_deja_observaciones(
    procesador: MediosPagoBbvaHits, fabrica: Fabrica
) -> None:
    salidas = _procesar(procesador, _extracto(fabrica, linea_22("250502", 155464, codigo=260)))
    assert sorted(salidas) == [NOMBRE_CATEGORIZADO, "HIST-2025-05-02-VISA.xlsx"]


# --- De punta a punta, por la ruta real y el proceso hijo ----------------------


class TestPuntaAPunta:
    """La tubería completa: HTTP → temporales sin extensión → `spawn` → ZIP."""

    @staticmethod
    def _subir(cliente: Any, archivos: list[tuple[str, bytes]]) -> Any:
        return cliente.post(
            f"/interno/procesadores/{CLAVE}",
            files=[
                ("archivos", (nombre, contenido, "application/octet-stream"))
                for nombre, contenido in archivos
            ],
            headers={"Authorization": "Bearer sentinela-token-de-pruebas-3f9c2a"},
        )

    def test_extracto_y_reporte_vuelven_en_un_zip(self, token_sentinela: str) -> None:
        from fastapi.testclient import TestClient

        from app.main import crear_app

        with TestClient(crear_app()) as cliente:
            respuesta = self._subir(
                cliente,
                [
                    ("bbva.csv_", extracto_bbva([linea_22("250506", 1387)])),
                    (
                        "movi_amex.csv",
                        csv_izipay("amex", [fila_izipay("amex", "20250506", neto="13.87")]),
                    ),
                ],
            )

        assert respuesta.status_code == 200, respuesta.text
        assert respuesta.headers["content-type"] == "application/zip"
        with zipfile.ZipFile(io.BytesIO(respuesta.content)) as contenedor:
            assert contenedor.namelist() == [NOMBRE_CATEGORIZADO, "HIST-2025-05-06-AMEX-IZI.xlsx"]
            fila = leer_xlsx(contenedor.read(NOMBRE_CATEGORIZADO))[1]
        assert fila[_DESCRIPCION:] == ["AMEX", "IZI", None]

    def test_dos_extractos_son_422(self, token_sentinela: str) -> None:
        from fastapi.testclient import TestClient

        from app.main import crear_app

        extracto = extracto_bbva([linea_22("250506", 1387)])
        with TestClient(crear_app()) as cliente:
            respuesta = self._subir(cliente, [("bbva.csv_", extracto), ("BBVA2.CSV_", extracto)])

        assert respuesta.status_code == 422
        assert respuesta.json()["contexto"] == {
            "archivo": "BBVA2.CSV_",
            "motivo": "tipo_duplicado",
            "columna": None,
        }
