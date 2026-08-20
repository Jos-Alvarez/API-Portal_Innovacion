"""Invariantes de arquitectura verificados por la suite (ítem #13; ADR 0011, ADR 0013).

Tres reglas que hasta acá vivían sólo en prosa —`TECH-DESIGN.md:288-298`, la
docstring de `app/registry.py` y la de `app/core/pipeline.py`— y que a partir
de este módulo fallan el build cuando alguien las rompe. La CI de este
repositorio es esta suite: no hay workflow aparte, la verificación es
`uv run pytest` junto a `ruff` y `mypy`.

**Alcance de cada regla, que no es el mismo y no es un descuido:**

- `core/` → `procesadores/` se verifica sobre imports **DIRECTOS**. La
  decisión está tomada y documentada en `app/registry.py`: la arista
  transitiva `app/core/ejecucion.py` → `app.registry` → `app.procesadores…`
  es inevitable desde el ítem #12, porque el hijo de `spawn` necesita
  encontrar su procesador en `REGISTRY` y la alternativa era un import por
  nombre dentro de `core/`, justo lo que ADR 0012 descarta. La evidencia de
  que el alcance es el correcto es textual y asimétrica: `TECH-DESIGN.md:291`
  califica la regla de `core.db` con "ni directa ni transitivamente" y
  `TECH-DESIGN.md:289` **no** califica así la de `core/` → `procesadores/`.
- `procesadores/` → `core.db` se verifica **TRANSITIVAMENTE**, cerrando el
  grafo de imports internos. Es la regla que ADR 0013 necesita: el hijo
  hereda las credenciales por variable de entorno, así que nada más que esta
  comprobación impide que un módulo de negocio llegue a la base.
- Cada ruta de procesador delega en `ejecutar_pipeline` y no reimplementa los
  pasos 6-8 por su cuenta.

**Una comprobación de `TECH-DESIGN.md` que a propósito NO está acá:** "buscar
el nombre de cualquier procesador dentro de `core/` devuelve cero
resultados". Hoy devuelve resultados y no por un error: `app/core/contrato.py`
contiene `_TABLA_CONTRATOS` con las claves `passthrough` y `passthrough_multi`
literales, porque el ítem #5 se desvió y esas filas todavía no viven en SQL
Server. Son datos, no imports, y el invariante que importa —que `core/` no
dependa del código de ningún procesador— lo cubre la primera regla. La
comprobación vuelve a ser exigible cuando el lector real de la base reemplace
esa tabla.

`app.core.db` todavía no existe (ítem #5 desviado). La regla se escribe igual
y hoy pasa sin encontrar nada: el día que el módulo aparezca, la comprobación
ya está puesta en vez de tener que acordarse. Que el recorrido transitivo
tiene dientes de verdad lo prueba
`test_el_recorrido_transitivo_ve_aristas_indirectas`, contra una arista real
del repositorio.
"""

from __future__ import annotations

import ast
from collections import deque
from collections.abc import Iterator
from pathlib import Path

from starlette.routing import Mount, Route

_RAIZ = Path(__file__).resolve().parent.parent
_APP = _RAIZ / "app"
_NUCLEO = "app.core"
_PROCESADORES = "app.procesadores"
_ACCESO_A_DATOS = "app.core.db"
_MONTAJE_INTERNO = "/interno"


def _nombre_de_modulo(ruta: Path) -> str:
    """Nombre punteado del módulo, con `__init__.py` colapsado a su paquete."""
    partes = ruta.relative_to(_RAIZ).with_suffix("").parts
    if partes[-1] == "__init__":
        partes = partes[:-1]
    return ".".join(partes)


def _modulos() -> dict[str, Path]:
    return {_nombre_de_modulo(ruta): ruta for ruta in sorted(_APP.rglob("*.py"))}


def _arbol(ruta: Path) -> ast.Module:
    return ast.parse(ruta.read_text(encoding="utf-8"), filename=str(ruta))


def _es_de(modulo: str, paquete: str) -> bool:
    """`True` si `modulo` es el paquete o vive adentro, sin coincidir por prefijo textual."""
    return modulo == paquete or modulo.startswith(f"{paquete}.")


def _paquete_contenedor(modulo: str, ruta: Path) -> str:
    """Paquete desde el que se resuelve un import relativo de nivel 1."""
    if ruta.name == "__init__.py":
        return modulo
    return modulo.rpartition(".")[0]


