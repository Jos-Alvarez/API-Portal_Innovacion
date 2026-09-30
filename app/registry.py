"""Registro de procesadores (ADR 0011, ítem #4 del backlog).

Punto de unión deliberadamente fuera de `core/`: es la única excepción
legítima al invariante de ADR 0011 ("`core/` no sabe que `procesadores/`
existe"), porque el registro necesita conocer procesadores concretos que
`core/` nunca debe importar. Real, tipado y —desde el ítem #12— con los dos
procesadores passthrough dados de alta.

El alta es este literal y nada más. No hay ningún `registrar()` ni ningún
import de auto-registro en `app/procesadores/__init__.py`: un procesador debe
ser importable sin efectos de importación, porque el hijo de ADR 0012
(`spawn`) reimporta el árbol de módulos entero antes de buscar su instancia
en `REGISTRY` por `clave` (`app/core/interfaz.py`).

Una sola clase bajo dos claves: ADR 0006 fija la cardinalidad en la fila
`procesador` (`entradas_min`/`entradas_max`, acá en
`app.core.contrato._TABLA_CONTRATOS`), no en el módulo, y prohíbe que un
procesador ramifique por cantidad de entradas. La variante multi-archivo del
passthrough es por lo tanto otra fila de contrato, no otro código.

**El borde `core/` → `procesadores/`, y hasta dónde llega el invariante.**
Registrar un procesador concreto convierte el `from app.registry import
REGISTRY` de `app/core/ejecucion.py:54` en una arista **transitiva**
`core/` → `procesadores/`. La decisión tomada acá es que el invariante de
ADR 0011 —y la comprobación de CI que el ítem #13 escribirá— quedan acotados
a los imports **directos**: ningún `core/*.py` puede contener
`from app.procesadores…`; `registry.py`, que no es `core/`, sí puede. La
evidencia es textual y asimétrica: `TECH-DESIGN.md:291` califica la regla de
`core.db` con "ni directa **ni transitivamente**", mientras que la regla
`core/` → `procesadores/` de `TECH-DESIGN.md:289` no lleva esa calificación;
y este módulo ya se declaraba a sí mismo la excepción legítima. Sin este
alcance, la única forma de que el hijo encontrara su procesador sería un
import por nombre dentro de `core/`, que es precisamente lo que ADR 0012
descarta. **El ítem #13 es el dueño de esa comprobación y debe honrar este
alcance.**
"""

from __future__ import annotations

from app.core.interfaz import Procesador
from app.procesadores.asientos_contables.modulo import AsientosContables
from app.procesadores.contado_carga.modulo import ContadoCarga
from app.procesadores.passthrough.modulo import Passthrough
from app.procesadores.prepago_carga.modulo import PrepagoCarga
from app.procesadores.registro_sencillo.modulo import RegistroSencillo

REGISTRY: dict[str, Procesador] = {
    "passthrough": Passthrough(clave="passthrough"),
    "passthrough_multi": Passthrough(clave="passthrough_multi"),
    "contado-carga": ContadoCarga(),
    "asientos-contables": AsientosContables(),
    "prepago-carga": PrepagoCarga(),
    "registro-sencillo": RegistroSencillo(),
}
