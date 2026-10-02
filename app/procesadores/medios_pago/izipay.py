"""Lectura y partición por fecha de los reportes crudos de Izipay y SafetyPay.

Es la parte de `Procesador_MediosPago_Reportes.py` que comparten los dos
procesadores del paquete: `medios-pago-reportes` escribe lo que sale de acá y
`medios-pago-bbva-hits` lo usa como conjunto de cruce (el script de BBVA
leía esos mismos CSV de la carpeta `Salida` de Reportes).

**CSV de Izipay** (`leer_csv` + `particionar`): `read_csv` con seis columnas
como texto (`COLUMNAS_TEXTO`) y el resto con la inferencia de tipos del
parser C de pandas (`_inferir_columna`), las columnas `Unnamed` fuera, la
fecha de abono reducida a sus primeros ocho dígitos, la fecha AMEX corrida
fuera de fines de semana y feriados de Perú, y cada fecha partida por
`Codigo == 4010761` en `{fecha}-{tipo}.csv` y `{fecha}-{tipo}-izipay.csv`.
Varios archivos del mismo tipo se ACUMULAN en el mismo nombre (`pd.concat`),
en el orden de NTFS de sus nombres (ver la docstring de `reportes.py`).
`to_csv(index=False)` se reproduce en `renderizar`.

**SafetyPay** (`leer_safetypay` + `particionar_safetypay`): `read_excel` con
`header=6`, cuatro columnas de identificadores como texto, la inferencia
numérica del parser de Python de pandas, la lista de columnas a eliminar,
`Payment Batch Number` en la segunda posición y un libro por fecha de
liquidación.

**Emulación del parser C de `read_csv`** (verificada contra pandas 2.2.3 y
3.0.6):

- Un campo que es exactamente un texto de `NULOS` es NaN, también en las
  columnas de texto. Una línea en blanco (o sólo con espacios) no cuenta.
- Las columnas no forzadas a texto se infieren POR TRAMOS de filas
  (`low_memory=True`): 32768 filas para los anchos de los reportes reales
  (`_filas_por_tramo`). En cada tramo: todos enteros y sin NaN → `int`;
  números (con NaN o decimales) → `float`; `True`/`False` → `bool`; si no,
  texto tal cual. Tramos de tipos distintos se unen como `concat_compat`:
  `int` con `float` es `float`, `bool` con `int` es `int`, cualquier otra
  mezcla es `object` y cada valor conserva el tipo de su tramo.
- `to_csv`: un `float` se escribe con su `repr` (`14.00` se vuelve `14.0`),
  NaN vacío, comillas mínimas y CRLF (`os.linesep` en Windows).
- `pd.concat` de tramos con columnas distintas une las columnas en orden de
  aparición; una columna ausente aporta NaN (un `int` pasa a `float`, un
  `bool` a `object`).

**Lo que cambia respecto del script** (ver también `reportes.py`):

- Una línea con MÁS campos que el título hacía fallar `read_csv` y el script
  salteaba el archivo entero con un `print`; acá se descarta esa línea y se
  reporta (`linea_invalida`). Una con menos campos se completa con NaN, como
  pandas.
- Un `Codigo` que no es un número hacía fallar `astype(float).astype(int)` en
  la fecha donde aparecía y el script perdía el resto del archivo; acá se
  descarta esa fila y se reporta (`codigo_invalido`).
- Una fecha de abono ESCRITA que no se puede leer se reporta
  (`fecha_invalida`); la fila se pierde, como en el script. Una fecha en
  blanco (cargos pendientes, sin abono todavía) es operación normal y no se
  reporta.
- Un archivo que no es UTF-8 válido hacía fallar `read_csv` y el script lo
  salteaba; acá es `cero_filas` para ese archivo.

**Feriados.** El script construía `holidays.PE(years=[2024, 2025])`, pero la
biblioteca amplía sola los años que se le consultan (`expand=True` por
defecto), así que una fecha de 2026 ya usaba los feriados de 2026: el error
que se sospechaba no existía. Acá se usa `holidays.country_holidays("PE")`,
que consulta los feriados del año de cada fecha (y del siguiente si el
corrimiento cruza el 31 de diciembre). Se importa sólo cuando hay un reporte
AMEX que ajustar: cuesta ~0,4 s por ejecución (medido en el README).
"""

