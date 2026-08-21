"""Arnés de medición y calibración (ítem #17 del backlog).

Responde con datos las tres preguntas que el PRD y el TECH-DESIGN dejaron
abiertas como suposiciones:

1. **¿Cuánto cuesta arrancar el proceso hijo?** ADR 0012 fuerza `spawn` en las
   dos plataformas, así que el intérprete reimporta el árbol de módulos entero
   en **cada** petición. El TECH-DESIGN lo estimaba en "cientos de
   milisegundos" y lo marcaba explícitamente como suposición.
2. **¿Cuál es el p95 de `Contado_Carga` de punta a punta?** El PRD fija el
   techo en 15 segundos.
3. **¿Cuánta memoria consume una ejecución?** Es la entrada que falta para
   darle a `EJECUCIONES_MAX` un valor fundado en vez de una estimación.

**No corre en la suite.** Es una herramienta, no una prueba: los números
dependen de la máquina y de su carga en ese momento, y una prueba que afirme
milisegundos concretos es una prueba intermitente esperando su turno. Lo que
sí vive en la suite es el guardián del techo de 15 s
(`tests/test_rendimiento.py`), que es el requisito del PRD y no un número
medido.

Uso:

    uv run python -m tools.medicion              # todo, con entrada sintética
    uv run python -m tools.medicion --repeticiones 30
    FIXTURES_PARIDAD=... uv run python -m tools.medicion   # usa el par real

**Lo que estas mediciones NO son.** Salen de la máquina de desarrollo
(Windows Server 2019 compartido), no de la instancia de producción, que no
existe todavía (prerrequisito #0 del backlog). Sirven para dimensionar y para
descartar sorpresas de orden de magnitud; el número final de
`EJECUCIONES_MAX` depende de la RAM de una instancia que hay que medir cuando
exista. Los resultados de la corrida que fundó los valores actuales están en
`MEDICIONES.md`.
"""

from __future__ import annotations

import argparse
import io
import json
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Final

from openpyxl import Workbook

from app.core.ejecucion import ejecutar_modulo
from app.core.tipos import ArchivoEntrada
from app.procesadores.contado_carga.modulo import COLUMNAS
from tests.paridad.manifiesto import resolver_raiz

_TIMEOUT: Final[timedelta] = timedelta(seconds=120)
_PLAZA: Final[str] = "PROSEGUR - P5 - El Pino"
_MB: Final[float] = 1024 * 1024


@dataclass(frozen=True)
class Muestras:
    """Una serie de tiempos, resumida como se la va a leer."""

    nombre: str
    valores_ms: list[float]

    @property
    def p50(self) -> float:
        return statistics.median(self.valores_ms)

    @property
    def p95(self) -> float:
        """Percentil 95 por interpolación lineal, sin dependencias.

        `statistics.quantiles` necesita al menos dos datos y reparte en
        veintiles; con pocas repeticiones da un número que sugiere más
        precisión de la que hay. Esto es explícito: se ordena y se interpola.
        """
        if len(self.valores_ms) == 1:
            return self.valores_ms[0]
        ordenados = sorted(self.valores_ms)
        posicion = 0.95 * (len(ordenados) - 1)
        bajo = int(posicion)
        alto = min(bajo + 1, len(ordenados) - 1)
        return ordenados[bajo] + (ordenados[alto] - ordenados[bajo]) * (posicion - bajo)

    def linea(self) -> str:
        return (
            f"{self.nombre:<38} n={len(self.valores_ms):>3}  "
            f"p50={self.p50:>9.1f} ms  p95={self.p95:>9.1f} ms  "
            f"min={min(self.valores_ms):>9.1f}  max={max(self.valores_ms):>9.1f}"
        )


def libro_sintetico(registros: int) -> bytes:
    """Un Excel con `registros` filas procesables, con la forma de un extracto real."""
    libro = Workbook()
    hoja = libro.active
    assert hoja is not None
    hoja.append(
        [
            COLUMNAS.fecha_contabilizacion,
            COLUMNAS.fecha_documento,
            "Clase de documento",
            COLUMNAS.referencia,
            COLUMNAS.importe,
            COLUMNAS.texto,
            COLUMNAS.fecha_entrada,
        ]
    )
    for indice in range(registros):
        hoja.append(
            [
                datetime(2026, 3, 14),
                datetime(2026, 3, 10),
                "DZ",
                4500001234 + indice,
                -1250.5 - indice,
                _PLAZA,
                datetime(2026, 3, 12),
            ]
        )
    memoria = io.BytesIO()
    libro.save(memoria)
    return memoria.getvalue()


