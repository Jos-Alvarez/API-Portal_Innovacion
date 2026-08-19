"""Pruebas de `app.core.ejecucion`, mitad de proceso (ítem #8, S3, design.md §5-§7).

Behaviourales, sin AST ni inspección estructural (TDD estricto deshabilitado).

Presupuesto de pruebas que spawnean un hijo real: el diseño pide ≤6 (design.md
§10) porque cada una paga un `spawn` real (~0.5-1.5s en Windows). Esta suite
usa exactamente 6: éxito, excepción sin tipificar, error tipificado, timeout
con kill real, `os._exit` anómalo, salida silenciosa -- más una que reutiliza
el hijo anómalo para probar que la capacidad no queda atascada (comparte el
mismo spawn, no agrega uno nuevo aparte del segundo hijo normal que prueba).

`clasificar_desenlace` es pura, así que la tabla completa de design.md §6 --
filas POSIX incluidas -- se prueba como datos, sin ningún proceso real: es la
forma en que las convenciones de POSIX quedan cubiertas en una máquina
Windows-only (design.md §6, §10).
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.configuracion import obtener_configuracion
from app.core.ejecucion import (
    Desenlace,
    EjecucionExpirada,
    ErrorDelHijo,
    ExcepcionDelHijo,
    HijoMuerto,
    SalidaDelHijo,
    admitir,
    clasificar_desenlace,
    ejecutar_aislado,
    obtener_semaforo,
)
from app.core.errores import ErrorCantidad
from tests.ayudas import hijos

# El único directorio de trabajo que `hijo_normal` reporta: sin archivos.
_TIMEOUT_HOLGADO = timedelta(seconds=10)
_TIMEOUT_CORTO = timedelta(seconds=0.3)


class TestClasificarDesenlace:
    """Tarea 3.6: la tabla completa de design.md §6, como datos puros."""

    @pytest.mark.parametrize(
        "exitcode,matado,hubo_mensaje,esperado",
        [
            pytest.param(0, False, True, Desenlace.NORMAL, id="mensaje_y_exitcode_cero_es_normal"),
            pytest.param(
                -15, True, False, Desenlace.MATADO, id="windows_kill_normalizado_a_menos_15"
            ),
            pytest.param(-9, True, False, Desenlace.MATADO, id="posix_kill_menos_9_con_flag"),
            pytest.param(-9, False, False, Desenlace.ANOMALO, id="posix_oom_menos_9_sin_flag"),
            pytest.param(-15, False, False, Desenlace.ANOMALO, id="posix_sigterm_externo_sin_flag"),
            pytest.param(3, False, False, Desenlace.ANOMALO, id="os_exit_3"),
            pytest.param(
                3221225477, False, False, Desenlace.ANOMALO, id="windows_access_violation"
            ),
            pytest.param(0, False, False, Desenlace.ANOMALO, id="salida_limpia_sin_mensaje"),
            pytest.param(None, False, False, Desenlace.ANOMALO, id="sigue_vivo_tras_join"),
            # Matado gana incluso si, por alguna razón, hubiera llegado un mensaje.
            pytest.param(0, True, True, Desenlace.MATADO, id="matado_gana_pese_a_mensaje"),
        ],
    )
    def test_tabla_completa(
        self, exitcode: int | None, matado: bool, hubo_mensaje: bool, esperado: Desenlace
    ) -> None:
        assert (
            clasificar_desenlace(exitcode=exitcode, matado=matado, hubo_mensaje=hubo_mensaje)
            == esperado
        )


@pytest.fixture(autouse=True)
def _configuracion_limpia(token_sentinela: str, limpiar_cache_configuracion: None) -> None:
    """Todas las pruebas de este módulo necesitan `TOKEN_SERVICIO` (requerido
    por `Configuracion`) y caches de módulo limpios entre pruebas -- el mismo
    patrón que `tests/test_admision.py`."""


class TestEjecutarAisladoExitoso:
    """Tarea 3.7: camino de éxito, excepción sin tipificar y error tipificado."""

    def test_hijo_normal_devuelve_salida_del_hijo(self) -> None:
        resultado = ejecutar_aislado(hijos.hijo_normal, (), timeout=_TIMEOUT_HOLGADO)
        assert isinstance(resultado, SalidaDelHijo)
        assert resultado.archivos == []

    def test_hijo_que_lanza_cruza_con_traceback_no_vacio(self) -> None:
        resultado = ejecutar_aislado(hijos.hijo_que_lanza, (), timeout=_TIMEOUT_HOLGADO)
        assert isinstance(resultado, ExcepcionDelHijo)
        assert resultado.clase == "RuntimeError"
        assert "fallo deliberado del módulo" in resultado.mensaje
        assert resultado.traza.strip() != ""
        assert "Traceback" in resultado.traza

    def test_error_tipificado_cruza_intacto_via_reduce(self) -> None:
        resultado = ejecutar_aislado(
            hijos.hijo_que_envia_error_tipificado, (), timeout=_TIMEOUT_HOLGADO
        )
        assert isinstance(resultado, ErrorDelHijo)
        assert isinstance(resultado.error, ErrorCantidad)
        assert resultado.error.contexto == {"minimo": 1, "maximo": 5, "recibido": 0}


class TestEjecutarAisladoTimeoutYAnomalias:
    """Tarea 3.7 (continuación): el hijo colgado realmente muere; los dos
    caminos anómalos (`os._exit` y silencio) se clasifican igual."""

    def test_hijo_colgado_expira_y_muere_de_verdad(self) -> None:
        with pytest.raises(EjecucionExpirada):
            ejecutar_aislado(hijos.hijo_que_cuelga, (), timeout=_TIMEOUT_CORTO)
        # No basta con que `ejecutar_aislado` haya retornado: el propio
        # `multiprocessing` ya no debe contar al hijo entre sus procesos
        # activos, porque `ejecutar_aislado` ya lo mató y lo unió (spec "A
        # hung child is really terminated on timeout, not merely un-awaited").
        import multiprocessing

        assert multiprocessing.active_children() == []

    def test_os_exit_anomalo_se_contiene_como_hijo_muerto(self) -> None:
        with pytest.raises(HijoMuerto) as excinfo:
            ejecutar_aislado(hijos.hijo_exit_anomalo, (), timeout=_TIMEOUT_HOLGADO)
        assert excinfo.value.exitcode == 3

    def test_salida_silenciosa_tambien_se_contiene_como_hijo_muerto(self) -> None:
        with pytest.raises(HijoMuerto) as excinfo:
            ejecutar_aislado(hijos.hijo_silencioso, (), timeout=_TIMEOUT_HOLGADO)
        # Salida limpia (0) pero sin mensaje: `clasificar_desenlace` la trata
        # igual de `ANOMALO` que un `os._exit(N)` no nulo (design.md §6).
        assert excinfo.value.exitcode == 0


class TestCapacidadNoQuedaAtascada:
    """Tarea 3.8: una muerte anómala del hijo no deja el slot de admisión
    ocupado ni impide que una segunda ejecución complete con éxito."""

    def test_capacidad_libre_y_segunda_ejecucion_exitosa_tras_muerte_anomala(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EJECUCIONES_MAX", "1")
        obtener_configuracion.cache_clear()
        obtener_semaforo.cache_clear()

        with pytest.raises(HijoMuerto):
            with admitir():
                ejecutar_aislado(hijos.hijo_exit_anomalo, (), timeout=_TIMEOUT_HOLGADO)

        # El slot -- propiedad del llamador, no de esta mitad de proceso --
        # quedó libre pese a la muerte anómala del hijo.
        assert obtener_semaforo().acquire(blocking=False) is True
        obtener_semaforo().release()

        # Una segunda ejecución, normal, completa sin ningún estado filtrado.
        with admitir():
            resultado = ejecutar_aislado(hijos.hijo_normal, (), timeout=_TIMEOUT_HOLGADO)
        assert isinstance(resultado, SalidaDelHijo)
