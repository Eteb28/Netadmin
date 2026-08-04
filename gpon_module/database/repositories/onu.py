"""Repositorio de ONU y de puertos PON."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ...core.enums import EstadoONU, ModoServicio, MotivoCaida
from ...core.errors import NoEncontrado
from ...core.models import ONU, PuertoPON, RefONU
from ..conexion import Conexion, a_fecha, a_texto

_CAMPOS = """
    id, olt_id, pon, onu_id, numero_serie, nombre, descripcion, modelo,
    fabricante_onu, firmware, estado, motivo_caida, modo_servicio, autorizada,
    distancia_metros, perfil_linea, perfil_servicio, vlan, ultima_subida,
    ultima_bajada, tiempo_en_estado, primera_vez_vista, ultima_vez_vista
"""


def _a_modelo(fila: dict[str, Any]) -> ONU:
    return ONU(
        id=fila["id"],
        olt_id=fila["olt_id"],
        ref=RefONU(pon=fila["pon"], onu_id=fila["onu_id"]),
        numero_serie=fila["numero_serie"],
        nombre=fila["nombre"],
        descripcion=fila["descripcion"],
        modelo=fila["modelo"],
        fabricante_onu=fila["fabricante_onu"],
        firmware=fila["firmware"],
        estado=EstadoONU(fila["estado"]),
        motivo_caida=MotivoCaida(fila["motivo_caida"]),
        modo_servicio=ModoServicio(fila["modo_servicio"]),
        autorizada=bool(fila["autorizada"]),
        distancia_metros=fila["distancia_metros"],
        perfil_linea=fila["perfil_linea"],
        perfil_servicio=fila["perfil_servicio"],
        vlan=fila["vlan"],
        ultima_subida=a_fecha(fila["ultima_subida"]),
        ultima_bajada=a_fecha(fila["ultima_bajada"]),
        tiempo_en_estado=fila["tiempo_en_estado"],
        primera_vez_vista=a_fecha(fila["primera_vez_vista"]),
        ultima_vez_vista=a_fecha(fila["ultima_vez_vista"]),
    )


class RepositorioONUSQL:
    """Persistencia del inventario de ONU.

    La identidad de una ONU es ``(olt_id, pon, onu_id)``, no su serial: el
    serial no siempre está disponible (en VSOL no viene por SNMP), y una ONU
    puede reemplazarse manteniendo su posición.
    """

    def __init__(self, conexion: Conexion) -> None:
        self._db = conexion

    def guardar(self, onu: ONU) -> ONU:
        """Alta o actualización, según exista o no la posición.

        ``primera_vez_vista`` se fija una sola vez y nunca se pisa: es el dato
        que permite saber desde cuándo está esa ONU en la red.
        """
        if onu.olt_id is None:
            raise NoEncontrado("La ONU debe pertenecer a una OLT")
        existente = self.obtener_por_ref(onu.olt_id, onu.ref)
        ahora = a_texto(datetime.now(UTC))
        vista = a_texto(onu.ultima_vez_vista) or ahora

        if existente is None:
            nuevo_id = self._db.ejecutar(
                """
                INSERT INTO onus (
                    olt_id, pon, onu_id, numero_serie, nombre, descripcion, modelo,
                    fabricante_onu, firmware, estado, motivo_caida, modo_servicio,
                    autorizada, distancia_metros, perfil_linea, perfil_servicio, vlan,
                    ultima_subida, ultima_bajada, tiempo_en_estado,
                    primera_vez_vista, ultima_vez_vista
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    onu.olt_id,
                    onu.ref.pon,
                    onu.ref.onu_id,
                    onu.numero_serie,
                    onu.nombre,
                    onu.descripcion,
                    onu.modelo,
                    onu.fabricante_onu,
                    onu.firmware,
                    str(onu.estado),
                    str(onu.motivo_caida),
                    str(onu.modo_servicio),
                    int(onu.autorizada),
                    onu.distancia_metros,
                    onu.perfil_linea,
                    onu.perfil_servicio,
                    onu.vlan,
                    a_texto(onu.ultima_subida),
                    a_texto(onu.ultima_bajada),
                    onu.tiempo_en_estado,
                    a_texto(onu.primera_vez_vista) or ahora,
                    vista,
                ),
            )
            return self.obtener(nuevo_id)

        self._db.ejecutar(
            """
            UPDATE onus SET
                numero_serie = ?, nombre = ?, descripcion = ?, modelo = ?,
                fabricante_onu = ?, firmware = ?, estado = ?, motivo_caida = ?,
                modo_servicio = ?, autorizada = ?, distancia_metros = ?,
                perfil_linea = ?, perfil_servicio = ?, vlan = ?, ultima_subida = ?,
                ultima_bajada = ?, tiempo_en_estado = ?, ultima_vez_vista = ?
            WHERE id = ?
            """,
            (
                onu.numero_serie or existente.numero_serie,
                onu.nombre or existente.nombre,
                onu.descripcion or existente.descripcion,
                onu.modelo or existente.modelo,
                onu.fabricante_onu or existente.fabricante_onu,
                onu.firmware or existente.firmware,
                str(onu.estado),
                str(onu.motivo_caida),
                str(onu.modo_servicio),
                int(onu.autorizada),
                onu.distancia_metros,
                onu.perfil_linea or existente.perfil_linea,
                onu.perfil_servicio or existente.perfil_servicio,
                onu.vlan if onu.vlan is not None else existente.vlan,
                a_texto(onu.ultima_subida),
                a_texto(onu.ultima_bajada),
                onu.tiempo_en_estado,
                vista,
                existente.id,
            ),
        )
        return self.obtener(existente.id)  # type: ignore[arg-type]

    def guardar_muchas(self, onus: list[ONU]) -> list[ONU]:
        return [self.guardar(onu) for onu in onus]

    def obtener(self, onu_id: int) -> ONU:
        fila = self._db.consultar_uno(f"SELECT {_CAMPOS} FROM onus WHERE id = ?", (onu_id,))
        if fila is None:
            raise NoEncontrado(f"No existe la ONU con id {onu_id}")
        return _a_modelo(fila)

    def obtener_por_ref(self, olt_id: int, ref: RefONU) -> ONU | None:
        fila = self._db.consultar_uno(
            f"SELECT {_CAMPOS} FROM onus WHERE olt_id = ? AND pon = ? AND onu_id = ?",
            (olt_id, ref.pon, ref.onu_id),
        )
        return _a_modelo(fila) if fila else None

    def obtener_por_serie(self, numero_serie: str) -> ONU | None:
        if not numero_serie:
            return None
        fila = self._db.consultar_uno(
            f"SELECT {_CAMPOS} FROM onus WHERE numero_serie = ? ORDER BY id DESC",
            (numero_serie,),
        )
        return _a_modelo(fila) if fila else None

    def listar_de_olt(self, olt_id: int, pon: int | None = None) -> list[ONU]:
        if pon is None:
            filas = self._db.consultar_todos(
                f"SELECT {_CAMPOS} FROM onus WHERE olt_id = ? ORDER BY pon, onu_id", (olt_id,)
            )
        else:
            filas = self._db.consultar_todos(
                f"SELECT {_CAMPOS} FROM onus WHERE olt_id = ? AND pon = ? ORDER BY onu_id",
                (olt_id, pon),
            )
        return [_a_modelo(fila) for fila in filas]

    def listar_por_estado(self, olt_id: int, estado: EstadoONU) -> list[ONU]:
        filas = self._db.consultar_todos(
            f"SELECT {_CAMPOS} FROM onus WHERE olt_id = ? AND estado = ? ORDER BY pon, onu_id",
            (olt_id, str(estado)),
        )
        return [_a_modelo(fila) for fila in filas]

    def eliminar(self, onu_id: int) -> None:
        self._db.ejecutar("DELETE FROM onus WHERE id = ?", (onu_id,))

    def contar_de_olt(self, olt_id: int) -> int:
        fila = self._db.consultar_uno("SELECT COUNT(*) AS c FROM onus WHERE olt_id = ?", (olt_id,))
        return int(fila["c"]) if fila else 0

    def contar_por_estado(self, olt_id: int) -> dict[str, int]:
        filas = self._db.consultar_todos(
            "SELECT estado, COUNT(*) AS c FROM onus WHERE olt_id = ? GROUP BY estado",
            (olt_id,),
        )
        return {fila["estado"]: int(fila["c"]) for fila in filas}