def entrada_real() -> bytes | None:
    """El par 01 del manifiesto de paridad, si `FIXTURES_PARIDAD` está definida."""
    raiz = resolver_raiz()
    if raiz is None:
        return None
    archivo = raiz / "contado_carga" / "01_entrada.xlsx"
    return archivo.read_bytes() if archivo.is_file() else None


# --- 1. Costo de arranque del hijo ------------------------------------------


def medir_arranque(repeticiones: int) -> Muestras:
    """Tiempo de una ejecución cuyo trabajo real es despreciable.

    Se usa `passthrough` sobre un archivo de un byte: lo que queda medido es
    `spawn` más la reimportación del árbol de módulos más el ida y vuelta del
    `Pipe`, que es exactamente el costo fijo que ADR 0012 impone por petición.
    """
    with tempfile.TemporaryDirectory() as temporal:
        ruta = Path(temporal) / "entrada_0"
        ruta.write_bytes(b"x")
        entrada = ArchivoEntrada(
            nombre_original="x.txt", ruta_temporal=ruta, tamano_comprimido=1, formato="txt"
        )
        valores = []
        for _ in range(repeticiones):
            inicio = time.perf_counter()
            ejecutar_modulo(clave="passthrough", entradas=[entrada], timeout=_TIMEOUT)
            valores.append((time.perf_counter() - inicio) * 1000)
    return Muestras("arranque del hijo (trabajo ~0)", valores)


def medir_costo_de_imports() -> list[tuple[str, float]]:
    """Cuánto tarda cada pieza en importarse, en intérpretes frescos.

    Un intérprete por medición y por repetición: dentro del mismo proceso el
    segundo import es un no-op y mediría cero. Es el mismo costo que paga el
    hijo de `spawn`, que siempre arranca frío.

    Se mide `app.registry` —la cadena entera que el hijo reimporta— y después
    sus dos piezas caras por separado, para poder decir de dónde sale el
    número en vez de sólo cuál es.
    """
    objetivos = {
        "árbol completo (app.registry)": "import app.registry",
        "  └ fastapi": "import fastapi",
        "  └ openpyxl": "import openpyxl",
        "intérprete pelado (referencia)": "pass",
    }
    resultados = []
    for nombre, sentencia in objetivos.items():
        tiempos = []
        for _ in range(5):
            inicio = time.perf_counter()
            subprocess.run(  # noqa: S603 - sentencias literales de este módulo
                [sys.executable, "-c", sentencia], check=True, capture_output=True
            )
            tiempos.append((time.perf_counter() - inicio) * 1000)
        resultados.append((nombre, statistics.median(tiempos)))
    return resultados


# --- 2. Punta a punta por la ruta real --------------------------------------


def medir_punta_a_punta(contenido: bytes, repeticiones: int, etiqueta: str) -> Muestras:
    """Petición HTTP completa: multipart, token, admisión, hijo, ZIP y respuesta.

    Va por `TestClient`, que ejercita la aplicación ASGI entera en proceso. Lo
    que queda fuera es el transporte de red entre el portal y el servicio —que
    no es tiempo del servicio— y el envío del cuerpo de respuesta al cliente.
    """
    from fastapi.testclient import TestClient

    from app.main import crear_app

    valores = []
    with TestClient(crear_app()) as cliente:
        for _ in range(repeticiones):
            inicio = time.perf_counter()
            respuesta = cliente.post(
                "/interno/procesadores/contado_carga",
                files={"archivos": ("contado.xlsx", contenido, "application/octet-stream")},
                headers={"Authorization": "Bearer medicion"},
            )
            transcurrido = (time.perf_counter() - inicio) * 1000
            if respuesta.status_code != 200:
                raise RuntimeError(
                    f"la petición falló con {respuesta.status_code}: {respuesta.text}"
                )
            valores.append(transcurrido)
    return Muestras(f"punta a punta ({etiqueta})", valores)