def _importados(modulo: str, ruta: Path, conocidos: frozenset[str]) -> set[str]:
    """Módulos internos que `modulo` importa **directamente**.

    De `from app.core.errores import ErrorTipificado` sale `app.core.errores`;
    de `from app.procesadores import passthrough` salen el paquete y el
    submódulo, porque el segundo es un módulo de verdad y la sintaxis no
    distingue entre importar un nombre e importar un submódulo. También se
    anotan los paquetes ancestro: CPython inicializa el padre antes que el
    hijo, así que son aristas reales del grafo de ejecución.
    """
    encontrados: set[str] = set()

    def anotar(nombre: str) -> None:
        if not _es_de(nombre, "app"):
            return
        partes = nombre.split(".")
        for corte in range(1, len(partes) + 1):
            ancestro = ".".join(partes[:corte])
            if ancestro in conocidos:
                encontrados.add(ancestro)

    for nodo in ast.walk(_arbol(ruta)):
        if isinstance(nodo, ast.Import):
            for alias in nodo.names:
                anotar(alias.name)
        elif isinstance(nodo, ast.ImportFrom):
            raiz = _raiz_de_import_from(nodo, modulo, ruta)
            if not raiz:
                continue
            anotar(raiz)
            for alias in nodo.names:
                anotar(f"{raiz}.{alias.name}")

    return encontrados


def _raiz_de_import_from(nodo: ast.ImportFrom, modulo: str, ruta: Path) -> str:
    """Módulo del que cuelga un `from … import …`, con los relativos resueltos."""
    if not nodo.level:
        return nodo.module or ""
    base = _paquete_contenedor(modulo, ruta).split(".")
    recorte = len(base) - (nodo.level - 1)
    ancla = ".".join(base[:recorte]) if recorte > 0 else ""
    if not nodo.module:
        return ancla
    return f"{ancla}.{nodo.module}" if ancla else nodo.module


def _grafo() -> dict[str, set[str]]:
    modulos = _modulos()
    conocidos = frozenset(modulos)
    return {
        nombre: _importados(nombre, ruta, conocidos) for nombre, ruta in sorted(modulos.items())
    }


def _alcanzables(inicio: str, grafo: dict[str, set[str]]) -> set[str]:
    """Cierre transitivo de imports internos desde `inicio`, sin incluirlo."""
    vistos: set[str] = set()
    pendientes = deque(grafo.get(inicio, set()))
    while pendientes:
        actual = pendientes.popleft()
        if actual in vistos:
            continue
        vistos.add(actual)
        pendientes.extend(grafo.get(actual, set()))
    vistos.discard(inicio)
    return vistos


def test_hay_sustrato_para_revisar() -> None:
    """Ninguno de los tres invariantes puede pasar por lista vacía."""
    grafo = _grafo()
    assert [m for m in grafo if _es_de(m, _NUCLEO)], "no se encontró ningún módulo de core/"
    assert [m for m in grafo if _es_de(m, _PROCESADORES)], "no se encontró ningún procesador"


def test_el_nucleo_no_importa_procesadores() -> None:
    """ADR 0011: `core/` no sabe que `procesadores/` existe (imports directos)."""
    culpables = {
        modulo: sorted(i for i in importados if _es_de(i, _PROCESADORES))
        for modulo, importados in _grafo().items()
        if _es_de(modulo, _NUCLEO) and any(_es_de(i, _PROCESADORES) for i in importados)
    }
    assert not culpables, (
        f"core/ importa procesadores/ directamente: {culpables}. "
        "El punto de unión legítimo es app/registry.py, que no es core/."
    )


def test_ningun_procesador_alcanza_el_acceso_a_datos() -> None:
    """ADR 0013: ningún procesador llega a `core.db`, ni directa ni transitivamente."""
    grafo = _grafo()
    culpables: dict[str, list[str]] = {}
    for modulo in grafo:
        if not _es_de(modulo, _PROCESADORES):
            continue
        alcance = sorted(a for a in _alcanzables(modulo, grafo) if _es_de(a, _ACCESO_A_DATOS))
        if alcance:
            culpables[modulo] = alcance
    assert not culpables, (
        f"un procesador alcanza el acceso a datos: {culpables}. "
        "Un módulo de negocio recibe sus entradas ya materializadas en disco."
    )


def test_el_recorrido_transitivo_ve_aristas_indirectas() -> None:
    """Los dientes de la regla anterior, probados contra una arista real.

    `app.core.ejecucion` no importa ningún procesador —eso lo garantiza
    `test_el_nucleo_no_importa_procesadores`— pero **sí** alcanza uno pasando
    por `app.registry`. Si el recorrido no viera esa arista, el invariante de
    `core.db` estaría pasando por no mirar, no por estar limpio.
    """
    grafo = _grafo()
    origen = "app.core.ejecucion"
    directos = grafo[origen]
    alcanzables = _alcanzables(origen, grafo)

    assert not [i for i in directos if _es_de(i, _PROCESADORES)]
    assert "app.registry" in directos
    indirectos = sorted(a for a in alcanzables if _es_de(a, _PROCESADORES))
    assert indirectos, (
        "se esperaba alcanzar un procesador de forma transitiva vía app.registry; "
        "si el registry se vació, este test perdió su sujeto y hay que darle otro"
    )


