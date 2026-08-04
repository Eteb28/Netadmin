"""Repositorio de perfiles, VLAN y service-ports.

Se guardan como espejo de lo que tiene la OLT: el equipo es la verdad, la base
es la copia consultable. Por eso ``reemplazar_de_olt`` sincroniza el conjunto
completo en una transacción, en vez de ir mezclando altas sueltas.
"""

from __future__ import annotations

from typing import Any

from ...core.models import (
    VLAN,
    PerfilDBA,
    Perfiles,
    PerfilLinea,
    PerfilServicio,
    RefONU,
    ServicePort,
)
from ..conexion import Conexion


class RepositorioPerfilesSQL:
    def __init__(self, conexion: Conexion) -> None:
        self._db = conexion

    # --- lectura ---

    def obtener_de_olt(self, olt_id: int) -> Perfiles:
        return Perfiles(
            dba=tuple(self._dba(olt_id)),
            linea=tuple(self._linea(olt_id)),
            servicio=tuple(self._servicio(olt_id)),
            vlans=tuple(self._vlans(olt_id)),
            service_ports=tuple(self._service_ports(olt_id)),
        )

    def _dba(self, olt_id: int) -> list[PerfilDBA]:
        filas = self._db.consultar_todos(
            "SELECT * FROM perfiles_dba WHERE olt_id = ? ORDER BY nombre", (olt_id,)
        )
        return [
            PerfilDBA(
                id=f["id"],
                olt_id=f["olt_id"],
                nombre=f["nombre"],
                identificador_equipo=f["identificador_equipo"],
                tipo=f["tipo"],
                ancho_banda_fijo_kbps=f["ancho_banda_fijo_kbps"],
                ancho_banda_asegurado_kbps=f["ancho_banda_asegurado_kbps"],
                ancho_banda_maximo_kbps=f["ancho_banda_maximo_kbps"],
            )
            for f in filas
        ]

    def _linea(self, olt_id: int) -> list[PerfilLinea]:
        filas = self._db.consultar_todos(
            "SELECT * FROM perfiles_linea WHERE olt_id = ? ORDER BY nombre", (olt_id,)
        )
        return [
            PerfilLinea(
                id=f["id"],
                olt_id=f["olt_id"],
                nombre=f["nombre"],
                identificador_equipo=f["identificador_equipo"],
                perfil_dba=f["perfil_dba"],
                cantidad_tcont=f["cantidad_tcont"],
                cantidad_gemport=f["cantidad_gemport"],
            )
            for f in filas
        ]

    def _servicio(self, olt_id: int) -> list[PerfilServicio]:
        filas = self._db.consultar_todos(
            "SELECT * FROM perfiles_servicio WHERE olt_id = ? ORDER BY nombre", (olt_id,)
        )
        return [
            PerfilServicio(
                id=f["id"],
                olt_id=f["olt_id"],
                nombre=f["nombre"],
                identificador_equipo=f["identificador_equipo"],
                vlan=f["vlan"],
            )
            for f in filas
        ]

    def _vlans(self, olt_id: int) -> list[VLAN]:
        filas = self._db.consultar_todos(
            "SELECT * FROM vlans WHERE olt_id = ? ORDER BY vlan_id", (olt_id,)
        )
        return [
            VLAN(
                id=f["id"],
                olt_id=f["olt_id"],
                vlan_id=f["vlan_id"],
                nombre=f["nombre"],
                descripcion=f["descripcion"],
            )
            for f in filas
        ]

    def _service_ports(self, olt_id: int) -> list[ServicePort]:
        filas = self._db.consultar_todos(
            "SELECT * FROM service_ports WHERE olt_id = ? ORDER BY indice", (olt_id,)
        )
        return [
            ServicePort(
                id=f["id"],
                olt_id=f["olt_id"],
                indice=f["indice"],
                ref_onu=(
                    RefONU(pon=f["pon"], onu_id=f["onu_id"])
                    if f["pon"] is not None and f["onu_id"] is not None
                    else None
                ),
                gemport=f["gemport"],
                vlan_usuario=f["vlan_usuario"],
                vlan_servicio=f["vlan_servicio"],
                perfil_trafico=f["perfil_trafico"],
            )
            for f in filas
        ]

    # --- escritura ---

    def reemplazar_de_olt(self, olt_id: int, perfiles: Perfiles) -> Perfiles:
        """Deja la base igual a lo que reporta la OLT.

        Si un perfil se borró en el equipo, tiene que desaparecer de la base:
        un perfil fantasma en la interfaz lleva a elegirlo al autorizar una ONU
        y a que el comando falle contra el equipo.
        """
        with self._transaccion():
            for tabla in (
                "perfiles_dba",
                "perfiles_linea",
                "perfiles_servicio",
                "vlans",
                "service_ports",
            ):
                self._db.ejecutar(f"DELETE FROM {tabla} WHERE olt_id = ?", (olt_id,))

            for dba in perfiles.dba:
                self._db.ejecutar(
                    """
                    INSERT INTO perfiles_dba (
                        olt_id, nombre, identificador_equipo, tipo,
                        ancho_banda_fijo_kbps, ancho_banda_asegurado_kbps,
                        ancho_banda_maximo_kbps
                    ) VALUES (?,?,?,?,?,?,?)
                    """,
                    (
                        olt_id,
                        dba.nombre,
                        dba.identificador_equipo,
                        dba.tipo,
                        dba.ancho_banda_fijo_kbps,
                        dba.ancho_banda_asegurado_kbps,
                        dba.ancho_banda_maximo_kbps,
                    ),
                )
            for linea in perfiles.linea:
                self._db.ejecutar(
                    """
                    INSERT INTO perfiles_linea (
                        olt_id, nombre, identificador_equipo, perfil_dba,
                        cantidad_tcont, cantidad_gemport
                    ) VALUES (?,?,?,?,?,?)
                    """,
                    (
                        olt_id,
                        linea.nombre,
                        linea.identificador_equipo,
                        linea.perfil_dba,
                        linea.cantidad_tcont,
                        linea.cantidad_gemport,
                    ),
                )
            for servicio in perfiles.servicio:
                self._db.ejecutar(
                    """
                    INSERT INTO perfiles_servicio (
                        olt_id, nombre, identificador_equipo, vlan
                    ) VALUES (?,?,?,?)
                    """,
                    (
                        olt_id,
                        servicio.nombre,
                        servicio.identificador_equipo,
                        servicio.vlan,
                    ),
                )
            for vlan in perfiles.vlans:
                self._db.ejecutar(
                    "INSERT INTO vlans (olt_id, vlan_id, nombre, descripcion) VALUES (?,?,?,?)",
                    (olt_id, vlan.vlan_id, vlan.nombre, vlan.descripcion),
                )
            for puerto in perfiles.service_ports:
                self._db.ejecutar(
                    """
                    INSERT INTO service_ports (
                        olt_id, indice, pon, onu_id, gemport,
                        vlan_usuario, vlan_servicio, perfil_trafico
                    ) VALUES (?,?,?,?,?,?,?,?)
                    """,
                    (
                        olt_id,
                        puerto.indice,
                        puerto.ref_onu.pon if puerto.ref_onu else None,
                        puerto.ref_onu.onu_id if puerto.ref_onu else None,
                        puerto.gemport,
                        puerto.vlan_usuario,
                        puerto.vlan_servicio,
                        puerto.perfil_trafico,
                    ),
                )
        return self.obtener_de_olt(olt_id)

    def _transaccion(self) -> Any:
        return self._db.transaccion()


__all__ = ["RepositorioPerfilesSQL"]
