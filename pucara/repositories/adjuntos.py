"""Repositorios de los adjuntos de notas."""
from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from pucara.models.adjuntos import AdjuntoTarea
from pucara.models.legado import TareaUsuario


class AdjuntoRepository:
    def __init__(self, sesion: Session) -> None:
        self._s = sesion

    def obtener(self, id_: int) -> AdjuntoTarea | None:
        return self._s.get(AdjuntoTarea, id_)

    def listar_de_tarea(self, tarea_id: int) -> Sequence[AdjuntoTarea]:
        return self._s.scalars(
            select(AdjuntoTarea)
            .where(AdjuntoTarea.tarea_id == tarea_id)
            .order_by(AdjuntoTarea.id)
        ).all()

    def listar_de_tareas(self, tarea_ids: list[int]) -> dict[int, list[AdjuntoTarea]]:
        """Todos los adjuntos de varias notas de una vez.

        El tablero pinta N post-its: pedir los adjuntos de cada uno por separado
        serían N consultas. Con esto es una sola.
        """
        if not tarea_ids:
            return {}
        filas = self._s.scalars(
            select(AdjuntoTarea)
            .where(AdjuntoTarea.tarea_id.in_(tarea_ids))
            .order_by(AdjuntoTarea.tarea_id, AdjuntoTarea.id)
        ).all()
        out: dict[int, list[AdjuntoTarea]] = {}
        for a in filas:
            out.setdefault(a.tarea_id, []).append(a)
        return out

    def contar_de_tarea(self, tarea_id: int) -> int:
        return self._s.scalar(
            select(func.count(AdjuntoTarea.id)).where(AdjuntoTarea.tarea_id == tarea_id)
        ) or 0

    def crear(self, **campos) -> AdjuntoTarea:
        a = AdjuntoTarea(**campos)
        self._s.add(a)
        self._s.flush()
        return a

    def borrar(self, adjunto: AdjuntoTarea) -> None:
        self._s.delete(adjunto)
        self._s.flush()

    def borrar_de_tarea(self, tarea_id: int) -> list[str]:
        """Borra las fichas de una nota y devuelve los archivos que quedaron
        huérfanos, para que el servicio los saque del disco."""
        archivos = [a.archivo for a in self.listar_de_tarea(tarea_id)]
        self._s.execute(delete(AdjuntoTarea).where(AdjuntoTarea.tarea_id == tarea_id))
        self._s.flush()
        return archivos


class TareaLegadaRepository:
    """Lectura de `tareas_usuario`, tabla heredada descrita en `models.legado`."""

    def __init__(self, sesion: Session) -> None:
        self._s = sesion

    def duenio(self, tarea_id: int) -> str | None:
        """Username del dueño de la nota, o None si la nota no existe."""
        return self._s.execute(
            select(TareaUsuario.username).where(TareaUsuario.id == tarea_id)
        ).scalar_one_or_none()
