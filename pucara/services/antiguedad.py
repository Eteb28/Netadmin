"""Estadísticas de permanencia y churn de clientes FTTH (fase 5)."""
from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import date

from pucara.repositories.clientes import ClienteAnaliticaRepository

# Tramos pedidos en el enunciado
TRAMOS: list[tuple[str, float, float]] = [
    ("0-3 meses", 0, 3),
    ("3-6 meses", 3, 6),
    ("6-12 meses", 6, 12),
    ("12-24 meses", 12, 24),
    ("Más de 24 meses", 24, float("inf")),
]

ESTADOS_BAJA = {"baja", "rescision"}


@dataclass(frozen=True)
class EstadisticasAntiguedad:
    total_activos: int
    total_bajas: int
    permanencia_media_meses: float | None
    permanencia_media_bajas_meses: float | None
    distribucion_activos: list[tuple[str, int]] = field(default_factory=list)
    distribucion_bajas: list[tuple[str, int]] = field(default_factory=list)
    altas_por_mes: list[tuple[str, int]] = field(default_factory=list)
    bajas_por_mes: list[tuple[str, int]] = field(default_factory=list)
    churn_mensual: list[tuple[str, float]] = field(default_factory=list)
    churn_anual: float | None = None


class ServicioAntiguedad:
    def __init__(self, repo: ClienteAnaliticaRepository) -> None:
        self._r = repo

    def calcular(self, tipo_servicio: str = "fibra") -> EstadisticasAntiguedad:
        clientes = self._r.clientes_con_antiguedad(tipo_servicio)
        if not clientes:
            return EstadisticasAntiguedad(0, 0, None, None)

        activos = [c for c in clientes if c.estado not in ESTADOS_BAJA]
        bajas = [c for c in clientes if c.estado in ESTADOS_BAJA]

        altas_mes = Counter(c.fecha_alta.strftime("%Y-%m") for c in clientes if c.fecha_alta)
        bajas_mes = Counter(c.fecha_baja.strftime("%Y-%m") for c in bajas if c.fecha_baja)

        return EstadisticasAntiguedad(
            total_activos=len(activos),
            total_bajas=len(bajas),
            permanencia_media_meses=_media([c.meses for c in activos]),
            permanencia_media_bajas_meses=_media([c.meses for c in bajas]),
            distribucion_activos=_distribuir(activos),
            distribucion_bajas=_distribuir(bajas),
            altas_por_mes=sorted(altas_mes.items()),
            bajas_por_mes=sorted(bajas_mes.items()),
            churn_mensual=self._churn_mensual(clientes, bajas_mes),
            churn_anual=self._churn_anual(len(activos), len(bajas)),
        )

    @staticmethod
    def _churn_mensual(clientes, bajas_mes) -> list[tuple[str, float]]:
        """Churn = bajas del mes / base activa al comenzar ese mes.

        La base se reconstruye contando quién ya estaba de alta y todavía no se
        había ido. Dividir por el total histórico daría un número siempre chico
        y sin sentido.
        """
        out = []
        for mes in sorted(bajas_mes):
            inicio = date.fromisoformat(f"{mes}-01")
            base = sum(
                1 for c in clientes
                if c.fecha_alta and c.fecha_alta < inicio
                and (c.fecha_baja is None or c.fecha_baja >= inicio)
            )
            if base:
                out.append((mes, round(bajas_mes[mes] / base * 100, 2)))
        return out

    @staticmethod
    def _churn_anual(activos: int, bajas: int) -> float | None:
        base = activos + bajas
        return round(bajas / base * 100, 2) if base else None


def _media(valores: list[float | None]) -> float | None:
    limpios = [v for v in valores if v is not None]
    return round(statistics.fmean(limpios), 1) if limpios else None


def _distribuir(clientes) -> list[tuple[str, int]]:
    cuenta = {etiqueta: 0 for etiqueta, _, _ in TRAMOS}
    for c in clientes:
        if c.meses is None:
            continue
        for etiqueta, desde, hasta in TRAMOS:
            if desde <= c.meses < hasta:
                cuenta[etiqueta] += 1
                break
    return list(cuenta.items())
