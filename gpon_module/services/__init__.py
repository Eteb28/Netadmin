"""Capa de servicios: la lógica de negocio del módulo.

Es la fachada del módulo. La API y la interfaz web consumen estos servicios;
nunca un driver ni un repositorio directamente. Cuando llegue la integración,
Pucará importará exactamente desde acá::

    from gpon_module.services import ServicioONU

Los servicios no conocen fabricantes: piden drivers a la fábrica, que los
resuelve por el registro.
"""

from .alta_onu import ResultadoAlta, ServicioAltaONU
from .baja_onu import ResultadoBaja, ServicioBajaONU
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
from .planes import ParPlanes, elegir_planes, segmento_de
from .propuesta_alta import PropuestaAlta, ServicioPropuestaAlta

__all__ = [
    "Captura",
    "Contenedor",
    "EquipoDeclarado",
    "Exploracion",
    "FabricaDrivers",
    "ParPlanes",
    "PotenciaONU",
    "PropuestaAlta",
    "ResultadoAlta",
    "ResultadoBaja",
    "ResultadoCarga",
    "ResultadoDescubrimiento",
    "ResultadoInventarioCLI",
    "ResultadoPendientes",
    "SalidaComando",
    "ServicioAltaONU",
    "ServicioBajaONU",
    "ServicioCaptura",
    "ServicioDescubrimiento",
    "ServicioExploracion",
    "ServicioInventarioArchivo",
    "ServicioInventarioCLI",
    "ServicioOLT",
    "ServicioONU",
    "ServicioPendientes",
    "ServicioPropuestaAlta",
    "crear_contenedor",
    "elegir_planes",
    "es_navegacion",
    "es_solo_lectura",
    "leer_equipos",
    "segmento_de",
]
