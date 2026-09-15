"""Modelos del motor unificado de incidentes (fases 3 y 4, ver ADR-0003).

Reemplaza los dos mecanismos desconectados que existen hoy (`snmp_eventos` para
wireless y `alertas_infra` para FTTH) con una sola máquina de estados.
"""
from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    DateTime, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pucara.db import Base, UtcDateTime
from pucara.models.reclamos import ahora


class EstadoIncidente(enum.Enum):
    """INICIO → ACTIVA → RECUPERADA → CERRADA (ADR-0003)."""

    ACTIVA = "activa"
    RECUPERADA = "recuperada"   # volvió, pero todavía no cumplió la estabilidad
    CERRADA = "cerrada"


class AlcanceIncidente(enum.Enum):
    """A qué le pasó el problema. Un incidente de PON agrupa muchas ONU."""

    ONU = "onu"
    PON = "pon"
    OLT = "olt"
    EQUIPO_TORRE = "equipo_torre"


class CausaProbable(enum.Enum):
    """Causa inferida de los motivos de caída que reporta la propia OLT.

    Está verificado que la V1600G1-B expone por ONU el motivo: `Power Off`
    (dying gasp: se cortó la luz en el domicilio) y `Onu Los` (pérdida de señal:
    problema de fibra). Distinguirlos es la diferencia entre no hacer nada y
    mandar una cuadrilla.
    """

    CORTE_ELECTRICO = "corte_electrico"
    CORTE_FIBRA = "corte_fibra"
    FALLA_OLT = "falla_olt"
    DESCONOCIDA = "desconocida"


class Incidente(Base):
    __tablename__ = "incidentes"
    __table_args__ = (
        Index("ix_incidentes_estado", "estado"),
        Index("ix_incidentes_alcance", "alcance", "referencia"),
        Index("ix_incidentes_inicio", "inicio"),
        # Sin este índice único, dos corridas del poller solapadas crearían dos
        # incidentes abiertos para el mismo objeto. Es la garantía de "no
        # generar eventos duplicados" a nivel motor, no a nivel código.
        #
        # Es PARCIAL a propósito (sólo sobre los no cerrados): un índice único
        # sobre (alcance, referencia) a secas impediría que un mismo PON tuviera
        # dos incidentes a lo largo del tiempo, que es justamente lo normal.
        # Lo que debe ser único es "un incidente ABIERTO por objeto".
        Index(
            "uq_incidente_abierto",
            "alcance", "referencia",
            unique=True,
            sqlite_where=text("estado != 'CERRADA'"),
            postgresql_where=text("estado != 'CERRADA'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    alcance: Mapped[AlcanceIncidente] = mapped_column(
        Enum(AlcanceIncidente, native_enum=False, length=20), nullable=False
    )
    # Identificador del objeto afectado: "olt:3/pon:5" o "onu:3/5/12".
    referencia: Mapped[str] = mapped_column(String(120), nullable=False)
    titulo: Mapped[str] = mapped_column(String(200), nullable=False)

    estado: Mapped[EstadoIncidente] = mapped_column(
        Enum(EstadoIncidente, native_enum=False, length=20),
        default=EstadoIncidente.ACTIVA, nullable=False,
    )
    causa_probable: Mapped[CausaProbable] = mapped_column(
        Enum(CausaProbable, native_enum=False, length=20),
        default=CausaProbable.DESCONOCIDA, nullable=False,
    )

    inicio: Mapped[datetime] = mapped_column(
        UtcDateTime, default=ahora, nullable=False
    )
    recuperado: Mapped[datetime | None] = mapped_column(UtcDateTime)
    cierre: Mapped[datetime | None] = mapped_column(UtcDateTime)

    usuario_cierre: Mapped[str] = mapped_column(String(80), default="Sistema")
    motivo_cierre: Mapped[str | None] = mapped_column(String(120))

    # Un incidente que va y viene NO genera uno nuevo cada vez: suma un ciclo.
    # Así el intermitente se ve como lo que es, y no como 20 incidentes.
    ciclos: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    olt_id: Mapped[int | None] = mapped_column(Integer)
    pon: Mapped[int | None] = mapped_column(Integer)
    detalle: Mapped[str | None] = mapped_column(Text)

    afectados: Mapped[list[IncidenteAfectado]] = relationship(
        back_populates="incidente", cascade="all, delete-orphan"
    )

    @property
    def minutos_caida(self) -> float | None:
        fin = self.recuperado or self.cierre
        if fin is None:
            return None
        return (fin - self.inicio).total_seconds() / 60.0

    @property
    def cantidad_afectados(self) -> int:
        return len(self.afectados)


class IncidenteAfectado(Base):
    """ONU (o equipo) afectado por un incidente masivo."""

    __tablename__ = "incidente_afectados"
    __table_args__ = (
        UniqueConstraint("incidente_id", "referencia", name="uq_afectado_incidente"),
        Index("ix_afectado_cliente", "cliente_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    incidente_id: Mapped[int] = mapped_column(
        ForeignKey("incidentes.id", ondelete="CASCADE"), nullable=False
    )
    referencia: Mapped[str] = mapped_column(String(120), nullable=False)
    cliente_id: Mapped[int | None] = mapped_column(Integer)
    nro_cliente: Mapped[str | None] = mapped_column(String(40))
    motivo_caida: Mapped[str | None] = mapped_column(String(60))
    recuperado: Mapped[datetime | None] = mapped_column(UtcDateTime)

    incidente: Mapped[Incidente] = relationship(back_populates="afectados")
