"""Paquete del procesador passthrough (ítem #12 del backlog).

Vacío a propósito, igual que `app/procesadores/__init__.py`: la
implementación vive en `modulo.py` y el alta es la entrada del literal de
`app/registry.py`. Ningún import acá, para que importar este paquete no
tenga efecto alguno (precondición de `spawn`, ADR 0012).

La ruta cáscara (`ruta.py` en el árbol de ADR 0011) no forma parte de esta
entrega: hoy la recepción sigue pasando por la ruta parametrizada de
andamiaje `POST /procesadores/{clave_procesador}` de `app/recepcion.py`.
Reemplazarla por rutas literales por procesador es un ítem aparte.
"""
