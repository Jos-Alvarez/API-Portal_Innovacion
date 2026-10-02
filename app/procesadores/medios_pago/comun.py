"""Piezas compartidas por los dos procesadores de medios de pago.

Lo que los scripts hacían con pandas y que este paquete reproduce sin pandas
(el hijo de `spawn` lo reimportaría en cada petición; ver el README de la
migración de `contado_carga`). Cada función documenta qué operación de pandas
emula. La referencia es **pandas 2.2.3**, la versión con que se regeneraron
las salidas esperadas y la única que reproduce también el estilo de los
títulos de las salidas históricas (pandas 3 dejó de ponerlos en negrita).

También viven acá el orden de NTFS de los nombres (lo que devolvía
`os.listdir`), la escritura de `.xlsx` con los títulos de `to_excel` y el
reporte `observaciones.txt`.

Este módulo importa la biblioteca estándar, `openpyxl` y —de `core/`— nada.
No tiene efecto de importación alguno.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Final, cast

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.cell.cell import Cell
from openpyxl.styles import Alignment, Border, Font, Side
from openpyxl.worksheet._write_only import WriteOnlyWorksheet

MIME_XLSX: Final[str] = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MIME_CSV: Final[str] = "text/csv; charset=utf-8"
MIME_TEXTO: Final[str] = "text/plain; charset=utf-8"

NOMBRE_OBSERVACIONES: Final[str] = "observaciones.txt"
FIN_DE_LINEA: Final[str] = "\r\n"
"""El de `observaciones.txt` de los demás procesadores, y también el que
`to_csv` escribía en Windows (`os.linesep`): fijado, no heredado de la
plataforma."""
CODIFICACION: Final[str] = "utf-8"

FORMATO_FECHA_HORA: Final[str] = "YYYY-MM-DD HH:MM:SS"
"""El `datetime_format` por defecto con que `to_excel` escribía un `datetime`."""
FORMATO_FECHA: Final[str] = "YYYY-MM-DD"
"""El `date_format` por defecto con que `to_excel` escribía un `date`."""

# --- Nulos y números -----------------------------------------------------------

NULOS: Final[frozenset[str]] = frozenset(
    {
        "",
        "#N/A",
        "#N/A N/A",
        "#NA",
        "-1.#IND",
        "-1.#QNAN",
        "-NaN",
        "-nan",
        "1.#IND",
        "1.#QNAN",
        "<NA>",
        "N/A",
        "NA",
        "NULL",
        "NaN",
        "None",
        "n/a",
        "nan",
        "null",
    }
)
"""Los `na_values` por defecto de `read_csv` y `read_excel`: un campo que es
EXACTAMENTE uno de estos textos (sin `strip()`) se lee como NaN, también en
las columnas leídas con `dtype=str`."""

ESPACIOS_ASCII: Final[str] = " \t\n\r\f\v"
ENTERO: Final[re.Pattern[str]] = re.compile(r"[+-]?[0-9]+")
"""Un entero como lo acepta pandas: sólo dígitos ASCII (Python también
aceptaría otros dígitos de Unicode y el `_`)."""
_DECIMAL: Final[re.Pattern[str]] = re.compile(
    r"[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"
)
_INFINITOS: Final[frozenset[str]] = frozenset(
    {"inf", "+inf", "-inf", "infinity", "+infinity", "-infinity"}
)

Numero = int | float


def es_blanco(texto: str | None) -> bool:
    """`None` (NaN) o sólo espacios: lo que no se reporta cuando no se lee."""
    return texto is None or not texto.strip()


def numero_de_texto(texto: str) -> Numero | None:
    """`pd.to_numeric(texto, errors='coerce')`: `None` por NaN.

    Tolera espacios ASCII alrededor (`" 12 "` es 12) pero no el espacio duro,
    ni separadores de miles, ni el `_` que Python sí acepta. `inf` y
    `Infinity` (sin distinguir mayúsculas) son infinitos; `nan` es NaN.
    """
    limpio = texto.strip(ESPACIOS_ASCII)
    if ENTERO.fullmatch(limpio):
        return int(limpio)
    if _DECIMAL.fullmatch(limpio) or limpio.lower() in _INFINITOS:
        return float(limpio)
    return None


def redondear2(valor: Numero | None) -> Numero | None:
    """`Series.round(2)` de numpy: `rint(x * 100) / 100`, con el redondeo al
    par de `rint`. NO es el `round(x, 2)` de Python, que redondea el valor
    decimal exacto (`2.675` → 2.67 en Python, 2.68 en numpy). Un entero
    sigue entero."""
    if valor is None or isinstance(valor, int):
        return valor
    if not math.isfinite(valor):
        return valor
    return float(round(valor * 100.0)) / 100.0


def texto_pandas(valor: object) -> str:
    """`Series.astype(str)` de pandas 2 sobre un valor: NaN es `"nan"`."""
    if valor is None:
        return "nan"
    if isinstance(valor, float):
        return "nan" if math.isnan(valor) else repr(valor)
    return str(valor)


def renderizar_csv(valor: object) -> str:
    """Cómo `to_csv` escribe un valor: NaN vacío, `float` con su `repr`
    (`14.0`, `1e-05`, `inf`), `bool` como `True`/`False`, el resto con `str`."""
    if valor is None:
        return ""
    if isinstance(valor, float):
        return "" if math.isnan(valor) else repr(valor)
    return str(valor)


# --- Fechas -------------------------------------------------------------------

TIMESTAMP_MIN: Final[datetime] = datetime(1677, 9, 21, 0, 12, 43, 145225)
TIMESTAMP_MAX: Final[datetime] = datetime(2262, 4, 11, 23, 47, 16, 854775)
"""Los límites de `pd.Timestamp`: fuera de ellos `to_datetime(errors='coerce')`
devuelve `NaT`."""


def en_rango_timestamp(fecha: datetime) -> bool:
    return TIMESTAMP_MIN <= fecha <= TIMESTAMP_MAX


_NAT: Final[frozenset[str]] = frozenset({"NaT", "nat", "NAT", "nan", "NaN", "NAN"})
"""Textos que `pd.to_datetime` lee como `NaT` y que salta al buscar el primer
valor con el cual inferir el formato."""

_HORA: Final[str] = r"(?P<hora>[ T]\d{1,2}:\d{2}(?::\d{2}(?P<fraccion>\.\d{1,6})?)?)?"
_ANIO_PRIMERO: Final[re.Pattern[str]] = re.compile(
    r"\d{4}(?P<sep>[-/.])\d{1,2}(?P=sep)\d{1,2}" + _HORA
)
_ANIO_ULTIMO: Final[re.Pattern[str]] = re.compile(
    r"\d{1,2}(?P<sep>[-/.])\d{1,2}(?P=sep)(?P<anio>\d{4}|\d{2})" + _HORA
)

DIAS_EN: Final[tuple[str, ...]] = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)
MESES_EN: Final[tuple[str, ...]] = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)
_LARGA_EN: Final[re.Pattern[str]] = re.compile(
    r"(?P<dia_semana>[A-Za-z]+), (?P<dia>\d{1,2}) (?P<mes>[A-Za-z]+) (?P<anio>\d{4})"
    r" (?P<h>\d{1,2}):(?P<m>\d{2}):(?P<s>\d{2})"
)
FORMATO_LARGO_EN: Final[str] = "%A, %d %B %Y %H:%M:%S"
"""La forma de `Merchant Settlement Date` de SafetyPay
(`"Monday, 26 May 2025 00:00:00"`), que pandas infiere así (verificado contra
pandas 2.2.3 y 3.0.6)."""


def _prueba(texto: str, formato: str) -> bool:
    try:
        datetime.strptime(texto, formato)
    except ValueError:
        return False
    return True


def _formato_de_hora(forma: re.Match[str]) -> str:
    hora = forma.group("hora")
    if not hora:
        return ""
    formato = f"{hora[0]}%H:%M" + (":%S" if hora.count(":") == 2 else "")
    return formato + (".%f" if forma.group("fraccion") else "")


def _fecha_larga_en(texto: str) -> datetime | None:
    """`strptime(texto, FORMATO_LARGO_EN)` sin depender del idioma del proceso:
    los nombres se comparan en inglés y sin distinguir mayúsculas, como el
    `strptime` de pandas. El día de la semana se lee pero no se verifica."""
    forma = _LARGA_EN.fullmatch(texto)
    if forma is None:
        return None
    if forma.group("dia_semana").lower() not in DIAS_EN:
        return None
    mes = forma.group("mes").lower()
    if mes not in MESES_EN:
        return None
    try:
        return datetime(
            int(forma.group("anio")),
            MESES_EN.index(mes) + 1,
            int(forma.group("dia")),
            int(forma.group("h")),
            int(forma.group("m")),
            int(forma.group("s")),
        )
    except ValueError:
        return None


def adivinar_formato(texto: str, *, dayfirst: bool, anio_corto: bool = False) -> str | None:
    """`guess_datetime_format` de pandas para las formas que este paquete
    conoce: año primero o año último con `-`, `/` o `.` y hora opcional (ver
    la migración de `flujo-caja-pagos`, de donde viene esta regla), y la forma
    larga en inglés de SafetyPay. `None` si no es una de ellas o no es una
    fecha válida."""
    nucleo = texto.strip()
    if not nucleo:
        return None
    if nucleo == texto and _fecha_larga_en(nucleo) is not None:
        return FORMATO_LARGO_EN
    antes = texto[: len(texto) - len(texto.lstrip())]
    despues = texto[len(texto.rstrip()) :]
    ordenes = (("%d", "%m"), ("%m", "%d")) if dayfirst else (("%m", "%d"), ("%d", "%m"))
    candidatos: list[str] = []
    forma = _ANIO_PRIMERO.fullmatch(nucleo)
    if forma:
        sep = forma.group("sep")
        candidatos = [f"%Y{sep}{a}{sep}{b}{_formato_de_hora(forma)}" for a, b in ordenes]
    forma = _ANIO_ULTIMO.fullmatch(nucleo)
    if forma and (anio_corto or len(forma.group("anio")) == 4):
        sep = forma.group("sep")
        anio = "%Y" if len(forma.group("anio")) == 4 else "%y"
        candidatos = [f"{a}{sep}{b}{sep}{anio}{_formato_de_hora(forma)}" for a, b in ordenes]
    for candidato in candidatos:
        if _prueba(nucleo, candidato):
            return f"{antes}{candidato}{despues}"
    return None


def _a_fecha(texto: str, formato: str | None) -> datetime | None:
    if formato is None:
        return None
    if formato == FORMATO_LARGO_EN:
        fecha = _fecha_larga_en(texto)
    else:
        try:
            fecha = datetime.strptime(texto, formato)
        except ValueError:
            return None
    return fecha if fecha is not None and en_rango_timestamp(fecha) else None


def fechas_de_columna(valores: Sequence[object], *, dayfirst: bool) -> list[datetime | None]:
    """`pd.to_datetime(columna, errors='coerce', dayfirst=...)`.

    Un `datetime` (o `date`) pasa tal cual. Sobre texto, pandas infiere UN
    formato a partir del primer texto no nulo (saltando los de `_NAT`) y lo
    exige a todos: lo que no calza es `NaT`. Si del primero no se infiere
    nada, cada valor se interpreta por separado, como el respaldo de dateutil
    (con las mismas formas). Un número es una cantidad de nanosegundos desde
    1970, como en pandas.
    """
    primero = next((v for v in valores if isinstance(v, str) and v.strip() and v not in _NAT), None)
    formato = None if primero is None else adivinar_formato(primero, dayfirst=dayfirst)
    fechas: list[datetime | None] = []
    for valor in valores:
        if valor is None:
            fechas.append(None)
        elif isinstance(valor, datetime):
            fechas.append(valor if en_rango_timestamp(valor) else None)
        elif isinstance(valor, date):
            fechas.append(datetime(valor.year, valor.month, valor.day))
        elif isinstance(valor, bool):
            fechas.append(None)
        elif isinstance(valor, int | float):
            fechas.append(_desde_nanosegundos(valor))
        elif not isinstance(valor, str) or not valor.strip() or valor in _NAT:
            fechas.append(None)
        elif formato is not None:
            fechas.append(_a_fecha(valor, formato))
        else:
            individual = adivinar_formato(valor, dayfirst=dayfirst, anio_corto=True)
            fechas.append(_a_fecha(valor, individual))
    return fechas


def _desde_nanosegundos(valor: float) -> datetime | None:
    if not math.isfinite(valor):
        return None
    return datetime(1970, 1, 1) + timedelta(microseconds=int(valor) // 1000)


# --- Lectura de Excel como pandas ----------------------------------------------


def celda_pandas(valor: object) -> object:
    """El `_convert_cell` del lector openpyxl de pandas: un `float` entero se
    lee `int`. `None` es la celda vacía (que pandas lee `""` y después NaN)."""
    if isinstance(valor, float) and math.isfinite(valor) and valor.is_integer():
        return int(valor)
    return valor


def es_nulo_excel(valor: object) -> bool:
    """Lo que `read_excel` lee como NaN: celda vacía, error de Excel o un
    texto de `NULOS`."""
    if valor is None:
        return True
    if isinstance(valor, float):
        return math.isnan(valor)
    return isinstance(valor, str) and (valor in NULOS or valor.startswith("#"))


def texto_excel(valor: object) -> str | None:
    """`read_excel(dtype=str)`: `None` por NaN; si no, `str()` de lo leído
    (un `datetime` se vuelve `"2025-05-02 00:00:00"`)."""
    convertido = celda_pandas(valor)
    if convertido is None or (isinstance(convertido, str) and convertido in NULOS):
        return None
    if isinstance(convertido, float) and math.isnan(convertido):
        return None
    return str(convertido)


def nombres_de_columnas(titulos: Sequence[object]) -> list[str]:
    """Los nombres que pandas da a una fila de títulos: vacío es
    `"Unnamed: i"` y un repetido lleva `.1`, `.2`… (`mangle_dupe_cols`)."""
    nombres: list[str] = []
    vistos: dict[str, int] = {}
    for indice, titulo in enumerate(titulos):
        nombre = f"Unnamed: {indice}" if titulo is None or titulo == "" else str(titulo)
        if nombre in vistos:
            cuenta = vistos[nombre]
            candidato = f"{nombre}.{cuenta}"
            while candidato in vistos:
                cuenta += 1
                candidato = f"{nombre}.{cuenta}"
            vistos[nombre] = cuenta + 1
            vistos[candidato] = 1
            nombre = candidato
        else:
            vistos[nombre] = 1
        nombres.append(nombre)
    return nombres


# --- Nombres de archivo ---------------------------------------------------------


def clave_ntfs(nombre: str) -> bytes:
    """Clave de orden del índice de directorio de NTFS (lo que devolvía
    `os.listdir`; ver la migración de `flujo-caja-pagos`): unidades UTF-16
    comparadas tras pasar cada una a mayúsculas con la conversión simple de
    Unicode. Los caracteres fuera del plano básico no se convierten."""
    mayusculas = "".join(
        c.upper() if ord(c) <= 0xFFFF and len(c.upper()) == 1 else c for c in nombre
    )
    return mayusculas.encode("utf-16-be", "surrogatepass")


def nombre_base(nombre_original: str) -> str:
    """`os.path.basename` de Windows: lo que sigue a la última `/` o `\\`."""
    return nombre_original.replace("\\", "/").rpartition("/")[2]


# --- Escritura de Excel ----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Celda:
    """Un valor con el formato de número que la salida le fija."""

    valor: object
    formato: str


_BORDE_FINO: Final[Side] = Side(style="thin")


ValorDeCelda = str | float | datetime | None
"""Lo que `WriteOnlyCell` declara aceptar; en ejecución también toma `int`,
`bool` y `date`."""


def _celda(hoja: WriteOnlyWorksheet, valor: object) -> Cell:
    return WriteOnlyCell(hoja, value=cast(ValorDeCelda, valor))


def _titulos(hoja: WriteOnlyWorksheet, columnas: Sequence[object]) -> list[Cell]:
    """La fila de títulos con el estilo de `to_excel` de pandas 2: negrita,
    borde fino y centrada arriba."""
    celdas: list[Cell] = []
    for titulo in columnas:
        celda = _celda(hoja, titulo)
        celda.font = Font(bold=True)
        celda.border = Border(
            left=_BORDE_FINO, right=_BORDE_FINO, top=_BORDE_FINO, bottom=_BORDE_FINO
        )
        celda.alignment = Alignment(horizontal="center", vertical="top")
        celdas.append(celda)
    return celdas


def _celdas(hoja: WriteOnlyWorksheet, fila: Sequence[object]) -> list[object]:
    """`""` y NaN son celdas vacías; una fecha lleva el formato de `to_excel`
    salvo que la salida le fije otro (`Celda`)."""
    celdas: list[object] = []
    for valor in fila:
        if isinstance(valor, Celda):
            celda = _celda(hoja, valor.valor)
            celda.number_format = valor.formato
            celdas.append(celda)
        elif isinstance(valor, datetime):
            celda = _celda(hoja, valor)
            celda.number_format = FORMATO_FECHA_HORA
            celdas.append(celda)
        elif isinstance(valor, date):
            celda = _celda(hoja, valor)
            celda.number_format = FORMATO_FECHA
            celdas.append(celda)
        elif valor == "" or (isinstance(valor, float) and math.isnan(valor)):
            celdas.append(None)
        else:
            celdas.append(valor)
    return celdas


def escribir_xlsx(
    ruta: Path,
    columnas: Sequence[object],
    filas: Iterable[Sequence[object]],
    *,
    fila_titulos: int = 1,
) -> None:
    """Una hoja `Sheet1` con títulos en `fila_titulos` (desde 1; `to_excel`
    con `startrow=fila_titulos - 1`) y sin índice."""
    libro = Workbook(write_only=True)
    hoja = libro.create_sheet(title="Sheet1")
    for _ in range(fila_titulos - 1):
        hoja.append([])
    hoja.append(_titulos(hoja, columnas))
    for fila in filas:
        hoja.append(_celdas(hoja, fila))
    libro.save(ruta)


# --- Observaciones ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Observacion:
    """Algo que el script habría hecho en silencio, con dónde y con qué valor.

    `fila` es la línea del archivo (desde 1) o la fila de Excel, o `None` si
    la observación es del archivo entero.
    """

    archivo: str
    fila: int | None
    motivo: str
    valor: str


def _limpio(texto: str) -> str:
    return texto.replace("\t", " ").replace("\r", " ").replace("\n", " ")


def escribir_observaciones(observaciones: Sequence[Observacion], ruta: Path) -> None:
    """Reporte de observaciones, una por línea, con `FIN_DE_LINEA` explícito."""
    conteo: dict[str, int] = {}
    for observacion in observaciones:
        conteo[observacion.motivo] = conteo.get(observacion.motivo, 0) + 1
    resumen = ", ".join(f"{motivo}={total}" for motivo, total in sorted(conteo.items()))
    lineas = [
        f"Observaciones: {len(observaciones)} ({resumen})",
        "",
        "\t".join(("archivo", "fila", "motivo", "valor")),
    ]
    lineas.extend(
        "\t".join(
            (
                _limpio(o.archivo),
                "" if o.fila is None else str(o.fila),
                o.motivo,
                _limpio(o.valor),
            )
        )
        for o in observaciones
    )
    with ruta.open("w", encoding=CODIFICACION, newline="") as salida:
        salida.write(FIN_DE_LINEA.join(lineas) + FIN_DE_LINEA)
