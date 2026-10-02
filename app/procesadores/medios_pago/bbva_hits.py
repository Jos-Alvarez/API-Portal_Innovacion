"""Migración de `Procesador_BBVA_Hits.py` — clave `medios-pago-bbva-hits`.

Traduce el script manual que categoriza los abonos del extracto BBVA
(`bbva.csv_`) y los cruza contra los reportes de Izipay ya partidos por fecha.
Las reglas de negocio son las del script y esta migración **no las
reinterpreta**: lectura de las líneas `22`, `ITF`, palabras y códigos a
eliminar, categorización por código y concepto, `SALDO NEGATIVO` por importe
menor a 10, las dos pasadas de cruce, `IZI`/`ANTIGUO`, el orden de columnas,
los formatos de fecha, los nombres `HIST-*` con títulos en la fila 5 y el
intercambio `Oficina`/`Nº. Doc.` de SAFETYPAY salen de ahí tal cual.

**Entradas.** Exactamente un extracto BBVA; cero o más reportes CRUDOS de
Izipay del período (Mastercard, AMEX, Diners), y opcionalmente el maestro
anterior `Abonos_BBVA.xlsx`. Dos extractos o dos maestros son
`tipo_duplicado`; ningún extracto es `cero_filas`. Un reporte de SafetyPay se
acepta y se IGNORA: el cruce del script sólo leía los CSV de Mastercard, AMEX
y Diners, así que se puede subir el mismo lote que en `medios-pago-reportes`.

**El conjunto de cruce es sólo lo que se sube.** El script cruzaba contra
TODA la carpeta `Salida` de Reportes, con lo que hubiera ido acumulando
corrida tras corrida. Acá los reportes crudos se parten con el MISMO código
que `medios-pago-reportes` (`izipay.py`) y el cruce ve sólo esas particiones:
un abono cuyo reporte no se subió queda sin categoría Izipay. Las
particiones se recorren en el orden de NTFS de sus nombres (lo que devolvía
`os.listdir` de esa carpeta; `comun.clave_ntfs`), y el cruce ve cada valor
como lo deja la ida y vuelta por disco: escrito con `to_csv` y releído con
`read_csv(dtype=str)` (`izipay.columna_renderizada` + `numero_de_texto`).

**Salidas.** `Abonos_BBVA_CATEGORIZADO.xlsx` (el script lo dejaba en la
subcarpeta `BBVA`; acá va junto a los demás) y un `HIST-{fecha}-….xlsx` por
fecha y categoría, más un `observaciones.txt` cuando —y sólo cuando— algo se
perdió en silencio. `app.core.empaquetado` arma el ZIP.

**Rarezas del script migradas VERBATIM** —parecen errores, pero cambiarlas
cambia la salida:

- Una fila ya categorizada (VISA, SAFETYPAY…) pero con `Observacion` vacía
  sigue siendo candidata del cruce (`Descripción` vacía **o** `Observacion`
  vacía) y el cruce la recategoriza.
- La primera pasada recalcula las candidatas para cada CSV; la segunda las
  fija una vez antes de recorrerlos, así que una fila puede cruzar con varios
  CSV y gana el último.
- En la segunda pasada la fecha del CSV se corre un día atrás (tres los
  lunes): un sábado y un lunes caen en el mismo viernes y comparten contador.
- `F. Valor` sale como TEXTO `dd/mm/aaaa` con formato de fecha: el script le
  aplicaba `strptime('%Y-%m-%d')` a un texto que ya estaba en `%d/%m/%Y`.
  `F. Operación` sí sale como fecha.
- Un `HIST-*` se escribía una vez por cada fila de su grupo y el último
  pisaba a los anteriores. Para VISA el nombre no lleva la observación pero
  el filtro sí: gana el filtro de la ÚLTIMA fila de esa fecha.
- `Concepto` vacío se escribe `NAN` (`astype(str).str.upper()` de pandas 2;
  pandas 3 lo dejaría vacío). El `%#d/%m/%Y` intermedio sólo de Windows no
  se observa en la salida: se vuelve a leer con `dayfirst=True`.

**Lo que cambia respecto del script** (PRD, "Endurecimiento obligatorio"):

1. **El tipo de cada archivo se detecta por el contenido** (`deteccion.py`).
2. **Ninguna excepción se traga**; lo no previsto es `FalloDelModulo`.
3. **Pérdidas silenciosas reportadas** en `observaciones.txt`, sólo de las
   filas que llegan a la salida (una fila que un filtro descarta no cambia
   nada): `fecha_invalida` (fecha de operación ilegible o vacía: la fila no
   tiene `HIST-*` —el script se caía al nombrarlo— ni cruza),
   `importe_invalido` (importe ilegible o vacío), `numero_invalido`
   (`Nº. Doc.`, `Oficina` o `Código` ilegibles, que salen 0), y, del lado de
   Izipay, `linea_invalida`, `fecha_invalida`, `codigo_invalido` (ver
   `izipay.py`), `columna_ausente` (un reporte sin `Neto_Total` no cruza) e
   `importe_invalido` (un `Neto_Total` ilegible no cruza). Una línea `22` con
   más de once campos se descarta y se reporta (`linea_invalida`); con menos
   se completa con NaN.
4. **El maestro no se borra**: el script eliminaba `Abonos_BBVA.xlsx` al
   terminar; acá es un archivo subido y su ciclo de vida es del núcleo.

Este módulo importa la biblioteca estándar, `openpyxl` y —de `core/`— la
interfaz, los tipos, los errores y el registro operativo. **No importa
`app.core.db`** (ADR 0013), no crea procesos ni hilos y no tiene efecto de
importación alguno.
"""

