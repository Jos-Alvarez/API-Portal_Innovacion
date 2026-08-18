"""Pruebas de `Procesador`, los tipos portadores y el registry (ítem #4).

Behaviourales, sin AST ni inspección estructural (design.md, metodología:
TDD estricto deshabilitado). Un fake de sólo pruebas prueba la interfaz;
nunca se registra nada en `app.registry.REGISTRY` — mutar un global de
módulo se filtraría entre pruebas (design.md §6).
"""

from __future__ import annotations

import dataclasses
import pickle
from pathlib import Path

import pytest

from app.core.errores import ErrorFormato, ErrorTipificado
from app.core.interfaz import Procesador
from app.core.tipos import ArchivoEntrada, ArchivoSalida
from app.registry import REGISTRY


class _ProcesadorFalso(Procesador):
    """Fake de sólo pruebas: implementa ambos métodos abstractos."""

    clave = "falso"

    def validar(self, archivos: list[ArchivoEntrada]) -> ErrorTipificado | None:
        if len(archivos) > 3:
            return ErrorFormato(
                archivo=archivos[0].nombre_original,
                formato_recibido=archivos[0].formato,
                formatos_aceptados=["xlsx"],
            )
        return None

    def procesar(self, archivos: list[ArchivoEntrada]) -> list[ArchivoSalida]:
        return [
            ArchivoSalida(
                nombre_propuesto=f"salida_{a.nombre_original}",
                ruta_temporal=a.ruta_temporal,
                tipo_mime="application/octet-stream",
            )
            for a in archivos
        ]


class _ProcesadorSinValidar(Procesador):
    """Fake incompleto: le falta `validar`."""

    clave = "sin_validar"

    def procesar(self, archivos: list[ArchivoEntrada]) -> list[ArchivoSalida]:
        return []


class _ProcesadorSinProcesar(Procesador):
    """Fake incompleto: le falta `procesar`."""

    clave = "sin_procesar"

    def validar(self, archivos: list[ArchivoEntrada]) -> ErrorTipificado | None:
        return None


def _archivo_entrada(directorio: Path, nombre: str = "enero.xlsx") -> ArchivoEntrada:
    return ArchivoEntrada(
        nombre_original=nombre,
        ruta_temporal=directorio / nombre,
        tamano_comprimido=1024,
        formato="xlsx",
    )


@pytest.mark.parametrize("clase", [Procesador, _ProcesadorSinValidar, _ProcesadorSinProcesar])
def test_instanciacion_directa_o_parcial_falla(clase: type[Procesador]) -> None:
    with pytest.raises(TypeError):
        clase()


class TestValidar:
    def test_devuelve_none_cuando_es_valido_un_elemento(self, tmp_path: Path) -> None:
        procesador = _ProcesadorFalso()
        resultado = procesador.validar([_archivo_entrada(tmp_path)])
        assert resultado is None

    def test_devuelve_none_cuando_es_valido_varios_elementos(self, tmp_path: Path) -> None:
        procesador = _ProcesadorFalso()
        archivos = [_archivo_entrada(tmp_path, f"enero_{i}.xlsx") for i in range(2)]
        resultado = procesador.validar(archivos)
        assert resultado is None

    def test_devuelve_error_tipificado_sin_levantar(self, tmp_path: Path) -> None:
        procesador = _ProcesadorFalso()
        archivos = [_archivo_entrada(tmp_path, f"enero_{i}.xlsx") for i in range(4)]
        resultado = procesador.validar(archivos)
        assert isinstance(resultado, ErrorTipificado)
        assert isinstance(resultado, ErrorFormato)


class TestProcesar:
    def test_un_elemento(self, tmp_path: Path) -> None:
        procesador = _ProcesadorFalso()
        resultado = procesador.procesar([_archivo_entrada(tmp_path)])
        assert isinstance(resultado, list)
        assert len(resultado) == 1
        assert all(isinstance(salida, ArchivoSalida) for salida in resultado)

    def test_varios_elementos(self, tmp_path: Path) -> None:
        procesador = _ProcesadorFalso()
        archivos = [_archivo_entrada(tmp_path, f"enero_{i}.xlsx") for i in range(3)]
        resultado = procesador.procesar(archivos)
        assert isinstance(resultado, list)
        assert len(resultado) == 3
        assert all(isinstance(salida, ArchivoSalida) for salida in resultado)


class TestPickle:
    def test_archivo_entrada_round_trip(self, tmp_path: Path) -> None:
        original = _archivo_entrada(tmp_path)
        assert pickle.loads(pickle.dumps(original)) == original  # noqa: S301

    def test_archivo_salida_round_trip(self, tmp_path: Path) -> None:
        original = ArchivoSalida(
            nombre_propuesto="salida.xlsx",
            ruta_temporal=tmp_path / "salida.xlsx",
            tipo_mime="application/vnd.openxmlformats",
        )
        assert pickle.loads(pickle.dumps(original)) == original  # noqa: S301


class TestInmutabilidad:
    """Nota: para `frozen=True, slots=True`, `__setattr__` intercepta toda
    asignación antes de mirar si el atributo existe. Reasignar un campo
    declarado da `FrozenInstanceError`; asignar uno no declarado da
    `TypeError` (verificado por ejecución en el intérprete fijado), no
    `AttributeError` como en un dataclass frozen sin slots.
    """

    def test_archivo_entrada_es_frozen_y_slotted(self, tmp_path: Path) -> None:
        original = _archivo_entrada(tmp_path)
        with pytest.raises(dataclasses.FrozenInstanceError):
            original.nombre_original = "otro.xlsx"  # type: ignore[misc]
        with pytest.raises(TypeError):
            original.atributo_no_declarado = "x"  # type: ignore[attr-defined]

    def test_archivo_salida_es_frozen_y_slotted(self, tmp_path: Path) -> None:
        original = ArchivoSalida(
            nombre_propuesto="salida.xlsx",
            ruta_temporal=tmp_path / "salida.xlsx",
            tipo_mime="application/vnd.openxmlformats",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            original.nombre_propuesto = "otro.xlsx"  # type: ignore[misc]
        with pytest.raises(TypeError):
            original.atributo_no_declarado = "x"  # type: ignore[attr-defined]


def test_instancia_es_asignable_a_dict_local_tipado() -> None:
    procesador = _ProcesadorFalso()
    registro_local: dict[str, Procesador] = {}
    registro_local[procesador.clave] = procesador
    assert registro_local[procesador.clave] is procesador


def test_registry_importa_vacio() -> None:
    assert REGISTRY == {}


def test_interfaz_importa_sin_procesadores() -> None:
    import app.core.interfaz  # noqa: F401


def test_docstring_registra_pregunta_abierta_del_item_8() -> None:
    assert Procesador.__doc__ is not None
    assert "proceso hijo" in Procesador.__doc__
    assert "re-deriva" in Procesador.__doc__
