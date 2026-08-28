"""Modelos del dominio Reclamos (fase 2).

Los catálogos de causa y resolución son TABLAS, no listas en el código: el
pedido pide administrarlos desde Configuración sin tocar el código.
"""
from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, DateTime, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pucara.db import Base, UtcDateTime


def ahora() -> datetime:
    """Instante actual en UTC.

    Se guarda en UTC a propósito: hoy el sistema usa datetime('now','localtime')
    y las fechas quedan sin zona, lo que rompe cualquier cálculo de duración
    cuando cambia el huso. La conversión a hora local se hace al mostrar.
    """
    return datetime.now(timezone.utc)


class EstadoReclamo(enum.Enum):
    ABIERTO = "abierto"
    EN_PROCESO = "en_proceso"
    RESUELTO = "resuelto"
    CERRADO = "cerrado"
    ANULADO = "anulado"

    @property
    def es_final(self) -> bool:
        return self in (EstadoReclamo.CERRADO, EstadoReclamo.ANULADO)


class _CatalogoBase:
    """Campos comunes de los catálogos administrables.

    `activo` en vez de borrar: un reclamo viejo debe seguir mostrando su causa
    aunque esa causa ya no se ofrezca para reclamos nuevos. Borrarla dejaría
    huérfano el histórico y falsearía las estadísticas.
    """

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    descripcion: Mapped[str | None] = mapped_column(Text)
    activo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    orden: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    creado: Mapped[datetime] = mapped_column(UtcDateTime, default=ahora)


class CausaReclamo(_CatalogoBase, Base):
    __tablename__ = "reclamo_causas"
    __table_args__ = (UniqueConstraint("nombre", name="uq_reclamo_causa_nombre"),)

    reclamos: Mapped[list[Reclamo]] = relationship(back_populates="causa")


class ResolucionReclamo(_CatalogoBase, Base):
    __tablename__ = "reclamo_resoluciones"
    __table_args__ = (UniqueConstraint("nombre", name="uq_reclamo_resolucion_nombre"),)

    reclamos: Mapped[list[Reclamo]] = relationship(back_populates="resolucion")


class Reclamo(Base):
    """Reclamo técnico con causa y resolución tipificadas.

    NO se llama `reclamos` a propósito: esa tabla ya existe y es el **espejo de
    los tickets de Tero HelpDesk** (`tero_id` como clave, categoría y canal del
    call center, sin causa técnica ni resolución). Son dos cosas distintas y
    conviven: Tero registra el contacto del cliente; esto registra qué falló y
    qué se hizo, que es lo que alimenta la analítica de las fases 3 y 4.
    """

    __tablename__ = "reclamos_tecnicos"
    __table_args__ = (
        # Índices pensados para las consultas reales del módulo:
        Index("ix_rectec_cliente_fecha", "cliente_id", "fecha_alta"),   # historial
        Index("ix_rectec_estado", "estado"),                            # pendientes
        Index("ix_rectec_causa", "causa_id"),                           # analítica
        Index("ix_rectec_ap", "ap_id"),                                 # top APs
        Index("ix_rectec_pon", "olt_id", "pon"),                        # top PON/OLT
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cliente_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    fecha_alta: Mapped[datetime] = mapped_column(
        UtcDateTime, default=ahora, nullable=False
    )
    fecha_cierre: Mapped[datetime | None] = mapped_column(UtcDateTime)

    estado: Mapped[EstadoReclamo] = mapped_column(
        Enum(EstadoReclamo, native_enum=False, length=20),
        default=EstadoReclamo.ABIERTO, nullable=False,
    )

    causa_id: Mapped[int | None] = mapped_column(ForeignKey("reclamo_causas.id"))
    resolucion_id: Mapped[int | None] = mapped_column(ForeignKey("reclamo_resoluciones.id"))

    usuario_alta: Mapped[str] = mapped_column(String(80), nullable=False)
    usuario_cierre: Mapped[str | None] = mapped_column(String(80))
    tecnico: Mapped[str | None] = mapped_column(String(120), index=True)

    observaciones: Mapped[str | None] = mapped_column(Text)

    # Contexto de red al momento del reclamo. Se guarda COPIADO, no por
    # referencia: si mañana el cliente cambia de AP o de PON, el reclamo debe
    # seguir contando contra el equipo que efectivamente falló. Sin esto, la
    # analítica por AP/PON se distorsiona con cada mudanza de cliente.
    ap_id: Mapped[int | None] = mapped_column(Integer)
    ap_nombre: Mapped[str | None] = mapped_column(String(120))
    olt_id: Mapped[int | None] = mapped_column(Integer)
    pon: Mapped[int | None] = mapped_column(Integer)
    tipo_servicio: Mapped[str | None] = mapped_column(String(30))

    causa: Mapped[CausaReclamo | None] = relationship(back_populates="reclamos")
    resolucion: Mapped[ResolucionReclamo | None] = relationship(back_populates="reclamos")

    @property
    def minutos_resolucion(self) -> float | None:
        """Tiempo hasta el cierre. None si sigue abierto (no cero: es distinto)."""
        if self.fecha_cierre is None:
            return None
        return (self.fecha_cierre - self.fecha_alta).total_seconds() / 60.0