from __future__ import annotations

import csv
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Final

from openpyxl import load_workbook
from openpyxl.worksheet._read_only import ReadOnlyWorksheet

from app.core.errores import ErrorContenido, ErrorTipificado
from app.core.interfaz import Procesador
from app.core.tipos import ArchivoEntrada, ArchivoSalida
from app.procesadores.medios_pago.comun import (
    MIME_XLSX,
    NULOS,
    Celda,
    Numero,
    Observacion,
    clave_ntfs,
    es_blanco,
    escribir_xlsx,
    fechas_de_columna,
    nombres_de_columnas,
    numero_de_texto,
    redondear2,
    texto_pandas,
)
from app.procesadores.medios_pago.deteccion import (
    COL_F_OPERACION,
    COL_F_OPERACION_DT,
    TIPO_BBVA,
    TIPO_MAESTRO,
    detectar,
    lineas_latin1,
)
from app.procesadores.medios_pago.izipay import (
    COL_FECHA_8DIG,
    COL_FECHA_ABONO,
    COL_NETO,
    MOTIVO_FECHA,
    TIPO_SAFETYPAY,
    TIPOS_IZIPAY,
    Particion,
    columna_renderizada,
    filas_de_libro,
)
from app.procesadores.medios_pago.reportes import (
    Entrada,
    ordenar,
    particiones_izipay,
    reportar,
)

CLAVE: Final[str] = "medios-pago-bbva-hits"

NOMBRE_CATEGORIZADO: Final[str] = "Abonos_BBVA_CATEGORIZADO.xlsx"

COLUMNAS_EXTRACTO: Final[int] = 11
"""`datos_nuevos.columns = ['a', 'b', 'Nº. Doc.', 'F. Operación', 'F. Valor',
'c', 'Código', 'd', 'Importe', 'Oficina', 'Concepto']`."""
_DOC, _FECHA, _CODIGO, _IMPORTE, _OFICINA, _CONCEPTO = 2, 3, 6, 8, 9, 10

COL_DESCRIPCION: Final[str] = "Descripción"
COL_OBSERVACION: Final[str] = "Observacion"
COL_FECHA_ABONO_BBVA: Final[str] = "FECHA (VAN Y VIENE DE ABONO)"
ORDEN_COLUMNAS: Final[tuple[str, ...]] = (
    "F. Operación",
    "F. Valor",
    "Código",
    "Importe",
    "Oficina",
    "Concepto",
    "Nº. Doc.",
    COL_DESCRIPCION,
    COL_OBSERVACION,
    COL_FECHA_ABONO_BBVA,
)
"""`orden_columnas` del script, verbatim."""

