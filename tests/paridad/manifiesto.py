"""Manifiesto de fixtures de paridad y su compuerta (ítem #15; ADR 0015).

Los pares reales de entrada/salida **no viven en este repositorio**: son
extractos financieros de Lima Expresa y versionarlos los dejaría en el
historial de Git de forma irreversible. Viven en un recurso compartido
interno y el repositorio guarda sólo este manifiesto: nombres, `sha256` y
—obligatoria— la procedencia de cada salida esperada.

**Las tres reglas de ADR 0015, y por qué no comparten severidad.** No es una
escala de gustos; cada nivel responde a un modo de falla distinto:

1. **Manifiesto mal formado o par sin procedencia completa → falla SIEMPRE**,
   en CI y en local. Es el contrato de la prueba y no depende de tener los
   archivos a mano. Si el manifiesto aceptara pares a medias, la exigencia se
   degradaría a una convención y volvería el problema que vino a resolver.
2. **Fixture presente pero con `sha256` distinto → falla SIEMPRE.** Es la
   barrera contra el peor fallo de esta clase de pruebas: ajustar el archivo
   de referencia hasta que la prueba pase. Que estés en tu máquina no la
   levanta.
3. **Fixtures ausentes (variable sin definir, recurso no montado) → falla en
   CI, saltea en local con aviso explícito.** Es el único caso que ADR 0015
   autoriza a saltear, y sólo porque quien recién clona el repositorio
   todavía no tiene acceso al recurso compartido.

**Cómo se distingue "CI" de "local", que es una decisión y conviene decirla:**
por la variable de entorno `CI`, la convención que fijan solos GitHub
Actions, GitLab CI, CircleCI y Jenkins. Este repositorio **no tiene hoy
ningún workflow de CI** —la compuerta real es `uv run pytest` en la máquina
de quien programa—, así que en la práctica la rama que hoy se recorre es
siempre la del salto. Eso no vuelve inútil la regla: la deja puesta para el
día que exista un runner, en vez de tener que acordarse entonces. Lo que sí
importa es que el salto **grite**: `warnings.warn` más `pytest.skip`, para
que aparezca en el resumen de warnings y no sólo como una `s` en la línea de
puntos.

**`FIXTURES_PARIDAD` no puede apuntar adentro del repositorio.** Es la única
promesa de ADR 0015 que un descuido de configuración puede romper de forma
irreversible: basta con "acomodar" la carpeta compartida dentro del árbol de
trabajo y que un `git add` la arrastre al historial. La comprobación es
barata y falla siempre, en CI y en local.
"""

from __future__ import annotations

import os
import re
import tomllib
import warnings
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Final

import pytest

_RAIZ_DEL_REPOSITORIO: Final[Path] = Path(__file__).resolve().parent.parent.parent
MANIFIESTO: Final[Path] = Path(__file__).resolve().parent / "manifiesto.toml"
VARIABLE_DE_UBICACION: Final[str] = "FIXTURES_PARIDAD"

_HASH: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_VERSION_DE_SCRIPT: Final[re.Pattern[str]] = re.compile(r"^sha256:[0-9a-f]{64}$")
_FINES_DE_LINEA: Final[frozenset[str]] = frozenset({"CRLF", "LF"})
_CAMPOS_DE_PROCEDENCIA: Final[tuple[str, ...]] = (
    "generado_por",
    "version_script",
    "generado_el",
    "generado_en",
    "fin_de_linea",
)
_TROZO: Final[int] = 1024 * 1024


class ManifiestoInvalido(RuntimeError):
    """El manifiesto no cumple el contrato de ADR 0015. Falla en CI y en local."""


class FixtureAlterado(RuntimeError):
    """Un fixture existe pero su `sha256` no es el declarado. Falla en CI y en local."""


@dataclass(frozen=True)
class Procedencia:
    """De dónde salió una salida esperada. Un hash dice que no cambió; esto, de dónde vino."""

    generado_por: str
    version_script: str
    generado_el: date
    generado_en: str
    fin_de_linea: str


@dataclass(frozen=True)
class ParDeParidad:
    """Un par de fixtures con su procedencia.

    `archivos` va como mapa y no como tres campos fijos a propósito: ADR 0015
    cierra con "la misma mecánica sirve para los otros dos procesadores", y
    ninguno de ellos tiene por qué producir un `.txt` y un `.xlsx`. Lo que se
    exige es la forma —al menos una entrada y al menos una salida—, no los
    nombres que le tocaron a `Contado_Carga`.
    """

    id: str
    archivos: dict[str, str]
    hashes: dict[str, str]
    procedencia: Procedencia


def _exigir(condicion: object, mensaje: str) -> None:
    if not condicion:
        raise ManifiestoInvalido(mensaje)


def _texto(datos: dict[str, object], clave: str, donde: str) -> str:
    valor = datos.get(clave)
    _exigir(isinstance(valor, str) and valor.strip(), f"{donde}: '{clave}' ausente o vacío")
    assert isinstance(valor, str)  # ya verificado por _exigir; estrecha el tipo para mypy
    return valor


