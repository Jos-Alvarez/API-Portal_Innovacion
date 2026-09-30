"""Procesador `Registro_Sencillo` (transferencias entre cuentas de peaje sencillo).

Sin imports de auto-registro, igual que `app/procesadores/prepago_carga`: el
alta vive en `app/registry.py` y este paquete debe ser importable sin efectos
de importación, porque el hijo de `spawn` (ADR 0012) reimporta el árbol
entero antes de buscar su instancia en `REGISTRY`.
"""