PALABRAS_ELIMINAR: Final[tuple[str, ...]] = (
    "/",
    "COMIS",
    "FIDUCIARIA",
    "SPOT MER",
    "APERTURA",
    "TRANSFERENCIA ENTRE CTAS",
    "CAPITAL/INT.PLAZO",
)
_PATRON_ELIMINAR: Final[re.Pattern[str]] = re.compile("|".join(PALABRAS_ELIMINAR))
"""`str.contains("|".join(palabras_eliminar))`: una expresión regular, como en
el script (el `.` de `INT.PLAZO` calza con cualquier carácter)."""
CODIGOS_ELIMINAR: Final[frozenset[int]] = frozenset({15, 18, 524, 612})

FORMATO_FECHA_EXCEL: Final[str] = "DD/MM/YYYY"
"""El `number_format` que `aplicar_formato_fechas_excel` fija en `F. Operación`
y `F. Valor`."""
FILA_TITULOS_HIST: Final[int] = 5
"""`startrow=4`: los títulos de cada `HIST-*` van en la fila 5."""

MOTIVO_IMPORTE: Final[str] = "importe_invalido"
MOTIVO_NUMERO: Final[str] = "numero_invalido"
MOTIVO_LINEA: Final[str] = "linea_invalida"
MOTIVO_COLUMNA: Final[str] = "columna_ausente"


# --- Lectura -------------------------------------------------------------------


@dataclass(slots=True)
class Movimiento:
    """Una fila del `df` del script. `doc`, `oficina` y `codigo` llevan lo que
    `to_numeric` haría con ellos (un texto del maestro se convierte al final,
    como en el script); `importe` todavía sin redondear en las del maestro."""

    archivo: str
    fila: int
    fecha: datetime | None
    doc: object
    codigo: Numero | None
    importe: Numero | None
    oficina: object
    concepto: str | None
    descripcion: str = ""
    observacion: str = ""
    fecha_abono: str = ""
    pendientes: list[tuple[str, str]] = field(default_factory=list)
    """Observaciones que se reportan sólo si la fila llega a la salida."""

    @property
    def dia(self) -> date | None:
        return None if self.fecha is None else self.fecha.date()


def convertir_a_datetime(texto: str | None) -> datetime | None:
    """`convertir_a_datetime` del script: `aammdd` → fecha del año 2000+aa."""
    if texto is None or len(texto) != 6:
        return None
    try:
        return datetime(2000 + int(texto[:2]), int(texto[2:4]), int(texto[4:6]))
    except ValueError:
        return None


def _sin_ceros(texto: str | None) -> tuple[Numero | None, bool]:
    """`pd.to_numeric(col.str.lstrip('0'), errors='coerce')`, y si se perdió
    algo escrito."""
    if texto is None:
        return None, False
    limpio = texto.lstrip("0")
    numero = numero_de_texto(limpio)
    return numero, numero is None and not es_blanco(limpio)


def leer_extracto(entrada: ArchivoEntrada, observaciones: list[Observacion]) -> list[Movimiento]:
    """Las líneas `22` del extracto, como las dejaba el bloque 3 del script
    (sin el filtro `ITF`, que es de `_sin_itf`)."""
    archivo = entrada.nombre_original
    movimientos: list[Movimiento] = []
    for numero, linea in enumerate(lineas_latin1(entrada.ruta_temporal.read_bytes()), 1):
        if not linea.strip().startswith("22"):
            continue
        campos: list[str | None] = list(next(csv.reader([linea])))
        if len(campos) > COLUMNAS_EXTRACTO:
            observaciones.append(
                Observacion(archivo=archivo, fila=numero, motivo=MOTIVO_LINEA, valor=linea)
            )
            continue
        campos += [None] * (COLUMNAS_EXTRACTO - len(campos))
        valores = [None if c is None or c in NULOS else c for c in campos]
        movimiento = Movimiento(
            archivo=archivo,
            fila=numero,
            fecha=convertir_a_datetime(valores[_FECHA]),
            doc=None,
            codigo=None,
            importe=None,
            oficina=None,
            concepto=valores[_CONCEPTO],
        )
        if movimiento.fecha is None:
            movimiento.pendientes.append((MOTIVO_FECHA, valores[_FECHA] or ""))
        crudo = valores[_IMPORTE]
        importe = None if crudo is None else numero_de_texto(crudo)
        movimiento.importe = None if importe is None else redondear2(float(importe) / 100.0)
        if importe is None:
            movimiento.pendientes.append((MOTIVO_IMPORTE, crudo or ""))
        for indice, atributo in ((_DOC, "doc"), (_OFICINA, "oficina"), (_CODIGO, "codigo")):
            valor, perdido = _sin_ceros(valores[indice])
            setattr(movimiento, atributo, valor)
            if perdido:
                movimiento.pendientes.append((MOTIVO_NUMERO, valores[indice] or ""))
        movimientos.append(movimiento)
    return movimientos


