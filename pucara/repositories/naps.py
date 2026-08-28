"""Repositorio de NAPs.

`naps` la sigue creando `app.py`, pero ya está descrita en
`pucara.models.legado`: por eso acá no hay más SQL en texto. La consulta se
arma con las columnas del modelo y el dialecto lo resuelve SQLAlchemy, que es
la condición para que esto no se reescriba al pasar a PostgreSQL (fase 8).
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from pucara.models.legado import Nap


@dataclass(frozen=True)
class UbicacionNap:
    id: int
    nombre: str
    lat: float | None
    lng: float | None


class NapRepository:
    def __init__(self, sesion: Session) -> None:
        self._s = sesion

    def obtener(self, nap_id: int) -> UbicacionNap | None:
        fila = self._s.execute(
            select(Nap.id, Nap.nombre, Nap.lat, Nap.lng).where(Nap.id == nap_id)
        ).first()
        if fila is None:
            return None
        return UbicacionNap(id=fila[0], nombre=fila[1], lat=fila[2], lng=fila[3])

    def mover(self, nap_id: int, lat: float, lng: float) -> None:
        """Actualiza SÓLO la posición.

        Deliberadamente acotado: el `PUT /api/naps/<id>` heredado reescribe la
        fila entera y exige el payload completo, así que usarlo para mover un
        marcador borraría descripción, localidad, red y CDO.
        """
        self._s.execute(
            update(Nap).where(Nap.id == nap_id).values(lat=lat, lng=lng)
        )
