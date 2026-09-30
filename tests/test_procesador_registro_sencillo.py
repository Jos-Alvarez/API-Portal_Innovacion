"""Pruebas del procesador `Registro_Sencillo` (transferencias de peaje sencillo).

El extracto real no está en este repositorio y no puede estarlo (ADR 0015),
así que estas pruebas arman libros sintéticos con `openpyxl`, guardados sin
extensión (`entrada_0`) como los temporales reales de `app/recepcion.py`.
Prueban las **reglas**; la paridad es `tests/paridad/test_registro_sencillo.py`.

El TXT es la única salida del módulo, así que las pruebas leen el TXT: cada
celda como texto, en el formato que el script volcaba.
"""

from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest
from openpyxl import Workbook

from app.core.errores import ErrorContenido, TipoError
from app.core.tipos import ArchivoEntrada
from app.procesadores.registro_sencillo.modulo import (
    COLUMNAS,
    FIN_DE_LINEA,
    GLOSA_BBVA,
    GLOSA_IBK,
    GLOSA_POR_DEFECTO,
    MOTIVO_BANCO_ENTRADA,
    MOTIVO_FECHA_CONTABLE,
    MOTIVO_FECHA_DOCUMENTO,
    NOMBRE_DESCARTES,
    NOMBRE_TXT,
    RegistroSencillo,
    _celda_de_txt,
)

_SALIDA = 1101017075
_ENTRADA = 1101017016

_ENCABEZADO = [
    COLUMNAS.banco_salida,
    COLUMNAS.banco_entrada,
    COLUMNAS.fecha_documento,
    COLUMNAS.fecha_contable,
    COLUMNAS.importe_salida,
    "IMPORTE ENTRADA",
]


def _fila(
    *,
    salida: object = _SALIDA,
    entrada: object = _ENTRADA,
    documento: object = "01.09.2026",
    contable: object = "11.10.2026",
    importe_salida: object = 63000,
    importe_entrada: object = 63000,
) -> list[object]:
    return [salida, entrada, documento, contable, importe_salida, importe_entrada]


def _libro(tmp_path: Path, filas: list[list[object]], encabezado: list[str] | None = None) -> Path:
    """Guarda el libro SIN extensión, como `app/recepcion.py` guarda los temporales."""
    ruta = tmp_path / "entrada_0"
    libro = Workbook()
    hoja = libro.active
    assert hoja is not None
    hoja.append(encabezado if encabezado is not None else _ENCABEZADO)
    for fila in filas:
        hoja.append(fila)
    with ruta.open("wb") as destino:
        libro.save(destino)
    return ruta


def _entrada(ruta: Path, nombre: str = "transferencias.xlsx") -> ArchivoEntrada:
    return ArchivoEntrada(
        nombre_original=nombre,
        ruta_temporal=ruta,
        tamano_comprimido=ruta.stat().st_size,
        formato="xlsx",
    )


def _salidas_por_nombre(procesador: RegistroSencillo, entrada: ArchivoEntrada) -> dict[str, Path]:
    return {s.nombre_propuesto: s.ruta_temporal for s in procesador.procesar([entrada])}


def _filas_txt(ruta: Path) -> list[list[str]]:
    with ruta.open(encoding="utf-8", newline="") as archivo:
        return list(csv.reader(archivo, delimiter="\t", lineterminator="\r\n"))


def _procesar(
    procesador: RegistroSencillo,
    tmp_path: Path,
    filas: list[list[object]],
    encabezado: list[str] | None = None,
) -> list[list[str]]:
    ruta = _libro(tmp_path, filas, encabezado=encabezado)
    return _filas_txt(_salidas_por_nombre(procesador, _entrada(ruta))[NOMBRE_TXT])


@pytest.fixture
def procesador() -> RegistroSencillo:
    return RegistroSencillo()


# --- El camino feliz y el layout de las tres líneas --------------------------


def test_un_registro_produce_cuatro_filas_de_26_columnas(
    procesador: RegistroSencillo, tmp_path: Path
) -> None:
    """Cabecera, salida, entrada y separadora. Sin línea de comisión."""
    filas = _procesar(procesador, tmp_path, [_fila()])
    assert len(filas) == 4
    assert all(len(f) == 26 for f in filas)


