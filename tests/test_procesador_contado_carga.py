"""Pruebas del procesador `Contado_Carga` (ítem #16).

Los tres pares reales no están en este repositorio y no pueden estarlo (ADR
0015), así que estas pruebas arman libros sintéticos con `openpyxl`. Prueban
las **reglas**, no la paridad: la paridad es `tests/paridad/test_contado_carga.py`
y hoy saltea porque los pares no se produjeron todavía.

El eje de lo que se verifica es el endurecimiento obligatorio del PRD, que es
justo donde el módulo migrado tiene permiso —y obligación— de comportarse
distinto del script viejo.
"""

from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest
from openpyxl import Workbook, load_workbook

from app.core.errores import ErrorContenido, TipoError
from app.core.tipos import ArchivoEntrada
from app.procesadores.contado_carga.modulo import (
    COLUMNAS,
    FIN_DE_LINEA,
    HOJA_DE_SALIDA,
    MAPEO_PLAZAS,
    MOTIVO_FECHA,
    MOTIVO_PLAZA,
    NOMBRE_DESCARTES,
    NOMBRE_TXT,
    NOMBRE_XLSX,
    ContadoCarga,
    _a_importe,
    _celda_de_txt,
)

_PLAZA = "PROSEGUR - P5 - El Pino"
_CUENTA = 1101017094

_ENCABEZADO = [
    COLUMNAS.fecha_contabilizacion,
    COLUMNAS.fecha_documento,
    "Columna que no le importa a nadie",
    COLUMNAS.referencia,
    COLUMNAS.importe,
    COLUMNAS.texto,
    COLUMNAS.fecha_entrada,
]


def _fila(
    *,
    contabilizacion: object = datetime(2026, 3, 14),
    documento: object = datetime(2026, 3, 10),
    referencia: object = 4500001234,
    importe: object = -1250.5,
    texto: object = _PLAZA,
    entrada: object = datetime(2026, 3, 12),
) -> list[object]:
    return [contabilizacion, documento, "ruido", referencia, importe, texto, entrada]


def _libro(tmp_path: Path, filas: list[list[object]], encabezado: list[str] | None = None) -> Path:
    ruta = tmp_path / "contado.xlsx"
    libro = Workbook()
    hoja = libro.active
    assert hoja is not None
    hoja.append(encabezado if encabezado is not None else _ENCABEZADO)
    for fila in filas:
        hoja.append(fila)
    libro.save(ruta)
    return ruta


def _entrada(ruta: Path, nombre: str = "contado.xlsx") -> ArchivoEntrada:
    return ArchivoEntrada(
        nombre_original=nombre,
        ruta_temporal=ruta,
        tamano_comprimido=ruta.stat().st_size,
        formato="xlsx",
    )


def _salidas_por_nombre(procesador: ContadoCarga, entrada: ArchivoEntrada) -> dict[str, Path]:
    return {s.nombre_propuesto: s.ruta_temporal for s in procesador.procesar([entrada])}


@pytest.fixture
def procesador() -> ContadoCarga:
    return ContadoCarga()


# --- El camino feliz y el layout de las cuatro filas -------------------------


def test_un_registro_produce_cuatro_filas(procesador: ContadoCarga, tmp_path: Path) -> None:
    """Tres líneas de datos más la separadora en blanco, de 26 columnas cada una."""
    entrada = _entrada(_libro(tmp_path, [_fila()]))
    salidas = _salidas_por_nombre(procesador, entrada)

    hoja = load_workbook(salidas[NOMBRE_XLSX]).worksheets[0]
    filas = [list(f) for f in hoja.iter_rows(values_only=True)]
    assert len(filas) == 4
    assert all(len(f) == 26 for f in filas)
    assert hoja.title == HOJA_DE_SALIDA