def _sin_itf(movimientos: list[Movimiento]) -> list[Movimiento]:
    """`~Concepto.str.upper().str.strip().eq('ITF')`: un concepto vacío se queda."""
    return [m for m in movimientos if m.concepto is None or m.concepto.upper().strip() != "ITF"]


def _texto_maestro(valor: object) -> str | None:
    """`read_excel(dtype=str)` de una celda ya convertida por `filas_de_libro`."""
    if valor is None:
        return None
    return repr(valor) if isinstance(valor, float) else str(valor)


def leer_maestro(entrada: ArchivoEntrada) -> list[Movimiento]:
    """`pd.read_excel(ruta_abonos_temp, dtype=str)` y la fecha de cada fila
    (`F. Operación_dt` si existe, si no `F. Operación`, sin `dayfirst`)."""
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
    if not datos:
        raise ErrorContenido.columna_faltante(archivo=archivo, columna=COL_F_OPERACION)
    nombres = nombres_de_columnas(["" if v is None else v for v in datos[0]])
    columna_fecha = COL_F_OPERACION_DT if COL_F_OPERACION_DT in nombres else COL_F_OPERACION
    if columna_fecha not in nombres:
        raise ErrorContenido.columna_faltante(archivo=archivo, columna=COL_F_OPERACION)
    filas = [
        {n: _texto_maestro(v) for n, v in zip(nombres, fila, strict=True)} for fila in datos[1:]
    ]
    fechas = fechas_de_columna([f[columna_fecha] for f in filas], dayfirst=False)
    movimientos: list[Movimiento] = []
    for numero, (fila, fecha) in enumerate(zip(filas, fechas, strict=True), 2):
        movimiento = Movimiento(
            archivo=archivo,
            fila=numero,
            fecha=fecha,
            doc=fila.get("Nº. Doc."),
            codigo=_numero_o_nada(fila.get("Código")),
            importe=_numero_o_nada(fila.get("Importe")),
            oficina=fila.get("Oficina"),
            concepto=fila.get("Concepto"),
            descripcion=fila.get(COL_DESCRIPCION) or "",
            observacion=fila.get(COL_OBSERVACION) or "",
            fecha_abono=fila.get(COL_FECHA_ABONO_BBVA) or "",
        )
        if fecha is None:
            movimiento.pendientes.append((MOTIVO_FECHA, fila[columna_fecha] or ""))
        for columna in ("Nº. Doc.", "Oficina", "Código"):
            texto = fila.get(columna)
            if texto is not None and numero_de_texto(texto) is None and not es_blanco(texto):
                movimiento.pendientes.append((MOTIVO_NUMERO, texto))
        movimientos.append(movimiento)
    return movimientos


def _numero_o_nada(texto: str | None) -> Numero | None:
    return None if texto is None else numero_de_texto(texto)


def _numero_final(valor: object) -> int:
    """`pd.to_numeric(col, errors='coerce').fillna(0).astype(int)`."""
    if valor is None:
        return 0
    numero = valor if isinstance(valor, int | float) else numero_de_texto(str(valor))
    return 0 if numero is None else int(numero)


# --- Categorización --------------------------------------------------------------


