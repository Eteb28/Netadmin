"""API interna del módulo.

Es la **única** puerta de entrada de la interfaz gráfica: la web no importa
servicios ni drivers, hace peticiones HTTP contra estas rutas. Ese límite es lo
que permite que mañana la consuma Pucará, una app móvil o un script sin cambiar
nada de acá.
"""

from .rutas import api

__all__ = ["api"]