from __future__ import annotations

import csv
import io
import math
import re
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Final

from openpyxl import load_workbook
from openpyxl.worksheet._read_only import ReadOnlyWorksheet

from app.core.errores import ErrorContenido
from app.core.tipos import ArchivoEntrada
from app.procesadores.medios_pago.comun import (
    ESPACIOS_ASCII,
    NULOS,
    Numero,
    Observacion,
    celda_pandas,
    en_rango_timestamp,
    fechas_de_columna,
    nombres_de_columnas,
    numero_de_texto,
    renderizar_csv,
    texto_pandas,
)

TIPO_MASTERCARD: Final[str] = "mastercard"
TIPO_AMEX: Final[str] = "amex"
TIPO_DINNER: Final[str] = "dinner"
TIPOS_IZIPAY: Final[tuple[str, ...]] = (TIPO_MASTERCARD, TIPO_AMEX, TIPO_DINNER)
"""Los tres reportes de Izipay, con el nombre que el script les daba en las
salidas (`dinner`, así, por Diners)."""
TIPO_SAFETYPAY: Final[str] = "safetypay"

COL_CODIGO: Final[str] = "Codigo"
COL_FECHA_ABONO: Final[str] = "Fecha_Abono"
COL_FECHA_8DIG: Final[str] = "Fecha_Abono_8Dig"
COL_NETO: Final[str] = "Neto_Total"
COLUMNAS_TEXTO: Final[tuple[str, ...]] = (
    "Terminal",
    "Codigo",
    "Lote_Pos",
    "Voucher",
    "Autorizacion",
    "Cuotas",
)
"""El `dtype=str` del `read_csv` del script."""

CODIGO_ANTIGUO: Final[int] = 4010761
"""El comercio cuyas filas van a `{fecha}-{tipo}.csv`; el resto va a
`{fecha}-{tipo}-izipay.csv`."""

MOTIVO_FECHA: Final[str] = "fecha_invalida"
MOTIVO_CODIGO: Final[str] = "codigo_invalido"
MOTIVO_LINEA: Final[str] = "linea_invalida"


def columna_de_fecha(tipo: str) -> str:
    """`"Fecha_Abono" if tipo == "amex" else "Fecha_Abono_8Dig"`, del script."""
    return COL_FECHA_ABONO if tipo == TIPO_AMEX else COL_FECHA_8DIG


# --- Inferencia de tipos del parser C ------------------------------------------

_ENTERO_C: Final[re.Pattern[str]] = re.compile(r"[+-]?[0-9]+")
_VERDADEROS: Final[frozenset[str]] = frozenset({"True", "TRUE", "true"})
_FALSOS: Final[frozenset[str]] = frozenset({"False", "FALSE", "false"})
_INT64: Final[range] = range(-(2**63), 2**63)
_UINT64: Final[range] = range(0, 2**64)

INT: Final[str] = "int"
FLOAT: Final[str] = "float"
BOOL: Final[str] = "bool"
OBJECT: Final[str] = "object"


def _filas_por_tramo(ancho: int) -> int:
    """`buffer_lines` del parser C con `low_memory=True`: la mayor potencia de
    dos cuyo doble no llega a `2**20 // ancho`."""
    heuristica = 2**20 // max(ancho, 1)
    filas = 1
    while filas * 2 < heuristica:
        filas *= 2
    return filas


