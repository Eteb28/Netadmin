"""Persistencia del módulo GPON.

Esquema propio, sin reutilizar ninguna tabla de Pucará (requisito explícito
del diseño). La integración futura será por servicios, no por base compartida.
"""

from .conexion import (
    RUTA_ESQUEMA_POSTGRES,
    RUTA_ESQUEMA_SQLITE,
    VERSION_ESQUEMA,
    Conexion,
    ConexionSQLite,
    a_fecha,
    a_texto,
    crear_conexion,
)

__all__ = [
    "RUTA_ESQUEMA_POSTGRES",
    "RUTA_ESQUEMA_SQLITE",
    "VERSION_ESQUEMA",
    "Conexion",
    "ConexionSQLite",
    "a_fecha",
    "a_texto",
    "crear_conexion",
]
