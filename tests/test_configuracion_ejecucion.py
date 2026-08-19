"""Pruebas de `EJECUCIONES_MAX` y `TIMEOUT_EJECUCION` (ítem #8, design.md §4).

Ambos campos ship con valor por defecto (design.md §4, corrige la propuesta
original que los pedía obligatorios), así que "ausente" arranca con éxito
usando el placeholder documentado -- a diferencia de `TOKEN_SERVICIO`, que
no tiene un valor seguro por defecto. Lo que sigue siendo fallo cerrado es un
valor *presente pero inválido*: cero, negativo, o fuera de la cota.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.configuracion import CORTE_DEL_PORTAL, ConfiguracionInvalida, obtener_configuracion

pytestmark = pytest.mark.usefixtures("limpiar_cache_configuracion")


class TestEjecucionesMax:
    def test_ausente_usa_el_placeholder_por_defecto(
        self, token_sentinela: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("EJECUCIONES_MAX", raising=False)
        configuracion = obtener_configuracion()
        assert configuracion.ejecuciones_max == 2

    def test_cero_falla(self, token_sentinela: str, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EJECUCIONES_MAX", "0")
        with pytest.raises(ConfiguracionInvalida):
            obtener_configuracion()

    def test_negativo_falla(self, token_sentinela: str, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EJECUCIONES_MAX", "-1")
        with pytest.raises(ConfiguracionInvalida):
            obtener_configuracion()

    def test_valor_positivo_arranca(
        self, token_sentinela: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EJECUCIONES_MAX", "5")
        configuracion = obtener_configuracion()
        assert configuracion.ejecuciones_max == 5

    def test_limite_superior_treinta_y_dos_pasa(
        self, token_sentinela: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EJECUCIONES_MAX", "32")
        configuracion = obtener_configuracion()
        assert configuracion.ejecuciones_max == 32

    def test_por_encima_de_treinta_y_dos_falla(
        self, token_sentinela: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EJECUCIONES_MAX", "33")
        with pytest.raises(ConfiguracionInvalida):
            obtener_configuracion()


class TestTimeoutEjecucion:
    def test_ausente_usa_el_placeholder_por_defecto(
        self, token_sentinela: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("TIMEOUT_EJECUCION", raising=False)
        configuracion = obtener_configuracion()
        assert configuracion.timeout_ejecucion == timedelta(seconds=60)

    def test_cero_falla(self, token_sentinela: str, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TIMEOUT_EJECUCION", "0")
        with pytest.raises(ConfiguracionInvalida):
            obtener_configuracion()

    def test_negativo_falla(self, token_sentinela: str, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TIMEOUT_EJECUCION", "-1")
        with pytest.raises(ConfiguracionInvalida):
            obtener_configuracion()

    def test_igual_al_corte_falla_y_nombra_la_relacion(
        self, token_sentinela: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TIMEOUT_EJECUCION", str(int(CORTE_DEL_PORTAL.total_seconds())))
        with pytest.raises(ConfiguracionInvalida) as excinfo:
            obtener_configuracion()
        assert "timeout_ejecucion" in str(excinfo.value)

    def test_por_encima_del_corte_falla(
        self, token_sentinela: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TIMEOUT_EJECUCION", str(int(CORTE_DEL_PORTAL.total_seconds()) + 30))
        with pytest.raises(ConfiguracionInvalida):
            obtener_configuracion()

    def test_estrictamente_debajo_del_corte_arranca(
        self, token_sentinela: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TIMEOUT_EJECUCION", "90")
        configuracion = obtener_configuracion()
        assert configuracion.timeout_ejecucion == timedelta(seconds=90)

    def test_construccion_directa_acepta_timedelta_o_numero(self, token_sentinela: str) -> None:
        from pydantic import SecretStr

        from app.core.configuracion import Configuracion

        con_timedelta = Configuracion(
            token_servicio=SecretStr(token_sentinela), timeout_ejecucion=timedelta(seconds=90)
        )
        con_entero = Configuracion(
            token_servicio=SecretStr(token_sentinela),
            timeout_ejecucion=90,  # type: ignore[arg-type]  # el conversor acepta int
        )
        assert (
            con_timedelta.timeout_ejecucion == con_entero.timeout_ejecucion == timedelta(seconds=90)
        )

    def test_formato_iso8601_tambien_se_acepta(
        self, token_sentinela: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TIMEOUT_EJECUCION", "PT90S")
        configuracion = obtener_configuracion()
        assert configuracion.timeout_ejecucion == timedelta(seconds=90)

    def test_ningun_valor_crudo_llega_al_mensaje(
        self, token_sentinela: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Sentinela numérico poco común, por encima del corte: si apareciera
        # en el mensaje de error, sería evidencia de una fuga del valor
        # rechazado.
        centinela = "774411"
        monkeypatch.setenv("TIMEOUT_EJECUCION", centinela)
        with pytest.raises(ConfiguracionInvalida) as excinfo:
            obtener_configuracion()
        assert centinela not in str(excinfo.value)