def _inferir_tramo(textos: Sequence[str | None]) -> tuple[str, list[object]]:
    """Tipo y valores de una columna en un tramo, como `_infer_types`."""
    presentes = [t for t in textos if t is not None]
    if not presentes:
        return FLOAT, [None] * len(textos)
    if all(_ENTERO_C.fullmatch(t.strip(ESPACIOS_ASCII)) for t in presentes):
        enteros = [None if t is None else int(t.strip(ESPACIOS_ASCII)) for t in textos]
        if all(e in _INT64 for e in enteros if e is not None) or all(
            e in _UINT64 for e in enteros if e is not None
        ):
            if len(presentes) == len(textos):
                return INT, list(enteros)
            return FLOAT, [None if e is None else float(e) for e in enteros]
        return OBJECT, list(textos)
    leidos: dict[str, Numero | None] = {}
    numeros = [
        None
        if t is None
        else leidos[t]
        if t in leidos
        else leidos.setdefault(t, numero_de_texto(t))
        for t in textos
    ]
    if all(n is not None for n, t in zip(numeros, textos, strict=True) if t is not None):
        return FLOAT, [None if n is None else float(n) for n in numeros]
    if all(t in _VERDADEROS or t in _FALSOS for t in presentes):
        valores: list[object] = [None if t is None else t in _VERDADEROS for t in textos]
        return (BOOL if len(presentes) == len(textos) else OBJECT), valores
    return OBJECT, list(textos)


def tipo_comun(tipos: Sequence[str], *, con_ausentes: bool = False) -> str:
    """El tipo de la unión de varios pedazos de una columna (`concat_compat`
    entre tramos, `pd.concat` entre archivos). `con_ausentes`: algún pedazo no
    tiene la columna y aporta NaN."""
    distintos = set(tipos)
    if OBJECT in distintos:
        comun = OBJECT
    elif len(distintos) == 1:
        comun = tipos[0]
    elif distintos <= {INT, FLOAT}:
        comun = FLOAT
    elif distintos <= {INT, BOOL}:
        comun = INT
    else:
        comun = OBJECT
    if con_ausentes:
        if comun == INT:
            return FLOAT
        if comun == BOOL:
            return OBJECT
    return comun


def convertir(valor: object, tipo: str) -> object:
    """Un valor llevado al tipo de su columna: en `float` un entero es `float`;
    en `int` un `bool` es entero; en `object` cada valor conserva el suyo."""
    if valor is None:
        return None
    if tipo == FLOAT and isinstance(valor, int | bool):
        return float(valor)
    if tipo == INT and isinstance(valor, bool):
        return int(valor)
    return valor


def _inferir_columna(textos: list[str | None], filas_por_tramo: int) -> tuple[str, list[object]]:
    tramos = [
        _inferir_tramo(textos[inicio : inicio + filas_por_tramo])
        for inicio in range(0, len(textos), filas_por_tramo)
    ]
    if not tramos:
        return FLOAT, []
    tipo = tipo_comun([t for t, _ in tramos])
    return tipo, [convertir(v, tipo) for _, valores in tramos for v in valores]


# --- Lectura de un CSV de Izipay ---------------------------------------------------


@dataclass(slots=True)
class TablaCsv:
    """Un reporte de Izipay leído como lo dejaba `read_csv`, sin las columnas
    `Unnamed`. `lineas` es la línea física de cada fila (para reportar)."""

    archivo: str
    tipo: str
    nombres: list[str]
    tipos: dict[str, str]
    columnas: dict[str, list[object]]
    lineas: list[int]


def decodificar_csv(entrada: ArchivoEntrada) -> str:
    """El texto del CSV como lo leía `read_csv`: UTF-8 estricto, sin BOM. Un
    archivo que no lo es no se pudo leer: `cero_filas`."""
    datos = entrada.ruta_temporal.read_bytes()
    try:
        return datos.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ErrorContenido.cero_filas(archivo=entrada.nombre_original) from error


def _es_linea_en_blanco(registro: Sequence[str]) -> bool:
    return not registro or (len(registro) == 1 and not registro[0].strip(" \t"))


