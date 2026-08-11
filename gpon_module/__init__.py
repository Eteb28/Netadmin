"""Módulo GPON — administración de OLT y ONU multifabricante.

Proyecto independiente, pensado para integrarse más adelante como módulo
interno de Pucará. No importa nada de Pucará y no comparte su base de datos:
la integración futura será por servicios.

Uso típico::

    from gpon_module import crear_contenedor
    from gpon_module.core import Fabricante, CredencialesOLT

    with crear_contenedor() as sistema:
        olt = sistema.servicio_olt.registrar(
            nombre="OLT Centro",
            host="192.168.1.10",
            fabricante=Fabricante.VSOL,
            credenciales=CredencialesOLT(usuario="admin", password="..."),
        )
        resultado = sistema.servicio_descubrimiento.descubrir(olt.id)

Estado: Fase 1 (núcleo, base de datos y driver simulado). Ver docs/.
"""

from . import drivers  # noqa: F401  (registra los drivers disponibles)
from .config import Configuracion
from .services import Contenedor, crear_contenedor

__version__ = "0.1.0"

__all__ = ["Configuracion", "Contenedor", "__version__", "crear_contenedor"]
