"""Migración de `Contado_Carga` (ítem #16; PRD "Endurecimiento obligatorio").

Traduce `Contado_Carga.py` —el script manual de la raíz del repositorio— a un
`Procesador` de este servicio. Las reglas de negocio son las de ese archivo y
esta migración **no las reinterpreta**: el layout de las tres líneas, el
mapeo de las diez plazas, el redondeo de importes y el formateo célula por
célula del TXT salen de ahí tal cual.

Lo que sí cambia, porque el PRD lo exige como requisito de la migración y no
como sugerencia:

1. **Columnas por nombre, no por posición.** El script usa `fila.iloc[1]`,
   `iloc[8]`, `iloc[13]`, `iloc[14]`. El riesgo real no es que renombren una
   columna: es que **inserten una**. Todo se corre un lugar, nada falla y la
   salida sale mal en silencio. Acá falta una columna obligatoria y la
   ejecución muere con `ErrorContenido.columna_faltante`.
2. **Fin de línea fijado explícitamente** (`FIN_DE_LINEA`), nunca heredado de
   la plataforma. Ver la nota de abajo: el valor está elegido, no confirmado.
3. **Los descartes se cuentan y se reportan.** El script tiene DOS descartes
   silenciosos, no uno: la plaza ausente del mapeo (que al menos lleva un
   contador que se imprime) y, antes que ése, **cualquiera de las tres fechas
   inválida**, que se descarta con un `continue` pelado y sin contador. Acá
   los dos se cuentan, se detallan por fila y salen en `descartes.txt`.
4. **Cero filas procesadas es `ErrorContenido.cero_filas`**, nunca un éxito
   con las manos vacías.
5. **Ninguna excepción se traga.** No hay `continue` dentro de un `except` ni
   `traceback.print_exc()`. Una fila que rompa de una forma no prevista
   levanta, y `app/core/ejecucion.py` la convierte en `FalloDelModulo`.

**Código muerto del script que NO se migró, a propósito.** `crear_linea_base()`
nunca se llama, y su layout de la primera línea está corrido una posición
respecto del que el código vivo arma inline —el propio comentario del script
lo dice: "Primera fila (sin columna 2, todo corre una posición)"—. Migrarla
habría sido migrar el layout equivocado. Tampoco se migran `fecha_ent_str` ni
`mes_str`, que el script calcula y nunca usa.

**La columna de fecha de entrada es sólo un filtro, y se conserva así.** Su
valor no entra en ninguna de las tres líneas de salida: lo único que hace es
descartar la fila cuando no parsea. Parece un descuido del script original,
pero corregirlo cambiaría **qué filas sobreviven** y por lo tanto la salida.
Se migra el comportamiento observable, no la intención supuesta.

**Verificado contra un extracto real el 2026-08-20.** Sobre el par 01 del
manifiesto de paridad —31 registros, cero descartes— este módulo produce un
TXT **idéntico byte a byte** al del script y un Excel idéntico por contenido.
Los seis nombres de `COLUMNAS` salen de la fila de encabezado de ese archivo.

**Lo que sigue sin confirmar, y no es lo mismo que lo anterior:**
`FIN_DE_LINEA` vale CRLF porque es lo que el script emite en Windows y es lo
que el sistema destino viene recibiendo. Eso está **observado** (124 CRLF,
cero LF sueltos en la salida real), pero **no confirmado con el sistema que
consume el TXT**: nadie del otro lado dijo todavía "necesito CRLF". Si el
servicio termina desplegado en un contenedor Linux, la constante ya está fija
y no hereda nada de la plataforma —que era el defecto a corregir—, pero el
valor correcto sigue siendo una pregunta abierta para el consumidor.

Este módulo importa la biblioteca estándar, `openpyxl` y —de `core/`— la
interfaz, los tipos, los errores y el registro operativo. **No importa
`app.core.db`** ni nada que lo alcance (ADR 0013), no crea procesos ni hilos,
y no tiene efecto de importación alguno.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from openpyxl import Workbook, load_workbook

from app.core.errores import ErrorContenido, ErrorTipificado
from app.core.interfaz import Procesador
from app.core.registro import configurar_logging, registrar_descartes
from app.core.tipos import ArchivoEntrada, ArchivoSalida

CLAVE: Final[str] = "contado_carga"

MAPEO_PLAZAS: Final[Mapping[str, int]] = MappingProxyType(
    {
        "PROSEGUR - P1 - Monterrico Entrada": 1101017004,
        "PROSEGUR - P2 - Monterrico Salida": 1101017004,
        "PROSEGUR - P3 - Separadora Entrada": 1101017004,
        "PROSEGUR - P4 - Santa Anita": 1101017004,
        "PROSEGUR - P5 - El Pino": 1101017094,
        "PROSEGUR - P6 - Prialé Entrada": 1101017094,
        "PROSEGUR - P7 - Prialé Salida": 1101017094,
        "PROSEGUR - P8 - Huanuco": 1101017104,
        "PROSEGUR - P9 - Puente Ejercito": 1101017104,
        "PROSEGUR - P10 - Estadio": 1101017104,
    }
)
"""Las diez plazas, con su texto EXACTO. La coincidencia es literal tras
`strip()`: no se normalizan acentos ni mayúsculas, así que "Prialé" lleva
tilde y "Huanuco" no. Cambiar eso cambiaría qué filas se procesan."""


@dataclass(frozen=True, slots=True)
class _Columnas:
    """Los seis encabezados que el módulo necesita. Ver la nota del módulo."""

    fecha_contabilizacion: str
    fecha_documento: str
    referencia: str
    importe: str
    texto: str
    fecha_entrada: str


# CONFIRMADOS contra la fila de encabezado de un extracto real
# ("PARTIDAS ABIERTAS - CONTADO.XLSX", 15 columnas, hoja "Sheet1"). Las
# posiciones coinciden exactamente con los `iloc` del script: 1, 2, 4, 8, 13
# y 14.
#
# Tres de estos seis nombres estaban antes inferidos y los tres estaban mal;
# el más instructivo es `importe`, que el comentario del script transcribe
# como "Importe en moneda doc" **sin el punto final** que el encabezado real
# sí lleva. Un carácter. Con la lectura por posición del script eso era
# invisible; con lectura por nombre, la ejecución muere con
# `columna_faltante` y nadie procesa nada con la columna equivocada. Ésa es
# exactamente la diferencia que el endurecimiento del PRD vino a comprar.
COLUMNAS: Final[_Columnas] = _Columnas(
    fecha_contabilizacion="Fe.contabilización",
    fecha_documento="Fecha de documento",
    referencia="Referencia",
    importe="Importe en moneda doc.",
    texto="Texto",
    fecha_entrada="Fecha de entrada",
)

FIN_DE_LINEA: Final[str] = "\r\n"
"""CRLF, fijado explícitamente (PRD, endurecimiento obligatorio).

