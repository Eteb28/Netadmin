"""Repositorio de OLT, incluidas sus credenciales cifradas."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ...core.enums import EstadoOLT, Fabricante
from ...core.errors import NoEncontrado
from ...core.interfaces import Cifrador
from ...core.models import OLT, CredencialesOLT
from ..conexion import Conexion, a_fecha, a_texto

_CAMPOS = """
    id, nombre, host, fabricante, modelo, firmware, numero_serie, mac,
    descripcion, estado, activa, cantidad_pon, cantidad_onus, uptime_segundos,
    ultima_sincronizacion, creada_en, actualizada_en
"""


class RepositorioOLTSQL:
    """Persistencia de OLT.

    Las credenciales entran y salen en claro por la interfaz, pero se guardan
    cifradas: quien mire la tabla no encuentra la contraseña de administrador
    de todas las OLT del ISP (mitiga R8).
    """

    def __init__(self, conexion: Conexion, cifrador: Cifrador) -> None:
        self._db = conexion
        self._cifrador = cifrador

    # --- conversión ---

    def _a_modelo(self, fila: dict[str, Any]) -> OLT:
        return OLT(
            id=fila["id"],
            nombre=fila["nombre"],
            host=fila["host"],
            fabricante=Fabricante(fila["fabricante"]),
            modelo=fila["modelo"],
            firmware=fila["firmware"],
            numero_serie=fila["numero_serie"],
            mac=fila["mac"],
            descripcion=fila["descripcion"],
            estado=EstadoOLT(fila["estado"]),
            activa=bool(fila["activa"]),
            cantidad_pon=fila["cantidad_pon"],
            cantidad_onus=fila["cantidad_onus"],
            uptime_segundos=fila["uptime_segundos"],
            ultima_sincronizacion=a_fecha(fila["ultima_sincronizacion"]),
            creada_en=a_fecha(fila["creada_en"]),
            actualizada_en=a_fecha(fila["actualizada_en"]),
        )

    # --- escritura ---

    def crear(self, olt: OLT, credenciales: CredencialesOLT) -> OLT:
        ahora = a_texto(datetime.now(UTC))
        cifrar = self._cifrador.cifrar
        nuevo_id = self._db.ejecutar(
            """
            INSERT INTO olts (
                nombre, host, fabricante, modelo, firmware, numero_serie, mac,
                descripcion, estado, activa, cantidad_pon, cantidad_onus,
                uptime_segundos, ultima_sincronizacion, creada_en, actualizada_en,
                usuario_cifrado, password_cifrado, password_enable_cifrado,
                comunidad_lectura_cifrada, comunidad_escritura_cifrada,
                puerto_snmp, puerto_telnet, puerto_ssh
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                olt.nombre,
                olt.host,
                str(olt.fabricante),
                olt.modelo,
                olt.firmware,
                olt.numero_serie,
                olt.mac,
                olt.descripcion,
                str(olt.estado),
                int(olt.activa),
                olt.cantidad_pon,
                olt.cantidad_onus,
                olt.uptime_segundos,
                a_texto(olt.ultima_sincronizacion),
                ahora,
                ahora,
                cifrar(credenciales.usuario),
                cifrar(credenciales.password),
                cifrar(credenciales.password_enable),
                cifrar(credenciales.comunidad_snmp_lectura),
                cifrar(credenciales.comunidad_snmp_escritura),
                credenciales.puerto_snmp,
                credenciales.puerto_telnet,
                credenciales.puerto_ssh,
            ),
        )
        return self.obtener(nuevo_id)

    def actualizar(self, olt: OLT) -> OLT:
        if olt.id is None:
            raise NoEncontrado("No se puede actualizar una OLT sin id")
        self._db.ejecutar(
            """
            UPDATE olts SET
                nombre = ?, host = ?, fabricante = ?, modelo = ?, firmware = ?,
                numero_serie = ?, mac = ?, descripcion = ?, estado = ?, activa = ?,
                cantidad_pon = ?, cantidad_onus = ?, uptime_segundos = ?,
                ultima_sincronizacion = ?, actualizada_en = ?
            WHERE id = ?
            """,
            (
                olt.nombre,
                olt.host,
                str(olt.fabricante),
                olt.modelo,
                olt.firmware,
                olt.numero_serie,
                olt.mac,
                olt.descripcion,
                str(olt.estado),
                int(olt.activa),
                olt.cantidad_pon,
                olt.cantidad_onus,
                olt.uptime_segundos,
                a_texto(olt.ultima_sincronizacion),
                a_texto(datetime.now(UTC)),
                olt.id,
            ),
        )
        return self.obtener(olt.id)

    def eliminar(self, olt_id: int) -> None:
        self._db.ejecutar("DELETE FROM olts WHERE id = ?", (olt_id,))

    # --- lectura ---

    def obtener(self, olt_id: int) -> OLT:
        fila = self._db.consultar_uno(f"SELECT {_CAMPOS} FROM olts WHERE id = ?", (olt_id,))
        if fila is None:
            raise NoEncontrado(f"No existe la OLT con id {olt_id}")
        return self._a_modelo(fila)

    def obtener_por_host(self, host: str) -> OLT | None:
        fila = self._db.consultar_uno(f"SELECT {_CAMPOS} FROM olts WHERE host = ?", (host,))
        return self._a_modelo(fila) if fila else None

    def listar(self, solo_activas: bool = False) -> list[OLT]:
        sql = f"SELECT {_CAMPOS} FROM olts"
        if solo_activas:
            sql += " WHERE activa = 1"
        sql += " ORDER BY nombre"
        return [self._a_modelo(fila) for fila in self._db.consultar_todos(sql)]

    # --- credenciales ---

    def obtener_credenciales(self, olt_id: int) -> CredencialesOLT:
        fila = self._db.consultar_uno(
            """
            SELECT usuario_cifrado, password_cifrado, password_enable_cifrado,
                   comunidad_lectura_cifrada, comunidad_escritura_cifrada,
                   puerto_snmp, puerto_telnet, puerto_ssh
            FROM olts WHERE id = ?
            """,
            (olt_id,),
        )
        if fila is None:
            raise NoEncontrado(f"No existe la OLT con id {olt_id}")
        descifrar = self._cifrador.descifrar
        return CredencialesOLT(
            usuario=descifrar(fila["usuario_cifrado"]),
            password=descifrar(fila["password_cifrado"]),
            password_enable=descifrar(fila["password_enable_cifrado"]),
            comunidad_snmp_lectura=descifrar(fila["comunidad_lectura_cifrada"]),
            comunidad_snmp_escritura=descifrar(fila["comunidad_escritura_cifrada"]),
            puerto_snmp=fila["puerto_snmp"],
            puerto_telnet=fila["puerto_telnet"],
            puerto_ssh=fila["puerto_ssh"],
        )

    def guardar_credenciales(self, olt_id: int, credenciales: CredencialesOLT) -> None:
        cifrar = self._cifrador.cifrar
        self._db.ejecutar(
            """
            UPDATE olts SET
                usuario_cifrado = ?, password_cifrado = ?, password_enable_cifrado = ?,
                comunidad_lectura_cifrada = ?, comunidad_escritura_cifrada = ?,
                puerto_snmp = ?, puerto_telnet = ?, puerto_ssh = ?, actualizada_en = ?
            WHERE id = ?
            """,
            (
                cifrar(credenciales.usuario),
                cifrar(credenciales.password),
                cifrar(credenciales.password_enable),
                cifrar(credenciales.comunidad_snmp_lectura),
                cifrar(credenciales.comunidad_snmp_escritura),
                credenciales.puerto_snmp,
                credenciales.puerto_telnet,
                credenciales.puerto_ssh,
                a_texto(datetime.now(UTC)),
                olt_id,
            ),
        )


__all__ = ["RepositorioOLTSQL"]