def test_el_layout_de_las_tres_lineas_es_el_del_script(
    procesador: RegistroSencillo, tmp_path: Path
) -> None:
    """Las posiciones exactas. Es la regla de negocio, no un detalle de formato."""
    cabecera, salida, entrada, separadora = _procesar(procesador, tmp_path, [_fila()])

    assert cabecera[:12] == [
        "1",
        "",
        "VPR1",
        "",
        "2026",
        "SA",
        "20260901",  # fecha documento
        "20261011",  # fecha contable
        "10",  # el mes sale de la contable
        "",
        "PEAJE SENCILLO",
        "PEN",
    ]
    assert cabecera[12:] == [""] * 14

    ocupadas = {0, 12, 13, 17, 25}
    for linea, clave, banco in ((salida, "50", _SALIDA), (entrada, "40", _ENTRADA)):
        assert [linea[0], linea[12], linea[13], linea[17], linea[25]] == [
            "2",
            clave,
            str(banco),
            "63000.0",
            GLOSA_POR_DEFECTO,
        ]
        assert all(linea[i] == "" for i in range(26) if i not in ocupadas)
    assert separadora == [""] * 26


def test_el_anio_sale_del_documento_y_el_mes_de_la_contable(
    procesador: RegistroSencillo, tmp_path: Path
) -> None:
    """Rareza del script conservada: en un cruce de año se nota."""
    fila = _fila(documento="31.12.2025", contable="02.01.2026")
    cabecera = _procesar(procesador, tmp_path, [fila])[0]
    assert cabecera[4] == "2025"
    assert cabecera[6] == "20251231"
    assert cabecera[7] == "20260102"
    assert cabecera[8] == "01"


def test_las_dos_lineas_usan_el_importe_de_salida(
    procesador: RegistroSencillo, tmp_path: Path
) -> None:
    """IMPORTE ENTRADA no se lee: las líneas 50 y 40 llevan IMPORTE SALIDA."""
    filas = _procesar(procesador, tmp_path, [_fila(importe_salida=1500, importe_entrada=999)])
    assert filas[1][17] == "1500.0"
    assert filas[2][17] == "1500.0"


def test_importe_entrada_no_es_obligatorio(procesador: RegistroSencillo, tmp_path: Path) -> None:
    """Sin la columna IMPORTE ENTRADA el libro se valida y se procesa igual."""
    encabezado = _ENCABEZADO[:5]
    ruta = _libro(tmp_path, [_fila()[:5]], encabezado=encabezado)
    assert procesador.validar([_entrada(ruta)]) is None
    filas = _filas_txt(_salidas_por_nombre(procesador, _entrada(ruta))[NOMBRE_TXT])
    assert filas[1][17] == "63000.0"


def test_los_importes_salen_positivos_y_redondeados(
    procesador: RegistroSencillo, tmp_path: Path
) -> None:
    filas = _procesar(procesador, tmp_path, [_fila(importe_salida=-1000.456)])
    assert filas[1][17] == "1000.46"
    assert filas[2][17] == "1000.46"


@pytest.mark.parametrize(
    ("crudo", "esperado"),
    [("1,234.56", "1234.56"), (None, "0.0"), ("NA", "0.0"), ("no es un número", "0.0")],
)
def test_el_importe_se_limpia_como_el_script(
    procesador: RegistroSencillo, tmp_path: Path, crudo: object, esperado: str
) -> None:
    """`limpiar_monto`: quita comas; nulo o no parseable vale cero, sin descarte."""
    filas = _procesar(procesador, tmp_path, [_fila(importe_salida=crudo)])
    assert filas[1][17] == esperado
    assert filas[2][17] == esperado


def test_un_banco_float_se_vuelca_como_entero(procesador: RegistroSencillo, tmp_path: Path) -> None:
    """`int(banco) if isinstance(banco, float)`: trunca, y el TXT no lleva decimales."""
    filas = _procesar(procesador, tmp_path, [_fila(salida=1101017075.7, entrada=1101017016.2)])
    assert filas[1][13] == "1101017075"
    assert filas[2][13] == "1101017016"