def categorizar(movimiento: Movimiento) -> None:
    """La categorización directa del script, en su orden (las últimas pisan)."""
    codigo = movimiento.codigo
    concepto = movimiento.concepto or ""
    if codigo == 10:
        movimiento.descripcion = "EFECTIVO"
    if codigo in (1, 17, 507):
        movimiento.descripcion = "SALDO NEGATIVO"
    if codigo == 260:
        movimiento.descripcion = "VISA"
    if "SAFTPAY" in concepto:
        movimiento.descripcion = "SAFETYPAY"
    if "COMPAÑIA DE SERV" in concepto:
        movimiento.descripcion = "AMEX"
    importe = movimiento.importe
    if importe is not None and importe < 10 and movimiento.descripcion.strip() == "":
        movimiento.descripcion = "SALDO NEGATIVO"


def filtrar_y_categorizar(movimientos: list[Movimiento]) -> list[Movimiento]:
    """Bloques 5 y 6 del script: `Concepto` en mayúsculas, filtros por
    palabra y por código, categorización y redondeo final del importe."""
    for movimiento in movimientos:
        movimiento.concepto = texto_pandas(movimiento.concepto).upper()
    quedan = [
        m
        for m in movimientos
        if not _PATRON_ELIMINAR.search(m.concepto or "") and m.codigo not in CODIGOS_ELIMINAR
    ]
    for movimiento in quedan:
        categorizar(movimiento)
        movimiento.importe = redondear2(movimiento.importe)
    return quedan


# --- Cruce -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ArchivoDeCruce:
    """Un CSV de la carpeta de cruce como lo releía el script: por fila, la
    fecha de abono y el `Neto_Total` redondeado (`None` si no se leen)."""

    nombre: str
    filas: tuple[tuple[date | None, Numero | None], ...]

    @property
    def descripcion(self) -> str:
        nombre = self.nombre.lower()
        return "MC" if "mastercard" in nombre else "AMEX" if "amex" in nombre else "DN"

    @property
    def observacion(self) -> str:
        return "IZI" if "izipay" in self.nombre.lower() else "ANTIGUO"


def _fecha_ocho(texto: str | None) -> date | None:
    """`pd.to_datetime(col, format='%Y%m%d', errors='coerce').dt.date`."""
    if texto is None or len(texto) != 8 or not texto.isdigit() or not texto.isascii():
        return None
    try:
        return datetime.strptime(texto, "%Y%m%d").date()
    except ValueError:
        return None


def archivos_de_cruce(
    particiones: Sequence[Particion], observaciones: list[Observacion]
) -> list[ArchivoDeCruce]:
    """Las particiones en el orden de NTFS de sus nombres, releídas como las
    releía el script. Un reporte crudo sin `Neto_Total` se reporta una vez
    (`columna_ausente`) y sus filas no cruzan."""
    sin_neto: dict[str, None] = {}
    cruce: list[ArchivoDeCruce] = []
    for particion in sorted(particiones, key=lambda p: clave_ntfs(p.nombre)):
        columna = COL_FECHA_ABONO if "amex" in particion.nombre.lower() else COL_FECHA_8DIG
        for tramo in particion.tramos:
            if COL_NETO not in tramo.tabla.columnas:
                sin_neto.setdefault(tramo.tabla.archivo)
        fechas = _renderizada(particion, columna)
        netos = _renderizada(particion, COL_NETO)
        if fechas is None or netos is None:
            continue
        filas: list[tuple[date | None, Numero | None]] = []
        for (fecha_texto, _o), (neto_texto, origen) in zip(fechas, netos, strict=True):
            neto = None if neto_texto is None else numero_de_texto(neto_texto)
            if neto is None and neto_texto is not None and origen is not None:
                observaciones.append(
                    Observacion(
                        archivo=origen[0], fila=origen[1], motivo=MOTIVO_IMPORTE, valor=neto_texto
                    )
                )
            filas.append((_fecha_ocho(fecha_texto), redondear2(neto)))
        cruce.append(ArchivoDeCruce(nombre=particion.nombre, filas=tuple(filas)))
    observaciones.extend(
        Observacion(archivo=a, fila=None, motivo=MOTIVO_COLUMNA, valor=COL_NETO) for a in sin_neto
    )
    return cruce


