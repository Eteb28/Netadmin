"""Repositorios: la única capa que sabe que existe una base de datos.

Implementan los contratos declarados en ``core.interfaces``. Los servicios
dependen de esos contratos, no de estas clases: cambiar de motor, o sustituir
por dobles en un test, no obliga a tocar la lógica de negocio.
"""

from .base import RepositorioBase
from .olt import RepositorioOLTSQL
from .onu import RepositorioONUSQL, RepositorioPuertoPONSQL
from .perfiles import RepositorioPerfilesSQL
from .telemetria import (
    RepositorioAlarmaSQL,
    RepositorioEventoSQL,
    RepositorioMetricaSQL,
    RepositorioOperacionSQL,
    RepositorioSincronizacionSQL,
)

__all__ = [
    "RepositorioAlarmaSQL",
    "RepositorioBase",
    "RepositorioEventoSQL",
    "RepositorioMetricaSQL",
    "RepositorioOLTSQL",
    "RepositorioONUSQL",
    "RepositorioOperacionSQL",
    "RepositorioPerfilesSQL",
    "RepositorioPuertoPONSQL",
    "RepositorioSincronizacionSQL",
]