# --- 3. Huella de memoria del hijo ------------------------------------------


@dataclass(frozen=True)
class Huella:
    """Las tres lecturas de RSS del hijo, más lo que tardó el trabajo real."""

    base_mb: float
    tras_importar_mb: float
    pico_mb: float
    trabajo_ms: float

    @property
    def arbol_mb(self) -> float:
        """Lo que cuesta el árbol de módulos: fijo por ejecución (ADR 0012)."""
        return self.tras_importar_mb - self.base_mb

    @property
    def datos_mb(self) -> float:
        """Lo que sube al procesar: lo único que escala con la entrada."""
        return self.pico_mb - self.tras_importar_mb


def medir_huella(contenido: bytes, clave: str = "contado_carga") -> Huella:
    """RSS de un intérprete fresco que importa el árbol y procesa la entrada.

    Se lanza con `subprocess` y no con `multiprocessing`: `spawn` reimporta en
    el hijo el `__main__` del padre, y el `__main__` de esta herramienta ya
    trae openpyxl, FastAPI y el árbol de `app` cargados. Medido así, el árbol
    de módulos "costaba" 0.0 MB. Ver la docstring de `tools/hijo_de_huella.py`.
    """
    with tempfile.TemporaryDirectory() as temporal:
        archivo = Path(temporal) / "entrada.xlsx"
        archivo.write_bytes(contenido)
        completado = subprocess.run(  # noqa: S603 - argumentos de este módulo
            [sys.executable, "-m", "tools.hijo_de_huella", str(archivo), clave],
            check=True,
            capture_output=True,
            text=True,
        )
    datos = json.loads(completado.stdout)
    return Huella(
        datos["base"] / _MB,
        datos["tras_importar"] / _MB,
        datos["pico"] / _MB,
        datos["trabajo_ms"],
    )


# --- 4. Comportamiento bajo concurrencia -------------------------------------


def medir_concurrencia(contenido: bytes, grados: tuple[int, ...], etiqueta: str) -> None:
    """Cómo se degrada la latencia con N ejecuciones simultáneas.

    Es la medición que decide `EJECUCIONES_MAX`, y no la de memoria. El
    trabajo del hijo —parsear un Excel con openpyxl— es CPU-bound: pasado el
    número de núcleos, subir el cupo no procesa más rápido, sólo reparte los
    mismos núcleos entre más peticiones y empeora la latencia de todas. La
    memoria acota por arriba; los núcleos acotan antes.

    `EJECUCIONES_MAX` se sube al máximo que admite el campo para que el
    semáforo no rechace durante la medición: acá se mide la degradación, no
    la admisión, que ya tiene sus propias pruebas.
    """
    import os
    from concurrent.futures import ThreadPoolExecutor

    from fastapi.testclient import TestClient

    from app.core.configuracion import obtener_configuracion
    from app.core.ejecucion import obtener_semaforo
    from app.main import crear_app

    def _olvidar_los_caches() -> None:
        """Los DOS caches, no sólo el de configuración.

        `obtener_semaforo` es otro `lru_cache(maxsize=1)` y se dimensiona con
        `ejecuciones_max` **en el momento de construirse**. Las mediciones
        anteriores de esta misma corrida ya lo dejaron armado con el valor por
        defecto, así que limpiar sólo la configuración deja en pie un semáforo
        de dos cupos y la medición de concurrencia se come un 503 a partir de
        la tercera petición. Es la trampa que documenta el fixture
        `limpiar_cache_configuracion` de `tests/conftest.py`, y caí en ella.
        """
        obtener_configuracion.cache_clear()
        obtener_semaforo.cache_clear()

    print(f"\n   entrada: {etiqueta}  ·  núcleos lógicos: {os.cpu_count()}\n")
    previo = os.environ.get("EJECUCIONES_MAX")
    os.environ["EJECUCIONES_MAX"] = "32"
    _olvidar_los_caches()
    try:
        for grado in grados:
            with TestClient(crear_app()) as cliente:

                def una_peticion() -> float:
                    inicio = time.perf_counter()
                    respuesta = cliente.post(
                        "/interno/procesadores/contado_carga",
                        files={"archivos": ("c.xlsx", contenido, "application/octet-stream")},
                        headers={"Authorization": "Bearer medicion"},
                    )
                    if respuesta.status_code != 200:
                        raise RuntimeError(f"la petición falló con {respuesta.status_code}")
                    return (time.perf_counter() - inicio) * 1000

                arranque = time.perf_counter()
                with ThreadPoolExecutor(max_workers=grado) as piscina:
                    latencias = list(piscina.map(lambda _: una_peticion(), range(grado)))
                total_s = time.perf_counter() - arranque

            muestras = Muestras(f"{grado} simultáneas", latencias)
            rendimiento = grado / total_s
            print(
                f"   {muestras.nombre:<16} p50={muestras.p50:>8.1f} ms  "
                f"p95={muestras.p95:>8.1f} ms  "
                f"total={total_s:>6.2f} s  {rendimiento:>5.2f} pet/s"
            )
    finally:
        if previo is None:
            os.environ.pop("EJECUCIONES_MAX", None)
        else:
            os.environ["EJECUCIONES_MAX"] = previo
        _olvidar_los_caches()