def _renderizada(
    particion: Particion, nombre: str
) -> list[tuple[str | None, tuple[str, int] | None]] | None:
    """El texto de cada fila en la columna `nombre` tras la ida y vuelta por
    `to_csv` / `read_csv(dtype=str)` (`None` es NaN), con el archivo y la
    línea de origen (`None` si la fila no tenía la columna)."""
    textos = columna_renderizada(particion, nombre)
    if textos is None:
        return None
    origenes: list[tuple[str, int] | None] = []
    for tramo in particion.tramos:
        tiene = nombre in tramo.tabla.columnas
        origenes.extend(
            (tramo.tabla.archivo, tramo.tabla.lineas[i]) if tiene else None for i in tramo.indices
        )
    return [(None if t in NULOS else t, o) for t, o in zip(textos, origenes, strict=True)]


def _contadores(
    claves: Sequence[tuple[date | None, Numero | None]],
) -> list[int | None]:
    """`groupby(['Fecha', 'Importe_MC']).cumcount()`: las filas con una clave
    NaN quedan fuera de todo grupo y nunca cruzan."""
    vistos: dict[tuple[date, Numero], int] = {}
    contadores: list[int | None] = []
    for fecha, importe in claves:
        if fecha is None or importe is None:
            contadores.append(None)
            continue
        clave = (fecha, importe)
        contadores.append(vistos.get(clave, 0))
        vistos[clave] = vistos.get(clave, 0) + 1
    return contadores


def _es_candidato(movimiento: Movimiento) -> bool:
    return movimiento.descripcion.strip() == "" or movimiento.observacion.strip() == ""


def _claves_de_candidatos(
    movimientos: Sequence[Movimiento],
) -> list[tuple[Movimiento, tuple[date, Numero, int] | None]]:
    candidatos = [m for m in movimientos if _es_candidato(m)]
    contadores = _contadores([(m.dia, m.importe) for m in candidatos])
    claves: list[tuple[Movimiento, tuple[date, Numero, int] | None]] = []
    for movimiento, contador in zip(candidatos, contadores, strict=True):
        if contador is None or movimiento.dia is None or movimiento.importe is None:
            claves.append((movimiento, None))
        else:
            claves.append((movimiento, (movimiento.dia, movimiento.importe, contador)))
    return claves


def _filas_validas(archivo: ArchivoDeCruce) -> list[tuple[date | None, Numero]]:
    """`df_csv[Importe_MC.notna() & (Importe_MC != 0)]`."""
    return [(f, i) for f, i in archivo.filas if i is not None and i != 0]


def primera_pasada(movimientos: Sequence[Movimiento], cruce: Sequence[ArchivoDeCruce]) -> None:
    """Bloque 7: por cada CSV, las candidatas DE ESE MOMENTO cruzadas por
    fecha, importe y número de aparición."""
    for archivo in cruce:
        filas = _filas_validas(archivo)
        contadores = _contadores(filas)
        claves_csv = {
            (f, i, c) for (f, i), c in zip(filas, contadores, strict=True) if c is not None
        }
        for movimiento, clave in _claves_de_candidatos(movimientos):
            if clave is not None and clave in claves_csv:
                movimiento.descripcion = archivo.descripcion
                movimiento.observacion = archivo.observacion


def fecha_corrida(fecha: date) -> date:
    """La fecha del CSV en la segunda pasada: tres días atrás un lunes, uno
    cualquier otro día."""
    return fecha - timedelta(days=3) if fecha.weekday() == 0 else fecha - timedelta(days=1)


def segunda_pasada(movimientos: Sequence[Movimiento], cruce: Sequence[ArchivoDeCruce]) -> None:
    """Bloque 8: candidatas fijadas UNA vez; cada CSV con su fecha corrida.
    Gana el último CSV que cruce, y deja su fecha original en `FECHA (VAN Y
    VIENE DE ABONO)`."""
    candidatas = _claves_de_candidatos(movimientos)
    for archivo in cruce:
        filas = _filas_validas(archivo)
        corridas = [(None if f is None else fecha_corrida(f), i) for f, i in filas]
        contadores = _contadores(corridas)
        originales: dict[tuple[date, Numero, int], date] = {}
        for (corrida, importe), (original, _i), contador in zip(
            corridas, filas, contadores, strict=True
        ):
            if corrida is not None and original is not None and contador is not None:
                originales[(corrida, importe, contador)] = original
        for movimiento, clave in candidatas:
            if clave is not None and clave in originales:
                movimiento.descripcion = archivo.descripcion
                movimiento.observacion = archivo.observacion
                movimiento.fecha_abono = f"{originales[clave]:%d/%m/%Y}"


