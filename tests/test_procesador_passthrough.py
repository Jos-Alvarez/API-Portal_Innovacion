"""Pruebas del procesador passthrough y de su alta (ítem #12 del backlog).

Behaviourales, sin AST ni inspección estructural (TDD estricto deshabilitado).

Presupuesto de pruebas que spawnean un hijo real: ≤6 por entrega (design.md
§10 del ítem #8, citado en `tests/test_ejecucion.py`). Esta entrega gasta
exactamente **dos**, los dos éxitos de punta a punta de
`TestExtremoAExtremoConHijoReal`. Son además los dos primeros éxitos con hijo
real de todo el repositorio: hasta este ítem no existía ningún procesador que
el hijo pudiera encontrar en `REGISTRY`, así que el único desenlace disponible
era `ErrorClaveInexistente`. Todo lo demás corre por llamada directa al
módulo, sin proceso.

Estas pruebas **no inyectan contrato**: usan las claves reales y las filas
reales de `app.core.contrato._TABLA_CONTRATOS`. El fixture `inyectar_contrato`
de `tests/test_recepcion.py` reemplaza la tabla entera, lo que acá escondería
justo lo que hay que probar — que lo embarcado en producción funciona.
"""

from __future__ import annotations

import io
import shutil
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.contrato import _TABLA_CONTRATOS, obtener_contrato
from app.core.empaquetado import MIME_DEL_ZIP, NOMBRE_DEL_ZIP
from app.core.temporales import _EN_VUELO, _raiz
from app.core.tipos import ArchivoEntrada
from app.main import crear_app
from app.procesadores.passthrough.modulo import MARCA, MIME_DE_SALIDA, Passthrough
from app.registry import REGISTRY

_CLAVE_SIMPLE = "passthrough"
_CLAVE_MULTI = "passthrough_multi"


def _ruta(clave: str) -> str:
    return f"/interno/procesadores/{clave}"


