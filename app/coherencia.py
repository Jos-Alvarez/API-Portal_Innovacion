"""Chequeo de arranque: el registry contra la tabla de contratos (ítem #11).

Convierte una desincronización entre `app.registry.REGISTRY` y la tabla de
`app.core.contrato` —hoy un 500 en producción, delante de un usuario que ya
subió su archivo— en un fallo o una advertencia en el arranque del despliegue.
Implementa la tabla de tres situaciones de TECH-DESIGN.md:

| Situación | Qué hace el arranque |
|---|---|
| Clave en el registry sin fila de contrato | **Falla**, nombrando la clave |
| Clave en el registry con fila `activo = False` | **Arranca**, con advertencia |
| Fila activa sin entrada en el registry | **Arranca**, con advertencia |

**Por qué vive en `app/` y no en `app/core/`.** Necesita `REGISTRY`, y un
módulo de `core/` que lo importara agregaría una segunda arista hacia afuera
del núcleo. La primera —`app/core/ejecucion.py:54`— se concedió por necesidad:
el hijo de `spawn` (ADR 0012) tiene que alcanzar procesadores concretos para
poder ejecutarlos, y no hay otro camino. Acá esa necesidad no existe: este
chequeo corre en el proceso padre, una sola vez, desde el lifespan. Colgarlo
de `app/` —junto a `recepcion.py`, `registry.py`, `salud.py` y `arranque.py`,
que son los otros módulos que sí conocen las dos mitades— mantiene el
invariante de ADR 0011 exactamente donde estaba.

**Cuándo corre.** Desde `app.main`, envuelto alrededor de
`app.core.temporales.ciclo_de_vida` y **dentro** de su cuerpo, nunca antes:
`ciclo_de_vida` llama primero a `obtener_configuracion()` y el orden es una
regla, no una casualidad. Un token faltante debe fallar siempre primero, para
que ningún otro problema de arranque pueda enmascarar un error de
configuración.

---

**Desviación 1: no hay rama de "no pude conectar", y se elimina a conciencia.**

BACKLOG fila 11 pide "mensaje distinto para 'no pude conectar' y 'el registry
no coincide'", y TECH-DESIGN lo repite en sus criterios de aceptación. Ese
requisito presupone la base de datos de ADR 0013, que el ítem #5 **no**
entregó: no hay instancia de SQL Server, no hay driver en `pyproject.toml`, y
`obtener_contrato`/`obtener_tabla_contratos` son lecturas de un
`MappingProxyType` en memoria, sin E/S de ninguna clase.
`tests/test_contrato_estatico.py` va más lejos y lo prueba: parchea
`socket.socket.connect` para que levante y afirma que la búsqueda igual
resuelve. Un `except` por fallo de conexión acá sería código muerto por
construcción, y bajo `warn_unreachable = true` mypy lo diría en voz alta.

La rama vuelve —con su mensaje propio y su culpable propio— cuando el ítem #5
entregue el lector real detrás de la firma inalterada de
`obtener_tabla_contratos`. La distinción entre los dos culpables sigue siendo
correcta; simplemente hoy sólo existe uno de los dos.

**Desviación 2: el fundamento de la asimetría está vacío hoy, y la asimetría
se implementa igual.**

TECH-DESIGN justifica que el arranque falle en un caso y sólo advierta en los
otros dos así: el arranque falla por lo que este repositorio controla (su
código) y sólo advierte por lo que administra el portal (las filas), porque
"un chequeo que fallara en los tres casos le daría a un administrador la
capacidad de impedir el arranque del servicio desde un formulario web".

Ese razonamiento no aplica al estado actual. Con la tabla de contratos en
código, las dos mitades las edita este repositorio, en el mismo commit: no hay
panel de administración, no hay filas administradas por el portal y nadie
puede tumbar el servicio desde un formulario. Lo que el fail/warn asimétrico
protege hoy es otra cosa, más chica: un error al editar dos diccionarios que
tienen que decir lo mismo. La asimetría se implementa tal cual está
especificada de todos modos, para que la conducta ya sea la correcta el día
que el catálogo real vuelva y el fundamento original recupere su sentido.
"""

from __future__ import annotations

from typing import Final

from app.core.contrato import obtener_tabla_contratos
from app.core.registro import obtener_logger, sanear_texto
from app.registry import REGISTRY

EVENTO_CONTRATO_INACTIVO: Final[str] = "contrato_inactivo"
EVENTO_CONTRATO_SIN_REGISTRY: Final[str] = "contrato_sin_registry"


class RegistrySinContrato(RuntimeError):
    """Hay claves en el registry sin ninguna fila de contrato. No se arranca.

    Tipo propio y no un `RuntimeError` pelado, siguiendo el precedente de
    `ConfiguracionInvalida` (`app/core/configuracion.py`) y
    `ArranqueInseguroError` (`app/arranque.py`): quien atrape esto tiene que
    poder distinguir un despliegue incompleto de cualquier otra falla de
    arranque. El mensaje nombra siempre las claves ofensoras — son literales de
    este repositorio, nunca entrada de un cliente.
    """


def contrastar_registry_contra_contratos() -> None:
    """Contrasta `REGISTRY` contra la tabla de contratos (tabla de arriba).

    Levanta `RegistrySinContrato` si alguna clave registrada en el código no
    tiene fila; en los otros dos casos advierte y devuelve.

    **El fallo se evalúa primero y corta.** Si el despliegue está incompleto,
    el arranque no ocurre: emitir antes un puñado de advertencias sobre otras
    claves sólo agregaría ruido delante del único mensaje que el operador
    necesita leer. Y nombra **todas** las claves sin fila de una vez, no la
    primera: quien arregla el despliegue quiere la lista entera en el primer
    intento.

    **Una fila inactiva sin entrada en el registry no dice nada, a propósito.**
    La tabla de TECH-DESIGN advierte por una fila *activa* sin entrada en el
    registry, y la palabra es deliberada: esa fila anuncia una ruta que el
    portal cree viva y que el servicio no puede atender. Una fila inactiva no
    anuncia nada — está apagada — así que una sin código detrás es justamente
    el estado final esperado de una baja, no un síntoma. Advertir por ella
    convertiría cada procesador retirado en ruido permanente en la bitácora.
    """
    tabla = obtener_tabla_contratos()
    claves_registradas = frozenset(REGISTRY)

    sin_fila = sorted(claves_registradas - frozenset(tabla))
    if sin_fila:
        nombradas = ", ".join(repr(sanear_texto(clave)) for clave in sin_fila)
        raise RegistrySinContrato(
            "Despliegue incompleto: hay claves en el registry de procesadores "
            f"sin fila de contrato ({nombradas}). Su ruta está viva y ninguna "
            "petición contra ella podría ejecutarse."
        )

    logger = obtener_logger()

    for clave in sorted(clave for clave in claves_registradas if not tabla[clave].activo):
        logger.warning(
            "procesador registrado con contrato inactivo",
            extra={
                "evento": EVENTO_CONTRATO_INACTIVO,
                "clave": sanear_texto(clave),
            },
        )

    huerfanas = sorted(
        clave for clave, fila in tabla.items() if fila.activo and clave not in claves_registradas
    )
    for clave in huerfanas:
        logger.warning(
            "contrato activo sin procesador en el registry",
            extra={
                "evento": EVENTO_CONTRATO_SIN_REGISTRY,
                "clave": sanear_texto(clave),
            },
        )
