"""Pruebas de `app/core/empaquetado.py` (ítem #9, design.md §8).

Sólo comportamiento: sin pruebas AST/estructurales, sin caos, sin
perturbación deliberada (Strict TDD apagado desde el ítem #3). Ningún test
necesita un proceso hijo ni `REGISTRY`; todo corre contra `ArchivoSalida`
construidos a mano, la misma postura autónoma que ya tiene
`tests/test_validaciones.py`.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from app.core.empaquetado import (
    MIME_DEL_ZIP,
    NOMBRE_DEL_ZIP,
    SalidaMalFormada,
    _nombre_plano,
    empaquetar,
)
from app.core.errores import ErrorContenido, TipoError
from app.core.tipos import ArchivoSalida


def _crear(directorio: Path, nombre: str, contenido: bytes = b"contenido") -> ArchivoSalida:
    ruta = directorio / nombre
    ruta.write_bytes(contenido)
    return ArchivoSalida(nombre_propuesto=nombre, ruta_temporal=ruta, tipo_mime="text/csv")


class TestPassthrough:
    def test_una_sola_salida_se_devuelve_verbatim(self, tmp_path: Path) -> None:
        entrada = _crear(tmp_path, "enero.csv")

        salida = empaquetar(archivos=[entrada], directorio=tmp_path)

        assert salida.nombre_propuesto == entrada.nombre_propuesto
        assert salida.ruta_temporal == entrada.ruta_temporal
        assert salida.tipo_mime == entrada.tipo_mime
        assert salida is entrada
        assert list(tmp_path.iterdir()) == [entrada.ruta_temporal]

    def test_una_sola_salida_no_verifica_su_nombre(self, tmp_path: Path) -> None:
        ruta = tmp_path / "unica.csv"
        ruta.write_bytes(b"contenido")
        entrada = ArchivoSalida(
            nombre_propuesto="../../nombre_hostil.csv", ruta_temporal=ruta, tipo_mime="text/csv"
        )

        salida = empaquetar(archivos=[entrada], directorio=tmp_path)

        assert salida is entrada


class TestMultiplesSalidas:
    def test_dos_o_mas_producen_un_unico_zip_plano(self, tmp_path: Path) -> None:
        entradas = [
            _crear(tmp_path, "enero.csv", b"datos-enero"),
            _crear(tmp_path, "febrero.csv", b"datos-febrero"),
        ]

        salida = empaquetar(archivos=entradas, directorio=tmp_path)

        assert salida.nombre_propuesto == NOMBRE_DEL_ZIP
        assert salida.tipo_mime == MIME_DEL_ZIP
        assert salida.ruta_temporal == tmp_path / NOMBRE_DEL_ZIP

        with zipfile.ZipFile(salida.ruta_temporal) as zip_:
            nombres = zip_.namelist()
            assert sorted(nombres) == ["enero.csv", "febrero.csv"]
            assert zip_.read("enero.csv") == b"datos-enero"
            assert zip_.read("febrero.csv") == b"datos-febrero"
            for nombre in nombres:
                assert "/" not in nombre
                assert "\\" not in nombre

        rutas_de_entrada = {e.ruta_temporal for e in entradas}
        nuevos = [p.name for p in tmp_path.iterdir() if p not in rutas_de_entrada]
        assert nuevos == [NOMBRE_DEL_ZIP]

    def test_el_zip_queda_dentro_del_directorio_provisto(self, tmp_path: Path) -> None:
        entradas = [_crear(tmp_path, "a.csv"), _crear(tmp_path, "b.csv")]

        salida = empaquetar(archivos=entradas, directorio=tmp_path)

        assert salida.ruta_temporal.parent == tmp_path


class TestCeroSalidas:
    def test_levanta_antes_de_tocar_disco(self, tmp_path: Path) -> None:
        with pytest.raises(ErrorContenido) as excinfo:
            empaquetar(archivos=[], directorio=tmp_path)

        error = excinfo.value
        assert error.tipo is TipoError.CONTENIDO
        assert error.contexto == {"motivo": "sin_salidas"}
        assert list(tmp_path.iterdir()) == []


class TestNombreAplanado:
    @pytest.mark.parametrize(
        "nombre_propuesto",
        ["../../x.txt", "a/b/c.txt", "C:\\Windows\\x.txt"],
    )
    def test_nombres_hostiles_se_confinan_a_un_arcname_plano(
        self, tmp_path: Path, nombre_propuesto: str
    ) -> None:
        assert _nombre_plano(nombre_propuesto) not in ("", ".", "..")
        assert "/" not in _nombre_plano(nombre_propuesto)
        assert "\\" not in _nombre_plano(nombre_propuesto)
        assert ".." not in _nombre_plano(nombre_propuesto).split("/")

    def test_nombres_hostiles_terminan_planos_dentro_del_zip(self, tmp_path: Path) -> None:
        # ruta_temporal debe existir en disco, con un nombre real de archivo;
        # sólo `nombre_propuesto` es el valor hostil bajo prueba (design.md §5).
        ruta_a = tmp_path / "origen_a.csv"
        ruta_a.write_bytes(b"a")
        ruta_b = tmp_path / "origen_b.csv"
        ruta_b.write_bytes(b"b")
        entradas = [
            ArchivoSalida(
                nombre_propuesto="../../x.txt", ruta_temporal=ruta_a, tipo_mime="text/csv"
            ),
            ArchivoSalida(nombre_propuesto="a/b/c.txt", ruta_temporal=ruta_b, tipo_mime="text/csv"),
        ]

        salida = empaquetar(archivos=entradas, directorio=tmp_path)

        with zipfile.ZipFile(salida.ruta_temporal) as zip_:
            for nombre in zip_.namelist():
                assert "/" not in nombre
                assert "\\" not in nombre

    @pytest.mark.parametrize("nombre_propuesto", ["", ".", "..", "/"])
    def test_nombres_degenerados_levantan(self, tmp_path: Path, nombre_propuesto: str) -> None:
        ruta_a = tmp_path / "origen_a.csv"
        ruta_a.write_bytes(b"a")
        ruta_b = tmp_path / "origen_b.csv"
        ruta_b.write_bytes(b"b")
        entradas = [
            ArchivoSalida(
                nombre_propuesto=nombre_propuesto, ruta_temporal=ruta_a, tipo_mime="text/csv"
            ),
            ArchivoSalida(
                nombre_propuesto="valido.csv", ruta_temporal=ruta_b, tipo_mime="text/csv"
            ),
        ]

        with pytest.raises(SalidaMalFormada):
            empaquetar(archivos=entradas, directorio=tmp_path)

        assert not (tmp_path / NOMBRE_DEL_ZIP).exists()


class TestDuplicados:
    def test_nombre_propuesto_duplicado_levanta(self, tmp_path: Path) -> None:
        sub = tmp_path / "otro"
        sub.mkdir()
        entradas = [_crear(tmp_path, "igual.csv"), _crear(sub, "igual.csv")]

        with pytest.raises(SalidaMalFormada):
            empaquetar(archivos=entradas, directorio=tmp_path)

        assert not (tmp_path / NOMBRE_DEL_ZIP).exists()

    def test_dos_rutas_distintas_que_aplanan_al_mismo_nombre_levantan(self, tmp_path: Path) -> None:
        sub = tmp_path / "sub"
        sub.mkdir()
        ruta_a = tmp_path / "igual.csv"
        ruta_a.write_bytes(b"a")
        ruta_b = sub / "otro.csv"
        ruta_b.write_bytes(b"b")
        entradas = [
            ArchivoSalida(nombre_propuesto="igual.csv", ruta_temporal=ruta_a, tipo_mime="text/csv"),
            ArchivoSalida(
                nombre_propuesto="carpeta/igual.csv", ruta_temporal=ruta_b, tipo_mime="text/csv"
            ),
        ]

        with pytest.raises(SalidaMalFormada):
            empaquetar(archivos=entradas, directorio=tmp_path)

        assert not (tmp_path / NOMBRE_DEL_ZIP).exists()


class TestRutaTemporalInexistente:
    def test_una_ruta_temporal_inexistente_levanta_antes_de_escribir(self, tmp_path: Path) -> None:
        existente = _crear(tmp_path, "existe.csv")
        faltante = ArchivoSalida(
            nombre_propuesto="faltante.csv",
            ruta_temporal=tmp_path / "no_esta_en_disco.csv",
            tipo_mime="text/csv",
        )

        with pytest.raises(SalidaMalFormada):
            empaquetar(archivos=[existente, faltante], directorio=tmp_path)

        assert not (tmp_path / NOMBRE_DEL_ZIP).exists()


class TestColisionConElDestino:
    def test_una_entrada_en_la_ruta_del_zip_levanta_antes_de_escribir(self, tmp_path: Path) -> None:
        destino = tmp_path / NOMBRE_DEL_ZIP
        destino.write_bytes(b"preexistente")
        otra = _crear(tmp_path, "otra.csv")
        entradas = [
            ArchivoSalida(
                nombre_propuesto=NOMBRE_DEL_ZIP, ruta_temporal=destino, tipo_mime="application/zip"
            ),
            otra,
        ]

        with pytest.raises(SalidaMalFormada):
            empaquetar(archivos=entradas, directorio=tmp_path)

        # El archivo preexistente no fue truncado por un `ZipFile(..., "w")`.
        assert destino.read_bytes() == b"preexistente"


class TestFalloDeEscritura:
    def test_un_fallo_a_mitad_de_escritura_no_deja_zip_parcial(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        entradas = [
            _crear(tmp_path, "enero.csv"),
            _crear(tmp_path, "febrero.csv"),
            _crear(tmp_path, "marzo.csv"),
        ]

        original_write = zipfile.ZipFile.write
        llamadas = {"n": 0}

        def _write_que_falla_en_el_segundo(
            self: zipfile.ZipFile, *args: object, **kwargs: object
        ) -> None:
            llamadas["n"] += 1
            if llamadas["n"] == 2:
                raise RuntimeError("fallo simulado a mitad de escritura")
            original_write(self, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(zipfile.ZipFile, "write", _write_que_falla_en_el_segundo)

        with pytest.raises(RuntimeError, match="fallo simulado a mitad de escritura"):
            empaquetar(archivos=entradas, directorio=tmp_path)

        assert not (tmp_path / NOMBRE_DEL_ZIP).exists()
        assert llamadas["n"] == 2

    def test_sin_fallo_el_zip_devuelto_ya_esta_cerrado(self, tmp_path: Path) -> None:
        entradas = [_crear(tmp_path, "enero.csv"), _crear(tmp_path, "febrero.csv")]

        salida = empaquetar(archivos=entradas, directorio=tmp_path)

        # Un `ZipFile` cerrado y completo se puede reabrir y leer sin error.
        with zipfile.ZipFile(salida.ruta_temporal) as zip_:
            assert zip_.testzip() is None
