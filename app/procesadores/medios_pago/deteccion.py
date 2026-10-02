"""Qué es cada archivo subido, decidido por su CONTENIDO.

Los scripts decidían por el nombre (`"mc" in nombre`, `"amex"`, `"servicios"`,
`"MPFinancialReport"`, rutas fijas para `bbva.csv_` y `Abonos_BBVA.xlsx`), y
la regla de `mc` es frágil: cualquier nombre con esas dos letras seguidas era
Mastercard. Acá el nombre es sólo el respaldo, y únicamente cuando el
contenido ya dijo de qué familia es el archivo:

- **Libro de Excel** (un ZIP): SafetyPay si la séptima fila (la de títulos de
  `header=6`) tiene `Merchant Settlement Date`; maestro de abonos BBVA si la
  primera fila tiene `F. Operación` (o `F. Operación_dt`), `Importe` y
  `Concepto`. Si no, por el nombre: `mpfinancialreport` → SafetyPay,
  `abonos_bbva` → maestro (y después falta la columna).
- **Texto**: reporte de Izipay si la primera línea tiene `Codigo` y una fecha
  de abono (`Fecha_Abono_8Dig` o `Fecha_Abono`). El tipo lo deciden las
  columnas que sólo tiene cada reporte en las muestras de mayo de 2025:
  `Comision_Merchant` (sin `Fecha_Abono_8Dig`) es AMEX, `Comision_Afecta` es
  Mastercard, ninguna de las dos con `Fecha_Abono_8Dig` es Diners. Con las
  dos a la vez decide el nombre con la regla del script. Si no es Izipay, es
  un extracto BBVA si su primera línea es un registro de cabecera (`00,`) o
  alguna empieza con `22,` (el registro de movimiento que el script lee); el
  nombre `bbva` es el respaldo.
- Lo demás es `tipo_no_reconocido`. Un libro que no abre es `cero_filas`, como
  en los demás procesadores.

Detectar no lee más que la cabecera de un CSV de Izipay (los primeros 64 KB)
y las primeras siete filas de un libro.
"""

from __future__ import annotations

import zipfile
from typing import Final

from openpyxl import load_workbook
from openpyxl.worksheet._read_only import ReadOnlyWorksheet

from app.core.errores import ErrorContenido
from app.core.tipos import ArchivoEntrada
from app.procesadores.medios_pago.comun import nombre_base, nombres_de_columnas
from app.procesadores.medios_pago.izipay import (
    COL_CODIGO,
    COL_FECHA_8DIG,
    COL_FECHA_ABONO,
    COL_FECHA_SAFETYPAY,
    FILA_TITULOS_SAFETYPAY,
    TIPO_AMEX,
    TIPO_DINNER,
    TIPO_MASTERCARD,
    TIPO_SAFETYPAY,
    columna_de_fecha,
    filas_de_libro,
    registros_csv,
)

TIPO_BBVA: Final[str] = "bbva"
"""El extracto `bbva.csv_` del banco."""
TIPO_MAESTRO: Final[str] = "maestro"
"""El maestro anterior `Abonos_BBVA.xlsx` (un CATEGORIZADO de una corrida previa)."""

COL_F_OPERACION: Final[str] = "F. Operación"
COL_F_OPERACION_DT: Final[str] = "F. Operación_dt"
COLUMNAS_MAESTRO: Final[tuple[str, ...]] = ("Importe", "Concepto")

_PREFIJO_CSV: Final[int] = 64 * 1024


def detectar(entrada: ArchivoEntrada) -> str:
    """El tipo del archivo: uno de `TIPOS_IZIPAY`, `TIPO_SAFETYPAY`,
    `TIPO_BBVA` o `TIPO_MAESTRO`. Levanta el error de contenido si no se
    reconoce o si al tipo le falta una columna que el script leía."""
    if zipfile.is_zipfile(entrada.ruta_temporal):
        return _detectar_libro(entrada)
    return _detectar_texto(entrada)


