"""Procesadores `medios-pago-reportes` y `medios-pago-bbva-hits`.

Un solo paquete para las dos ventanas del portal: comparten la lectura y la
partición por fecha de los reportes crudos de Izipay (`izipay.py`). Sin
imports de auto-registro, igual que los demás paquetes de `app/procesadores/`:
el alta vive en `app/registry.py` y este paquete debe ser importable sin
efectos de importación, porque el hijo de `spawn` (ADR 0012) reimporta el
árbol entero antes de buscar su instancia en `REGISTRY`.
"""
