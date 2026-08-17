"""Pruebas estructurales (AST) del ítem #2 — design.md §6, §4 y §8.

Estas pruebas verifican por inspección, nunca por medición de tiempo
(`TECH-DESIGN.md:221`), que la comparación es de tiempo constante, que
`get_secret_value()` tiene un único sitio de llamada en todo el repositorio,
y que ninguna aplicación se construye con `debug=True`.
"""

from __future__ import annotations

import ast
from pathlib import Path

_RAIZ = Path(__file__).resolve().parent.parent
_MODULO_SEGURIDAD = _RAIZ / "app" / "core" / "seguridad.py"


def _arbol(ruta: Path) -> ast.Module:
    return ast.parse(ruta.read_text(encoding="utf-8"), filename=str(ruta))


def _buscar_funcion(arbol: ast.AST, nombre: str) -> ast.FunctionDef:
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.FunctionDef) and nodo.name == nombre:
            return nodo
    raise AssertionError(f"no se encontró la función {nombre!r}")


def test_comparacion_es_de_tiempo_constante() -> None:
    arbol = _arbol(_MODULO_SEGURIDAD)
    coincide = _buscar_funcion(arbol, "_coincide")
    assert len(coincide.body) == 1
    (unico,) = coincide.body
    assert isinstance(unico, ast.Return)
    assert isinstance(unico.value, ast.Call)
    llamada = unico.value
    assert isinstance(llamada.func, ast.Attribute)
    assert llamada.func.attr == "compare_digest"
    assert isinstance(llamada.func.value, ast.Name)
    assert llamada.func.value.id == "hmac"


def test_no_hay_comparacion_por_longitud() -> None:
    arbol = _arbol(_MODULO_SEGURIDAD)
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name):
            assert nodo.func.id != "len", "len() no debe usarse en seguridad.py"


def test_compare_digest_se_usa_una_sola_vez() -> None:
    arbol = _arbol(_MODULO_SEGURIDAD)
    llamadas = [
        nodo
        for nodo in ast.walk(arbol)
        if isinstance(nodo, ast.Call)
        and isinstance(nodo.func, ast.Attribute)
        and nodo.func.attr == "compare_digest"
    ]
    assert len(llamadas) == 1
    importa_hmac = any(
        isinstance(nodo, ast.Import) and any(alias.name == "hmac" for alias in nodo.names)
        for nodo in ast.walk(arbol)
    )
    assert importa_hmac


def test_la_credencial_nunca_se_normaliza() -> None:
    arbol = _arbol(_MODULO_SEGURIDAD)
    for nodo in ast.walk(arbol):
        if (
            isinstance(nodo, ast.Call)
            and isinstance(nodo.func, ast.Attribute)
            and nodo.func.attr in {"lower", "upper", "strip"}
            and isinstance(nodo.func.value, ast.Name)
        ):
            assert nodo.func.value.id != "credencial", (
                "la credencial no debe normalizarse; solo el esquema puede hacerlo"
            )


def _llamadas_get_secret_value(ruta: Path) -> list[ast.Call]:
    arbol = _arbol(ruta)
    return [
        nodo
        for nodo in ast.walk(arbol)
        if isinstance(nodo, ast.Call)
        and isinstance(nodo.func, ast.Attribute)
        and nodo.func.attr == "get_secret_value"
    ]


def _es_argumento_de_logging_o_formato(nodo: ast.Call, arbol: ast.AST) -> bool:
    """Determina si `nodo` es argumento de una llamada de logging/formato,
    o si está dentro de un f-string (`JoinedStr`)."""
    for padre in ast.walk(arbol):
        if isinstance(padre, ast.JoinedStr) and nodo in ast.walk(padre):
            return True
        if isinstance(padre, ast.Call) and nodo in padre.args + [kw.value for kw in padre.keywords]:
            objetivo = padre.func
            if isinstance(objetivo, ast.Attribute) and objetivo.attr in {
                "format",
                "debug",
                "info",
                "warning",
                "error",
                "critical",
                "exception",
            }:
                return True
            if isinstance(objetivo, ast.Name) and objetivo.id == "print":
                return True
    return False


def test_get_secret_value_un_solo_sitio() -> None:
    total = 0
    sitios: list[tuple[Path, ast.Call]] = []
    for ruta in sorted((_RAIZ / "app").rglob("*.py")):
        for llamada in _llamadas_get_secret_value(ruta):
            total += 1
            sitios.append((ruta, llamada))
    assert total == 1, f"se esperaba exactamente un get_secret_value(), hubo {total}: {sitios}"
    ruta_unica, llamada_unica = sitios[0]
    assert ruta_unica == _MODULO_SEGURIDAD
    arbol_unico = _arbol(ruta_unica)
    assert not _es_argumento_de_logging_o_formato(llamada_unica, arbol_unico)


def _construcciones_de_app(ruta: Path) -> list[ast.Call]:
    arbol = _arbol(ruta)
    resultado = []
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.Call):
            continue
        objetivo = nodo.func
        if (isinstance(objetivo, ast.Name) and objetivo.id in {"FastAPI", "Starlette"}) or (
            isinstance(objetivo, ast.Attribute) and objetivo.attr in {"FastAPI", "Starlette"}
        ):
            resultado.append(nodo)
    return resultado


def test_sin_debug_true() -> None:
    for carpeta in (_RAIZ / "app", _RAIZ / "tests"):
        for ruta in sorted(carpeta.rglob("*.py")):
            for llamada in _construcciones_de_app(ruta):
                for kw in llamada.keywords:
                    if kw.arg == "debug":
                        assert isinstance(kw.value, ast.Constant) and kw.value.value is False, (
                            f"debug=True (o no-constante) en {ruta}:{llamada.lineno}"
                        )