def test_el_layout_de_las_tres_lineas_es_el_del_script(
    procesador: ContadoCarga, tmp_path: Path
) -> None:
    """Las posiciones exactas. Es la regla de negocio, no un detalle de formato."""
    entrada = _entrada(_libro(tmp_path, [_fila()]))
    salidas = _salidas_por_nombre(procesador, entrada)
    filas = [
        list(f)
        for f in load_workbook(salidas[NOMBRE_XLSX]).worksheets[0].iter_rows(values_only=True)
    ]

    cabecera, linea2, linea3, separadora = filas
    assert cabecera[0] == 1
    assert cabecera[2] == "VPR1"
    assert cabecera[4] == 2026  # el año sale de Fe.contabilización
    assert cabecera[5] == "DZ"
    assert cabecera[6] == "20260310"  # fecha de documento
    assert cabecera[7] == "20260314"  # fecha de contabilización
    assert cabecera[8] == "03"
    assert cabecera[9] == "4500001234"
    assert cabecera[10] == _PLAZA
    assert cabecera[11] == "PEN"

    assert [linea2[0], linea2[12], linea2[13], linea2[17], linea2[25]] == [
        2,
        15,
        1001530,
        1250.5,  # round(abs(-1250.5), 2): el importe sale SIEMPRE positivo
        _PLAZA,
    ]
    assert [linea3[0], linea3[12], linea3[13], linea3[17], linea3[25]] == [
        2,
        40,
        _CUENTA,
        1250.5,
        _PLAZA,
    ]
    assert all(celda is None or celda == "" for celda in separadora)


def test_la_fecha_de_entrada_no_aparece_en_la_salida(
    procesador: ContadoCarga, tmp_path: Path
) -> None:
    """Se exige válida y se descarta: es un filtro, no un dato (ver docstring del módulo)."""
    entrada = _entrada(_libro(tmp_path, [_fila(entrada=datetime(2026, 12, 25))]))
    salidas = _salidas_por_nombre(procesador, entrada)
    contenido = salidas[NOMBRE_TXT].read_text(encoding="utf-8")
    assert "20261225" not in contenido
    assert "20260314" in contenido  # la de contabilización sí está


def test_cada_plaza_mapea_a_su_cuenta(procesador: ContadoCarga, tmp_path: Path) -> None:
    """Las diez, con su texto exacto. Un typo en el mapeo descarta filas en producción."""
    filas = [_fila(texto=plaza) for plaza in MAPEO_PLAZAS]
    entrada = _entrada(_libro(tmp_path, filas))
    salidas = _salidas_por_nombre(procesador, entrada)
    hoja = load_workbook(salidas[NOMBRE_XLSX]).worksheets[0]
    todas = [list(f) for f in hoja.iter_rows(values_only=True)]

    cuentas = [todas[indice * 4 + 2][13] for indice in range(len(MAPEO_PLAZAS))]
    assert cuentas == list(MAPEO_PLAZAS.values())


# --- Endurecimiento 1: columnas por nombre ----------------------------------


def test_falta_una_columna_obligatoria(procesador: ContadoCarga, tmp_path: Path) -> None:
    """El modo de fallo que motiva la regla: alguien INSERTA una columna."""
    encabezado = [c for c in _ENCABEZADO if c != COLUMNAS.importe]
    entrada = _entrada(_libro(tmp_path, [], encabezado=encabezado))

    error = procesador.validar([entrada])
    assert isinstance(error, ErrorContenido)
    assert error.tipo is TipoError.CONTENIDO
    assert error.contexto == {
        "archivo": "contado.xlsx",
        "motivo": "columna_faltante",
        "columna": COLUMNAS.importe,
    }


def test_una_columna_insertada_no_corre_la_lectura(
    procesador: ContadoCarga, tmp_path: Path
) -> None:
    """Con lectura por nombre, insertar una columna al principio es inocuo.

    Leyendo por posición —lo que hacía el script— esto producía salida
    incorrecta sin fallar, que es exactamente el riesgo que el PRD nombra.
    """
    encabezado = ["Columna nueva del ERP", *_ENCABEZADO]
    filas = [["basura", *_fila()]]
    entrada = _entrada(_libro(tmp_path, filas, encabezado=encabezado))

    assert procesador.validar([entrada]) is None
    salidas = _salidas_por_nombre(procesador, entrada)
    cabecera = list(load_workbook(salidas[NOMBRE_XLSX]).worksheets[0].iter_rows(values_only=True))[
        0
    ]
    assert cabecera[10] == _PLAZA


# --- Endurecimiento 2: fin de línea explícito -------------------------------


def test_el_txt_usa_crlf_explicito(procesador: ContadoCarga, tmp_path: Path) -> None:
    """Sin heredar de la plataforma: se comprueba sobre los BYTES, no sobre texto."""
    entrada = _entrada(_libro(tmp_path, [_fila()]))
    salidas = _salidas_por_nombre(procesador, entrada)

    crudo = salidas[NOMBRE_TXT].read_bytes()
    assert FIN_DE_LINEA.encode() == b"\r\n"
    assert crudo.endswith(b"\r\n")
    assert crudo.count(b"\r\n") == 4
    assert b"\n" not in crudo.replace(b"\r\n", b"")  # ningún LF suelto


