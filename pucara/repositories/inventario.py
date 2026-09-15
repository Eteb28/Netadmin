"""Lecturas para conciliar el inventario contra lo que la red ya reporta.

La idea de fondo: **la red es un inventario que ya se está tomando todos los
días y nadie está leyendo.** La OLT sabe el número de serie de cada ONU, los AP
saben la MAC y el modelo de cada equipo de cliente colgado de ellos, y el poller
sabe qué equipo de torre contestó y cuándo. Nada de eso hay que ir a escanear:
ya está en la base.

Este repositorio junta esas cuatro fuentes y el registro con el que hay que
cruzarlas. No decide nada — de eso se ocupa `services/inventario.py`.

Se leen los dos lados por separado y se cruzan en Python en vez de con un JOIN:
hace falta ver también los que NO tienen contraparte, que son justamente los
hallazgos que interesan, y de los dos lados a la vez.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from pucara.models.legado import (
    Cliente, Olt, OnuSenal, SnmpEstacion, StockItem, Torre, TorreEquipo,
)

#: Estados en los que a un cliente se le apaga el servicio a propósito. Que la
#: red no lo vea es lo esperado, no un hallazgo.
ESTADOS_SIN_SERVICIO = ("suspendido", "rescision", "pte_rescision", "baja")


@dataclass(frozen=True)
class AvistajeOnu:
    """Una ONU que la OLT está viendo ahora mismo."""
    olt_id: int | None
    olt_nombre: str | None
    pon: int | None
    onu: int | None
    serial: str | None
    nro_cliente: str | None
    online: bool
    ultimo_chequeo: str | None

    @property
    def ubicacion(self) -> str:
        olt = self.olt_nombre or f"OLT {self.olt_id}"
        return f"{olt} · GPON0/{self.pon} · ONU {self.onu}"


@dataclass(frozen=True)
class AvistajeEstacion:
    """Un equipo de cliente inalámbrico asociado a un AP."""
    mac: str
    cliente_id: int | None
    modelo: str | None
    firmware: str | None
    ap_equipo_id: int | None
    ap_nombre: str | None
    torre_nombre: str | None
    fecha: str | None

    @property
    def ubicacion(self) -> str:
        if self.torre_nombre and self.ap_nombre:
            return f"{self.torre_nombre} · {self.ap_nombre}"
        return self.torre_nombre or self.ap_nombre or "AP sin identificar"


@dataclass(frozen=True)
class ClienteRegistrado:
    """Lo que el padrón DICE que tiene el cliente."""
    id: int
    nombre: str
    nro_cliente: str | None
    estado: str | None
    tipo_servicio: str | None
    equipo_serie: str | None
    equipo_modelo: str | None
    mac_address: str | None

    @property
    def deberia_estar_online(self) -> bool:
        return (self.estado or "").lower() not in ESTADOS_SIN_SERVICIO


@dataclass(frozen=True)
class EquipoTorre:
    id: int
    torre_id: int | None
    torre_nombre: str | None
    tipo: str | None
    fabricante: str | None
    modelo: str | None
    serie: str | None
    mac: str | None
    estado: str | None
    ultimo_snmp: str | None
    snmp_estado: str | None

    @property
    def ubicacion(self) -> str:
        if self.torre_id is None:
            return "Sin torre asignada"
        return self.torre_nombre or f"Torre {self.torre_id}"


@dataclass(frozen=True)
class ItemStock:
    id: int
    serie: str | None
    mac: str | None
    modelo: str | None
    marca: str | None
    tipo: str | None
    estado: str | None
    cliente_id: int | None
    cliente_nombre: str | None
    ubicacion: str | None
    fecha_ingreso: str | None

    @property
    def figura_instalado(self) -> bool:
        return (self.estado or "").lower() == "instalado" or self.cliente_id is not None


class InventarioRepository:
    def __init__(self, sesion: Session) -> None:
        self._s = sesion

    # ── Lado "red": lo que existe de verdad ────────────────────────────

    def onus_de_la_red(self) -> list[AvistajeOnu]:
        """Cada ONU registrada en una OLT, con el serial que la OLT reporta."""
        filas = self._s.execute(
            select(
                OnuSenal.olt_id, Olt.nombre, OnuSenal.pon, OnuSenal.onu,
                OnuSenal.serial_onu, OnuSenal.nro_cliente,
                OnuSenal.online, OnuSenal.last_check,
            )
            .select_from(OnuSenal)
            .outerjoin(Olt, Olt.id == OnuSenal.olt_id)
            .order_by(OnuSenal.olt_id, OnuSenal.pon, OnuSenal.onu)
        ).all()
        return [
            AvistajeOnu(olt_id=f[0], olt_nombre=f[1], pon=f[2], onu=f[3],
                        serial=f[4], nro_cliente=f[5], online=bool(f[6]),
                        ultimo_chequeo=f[7])
            for f in filas
        ]

    def estaciones_de_la_red(self) -> list[AvistajeEstacion]:
        """Equipos de cliente que los AP están viendo asociados.

        `snmp_estaciones` es una foto del momento: el que se desconectó ya no
        está. Por eso lo que aparece acá existe con certeza.
        """
        filas = self._s.execute(
            select(
                SnmpEstacion.mac, SnmpEstacion.cliente_id, SnmpEstacion.modelo_sm,
                SnmpEstacion.firmware_sm, SnmpEstacion.equipo_id,
                SnmpEstacion.nombre_ap, Torre.nombre, SnmpEstacion.fecha,
            )
            .select_from(SnmpEstacion)
            .outerjoin(TorreEquipo, TorreEquipo.id == SnmpEstacion.equipo_id)
            .outerjoin(Torre, Torre.id == TorreEquipo.torre_id)
            .order_by(SnmpEstacion.equipo_id, SnmpEstacion.mac)
        ).all()
        return [
            AvistajeEstacion(mac=f[0], cliente_id=f[1], modelo=f[2], firmware=f[3],
                             ap_equipo_id=f[4], ap_nombre=f[5], torre_nombre=f[6],
                             fecha=f[7])
            for f in filas
        ]

    def equipos_de_torre(self) -> list[EquipoTorre]:
        """Equipos de torre cargados, con la última vez que contestaron SNMP."""
        filas = self._s.execute(
            select(
                TorreEquipo.id, TorreEquipo.torre_id, Torre.nombre, TorreEquipo.tipo,
                TorreEquipo.fabricante, TorreEquipo.modelo, TorreEquipo.nro_serie,
                TorreEquipo.mac, TorreEquipo.estado, TorreEquipo.ultimo_snmp,
                TorreEquipo.snmp_estado,
            )
            .select_from(TorreEquipo)
            .outerjoin(Torre, Torre.id == TorreEquipo.torre_id)
            .order_by(Torre.nombre, TorreEquipo.tipo)
        ).all()
        return [
            EquipoTorre(id=f[0], torre_id=f[1], torre_nombre=f[2], tipo=f[3],
                        fabricante=f[4], modelo=f[5], serie=f[6], mac=f[7],
                        estado=f[8], ultimo_snmp=f[9], snmp_estado=f[10])
            for f in filas
        ]

    # ── Lado "registro": lo que decimos que tenemos ────────────────────

    def padron(self, tipo_servicio: str | None = None) -> list[ClienteRegistrado]:
        """Clientes con el equipo que el padrón les asigna."""
        consulta = select(
            Cliente.id, Cliente.nombre, Cliente.nro_cliente, Cliente.estado,
            Cliente.tipo_servicio, Cliente.equipo_serie, Cliente.equipo_modelo,
            Cliente.mac_address,
        )
        if tipo_servicio:
            consulta = consulta.where(Cliente.tipo_servicio == tipo_servicio)
        return [
            ClienteRegistrado(id=f[0], nombre=f[1], nro_cliente=f[2], estado=f[3],
                              tipo_servicio=f[4], equipo_serie=f[5],
                              equipo_modelo=f[6], mac_address=f[7])
            for f in self._s.execute(consulta.order_by(Cliente.nombre)).all()
        ]

    def items_de_stock(self, incluir_bajas: bool = False) -> list[ItemStock]:
        """Equipos serializados del depósito. Las bajas quedan afuera salvo
        que se pidan: ya se decidió que no están y no son un hallazgo."""
        consulta = select(
            StockItem.id, StockItem.serie, StockItem.mac, StockItem.modelo,
            StockItem.marca, StockItem.tipo, StockItem.estado, StockItem.cliente_id,
            StockItem.cliente_nombre, StockItem.ubicacion, StockItem.fecha_ingreso,
        )
        if not incluir_bajas:
            consulta = consulta.where(StockItem.fecha_baja.is_(None))
        return [
            ItemStock(id=f[0], serie=f[1], mac=f[2], modelo=f[3], marca=f[4],
                      tipo=f[5], estado=f[6], cliente_id=f[7], cliente_nombre=f[8],
                      ubicacion=f[9], fecha_ingreso=f[10])
            for f in self._s.execute(consulta.order_by(StockItem.id)).all()
        ]
