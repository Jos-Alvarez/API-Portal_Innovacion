"""Pruebas de `app.recepcion`: la ruta de recepción con contrato aplicado.

Ítem #6 embarcó esta ruta; el ítem #7 (slice B) le invierte el orden — el
contrato pasa a ser precondición de la copia, no postcondición. Eso obliga a
**reestructurar** este módulo, no sólo a extenderlo: con `_TABLA_CONTRATOS`
vacía, subir la resolución del contrato por encima del bucle hace que ninguna
petición llegue a escribir nada en producción. Las tres pruebas del ítem #6 que
afirmaban archivos en disco se reconstruyen sobre un contrato inyectado.

El ítem #10 cerró la costura que quedaba al final de la fase 2. Mientras
estuvo abierta, `assert respuesta.status_code == 500` significaba en este
módulo "la petición pasó todo el contrato y llegó al `NotImplementedError`";
ese código ya no significa eso en ninguna prueba de acá. Un lote que pasa el
contrato ahora recorre el pipeline entero y termina en 200 con el archivo de
salida, o en el estado que le corresponda a la falla que lo interrumpió.

Behaviourales, sin AST ni inspección estructural (TDD estricto deshabilitado).
La app de producción se usa tal cual (`app.main.crear_app`), no un router de
pruebas aparte, porque esta ruta ya vive en `router_interno` y su cobertura de
pin está en `tests/test_seguridad_token.py`.

El estado modular de `app.core.temporales` (`_EN_VUELO`, la raíz dedicada) se
limpia antes y después de cada prueba, igual que en `tests/test_temporales.py`.
"""

from __future__ import annotations

import io
import logging
import shutil
import zipfile
from collections.abc import Callable, Iterator
from datetime import timedelta
from pathlib import Path
from types import MappingProxyType

import pytest
from fastapi.testclient import TestClient

from app.core import contrato as contrato_modulo
from app.core import pipeline, temporales
from app.core.contrato import CONTRATO_POR_DEFECTO, ContratoProcesador
from app.core.ejecucion import EjecucionExpirada, FalloDelModulo, HijoMuerto
from app.core.empaquetado import MIME_DEL_ZIP, NOMBRE_DEL_ZIP
from app.core.errores import ErrorTamano
from app.core.temporales import _EN_VUELO, _raiz
from app.core.tipos import ArchivoEntrada, ArchivoSalida
from app.core.validaciones import PRESUPUESTO_DE_RAM_BYTES
from app.main import crear_app
from app.recepcion import _copiar, _formato

_CLAVE = "cualquiera"
_RUTA = f"/interno/procesadores/{_CLAVE}"

InyectarContrato = Callable[..., ContratoProcesador]
FabricaDeSalidas = Callable[[list[ArchivoEntrada]], list[ArchivoSalida]]
InstalarModulo = Callable[[FabricaDeSalidas], None]


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
    # `raise_server_exceptions=False`: el ítem #10 cerró la costura, así que un
    # 500 ya no significa "todo pasó" -- significa lo que significa en
    # producción. La bandera queda para que una excepción que ningún manejador
    # cubra se vea como el 500 que el cliente recibiría, en vez de reventar
    # dentro de la prueba con otra forma. Los errores tipificados y las cuatro
    # fallas del pipeline no dependen de ella: los contestan los manejadores
    # registrados en `crear_app()`, no el middleware de errores del servidor.
    with TestClient(crear_app(), raise_server_exceptions=False) as cliente:
        yield cliente


@pytest.fixture
def inyectar_contrato(monkeypatch: pytest.MonkeyPatch) -> InyectarContrato:
    """Registra un contrato para `_CLAVE` durante la prueba.

    Se parchea `_TABLA_CONTRATOS`, no `obtener_contrato`: así la función real
    —y su semántica de `None`— queda dentro del camino bajo prueba. Mismo
    patrón con que el ítem #6 parchea `temporales.Reserva.limpiar`.
    """

    def _inyectar(
        *,
        entradas_min: int = CONTRATO_POR_DEFECTO.entradas_min,
        entradas_max: int = CONTRATO_POR_DEFECTO.entradas_max,
        formatos_aceptados: tuple[str, ...] = CONTRATO_POR_DEFECTO.formatos_aceptados,
        tamano_max_bytes: int = CONTRATO_POR_DEFECTO.tamano_max_bytes,
        tamano_max_total_bytes: int = CONTRATO_POR_DEFECTO.tamano_max_total_bytes,
    ) -> ContratoProcesador:
        contrato = ContratoProcesador(
            entradas_min=entradas_min,
            entradas_max=entradas_max,
            formatos_aceptados=formatos_aceptados,
            tamano_max_bytes=tamano_max_bytes,
            tamano_max_total_bytes=tamano_max_total_bytes,
            activo=True,
        )
        monkeypatch.setattr(
            contrato_modulo, "_TABLA_CONTRATOS", MappingProxyType({_CLAVE: contrato})
        )
        return contrato

    return _inyectar


