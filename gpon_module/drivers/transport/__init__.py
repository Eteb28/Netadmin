"""Transportes: la mecánica de hablar con un equipo.

``base`` concentra lo que no depende del fabricante ni del protocolo. Las
implementaciones concretas de Telnet y SSH llegan en la Fase 2, junto con el
driver VSOL de lectura.
"""

from .base import (
    MARCADORES_ERROR,
    TransporteCLIBase,
    detectar_rechazo,
    reintentar,
    sesion_exclusiva,
)

__all__ = [
    "MARCADORES_ERROR",
    "TransporteCLIBase",
    "detectar_rechazo",
    "reintentar",
    "sesion_exclusiva",
]
