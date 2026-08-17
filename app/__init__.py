"""Paquete raíz del servicio."""

# LOAD-BEARING: no borrar ni "limpiar" esta llamada, y no moverla a
# main.py. Es lo único que este archivo hace, a propósito: CPython
# inicializa un paquete padre antes que cualquiera de sus submódulos, así
# que esta línea es lo que convierte "spawn antes que cualquier proceso o
# conexión" (ADR 0012) en una garantía del lenguaje en vez de una
# convención de orden de statements dentro de main.py. Ver design.md D1.
from app.arranque import fijar_metodo_arranque

fijar_metodo_arranque()