@pytest.fixture
def modulo_falso(monkeypatch: pytest.MonkeyPatch) -> InstalarModulo:
    """Sustituye `ejecutar_modulo` dentro del espacio de nombres de
    `app.core.pipeline`, sin spawnear ningún hijo.

    Parchear `app.registry.REGISTRY` no serviría: `spawn` re-importa
    `app.registry` en el hijo, que vería siempre la tabla vacía de producción.
    Y cada spawn real cuesta ~0.5-1.5s en Windows contra un presupuesto de ≤6
    por entrega (`tests/test_ejecucion.py`); el único de esta entrega está en
    `TestPipelineCompletoConHijoReal`. Todo lo demás del camino -- el contrato,
    la copia acotada, `empaquetar`, la `FileResponse` y la limpieza cedida --
    corre de verdad.
    """

    def _instalar(fabrica: FabricaDeSalidas) -> None:
        def _falso(
            *, clave: str, entradas: list[ArchivoEntrada], timeout: timedelta
        ) -> list[ArchivoSalida]:
            return fabrica(entradas)

        monkeypatch.setattr(pipeline, "ejecutar_modulo", _falso)

    return _instalar


def _passthrough(entradas: list[ArchivoEntrada]) -> list[ArchivoSalida]:
    """Una salida por entrada, apuntando al archivo que ya está en disco.

    No escribe ningún archivo nuevo en el directorio de la reserva, así que las
    pruebas de recepción del ítem #6 siguen pudiendo afirmar exactamente qué
    hay ahí adentro. `nombre_propuesto` usa el nombre generado por el servidor
    (`entrada_0`, `entrada_1`, ...) y no `nombre_original`, que el cliente
    puede mandar duplicado y haría fallar el empaquetado por colisión.
    """
    return [
        ArchivoSalida(
            nombre_propuesto=entrada.ruta_temporal.name,
            ruta_temporal=entrada.ruta_temporal,
            tipo_mime="application/octet-stream",
        )
        for entrada in entradas
    ]


def _fabricar(salidas: list[tuple[str, str, bytes]]) -> FabricaDeSalidas:
    """Fábrica que escribe salidas nuevas dentro del directorio de la reserva.

    Cada tupla es `(nombre_propuesto, tipo_mime, contenido)`. El nombre en
    disco lo genera esta ayuda (`salida_0`, `salida_1`, ...), igual que hace
    la ruta con las entradas: `nombre_propuesto` es sólo una etiqueta.
    """

    def _fabrica(entradas: list[ArchivoEntrada]) -> list[ArchivoSalida]:
        directorio = entradas[0].ruta_temporal.parent
        producidas = []
        for indice, (nombre, mime, contenido) in enumerate(salidas):
            ruta = directorio / f"salida_{indice}"
            ruta.write_bytes(contenido)
            producidas.append(
                ArchivoSalida(nombre_propuesto=nombre, ruta_temporal=ruta, tipo_mime=mime)
            )
        return producidas

    return _fabrica


def _fallar(falla: Exception) -> FabricaDeSalidas:
    """Fábrica que levanta `falla` en lugar de producir salidas."""

    def _fabrica(entradas: list[ArchivoEntrada]) -> list[ArchivoSalida]:
        raise falla

    return _fabrica


