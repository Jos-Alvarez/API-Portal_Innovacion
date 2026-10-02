"""Pruebas del procesador `medios-pago-reportes`.

Entradas sintéticas con el layout de las muestras reales (`tests/ayudas/
medios_pago.py`), guardadas SIN extensión como las escribe `app/recepcion.py`.
Prueban las **reglas**; la paridad contra el script es
`tests/paridad/test_medios_pago_reportes.py`.
"""

from __future__ import annotations

import io
import zipfile
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest

from app.core.contrato import obtener_contrato
from app.core.errores import ErrorContenido
from app.core.tipos import ArchivoEntrada
from app.procesadores.medios_pago.comun import NOMBRE_OBSERVACIONES, redondear2
from app.procesadores.medios_pago.izipay import (
    _filas_por_tramo,
    _inferir_columna,
    fecha_de_abono,
)
from app.procesadores.medios_pago.reportes import CLAVE, MediosPagoReportes
from tests.ayudas.medios_pago import (
    ANTIGUO,
    TITULOS_IZIPAY,
    TITULOS_SAFETYPAY,
    Fabrica,
    celdas_xlsx,
    csv_izipay,
    extracto_bbva,
    fecha_safetypay,
    fila_izipay,
    fila_safetypay,
    leer_xlsx,
    libro_safetypay,
    linea_22,
)


@pytest.fixture
def fabrica(tmp_path: Path) -> Fabrica:
    return Fabrica(tmp_path)


@pytest.fixture
def procesador() -> MediosPagoReportes:
    return MediosPagoReportes()


def _procesar(procesador: MediosPagoReportes, *entradas: ArchivoEntrada) -> dict[str, Path]:
    assert procesador.validar(list(entradas)) is None
    return {s.nombre_propuesto: s.ruta_temporal for s in procesador.procesar(list(entradas))}


def _error(procesador: MediosPagoReportes, *entradas: ArchivoEntrada) -> ErrorContenido:
    error = procesador.validar(list(entradas))
    assert isinstance(error, ErrorContenido)
    return error


def _lineas(ruta: Path) -> list[str]:
    datos = ruta.read_bytes()
    assert b"\r\n" in datos and b"\n" not in datos.replace(b"\r\n", b"")
    return datos.decode("utf-8").split("\r\n")[:-1]


def _columna(ruta: Path, nombre: str) -> list[str]:
    lineas = _lineas(ruta)
    indice = lineas[0].split(",").index(nombre)
    return [linea.split(",")[indice] for linea in lineas[1:]]


def _observaciones(ruta: Path) -> list[list[str]]:
    lineas = ruta.read_bytes().decode("utf-8").split("\r\n")
    return [linea.split("\t") for linea in lineas[3:] if linea]


# --- Registro y contrato ------------------------------------------------------


def test_la_clave_coincide_con_el_registry_y_el_contrato() -> None:
    from app.registry import REGISTRY

    procesador = REGISTRY[CLAVE]
    assert procesador.clave == CLAVE == "medios-pago-reportes"
    assert isinstance(procesador, MediosPagoReportes)
    contrato = obtener_contrato(CLAVE)
    assert contrato is not None
    assert (contrato.entradas_min, contrato.entradas_max) == (1, 10)
    assert contrato.formatos_aceptados == ("csv", "xlsx")


# --- Detección por contenido -------------------------------------------------


def test_el_tipo_se_detecta_por_las_columnas_y_no_por_el_nombre(
    procesador: MediosPagoReportes, fabrica: Fabrica
) -> None:
    """Un Mastercard llamado sin `mc`, un AMEX llamado `mc…` y un Diners sin
    `servicios`: el script los habría confundido o salteado."""
    salidas = _procesar(
        procesador,
        fabrica(
            "reporte uno.csv", csv_izipay("mastercard", [fila_izipay("mastercard", "20250506")])
        ),
        fabrica("mc_falso.csv", csv_izipay("amex", [fila_izipay("amex", "20250506")])),
        fabrica("otro.csv", csv_izipay("dinner", [fila_izipay("dinner", "20250506")])),
    )
    assert sorted(salidas) == [
        "2025-05-06-amex-izipay.csv",
        "2025-05-06-dinner-izipay.csv",
        "2025-05-06-mastercard-izipay.csv",
    ]


