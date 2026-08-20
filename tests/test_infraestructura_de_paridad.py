"""Pruebas de la maquinaria de fixtures de paridad (ítem #15; ADR 0015).

Estas pruebas no tocan ningún fixture real: arman manifiestos y directorios
sintéticos en `tmp_path`. Es a propósito y no es una comodidad. Los pares
reales son extractos financieros que no están en este repositorio ni pueden
estarlo, así que si la maquinaria sólo se pudiera probar con ellos, no se
podría probar nunca — que es exactamente la clase de infraestructura que
llega rota al día en que hace falta.

Lo que se verifica es la tabla de severidades de ADR 0015: qué falla siempre,
qué saltea sólo fuera de CI, y que el salto grite.
"""

from __future__ import annotations

import textwrap
from hashlib import sha256
from pathlib import Path

import pytest

from tests.paridad.manifiesto import (
    VARIABLE_DE_UBICACION,
    FixtureAlterado,
    ManifiestoInvalido,
    cargar_manifiesto,
    en_ci,
    exigir_pares,
    resolver_raiz,
)

_PROCEDENCIA_COMPLETA = """
  [contado_carga.pares.procedencia]
  generado_por   = "Contado_Carga.py"
  version_script = "sha256:{script}"
  generado_el    = 2026-08-14
  generado_en    = "Windows Server 2019 / Python 3.11.9"
  fin_de_linea   = "CRLF"
"""


def _hash(contenido: bytes) -> str:
    return sha256(contenido).hexdigest()


def _manifiesto(tmp_path: Path, cuerpo: str) -> Path:
    ruta = tmp_path / "manifiesto.toml"
    ruta.write_text(textwrap.dedent(cuerpo), encoding="utf-8")
    return ruta


def _par_valido(
    *,
    entrada: bytes = b"entrada",
    salida: bytes = b"salida",
    procedencia: str | None = None,
    identificador: str = "01",
) -> str:
    bloque = _PROCEDENCIA_COMPLETA.format(script="b" * 64) if procedencia is None else procedencia
    return (
        "[[contado_carga.pares]]\n"
        f'id          = "{identificador}"\n'
        f'entrada     = {{ archivo = "{identificador}_entrada.xlsx", '
        f'sha256 = "{_hash(entrada)}" }}\n'
        f'salida_txt  = {{ archivo = "{identificador}_salida.txt", '
        f'sha256 = "{_hash(salida)}" }}\n'
        f"{bloque}"
    )


def _recurso_compartido(
    tmp_path: Path,
    *,
    entrada: bytes = b"entrada",
    salida: bytes = b"salida",
    identificador: str = "01",
) -> Path:
    raiz = tmp_path / "compartido"
    directorio = raiz / "contado_carga"
    directorio.mkdir(parents=True)
    (directorio / f"{identificador}_entrada.xlsx").write_bytes(entrada)
    (directorio / f"{identificador}_salida.txt").write_bytes(salida)
    return raiz


@pytest.fixture
def fuera_de_ci(monkeypatch: pytest.MonkeyPatch) -> None:
    """La máquina de quien programa puede tener `CI` puesta por otra cosa."""
    monkeypatch.delenv("CI", raising=False)


