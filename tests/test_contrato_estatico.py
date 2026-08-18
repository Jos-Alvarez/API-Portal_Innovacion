"""Pruebas del contrato estático sin base de datos (ADR 0013, desviación).

Behaviourales, sin AST ni inspección estructural (metodología: TDD estricto
deshabilitado para este cambio).
"""

from __future__ import annotations

import dataclasses
import socket

import pytest

from app.core.contrato import CONTRATO_POR_DEFECTO, ContratoProcesador, obtener_contrato


def test_lookup_resuelve_offline_sin_intentar_conexion(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fallar_si_se_conecta(*args: object, **kwargs: object) -> None:
        raise AssertionError("obtener_contrato no debe abrir ninguna conexión de red")

    monkeypatch.setattr(socket.socket, "connect", _fallar_si_se_conecta)
    obtener_contrato("cualquier_clave")


def test_clave_desconocida_reporta_ausencia() -> None:
    assert obtener_contrato("clave_que_no_existe") is None


def test_limites_del_contrato_por_defecto_son_positivos_y_completos() -> None:
    assert CONTRATO_POR_DEFECTO.entradas_min > 0
    assert CONTRATO_POR_DEFECTO.entradas_max > 0
    assert CONTRATO_POR_DEFECTO.tamano_max_bytes > 0
    assert CONTRATO_POR_DEFECTO.tamano_max_total_bytes > 0
    assert len(CONTRATO_POR_DEFECTO.formatos_aceptados) > 0


def test_contrato_procesador_es_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        CONTRATO_POR_DEFECTO.entradas_min = 99  # type: ignore[misc]


def test_contrato_procesador_se_construye_con_los_campos_esperados() -> None:
    contrato = ContratoProcesador(
        entradas_min=1,
        entradas_max=2,
        formatos_aceptados=("xlsx", "csv"),
        tamano_max_bytes=100,
        tamano_max_total_bytes=200,
        activo=False,
    )
    assert contrato.entradas_min == 1
    assert contrato.activo is False