def test_columnas_ambiguas_las_decide_el_nombre_como_en_el_script(
    procesador: MediosPagoReportes, fabrica: Fabrica
) -> None:
    titulos = (*TITULOS_IZIPAY["mastercard"], "Comision_Merchant")
    contenido = csv_izipay("mastercard", [fila_izipay("mastercard", "20250506")], titulos=titulos)
    salidas = _procesar(procesador, fabrica("mc_052025.csv", contenido))
    assert list(salidas) == ["2025-05-06-mastercard-izipay.csv"]
    error = _error(procesador, fabrica("reporte.csv", contenido))
    assert error.contexto == {
        "archivo": "reporte.csv",
        "motivo": "tipo_no_reconocido",
        "columna": None,
    }


def test_un_amex_por_nombre_sin_su_fecha_es_columna_faltante(
    procesador: MediosPagoReportes, fabrica: Fabrica
) -> None:
    titulos = (*TITULOS_IZIPAY["mastercard"], "Comision_Merchant")
    contenido = csv_izipay("mastercard", [], titulos=[t for t in titulos if t != "Fecha_Abono"])
    error = _error(procesador, fabrica("movi_amex.csv", contenido))
    assert error.contexto == {
        "archivo": "movi_amex.csv",
        "motivo": "columna_faltante",
        "columna": "Fecha_Abono",
    }


@pytest.mark.parametrize(
    ("nombre", "contenido"),
    [
        ("mc_cualquiera.csv", b"a,b,c\n1,2,3\n"),
        ("bbva.csv", extracto_bbva([linea_22("250502", 155464)])),
        ("vacio.csv", b""),
    ],
)
def test_lo_que_no_es_un_reporte_es_tipo_no_reconocido(
    procesador: MediosPagoReportes, fabrica: Fabrica, nombre: str, contenido: bytes
) -> None:
    error = _error(procesador, fabrica(nombre, contenido))
    assert error.contexto == {"archivo": nombre, "motivo": "tipo_no_reconocido", "columna": None}


def test_dos_safetypay_son_tipo_duplicado(procesador: MediosPagoReportes, fabrica: Fabrica) -> None:
    libro = libro_safetypay([fila_safetypay(fecha_safetypay(date(2025, 5, 26)))])
    error = _error(
        procesador, fabrica("MPFinancialReport.xlsx", libro), fabrica("otro.xlsx", libro)
    )
    assert error.contexto == {"archivo": "otro.xlsx", "motivo": "tipo_duplicado", "columna": None}


def test_un_libro_que_no_abre_es_cero_filas(
    procesador: MediosPagoReportes, fabrica: Fabrica
) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as falso:
        falso.writestr("hola.txt", "no soy un libro")
    error = _error(procesador, fabrica("MPFinancialReport.xlsx", buffer.getvalue()))
    assert error.contexto["motivo"] == "cero_filas"


def test_un_csv_que_no_es_utf8_es_cero_filas(
    procesador: MediosPagoReportes, fabrica: Fabrica
) -> None:
    contenido = csv_izipay(
        "mastercard", [fila_izipay("mastercard", "20250506", Observaciones="Señal")]
    ).replace("Señal".encode(), "Señal".encode("latin1"))
    entrada = fabrica("mc.csv", contenido)
    assert procesador.validar([entrada]) is None
    with pytest.raises(ErrorContenido) as error:
        procesador.procesar([entrada])
    assert error.value.contexto == {"archivo": "mc.csv", "motivo": "cero_filas", "columna": None}


# --- Partición de Izipay ---------------------------------------------------------


def test_cada_fecha_se_parte_por_codigo(procesador: MediosPagoReportes, fabrica: Fabrica) -> None:
    filas = [
        fila_izipay("mastercard", "20250506", codigo=ANTIGUO, Voucher="1"),
        fila_izipay("mastercard", "20250507", Voucher="2"),
        fila_izipay("mastercard", "20250506", Voucher="3"),
        fila_izipay("mastercard", "20250506", codigo="4010761", Voucher="4"),
    ]
    salidas = _procesar(procesador, fabrica("mc.csv", csv_izipay("mastercard", filas)))
    assert list(salidas) == [
        "2025-05-06-mastercard.csv",
        "2025-05-06-mastercard-izipay.csv",
        "2025-05-07-mastercard-izipay.csv",
    ]
    assert _columna(salidas["2025-05-06-mastercard.csv"], "Voucher") == ["1", "4"]
    assert _columna(salidas["2025-05-06-mastercard-izipay.csv"], "Voucher") == ["3"]