def test_el_txt_es_utf8_y_separado_por_tabulaciones(
    procesador: ContadoCarga, tmp_path: Path
) -> None:
    entrada = _entrada(_libro(tmp_path, [_fila(texto="PROSEGUR - P6 - Prialé Entrada")]))
    salidas = _salidas_por_nombre(procesador, entrada)

    crudo = salidas[NOMBRE_TXT].read_bytes()
    assert "Prialé".encode() in crudo  # la tilde sobrevive en UTF-8
    with salidas[NOMBRE_TXT].open(encoding="utf-8", newline="") as archivo:
        filas = list(csv.reader(archivo, delimiter="\t"))
    assert all(len(fila) == 26 for fila in filas)


# --- Endurecimiento 3: los descartes se cuentan y se reportan ---------------


def test_sin_descartes_no_hay_tercer_archivo(procesador: ContadoCarga, tmp_path: Path) -> None:
    """Entrada limpia = misma forma que el script: un Excel y un TXT, nada más."""
    entrada = _entrada(_libro(tmp_path, [_fila()]))
    salidas = _salidas_por_nombre(procesador, entrada)
    assert sorted(salidas) == sorted((NOMBRE_XLSX, NOMBRE_TXT))


def test_una_plaza_desconocida_se_descarta_y_se_reporta(
    procesador: ContadoCarga, tmp_path: Path
) -> None:
    """El descarte que el script contaba pero sólo imprimía a stdout."""
    filas = [_fila(), _fila(texto="PROSEGUR - P11 - Plaza Nueva")]
    entrada = _entrada(_libro(tmp_path, filas))
    salidas = _salidas_por_nombre(procesador, entrada)

    assert NOMBRE_DESCARTES in salidas
    reporte = salidas[NOMBRE_DESCARTES].read_text(encoding="utf-8")
    assert f"{MOTIVO_PLAZA}=1" in reporte
    assert "PROSEGUR - P11 - Plaza Nueva" in reporte
    assert "\t3\t" not in reporte  # la fila válida no figura
    assert reporte.splitlines()[-1].startswith("3\t")  # la fila 3 del Excel


def test_una_fecha_invalida_se_descarta_y_se_reporta(
    procesador: ContadoCarga, tmp_path: Path
) -> None:
    """El descarte que el script hacía con un `continue` PELADO, sin contador.

    Es el que el PRD no nombra y el que más silenciosamente perdía filas.
    """
    filas = [_fila(), _fila(documento="no es una fecha")]
    entrada = _entrada(_libro(tmp_path, filas))
    salidas = _salidas_por_nombre(procesador, entrada)

    reporte = salidas[NOMBRE_DESCARTES].read_text(encoding="utf-8")
    assert f"{MOTIVO_FECHA}=1" in reporte
    assert "Filas descartadas: 1" in reporte


def test_el_reporte_distingue_los_dos_motivos(procesador: ContadoCarga, tmp_path: Path) -> None:
    filas = [_fila(), _fila(entrada=None), _fila(texto="Otra cosa"), _fila(texto="Y otra")]
    entrada = _entrada(_libro(tmp_path, filas))
    salidas = _salidas_por_nombre(procesador, entrada)

    reporte = salidas[NOMBRE_DESCARTES].read_text(encoding="utf-8")
    assert "Filas descartadas: 3" in reporte
    assert f"{MOTIVO_FECHA}=1" in reporte
    assert f"{MOTIVO_PLAZA}=2" in reporte