def registros_csv(texto: str) -> Iterator[tuple[int, list[str]]]:
    """Los registros no vacíos del CSV, con la línea física donde terminan."""
    csv.field_size_limit(2**31 - 1)
    lector = csv.reader(io.StringIO(texto, newline=""))
    for registro in lector:
        if not _es_linea_en_blanco(registro):
            yield lector.line_num, registro


def encabezado_csv(texto: str) -> list[str] | None:
    """Los nombres de columna (ya con `Unnamed` y repetidos numerados)."""
    for _linea, registro in registros_csv(texto):
        return nombres_de_columnas(registro)
    return None


def leer_csv(entrada: ArchivoEntrada, tipo: str, observaciones: list[Observacion]) -> TablaCsv:
    """`pd.read_csv(ruta, dtype={...COLUMNAS_TEXTO: str})` sin las `Unnamed`."""
    archivo = entrada.nombre_original
    registros = registros_csv(decodificar_csv(entrada))
    titulo = next(registros, None)
    if titulo is None:
        raise ErrorContenido.cero_filas(archivo=archivo)
    nombres = nombres_de_columnas(titulo[1])
    ancho = len(nombres)
    crudas: list[list[str | None]] = [[] for _ in nombres]
    lineas: list[int] = []
    # Un solo objeto por texto repetido: los reportes reales repiten casi todo
    # (fechas, estados, códigos) y esto baja la memoria a la mitad.
    compartidos: dict[str, str] = {}
    for linea, registro in registros:
        if len(registro) > ancho:
            observaciones.append(
                Observacion(
                    archivo=archivo, fila=linea, motivo=MOTIVO_LINEA, valor=",".join(registro)
                )
            )
            continue
        lineas.append(linea)
        for indice in range(ancho):
            campo = registro[indice] if indice < len(registro) else None
            if campo is None or campo in NULOS:
                crudas[indice].append(None)
            else:
                crudas[indice].append(compartidos.setdefault(campo, campo))
    filas_por_tramo = _filas_por_tramo(ancho)
    tipos: dict[str, str] = {}
    columnas: dict[str, list[object]] = {}
    for indice, nombre in enumerate(nombres):
        textos, crudas[indice] = crudas[indice], []
        if nombre.startswith("Unnamed"):
            continue
        if nombre in COLUMNAS_TEXTO:
            tipos[nombre], columnas[nombre] = OBJECT, list(textos)
        else:
            tipos[nombre], columnas[nombre] = _inferir_columna(textos, filas_por_tramo)
    return TablaCsv(
        archivo=archivo,
        tipo=tipo,
        nombres=[n for n in nombres if n in columnas],
        tipos=tipos,
        columnas=columnas,
        lineas=lineas,
    )


# --- Partición por fecha y código ------------------------------------------------

_OCHO_DIGITOS: Final[re.Pattern[str]] = re.compile(r"(\d{8})")


def fecha_de_abono(valor: object) -> date | None:
    """`astype(str).str.strip().str.extract(r"(\\d{8})")` y después
    `pd.to_datetime(format="%Y%m%d", errors="coerce")`."""
    forma = _OCHO_DIGITOS.search(texto_pandas(valor).strip())
    if forma is None:
        return None
    try:
        fecha = datetime.strptime(forma.group(1), "%Y%m%d")
    except ValueError:
        return None
    return fecha.date() if en_rango_timestamp(fecha) else None


def codigo_numerico(valor: object) -> int | None:
    """`astype(float).astype(int)` sobre el `Codigo` leído como texto. `None`
    donde el script fallaba (NaN, texto, infinito)."""
    if not isinstance(valor, str):
        return None
    limpio = valor.strip()
    if "_" in limpio or not limpio.isascii():
        return None
    try:
        numero = float(limpio)
    except ValueError:
        return None
    if not math.isfinite(numero):
        return None
    return int(numero)


AjusteDeFecha = Callable[[date], date]