def test_to_csv_como_pandas(procesador: MediosPagoReportes, fabrica: Fabrica) -> None:
    """Números normalizados (`14.00` → `14.0`), enteros con NaN como `float`,
    texto con sus ceros, comillas mínimas, sin la columna `Unnamed` y CRLF."""
    filas = [
        fila_izipay("mastercard", "20250506", Lote_Manual="4196", Observaciones="con, coma"),
        fila_izipay("mastercard", "20250506", Importe="7", Observaciones='"citado"'),
    ]
    salidas = _procesar(procesador, fabrica("mc.csv", csv_izipay("mastercard", filas)))
    lineas = _lineas(salidas["2025-05-06-mastercard-izipay.csv"])
    assert lineas[0] == ",".join(TITULOS_IZIPAY["mastercard"])
    assert lineas[1] == (
        "001042409,VA,A,02/05/2025,,4196.0,0378,PS0005,0004034,072277,,477289******7763,,,,14.0,,"
        '0.12,,0.01,13.87,13.87,,20250506,"con, coma"'
    )
    assert lineas[2].endswith(',7.0,,0.12,,0.01,13.87,13.87,,20250506,"""citado"""')


def test_una_columna_entera_sin_nan_queda_entera(
    procesador: MediosPagoReportes, fabrica: Fabrica
) -> None:
    filas = [fila_izipay("mastercard", "20250506", Lote_Manual="0042", Importe="14")]
    salidas = _procesar(procesador, fabrica("mc.csv", csv_izipay("mastercard", filas)))
    ruta = salidas["2025-05-06-mastercard-izipay.csv"]
    assert _columna(ruta, "Lote_Manual") == ["42"]
    assert _columna(ruta, "Importe") == ["14"]


def test_la_fecha_se_reduce_a_ocho_digitos(
    procesador: MediosPagoReportes, fabrica: Fabrica
) -> None:
    filas = [fila_izipay("dinner", "x20250506y"), fila_izipay("dinner", "20250507")]
    salidas = _procesar(procesador, fabrica("servicios.csv", csv_izipay("dinner", filas)))
    assert _columna(salidas["2025-05-06-dinner-izipay.csv"], "Fecha_Abono_8Dig") == ["20250506"]


@pytest.mark.parametrize(
    ("valor", "fecha"),
    [
        ("20250506", date(2025, 5, 6)),
        (20250506, date(2025, 5, 6)),
        (20250506.0, date(2025, 5, 6)),
        ("2025-05-06", None),
        ("20251399", None),
        (None, None),
    ],
)
def test_fecha_de_abono(valor: object, fecha: date | None) -> None:
    assert fecha_de_abono(valor) == fecha


def test_varios_archivos_del_mismo_tipo_se_acumulan_en_orden_ntfs(
    procesador: MediosPagoReportes, fabrica: Fabrica
) -> None:
    """`b` antes que `C` (NTFS compara en mayúsculas) aunque se suban al revés;
    la columna que sólo tiene uno pasa a `float` (`4196.0`) y queda vacía en
    las filas del otro."""
    titulos_sin_lote = [t for t in TITULOS_IZIPAY["mastercard"] if t != "Lote_Manual"]
    uno = csv_izipay(
        "mastercard", [fila_izipay("mastercard", "20250506", Voucher="C")], titulos=titulos_sin_lote
    )
    dos = csv_izipay(
        "mastercard", [fila_izipay("mastercard", "20250506", Voucher="b", Lote_Manual="4196")]
    )
    salidas = _procesar(procesador, fabrica("C mc.csv", uno), fabrica("b mc.csv", dos))
    ruta = salidas["2025-05-06-mastercard-izipay.csv"]
    assert _columna(ruta, "Voucher") == ["b", "C"]
    assert _columna(ruta, "Lote_Manual") == ["4196.0", ""]


