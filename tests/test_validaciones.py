"""Pruebas de `app.core.validaciones` (ítem #7, slice A2).

Behaviourales y en aislamiento: contratos construidos a mano, sin HTTP y sin
disco salvo en los casos de ZIP. Eso es posible exactamente porque el módulo
recibe primitivos y no tipos de Starlette (ADR 0021) — `_TABLA_CONTRATOS` sigue
vacía, así que no hay contrato real que resolver.

Convención de límites bajo prueba: un valor igual al límite se acepta; recién
el siguiente rechaza. Cada rechazo se comprueba sobre el `contexto` entero, no
campo por campo, para que un campo de más o de menos falle la prueba.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from app.core.contrato import ContratoProcesador
from app.core.errores import ErrorCantidad, ErrorFormato, ErrorTamano, TipoError
from app.core.tipos import ArchivoEntrada
from app.core.validaciones import (
    PRESUPUESTO_DE_RAM_BYTES,
    validar_cantidad,
    validar_formato,
    validar_tamano,
    validar_tamano_descomprimido,
    validar_tamano_total,
)

_CONTRATO = ContratoProcesador(
    entradas_min=1,
    entradas_max=3,
    formatos_aceptados=("xlsx", "xlsm"),
    tamano_max_bytes=1_000,
    tamano_max_total_bytes=2_500,
    activo=True,
)


def _entrada(ruta: Path, *, nombre_original: str = "informe.xlsx") -> ArchivoEntrada:
    return ArchivoEntrada(
        nombre_original=nombre_original,
        ruta_temporal=ruta,
        tamano_comprimido=ruta.stat().st_size,
        formato="xlsx",
    )


def _zip_declarando(tmp_path: Path, *tamanos: int) -> Path:
    """Un ZIP cuyo directorio central declara `tamanos` sin comprimir.

    El contenido son ceros, que comprimen muchísimo: el archivo en disco pesa
    una fracción de lo declarado. Ésa es la forma de una bomba ZIP, y lo que
    hace que la comprobación tenga sentido — el tope comprimido no acota lo
    descomprimido.
    """
    ruta = tmp_path / "bomba.xlsx"
    with zipfile.ZipFile(ruta, "w", zipfile.ZIP_DEFLATED) as archivo:
        for indice, tamano in enumerate(tamanos):
            archivo.writestr(f"hoja{indice}.xml", b"\0" * tamano)
    return ruta


class TestValidarCantidad:
    @pytest.mark.parametrize("recibido", [1, 2, 3])
    def test_acepta_dentro_del_rango_incluidos_los_bordes(self, recibido: int) -> None:
        validar_cantidad(recibido=recibido, contrato=_CONTRATO)

    @pytest.mark.parametrize("recibido", [0, 4])
    def test_rechaza_fuera_del_rango(self, recibido: int) -> None:
        with pytest.raises(ErrorCantidad) as capturado:
            validar_cantidad(recibido=recibido, contrato=_CONTRATO)
        assert capturado.value.tipo is TipoError.CANTIDAD
        assert capturado.value.contexto == {"minimo": 1, "maximo": 3, "recibido": recibido}


class TestValidarFormato:
    @pytest.mark.parametrize("formato", ["xlsx", "xlsm"])
    def test_acepta_los_formatos_del_contrato(self, formato: str) -> None:
        validar_formato(nombre_original="a.xlsx", formato=formato, contrato=_CONTRATO)

    @pytest.mark.parametrize("formato", ["csv", "", "XLSX"])
    def test_rechaza_lo_que_no_esta_en_el_contrato(self, formato: str) -> None:
        # "XLSX" en mayúsculas rechaza a propósito: normalizar es tarea de
        # `_formato()` en la superficie HTTP, no de esta comparación.
        with pytest.raises(ErrorFormato) as capturado:
            validar_formato(nombre_original="enero.csv", formato=formato, contrato=_CONTRATO)
        assert capturado.value.tipo is TipoError.FORMATO
        assert capturado.value.contexto == {
            "archivo": "enero.csv",
            "formato_recibido": formato,
            "formatos_aceptados": ["xlsx", "xlsm"],
        }

    def test_los_formatos_aceptados_viajan_como_lista_serializable(self) -> None:
        # El contrato los guarda en una tupla; el contexto debe llevar una lista,
        # que es lo que `JSONResponse` sabe serializar.
        with pytest.raises(ErrorFormato) as capturado:
            validar_formato(nombre_original="x.csv", formato="csv", contrato=_CONTRATO)
        assert isinstance(capturado.value.contexto["formatos_aceptados"], list)


class TestValidarTamano:
    @pytest.mark.parametrize("tamano_bytes", [0, 999, 1_000])
    def test_acepta_hasta_el_limite_inclusive(self, tamano_bytes: int) -> None:
        validar_tamano(nombre_original="a.xlsx", tamano_bytes=tamano_bytes, contrato=_CONTRATO)

    def test_rechaza_un_byte_por_encima(self) -> None:
        with pytest.raises(ErrorTamano) as capturado:
            validar_tamano(nombre_original="enero.xlsx", tamano_bytes=1_001, contrato=_CONTRATO)
        assert capturado.value.tipo is TipoError.TAMANO
        assert capturado.value.contexto == {
            "archivo": "enero.xlsx",
            "limite_bytes": 1_000,
            "recibido_bytes": 1_001,
        }


class TestValidarTamanoTotal:
    @pytest.mark.parametrize("total_bytes", [0, 2_499, 2_500])
    def test_acepta_hasta_el_limite_inclusive(self, total_bytes: int) -> None:
        validar_tamano_total(nombres=["a.xlsx"], total_bytes=total_bytes, contrato=_CONTRATO)

    def test_rechaza_con_la_forma_hermana_y_todos_los_nombres(self) -> None:
        nombres = ["enero.xlsx", "febrero.xlsx", "marzo.xlsx"]
        with pytest.raises(ErrorTamano) as capturado:
            validar_tamano_total(nombres=nombres, total_bytes=2_501, contrato=_CONTRATO)
        assert capturado.value.tipo is TipoError.TAMANO
        assert capturado.value.contexto == {
            "archivos": nombres,
            "limite_bytes": 2_500,
            "recibido_bytes": 2_501,
        }

    def test_el_contexto_no_lleva_archivo_singular(self) -> None:
        with pytest.raises(ErrorTamano) as capturado:
            validar_tamano_total(nombres=["a.xlsx"], total_bytes=9_999, contrato=_CONTRATO)
        assert "archivo" not in capturado.value.contexto

    def test_la_lista_de_nombres_es_una_copia(self) -> None:
        # Mutar la lista del llamador después del rechazo no debe cambiar el
        # contexto ya construido.
        nombres = ["enero.xlsx"]
        with pytest.raises(ErrorTamano) as capturado:
            validar_tamano_total(nombres=nombres, total_bytes=9_999, contrato=_CONTRATO)
        nombres.append("colado.xlsx")
        assert capturado.value.contexto == {
            "archivos": ["enero.xlsx"],
            "limite_bytes": 2_500,
            "recibido_bytes": 9_999,
        }


class TestValidarTamanoDescomprimido:
    def test_rechaza_lo_declarado_por_encima_del_presupuesto(self, tmp_path: Path) -> None:
        ruta = _zip_declarando(tmp_path, 100_000)
        with pytest.raises(ErrorTamano) as capturado:
            validar_tamano_descomprimido(_entrada(ruta), presupuesto_bytes=10_000)
        assert capturado.value.tipo is TipoError.TAMANO
        assert capturado.value.contexto == {
            "archivo": "informe.xlsx",
            "limite_bytes": 10_000,
            "recibido_bytes": 100_000,
        }

    def test_el_tope_comprimido_no_habria_alcanzado(self, tmp_path: Path) -> None:
        # La razón de existir de esta comprobación (H-04): el archivo en disco
        # pesa una fracción de lo que declara descomprimir, así que ningún
        # límite sobre el tamaño comprimido lo habría frenado.
        ruta = _zip_declarando(tmp_path, 1_000_000)
        assert ruta.stat().st_size < 10_000
        with pytest.raises(ErrorTamano):
            validar_tamano_descomprimido(_entrada(ruta), presupuesto_bytes=500_000)

    def test_acepta_lo_declarado_en_el_limite_exacto(self, tmp_path: Path) -> None:
        ruta = _zip_declarando(tmp_path, 10_000)
        validar_tamano_descomprimido(_entrada(ruta), presupuesto_bytes=10_000)

    def test_suma_todas_las_entradas_del_archivo(self, tmp_path: Path) -> None:
        # Por archivo, no por entrada: tres hojas de 4_000 pasan cada una pero
        # suman 12_000.
        ruta = _zip_declarando(tmp_path, 4_000, 4_000, 4_000)
        with pytest.raises(ErrorTamano) as capturado:
            validar_tamano_descomprimido(_entrada(ruta), presupuesto_bytes=10_000)
        assert capturado.value.contexto["recibido_bytes"] == 12_000

    def test_no_descomprime_ninguna_entrada(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Prueba de la propiedad, no del recuerdo: si la implementación abriera
        # o leyera el contenido de una entrada, esto reventaría antes de llegar
        # al `ErrorTamano`.
        ruta = _zip_declarando(tmp_path, 100_000)  # antes del cerrojo: escribir usa `open`

        def _prohibido(*_args: object, **_kwargs: object) -> object:
            raise AssertionError("se descomprimió contenido; debía leerse sólo el índice")

        monkeypatch.setattr(zipfile.ZipFile, "open", _prohibido)
        monkeypatch.setattr(zipfile.ZipFile, "read", _prohibido)

        with pytest.raises(ErrorTamano):
            validar_tamano_descomprimido(_entrada(ruta), presupuesto_bytes=10_000)

    def test_un_archivo_que_no_es_zip_es_un_no_op(self, tmp_path: Path) -> None:
        ruta = tmp_path / "plano.xlsx"
        ruta.write_bytes(b"esto no es un zip" * 100)
        validar_tamano_descomprimido(_entrada(ruta), presupuesto_bytes=1)

    def test_un_archivo_vacio_es_un_no_op(self, tmp_path: Path) -> None:
        ruta = tmp_path / "vacio.xlsx"
        ruta.write_bytes(b"")
        validar_tamano_descomprimido(_entrada(ruta), presupuesto_bytes=1)

    def test_magia_de_zip_seguida_de_basura_es_un_no_op(self, tmp_path: Path) -> None:
        # Sin registro de fin de directorio central: `is_zipfile` ya dice que
        # no, y no se llega a abrirlo.
        ruta = tmp_path / "corrupto.xlsx"
        ruta.write_bytes(b"PK\x03\x04" + b"\xff" * 200)
        validar_tamano_descomprimido(_entrada(ruta), presupuesto_bytes=1)

    def test_un_zip_con_directorio_central_roto_es_un_no_op(self, tmp_path: Path) -> None:
        # El caso que de verdad ejercita `BadZipFile`: el registro de fin sigue
        # intacto, así que `is_zipfile` dice que sí, y recién al leer el índice
        # revienta. Decidir si esto es un `.xlsx` válido es validación de
        # **contenido**, y el enum cerrado de ADR 0014 no tiene vocabulario para
        # expresarlo. Lo falla el procesador (ítems #12/#16), no esta función.
        ruta = _zip_declarando(tmp_path, 1_000)
        crudo = ruta.read_bytes()
        posicion = crudo.index(b"PK\x01\x02")  # cabecera del directorio central
        ruta.write_bytes(crudo[:posicion] + b"XXXX" + crudo[posicion + 4 :])

        assert zipfile.is_zipfile(ruta)  # el registro de fin quedó intacto
        with pytest.raises(zipfile.BadZipFile):  # y leer el índice falla
            zipfile.ZipFile(ruta).infolist()

        validar_tamano_descomprimido(_entrada(ruta), presupuesto_bytes=1)

    def test_el_presupuesto_por_defecto_es_el_de_modulo(self, tmp_path: Path) -> None:
        ruta = _zip_declarando(tmp_path, 100_000)
        validar_tamano_descomprimido(_entrada(ruta))


def test_presupuesto_de_ram_es_256_mib() -> None:
    # Elección con piso fundado (ADR 0021), pinchada acá para que moverla sea
    # una decisión visible en el diff, no una deriva.
    assert PRESUPUESTO_DE_RAM_BYTES == 256 * 1024 * 1024
