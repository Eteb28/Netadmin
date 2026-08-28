"""Lectura de señal óptica: estado actual e histórico.

Las tablas son heredadas (las crea `app.py`) pero ya están descritas en
`pucara.models.legado`, así que las consultas se arman con SQLAlchemy y no con
texto: sobreviven al cambio de motor sin reescribirse.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from pucara.models.legado import Cliente, Olt, OnuSenal, OnuSenalHist


@dataclass(frozen=True)
class LecturaActual:
    olt_id: int
    olt_nombre: str | None
    pon: int
    onu: int
    nro_cliente: str | None
    cliente_nombre: str | None
    cliente_id: int | None
    rx: float | None
    online: bool
    ultimo_chequeo: str | None


@dataclass(frozen=True)
class OcupacionPon:
    olt_id: int
    olt_nombre: str | None
    pon: int
    onus: int
    online: int


class OpticaRepository:
    def __init__(self, sesion: Session) -> None:
        self._s = sesion

    def lecturas_actuales(self) -> list[LecturaActual]:
        """Última señal conocida de cada ONU, con el cliente cruzado.

        El cruce va por `TRIM` en los dos lados: en producción hay
        `nro_cliente` cargados con espacios y sin eso el cliente no aparece.
        """
        consulta = (
            select(
                OnuSenal.olt_id, Olt.nombre, OnuSenal.pon, OnuSenal.onu,
                OnuSenal.nro_cliente, Cliente.nombre, Cliente.id,
                OnuSenal.rx_power, OnuSenal.online, OnuSenal.last_check,
            )
            .select_from(OnuSenal)
            .outerjoin(Olt, Olt.id == OnuSenal.olt_id)
            .outerjoin(
                Cliente,
                func.trim(Cliente.nro_cliente) == func.trim(OnuSenal.nro_cliente),
            )
            .order_by(OnuSenal.olt_id, OnuSenal.pon, OnuSenal.onu)
        )
        return [
            LecturaActual(
                olt_id=f[0], olt_nombre=f[1], pon=f[2], onu=f[3], nro_cliente=f[4],
                cliente_nombre=f[5], cliente_id=f[6], rx=f[7],
                online=bool(f[8]), ultimo_chequeo=f[9],
            )
            for f in self._s.execute(consulta).all()
        ]

    def historico_rx(self, dias: int = 30) -> dict[tuple[int, int, int], list[float]]:
        """Lecturas de Rx por ONU en los últimos N días.

        La fecha de corte se calcula en Python y no con `datetime('now', '-N days')`
        porque esa función es de SQLite y no existe en PostgreSQL: la consulta
        tiene que sobrevivir a la fase 8 sin reescribirse.
        """
        from datetime import date, timedelta

        corte = (date.today() - timedelta(days=dias)).isoformat()
        filas = self._s.execute(
            select(
                OnuSenalHist.olt_id, OnuSenalHist.pon,
                OnuSenalHist.onu, OnuSenalHist.rx_power,
            )
            .where(OnuSenalHist.rx_power.is_not(None), OnuSenalHist.fecha >= corte)
            .order_by(OnuSenalHist.fecha)
        ).all()

        out: dict[tuple[int, int, int], list[float]] = {}
        for olt, pon, onu, rx in filas:
            if olt is None or pon is None or onu is None:
                continue
            out.setdefault((olt, pon, onu), []).append(float(rx))
        return out

    def ocupacion_por_pon(self) -> list[OcupacionPon]:
        """Cuántas ONU cuelga cada puerto PON. Alimenta la alerta de saturación."""
        total = func.count()
        # `online` es 0/1 en la base heredada, no booleano: se suma con CASE en
        # vez de con SUM(online) para que no dependa de cómo tipe cada motor esa
        # columna cuando la fase 8 la convierta.
        activas = func.sum(case((OnuSenal.online == 1, 1), else_=0))
        filas = self._s.execute(
            select(OnuSenal.olt_id, Olt.nombre, OnuSenal.pon, total, activas)
            .select_from(OnuSenal)
            .outerjoin(Olt, Olt.id == OnuSenal.olt_id)
            .group_by(OnuSenal.olt_id, Olt.nombre, OnuSenal.pon)
            .order_by(total.desc())
        ).all()
        return [
            OcupacionPon(olt_id=f[0], olt_nombre=f[1], pon=f[2], onus=int(f[3]),
                         online=int(f[4] or 0))
            for f in filas
        ]