def ajustador_amex() -> AjusteDeFecha:
    """`ajustar_fecha_amex`: corre la fecha mientras sea sábado, domingo o
    feriado de Perú. Importa `holidays` recién acá (ver la docstring)."""
    import holidays  # perezoso: sólo cuando hay un reporte AMEX

    feriados = holidays.country_holidays("PE")

    def ajustar(fecha: date) -> date:
        while fecha in feriados or fecha.weekday() >= 5:
            fecha += timedelta(days=1)
        return fecha

    return ajustar


def _es_blanco_valor(valor: object) -> bool:
    return valor is None or (isinstance(valor, str) and not valor.strip())


@dataclass(frozen=True, slots=True)
class Tramo:
    """Las filas `indices` de `tabla` con la columna de fecha reemplazada por
    `fechas` (`"%Y%m%d"`): un `df_amex` o `df_izipay` del script."""

    tabla: TablaCsv
    indices: tuple[int, ...]
    fechas: tuple[str, ...]


def nombre_de_particion(fecha: date, tipo: str, *, antiguo: bool) -> str:
    sufijo = "" if antiguo else "-izipay"
    return f"{fecha:%Y-%m-%d}-{tipo}{sufijo}.csv"


def particionar(
    tabla: TablaCsv,
    ajustar: AjusteDeFecha | None,
    observaciones: list[Observacion],
) -> list[tuple[str, Tramo]]:
    """El cuerpo del `for archivo` de `procesar_archivos_csv`, para un archivo.

    Devuelve los tramos en el orden en que el script los agregaba al
    acumulador: fechas en orden de primera aparición y, por fecha, primero el
    del código antiguo y después el de Izipay (sólo los no vacíos).
    """
    columna = columna_de_fecha(tabla.tipo)
    valores_fecha = tabla.columnas[columna]
    codigos = tabla.columnas[COL_CODIGO]
    grupos: dict[date, tuple[list[int], list[int]]] = {}
    leidas: dict[tuple[type, object], date | None] = {}
    for indice, valor in enumerate(valores_fecha):
        clave = (type(valor), valor)
        if clave not in leidas:
            leida = fecha_de_abono(valor)
            leidas[clave] = None if leida is None else (ajustar(leida) if ajustar else leida)
        fecha = leidas[clave]
        if fecha is None:
            if not _es_blanco_valor(valor):
                observaciones.append(
                    Observacion(
                        archivo=tabla.archivo,
                        fila=tabla.lineas[indice],
                        motivo=MOTIVO_FECHA,
                        valor=renderizar_csv(valor),
                    )
                )
            continue
        codigo = codigo_numerico(codigos[indice])
        if codigo is None:
            observaciones.append(
                Observacion(
                    archivo=tabla.archivo,
                    fila=tabla.lineas[indice],
                    motivo=MOTIVO_CODIGO,
                    valor=renderizar_csv(codigos[indice]),
                )
            )
            continue
        antiguos, izipay = grupos.setdefault(fecha, ([], []))
        (antiguos if codigo == CODIGO_ANTIGUO else izipay).append(indice)
    tramos: list[tuple[str, Tramo]] = []
    for fecha, (antiguos, izipay) in grupos.items():
        texto = f"{fecha:%Y%m%d}"
        for indices, antiguo in ((antiguos, True), (izipay, False)):
            if indices:
                tramos.append(
                    (
                        nombre_de_particion(fecha, tabla.tipo, antiguo=antiguo),
                        Tramo(tabla=tabla, indices=tuple(indices), fechas=(texto,) * len(indices)),
                    )
                )
    return tramos


# --- Unión de tramos y escritura (`pd.concat` + `to_csv`) -----------------------


@dataclass(frozen=True, slots=True)
class Particion:
    """Un archivo de salida: el `pd.concat` de sus tramos."""

    nombre: str
    tramos: tuple[Tramo, ...]


def _columnas_de(particion: Particion) -> list[str]:
    columnas: list[str] = []
    vistas: set[str] = set()
    for tramo in particion.tramos:
        for nombre in tramo.tabla.nombres:
            if nombre not in vistas:
                vistas.add(nombre)
                columnas.append(nombre)
    return columnas