def _cabecera(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _hijos_de_la_raiz() -> list[Path]:
    return list(_raiz().iterdir()) if _raiz().is_dir() else []


@pytest.fixture
def captura_de_limpieza(monkeypatch: pytest.MonkeyPatch) -> dict[Path, dict[str, bytes]]:
    """Espía sobre `Reserva.limpiar` que guarda el contenido del directorio
    justo antes de que se borre de verdad, y llama al original después --
    así ninguna prueba deja basura ni depende de inspeccionar un directorio
    a mitad de una petición síncrona de `TestClient`.

    Un diccionario vacío ahora significa algo más fuerte que antes: `reservar()`
    nunca se entró, o sea que la petición murió en la fase 1 sin costar ni un
    `mkdtemp`.
    """
    contenidos: dict[Path, dict[str, bytes]] = {}
    limpiar_original = temporales.Reserva.limpiar

    def _espia(self: temporales.Reserva) -> None:
        if self.directorio.is_dir():
            contenidos[self.directorio] = {
                hijo.name: hijo.read_bytes() for hijo in self.directorio.iterdir()
            }
        limpiar_original(self)

    monkeypatch.setattr(temporales.Reserva, "limpiar", _espia)
    return contenidos


class TestRecepcionConContratoInyectado:
    """Las afirmaciones de recepción del ítem #6, reconstruidas sobre un
    contrato registrado — el único camino por el que hoy se escribe un byte."""

    def test_archivo_escrito_dentro_del_directorio_y_borrado_despues(
        self,
        cliente_de_prueba: TestClient,
        token_sentinela: str,
        inyectar_contrato: InyectarContrato,
        modulo_falso: InstalarModulo,
        captura_de_limpieza: dict[Path, dict[str, bytes]],
    ) -> None:
        inyectar_contrato()
        modulo_falso(_passthrough)
        respuesta = cliente_de_prueba.post(
            _RUTA,
            files={
                "archivos": ("informe.xlsx", b"contenido-de-prueba", "application/octet-stream")
            },
            headers=_cabecera(token_sentinela),
        )
        # Pasó todo el contrato y el pipeline entero (ítem #10).
        assert respuesta.status_code == 200
        [(directorio, contenido)] = captura_de_limpieza.items()
        assert contenido == {"entrada_0": b"contenido-de-prueba"}
        # Ya no limpia el `finally`, sino el `BackgroundTask` cedido; para
        # cuando `TestClient` devuelve la respuesta, ya corrió (ADR 0020).
        assert not directorio.exists()

    @pytest.mark.parametrize(
        "nombre_hostil",
        ["../../x", "..\\x.xlsx", "C:\\Windows\\x", "/etc/passwd", "café con leche.xlsx"],
    )
    def test_nombre_hostil_confinado_al_directorio_temporal(
        self,
        cliente_de_prueba: TestClient,
        token_sentinela: str,
        inyectar_contrato: InyectarContrato,
        modulo_falso: InstalarModulo,
        captura_de_limpieza: dict[Path, dict[str, bytes]],
        nombre_hostil: str,
    ) -> None:
        # El contrato acepta justo el formato de este nombre, para que la
        # petición llegue a la fase 2: lo que se prueba acá es el confinamiento
        # en disco, no el rechazo por formato.
        inyectar_contrato(formatos_aceptados=(_formato(nombre_hostil),))
        modulo_falso(_passthrough)
        respuesta = cliente_de_prueba.post(
            _RUTA,
            files={"archivos": (nombre_hostil, b"x", "application/octet-stream")},
            headers=_cabecera(token_sentinela),
        )
        assert respuesta.status_code == 200
        # Ningún archivo aparece en ninguna ruta derivada del nombre hostil.
        assert not Path(nombre_hostil).exists()
        [(directorio, contenido)] = captura_de_limpieza.items()
        # El único nombre en disco es el generado por el servidor.
        assert set(contenido) == {"entrada_0"}
        assert not directorio.exists()

    def test_nombres_duplicados_producen_archivos_distintos(
        self,
        cliente_de_prueba: TestClient,
        token_sentinela: str,
        inyectar_contrato: InyectarContrato,
        modulo_falso: InstalarModulo,
        captura_de_limpieza: dict[Path, dict[str, bytes]],
    ) -> None:
        inyectar_contrato(entradas_max=2)
        modulo_falso(_passthrough)
        respuesta = cliente_de_prueba.post(
            _RUTA,
            files=[
                ("archivos", ("reporte.xlsx", b"contenido-uno", "application/octet-stream")),
                ("archivos", ("reporte.xlsx", b"contenido-dos", "application/octet-stream")),
            ],
            headers=_cabecera(token_sentinela),
        )
        assert respuesta.status_code == 200
        [(_directorio, contenido)] = captura_de_limpieza.items()
        # Dos entradas con el MISMO `filename` del cliente, dos archivos
        # distintos en disco. `salida.zip` también está ahí: con dos salidas,
        # el empaquetado del ítem #9 corre de verdad dentro de la reserva.
        assert contenido["entrada_0"] == b"contenido-uno"
        assert contenido["entrada_1"] == b"contenido-dos"
        assert set(contenido) == {"entrada_0", "entrada_1", NOMBRE_DEL_ZIP}

    def test_no_quedan_temporales_tras_una_respuesta_completa(
        self,
        cliente_de_prueba: TestClient,
        token_sentinela: str,
        inyectar_contrato: InyectarContrato,
        modulo_falso: InstalarModulo,
    ) -> None:
        inyectar_contrato()
        modulo_falso(_passthrough)
        respuesta = cliente_de_prueba.post(
            _RUTA,
            files={"archivos": ("x.xlsx", b"x", "application/octet-stream")},
            headers=_cabecera(token_sentinela),
        )
        assert respuesta.status_code == 200
        assert _hijos_de_la_raiz() == []


class TestRechazoAntesDeEscribir:
    """La regresión de orden: un lote rechazado en la fase 1 no cuesta ni un
    `mkdtemp`. `captura_de_limpieza` vacío prueba que `reservar()` no se entró.
    """

    def test_clave_desconocida_muere_antes_de_cualquier_escritura(
        self,
        cliente_de_prueba: TestClient,
        token_sentinela: str,
        captura_de_limpieza: dict[Path, dict[str, bytes]],
    ) -> None:
        respuesta = cliente_de_prueba.post(
            _RUTA,
            files={"archivos": ("informe.xlsx", b"contenido", "application/octet-stream")},
            headers=_cabecera(token_sentinela),
        )
        assert respuesta.status_code == 500
        assert respuesta.json() == {
            "tipo": "clave_inexistente",
            "contexto": {"clave_procesador": _CLAVE, "causa": "fila_ausente"},
        }
        assert captura_de_limpieza == {}
        assert _hijos_de_la_raiz() == []

    @pytest.mark.parametrize("clave_procesador", ["contado_carga", "otra-clave", "123"])
    def test_cualquier_clave_procesador_produce_el_mismo_error(
        self, cliente_de_prueba: TestClient, token_sentinela: str, clave_procesador: str
    ) -> None:
        respuesta = cliente_de_prueba.post(
            f"/interno/procesadores/{clave_procesador}",
            files={"archivos": ("x.xlsx", b"x", "application/octet-stream")},
            headers=_cabecera(token_sentinela),
        )
        assert respuesta.status_code == 500
        assert respuesta.json() == {
            "tipo": "clave_inexistente",
            "contexto": {"clave_procesador": clave_procesador, "causa": "fila_ausente"},
        }

    def test_cantidad_fuera_de_rango(
        self,
        cliente_de_prueba: TestClient,
        token_sentinela: str,
        inyectar_contrato: InyectarContrato,
        captura_de_limpieza: dict[Path, dict[str, bytes]],
    ) -> None:
        inyectar_contrato(entradas_min=1, entradas_max=1)
        respuesta = cliente_de_prueba.post(
            _RUTA,
            files=[
                ("archivos", ("uno.xlsx", b"a", "application/octet-stream")),
                ("archivos", ("dos.xlsx", b"b", "application/octet-stream")),
            ],
            headers=_cabecera(token_sentinela),
        )
        assert respuesta.status_code == 422
        assert respuesta.json() == {
            "tipo": "cantidad",
            "contexto": {"minimo": 1, "maximo": 1, "recibido": 2},
        }
        assert captura_de_limpieza == {}
        assert _hijos_de_la_raiz() == []

    def test_formato_no_aceptado(
        self,
        cliente_de_prueba: TestClient,
        token_sentinela: str,
        inyectar_contrato: InyectarContrato,
        captura_de_limpieza: dict[Path, dict[str, bytes]],
    ) -> None:
        inyectar_contrato(formatos_aceptados=("xlsx",))
        respuesta = cliente_de_prueba.post(
            _RUTA,
            files={"archivos": ("enero.csv", b"a;b;c", "application/octet-stream")},
            headers=_cabecera(token_sentinela),
        )
        assert respuesta.status_code == 422
        assert respuesta.json() == {
            "tipo": "formato",
            "contexto": {
                "archivo": "enero.csv",
                "formato_recibido": "csv",
                "formatos_aceptados": ["xlsx"],
            },
        }
        assert captura_de_limpieza == {}
        assert _hijos_de_la_raiz() == []

    def test_tamano_por_archivo_con_la_cuenta_medida_por_starlette(
        self,
        cliente_de_prueba: TestClient,
        token_sentinela: str,
        inyectar_contrato: InyectarContrato,
        captura_de_limpieza: dict[Path, dict[str, bytes]],
    ) -> None:
        # `recibido_bytes` es el tamaño completo, medido por el parser, y con
        # cero bytes escritos: mejor desenlace que abortar a mitad de copia.
        inyectar_contrato(tamano_max_bytes=10, tamano_max_total_bytes=1_000)
        respuesta = cliente_de_prueba.post(
            _RUTA,
            files={"archivos": ("grande.xlsx", b"x" * 20, "application/octet-stream")},
            headers=_cabecera(token_sentinela),
        )
        assert respuesta.status_code == 422
        assert respuesta.json() == {
            "tipo": "tamano",
            "contexto": {
                "archivo": "grande.xlsx",
                "limite_bytes": 10,
                "recibido_bytes": 20,
            },
        }
        assert captura_de_limpieza == {}
        assert _hijos_de_la_raiz() == []

    def test_tamano_total_del_lote_con_la_forma_hermana(
        self,
        cliente_de_prueba: TestClient,
        token_sentinela: str,
        inyectar_contrato: InyectarContrato,
        captura_de_limpieza: dict[Path, dict[str, bytes]],
    ) -> None:
        # Cada archivo pasa su propio límite; la suma no.
        inyectar_contrato(entradas_max=2, tamano_max_bytes=100, tamano_max_total_bytes=15)
        respuesta = cliente_de_prueba.post(
            _RUTA,
            files=[
                ("archivos", ("uno.xlsx", b"x" * 10, "application/octet-stream")),
                ("archivos", ("dos.xlsx", b"y" * 10, "application/octet-stream")),
            ],
            headers=_cabecera(token_sentinela),
        )
        assert respuesta.status_code == 422
        assert respuesta.json() == {
            "tipo": "tamano",
            "contexto": {
                "archivos": ["uno.xlsx", "dos.xlsx"],
                "limite_bytes": 15,
                "recibido_bytes": 20,
            },
        }
        assert captura_de_limpieza == {}
        assert _hijos_de_la_raiz() == []


class TestBombaZipEnLaFaseDos:
    def test_tamano_declarado_sin_comprimir_por_encima_del_presupuesto(
        self,
        cliente_de_prueba: TestClient,
        token_sentinela: str,
        inyectar_contrato: InyectarContrato,
        captura_de_limpieza: dict[Path, dict[str, bytes]],
        tmp_path: Path,
    ) -> None:
        # 257 MiB de ceros declarados, ~256 KB en disco: ningún límite sobre el
        # tamaño comprimido lo habría frenado (H-04). Se escribe en trozos de
        # 1 MiB, así que construirlo no cuesta memoria.
        declarado = 257 * 1024 * 1024
        ruta = tmp_path / "bomba.xlsx"
        with zipfile.ZipFile(ruta, "w", zipfile.ZIP_DEFLATED) as archivo:
            with archivo.open("hoja.xml", "w") as entrada:
                for _ in range(257):
                    entrada.write(b"\0" * 1024 * 1024)

        crudo = ruta.read_bytes()
        assert len(crudo) < 1024 * 1024
        inyectar_contrato(tamano_max_bytes=len(crudo), tamano_max_total_bytes=len(crudo))

        respuesta = cliente_de_prueba.post(
            _RUTA,
            files={"archivos": ("bomba.xlsx", crudo, "application/octet-stream")},
            headers=_cabecera(token_sentinela),
        )
        assert respuesta.status_code == 422
        assert respuesta.json() == {
            "tipo": "tamano",
            "contexto": {
                "archivo": "bomba.xlsx",
                "limite_bytes": PRESUPUESTO_DE_RAM_BYTES,
                "recibido_bytes": declarado,
            },
        }
        # Falla en la fase 2: el archivo llegó a disco y el `finally` lo borró.
        [(directorio, contenido)] = captura_de_limpieza.items()
        assert set(contenido) == {"entrada_0"}
        assert not directorio.exists()
        assert _hijos_de_la_raiz() == []


class TestRespuestaDelPipeline:
    """Paso 9 del ítem #10: qué le llega al cliente cuando el pipeline gana."""

    def test_una_sola_salida_llega_verbatim_con_su_nombre_y_su_mime(
        self,
        cliente_de_prueba: TestClient,
        token_sentinela: str,
        inyectar_contrato: InyectarContrato,
        modulo_falso: InstalarModulo,
    ) -> None:
        inyectar_contrato()
        modulo_falso(_fabricar([("informe_procesado.csv", "text/csv", b"col_a;col_b\n1;2\n")]))

        respuesta = cliente_de_prueba.post(
            _RUTA,
            files={"archivos": ("informe.xlsx", b"entrada", "application/octet-stream")},
            headers=_cabecera(token_sentinela),
        )

        assert respuesta.status_code == 200
        assert respuesta.content == b"col_a;col_b\n1;2\n"
        # Starlette le agrega `charset` a todo `text/*`; el `tipo_mime` que el
        # procesador propuso viaja intacto delante de esa adición.
        assert respuesta.headers["content-type"] == "text/csv; charset=utf-8"
        assert respuesta.headers["content-disposition"] == (
            'attachment; filename="informe_procesado.csv"'
        )
        assert _hijos_de_la_raiz() == []

    def test_varias_salidas_llegan_como_un_unico_zip(
        self,
        cliente_de_prueba: TestClient,
        token_sentinela: str,
        inyectar_contrato: InyectarContrato,
        modulo_falso: InstalarModulo,
    ) -> None:
        inyectar_contrato()
        modulo_falso(
            _fabricar(
                [
                    ("enero.csv", "text/csv", b"datos-enero"),
                    ("febrero.csv", "text/csv", b"datos-febrero"),
                ]
            )
        )

        respuesta = cliente_de_prueba.post(
            _RUTA,
            files={"archivos": ("informe.xlsx", b"entrada", "application/octet-stream")},
            headers=_cabecera(token_sentinela),
        )

        assert respuesta.status_code == 200
        assert respuesta.headers["content-type"] == MIME_DEL_ZIP
        assert NOMBRE_DEL_ZIP in respuesta.headers["content-disposition"]
        with zipfile.ZipFile(io.BytesIO(respuesta.content)) as contenedor:
            assert sorted(contenedor.namelist()) == ["enero.csv", "febrero.csv"]
            assert contenedor.read("febrero.csv") == b"datos-febrero"
        assert _hijos_de_la_raiz() == []

    def test_nombre_no_ascii_lo_codifica_starlette(
        self,
        cliente_de_prueba: TestClient,
        token_sentinela: str,
        inyectar_contrato: InyectarContrato,
        modulo_falso: InstalarModulo,
    ) -> None:
        # La codificación de `Content-Disposition` quedó diferida a este ítem y
        # se resuelve delegándola en `FileResponse(filename=...)`, sin armar el
        # encabezado a mano. Lo que se afirma es el resultado observable: el
        # nombre viaja en la forma `filename*` de RFC 5987, no crudo.
        inyectar_contrato()
        modulo_falso(_fabricar([("café con leche.csv", "text/csv", b"x")]))

        respuesta = cliente_de_prueba.post(
            _RUTA,
            files={"archivos": ("informe.xlsx", b"entrada", "application/octet-stream")},
            headers=_cabecera(token_sentinela),
        )

        assert respuesta.status_code == 200
        assert respuesta.headers["content-disposition"] == (
            "attachment; filename*=utf-8''caf%C3%A9%20con%20leche.csv"
        )

    def test_cero_salidas_da_422_tipificado_sin_salidas(
        self,
        cliente_de_prueba: TestClient,
        token_sentinela: str,
        inyectar_contrato: InyectarContrato,
        modulo_falso: InstalarModulo,
    ) -> None:
        inyectar_contrato()
        modulo_falso(_fabricar([]))

        respuesta = cliente_de_prueba.post(
            _RUTA,
            files={"archivos": ("informe.xlsx", b"entrada", "application/octet-stream")},
            headers=_cabecera(token_sentinela),
        )

        assert respuesta.status_code == 422
        assert respuesta.json() == {"tipo": "contenido", "contexto": {"motivo": "sin_salidas"}}
        assert _hijos_de_la_raiz() == []


class TestFallasDelPipelineEnHttp:
    """Las cuatro excepciones que el ítem #10 tradujo a un estado desnudo.

    Ninguna es un `TipoError` (ADR 0014 sigue con cinco miembros), así que
    ninguna tiene cuerpo `tipo`/`contexto`. Van por clase concreta: que
    `SalidaMalFormada` (bug de empaquetado) comparta el 500 con
    `FalloDelModulo` no la hace parte de `FalloDeEjecucion` (ADR 0023).
    """

    @pytest.mark.parametrize(
        "falla,estado",
        [
            pytest.param(EjecucionExpirada(), 504, id="ejecucion_expirada_es_504"),
            pytest.param(HijoMuerto(3), 500, id="hijo_muerto_es_500"),
            pytest.param(
                FalloDelModulo(clase="ValueError", mensaje="se cayó", traza="Traceback (...)"),
                500,
                id="fallo_del_modulo_es_500",
            ),
        ],
    )
    def test_cada_falla_de_ejecucion_tiene_su_estado_desnudo(
        self,
        cliente_de_prueba: TestClient,
        token_sentinela: str,
        inyectar_contrato: InyectarContrato,
        modulo_falso: InstalarModulo,
        falla: Exception,
        estado: int,
    ) -> None:
        inyectar_contrato()
        modulo_falso(_fallar(falla))

        respuesta = cliente_de_prueba.post(
            _RUTA,
            files={"archivos": ("informe.xlsx", b"entrada", "application/octet-stream")},
            headers=_cabecera(token_sentinela),
        )

        assert respuesta.status_code == estado
        assert respuesta.content == b""
        # El `finally` de `reservar()` limpió: nada se cedió a una respuesta.
        assert _hijos_de_la_raiz() == []

    def test_la_traza_del_modulo_nunca_llega_al_cuerpo(
        self,
        cliente_de_prueba: TestClient,
        token_sentinela: str,
        inyectar_contrato: InyectarContrato,
        modulo_falso: InstalarModulo,
    ) -> None:
        # ADR 0022: `traza` es material de logging (ítem #14), nunca de la
        # respuesta. El centinela viaja en las tres partes de `FalloDelModulo`.
        centinela = "centinela-de-traza-4c1e9d"
        inyectar_contrato()
        modulo_falso(
            _fallar(
                FalloDelModulo(
                    clase=centinela,
                    mensaje=centinela,
                    traza=f"Traceback (most recent call last):\n  {centinela}",
                )
            )
        )

        respuesta = cliente_de_prueba.post(
            _RUTA,
            files={"archivos": ("informe.xlsx", b"entrada", "application/octet-stream")},
            headers=_cabecera(token_sentinela),
        )

        assert respuesta.status_code == 500
        assert centinela not in respuesta.text
        assert respuesta.content == b""

    def test_salida_mal_formada_es_500_desnudo(
        self,
        cliente_de_prueba: TestClient,
        token_sentinela: str,
        inyectar_contrato: InyectarContrato,
        modulo_falso: InstalarModulo,
    ) -> None:
        # Dos salidas que aplanan al mismo nombre: `empaquetar` real levanta
        # `SalidaMalFormada`, que no es un `FalloDeEjecucion`.
        inyectar_contrato()
        modulo_falso(
            _fabricar(
                [
                    ("reporte.csv", "text/csv", b"uno"),
                    ("sub/reporte.csv", "text/csv", b"dos"),
                ]
            )
        )

        respuesta = cliente_de_prueba.post(
            _RUTA,
            files={"archivos": ("informe.xlsx", b"entrada", "application/octet-stream")},
            headers=_cabecera(token_sentinela),
        )

        assert respuesta.status_code == 500
        assert respuesta.content == b""
        assert _hijos_de_la_raiz() == []


class TestPipelineCompletoConHijoReal:
    """El único spawn real de esta entrega (presupuesto ≤6, ver
    `tests/test_ejecucion.py`): la ruta entera sin un solo sustituto.

    Con `REGISTRY` vacío -- el estado de producción hasta los ítems #12/#16 --
    el hijo real tipifica la ausencia y el error cruza el `Pipe` intacto vía
    `ErrorTipificado.__reduce__`. Es la prueba de que la costura quedó cerrada
    de punta a punta: contrato, copia, `spawn`, `Pipe`, manejador tipificado y
    limpieza del temporal, sin ningún gancho de prueba en producción.
    """

    def test_registry_vacio_llega_al_cliente_como_clave_inexistente(
        self,
        cliente_de_prueba: TestClient,
        token_sentinela: str,
        inyectar_contrato: InyectarContrato,
    ) -> None:
        inyectar_contrato()

        respuesta = cliente_de_prueba.post(
            _RUTA,
            files={"archivos": ("informe.xlsx", b"entrada", "application/octet-stream")},
            headers=_cabecera(token_sentinela),
        )

        assert respuesta.status_code == 500
        assert respuesta.json() == {
            "tipo": "clave_inexistente",
            "contexto": {"clave_procesador": _CLAVE, "causa": "no_en_registry"},
        }
        assert _hijos_de_la_raiz() == []


class TestCopiaAcotada:
    """`_copiar` en aislamiento.

    A través de la ruta este techo no se alcanza: Starlette siempre mide
    `carga.size`, así que la comprobación previa gana. Se prueba por llamada
    directa, que es además el camino que los ítems #9/#10 podrían tomar sin
    comprobación previa alguna.
    """

    def test_corta_al_cruzar_el_limite_y_reporta_la_cuenta_real(self, tmp_path: Path) -> None:
        origen = io.BytesIO(b"x" * (3 * 1024 * 1024))
        destino = tmp_path / "salida"
        with pytest.raises(ErrorTamano) as capturado:
            _copiar(origen, destino, limite_bytes=1_024, nombre_original="grande.xlsx")
        # Un trozo de 1 MiB entero, no tres: dejó de leer al cruzar.
        assert capturado.value.contexto == {
            "archivo": "grande.xlsx",
            "limite_bytes": 1_024,
            "recibido_bytes": 1024 * 1024,
        }
        assert destino.stat().st_size == 1024 * 1024

    def test_deja_el_manejador_cerrado_al_abortar(self, tmp_path: Path) -> None:
        # La propiedad que importa en Windows: si el manejador siguiera abierto,
        # borrar levantaría `PermissionError` y la limpieza dejaría de ser
        # síncrona (ADR 0020).
        origen = io.BytesIO(b"x" * (2 * 1024 * 1024))
        destino = tmp_path / "salida"
        with pytest.raises(ErrorTamano):
            _copiar(origen, destino, limite_bytes=1, nombre_original="grande.xlsx")
        destino.unlink()
        assert not destino.exists()

    def test_sin_desborde_copia_verbatim_y_devuelve_la_cuenta(self, tmp_path: Path) -> None:
        contenido = b"contenido-de-prueba"
        destino = tmp_path / "salida"
        escritos = _copiar(
            io.BytesIO(contenido),
            destino,
            limite_bytes=1_000,
            nombre_original="informe.xlsx",
        )
        assert escritos == len(contenido)
        assert destino.read_bytes() == contenido

    def test_el_limite_exacto_no_rechaza(self, tmp_path: Path) -> None:
        contenido = b"y" * 1_000
        destino = tmp_path / "salida"
        assert (
            _copiar(
                io.BytesIO(contenido),
                destino,
                limite_bytes=1_000,
                nombre_original="justo.xlsx",
            )
            == 1_000
        )

    def test_reposiciona_el_cursor_del_origen(self, tmp_path: Path) -> None:
        origen = io.BytesIO(b"contenido-completo")
        origen.read(5)  # el parser podría dejar el cursor en cualquier lado
        destino = tmp_path / "salida"
        _copiar(origen, destino, limite_bytes=1_000, nombre_original="informe.xlsx")
        assert destino.read_bytes() == b"contenido-completo"


class TestValidacionDeEntradaHttp:
    def test_campo_archivos_ausente_da_422_sin_cuerpo(
        self, cliente_de_prueba: TestClient, token_sentinela: str
    ) -> None:
        respuesta = cliente_de_prueba.post(
            _RUTA,
            files={"otro_campo": ("x.xlsx", b"x", "application/octet-stream")},
            headers=_cabecera(token_sentinela),
        )
        assert respuesta.status_code == 422
        assert respuesta.content == b""

    def test_401_llega_sin_leer_el_cuerpo(self, cliente_de_prueba: TestClient) -> None:
        def _cuerpo_que_nunca_termina() -> Iterator[bytes]:
            # Un generador que jamás se agota: si la ruta llegara a leerlo,
            # la prueba colgaría en vez de fallar rápido.
            while True:
                yield b"0" * 1024

        respuesta = cliente_de_prueba.post(_RUTA, content=_cuerpo_que_nunca_termina())
        assert respuesta.status_code == 401
        assert respuesta.content == b""


class TestFormato:
    @pytest.mark.parametrize(
        "nombre_original,esperado",
        [
            ("a.b.XLSX", "xlsx"),
            ("sin-extension", ""),
            ("", ""),
            ("..\\x.xlsx", "xlsx"),
        ],
    )
    def test_formato_extrae_la_extension(self, nombre_original: str, esperado: str) -> None:
        assert _formato(nombre_original) == esperado


_SENTINELA_TOKEN_RECEPCION = "sentinela-recepcion-8b2f31cd"


def test_token_no_aparece_en_respuestas_ni_en_logs(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("TOKEN_SERVICIO", _SENTINELA_TOKEN_RECEPCION)
    from app.core.configuracion import obtener_configuracion

    obtener_configuracion.cache_clear()
    try:
        with caplog.at_level(logging.DEBUG):
            with TestClient(crear_app(), raise_server_exceptions=False) as cliente:
                # El ítem #10 cerró la costura, así que esta petición termina
                # de verdad en 200: el centinela pasa a cubrir también un
                # cuerpo de descarga y su `Content-Disposition`, no sólo
                # cuerpos de error.
                monkeypatch.setattr(
                    contrato_modulo,
                    "_TABLA_CONTRATOS",
                    MappingProxyType({_CLAVE: CONTRATO_POR_DEFECTO}),
                )

                def _modulo_falso(
                    *, clave: str, entradas: list[ArchivoEntrada], timeout: timedelta
                ) -> list[ArchivoSalida]:
                    return _passthrough(entradas)

                monkeypatch.setattr(pipeline, "ejecutar_modulo", _modulo_falso)

                exitosa = cliente.post(
                    _RUTA,
                    files={"archivos": ("x.xlsx", b"x", "application/octet-stream")},
                    headers=_cabecera(_SENTINELA_TOKEN_RECEPCION),
                )
                # Un rechazo tipificado del ítem #7, para que el centinela cubra
                # también los cuerpos 422 nuevos.
                rechazo_de_contrato = cliente.post(
                    _RUTA,
                    files={"archivos": ("enero.csv", b"a;b", "application/octet-stream")},
                    headers=_cabecera(_SENTINELA_TOKEN_RECEPCION),
                )
                rechazada = cliente.post(
                    _RUTA,
                    files={"archivos": ("x.xlsx", b"x", "application/octet-stream")},
                    headers=_cabecera("credencial-incorrecta"),
                )

                def _cuerpo_que_nunca_termina() -> Iterator[bytes]:
                    while True:
                        yield b"0" * 1024

                desconectada = cliente.post(_RUTA, content=_cuerpo_que_nunca_termina())

        assert exitosa.status_code == 200
        assert rechazo_de_contrato.status_code == 422
        assert rechazada.status_code == 401
        assert desconectada.status_code == 401

        cuerpos = (
            exitosa.text
            + exitosa.headers["content-disposition"]
            + rechazo_de_contrato.text
            + rechazada.text
            + desconectada.text
        )
        mensajes = "".join(record.getMessage() for record in caplog.records)
        assert _SENTINELA_TOKEN_RECEPCION not in cuerpos
        assert _SENTINELA_TOKEN_RECEPCION not in mensajes
    finally:
        obtener_configuracion.cache_clear()
