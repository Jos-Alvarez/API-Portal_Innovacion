"""Migración de `Procesador_MediosPago_Reportes.py` — clave `medios-pago-reportes`.

Traduce el script manual que parte los reportes crudos de medios de pago por
fecha de abono:

- **Izipay** (CSV): Mastercard (`mc…`), AMEX (`movi_amex…`) y Diners
  (`servicios…`). Cada fecha de abono sale en `{fecha}-{tipo}.csv` (filas del
  comercio `4010761`) y `{fecha}-{tipo}-izipay.csv` (el resto), con
  `tipo` ∈ `mastercard`, `amex`, `dinner`. La fecha AMEX se corre fuera de
  fines de semana y feriados de Perú.
- **SafetyPay** (`MPFinancialReport*.xlsx`): un `{fecha}-SafetyPay.xlsx` por
  fecha de liquidación.

Las reglas de negocio son las del script y esta migración **no las
reinterpreta**; viven en `izipay.py` (compartido con `medios-pago-bbva-hits`)
y su docstring documenta la emulación de pandas.

**Entradas y salidas.** De uno a diez archivos, en cualquier combinación.
Varios reportes del MISMO tipo de Izipay son válidos: el script los acumulaba
en el mismo nombre de salida, y acá también. Sale un archivo por partición
más un `observaciones.txt` cuando —y sólo cuando— pasó algo que el script
salteaba o perdía en silencio. `app.core.empaquetado` arma el ZIP; este
módulo nunca lo hace (ADR 0006).

**Orden de los archivos.** El script recorría `os.listdir` de la carpeta de
entrada, que en NTFS devuelve los nombres en el orden del índice del
directorio (`comun.clave_ntfs`; ver la migración de `flujo-caja-pagos`). Ese
orden decide el de las filas acumuladas y el de los archivos de salida; acá
se ordena igual por el nombre base de `nombre_original`, y a igual nombre por
orden de subida.

Lo que cambia respecto del script, por el PRD ("Endurecimiento obligatorio"):

1. **El tipo se detecta por el contenido** (`deteccion.py`), no por
   `"mc" in nombre`. Un archivo que no es ninguno de los cuatro reportes es
   `tipo_no_reconocido` (también un extracto BBVA o un maestro de abonos, que
   son de la otra ventana).
2. **Un solo SafetyPay por ejecución.** El script procesaba sólo el PRIMER
   `MPFinancialReport` de la carpeta e ignoraba los demás sin avisar; acá un
   segundo es `tipo_duplicado`.
3. **Ninguna excepción se traga**: desaparecen los `try/except: print`. Lo no
   previsto se propaga y `app/core/ejecucion.py` lo convierte en
   `FalloDelModulo`.
4. **Las pérdidas silenciosas se reportan** en `observaciones.txt`:
   `fecha_invalida`, `codigo_invalido`, `linea_invalida` (ver `izipay.py`).
   Ninguna partición en toda la ejecución es `cero_filas`.

Este módulo importa la biblioteca estándar, `openpyxl` y —de `core/`— la
interfaz, los tipos, los errores y el registro operativo. `holidays` se
importa dentro de `procesar` y sólo con un reporte AMEX. **No importa
`app.core.db`** (ADR 0013), no crea procesos ni hilos y no tiene efecto de
importación alguno.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from app.core.errores import ErrorContenido, ErrorTipificado
from app.core.interfaz import Procesador
from app.core.registro import configurar_logging, registrar_descartes
from app.core.tipos import ArchivoEntrada, ArchivoSalida
from app.procesadores.medios_pago.comun import (
    CODIFICACION,
    MIME_CSV,
    MIME_TEXTO,
    MIME_XLSX,
    NOMBRE_OBSERVACIONES,
    Observacion,
    clave_ntfs,
    escribir_observaciones,
    escribir_xlsx,
    nombre_base,
)
from app.procesadores.medios_pago.deteccion import detectar
from app.procesadores.medios_pago.izipay import (
    TIPO_AMEX,
    TIPO_SAFETYPAY,
    TIPOS_IZIPAY,
    LibroSafetyPay,
    Particion,
    Tramo,
    acumular,
    ajustador_amex,
    leer_csv,
    leer_safetypay,
    particionar,
    particionar_safetypay,
    renderizar,
)

CLAVE: Final[str] = "medios-pago-reportes"


@dataclass(frozen=True, slots=True)
class Entrada:
    """Un archivo subido con su tipo ya detectado."""

    archivo: ArchivoEntrada
    tipo: str


def ordenar(entradas: Sequence[Entrada]) -> list[Entrada]:
    """El orden de `os.listdir` en NTFS, por nombre base; a igual nombre, el
    de subida (`sorted` es estable)."""
    return sorted(entradas, key=lambda e: clave_ntfs(nombre_base(e.archivo.nombre_original)))


def particiones_izipay(
    entradas: Sequence[Entrada], observaciones: list[Observacion]
) -> list[Particion]:
    """`procesar_archivos_csv` del script sobre los reportes de Izipay de
    `entradas` (ya ordenados): las particiones acumuladas, en el orden del
    diccionario `acumulador`."""
    izipay = [e for e in entradas if e.tipo in TIPOS_IZIPAY]
    ajustar = ajustador_amex() if any(e.tipo == TIPO_AMEX for e in izipay) else None
    tramos: list[tuple[str, Tramo]] = []
    for entrada in izipay:
        tabla = leer_csv(entrada.archivo, entrada.tipo, observaciones)
        tramos.extend(
            particionar(tabla, ajustar if entrada.tipo == TIPO_AMEX else None, observaciones)
        )
    return acumular(tramos)


def _filas_por_archivo(
    particiones: Sequence[Particion], libros: Sequence[tuple[str, LibroSafetyPay]]
) -> dict[str, int]:
    filas: dict[str, int] = {}
    for particion in particiones:
        for tramo in particion.tramos:
            filas[tramo.tabla.archivo] = filas.get(tramo.tabla.archivo, 0) + len(tramo.indices)
    for archivo, libro in libros:
        filas[archivo] = filas.get(archivo, 0) + len(libro.filas)
    return filas


def detectar_reportes(archivos: Sequence[ArchivoEntrada]) -> list[Entrada]:
    """Tipo de cada archivo; un extracto o un maestro BBVA no son de esta
    ventana, y un segundo SafetyPay es `tipo_duplicado`."""
    entradas: list[Entrada] = []
    safetypay = False
    for archivo in archivos:
        tipo = detectar(archivo)
        if tipo not in (*TIPOS_IZIPAY, TIPO_SAFETYPAY):
            raise ErrorContenido.tipo_no_reconocido(archivo=archivo.nombre_original)
        if tipo == TIPO_SAFETYPAY:
            if safetypay:
                raise ErrorContenido.tipo_duplicado(archivo=archivo.nombre_original)
            safetypay = True
        entradas.append(Entrada(archivo=archivo, tipo=tipo))
    return entradas


class MediosPagoReportes(Procesador):
    """El procesador real: de uno a diez reportes crudos entran; una partición
    por fecha (y tipo) sale.

    Más un `observaciones.txt` cuando —y sólo cuando— hubo algo que reportar.
    """

    def __init__(self, clave: str = CLAVE) -> None:
        self.clave = clave

    def validar(self, archivos: list[ArchivoEntrada]) -> ErrorTipificado | None:
        """Tipo de cada archivo y columnas que el script leía, sin leer filas.

        Devuelve el error en vez de levantarlo, como fija `Procesador`.
        """
        try:
            detectar_reportes(archivos)
        except ErrorContenido as error:
            return error
        return None

    def procesar(self, archivos: list[ArchivoEntrada]) -> list[ArchivoSalida]:
        """Calcula todo antes de escribir el primer byte, y devuelve las salidas.

        Ninguna excepción se traga; lo no previsto se propaga y
        `app/core/ejecucion.py` lo convierte en `FalloDelModulo`.
        """
        entradas = ordenar(detectar_reportes(archivos))
        observaciones: list[Observacion] = []
        particiones = particiones_izipay(entradas, observaciones)
        libros: list[tuple[str, LibroSafetyPay]] = []
        for entrada in entradas:
            if entrada.tipo == TIPO_SAFETYPAY:
                tabla = leer_safetypay(entrada.archivo)
                libros.extend(
                    (tabla.archivo, libro) for libro in particionar_safetypay(tabla, observaciones)
                )
        if not particiones and not libros:
            raise ErrorContenido.cero_filas(
                archivo=", ".join(e.archivo.nombre_original for e in entradas)
            )

        directorio = archivos[0].ruta_temporal.parent
        salidas: list[ArchivoSalida] = []
        for particion in particiones:
            ruta = directorio / particion.nombre
            _escribir_texto(ruta, renderizar(particion))
            salidas.append(
                ArchivoSalida(
                    nombre_propuesto=particion.nombre, ruta_temporal=ruta, tipo_mime=MIME_CSV
                )
            )
        for _archivo, libro in libros:
            ruta = directorio / libro.nombre
            escribir_xlsx(ruta, libro.columnas, libro.filas)
            salidas.append(
                ArchivoSalida(
                    nombre_propuesto=libro.nombre, ruta_temporal=ruta, tipo_mime=MIME_XLSX
                )
            )
        if observaciones:
            salidas.append(
                reportar(
                    self.clave,
                    directorio,
                    observaciones,
                    _filas_por_archivo(particiones, libros),
                )
            )
        return salidas


def _escribir_texto(ruta: Path, texto: str) -> None:
    with ruta.open("w", encoding=CODIFICACION, newline="") as salida:
        salida.write(texto)


def reportar(
    clave: str,
    directorio: Path,
    observaciones: Sequence[Observacion],
    filas_por_archivo: dict[str, int],
) -> ArchivoSalida:
    """Escribe `observaciones.txt` y emite una línea de log por archivo con
    observaciones.

    El logging se configura ACÁ y no al importar: este código corre en el hijo
    de `spawn`, que no hereda la configuración del padre (ver `contado_carga`).
    """
    ruta = directorio / NOMBRE_OBSERVACIONES
    escribir_observaciones(observaciones, ruta)
    configurar_logging()
    por_archivo: dict[str, list[Observacion]] = {}
    for observacion in observaciones:
        por_archivo.setdefault(observacion.archivo, []).append(observacion)
    for archivo, propias in por_archivo.items():
        registrar_descartes(
            clave=clave,
            archivo=archivo,
            filas_procesadas=filas_por_archivo.get(archivo, 0),
            descartes=[(o.motivo, o.fila or 0) for o in propias],
        )
    return ArchivoSalida(
        nombre_propuesto=NOMBRE_OBSERVACIONES, ruta_temporal=ruta, tipo_mime=MIME_TEXTO
    )
