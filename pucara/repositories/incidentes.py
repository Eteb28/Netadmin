"""Repositorio del motor de incidentes."""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from pucara.models.incidentes import (  # noqa: F401
    AlcanceIncidente, EstadoIncidente, Incidente, IncidenteAfectado,
)
from pucara.models.legado import OnuSenal


class IncidenteRepository:
    def __init__(self, sesion: Session) -> None:
        self._s = sesion

    def buscar_abierto(self, alcance: AlcanceIncidente, referencia: str) -> Incidente | None:
        """Incidente no cerrado para ese objeto. Base de la no-duplicación."""
        return self._s.scalars(
            select(Incidente)
            .options(selectinload(Incidente.afectados))
            .where(
                Incidente.alcance == alcance,
                Incidente.referencia == referencia,
                Incidente.estado != EstadoIncidente.CERRADA,
            )
        ).first()

    def listar_activos(self) -> Sequence[Incidente]:
        return self._s.scalars(
            select(Incidente)
            .options(selectinload(Incidente.afectados))
            .where(Incidente.estado != EstadoIncidente.CERRADA)
            .order_by(Incidente.inicio)
        ).all()

    def listar_recuperados_antes_de(self, limite: datetime) -> Sequence[Incidente]:
        return self._s.scalars(
            select(Incidente).where(
                Incidente.estado == EstadoIncidente.RECUPERADA,
                Incidente.recuperado.is_not(None),
                Incidente.recuperado <= limite,
            )
        ).all()

    def historial(self, limite: int = 100) -> Sequence[Incidente]:
        return self._s.scalars(
            select(Incidente)
            .options(selectinload(Incidente.afectados))
            .order_by(Incidente.inicio.desc())
            .limit(limite)
        ).all()

    def total_onus_en_pon(self, olt_id: int, pon: int) -> int:
        """Total de ONU del PON, para evaluar el umbral porcentual.

        Lee de `onu_senal`, que mantiene el poller de OLT. Si la tabla no
        existe —base recién creada, o una instalación sin fibra— devuelve 0 y
        el motor cae al umbral absoluto en vez de fallar.

        **El SAVEPOINT no es decorativo.** En SQLite un `SELECT` contra una
        tabla inexistente falla y la transacción sigue usable; en PostgreSQL
        aborta la transacción entera y todo lo que venga después muere con
        "current transaction is aborted". Sin el `begin_nested()`, este
        `except` convertía una tabla faltante en la pérdida de todo el lote de
        incidentes de esa pasada. Con savepoint, el error queda contenido.
        """
        try:
            with self._s.begin_nested():
                return self._s.scalar(
                    select(func.count())
                    .select_from(OnuSenal)
                    .where(OnuSenal.olt_id == olt_id, OnuSenal.pon == pon)
                ) or 0
        except Exception:
            return 0

    def crear(self, **campos) -> Incidente:
        inc = Incidente(**campos)
        self._s.add(inc)
        self._s.flush()
        return inc

    def guardar(self, inc: Incidente) -> Incidente:
        self._s.add(inc)
        self._s.flush()
        return inc