# --- Informe ----------------------------------------------------------------


def main() -> None:
    # El informe lleva acentos y caracteres de dibujo, y la consola de esta
    # máquina es cp1252: sin esto el `print` revienta con `UnicodeEncodeError`
    # a mitad de la salida. Es exactamente el modo de fallo de
    # `Contado_Carga.py`, que además se cae otra vez dentro de su propio
    # manejador de errores intentando imprimir un emoji. Se arregla acá, en la
    # herramienta, y no pidiéndole a quien la corra que exporte
    # `PYTHONIOENCODING`.
    for flujo in (sys.stdout, sys.stderr):
        if isinstance(flujo, io.TextIOWrapper):
            flujo.reconfigure(encoding="utf-8", errors="replace")

    analizador = argparse.ArgumentParser(description="Mediciones del ítem #17")
    analizador.add_argument("--repeticiones", type=int, default=15)
    opciones = analizador.parse_args()

    real = entrada_real()
    print("=" * 78)
    print(
        f"MEDICIÓN — {datetime.now():%Y-%m-%d %H:%M}  ·  {sys.platform}  ·  Python "
        f"{sys.version.split()[0]}"
    )
    print(f"entrada real del par 01: {'sí' if real else 'no (FIXTURES_PARIDAD sin definir)'}")
    print("=" * 78)

    print("\n1. COSTO DE ARRANQUE DEL HIJO (ADR 0012: se paga en cada petición)\n")
    print("   " + medir_arranque(opciones.repeticiones).linea())
    print("\n   De dónde sale, en intérpretes frescos:\n")
    for nombre, mediana_ms in medir_costo_de_imports():
        print(f"   {nombre:<38} {mediana_ms:>9.1f} ms")

    print("\n2. PUNTA A PUNTA POR LA RUTA REAL (PRD: p95 ≤ 15 s)\n")
    casos: list[tuple[str, bytes]] = []
    if real is not None:
        casos.append(("par 01 real, 31 registros", real))
    for registros in (100, 1000, 5000):
        casos.append((f"sintético, {registros} registros", libro_sintetico(registros)))
    for etiqueta, contenido in casos:
        muestras = medir_punta_a_punta(contenido, opciones.repeticiones, etiqueta)
        techo = " ✓" if muestras.p95 <= 15_000 else "  ¡EXCEDE EL TECHO DE 15 s!"
        print("   " + muestras.linea() + techo)

    print("\n3. HUELLA DE MEMORIA DEL HIJO (entrada para EJECUCIONES_MAX)\n")
    for etiqueta, contenido in casos:
        huella = medir_huella(contenido)
        print(
            f"   {etiqueta:<38} base={huella.base_mb:>6.1f}  "
            f"+árbol={huella.arbol_mb:>6.1f}  +datos={huella.datos_mb:>6.1f}  "
            f"= pico {huella.pico_mb:>6.1f} MB   (trabajo {huella.trabajo_ms:>7.1f} ms)"
        )

    print("\n4. CONCURRENCIA (lo que realmente acota EJECUCIONES_MAX)")
    medir_concurrencia(libro_sintetico(1000), (1, 2, 4, 8, 16), "sintético, 1000 registros")
    print()


if __name__ == "__main__":
    main()
