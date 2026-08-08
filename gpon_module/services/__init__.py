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
from .exploracion import Exploracion, ServicioExploracion, es_navegacion
from .fabrica import FabricaDrivers
from .inventario_archivo import (
    EquipoDeclarado,
    ResultadoCarga,
    ServicioInventarioArchivo,
    leer_equipos,
)
from .inventario_cli import ResultadoInventarioCLI, ServicioInventarioCLI
from .olt import ServicioOLT
from .onu import PotenciaONU, ServicioONU
from .pendientes import ResultadoPendientes, ServicioPendientes

__all__ = [
    "Captura",
    "Contenedor",
    "EquipoDeclarado",
    "Exploracion",
    "FabricaDrivers",
    "PotenciaONU",
    "ResultadoCarga",
    "ResultadoDescubrimiento",
    "ResultadoInventarioCLI",
    "ResultadoPendientes",
    "SalidaComando",
    "ServicioCaptura",
    "ServicioDescubrimiento",
    "ServicioExploracion",
    "ServicioInventarioArchivo",
    "ServicioInventarioCLI",
    "ServicioOLT",
    "ServicioONU",
    "ServicioPendientes",
    "crear_contenedor",
    "es_navegacion",
    "es_solo_lectura",
    "leer_equipos",
]
