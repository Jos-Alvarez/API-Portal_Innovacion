"""Helper to run a Python snippet in a clean, fresh interpreter.

Several ordering/leak invariants (spawn fixation, token-secrecy, laziness)
can only be proven in a fresh interpreter: the pytest process's own
``multiprocessing`` state and module cache are already polluted by the time
any test body runs, and would produce a false pass.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class ResultadoSubproceso:
    """Resultado de ejecutar un snippet en un intérprete fresco."""

    codigo_salida: int
    salida: str


def ejecutar_snippet(codigo: str, *, env: dict[str, str] | None = None) -> ResultadoSubproceso:
    """Ejecuta ``codigo`` en un intérprete Python nuevo y limpio.

    Usa ``sys.executable`` con argv en lista y ``shell=False`` siempre
    (nunca ``shell=True``, nunca un string interpolado) para evitar
    inyección de comandos. Devuelve el código de salida y la salida
    combinada de stdout+stderr.
    """
    argv = [sys.executable, "-c", codigo]
    proceso = subprocess.run(  # noqa: S603 - argv en lista, shell=False, sin entrada de usuario
        argv,
        shell=False,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    salida = proceso.stdout + proceso.stderr
    return ResultadoSubproceso(codigo_salida=proceso.returncode, salida=salida)