def _cabecera(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _hijos_de_la_raiz() -> list[Path]:
    return list(_raiz().iterdir()) if _raiz().is_dir() else []


def _entrada(
    directorio: Path, indice: int, nombre_original: str, contenido: bytes
) -> ArchivoEntrada:
    """Escribe una entrada en disco tal como lo hace `app/recepcion.py`.

    El nombre en disco lo genera el servidor (`entrada_0`, `entrada_1`, ...);
    `nombre_original` es sólo lo que declaró el cliente.
    """
    ruta = directorio / f"entrada_{indice}"
    ruta.write_bytes(contenido)
    return ArchivoEntrada(
        nombre_original=nombre_original,
        ruta_temporal=ruta,
        tamano_comprimido=len(contenido),
        formato=nombre_original.rpartition(".")[2].lower(),
    )


@pytest.fixture(autouse=True)
def _estado_limpio() -> Iterator[None]:
    """`_EN_VUELO` y la raíz dedicada son estado de módulo compartido con
    `app.core.temporales`; no debe filtrarse entre pruebas."""
    _EN_VUELO.clear()
    shutil.rmtree(_raiz(), ignore_errors=True)
    yield
    _EN_VUELO.clear()
    shutil.rmtree(_raiz(), ignore_errors=True)


@pytest.fixture
def cliente_de_prueba(
    token_sentinela: str, limpiar_cache_configuracion: None
) -> Iterator[TestClient]:
    with TestClient(crear_app(), raise_server_exceptions=False) as cliente:
        yield cliente


class TestRegistroDeProduccion:
    """El alta: `REGISTRY` y `_TABLA_CONTRATOS` tienen que decir lo mismo.

    `Procesador.clave` es una anotación sin valor que ni mypy ni `ABCMeta`
    obligan a definir (`app/core/interfaz.py`), y el hijo de ADR 0012 busca su
    procesador por esa `clave`. Estas pruebas son el único guardián de que la
    llave del diccionario y el atributo no se desincronicen.
    """

    def test_cada_llave_coincide_con_la_clave_de_su_procesador(self) -> None:
        assert all(llave == procesador.clave for llave, procesador in REGISTRY.items())

    def test_toda_clave_del_registry_tiene_fila_de_contrato(self) -> None:
        # Sin fila, la ruta muere en `ErrorClaveInexistente` antes de spawnear
        # y el procesador registrado sería inalcanzable.
        assert all(obtener_contrato(llave) is not None for llave in REGISTRY)

    def test_las_dos_claves_del_passthrough_estan_dadas_de_alta(self) -> None:
        assert {_CLAVE_SIMPLE, _CLAVE_MULTI} <= set(REGISTRY)

    def test_una_sola_clase_sirve_a_las_dos_claves(self) -> None:
        # ADR 0006: la cardinalidad se declara en la fila, no en el módulo, y
        # el módulo no ramifica por cantidad de entradas.
        assert type(REGISTRY[_CLAVE_SIMPLE]) is type(REGISTRY[_CLAVE_MULTI]) is Passthrough
        assert REGISTRY[_CLAVE_SIMPLE] is not REGISTRY[_CLAVE_MULTI]

    def test_las_filas_difieren_solo_en_la_cardinalidad(self) -> None:
        simple = _TABLA_CONTRATOS[_CLAVE_SIMPLE]
        multi = _TABLA_CONTRATOS[_CLAVE_MULTI]
        assert (simple.entradas_min, simple.entradas_max) == (1, 1)
        assert multi.entradas_max > multi.entradas_min >= 2
        assert simple.formatos_aceptados == multi.formatos_aceptados
        assert simple.tamano_max_bytes == multi.tamano_max_bytes
        assert simple.tamano_max_total_bytes == multi.tamano_max_total_bytes
        assert simple.activo is multi.activo is True


class TestProcesarSinProceso:
    """El módulo en aislamiento, por llamada directa: ni HTTP ni `spawn`."""

    @pytest.mark.parametrize("cantidad", [1, 2, 5], ids=["una", "dos", "cinco"])
    def test_una_salida_por_entrada_en_el_mismo_orden(self, tmp_path: Path, cantidad: int) -> None:
        entradas = [
            _entrada(tmp_path, indice, f"archivo_{indice}.csv", f"datos-{indice}".encode())
            for indice in range(cantidad)
        ]

        salidas = Passthrough(clave=_CLAVE_SIMPLE).procesar(entradas)

        assert len(salidas) == cantidad
        for indice, salida in enumerate(salidas):
            assert salida.nombre_propuesto == f"{indice}_archivo_{indice}.csv"
            assert salida.tipo_mime == MIME_DE_SALIDA

    def test_la_salida_marca_el_contenido_de_la_entrada(self, tmp_path: Path) -> None:
        entradas = [_entrada(tmp_path, 0, "informe.csv", b"contenido-de-prueba")]

        [salida] = Passthrough(clave=_CLAVE_SIMPLE).procesar(entradas)

        assert salida.ruta_temporal.read_bytes() == MARCA + b"contenido-de-prueba"
        # La entrada queda intacta: se copia, no se muta.
        assert entradas[0].ruta_temporal.read_bytes() == b"contenido-de-prueba"

    def test_nombres_unicos_aunque_el_cliente_repita_el_nombre(self, tmp_path: Path) -> None:
        # `nombre_original` lo elige el cliente y puede venir duplicado; dos
        # `nombre_propuesto` iguales harían reventar la petición entera con
        # `SalidaMalFormada` (ADR 0023).
        entradas = [
            _entrada(tmp_path, 0, "informe.csv", b"uno"),
            _entrada(tmp_path, 1, "informe.csv", b"dos"),
        ]

        salidas = Passthrough(clave=_CLAVE_MULTI).procesar(entradas)

        nombres = [salida.nombre_propuesto for salida in salidas]
        assert nombres == ["0_informe.csv", "1_informe.csv"]
        assert len(set(nombres)) == len(nombres)

    @pytest.mark.parametrize(
        "nombre_original,esperado",
        [
            pytest.param("sub/informe.csv", "0_informe.csv", id="barra_normal"),
            pytest.param("..\\informe.csv", "0_informe.csv", id="barra_invertida"),
            pytest.param("C:\\Windows\\informe.csv", "0_informe.csv", id="ruta_absoluta"),
            pytest.param("", "0_", id="nombre_vacio"),
            pytest.param("..", "0_..", id="nombre_degenerado"),
        ],
    )
    def test_el_nombre_se_aplana_antes_de_prefijar_el_indice(
        self, tmp_path: Path, nombre_original: str, esperado: str
    ) -> None:
        # Aplanar después de prefijar dejaría que `"0_sub/a.csv"` volviera a
        # aplanar a `"a.csv"` dentro de `app.core.empaquetado`, y dos entradas
        # en subdirectorios distintos podrían colisionar pese al índice.
        entradas = [_entrada(tmp_path, 0, nombre_original, b"x")]

        [salida] = Passthrough(clave=_CLAVE_SIMPLE).procesar(entradas)

        assert salida.nombre_propuesto == esperado

    def test_las_salidas_se_escriben_junto_a_las_entradas(self, tmp_path: Path) -> None:
        # El directorio se deriva de la entrada, no se recibe: es
        # `reserva.directorio`, y escribir ahí es lo que hace que la limpieza
        # cedida a la `FileResponse` barra también las salidas (ADR 0020).
        entradas = [
            _entrada(tmp_path, 0, "uno.csv", b"uno"),
            _entrada(tmp_path, 1, "dos.csv", b"dos"),
        ]

        salidas = Passthrough(clave=_CLAVE_MULTI).procesar(entradas)

        assert [salida.ruta_temporal.parent for salida in salidas] == [tmp_path, tmp_path]
        # Ninguna salida pisa una entrada ni comparte ruta con otra salida.
        rutas = [salida.ruta_temporal for salida in salidas]
        assert len(set(rutas)) == len(rutas)
        assert not set(rutas) & {entrada.ruta_temporal for entrada in entradas}

    def test_validar_no_rechaza_nada(self, tmp_path: Path) -> None:
        # El passthrough no tiene reglas de contenido: cantidad, formato y
        # tamaño ya los aplicó el borde contra la fila del contrato.
        entradas = [_entrada(tmp_path, 0, "informe.csv", b"x")]
        assert Passthrough(clave=_CLAVE_SIMPLE).validar(entradas) is None
        assert Passthrough(clave=_CLAVE_SIMPLE).validar([]) is None


class TestExtremoAExtremoConHijoReal:
    """Los dos únicos spawns reales de esta entrega (presupuesto ≤6).

    Sin ningún sustituto en el camino: contrato real, copia acotada real,
    `spawn` real, `REGISTRY` real, `empaquetar` real, `FileResponse` real y
    limpieza cedida real. Es la prueba que el ítem #12 existe para dar — que
    la tubería navegador → portal → FastAPI → descarga entrega un archivo
    verificablemente distinto del que se subió.
    """

    def test_una_entrada_vuelve_marcada_con_su_nombre_y_su_mime(
        self, cliente_de_prueba: TestClient, token_sentinela: str
    ) -> None:
        respuesta = cliente_de_prueba.post(
            _ruta(_CLAVE_SIMPLE),
            files={"archivos": ("informe.csv", b"contenido-de-prueba", "text/csv")},
            headers=_cabecera(token_sentinela),
        )

        assert respuesta.status_code == 200
        assert respuesta.content == MARCA + b"contenido-de-prueba"
        assert respuesta.headers["content-type"] == MIME_DE_SALIDA
        assert "0_informe.csv" in respuesta.headers["content-disposition"]
        assert _hijos_de_la_raiz() == []

    def test_varias_entradas_vuelven_como_zip_de_salidas_marcadas(
        self, cliente_de_prueba: TestClient, token_sentinela: str
    ) -> None:
        respuesta = cliente_de_prueba.post(
            _ruta(_CLAVE_MULTI),
            files=[
                ("archivos", ("enero.csv", b"datos-enero", "text/csv")),
                ("archivos", ("febrero.txt", b"datos-febrero", "text/plain")),
            ],
            headers=_cabecera(token_sentinela),
        )

        assert respuesta.status_code == 200
        assert respuesta.headers["content-type"] == MIME_DEL_ZIP
        assert NOMBRE_DEL_ZIP in respuesta.headers["content-disposition"]
        with zipfile.ZipFile(io.BytesIO(respuesta.content)) as contenedor:
            assert sorted(contenedor.namelist()) == ["0_enero.csv", "1_febrero.txt"]
            assert contenedor.read("0_enero.csv") == MARCA + b"datos-enero"
            assert contenedor.read("1_febrero.txt") == MARCA + b"datos-febrero"
        assert _hijos_de_la_raiz() == []