class RepositorioPuertoPONSQL:
    """Persistencia de los puertos PON."""

    def __init__(self, conexion: Conexion) -> None:
        self._db = conexion

    def _a_modelo(self, fila: dict[str, Any]) -> PuertoPON:
        return PuertoPON(
            id=fila["id"],
            olt_id=fila["olt_id"],
            indice=fila["indice"],
            nombre=fila["nombre"],
            descripcion=fila["descripcion"],
            habilitado=bool(fila["habilitado"]),
            operativo=bool(fila["operativo"]),
            cantidad_onus=fila["cantidad_onus"],
            cantidad_onus_en_linea=fila["cantidad_onus_en_linea"],
            potencia_tx_dbm=fila["potencia_tx_dbm"],
            temperatura_celsius=fila["temperatura_celsius"],
            voltaje_voltios=fila["voltaje_voltios"],
            corriente_ma=fila["corriente_ma"],
            leido_en=a_fecha(fila["leido_en"]),
        )

    def guardar(self, puerto: PuertoPON) -> PuertoPON:
        existente = self._db.consultar_uno(
            "SELECT id FROM puertos_pon WHERE olt_id = ? AND indice = ?",
            (puerto.olt_id, puerto.indice),
        )
        datos = (
            puerto.nombre,
            puerto.descripcion,
            int(puerto.habilitado),
            int(puerto.operativo),
            puerto.cantidad_onus,
            puerto.cantidad_onus_en_linea,
            puerto.potencia_tx_dbm,
            puerto.temperatura_celsius,
            puerto.voltaje_voltios,
            puerto.corriente_ma,
            a_texto(puerto.leido_en),
        )
        if existente is None:
            nuevo_id = self._db.ejecutar(
                """
                INSERT INTO puertos_pon (
                    olt_id, indice, nombre, descripcion, habilitado, operativo,
                    cantidad_onus, cantidad_onus_en_linea, potencia_tx_dbm,
                    temperatura_celsius, voltaje_voltios, corriente_ma, leido_en
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (puerto.olt_id, puerto.indice, *datos),
            )
            return self.obtener(nuevo_id)
        self._db.ejecutar(
            """
            UPDATE puertos_pon SET
                nombre = ?, descripcion = ?, habilitado = ?, operativo = ?,
                cantidad_onus = ?, cantidad_onus_en_linea = ?, potencia_tx_dbm = ?,
                temperatura_celsius = ?, voltaje_voltios = ?, corriente_ma = ?,
                leido_en = ?
            WHERE id = ?
            """,
            (*datos, existente["id"]),
        )
        return self.obtener(existente["id"])

    def obtener(self, puerto_id: int) -> PuertoPON:
        fila = self._db.consultar_uno("SELECT * FROM puertos_pon WHERE id = ?", (puerto_id,))
        if fila is None:
            raise NoEncontrado(f"No existe el puerto PON con id {puerto_id}")
        return self._a_modelo(fila)

    def reemplazar_de_olt(self, olt_id: int, puertos: list[PuertoPON]) -> list[PuertoPON]:
        """Actualiza los puertos descubiertos, conservando los ids existentes."""
        return [self.guardar(puerto) for puerto in puertos]

    def listar_de_olt(self, olt_id: int) -> list[PuertoPON]:
        filas = self._db.consultar_todos(
            "SELECT * FROM puertos_pon WHERE olt_id = ? ORDER BY indice", (olt_id,)
        )
        return [self._a_modelo(fila) for fila in filas]

    def obtener_por_indice(self, olt_id: int, indice: int) -> PuertoPON | None:
        fila = self._db.consultar_uno(
            "SELECT * FROM puertos_pon WHERE olt_id = ? AND indice = ?", (olt_id, indice)
        )
        return self._a_modelo(fila) if fila else None


__all__ = ["RepositorioONUSQL", "RepositorioPuertoPONSQL"]