def test_varios_registros_se_encadenan_en_orden(
    procesador: RegistroSencillo, tmp_path: Path
) -> None:
    filas = _procesar(
        procesador,
        tmp_path,
        [_fila(), _fila(salida=1101017085), _fila(salida=1101017005)],
    )
    assert len(filas) == 3 * 4
    assert [filas[i][13] for i in (1, 5, 9)] == ["1101017075", "1101017085", "1101017005"]


# --- La glosa ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("salida", "entrada", "glosa"),
    [
        (1101015005, _ENTRADA, GLOSA_IBK),
        (1101015055, _ENTRADA, GLOSA_BBVA),
        (_SALIDA, 1101015006, GLOSA_IBK),
        (_SALIDA, 1101015056, GLOSA_BBVA),
        (_SALIDA, _ENTRADA, GLOSA_POR_DEFECTO),
    ],
)
def test_cada_rama_de_la_glosa(
    procesador: RegistroSencillo, tmp_path: Path, salida: int, entrada: int, glosa: str
) -> None:
    """La glosa va en la columna 25 de las DOS líneas de detalle, no en la cabecera."""
    filas = _procesar(procesador, tmp_path, [_fila(salida=salida, entrada=entrada)])
    assert filas[1][25] == glosa
    assert filas[2][25] == glosa
    assert filas[0][25] == ""


def test_la_regla_del_banco_de_salida_gana_sobre_la_de_entrada(
    procesador: RegistroSencillo, tmp_path: Path
) -> None:
    """Salida IBK con entrada BBVA: gana la salida, porque se evalúa primero."""
    filas = _procesar(procesador, tmp_path, [_fila(salida=1101015005, entrada=1101015056)])
    assert filas[1][25] == GLOSA_IBK

    filas = _procesar(procesador, tmp_path, [_fila(salida=1101015055, entrada=1101015006)])
    assert filas[1][25] == GLOSA_BBVA


def test_la_glosa_compara_con_el_banco_ya_truncado(
    procesador: RegistroSencillo, tmp_path: Path
) -> None:
    """El script convierte el `float` a `int` ANTES de comparar."""
    filas = _procesar(procesador, tmp_path, [_fila(salida=1101015005.4)])
    assert filas[1][25] == GLOSA_IBK


def test_un_banco_de_texto_no_coincide_con_ninguna_regla(
    procesador: RegistroSencillo, tmp_path: Path
) -> None:
    """Igualdad numérica, como en pandas: `"1101015005" == 1101015005` es falso."""
    filas = _procesar(procesador, tmp_path, [_fila(salida="1101015005", entrada="1101015056")])
    assert filas[1][13] == "1101015005"
    assert filas[1][25] == GLOSA_POR_DEFECTO


# --- Columnas por nombre -----------------------------------------------------


@pytest.mark.parametrize(
    "faltante",
    [
        COLUMNAS.banco_salida,
        COLUMNAS.banco_entrada,
        COLUMNAS.fecha_documento,
        COLUMNAS.fecha_contable,
        COLUMNAS.importe_salida,
    ],
)
def test_falta_una_columna_obligatoria(
    procesador: RegistroSencillo, tmp_path: Path, faltante: str
) -> None:
    encabezado = [c for c in _ENCABEZADO if c != faltante]
    error = procesador.validar([_entrada(_libro(tmp_path, [], encabezado=encabezado))])
    assert isinstance(error, ErrorContenido)
    assert error.tipo is TipoError.CONTENIDO
    assert error.contexto == {
        "archivo": "transferencias.xlsx",
        "motivo": "columna_faltante",
        "columna": faltante,
    }


def test_una_columna_insertada_no_corre_la_lectura(
    procesador: RegistroSencillo, tmp_path: Path
) -> None:
    encabezado = ["Columna nueva", *_ENCABEZADO]
    filas = _procesar(procesador, tmp_path, [["basura", *_fila()]], encabezado=encabezado)
    assert filas[1][13] == str(_SALIDA)


def test_los_encabezados_se_comparan_tras_strip(
    procesador: RegistroSencillo, tmp_path: Path
) -> None:
    encabezado = [f"  {c} " for c in _ENCABEZADO]
    ruta = _libro(tmp_path, [_fila()], encabezado=encabezado)
    assert procesador.validar([_entrada(ruta)]) is None