def _tipo_en_tramo(tramo: Tramo, nombre: str) -> str:
    return OBJECT if nombre == columna_de_fecha(tramo.tabla.tipo) else tramo.tabla.tipos[nombre]


def _tipos_de(particion: Particion, columnas: Sequence[str]) -> dict[str, str]:
    tipos: dict[str, str] = {}
    for nombre in columnas:
        presentes = [
            _tipo_en_tramo(t, nombre) for t in particion.tramos if nombre in t.tabla.columnas
        ]
        tipos[nombre] = tipo_comun(presentes, con_ausentes=len(presentes) < len(particion.tramos))
    return tipos


def _valores(tramo: Tramo, nombre: str, tipo: str) -> Iterator[object]:
    if nombre == columna_de_fecha(tramo.tabla.tipo):
        yield from tramo.fechas
        return
    columna = tramo.tabla.columnas.get(nombre)
    for indice in tramo.indices:
        yield None if columna is None else convertir(columna[indice], tipo)


def columna_renderizada(particion: Particion, nombre: str) -> list[str] | None:
    """Los textos que `to_csv` escribe en la columna `nombre`, o `None` si la
    partición no la tiene."""
    columnas = _columnas_de(particion)
    if nombre not in columnas:
        return None
    tipo = _tipos_de(particion, [nombre])[nombre]
    return [renderizar_csv(v) for tramo in particion.tramos for v in _valores(tramo, nombre, tipo)]


