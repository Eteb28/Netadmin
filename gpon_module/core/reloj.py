"""Fuentes de tiempo inyectables.

Todo el módulo pide la hora a un ``Reloj``, nunca a ``datetime.now()`` directo.
Así los tests de sincronización e histéresis de alarmas son deterministas.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


class RelojSistema:
    """Reloj real, en UTC. Toda marca de tiempo del módulo es UTC."""

    def ahora(self) -> datetime:
        return datetime.now(UTC)


class RelojFijo:
    """Reloj controlado, para pruebas."""

    def __init__(self, momento: datetime | None = None) -> None:
        self._momento = momento or datetime(2026, 1, 1, tzinfo=UTC)

    def ahora(self) -> datetime:
        return self._momento

    def avanzar(self, *, segundos: float = 0, minutos: float = 0, horas: float = 0) -> datetime:
        self._momento += timedelta(seconds=segundos, minutes=minutos, hours=horas)
        return self._momento

    def fijar(self, momento: datetime) -> None:
        self._momento = momento
