"""Pruebas de `app.core.pipeline` (ítem #10): los pasos 6-8 en orden.

Behaviourales, sin AST ni inspección estructural (TDD estricto deshabilitado).

Ninguna spawnea un hijo real. El presupuesto de ≤6 pruebas con `spawn` por
entrega (design.md §10 del ítem #8, citado en `tests/test_ejecucion.py`) se
reserva para las pruebas donde el proceso hijo *es* lo que está bajo prueba;
acá lo que se prueba es la composición, así que se sustituye `ejecutar_modulo`
dentro del espacio de nombres de `app.core.pipeline` -- el punto de unión real
entre este módulo y la mitad de proceso del ítem #8. `empaquetar` corre de
verdad en todas estas pruebas, sin sustituto.

Parchear `app.registry.REGISTRY` no sería una alternativa: `spawn` re-importa
`app.registry` en el hijo, que vería siempre la tabla de producción y nunca el
parche del proceso padre.
"""

from __future__ import annotations

import zipfile
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import pytest

from app.core import pipeline
from app.core.ejecucion import EjecucionExpirada, FalloDeEjecucion, FalloDelModulo, HijoMuerto
from app.core.empaquetado import MIME_DEL_ZIP, NOMBRE_DEL_ZIP, SalidaMalFormada
from app.core.errores import ErrorCantidad, ErrorContenido
from app.core.pipeline import ejecutar_pipeline
from app.core.tipos import ArchivoEntrada, ArchivoSalida

_TIMEOUT = timedelta(seconds=7)

Resultado = Callable[[], list[ArchivoSalida]]
InstalarModulo = Callable[[Resultado], list[dict[str, object]]]


@pytest.fixture
def modulo_falso(monkeypatch: pytest.MonkeyPatch) -> InstalarModulo:
    """Instala un `ejecutar_modulo` de mentira y devuelve el registro de llamadas."""

    def _instalar(resultado: Resultado) -> list[dict[str, object]]:
        llamadas: list[dict[str, object]] = []

        def _falso(
            *, clave: str, entradas: list[ArchivoEntrada], timeout: timedelta
        ) -> list[ArchivoSalida]:
            llamadas.append({"clave": clave, "entradas": entradas, "timeout": timeout})
            return resultado()

        monkeypatch.setattr(pipeline, "ejecutar_modulo", _falso)
        return llamadas

    return _instalar


def _sin_salidas() -> list[ArchivoSalida]:
    """El módulo terminó bien pero no produjo ni un archivo."""
    return []


def _entrada(directorio: Path, nombre: str = "informe.xlsx") -> ArchivoEntrada:
    ruta = directorio / "entrada_0"
    ruta.write_bytes(b"entrada")
    return ArchivoEntrada(
        nombre_original=nombre, ruta_temporal=ruta, tamano_comprimido=7, formato="xlsx"
    )


def _salida(directorio: Path, nombre: str, contenido: bytes = b"salida") -> ArchivoSalida:
    ruta = directorio / f"cruda_{nombre}"
    ruta.write_bytes(contenido)
    return ArchivoSalida(nombre_propuesto=nombre, ruta_temporal=ruta, tipo_mime="text/csv")