# --- TXT: formato y fin de línea ---------------------------------------------


def test_el_txt_usa_crlf_explicito_y_utf8(procesador: RegistroSencillo, tmp_path: Path) -> None:
    salidas = _salidas_por_nombre(procesador, _entrada(_libro(tmp_path, [_fila(), _fila()])))
    crudo = salidas[NOMBRE_TXT].read_bytes()
    assert FIN_DE_LINEA.encode() == b"\r\n"
    assert crudo.endswith(b"\r\n")
    assert crudo.count(b"\r\n") == 8
    assert b"\n" not in crudo.replace(b"\r\n", b"")
    crudo.decode("utf-8")


@pytest.mark.parametrize(
    ("celda", "esperado"),
    [
        ("", ""),
        (63000.0, "63000.0"),
        (2000000000.0, "2000000000"),
        (1101015005, "1101015005"),
        (4.3, "4.3"),
        ("texto", "texto"),
    ],
)
def test_formateo_de_celda_del_txt(celda: object, esperado: str) -> None:
    assert _celda_de_txt(celda) == esperado


# --- Fechas ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("crudo", "esperado"),
    [
        ("01.09.2026", "20260901"),
        ("13/02/2026", "20260213"),
        ("13-02-2026", "20260213"),
        ("2026-02-13", "20260213"),
        ("01.02.2026", "20260201"),  # día primero: 1 de febrero
        (datetime(2026, 2, 13, 10, 30), "20260213"),
        (date(2026, 2, 13), "20260213"),
    ],
)
def test_fechas_se_leen_con_el_dia_primero(
    procesador: RegistroSencillo, tmp_path: Path, crudo: object, esperado: str
) -> None:
    cabecera = _procesar(procesador, tmp_path, [_fila(documento=crudo, contable=crudo)])[0]
    assert cabecera[6] == esperado
    assert cabecera[7] == esperado


# --- Descartes ---------------------------------------------------------------


def test_sin_descartes_la_salida_es_solo_el_txt(
    procesador: RegistroSencillo, tmp_path: Path
) -> None:
    salidas = _salidas_por_nombre(procesador, _entrada(_libro(tmp_path, [_fila()])))
    assert list(salidas) == [NOMBRE_TXT]


@pytest.mark.parametrize(
    ("fila", "motivo", "valor"),
    [
        (_fila(entrada=None), MOTIVO_BANCO_ENTRADA, ""),
        (_fila(entrada="NA"), MOTIVO_BANCO_ENTRADA, "NA"),
        (_fila(documento="no es fecha"), MOTIVO_FECHA_DOCUMENTO, "no es fecha"),
        (_fila(documento=None), MOTIVO_FECHA_DOCUMENTO, ""),
        (_fila(documento=45000), MOTIVO_FECHA_DOCUMENTO, "45000"),
        (_fila(contable="32.01.2026"), MOTIVO_FECHA_CONTABLE, "32.01.2026"),
    ],
)
def test_cada_descarte_se_reporta_con_motivo_fila_y_valor(
    procesador: RegistroSencillo, tmp_path: Path, fila: list[object], motivo: str, valor: str
) -> None:
    salidas = _salidas_por_nombre(procesador, _entrada(_libro(tmp_path, [_fila(), fila])))
    assert list(salidas) == [NOMBRE_TXT, NOMBRE_DESCARTES]
    reporte = salidas[NOMBRE_DESCARTES].read_bytes().decode("utf-8")
    lineas = reporte.split("\r\n")
    assert lineas[0] == f"Filas descartadas: 1 ({motivo}=1)"
    assert lineas[2] == "fila\tmotivo\tvalor"
    assert lineas[3] == f"3\t{motivo}\t{valor}"  # la fila 3 del Excel
    assert reporte.endswith("\r\n")
    # La fila válida sigue saliendo.
    assert len(_filas_txt(salidas[NOMBRE_TXT])) == 4