def _nombre_de_archivo(valor: str, donde: str) -> str:
    """Nombre suelto, nunca una ruta.

    El manifiesto es un archivo de configuración y su valor se concatena a una
    raíz: separadores o `..` acá saldrían del directorio del procesador. Es la
    misma disciplina que `app/recepcion.py` aplica sobre el nombre que declara
    el cliente, por el mismo motivo.
    """
    _exigir(
        valor == Path(valor).name and valor not in {"", ".", ".."},
        f"{donde}: '{valor}' debe ser un nombre de archivo suelto, sin separadores ni '..'",
    )
    return valor


def _procedencia(datos: object, donde: str) -> Procedencia:
    _exigir(isinstance(datos, dict), f"{donde}: falta el bloque [procedencia], que es obligatorio")
    assert isinstance(datos, dict)
    faltantes = [campo for campo in _CAMPOS_DE_PROCEDENCIA if campo not in datos]
    _exigir(not faltantes, f"{donde}: procedencia incompleta, faltan {faltantes}")

    generado_el = datos["generado_el"]
    _exigir(
        isinstance(generado_el, date),
        f"{donde}: 'generado_el' debe ser una fecha TOML nativa (2026-08-14), no texto",
    )
    assert isinstance(generado_el, date)

    version_script = _texto(datos, "version_script", donde)
    _exigir(
        _VERSION_DE_SCRIPT.match(version_script),
        f"{donde}: 'version_script' debe ser 'sha256:<64 hex>' — el script manual no está "
        "versionado y el hash del .py que corrió es el único identificador que no se confunde",
    )

    fin_de_linea = _texto(datos, "fin_de_linea", donde)
    _exigir(
        fin_de_linea in _FINES_DE_LINEA,
        f"{donde}: 'fin_de_linea' debe ser uno de {sorted(_FINES_DE_LINEA)}, observado del "
        f"archivo real, no asumido; llegó {fin_de_linea!r}",
    )

    return Procedencia(
        generado_por=_texto(datos, "generado_por", donde),
        version_script=version_script,
        generado_el=generado_el,
        generado_en=_texto(datos, "generado_en", donde),
        fin_de_linea=fin_de_linea,
    )


def _par(datos: object, procesador: str, posicion: int) -> ParDeParidad:
    donde = f"[{procesador}] par #{posicion}"
    _exigir(isinstance(datos, dict), f"{donde}: cada par debe ser una tabla")
    assert isinstance(datos, dict)

    identificador = _texto(datos, "id", donde)
    donde = f"[{procesador}] par {identificador!r}"

    archivos: dict[str, str] = {}
    hashes: dict[str, str] = {}
    for papel, valor in datos.items():
        if papel in {"id", "procedencia"}:
            continue
        _exigir(isinstance(valor, dict), f"{donde}: '{papel}' debe ser una tabla archivo/sha256")
        assert isinstance(valor, dict)
        contexto = f"{donde}.{papel}"
        nombre = _nombre_de_archivo(_texto(valor, "archivo", contexto), contexto)
        digesto = _texto(valor, "sha256", contexto)
        _exigir(
            _HASH.match(digesto),
            f"{donde}.{papel}: 'sha256' debe ser 64 dígitos hexadecimales en minúscula",
        )
        archivos[papel] = nombre
        hashes[papel] = digesto

    _exigir(
        any(papel.startswith("entrada") for papel in archivos),
        f"{donde}: no declara ninguna entrada",
    )
    _exigir(
        any(papel.startswith("salida") for papel in archivos),
        f"{donde}: no declara ninguna salida esperada",
    )

    return ParDeParidad(
        id=identificador,
        archivos=archivos,
        hashes=hashes,
        procedencia=_procedencia(datos.get("procedencia"), donde),
    )