def test_amex_se_corre_fuera_de_fines_de_semana_y_feriados(
    procesador: MediosPagoReportes, fabrica: Fabrica
) -> None:
    filas = [
        fila_izipay("amex", "20250510", Voucher="sabado"),  # → lunes 12
        fila_izipay("amex", "20250501", Voucher="trabajo"),  # feriado jueves → viernes 2
        fila_izipay("amex", "20260728", Voucher="patrias"),  # 28 y 29 de julio de 2026 → 30
        fila_izipay("amex", "20260402", Voucher="santo"),  # jueves y viernes santo 2026 → lunes 6
        fila_izipay("amex", "20281230", Voucher="anio"),  # sábado, domingo, 1/1/2029 → martes 2
    ]
    salidas = _procesar(procesador, fabrica("movi_amex.csv", csv_izipay("amex", filas)))
    esperado = {
        "2025-05-12-amex-izipay.csv": ("sabado", "20250512"),
        "2025-05-02-amex-izipay.csv": ("trabajo", "20250502"),
        "2026-07-30-amex-izipay.csv": ("patrias", "20260730"),
        "2026-04-06-amex-izipay.csv": ("santo", "20260406"),
        "2029-01-02-amex-izipay.csv": ("anio", "20290102"),
    }
    assert set(salidas) == set(esperado)
    for nombre, (voucher, fecha) in esperado.items():
        assert _columna(salidas[nombre], "Voucher") == [voucher]
        assert _columna(salidas[nombre], "Fecha_Abono") == [fecha]


def test_mastercard_y_diners_no_se_corren(procesador: MediosPagoReportes, fabrica: Fabrica) -> None:
    salidas = _procesar(
        procesador,
        fabrica("mc.csv", csv_izipay("mastercard", [fila_izipay("mastercard", "20250510")])),
    )
    assert list(salidas) == ["2025-05-10-mastercard-izipay.csv"]


def test_perdidas_silenciosas_se_reportan_y_las_fechas_en_blanco_no(
    procesador: MediosPagoReportes, fabrica: Fabrica
) -> None:
    filas = [
        fila_izipay("mastercard", "20250506"),
        fila_izipay("mastercard", "", Voucher="pendiente"),
        fila_izipay("mastercard", "06/05/2025"),
        fila_izipay("mastercard", "20250506", codigo="X1"),
    ]
    contenido = csv_izipay("mastercard", filas, extra=["1,2,3" + "," * 30])
    salidas = _procesar(procesador, fabrica("mc.csv", contenido))
    assert set(salidas) == {"2025-05-06-mastercard-izipay.csv", NOMBRE_OBSERVACIONES}
    assert _observaciones(salidas[NOMBRE_OBSERVACIONES]) == [
        ["mc.csv", "6", "linea_invalida", "1,2,3" + "," * 30],
        ["mc.csv", "4", "fecha_invalida", "06/05/2025"],
        ["mc.csv", "5", "codigo_invalido", "X1"],
    ]


def test_sin_ninguna_fecha_es_cero_filas_y_no_escribe_nada(
    procesador: MediosPagoReportes, fabrica: Fabrica, tmp_path: Path
) -> None:
    entrada = fabrica("mc.csv", csv_izipay("mastercard", [fila_izipay("mastercard", "")]))
    with pytest.raises(ErrorContenido) as error:
        procesador.procesar([entrada])
    assert error.value.contexto == {"archivo": "mc.csv", "motivo": "cero_filas", "columna": None}
    assert sorted(p.name for p in tmp_path.iterdir()) == ["entrada_0"]


# --- Emulación de pandas ------------------------------------------------------------


def test_la_inferencia_es_por_tramos_como_low_memory() -> None:
    """Enteros en un tramo y texto en otro: cada valor conserva el tipo de su
    tramo (`0123` se vuelve 123 sólo en el primero)."""
    assert _filas_por_tramo(26) == 32768
    tipo, valores = _inferir_columna(["0123", "7", "x", "0123"], 2)
    assert (tipo, valores) == ("object", [123, 7, "x", "0123"])
    assert _inferir_columna(["1", None, "2", "3"], 2) == ("float", [1.0, None, 2.0, 3.0])
    assert _inferir_columna(["True", "False"], 2) == ("bool", [True, False])


@pytest.mark.parametrize(
    ("valor", "redondeado"),
    [(2.675, 2.68), (0.125, 0.12), (1554.64, 1554.64), (7, 7), (None, None)],
)
def test_redondear2_es_el_de_numpy(valor: float | None, redondeado: float | None) -> None:
    assert redondear2(valor) == redondeado


# --- SafetyPay ---------------------------------------------------------------------