# --- Salidas -------------------------------------------------------------------------


def _fila_de_salida(movimiento: Movimiento, importe_float: bool) -> list[object]:
    """Una fila en `ORDEN_COLUMNAS`, ya con el formato de
    `aplicar_formato_fechas_excel`."""
    dia = movimiento.dia
    importe = movimiento.importe
    if importe_float and isinstance(importe, int):
        importe = float(importe)
    return [
        None if dia is None else Celda(datetime(dia.year, dia.month, dia.day), FORMATO_FECHA_EXCEL),
        None if dia is None else Celda(f"{dia:%d/%m/%Y}", FORMATO_FECHA_EXCEL),
        _numero_final(movimiento.codigo),
        importe,
        _numero_final(movimiento.oficina),
        movimiento.concepto,
        _numero_final(movimiento.doc),
        movimiento.descripcion,
        movimiento.observacion,
        movimiento.fecha_abono,
    ]


_IDX_OFICINA: Final[int] = ORDEN_COLUMNAS.index("Oficina")
_IDX_DOC: Final[int] = ORDEN_COLUMNAS.index("Nº. Doc.")


def nombre_hist(movimiento: Movimiento) -> str | None:
    """El nombre del `HIST-*` de una fila categorizada, o `None` si no tiene."""
    dia = movimiento.dia
    if dia is None:
        return None
    descripcion, observacion = movimiento.descripcion, movimiento.observacion
    if descripcion in ("MC", "DN", "AMEX") and observacion in ("IZI", "ANTIGUO"):
        return f"HIST-{dia:%Y-%m-%d}-{descripcion}-{observacion}.xlsx"
    if descripcion == "SAFETYPAY":
        return f"HIST-{dia:%Y-%m-%d}-SP.xlsx"
    if descripcion == "VISA":
        return f"HIST-{dia:%Y-%m-%d}-VISA.xlsx"
    return None


@dataclass(frozen=True, slots=True)
class LibroHist:
    nombre: str
    filas: tuple[list[object], ...]


def libros_hist(movimientos: Sequence[Movimiento], importe_float: bool) -> list[LibroHist]:
    """Bloque 12: un libro por nombre, en orden de primera aparición, con el
    filtro de la ÚLTIMA fila que lo escribió (la última escritura gana)."""
    ultimos: dict[str, Movimiento] = {}
    for movimiento in movimientos:
        if movimiento.descripcion.strip() == "":
            continue
        nombre = nombre_hist(movimiento)
        if nombre is not None:
            ultimos[nombre] = movimiento
    libros: list[LibroHist] = []
    for nombre, ultimo in ultimos.items():
        filas: list[list[object]] = []
        for movimiento in movimientos:
            if movimiento.dia != ultimo.dia or movimiento.descripcion != ultimo.descripcion:
                continue
            if ultimo.descripcion != "SAFETYPAY" and movimiento.observacion != ultimo.observacion:
                continue
            fila = _fila_de_salida(movimiento, importe_float)
            if ultimo.descripcion == "SAFETYPAY":
                fila[_IDX_OFICINA], fila[_IDX_DOC] = fila[_IDX_DOC], fila[_IDX_OFICINA]
            filas.append(fila)
        libros.append(LibroHist(nombre=nombre, filas=tuple(filas)))
    return libros


# --- Procesador ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Lote:
    extracto: ArchivoEntrada
    maestro: ArchivoEntrada | None
    izipay: tuple[Entrada, ...]