def cargar_manifiesto(ruta: Path | None = None) -> dict[str, list[ParDeParidad]]:
    """Lee y valida el manifiesto entero. Cualquier defecto es `ManifiestoInvalido`.

    Se valida el archivo completo, no sólo la sección que el llamador pide:
    un par roto de otro procesador es igual de inaceptable y descubrirlo recién
    cuando alguien corra esa suite sería enterarse tarde.
    """
    ruta = ruta or MANIFIESTO
    _exigir(ruta.is_file(), f"no existe el manifiesto {ruta}")
    try:
        crudo = tomllib.loads(ruta.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise ManifiestoInvalido(f"{ruta} no es TOML válido: {error}") from error

    secciones: dict[str, list[ParDeParidad]] = {}
    for procesador, contenido in crudo.items():
        _exigir(isinstance(contenido, dict), f"[{procesador}]: debe ser una tabla")
        assert isinstance(contenido, dict)
        pares = contenido.get("pares", [])
        _exigir(isinstance(pares, list), f"[{procesador}]: 'pares' debe ser un arreglo de tablas")
        assert isinstance(pares, list)
        interpretados = [_par(datos, procesador, posicion) for posicion, datos in enumerate(pares)]
        identificadores = [par.id for par in interpretados]
        repetidos = sorted({i for i in identificadores if identificadores.count(i) > 1})
        _exigir(not repetidos, f"[{procesador}]: ids de par repetidos {repetidos}")
        secciones[procesador] = interpretados
    return secciones


def resolver_raiz() -> Path | None:
    """Raíz del recurso compartido según `FIXTURES_PARIDAD`, o `None` si no está definida."""
    crudo = os.environ.get(VARIABLE_DE_UBICACION, "").strip()
    if not crudo:
        return None
    raiz = Path(crudo).expanduser()
    try:
        adentro = raiz.resolve().is_relative_to(_RAIZ_DEL_REPOSITORIO)
    except OSError:  # una UNC no montada no se puede resolver, y no está adentro
        adentro = False
    if adentro:
        raise ManifiestoInvalido(
            f"{VARIABLE_DE_UBICACION}={crudo} apunta adentro del repositorio. Los pares reales "
            "viven fuera (ADR 0015): un 'git add' distraído los dejaría en el historial de "
            "forma irreversible."
        )
    return raiz


def en_ci() -> bool:
    """`True` cuando corre en un runner de integración continua.

    Por la variable `CI`, que GitHub Actions, GitLab CI, CircleCI y Jenkins
    fijan sin que haya que configurarlos. Hoy este repositorio no tiene
    ninguno: la rama que se recorre en la práctica es la otra.
    """
    return os.environ.get("CI", "").strip().lower() not in {"", "0", "false", "no"}


def _sin_fixtures(motivo: str) -> None:
    """Único desenlace que ADR 0015 autoriza a saltear, y sólo fuera de CI."""
    if en_ci():
        pytest.fail(
            f"{motivo} En CI la ausencia de fixtures de paridad es un fallo, nunca un salto: "
            "una prueba que se saltea en silencio da luz verde sin haber probado nada "
            "(ADR 0015)."
        )
    aviso = (
        f"PARIDAD NO VERIFICADA. {motivo} Se saltea porque esto no es CI. "
        f"Definí {VARIABLE_DE_UBICACION} apuntando al recurso compartido para correrla; "
        "ver la sección 'Parity fixtures' del README."
    )
    warnings.warn(aviso, UserWarning, stacklevel=3)
    pytest.skip(aviso)


def _digesto(ruta: Path) -> str:
    acumulador = sha256()
    with ruta.open("rb") as archivo:
        while trozo := archivo.read(_TROZO):
            acumulador.update(trozo)
    return acumulador.hexdigest()


def exigir_pares(procesador: str, *, manifiesto: Path | None = None) -> list[ParDeParidad]:
    """Devuelve los pares verificados de `procesador`, o corta la prueba.

    Compuerta completa y en este orden, que es el de severidad decreciente:
    manifiesto válido y sección presente (falla siempre), ubicación fuera del
    repositorio (falla siempre), fixtures presentes (falla en CI, saltea en
    local con aviso) y `sha256` coincidente (falla siempre).

    Que el hash se verifique acá y no dentro de cada prueba de paridad es
    deliberado: ADR 0015 lo pide *antes* de comparar, para que un archivo de
    referencia retocado falle por hash y no por contenido.
    """
    secciones = cargar_manifiesto(manifiesto)
    pares = secciones.get(procesador)
    _exigir(pares is not None, f"el manifiesto no tiene sección [{procesador}]")
    assert pares is not None
    _exigir(pares, f"[{procesador}]: la sección no declara ningún par")

    raiz = resolver_raiz()
    if raiz is None:
        _sin_fixtures(f"{VARIABLE_DE_UBICACION} no está definida.")
        raise AssertionError("inalcanzable: _sin_fixtures siempre corta")  # pragma: no cover
    directorio = raiz / procesador
    if not directorio.is_dir():
        _sin_fixtures(f"no existe el directorio de fixtures {directorio}.")

    ausentes = [
        f"{par.id}/{papel}={nombre}"
        for par in pares
        for papel, nombre in par.archivos.items()
        if not (directorio / nombre).is_file()
    ]
    if ausentes:
        _sin_fixtures(f"faltan fixtures en {directorio}: {ausentes}.")

    alterados = [
        f"{par.id}/{papel}={nombre} (declarado {par.hashes[papel]}, real {real})"
        for par in pares
        for papel, nombre in par.archivos.items()
        if (real := _digesto(directorio / nombre)) != par.hashes[papel]
    ]
    if alterados:
        raise FixtureAlterado(
            f"[{procesador}] el sha256 no coincide con el manifiesto: {alterados}. "
            "Un fixture de referencia no se 'arregla' para que la prueba pase: se reemplaza "
            "en el recurso compartido y se actualizan su hash Y su procedencia, en un cambio "
            "revisable (ADR 0015)."
        )
    return pares