class TestComposicionDeLosPasos:
    def test_la_clave_las_entradas_y_el_timeout_llegan_verbatim_al_modulo(
        self, modulo_falso: InstalarModulo, tmp_path: Path
    ) -> None:
        entradas = [_entrada(tmp_path)]
        llamadas = modulo_falso(lambda: [_salida(tmp_path, "unica.csv")])

        ejecutar_pipeline(
            clave="contado_carga", entradas=entradas, directorio=tmp_path, timeout=_TIMEOUT
        )

        assert llamadas == [{"clave": "contado_carga", "entradas": entradas, "timeout": _TIMEOUT}]

    def test_una_sola_salida_se_devuelve_verbatim(
        self, modulo_falso: InstalarModulo, tmp_path: Path
    ) -> None:
        unica = _salida(tmp_path, "enero.csv", b"datos-enero")
        modulo_falso(lambda: [unica])

        salida = ejecutar_pipeline(
            clave="k", entradas=[_entrada(tmp_path)], directorio=tmp_path, timeout=_TIMEOUT
        )

        assert salida is unica
        assert not (tmp_path / NOMBRE_DEL_ZIP).exists()  # no se comprimió nada

    def test_dos_o_mas_salidas_se_comprimen_en_el_directorio_recibido(
        self, modulo_falso: InstalarModulo, tmp_path: Path
    ) -> None:
        destino = tmp_path / "reserva"
        destino.mkdir()
        modulo_falso(
            lambda: [
                _salida(tmp_path, "enero.csv", b"datos-enero"),
                _salida(tmp_path, "febrero.csv", b"datos-febrero"),
            ]
        )

        salida = ejecutar_pipeline(
            clave="k", entradas=[_entrada(tmp_path)], directorio=destino, timeout=_TIMEOUT
        )

        # El ZIP se escribe en el `directorio` recibido, nunca en otro lado.
        assert salida.ruta_temporal == destino / NOMBRE_DEL_ZIP
        assert salida.nombre_propuesto == NOMBRE_DEL_ZIP
        assert salida.tipo_mime == MIME_DEL_ZIP
        with zipfile.ZipFile(salida.ruta_temporal) as contenedor:
            assert sorted(contenedor.namelist()) == ["enero.csv", "febrero.csv"]
            assert contenedor.read("enero.csv") == b"datos-enero"

    def test_cero_salidas_levanta_el_error_tipificado_sin_escribir_nada(
        self, modulo_falso: InstalarModulo, tmp_path: Path
    ) -> None:
        destino = tmp_path / "reserva"
        destino.mkdir()
        modulo_falso(_sin_salidas)

        with pytest.raises(ErrorContenido) as capturado:
            ejecutar_pipeline(
                clave="k", entradas=[_entrada(tmp_path)], directorio=destino, timeout=_TIMEOUT
            )

        assert capturado.value.contexto == {"motivo": "sin_salidas"}
        assert list(destino.iterdir()) == []


class TestPropagacionSinTraduccion:
    """El pipeline no atrapa nada: cada falla sale con su propio tipo.

    Es lo que permite que el borde HTTP las distinga -- una `SalidaMalFormada`
    (bug de empaquetado) nunca puede reportarse como una caída del módulo
    (ADR 0023), y eso sólo se sostiene si acá no hay un `except` que las funda.
    """

    def test_un_error_tipificado_del_modulo_sale_intacto(
        self, modulo_falso: InstalarModulo, tmp_path: Path
    ) -> None:
        def _levantar() -> list[ArchivoSalida]:
            raise ErrorCantidad(minimo=1, maximo=1, recibido=4)

        modulo_falso(_levantar)

        with pytest.raises(ErrorCantidad) as capturado:
            ejecutar_pipeline(
                clave="k", entradas=[_entrada(tmp_path)], directorio=tmp_path, timeout=_TIMEOUT
            )

        assert capturado.value.contexto == {"minimo": 1, "maximo": 1, "recibido": 4}

    @pytest.mark.parametrize(
        "falla",
        [
            pytest.param(EjecucionExpirada(), id="ejecucion_expirada"),
            pytest.param(HijoMuerto(3), id="hijo_muerto"),
            pytest.param(
                FalloDelModulo(clase="RuntimeError", mensaje="se cayó", traza="Traceback..."),
                id="fallo_del_modulo",
            ),
        ],
    )
    def test_las_fallas_de_ejecucion_no_se_traducen(
        self, modulo_falso: InstalarModulo, tmp_path: Path, falla: FalloDeEjecucion
    ) -> None:
        def _levantar() -> list[ArchivoSalida]:
            raise falla

        modulo_falso(_levantar)

        with pytest.raises(type(falla)) as capturado:
            ejecutar_pipeline(
                clave="k", entradas=[_entrada(tmp_path)], directorio=tmp_path, timeout=_TIMEOUT
            )

        assert capturado.value is falla

    def test_un_conjunto_de_salidas_mal_formado_sale_como_salida_mal_formada(
        self, modulo_falso: InstalarModulo, tmp_path: Path
    ) -> None:
        # Dos salidas que aplanan al mismo nombre: el bug de primera parte que
        # ADR 0023 mantiene deliberadamente fuera de `FalloDeEjecucion`.
        primera = _salida(tmp_path, "reporte.csv", b"uno")
        segunda = ArchivoSalida(
            nombre_propuesto="sub/reporte.csv",
            ruta_temporal=tmp_path / "otra_cruda",
            tipo_mime="text/csv",
        )
        segunda.ruta_temporal.write_bytes(b"dos")
        modulo_falso(lambda: [primera, segunda])

        with pytest.raises(SalidaMalFormada):
            ejecutar_pipeline(
                clave="k", entradas=[_entrada(tmp_path)], directorio=tmp_path, timeout=_TIMEOUT
            )

        # El ZIP a medio escribir no queda: `empaquetar` lo borra al fallar.
        assert not (tmp_path / NOMBRE_DEL_ZIP).exists()
