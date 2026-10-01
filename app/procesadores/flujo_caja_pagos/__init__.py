"""Procesador `flujo-caja-pagos` (consolidado de pagos programados semanales).

Sin imports de auto-registro, igual que los demás paquetes de
`app/procesadores/`: el alta vive en `app/registry.py` y este paquete debe ser
importable sin efectos de importación, porque el hijo de `spawn` (ADR 0012)
reimporta el árbol entero antes de buscar su instancia en `REGISTRY`.
"""