**Observado, no confirmado.** La salida real del script sobre el extracto del
par 01 trae 124 CRLF y cero LF sueltos, así que CRLF es lo que el sistema
destino viene recibiendo. Lo que falta es que ese sistema confirme que lo
*exige* (BACKLOG, contexto extra del ítem 16). Fijarlo acá ya cumple el
requisito del PRD —el fin de línea no se hereda de la plataforma— y deja el
cambio en una sola línea si la respuesta es otra."""

CODIFICACION: Final[str] = "utf-8"
HOJA_DE_SALIDA: Final[str] = "Contado Lima Expresa"
COLUMNAS_POR_FILA: Final[int] = 26
UMBRAL_DE_IDENTIFICADOR: Final[float] = 1000000000
"""Por encima de este valor, un `float` entero se vuelca sin decimales: el
script asume que es un identificador y no un monto. Se migra verbatim."""

NOMBRE_XLSX: Final[str] = "resultado_contado_procesado.xlsx"
NOMBRE_TXT: Final[str] = "resultado_contado_procesado.txt"
NOMBRE_DESCARTES: Final[str] = "descartes.txt"

MIME_XLSX: Final[str] = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MIME_TEXTO: Final[str] = "text/plain; charset=utf-8"

_FORMATOS_DE_FECHA: Final[tuple[str, ...]] = (
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d.%m.%Y",
    "%d/%m/%y",
    "%Y-%m-%d",
    "%Y/%m/%d",
)
"""Formatos de texto aceptados, **día primero**, replicando el `dayfirst=True`
del script. El orden importa: `01/02/2026` es el 1 de febrero, nunca el 2 de
enero. Un `.xlsx` bien formado entrega `datetime` y no pasa por acá; esto
cubre la columna guardada como texto, que es justo el caso en que el script
original dependía de la heurística de pandas."""

MOTIVO_FECHA: Final[str] = "fecha_invalida"
MOTIVO_PLAZA: Final[str] = "plaza_no_mapeada"


@dataclass(frozen=True, slots=True)
class Descarte:
    """Una fila que no llegó a la salida, con por qué y con qué valor."""

    fila: int
    motivo: str
    valor: str


def _a_fecha(valor: object) -> date | None:
    """Equivalente de `pd.to_datetime(valor, dayfirst=True, errors='coerce')`.

    Devuelve `None` en vez de `NaT`; quien llama trata ese `None` como el
    descarte que el script hacía con un `continue`. Un valor numérico no se
    interpreta como serial de Excel a propósito: `pd.to_datetime` sobre un
    número lo lee como nanosegundos desde la época y produce basura, así que
    en el script esas filas también terminaban descartadas.
    """
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    if not isinstance(valor, str):
        return None
    texto = valor.strip()
    if not texto:
        return None
    for formato in _FORMATOS_DE_FECHA:
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            continue
    return None


def _a_importe(valor: object) -> float:
    """Equivalente de `limpiar_montos`: quita comas, y lo que no parsea es 0.

    El script encadena `astype(str).str.replace(",", "").str.strip()`,
    sustituye `""` y `"-"` por `"0"`, y remata con `to_numeric(errors='coerce')`
    más `fillna(0)`. El resultado observable es exactamente éste: todo lo que
    no sea un número reconocible cuenta como cero. Un cero silencioso es una
    decisión discutible, pero es LA decisión del script y cambiarla acá
    cambiaría importes.
    """
    texto = str(valor).replace(",", "").strip()
    if texto in {"", "-"}:
        return 0.0
    try:
        return float(texto)
    except ValueError:
        return 0.0


def _a_referencia(valor: object) -> str:
    """Un número se vuelca sin decimales; el resto, tal cual. Vacío si no hay."""
    if valor is None:
        return ""
    if isinstance(valor, bool):
        return str(valor)
    if isinstance(valor, int | float):
        return str(int(valor))
    return str(valor)


def _a_texto(valor: object) -> str:
    return "" if valor is None else str(valor)


def _celda_de_txt(celda: object) -> str:
    """Formateo célula por célula del volcado, migrado verbatim del script.

    La regla es más rara de lo que parece y se conserva entera: un `float`
    entero por encima de `UMBRAL_DE_IDENTIFICADOR` pierde los decimales
    (el script asume identificador), y **cualquier otro `float` sale con
    `str()` tal cual**, así que un importe de `1234.0` se vuelca literalmente
    `"1234.0"`. Las cuentas contables son `int`, no `float`, así que esquivan
    la rama y salen limpias. "Arreglar" esto rompe la paridad byte a byte.
    """
    if celda == "":
        return ""
    if isinstance(celda, float):
        if celda == int(celda) and celda > UMBRAL_DE_IDENTIFICADOR:
            return str(int(celda))
        return str(celda)
    return str(celda)


def _indices_de_columnas(encabezado: Sequence[object], archivo: str) -> dict[str, int]:
    """Mapa nombre → índice de las seis columnas obligatorias.

    Falla con `ErrorContenido.columna_faltante` en la PRIMERA que falte, en el
    orden en que están declaradas en `COLUMNAS`: el contexto del error nombra
    una columna, no una lista, y quien recibe el 422 arregla de a una.
    """
    posiciones = {
        str(nombre).strip(): indice
        for indice, nombre in enumerate(encabezado)
        if nombre is not None
    }
    indices: dict[str, int] = {}
    for campo in (
        COLUMNAS.fecha_contabilizacion,
        COLUMNAS.fecha_documento,
        COLUMNAS.referencia,
        COLUMNAS.importe,
        COLUMNAS.texto,
        COLUMNAS.fecha_entrada,
    ):
        if campo not in posiciones:
            raise ErrorContenido.columna_faltante(archivo=archivo, columna=campo)
        indices[campo] = posiciones[campo]
    return indices


def _celda(fila: list[Any], indice: int) -> object:
    return fila[indice] if indice < len(fila) else None


def _leer_filas(ruta: Path, archivo: str) -> tuple[list[list[Any]], dict[str, int]]:
    """Encabezado y filas de datos de la primera hoja, en modo sólo lectura.

    `read_only=True` mantiene el consumo proporcional al archivo y no al
    libro entero, que es lo que hace viable el presupuesto de 256 MB por hijo
    de ADR 0021. `data_only=True` entrega el **valor cacheado** de una
    fórmula, que es lo mismo que leía pandas.

    **Se abre un descriptor y se le pasa el objeto, nunca la ruta.** No es
    estilo: `load_workbook` valida la **extensión del nombre** antes de mirar
    un solo byte, y los temporales de `app/recepcion.py` se llaman `entrada_0`
    —sin extensión, a propósito, porque el nombre que manda el cliente jamás
    toca el disco (ADR 0020)—. Pasando la ruta, todo `.xlsx` legítimo moría
    con `InvalidFileException`, que este módulo traducía a `cero_filas`: un
    422 perfectamente formado y perfectamente equivocado. Con el descriptor
    abierto, openpyxl saltea esa comprobación y lee el contenido, que es lo
    único que decide si el archivo es un Excel. Lo destapó la prueba de punta
    a punta; ninguna prueba unitaria que pase una ruta con extensión lo ve.

    Un `.xlsx` ilegible o sin ninguna fila es error de contenido, no una
    excepción cruda: `app/core/validaciones.py` declara explícitamente que
    decidir si un archivo es un Excel válido es trabajo de este módulo.
    """
    try:
        with ruta.open("rb") as descriptor:
            libro = load_workbook(descriptor, read_only=True, data_only=True)
            try:
                hoja = libro.worksheets[0]
                filas: list[list[Any]] = [list(fila) for fila in hoja.iter_rows(values_only=True)]
            finally:
                # Antes de cerrar el descriptor: en modo `read_only` el libro
                # lee perezosamente y sigue necesitándolo mientras se itera.
                libro.close()
    except Exception as error:
        raise ErrorContenido.cero_filas(archivo=archivo) from error

    if not filas:
        raise ErrorContenido.cero_filas(archivo=archivo)
    return filas[1:], _indices_de_columnas(filas[0], archivo)


def _construir_lineas(
    importe: float, cuenta: int, texto: str, cabecera: list[Any]
) -> list[list[Any]]:
    """Las cuatro filas de un registro: las tres de datos más la separadora."""
    linea2: list[Any] = [""] * COLUMNAS_POR_FILA
    linea2[0] = 2
    linea2[12] = 15
    linea2[13] = 1001530
    linea2[17] = round(abs(importe), 2)
    linea2[25] = texto

    linea3: list[Any] = [""] * COLUMNAS_POR_FILA
    linea3[0] = 2
    linea3[12] = 40
    linea3[13] = cuenta
    linea3[17] = round(abs(importe), 2)
    linea3[25] = texto

    return [cabecera, linea2, linea3, [""] * COLUMNAS_POR_FILA]


def _procesar_fila(fila: list[Any], indices: dict[str, int]) -> list[list[Any]] | str:
    """Las cuatro filas de salida de un registro, o el motivo de su descarte."""
    fecha_contabilizacion = _a_fecha(_celda(fila, indices[COLUMNAS.fecha_contabilizacion]))
    fecha_documento = _a_fecha(_celda(fila, indices[COLUMNAS.fecha_documento]))
    fecha_entrada = _a_fecha(_celda(fila, indices[COLUMNAS.fecha_entrada]))
    # La fecha de entrada se exige y no se usa: es un filtro y nada más. Ver
    # la docstring del módulo antes de "simplificar" esta línea.
    if fecha_contabilizacion is None or fecha_documento is None or fecha_entrada is None:
        return MOTIVO_FECHA

    texto = _a_texto(_celda(fila, indices[COLUMNAS.texto]))
    cuenta = MAPEO_PLAZAS.get(texto.strip())
    if cuenta is None:
        return MOTIVO_PLAZA

    cabecera: list[Any] = [""] * COLUMNAS_POR_FILA
    cabecera[0] = 1
    cabecera[2] = "VPR1"
    cabecera[4] = fecha_contabilizacion.year
    cabecera[5] = "DZ"
    cabecera[6] = fecha_documento.strftime("%Y%m%d")
    cabecera[7] = fecha_contabilizacion.strftime("%Y%m%d")
    cabecera[8] = fecha_contabilizacion.strftime("%m")
    cabecera[9] = _a_referencia(_celda(fila, indices[COLUMNAS.referencia]))
    cabecera[10] = texto
    cabecera[11] = "PEN"

    importe = _a_importe(_celda(fila, indices[COLUMNAS.importe]))
    return _construir_lineas(importe, cuenta, texto, cabecera)


def _escribir_xlsx(filas: list[list[Any]], ruta: Path) -> None:
    """Vuelca las filas en la hoja `Contado Lima Expresa`, sin encabezado ni índice."""
    libro = Workbook(write_only=True)
    hoja = libro.create_sheet(title=HOJA_DE_SALIDA)
    for fila in filas:
        hoja.append(fila)
    libro.save(ruta)


def _escribir_txt(filas: list[list[Any]], ruta: Path) -> None:
    """Vuelca las filas separadas por tabulaciones, con `FIN_DE_LINEA` explícito.

    `newline=""` es obligatorio: sin él, Python traduce cada `\\n` según la
    plataforma y el fin de línea volvería a heredarse, que es exactamente el
    defecto que esta migración corrige.
    """
    with ruta.open("w", encoding=CODIFICACION, newline="") as salida:
        for fila in filas:
            salida.write("\t".join(_celda_de_txt(celda) for celda in fila) + FIN_DE_LINEA)


def _escribir_descartes(descartes: list[Descarte], ruta: Path) -> None:
    """Reporte de descartes, una fila por línea, con el mismo fin de línea."""
    conteo: dict[str, int] = {}
    for descarte in descartes:
        conteo[descarte.motivo] = conteo.get(descarte.motivo, 0) + 1
    resumen = ", ".join(f"{motivo}={total}" for motivo, total in sorted(conteo.items()))

    lineas = [
        f"Filas descartadas: {len(descartes)} ({resumen})",
        "",
        "\t".join(("fila", "motivo", "valor")),
    ]
    lineas.extend(
        "\t".join((str(d.fila), d.motivo, d.valor.replace("\t", " ").replace("\n", " ")))
        for d in descartes
    )
    with ruta.open("w", encoding=CODIFICACION, newline="") as salida:
        salida.write(FIN_DE_LINEA.join(lineas) + FIN_DE_LINEA)


class ContadoCarga(Procesador):
    """El procesador real: un Excel financiero entra, un Excel y un TXT salen.

    Más un `descartes.txt` cuando —y sólo cuando— hubo filas descartadas: con
    una entrada limpia la salida tiene la misma forma que la del script, y el
    ZIP no cambia. `app.core.empaquetado` decide si eso viaja suelto o
    comprimido; este módulo nunca arma un ZIP (ADR 0006).
    """

    def __init__(self, clave: str = CLAVE) -> None:
        self.clave = clave

    def validar(self, archivos: list[ArchivoEntrada]) -> ErrorTipificado | None:
        """Comprueba que el Excel se abra y traiga las seis columnas obligatorias.

        Devuelve el error en vez de levantarlo, como fija `Procesador`. Es una
        lectura completa del libro, igual que la de `procesar`: `read_only`
        hace que el costo sea el de recorrer las filas una vez más, y a cambio
        una columna faltante se rechaza antes de escribir un solo archivo.
        """
        for entrada in archivos:
            try:
                _leer_filas(entrada.ruta_temporal, entrada.nombre_original)
            except ErrorContenido as error:
                return error
        return None

    def procesar(self, archivos: list[ArchivoEntrada]) -> list[ArchivoSalida]:
        """Transforma la entrada y devuelve entre dos y tres archivos.

        Cero filas procesadas levanta `ErrorContenido.cero_filas` **antes** de
        escribir nada: nunca sale un Excel vacío ni un éxito con las manos
        vacías. Ninguna excepción se traga; una fila que rompa de una forma no
        prevista se propaga y `app/core/ejecucion.py` la convierte en
        `FalloDelModulo`.
        """
        entrada = archivos[0]
        directorio = entrada.ruta_temporal.parent
        filas_crudas, indices = _leer_filas(entrada.ruta_temporal, entrada.nombre_original)

        salida_filas: list[list[Any]] = []
        descartes: list[Descarte] = []
        for numero, fila in enumerate(filas_crudas, start=2):  # 1 es el encabezado
            valor_de_filtro = _celda(fila, indices[COLUMNAS.fecha_contabilizacion])
            if valor_de_filtro is None or valor_de_filtro == "":
                continue  # el script filtra estas filas ANTES de contar nada

            resultado = _procesar_fila(fila, indices)
            if isinstance(resultado, str):
                descartes.append(
                    Descarte(
                        fila=numero,
                        motivo=resultado,
                        valor=_a_texto(_celda(fila, indices[COLUMNAS.texto])),
                    )
                )
                continue
            salida_filas.extend(resultado)

        if not salida_filas:
            raise ErrorContenido.cero_filas(archivo=entrada.nombre_original)

        ruta_xlsx = directorio / NOMBRE_XLSX
        ruta_txt = directorio / NOMBRE_TXT
        _escribir_xlsx(salida_filas, ruta_xlsx)
        _escribir_txt(salida_filas, ruta_txt)

        salidas = [
            ArchivoSalida(
                nombre_propuesto=NOMBRE_XLSX, ruta_temporal=ruta_xlsx, tipo_mime=MIME_XLSX
            ),
            ArchivoSalida(
                nombre_propuesto=NOMBRE_TXT, ruta_temporal=ruta_txt, tipo_mime=MIME_TEXTO
            ),
        ]

        if descartes:
            ruta_descartes = directorio / NOMBRE_DESCARTES
            _escribir_descartes(descartes, ruta_descartes)
            salidas.append(
                ArchivoSalida(
                    nombre_propuesto=NOMBRE_DESCARTES,
                    ruta_temporal=ruta_descartes,
                    tipo_mime=MIME_TEXTO,
                )
            )
            # El logging se configura ACÁ y no al importar: este código corre
            # en el hijo de `spawn`, que nunca llama a `crear_app()` y por lo
            # tanto no tiene handler. Su `stderr` lo hereda del padre, así que
            # la línea sale por el mismo flujo que las del ítem #14. Configurar
            # dentro de `procesar` —jamás a nivel de módulo— es lo que mantiene
            # la promesa de `app/core/registro.py` de no tener efecto de
            # importación en la cadena que el hijo reimporta.
            configurar_logging()
            registrar_descartes(
                clave=self.clave,
                archivo=entrada.nombre_original,
                filas_procesadas=len(salida_filas) // 4,
                descartes=[(d.motivo, d.fila) for d in descartes],
            )

        return salidas
