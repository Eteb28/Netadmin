"""Catálogos de comandos de captura, por fabricante.

Cada fabricante publica desde su propio paquete la lista de comandos de sólo
lectura que interesa probar contra un equipo real. Acá sólo se juntan, para que
el servicio de captura no tenga que conocer a ninguno en particular.
"""

from __future__ import annotations

from ..core.enums import Fabricante
from .vsol.comandos import AYUDAS_VSOL, CATALOGO_VSOL, ComandoCandidato

#: Comandos genéricos, para un fabricante todavía sin catálogo propio.
CATALOGO_GENERICO: tuple[ComandoCandidato, ...] = (
    ComandoCandidato("show version", "Modelo y versión de firmware", "identidad"),
    ComandoCandidato("show running-config", "Configuración completa", "configuracion"),
)

AYUDAS_GENERICAS: tuple[str, ...] = ("", "show ")

_CATALOGOS: dict[Fabricante, tuple[ComandoCandidato, ...]] = {
    Fabricante.VSOL: CATALOGO_VSOL,
}

_AYUDAS: dict[Fabricante, tuple[str, ...]] = {
    Fabricante.VSOL: AYUDAS_VSOL,
}


def catalogo_de(fabricante: Fabricante) -> tuple[ComandoCandidato, ...]:
    """Comandos candidatos para ese fabricante."""
    return _CATALOGOS.get(fabricante, CATALOGO_GENERICO)


def ayudas_de(fabricante: Fabricante) -> tuple[str, ...]:
    """Prefijos con los que pedir la ayuda en línea de ese fabricante."""
    return _AYUDAS.get(fabricante, AYUDAS_GENERICAS)


__all__ = ["ComandoCandidato", "ayudas_de", "catalogo_de"]