_ATRIBUTOS_DE_DESCENSO = ("routes", "original_router", "_base_app", "app", "router")


def _rutas_bajo(objeto: object, vistos: set[int]) -> Iterator[Route]:
    """Toda `Route` colgada de `objeto`, sin suponer cómo la envolvió FastAPI.

    El descenso es a ciegas y a propósito. Entre el `Mount` y la ruta hay hoy
    dos middlewares y un `_IncludedRouter` perezoso que esta versión de
    FastAPI interpone; nada de eso es contrato público y ya cambió una vez.
    Un walker genérico sobrevive a la próxima versión; lo que no puede pasar
    es que deje de encontrar rutas en silencio, y de eso se ocupa
    `test_hay_al_menos_una_ruta_de_procesador`.
    """
    if id(objeto) in vistos:
        return
    vistos.add(id(objeto))
    if isinstance(objeto, Route):
        yield objeto
        return
    if isinstance(objeto, list | tuple):
        for elemento in objeto:
            yield from _rutas_bajo(elemento, vistos)
        return
    for atributo in _ATRIBUTOS_DE_DESCENSO:
        hijo = getattr(objeto, atributo, None)
        if hijo is not None and not isinstance(hijo, str | bytes):
            yield from _rutas_bajo(hijo, vistos)


def _rutas_de_procesador() -> list[Route]:
    """Rutas montadas bajo `/interno`: la frontera autenticada de `crear_app()`.

    La pertenencia se lee del montaje, nunca de una lista de rutas escrita a
    mano (ADR 0016, ADR 0019): una ruta nueva entra sola a este test por el
    solo hecho de registrarse donde corresponde.
    """
    from app.main import crear_app

    encontradas: list[Route] = []
    for ruta in crear_app().router.routes:
        if isinstance(ruta, Mount) and ruta.path == _MONTAJE_INTERNO:
            encontradas.extend(_rutas_bajo(ruta.routes, set()))
    return encontradas


def _funcion(modulo: str, nombre: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    ruta = _modulos()[modulo]
    for nodo in ast.walk(_arbol(ruta)):
        if isinstance(nodo, ast.FunctionDef | ast.AsyncFunctionDef) and nodo.name == nombre:
            return nodo
    raise AssertionError(f"no se encontró {nombre!r} en {modulo}")


def _referencias(nodo: ast.AST) -> set[str]:
    """Nombres mencionados en el cuerpo, se los llame o se los pase como argumento.

    `recepcion.py` no escribe `ejecutar_pipeline(...)`: se lo pasa a
    `run_in_threadpool`, porque el pipeline bloquea de verdad. Buscar sólo
    llamadas directas daría un falso negativo en la única ruta que existe.
    """
    return {hijo.id for hijo in ast.walk(nodo) if isinstance(hijo, ast.Name)}


def test_hay_al_menos_una_ruta_de_procesador() -> None:
    assert _rutas_de_procesador(), f"no hay ninguna ruta montada bajo {_MONTAJE_INTERNO}"


def test_cada_ruta_de_procesador_delega_en_el_pipeline() -> None:
    """`TECH-DESIGN.md:297`: **cada** ruta delega en el pipeline común."""
    for ruta in _rutas_de_procesador():
        endpoint = ruta.endpoint
        cuerpo = _funcion(endpoint.__module__, endpoint.__name__)
        assert "ejecutar_pipeline" in _referencias(cuerpo), (
            f"la ruta {ruta.path} ({endpoint.__module__}.{endpoint.__name__}) no delega "
            "en app.core.pipeline.ejecutar_pipeline"
        )


def test_ninguna_ruta_de_procesador_reimplementa_el_pipeline() -> None:
    """El reparto de los nueve pasos, hecho comprobación.

    Una ruta conserva los pasos 1-5 y el 9 (necesitan `UploadFile` y tipos de
    Starlette); los pasos 6-8 son del pipeline. Llamar `ejecutar_modulo` o
    `empaquetar` desde una ruta es reimplementarlo, aunque el resultado
    coincida hoy.
    """
    prohibidas = {"ejecutar_modulo", "empaquetar"}
    for ruta in _rutas_de_procesador():
        endpoint = ruta.endpoint
        cuerpo = _funcion(endpoint.__module__, endpoint.__name__)
        invasiones = sorted(prohibidas & _referencias(cuerpo))
        assert not invasiones, (
            f"la ruta {ruta.path} usa {invasiones} por su cuenta; los pasos 6-8 son "
            "de app.core.pipeline.ejecutar_pipeline"
        )