def test_el_banco_entrada_se_revisa_antes_que_las_fechas(
    procesador: RegistroSencillo, tmp_path: Path
) -> None:
    """Mismo orden que el script: un solo motivo por fila, el primero que falla."""
    fila = _fila(entrada=None, documento="mal", contable="mal")
    salidas = _salidas_por_nombre(procesador, _entrada(_libro(tmp_path, [_fila(), fila])))
    reporte = salidas[NOMBRE_DESCARTES].read_text(encoding="utf-8")
    assert reporte.splitlines()[0] == f"Filas descartadas: 1 ({MOTIVO_BANCO_ENTRADA}=1)"


def test_el_reporte_cuenta_por_motivo(procesador: RegistroSencillo, tmp_path: Path) -> None:
    filas = [
        _fila(),
        _fila(entrada=None),
        _fila(documento="x"),
        _fila(contable="y"),
        _fila(contable="z"),
    ]
    salidas = _salidas_por_nombre(procesador, _entrada(_libro(tmp_path, filas)))
    reporte = salidas[NOMBRE_DESCARTES].read_text(encoding="utf-8")
    assert reporte.splitlines()[0] == (
        f"Filas descartadas: 4 ({MOTIVO_BANCO_ENTRADA}=1, "
        f"{MOTIVO_FECHA_CONTABLE}=2, {MOTIVO_FECHA_DOCUMENTO}=1)"
    )


