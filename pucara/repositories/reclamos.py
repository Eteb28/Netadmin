"""Repositorios del dominio Reclamos.

ÚNICO lugar del dominio con acceso a datos (ADR-0001). Los servicios reciben una
instancia de repositorio; no construyen consultas ni conocen SQLAlchemy.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import Select, case, func, select
from sqlalchemy.orm import Session

from pucara.models.reclamos import (
    CausaReclamo, EstadoReclamo, Reclamo, ResolucionReclamo,
)


class CatalogoRepository:
    """Repositorio genérico de los catálogos administrables (causa/resolución)."""

    def __init__(self, sesion: Session, modelo: type) -> None:
        self._s = sesion
        self._m = modelo

    def listar(self, incluir_inactivos: bool = False) -> Sequence:
        q = select(self._m)
        if not incluir_inactivos:
            q = q.where(self._m.activo.is_(True))
        return self._s.scalars(q.order_by(self._m.orden, self._m.nombre)).all()

    def obtener(self, id_: int):
        return self._s.get(self._m, id_)

    def buscar_por_nombre(self, nombre: str):
        return self._s.scalars(
            select(self._m).where(func.lower(self._m.nombre) == nombre.strip().lower())
        ).first()

    def crear(self, nombre: str, descripcion: str | None = None, orden: int = 0):
        obj = self._m(nombre=nombre.strip(), descripcion=descripcion, orden=orden)
        self._s.add(obj)
        self._s.flush()
        return obj

    def actualizar(self, id_: int, **campos):
        obj = self.obtener(id_)
        if obj is None:
            return None
        for k, v in campos.items():
            if v is not None and hasattr(obj, k):
                setattr(obj, k, v)
        self._s.flush()
        return obj

    def desactivar(self, id_: int) -> bool:
        """Baja lógica. Nunca DELETE: los reclamos históricos siguen apuntando acá."""
        obj = self.obtener(id_)
        if obj is None:
            return False
        obj.activo = False
        self._s.flush()
        return True


class CausaRepository(CatalogoRepository):
    def __init__(self, sesion: Session) -> None:
        super().__init__(sesion, CausaReclamo)


class ResolucionRepository(CatalogoRepository):
    def __init__(self, sesion: Session) -> None:
        super().__init__(sesion, ResolucionReclamo)


class ReclamoRepository:
    def __init__(self, sesion: Session) -> None:
        self._s = sesion

    # ── lectura ──────────────────────────────────────────────────────────
    def obtener(self, id_: int) -> Reclamo | None:
        return self._s.get(Reclamo, id_)

    def listar_por_cliente(self, cliente_id: int, limite: int | None = None) -> Sequence[Reclamo]:
        q = (
            select(Reclamo)
            .where(Reclamo.cliente_id == cliente_id)
            .order_by(Reclamo.fecha_alta.desc())
        )
        if limite:
            q = q.limit(limite)
        return self._s.scalars(q).all()

    def listar_abiertos(self) -> Sequence[Reclamo]:
        return self._s.scalars(
            select(Reclamo)
            .where(Reclamo.estado.in_([EstadoReclamo.ABIERTO, EstadoReclamo.EN_PROCESO]))
            .order_by(Reclamo.fecha_alta)
        ).all()

    def contar_por_cliente(self, cliente_id: int) -> int:
        return self._s.scalar(
            select(func.count(Reclamo.id)).where(Reclamo.cliente_id == cliente_id)
        ) or 0

    # ── escritura ────────────────────────────────────────────────────────
    def crear(self, **campos) -> Reclamo:
        r = Reclamo(**campos)
        self._s.add(r)
        self._s.flush()
        return r

    def guardar(self, reclamo: Reclamo) -> Reclamo:
        self._s.add(reclamo)
        self._s.flush()
        return reclamo

    # ── analítica (fase 3) ───────────────────────────────────────────────
    # Las agregaciones viven acá y no en el servicio: son acceso a datos, y
    # resolverlas en la base evita traer miles de filas a memoria.

    def _base_periodo(self, desde: datetime | None, hasta: datetime | None) -> Select:
        q = select(Reclamo)
        if desde:
            q = q.where(Reclamo.fecha_alta >= desde)
        if hasta:
            q = q.where(Reclamo.fecha_alta <= hasta)
        return q

    def agrupar_por(
        self, columna, desde: datetime | None = None, hasta: datetime | None = None,
        limite: int = 20,
    ) -> list[tuple]:
        """Conteo agrupado por una columna cualquiera. Base de los rankings."""
        q = (
            select(columna, func.count(Reclamo.id).label("total"))
            .where(columna.is_not(None))
            .group_by(columna)
            .order_by(func.count(Reclamo.id).desc())
            .limit(limite)
        )
        if desde:
            q = q.where(Reclamo.fecha_alta >= desde)
        if hasta:
            q = q.where(Reclamo.fecha_alta <= hasta)
        return [tuple(f) for f in self._s.execute(q).all()]

    def conteo_por_causa(self, desde=None, hasta=None) -> list[tuple[str, int]]:
        q = (
            select(CausaReclamo.nombre, func.count(Reclamo.id))
            .join(CausaReclamo, Reclamo.causa_id == CausaReclamo.id)
            .group_by(CausaReclamo.nombre)
            .order_by(func.count(Reclamo.id).desc())
        )
        if desde:
            q = q.where(Reclamo.fecha_alta >= desde)
        if hasta:
            q = q.where(Reclamo.fecha_alta <= hasta)
        return [(n, c) for n, c in self._s.execute(q).all()]

    def conteo_por_resolucion(self, desde=None, hasta=None) -> list[tuple[str, int]]:
        q = (
            select(ResolucionReclamo.nombre, func.count(Reclamo.id))
            .join(ResolucionReclamo, Reclamo.resolucion_id == ResolucionReclamo.id)
            .group_by(ResolucionReclamo.nombre)
            .order_by(func.count(Reclamo.id).desc())
        )
        if desde:
            q = q.where(Reclamo.fecha_alta >= desde)
        if hasta:
            q = q.where(Reclamo.fecha_alta <= hasta)
        return [(n, c) for n, c in self._s.execute(q).all()]

    def cerrados_con_duracion(self, desde=None, hasta=None) -> Sequence[Reclamo]:
        """Reclamos ya cerrados. Insumo del MTTR."""
        q = self._base_periodo(desde, hasta).where(Reclamo.fecha_cierre.is_not(None))
        return self._s.scalars(q).all()

    def fechas_por_cliente(self, cliente_id: int) -> list[datetime]:
        """Fechas de alta ordenadas. Insumo del MTBF."""
        return list(
            self._s.scalars(
                select(Reclamo.fecha_alta)
                .where(Reclamo.cliente_id == cliente_id)
                .order_by(Reclamo.fecha_alta)
            ).all()
        )

    def conteo_por_olt_pon(
        self, desde=None, hasta=None, limite: int = 20,
    ) -> list[tuple[int, int, int]]:
        """(olt_id, pon, total). Agrupa por el **par**, no por el PON suelto.

        Agrupar sólo por `pon` sumaría el PON 1 de la OLT de Crespo con el PON 1
        de la de El Pingo, que son dos puertos físicos distintos.
        """
        q = (
            select(Reclamo.olt_id, Reclamo.pon, func.count(Reclamo.id))
            .where(Reclamo.olt_id.is_not(None), Reclamo.pon.is_not(None))
            .group_by(Reclamo.olt_id, Reclamo.pon)
            .order_by(func.count(Reclamo.id).desc())
            .limit(limite)
        )
        if desde:
            q = q.where(Reclamo.fecha_alta >= desde)
        if hasta:
            q = q.where(Reclamo.fecha_alta <= hasta)
        return [(o, p, t) for o, p, t in self._s.execute(q).all()]

    def ranking_tecnicos(self, desde=None, hasta=None) -> list[tuple[str, int, int]]:
        """(técnico, total, resueltos) para calcular la tasa de resolución."""
        resueltos = func.sum(
            case((Reclamo.fecha_cierre.is_not(None), 1), else_=0)
        )
        q = (
            select(Reclamo.tecnico, func.count(Reclamo.id), resueltos)
            .where(Reclamo.tecnico.is_not(None))
            .group_by(Reclamo.tecnico)
            .order_by(func.count(Reclamo.id).desc())
        )
        if desde:
            q = q.where(Reclamo.fecha_alta >= desde)
        if hasta:
            q = q.where(Reclamo.fecha_alta <= hasta)
        return [(t, int(tot), int(res or 0)) for t, tot, res in self._s.execute(q).all()]