def renderizar(particion: Particion) -> str:
    """`pd.concat(...).to_csv(index=False)` en Windows: CRLF, comillas mínimas."""
    columnas = _columnas_de(particion)
    tipos = _tipos_de(particion, columnas)
    salida = io.StringIO(newline="")
    escritor = csv.writer(salida, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
    escritor.writerow(columnas)
    for tramo in particion.tramos:
        por_columna = [list(_valores(tramo, nombre, tipos[nombre])) for nombre in columnas]
        for fila in zip(*por_columna, strict=True):
            escritor.writerow([renderizar_csv(v) for v in fila])
    return salida.getvalue()


def acumular(tramos: Sequence[tuple[str, Tramo]]) -> list[Particion]:
    """El diccionario `acumulador` del script: un nombre por clave, en orden
    de primera aparición, con sus tramos en orden de llegada."""
    por_nombre: dict[str, list[Tramo]] = {}
    for nombre, tramo in tramos:
        por_nombre.setdefault(nombre, []).append(tramo)
    return [Particion(nombre=n, tramos=tuple(t)) for n, t in por_nombre.items()]


# --- SafetyPay -------------------------------------------------------------------

FILA_TITULOS_SAFETYPAY: Final[int] = 6
"""`header=6`: la séptima fila del libro."""
COL_FECHA_SAFETYPAY: Final[str] = "Merchant Settlement Date"
COL_LOTE: Final[str] = "Payment Batch Number"
COLUMNAS_TEXTO_SAFETYPAY: Final[tuple[str, ...]] = (
    "Operation ID",
    "Transaction ID",
    "Merchant Sales ID",
    "Merchant Order Number",
)
COLUMNAS_A_ELIMINAR: Final[tuple[str, ...]] = (
    "Type Of Operation",
    "Sale Currency",
    "Payment Country",
    "Payment Currency",
    "Payment Channel",
    "Shopper Discount Amount",
    "FX Commission Tax",
    "Total Withholding",
    "Merchant Withholding IVA",
    "Merchant Withholding Retefuente",
    "Reconciled",
    "Created By",
    "Skrill Transaction ID",
    "Merchant Settlement Date",
)
"""`columnas_a_eliminar` del script, verbatim."""

_ERRORES_EXCEL: Final[frozenset[str]] = frozenset(
    {"#DIV/0!", "#VALUE!", "#REF!", "#NAME?", "#NUM!", "#NULL!", "#N/A"}
)


@dataclass(slots=True)
class TablaSafetyPay:
    """El `DataFrame` de `read_excel(header=6, dtype=...)`. `filas` es la fila
    de Excel (desde 1) de cada fila de datos."""

    archivo: str
    nombres: list[str]
    tipos: dict[str, str]
    columnas: dict[str, list[object]]
    filas: list[int]


def _celda_leida(valor: object, tipo_dato: str) -> object:
    """`_convert_cell` + `na_values`: `None` es NaN."""
    if valor is None or tipo_dato == "e":
        return None
    convertido = celda_pandas(valor)
    if isinstance(convertido, str) and (convertido in NULOS or convertido in _ERRORES_EXCEL):
        return None
    return convertido


def filas_de_libro(hoja: ReadOnlyWorksheet, limite: int | None = None) -> list[list[object]]:
    """`get_sheet_data` del lector openpyxl de pandas: las celdas vacías al
    final de cada fila y las filas vacías al final de la hoja no cuentan, y
    las demás se completan hasta el ancho mayor. `None` es una celda que
    pandas lee como NaN."""
    hoja.reset_dimensions()
    datos: list[list[object]] = []
    ultima = -1
    for numero, fila in enumerate(hoja.rows):
        convertida = [_celda_leida(c.value, getattr(c, "data_type", "n")) for c in fila]
        crudas = [c.value for c in fila]
        while crudas and crudas[-1] is None:
            crudas.pop()
            convertida.pop()
        if crudas:
            ultima = numero
        datos.append(convertida)
        if limite is not None and len(datos) >= limite:
            break
    datos = datos[: ultima + 1]
    ancho = max((len(f) for f in datos), default=0)
    return [f + [None] * (ancho - len(f)) for f in datos]


def _numerico_python(valores: Sequence[object]) -> tuple[str, list[object]] | None:
    """`maybe_convert_numeric` del parser de Python: `None` si algún valor no
    es un número (ni un texto numérico)."""
    convertidos: list[Numero | None] = []
    hay_nulo = hay_float = False
    todos_bool = True
    for valor in valores:
        if valor is None:
            hay_nulo = True
            convertidos.append(None)
            continue
        numero: Numero | None
        if isinstance(valor, bool):
            numero = int(valor)
        elif isinstance(valor, int | float):
            todos_bool = False
            numero = valor
        elif isinstance(valor, str):
            todos_bool = False
            numero = numero_de_texto(valor)
            if numero is None:
                return None
        else:
            return None
        hay_float = hay_float or isinstance(numero, float)
        convertidos.append(numero)
    if todos_bool and not hay_nulo and convertidos:
        return BOOL, [bool(v) for v in convertidos]
    if hay_nulo or hay_float:
        return FLOAT, [None if v is None else float(v) for v in convertidos]
    return INT, list(convertidos)


def leer_safetypay(entrada: ArchivoEntrada) -> TablaSafetyPay:
    """`pd.read_excel(ruta, header=6, dtype={...COLUMNAS_TEXTO_SAFETYPAY: str})`
    de la primera hoja, leído por descriptor (los temporales no tienen
    extensión). Sin la columna de fecha es `columna_faltante`."""
    archivo = entrada.nombre_original
    with entrada.ruta_temporal.open("rb") as descriptor:
        try:
            libro = load_workbook(descriptor, read_only=True, data_only=True)
        except Exception as error:
            raise ErrorContenido.cero_filas(archivo=archivo) from error
        try:
            hoja = libro.worksheets[0] if libro.worksheets else None
            datos = filas_de_libro(hoja) if isinstance(hoja, ReadOnlyWorksheet) else []
        finally:
            libro.close()
    if len(datos) <= FILA_TITULOS_SAFETYPAY:
        raise ErrorContenido.columna_faltante(archivo=archivo, columna=COL_FECHA_SAFETYPAY)
    titulos = ["" if v is None else v for v in datos[FILA_TITULOS_SAFETYPAY]]
    nombres = nombres_de_columnas(titulos)
    if COL_FECHA_SAFETYPAY not in nombres:
        raise ErrorContenido.columna_faltante(archivo=archivo, columna=COL_FECHA_SAFETYPAY)
    filas = datos[FILA_TITULOS_SAFETYPAY + 1 :]
    tipos: dict[str, str] = {}
    columnas: dict[str, list[object]] = {}
    for indice, nombre in enumerate(nombres):
        valores = [fila[indice] for fila in filas]
        if nombre in COLUMNAS_TEXTO_SAFETYPAY:
            tipos[nombre] = OBJECT
            columnas[nombre] = [None if v is None else _texto_de_celda(v) for v in valores]
            continue
        numerico = _numerico_python(valores)
        if numerico is None:
            tipos[nombre], columnas[nombre] = OBJECT, list(valores)
        else:
            tipos[nombre], columnas[nombre] = numerico
    return TablaSafetyPay(
        archivo=archivo,
        nombres=nombres,
        tipos=tipos,
        columnas=columnas,
        filas=list(range(FILA_TITULOS_SAFETYPAY + 2, FILA_TITULOS_SAFETYPAY + 2 + len(filas))),
    )


def _texto_de_celda(valor: object) -> str:
    """`astype(str)` de un valor de Excel: `str()` (un `float` con su `repr`)."""
    return repr(valor) if isinstance(valor, float) else str(valor)


@dataclass(frozen=True, slots=True)
class LibroSafetyPay:
    """Un `{fecha}-SafetyPay.xlsx`: títulos y filas, en el orden del script."""

    nombre: str
    columnas: tuple[str, ...]
    filas: tuple[tuple[object, ...], ...]


@dataclass(slots=True)
class _Agrupado:
    filas: dict[date, list[int]] = field(default_factory=dict)


def particionar_safetypay(
    tabla: TablaSafetyPay, observaciones: list[Observacion]
) -> list[LibroSafetyPay]:
    """El resto de `procesar_archivos_excel`: filas con fecha de liquidación,
    columnas eliminadas y reordenadas, un libro por fecha en orden de fecha
    (`groupby` ordena las claves)."""
    valores_fecha = tabla.columnas[COL_FECHA_SAFETYPAY]
    fechas = fechas_de_columna(valores_fecha, dayfirst=False)
    agrupado = _Agrupado()
    for indice, (valor, fecha) in enumerate(zip(valores_fecha, fechas, strict=True)):
        if fecha is None:
            if not _es_blanco_valor(valor):
                observaciones.append(
                    Observacion(
                        archivo=tabla.archivo,
                        fila=tabla.filas[indice],
                        motivo=MOTIVO_FECHA,
                        valor=str(valor),
                    )
                )
            continue
        agrupado.filas.setdefault(fecha.date(), []).append(indice)

    columnas = [c for c in tabla.nombres if c not in COLUMNAS_A_ELIMINAR]
    if COL_LOTE in columnas:
        primera = columnas[0]
        resto = list(columnas)
        resto.remove(COL_LOTE)
        columnas = [primera, COL_LOTE, *[c for c in resto if c != primera]]

    libros: list[LibroSafetyPay] = []
    for dia in sorted(agrupado.filas):
        filas = tuple(
            tuple(_valor_excel(tabla.columnas[c][i]) for c in columnas) for i in agrupado.filas[dia]
        )
        libros.append(
            LibroSafetyPay(
                nombre=f"{dia:%Y-%m-%d}-SafetyPay.xlsx", columnas=tuple(columnas), filas=filas
            )
        )
    return libros


def _valor_excel(valor: object) -> object:
    """Lo que `to_excel` pone en la celda: NaN vacía, el resto tal cual (una
    fecha con el formato por defecto, ver `comun.escribir_xlsx`)."""
    if valor is None or (isinstance(valor, float) and math.isnan(valor)):
        return None
    return valor
