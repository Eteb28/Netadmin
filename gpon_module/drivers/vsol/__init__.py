"""Driver VSOL V1600G1 / V1600G1-B.

Estado: **sólo lectura** (Fase 2). La escritura llega en la Fase 5 y va por
CLI, porque en estos equipos SNMP no expone ninguna operación de
aprovisionamiento.
"""

from .driver import CAPACIDADES_VSOL, DriverVSOL, MuestraSondeo

__all__ = ["CAPACIDADES_VSOL", "DriverVSOL", "MuestraSondeo"]