def test_el_descarte_se_registra_en_el_log(
    procesador: RegistroSencillo, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    filas = [_fila(), _fila(), _fila(documento="mal")]
    with caplog.at_level("INFO", logger="app"):
        procesador.procesar([_entrada(_libro(tmp_path, filas))])

    (registro,) = [r for r in caplog.records if getattr(r, "evento", None) == "descartes"]
    assert registro.clave == "registro-sencillo"  # type: ignore[attr-defined]
    assert registro.filas_descartadas == 1  # type: ignore[attr-defined]
    assert registro.filas_procesadas == 2  # type: ignore[attr-defined]
    assert registro.por_motivo == {MOTIVO_FECHA_DOCUMENTO: 1}  # type: ignore[attr-defined]


def test_sin_descartes_no_se_registra_nada(
    procesador: RegistroSencillo, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("INFO", logger="app"):
        procesador.procesar([_entrada(_libro(tmp_path, [_fila()]))])
    assert not [r for r in caplog.records if getattr(r, "evento", None) == "descartes"]


@pytest.mark.parametrize("vacio", [None, "", "NA"])
def test_las_filas_sin_banco_salida_se_filtran_sin_contar(
    procesador: RegistroSencillo, tmp_path: Path, vacio: object
) -> None:
    """El filtro previo del script (columna A vacía) no es un descarte: es ruido."""
    filas = [_fila(), _fila(salida=vacio, documento="basura")]
    salidas = _salidas_por_nombre(procesador, _entrada(_libro(tmp_path, filas)))
    assert NOMBRE_DESCARTES not in salidas
    assert len(_filas_txt(salidas[NOMBRE_TXT])) == 4


# --- Cero filas y archivos ilegibles -----------------------------------------


def test_cero_filas_procesadas_es_error_de_contenido(
    procesador: RegistroSencillo, tmp_path: Path
) -> None:
    ruta = _libro(tmp_path, [_fila(documento="mal"), _fila(salida=None)])
    with pytest.raises(ErrorContenido) as capturado:
        procesador.procesar([_entrada(ruta)])
    assert capturado.value.contexto == {
        "archivo": "transferencias.xlsx",
        "motivo": "cero_filas",
        "columna": None,
    }
    assert sorted(p.name for p in tmp_path.iterdir()) == ["entrada_0"]  # nada escrito


def test_solo_encabezado_es_cero_filas(procesador: RegistroSencillo, tmp_path: Path) -> None:
    with pytest.raises(ErrorContenido) as capturado:
        procesador.procesar([_entrada(_libro(tmp_path, []))])
    assert capturado.value.contexto["motivo"] == "cero_filas"


def test_un_excel_ilegible_es_error_de_contenido(
    procesador: RegistroSencillo, tmp_path: Path
) -> None:
    ruta = tmp_path / "entrada_0"
    ruta.write_bytes(b"esto no es un xlsx")
    error = procesador.validar([_entrada(ruta)])
    assert isinstance(error, ErrorContenido)
    assert error.contexto["motivo"] == "cero_filas"
    with pytest.raises(ErrorContenido):
        procesador.procesar([_entrada(ruta)])


def test_una_fila_que_rompe_no_se_traga(
    procesador: RegistroSencillo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El script tenía `except Exception: continue`. Acá se propaga."""
    import app.procesadores.registro_sencillo.modulo as modulo

    def _explota(*_args: Any, **_kwargs: Any) -> float:
        raise RuntimeError("importe imposible")

    monkeypatch.setattr(modulo, "_a_importe", _explota)
    with pytest.raises(RuntimeError, match="importe imposible"):
        procesador.procesar([_entrada(_libro(tmp_path, [_fila()]))])


# --- Coherencia con el registro ----------------------------------------------


def test_la_clave_coincide_con_el_registry() -> None:
    from app.core.contrato import obtener_contrato
    from app.registry import REGISTRY

    procesador = REGISTRY["registro-sencillo"]
    assert procesador.clave == "registro-sencillo"
    assert isinstance(procesador, RegistroSencillo)

    contrato = obtener_contrato("registro-sencillo")
    assert contrato is not None
    assert contrato.entradas_min == 1
    assert contrato.entradas_max == 1
    assert "xlsx" in contrato.formatos_aceptados


# --- De punta a punta, por la ruta real y el proceso hijo --------------------


class TestPuntaAPunta:
    """La tubería completa: HTTP → temporal sin extensión → `spawn` → respuesta.

    Obligatoria para todo procesador nuevo (ver `test_procesador_contado_carga`):
    el temporal sin extensión es una trampa estructural que sólo se ve acá.
    Con una entrada limpia hay UNA salida y viaja suelta, sin ZIP.
    """

    @staticmethod
    def _subir(cliente: Any, contenido: bytes) -> Any:
        return cliente.post(
            "/interno/procesadores/registro-sencillo",
            files={"archivos": ("transferencias.xlsx", contenido, "application/octet-stream")},
            headers={"Authorization": "Bearer sentinela-token-de-pruebas-3f9c2a"},
        )

    @staticmethod
    def _bytes_de_libro(filas: list[list[object]]) -> bytes:
        import io

        libro = Workbook()
        hoja = libro.active
        assert hoja is not None
        hoja.append(_ENCABEZADO)
        for fila in filas:
            hoja.append(fila)
        memoria = io.BytesIO()
        libro.save(memoria)
        return memoria.getvalue()

    def test_un_excel_legitimo_vuelve_como_el_txt_suelto(self, token_sentinela: str) -> None:
        from fastapi.testclient import TestClient

        from app.main import crear_app

        with TestClient(crear_app()) as cliente:
            respuesta = self._subir(cliente, self._bytes_de_libro([_fila()]))

        assert respuesta.status_code == 200, respuesta.text
        assert NOMBRE_TXT in respuesta.headers["content-disposition"]
        assert not respuesta.content.startswith(b"PK")  # no es un ZIP
        assert respuesta.content.count(b"\r\n") == 4
        assert b"PEAJE SENCILLO" in respuesta.content

    def test_el_descarte_viaja_en_el_zip(self, token_sentinela: str) -> None:
        import io
        import zipfile

        from fastapi.testclient import TestClient

        from app.main import crear_app

        filas = [_fila(), _fila(contable="fecha rota")]
        with TestClient(crear_app()) as cliente:
            respuesta = self._subir(cliente, self._bytes_de_libro(filas))

        assert respuesta.status_code == 200, respuesta.text
        with zipfile.ZipFile(io.BytesIO(respuesta.content)) as paquete:
            assert sorted(paquete.namelist()) == sorted((NOMBRE_TXT, NOMBRE_DESCARTES))
            assert b"fecha rota" in paquete.read(NOMBRE_DESCARTES)

    def test_un_archivo_que_no_es_excel_es_422(self, token_sentinela: str) -> None:
        from fastapi.testclient import TestClient

        from app.main import crear_app

        with TestClient(crear_app()) as cliente:
            respuesta = self._subir(cliente, b"esto no es un xlsx")

        assert respuesta.status_code == 422
        assert respuesta.json()["tipo"] == "contenido"