def test_el_descarte_se_registra_en_el_log(
    procesador: ContadoCarga, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    filas = [_fila(), _fila(texto="Plaza desconocida")]
    entrada = _entrada(_libro(tmp_path, filas))

    with caplog.at_level("INFO", logger="app"):
        procesador.procesar([entrada])

    (registro,) = [r for r in caplog.records if getattr(r, "evento", None) == "descartes"]
    assert registro.clave == "contado-carga"  # type: ignore[attr-defined]
    assert registro.filas_descartadas == 1  # type: ignore[attr-defined]
    assert registro.filas_procesadas == 1  # type: ignore[attr-defined]
    assert registro.por_motivo == {MOTIVO_PLAZA: 1}  # type: ignore[attr-defined]


def test_sin_descartes_no_se_registra_nada(
    procesador: ContadoCarga, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    entrada = _entrada(_libro(tmp_path, [_fila()]))
    with caplog.at_level("INFO", logger="app"):
        procesador.procesar([entrada])
    assert not [r for r in caplog.records if getattr(r, "evento", None) == "descartes"]


# --- Endurecimiento 4: cero filas es error de contenido ---------------------


def test_cero_filas_procesadas_es_error_de_contenido(
    procesador: ContadoCarga, tmp_path: Path
) -> None:
    """Nunca un Excel vacío ni un éxito con las manos vacías."""
    entrada = _entrada(_libro(tmp_path, [_fila(texto="Ninguna plaza conocida")]))

    with pytest.raises(ErrorContenido) as capturado:
        procesador.procesar([entrada])
    assert capturado.value.contexto == {
        "archivo": "contado.xlsx",
        "motivo": "cero_filas",
        "columna": None,
    }


def test_cero_filas_no_deja_ningun_archivo(procesador: ContadoCarga, tmp_path: Path) -> None:
    """El error se levanta ANTES de escribir: no queda un Excel a medias."""
    ruta = _libro(tmp_path, [_fila(texto="Desconocida")])
    with pytest.raises(ErrorContenido):
        procesador.procesar([_entrada(ruta)])
    assert sorted(p.name for p in tmp_path.iterdir()) == ["contado.xlsx"]


def test_un_excel_ilegible_es_error_de_contenido(procesador: ContadoCarga, tmp_path: Path) -> None:
    """`app/core/validaciones.py` designa a este módulo como el dueño de este caso."""
    ruta = tmp_path / "corrupto.xlsx"
    ruta.write_bytes(b"esto no es un xlsx")

    error = procesador.validar([_entrada(ruta, "corrupto.xlsx")])
    assert isinstance(error, ErrorContenido)
    assert error.contexto["motivo"] == "cero_filas"


# --- Endurecimiento 5: ninguna excepción se traga ---------------------------


def test_una_fila_que_rompe_no_se_traga(
    procesador: ContadoCarga, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El script tenía `except Exception: continue`. Acá se propaga.

    `app/core/ejecucion.py` la convierte en `FalloDelModulo` y el ítem #10 la
    mapea a un 500; lo que no puede pasar es que la fila desaparezca y el
    proceso termine "bien".
    """
    import app.procesadores.contado_carga.modulo as modulo

    def _explota(*_args: Any, **_kwargs: Any) -> float:
        raise RuntimeError("importe imposible")

    monkeypatch.setattr(modulo, "_a_importe", _explota)
    entrada = _entrada(_libro(tmp_path, [_fila()]))

    with pytest.raises(RuntimeError, match="importe imposible"):
        procesador.procesar([entrada])


# --- Reglas de conversión migradas verbatim ---------------------------------


@pytest.mark.parametrize(
    ("crudo", "esperado"),
    [
        ("1,234.56", 1234.56),
        ("  -42.0 ", -42.0),
        ("", 0.0),
        ("-", 0.0),
        ("no es un número", 0.0),
        (None, 0.0),
        (1250.5, 1250.5),
    ],
)
def test_limpieza_de_importes(crudo: object, esperado: float) -> None:
    """Equivalente de `limpiar_montos`: lo que no parsea vale cero."""
    assert _a_importe(crudo) == esperado


@pytest.mark.parametrize(
    ("celda", "esperado"),
    [
        ("", ""),
        (1234.0, "1234.0"),  # un float normal CONSERVA el .0
        (2000000000.0, "2000000000"),  # por encima del umbral pierde los decimales
        (1101017004, "1101017004"),  # int, no float: esquiva la rama entera
        (1250.5, "1250.5"),
        ("texto", "texto"),
    ],
)
def test_formateo_de_celda_del_txt(celda: object, esperado: str) -> None:
    """La regla más fácil de "arreglar" sin querer, y la que rompe la paridad."""
    assert _celda_de_txt(celda) == esperado


@pytest.mark.parametrize(
    ("crudo", "esperado"),
    [("14/03/2026", "20260314"), ("14-03-2026", "20260314"), ("2026-03-14", "20260314")],
)
def test_fechas_en_texto_se_leen_con_el_dia_primero(
    procesador: ContadoCarga, tmp_path: Path, crudo: str, esperado: str
) -> None:
    """`dayfirst=True`: `01/02/2026` es el 1 de febrero, jamás el 2 de enero."""
    entrada = _entrada(_libro(tmp_path, [_fila(contabilizacion=crudo)]))
    salidas = _salidas_por_nombre(procesador, entrada)
    cabecera = list(load_workbook(salidas[NOMBRE_XLSX]).worksheets[0].iter_rows(values_only=True))[
        0
    ]
    assert cabecera[7] == esperado


def test_una_fecha_como_date_puro_se_acepta(procesador: ContadoCarga, tmp_path: Path) -> None:
    entrada = _entrada(_libro(tmp_path, [_fila(contabilizacion=date(2026, 3, 14))]))
    assert NOMBRE_XLSX in _salidas_por_nombre(procesador, entrada)


def test_las_filas_sin_fecha_de_contabilizacion_se_filtran_sin_contar(
    procesador: ContadoCarga, tmp_path: Path
) -> None:
    """El filtro previo del script (columna B vacía) no es un descarte: es ruido.

    Un Excel exportado suele traer filas de relleno al final. Contarlas como
    descartes llenaría el reporte de falsos positivos y escondería los de
    verdad.
    """
    filas: list[list[object]] = [_fila(), [None, None, None, None, None, None, None]]
    entrada = _entrada(_libro(tmp_path, filas))
    salidas = _salidas_por_nombre(procesador, entrada)
    assert NOMBRE_DESCARTES not in salidas


# --- Coherencia con el registro ---------------------------------------------


def test_la_clave_coincide_con_el_registry() -> None:
    from app.core.contrato import obtener_contrato
    from app.registry import REGISTRY

    procesador = REGISTRY["contado-carga"]
    assert procesador.clave == "contado-carga"
    assert isinstance(procesador, ContadoCarga)

    contrato = obtener_contrato("contado-carga")
    assert contrato is not None
    assert contrato.entradas_min == 1
    assert contrato.entradas_max == 1
    assert "xlsx" in contrato.formatos_aceptados


# --- De punta a punta, por la ruta real y el proceso hijo -------------------


class TestPuntaAPunta:
    """La tubería completa: HTTP → temporal sin extensión → `spawn` → ZIP.

    Existe por un bug concreto que ninguna prueba de esta suite podía ver:
    `openpyxl.load_workbook` valida la **extensión del nombre** antes de leer
    un byte, y `app/recepcion.py` escribe los temporales como `entrada_0`, sin
    extensión y a propósito (ADR 0020). Todas las pruebas de arriba le pasan
    al módulo una ruta que termina en `.xlsx`, así que todas pasaban mientras
    la ruta real devolvía 422 a cada Excel legítimo.
    """

    @staticmethod
    def _subir(cliente: Any, contenido: bytes) -> Any:
        return cliente.post(
            "/interno/procesadores/contado-carga",
            files={"archivos": ("contado.xlsx", contenido, "application/octet-stream")},
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

    def test_un_excel_legitimo_vuelve_como_zip(self, token_sentinela: str) -> None:
        import io
        import zipfile

        from fastapi.testclient import TestClient

        from app.main import crear_app

        with TestClient(crear_app()) as cliente:
            respuesta = self._subir(cliente, self._bytes_de_libro([_fila()]))

        assert respuesta.status_code == 200, respuesta.text
        with zipfile.ZipFile(io.BytesIO(respuesta.content)) as paquete:
            assert sorted(paquete.namelist()) == sorted((NOMBRE_XLSX, NOMBRE_TXT))
            assert paquete.read(NOMBRE_TXT).count(b"\r\n") == 4

    def test_el_descarte_viaja_en_el_zip(self, token_sentinela: str) -> None:
        import io
        import zipfile

        from fastapi.testclient import TestClient

        from app.main import crear_app

        filas = [_fila(), _fila(texto="PROSEGUR - P99 - Inventada")]
        with TestClient(crear_app()) as cliente:
            respuesta = self._subir(cliente, self._bytes_de_libro(filas))

        assert respuesta.status_code == 200, respuesta.text
        with zipfile.ZipFile(io.BytesIO(respuesta.content)) as paquete:
            assert NOMBRE_DESCARTES in paquete.namelist()
            assert b"PROSEGUR - P99 - Inventada" in paquete.read(NOMBRE_DESCARTES)

    def test_un_archivo_que_no_es_excel_es_422(self, token_sentinela: str) -> None:
        """Sigue siendo error de contenido: la extensión no lo salva."""
        from fastapi.testclient import TestClient

        from app.main import crear_app

        with TestClient(crear_app()) as cliente:
            respuesta = self._subir(cliente, b"esto no es un xlsx")

        assert respuesta.status_code == 422
        assert respuesta.json()["tipo"] == "contenido"