def _detectar_libro(entrada: ArchivoEntrada) -> str:
    archivo = entrada.nombre_original
    with entrada.ruta_temporal.open("rb") as descriptor:
        try:
            libro = load_workbook(descriptor, read_only=True, data_only=True)
        except Exception as error:
            raise ErrorContenido.cero_filas(archivo=archivo) from error
        try:
            hoja = libro.worksheets[0] if libro.worksheets else None
            filas = (
                filas_de_libro(hoja, limite=FILA_TITULOS_SAFETYPAY + 1)
                if isinstance(hoja, ReadOnlyWorksheet)
                else []
            )
        finally:
            libro.close()
    titulos_sp = (
        set(nombres_de_columnas(["" if v is None else v for v in filas[FILA_TITULOS_SAFETYPAY]]))
        if len(filas) > FILA_TITULOS_SAFETYPAY
        else set()
    )
    if COL_FECHA_SAFETYPAY in titulos_sp:
        return TIPO_SAFETYPAY
    titulos = (
        set(nombres_de_columnas(["" if v is None else v for v in filas[0]])) if filas else set()
    )
    if {COL_F_OPERACION, COL_F_OPERACION_DT} & titulos and set(COLUMNAS_MAESTRO) <= titulos:
        return TIPO_MAESTRO
    nombre = nombre_base(archivo).casefold()
    if "mpfinancialreport" in nombre:
        raise ErrorContenido.columna_faltante(archivo=archivo, columna=COL_FECHA_SAFETYPAY)
    if "abonos_bbva" in nombre:
        faltante = next(
            (c for c in (COL_F_OPERACION, *COLUMNAS_MAESTRO) if c not in titulos), COL_F_OPERACION
        )
        raise ErrorContenido.columna_faltante(archivo=archivo, columna=faltante)
    raise ErrorContenido.tipo_no_reconocido(archivo=archivo)


def tipo_izipay_por_columnas(nombres: set[str]) -> str | None:
    """El tipo de reporte de Izipay por sus columnas; `""` si es Izipay pero
    las columnas no deciden, `None` si no es un reporte de Izipay."""
    if COL_CODIGO not in nombres or not {COL_FECHA_ABONO, COL_FECHA_8DIG} & nombres:
        return None
    merchant = "Comision_Merchant" in nombres
    afecta = "Comision_Afecta" in nombres
    ocho = COL_FECHA_8DIG in nombres
    if merchant and not afecta and not ocho:
        return TIPO_AMEX
    if afecta and not merchant and ocho:
        return TIPO_MASTERCARD
    if not merchant and not afecta and ocho:
        return TIPO_DINNER
    return ""


def tipo_izipay_por_nombre(nombre_original: str) -> str | None:
    """`detectar_tipo` del script, verbatim y en su orden, sobre el nombre base."""
    nombre = nombre_base(nombre_original).lower()
    if "mc" in nombre:
        return TIPO_MASTERCARD
    if "amex" in nombre:
        return TIPO_AMEX
    if "servicios" in nombre:
        return TIPO_DINNER
    return None


def _detectar_texto(entrada: ArchivoEntrada) -> str:
    archivo = entrada.nombre_original
    with entrada.ruta_temporal.open("rb") as descriptor:
        prefijo = descriptor.read(_PREFIJO_CSV)
    texto = prefijo.decode("utf-8-sig", errors="replace")
    primera = next(registros_csv(texto), None)
    nombres = set(nombres_de_columnas(primera[1])) if primera is not None else set()
    tipo = tipo_izipay_por_columnas(nombres)
    if tipo is not None:
        if tipo == "":
            tipo = tipo_izipay_por_nombre(archivo)
            if tipo is None:
                raise ErrorContenido.tipo_no_reconocido(archivo=archivo)
        for columna in (COL_CODIGO, columna_de_fecha(tipo)):
            if columna not in nombres:
                raise ErrorContenido.columna_faltante(archivo=archivo, columna=columna)
        return tipo
    if _es_extracto_bbva(entrada) or "bbva" in nombre_base(archivo).casefold():
        return TIPO_BBVA
    raise ErrorContenido.tipo_no_reconocido(archivo=archivo)


def _es_extracto_bbva(entrada: ArchivoEntrada) -> bool:
    lineas = lineas_latin1(entrada.ruta_temporal.read_bytes())
    primera = next((linea for linea in lineas if linea.strip()), "")
    if primera.startswith("00,"):
        return True
    return any(linea.strip().startswith("22,") for linea in lineas)


def lineas_latin1(datos: bytes) -> list[str]:
    """Las líneas como las iteraba `open(..., encoding='latin1')`: separadas
    sólo por `\\r\\n`, `\\r` o `\\n` (no por los demás separadores que
    `str.splitlines` reconoce y que latin1 puede producir)."""
    texto = datos.decode("latin1").replace("\r\n", "\n").replace("\r", "\n")
    lineas = texto.split("\n")
    if lineas and lineas[-1] == "":
        lineas.pop()
    return lineas