@pytest.fixture
def en_ci_simulado(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CI", "true")


# --- El manifiesto embarcado en el repositorio -------------------------------


def test_el_manifiesto_del_repositorio_es_valido() -> None:
    """El archivo que viaja en el repo tiene que parsear y validar tal cual está."""
    assert cargar_manifiesto() == {}


def test_pedir_una_seccion_que_no_existe_es_un_fallo(fuera_de_ci: None) -> None:
    """Hoy el manifiesto embarcado está vacío: el ítem #16 todavía no tiene sus pares.

    Que esto sea `ManifiestoInvalido` y no un salto es la diferencia entre "no
    tengo los archivos a mano" y "el contrato de la prueba no existe".
    """
    with pytest.raises(ManifiestoInvalido, match="no tiene sección"):
        exigir_pares("contado_carga")


# --- Severidad 1: el contrato del manifiesto falla siempre -------------------


def test_un_par_completo_se_interpreta(tmp_path: Path) -> None:
    ruta = _manifiesto(tmp_path, _par_valido())
    (par,) = cargar_manifiesto(ruta)["contado_carga"]
    assert par.id == "01"
    assert par.archivos == {"entrada": "01_entrada.xlsx", "salida_txt": "01_salida.txt"}
    assert par.procedencia.fin_de_linea == "CRLF"
    assert par.procedencia.generado_el.isoformat() == "2026-08-14"


def test_un_par_sin_procedencia_es_invalido(tmp_path: Path) -> None:
    ruta = _manifiesto(tmp_path, _par_valido(procedencia=""))
    with pytest.raises(ManifiestoInvalido, match="obligatorio"):
        cargar_manifiesto(ruta)


def test_una_procedencia_incompleta_es_invalida(tmp_path: Path) -> None:
    """Sin `fin_de_linea` no se puede distinguir un cambio de módulo de uno de plataforma."""
    parcial = """
      [contado_carga.pares.procedencia]
      generado_por   = "Contado_Carga.py"
      version_script = "sha256:{script}"
      generado_el    = 2026-08-14
      generado_en    = "Windows Server 2019 / Python 3.11.9"
    """.format(script="b" * 64)
    ruta = _manifiesto(tmp_path, _par_valido(procedencia=textwrap.dedent(parcial)))
    with pytest.raises(ManifiestoInvalido, match="fin_de_linea"):
        cargar_manifiesto(ruta)


def test_la_fecha_de_generacion_debe_ser_una_fecha_toml(tmp_path: Path) -> None:
    con_texto = _PROCEDENCIA_COMPLETA.format(script="b" * 64).replace(
        "generado_el    = 2026-08-14", 'generado_el    = "2026-08-14"'
    )
    ruta = _manifiesto(tmp_path, _par_valido(procedencia=con_texto))
    with pytest.raises(ManifiestoInvalido, match="fecha TOML nativa"):
        cargar_manifiesto(ruta)


def test_la_version_del_script_debe_ser_un_sha256(tmp_path: Path) -> None:
    """ADR 0015: el script manual no está versionado; un 'v2' no identifica nada."""
    con_etiqueta = _PROCEDENCIA_COMPLETA.format(script="b" * 64).replace(
        f'"sha256:{"b" * 64}"', '"v2.1"'
    )
    ruta = _manifiesto(tmp_path, _par_valido(procedencia=con_etiqueta))
    with pytest.raises(ManifiestoInvalido, match="version_script"):
        cargar_manifiesto(ruta)


def test_el_fin_de_linea_solo_admite_lo_observable(tmp_path: Path) -> None:
    con_invento = _PROCEDENCIA_COMPLETA.format(script="b" * 64).replace('"CRLF"', '"depende"')
    ruta = _manifiesto(tmp_path, _par_valido(procedencia=con_invento))
    with pytest.raises(ManifiestoInvalido, match="fin_de_linea"):
        cargar_manifiesto(ruta)


def test_un_hash_mal_formado_es_invalido(tmp_path: Path) -> None:
    ruta = _manifiesto(tmp_path, _par_valido().replace(_hash(b"entrada"), "AB12"))
    with pytest.raises(ManifiestoInvalido, match="64 dígitos hexadecimales"):
        cargar_manifiesto(ruta)


def test_el_nombre_de_archivo_no_puede_ser_una_ruta(tmp_path: Path) -> None:
    """El valor sale de un archivo de configuración y se concatena a una raíz."""
    ruta = _manifiesto(tmp_path, _par_valido().replace("01_entrada.xlsx", "../../etc/passwd"))
    with pytest.raises(ManifiestoInvalido, match="nombre de archivo suelto"):
        cargar_manifiesto(ruta)


def test_un_par_sin_salida_esperada_es_invalido(tmp_path: Path) -> None:
    sin_salida = "\n".join(
        linea for linea in _par_valido().splitlines() if not linea.startswith("salida_txt")
    )
    ruta = _manifiesto(tmp_path, sin_salida)
    with pytest.raises(ManifiestoInvalido, match="ninguna salida esperada"):
        cargar_manifiesto(ruta)


def test_los_ids_de_par_no_se_repiten(tmp_path: Path) -> None:
    ruta = _manifiesto(tmp_path, _par_valido() + "\n" + _par_valido())
    with pytest.raises(ManifiestoInvalido, match="repetidos"):
        cargar_manifiesto(ruta)


def test_un_toml_roto_es_manifiesto_invalido(tmp_path: Path) -> None:
    ruta = _manifiesto(tmp_path, "[[contado_carga.pares]\nid = ")
    with pytest.raises(ManifiestoInvalido, match="no es TOML válido"):
        cargar_manifiesto(ruta)


# --- Severidad 1 bis: la ubicación no puede caer adentro del repositorio -----


def test_la_ubicacion_no_puede_apuntar_adentro_del_repositorio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La única promesa de ADR 0015 que un descuido puede romper para siempre."""
    monkeypatch.setenv(VARIABLE_DE_UBICACION, str(Path(__file__).resolve().parent))
    with pytest.raises(ManifiestoInvalido, match="adentro del repositorio"):
        resolver_raiz()


def test_sin_la_variable_no_hay_raiz(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(VARIABLE_DE_UBICACION, raising=False)
    assert resolver_raiz() is None


# --- Severidad 3: ausencia de fixtures — falla en CI, saltea en local --------


def test_sin_variable_saltea_fuera_de_ci_con_aviso(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fuera_de_ci: None,
    recwarn: pytest.WarningsRecorder,
) -> None:
    """El salto tiene que gritar: una `s` en la línea de puntos no es un aviso."""
    monkeypatch.delenv(VARIABLE_DE_UBICACION, raising=False)
    ruta = _manifiesto(tmp_path, _par_valido())

    with pytest.raises(pytest.skip.Exception):
        exigir_pares("contado_carga", manifiesto=ruta)

    assert any("PARIDAD NO VERIFICADA" in str(aviso.message) for aviso in recwarn)


def test_sin_variable_falla_en_ci(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, en_ci_simulado: None
) -> None:
    monkeypatch.delenv(VARIABLE_DE_UBICACION, raising=False)
    ruta = _manifiesto(tmp_path, _par_valido())

    with pytest.raises(pytest.fail.Exception, match="nunca un salto"):
        exigir_pares("contado_carga", manifiesto=ruta)


def test_un_fixture_ausente_saltea_fuera_de_ci(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fuera_de_ci: None
) -> None:
    raiz = _recurso_compartido(tmp_path)
    (raiz / "contado_carga" / "01_salida.txt").unlink()
    monkeypatch.setenv(VARIABLE_DE_UBICACION, str(raiz))
    ruta = _manifiesto(tmp_path, _par_valido())

    with pytest.raises(pytest.skip.Exception, match="faltan fixtures"):
        exigir_pares("contado_carga", manifiesto=ruta)


def test_un_fixture_ausente_falla_en_ci(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, en_ci_simulado: None
) -> None:
    raiz = _recurso_compartido(tmp_path)
    (raiz / "contado_carga" / "01_salida.txt").unlink()
    monkeypatch.setenv(VARIABLE_DE_UBICACION, str(raiz))
    ruta = _manifiesto(tmp_path, _par_valido())

    with pytest.raises(pytest.fail.Exception, match="faltan fixtures"):
        exigir_pares("contado_carga", manifiesto=ruta)


# --- Severidad 2: un fixture retocado falla en los dos entornos --------------


def test_un_fixture_alterado_falla_fuera_de_ci(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fuera_de_ci: None
) -> None:
    """La barrera contra ajustar el archivo de referencia no se levanta en local."""
    raiz = _recurso_compartido(tmp_path, salida=b"salida retocada")
    monkeypatch.setenv(VARIABLE_DE_UBICACION, str(raiz))
    ruta = _manifiesto(tmp_path, _par_valido(salida=b"salida"))

    with pytest.raises(FixtureAlterado, match="no coincide con el manifiesto"):
        exigir_pares("contado_carga", manifiesto=ruta)


def test_un_fixture_alterado_falla_en_ci(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, en_ci_simulado: None
) -> None:
    raiz = _recurso_compartido(tmp_path, salida=b"salida retocada")
    monkeypatch.setenv(VARIABLE_DE_UBICACION, str(raiz))
    ruta = _manifiesto(tmp_path, _par_valido(salida=b"salida"))

    with pytest.raises(FixtureAlterado):
        exigir_pares("contado_carga", manifiesto=ruta)


# --- El camino feliz: con todo en su lugar, ni saltea ni falla ---------------


def test_con_los_fixtures_en_su_lugar_devuelve_los_pares(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fuera_de_ci: None
) -> None:
    raiz = _recurso_compartido(tmp_path)
    monkeypatch.setenv(VARIABLE_DE_UBICACION, str(raiz))
    ruta = _manifiesto(tmp_path, _par_valido())

    (par,) = exigir_pares("contado_carga", manifiesto=ruta)
    assert par.id == "01"
    assert par.procedencia.generado_por == "Contado_Carga.py"


def test_la_deteccion_de_ci_lee_la_convencion(monkeypatch: pytest.MonkeyPatch) -> None:
    for valor, esperado in (("true", True), ("1", True), ("", False), ("false", False)):
        monkeypatch.setenv("CI", valor)
        assert en_ci() is esperado
    monkeypatch.delenv("CI")
    assert en_ci() is False
