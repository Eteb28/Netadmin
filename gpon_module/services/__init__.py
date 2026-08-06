"""Capa de servicios: la lógica de negocio del módulo.

Es la fachada del módulo. La API y la interfaz web consumen estos servicios;
nunca un driver ni un repositorio directamente. Cuando llegue la integración,
Pucará importará exactamente desde acá::

    from gpon_module.services import ServicioONU

Los servicios no conocen fabricantes: piden drivers a la fábrica, que los
resuelve por el registro.
"""

from .captura import Captura, SalidaComando, ServicioCaptura, es_solo_lectura
from .contenedor import Contenedor, crear_contenedor
from .descubrimiento import ResultadoDescubrimiento, ServicioDescubrimiento
from .fabrica import FabricaDrivers
from .inventario_archivo import (
    EquipoDeclarado,
    ResultadoCarga,
    ServicioInventarioArchivo,
    leer_equipos,
)
from .olt import ServicioOLT
from .onu import PotenciaONU, ServicioONU

__all__ = [
    "Captura",
    "Contenedor",
    "EquipoDeclarado",
    "FabricaDrivers",
    "PotenciaONU",
    "ResultadoCarga",
    "ResultadoDescubrimiento",
    "SalidaComando",
    "ServicioCaptura",
    "ServicioDescubrimiento",
    "ServicioInventarioArchivo",
    "ServicioOLT",
    "ServicioONU",
    "crear_contenedor",
    "es_solo_lectura",
    "leer_equipos",
]