def test_safetypay_un_libro_por_fecha_con_sus_columnas(
    procesador: MediosPagoReportes, fabrica: Fabrica
) -> None:
    libro = libro_safetypay(
        [
            fila_safetypay(fecha_safetypay(date(2025, 5, 27)), **{"Transaction ID": "1"}),
            fila_safetypay(fecha_safetypay(date(2025, 5, 26)), **{"Transaction ID": "2"}),
            fila_safetypay(fecha_safetypay(date(2025, 5, 27)), **{"Transaction ID": "3"}),
        ]
    )
    salidas = _procesar(procesador, fabrica("MPFinancialReport (1).xlsx", libro))
    assert list(salidas) == ["2025-05-26-SafetyPay.xlsx", "2025-05-27-SafetyPay.xlsx"]
    filas = leer_xlsx(salidas["2025-05-27-SafetyPay.xlsx"])
    assert filas[0] == [
        "Purchase Complete Date (GMT Merchant)",
        "Payment Batch Number",
        "Operation ID",
        "Transaction ID",
        "Merchant Sales ID",
        "Merchant Order Number",
        "Sale Amount",
        "SafetyPay Commission ",
        "Net To Merchant",
    ]
    assert filas[1] == [
        "05/22/2025 22:48:25",
        177614,
        "0125143389223723",
        "1",
        "00000000000000390223",
        "00000000000000390223",
        20,
        0.3,
        19.65,
    ]
    assert [f[3] for f in filas[1:]] == ["1", "3"]
    titulo = celdas_xlsx(salidas["2025-05-27-SafetyPay.xlsx"])[0][0]
    assert (titulo.font.b, titulo.border.left.style, titulo.alignment.horizontal) == (
        True,
        "thin",
        "center",
    )


def test_safetypay_fecha_ilegible_se_reporta_y_el_pie_no(
    procesador: MediosPagoReportes, fabrica: Fabrica
) -> None:
    libro = libro_safetypay(
        [fila_safetypay(fecha_safetypay(date(2025, 5, 26))), fila_safetypay("el lunes")]
    )
    salidas = _procesar(procesador, fabrica("MPFinancialReport.xlsx", libro))
    assert _observaciones(salidas[NOMBRE_OBSERVACIONES]) == [
        ["MPFinancialReport.xlsx", "9", "fecha_invalida", "el lunes"],
    ]


def test_safetypay_acepta_fechas_reales_de_excel(
    procesador: MediosPagoReportes, fabrica: Fabrica
) -> None:
    libro = libro_safetypay([fila_safetypay(datetime(2025, 5, 26, 10, 0))])
    salidas = _procesar(procesador, fabrica("MPFinancialReport.xlsx", libro))
    assert list(salidas) == ["2025-05-26-SafetyPay.xlsx"]


def test_safetypay_sin_columna_de_fecha_es_columna_faltante(
    procesador: MediosPagoReportes, fabrica: Fabrica
) -> None:
    titulos = [t for t in TITULOS_SAFETYPAY if t != "Merchant Settlement Date"]
    libro = libro_safetypay([fila_safetypay("x")], titulos=titulos)
    error = _error(procesador, fabrica("MPFinancialReport.xlsx", libro))
    assert error.contexto == {
        "archivo": "MPFinancialReport.xlsx",
        "motivo": "columna_faltante",
        "columna": "Merchant Settlement Date",
    }
    assert _error(procesador, fabrica("reporte.xlsx", libro)).contexto["motivo"] == (
        "tipo_no_reconocido"
    )


# --- De punta a punta, por la ruta real y el proceso hijo ---------------------


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

    def test_reportes_mixtos_vuelven_en_un_zip(self, token_sentinela: str) -> None:
        from fastapi.testclient import TestClient

        from app.main import crear_app

        with TestClient(crear_app()) as cliente:
            respuesta = self._subir(
                cliente,
                [
                    ("movi_amex.csv", csv_izipay("amex", [fila_izipay("amex", "20250510")])),
                    (
                        "MPFinancialReport.xlsx",
                        libro_safetypay([fila_safetypay(fecha_safetypay(date(2025, 5, 26)))]),
                    ),
                ],
            )

        assert respuesta.status_code == 200, respuesta.text
        assert respuesta.headers["content-type"] == "application/zip"
        with zipfile.ZipFile(io.BytesIO(respuesta.content)) as contenedor:
            assert contenedor.namelist() == [
                "2025-05-12-amex-izipay.csv",
                "2025-05-26-SafetyPay.xlsx",
            ]

    def test_un_archivo_desconocido_es_422(self, token_sentinela: str) -> None:
        from fastapi.testclient import TestClient

        from app.main import crear_app

        with TestClient(crear_app()) as cliente:
            respuesta = self._subir(cliente, [("otro.csv", b"a,b\n1,2\n")])

        assert respuesta.status_code == 422
        assert respuesta.json()["contexto"] == {
            "archivo": "otro.csv",
            "motivo": "tipo_no_reconocido",
            "columna": None,
        }
