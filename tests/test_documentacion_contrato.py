"""Pruebas de contenido estático para los cuatro escenarios de la spec que
no tienen comportamiento en tiempo de ejecución que probar (piso de Python,
alcance del health check, ausencia de scaffolding multi-worker, ADR 0016 +
H-08). Ver openspec/changes/esqueleto-servicio-arranque-seguro/verify-report.md
-- estos cuatro escenarios estaban marcados CRITICAL UNTESTED.
"""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path


def _raiz() -> Path:
    """Raíz del repositorio, resuelta desde la ubicación de este archivo,
    nunca desde el directorio de trabajo actual (Windows-safe).
    """
    return Path(__file__).resolve().parents[1]


# --- Requirement: Python version floor recorded independently of ADR 0012 ---


def test_piso_python_311_declarado() -> None:
    ruta = _raiz() / "pyproject.toml"
    with ruta.open("rb") as f:
        datos = tomllib.load(f)
    assert datos["project"]["requires-python"] == ">=3.11"


def test_piso_python_no_atribuye_a_adr_0012() -> None:
    """Ningún comentario/doc en pyproject.toml puede citar ADR 0012 como la
    razón del piso de Python (ADR 0012 degrada 3.11 a decisión de plataforma
    independiente). Se buscan patrones de atribución directa, no la mera
    mención de "ADR 0012" -- el comentario real lo nombra solo para
    descartarlo explícitamente como la razón.
    """
    texto = (_raiz() / "pyproject.toml").read_text(encoding="utf-8").lower()
    marcadores_de_atribucion_directa = [
        "por adr 0012",
        "segun adr 0012",
        "según adr 0012",
        "consecuencia de adr 0012",
        "requerido por adr 0012",
        "debido a adr 0012",
        "gracias a adr 0012",
    ]
    for marcador in marcadores_de_atribucion_directa:
        assert marcador not in texto, (
            f"pyproject.toml no debe atribuir el piso de Python a ADR 0012 "
            f"(patrón de atribución encontrado: {marcador!r})"
        )


# --- Requirement: Health response does not claim full functionality ---


def test_docstring_salud_documenta_las_cuatro_limitaciones() -> None:
    """El contrato documentado de GET /salud debe listar las cuatro cosas
    que un 200 no prueba: validez del token más allá del arranque,
    alcance de SQL Server, coincidencia registry<->catálogo, y que un
    procesador pueda ejecutar.
    """
    ruta = _raiz() / "app" / "salud.py"
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    funcion = next(
        nodo
        for nodo in ast.walk(arbol)
        if isinstance(nodo, ast.FunctionDef) and nodo.name == "obtener_salud"
    )
    docstring = (ast.get_docstring(funcion) or "").lower()
    assert docstring, "obtener_salud debe documentar su propio contrato"

    assert "token" in docstring, "falta la limitación sobre validez del token"
    assert "sql server" in docstring, "falta la limitación sobre alcance de SQL Server"
    assert "registry" in docstring, "falta la limitación sobre coincidencia registry<->catálogo"
    assert "catálogo" in docstring or "catalogo" in docstring, (
        "falta la limitación sobre coincidencia registry<->catálogo"
    )
    assert "procesador" in docstring, "falta la limitación sobre ejecución de un procesador"


# --- Requirement: No multi-worker deployment regression ---


def _bloques_de_codigo(texto: str) -> list[str]:
    return re.findall(r"```(?:[^\n]*)\n(.*?)```", texto, re.DOTALL)


def test_invocacion_canonica_no_usa_workers_multiples_ni_gunicorn() -> None:
    """La invocación documentada (el bloque de código real bajo 'Running the
    service') no debe usar --workers ni invocar Gunicorn. Se escanea solo el
    bloque de código de la invocación, no todo el texto: una búsqueda de
    substring ingenua sobre el README completo encontraría "--workers" en la
    propia oración que lo prohíbe.
    """
    texto = (_raiz() / "README.md").read_text(encoding="utf-8")
    bloques = _bloques_de_codigo(texto)
    invocaciones_uvicorn = [b for b in bloques if "uvicorn" in b and "run" in b]
    assert invocaciones_uvicorn, "README.md debe documentar la invocación canónica de uvicorn"

    for invocacion in invocaciones_uvicorn:
        assert "--workers" not in invocacion, (
            f"la invocación documentada no debe usar --workers: {invocacion!r}"
        )
        assert "gunicorn" not in invocacion.lower(), (
            f"la invocación documentada no debe invocar Gunicorn: {invocacion!r}"
        )


def test_ausencia_de_scaffolding_de_despliegue_declarada_explicitamente() -> None:
    """Si este cambio no agrega scaffolding de despliegue, esa ausencia debe
    quedar declarada explícitamente (no implícita), y la prohibición de
    --workers/Gunicorn debe estar dicha en el propio texto.
    """
    raiz = _raiz()

    # Sin Dockerfile, run script ni unit de servicio en el repositorio.
    candidatos_de_scaffolding = (
        list(raiz.glob("Dockerfile"))
        + list(raiz.glob("*.service"))
        + list(raiz.glob("run.sh"))
        + list(raiz.glob("run.ps1"))
    )
    assert candidatos_de_scaffolding == [], (
        f"no debe existir scaffolding de despliegue: {candidatos_de_scaffolding}"
    )

    texto = (raiz / "README.md").read_text(encoding="utf-8")
    assert "No deployment scaffolding ships in this change." in texto
    assert "forbidden" in texto.lower()
    assert "gunicorn" in texto.lower()
    assert "--workers" in texto  # mencionado en la oración de prohibición, no en la invocación


# --- Requirement: ADR 0016 resolves H-08 ---


def test_adr_0016_existe_con_formato_madr_de_sus_hermanas() -> None:
    ruta_adrs = _raiz() / "adrs"
    candidatos = list(ruta_adrs.glob("0016-*.md"))
    assert len(candidatos) == 1, (
        f"debe existir exactamente un adrs/0016-*.md, hallado: {candidatos}"
    )

    contenido = candidatos[0].read_text(encoding="utf-8")
    encabezados = {h.strip() for h in re.findall(r"^## (.+)$", contenido, re.MULTILINE)}

    encabezados_requeridos_sin_decision = {
        "Estado",
        "Contexto",
        "Alternativas consideradas",
        "Consecuencias",
    }
    assert encabezados_requeridos_sin_decision <= encabezados, (
        f"adrs/0016-*.md debe tener los encabezados MADR de adrs/0011-0015, faltan: "
        f"{encabezados_requeridos_sin_decision - encabezados}"
    )
    assert "Decisión" in encabezados or "Decision" in encabezados, (
        "adrs/0016-*.md debe tener una sección de Decisión"
    )


def test_h08_resuelto_en_revision_adversarial() -> None:
    contenido = (_raiz() / "REVISION-ADVERSARIAL.md").read_text(encoding="utf-8")
    lineas_h08 = [linea for linea in contenido.splitlines() if "H-08" in linea]
    assert lineas_h08, "REVISION-ADVERSARIAL.md debe seguir mencionando H-08"

    for linea in lineas_h08:
        assert "Abierto" not in linea, f"la fila de H-08 no debe seguir 'Abierto': {linea!r}"

    assert "ADR 0016" in contenido, "la resolución de H-08 debe referenciar ADR 0016"