def clasificar(archivos: Sequence[ArchivoEntrada]) -> _Lote:
    """Tipo de cada archivo y la composición del lote."""
    extracto: ArchivoEntrada | None = None
    maestro: ArchivoEntrada | None = None
    izipay: list[Entrada] = []
    for archivo in archivos:
        tipo = detectar(archivo)
        if tipo == TIPO_BBVA:
            if extracto is not None:
                raise ErrorContenido.tipo_duplicado(archivo=archivo.nombre_original)
            extracto = archivo
        elif tipo == TIPO_MAESTRO:
            if maestro is not None:
                raise ErrorContenido.tipo_duplicado(archivo=archivo.nombre_original)
            maestro = archivo
        elif tipo in TIPOS_IZIPAY:
            izipay.append(Entrada(archivo=archivo, tipo=tipo))
        elif tipo != TIPO_SAFETYPAY:  # pragma: no cover - `detectar` no devuelve otro
            raise ErrorContenido.tipo_no_reconocido(archivo=archivo.nombre_original)
    if extracto is None:
        raise ErrorContenido.cero_filas(archivo=", ".join(a.nombre_original for a in archivos))
    return _Lote(extracto=extracto, maestro=maestro, izipay=tuple(ordenar(izipay)))


def _con_maestro(nuevos: list[Movimiento], maestro: list[Movimiento]) -> list[Movimiento]:
    """Bloque 4: las fechas del maestro mandan; los movimientos nuevos de esas
    fechas se descartan y el resto va DESPUÉS del maestro."""
    fechas = {m.dia for m in maestro if m.dia is not None}
    return [*maestro, *(m for m in nuevos if m.dia is None or m.dia not in fechas)]


class MediosPagoBbvaHits(Procesador):
    """El procesador real: un extracto BBVA (más reportes de Izipay y un
    maestro opcionales) entra; el categorizado y los `HIST-*` salen."""

    def __init__(self, clave: str = CLAVE) -> None:
        self.clave = clave

    def validar(self, archivos: list[ArchivoEntrada]) -> ErrorTipificado | None:
        """Tipo de cada archivo y composición del lote, sin leer filas.

        Devuelve el error en vez de levantarlo, como fija `Procesador`.
        """
        try:
            clasificar(archivos)
        except ErrorContenido as error:
            return error
        return None

    def procesar(self, archivos: list[ArchivoEntrada]) -> list[ArchivoSalida]:
        """Calcula todo antes de escribir el primer byte, y devuelve las salidas.

        Ninguna excepción se traga; lo no previsto se propaga y
        `app/core/ejecucion.py` lo convierte en `FalloDelModulo`.
        """
        lote = clasificar(archivos)
        observaciones: list[Observacion] = []
        movimientos = _sin_itf(leer_extracto(lote.extracto, observaciones))
        if lote.maestro is not None:
            movimientos = _con_maestro(movimientos, leer_maestro(lote.maestro))
        movimientos = filtrar_y_categorizar(movimientos)
        if not movimientos:
            raise ErrorContenido.cero_filas(archivo=lote.extracto.nombre_original)

        cruce = archivos_de_cruce(particiones_izipay(lote.izipay, observaciones), observaciones)
        primera_pasada(movimientos, cruce)
        segunda_pasada(movimientos, cruce)

        for movimiento in movimientos:
            for motivo, valor in movimiento.pendientes:
                observaciones.append(
                    Observacion(
                        archivo=movimiento.archivo, fila=movimiento.fila, motivo=motivo, valor=valor
                    )
                )

        importe_float = any(isinstance(m.importe, float) for m in movimientos)
        directorio = archivos[0].ruta_temporal.parent
        ruta = directorio / NOMBRE_CATEGORIZADO
        escribir_xlsx(
            ruta, ORDEN_COLUMNAS, (_fila_de_salida(m, importe_float) for m in movimientos)
        )
        salidas = [
            ArchivoSalida(
                nombre_propuesto=NOMBRE_CATEGORIZADO, ruta_temporal=ruta, tipo_mime=MIME_XLSX
            )
        ]
        for libro in libros_hist(movimientos, importe_float):
            ruta = directorio / libro.nombre
            escribir_xlsx(ruta, ORDEN_COLUMNAS, libro.filas, fila_titulos=FILA_TITULOS_HIST)
            salidas.append(
                ArchivoSalida(
                    nombre_propuesto=libro.nombre, ruta_temporal=ruta, tipo_mime=MIME_XLSX
                )
            )
        if observaciones:
            filas: dict[str, int] = {}
            for movimiento in movimientos:
                filas[movimiento.archivo] = filas.get(movimiento.archivo, 0) + 1
            salidas.append(reportar(self.clave, directorio, observaciones, filas))
        return salidas
