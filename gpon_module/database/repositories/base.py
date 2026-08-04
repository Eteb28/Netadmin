"""Base común de los repositorios.

Un repositorio traduce entre filas de base de datos y modelos del dominio, y
nada más: no decide, no llama a drivers, no arma alarmas. Toda regla de negocio
vive en la capa de servicios.
"""

from __future__ import annotations

from typing import Any

from ..conexion import Conexion


class RepositorioBase:
    """Sostiene la conexión y ofrece utilidades de conversión."""

    def __init__(self, conexion: Conexion) -> None:
        self._db = conexion

    # SQLite guarda los booleanos como enteros; PostgreSQL como BOOLEAN. Estas
    # dos funciones son el único lugar donde esa diferencia importa.

    @staticmethod
    def _bool(valor: Any) -> bool:
        return bool(valor)

    @staticmethod
    def _int(valor: Any) -> int:
        return int(bool(valor))
