"""Servicio del dominio Reclamos (fases 2 y 3).

Contiene la lógica de negocio. No sabe de HTTP ni de SQL: recibe repositorios
por constructor (inyección de dependencias) y devuelve DTO.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

from pucara.models.reclamos import EstadoReclamo, Reclamo, ahora
from pucara.repositories.reclamos import (
    CausaRepository, ReclamoRepository, ResolucionRepository,
)


class ErrorReclamo(Exception):
    """Error de negocio. La capa API lo traduce a HTTP 400."""


# ── DTO ──────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class ReclamoDTO:
    id: int
    cliente_id: int
    fecha_alta: datetime
    fecha_cierre: datetime | None
    estado: str
    causa: str | None
    resolucion: str | None
    usuario_alta: str
    tecnico: str | None
    observaciones: str | None
    minutos_resolucion: float | None
    ap_nombre: str | None
    olt_id: int | None
    pon: int | None

    @classmethod
    def desde_modelo(cls, r: Reclamo) -> ReclamoDTO:
        return cls(
            id=r.id, cliente_id=r.cliente_id, fecha_alta=r.fecha_alta,
            fecha_cierre=r.fecha_cierre, estado=r.estado.value,
            causa=r.causa.nombre if r.causa else None,
            resolucion=r.resolucion.nombre if r.resolucion else None,
            usuario_alta=r.usuario_alta, tecnico=r.tecnico,
            observaciones=r.observaciones,
            minutos_resolucion=r.minutos_resolucion,
            ap_nombre=r.ap_nombre, olt_id=r.olt_id, pon=r.pon,
        )


@dataclass(frozen=True)
class EstadisticasCliente:
    """Lo que se muestra en la pestaña Reclamos del modal del cliente."""

    total: int
    abiertos: int
    por_causa: list[tuple[str, int]] = field(default_factory=list)
    por_resolucion: list[tuple[str, int]] = field(default_factory=list)
    mttr_minutos: float | None = None          # tiempo medio de resolución
    mtbf_dias: float | None = None             # tiempo medio entre reclamos
    dias_desde_ultimo: float | None = None
    ultimos: list[ReclamoDTO] = field(default_factory=list)


# ── servicio ─────────────────────────────────────────────────────────────
class ServicioReclamos:
    def __init__(
        self,
        reclamos: ReclamoRepository,
        causas: CausaRepository,
        resoluciones: ResolucionRepository,
    ) -> None:
        self._reclamos = reclamos
        self._causas = causas
        self._resoluciones = resoluciones

    # ── operaciones ──────────────────────────────────────────────────────
    def registrar(
        self, cliente_id: int, usuario: str, causa_id: int | None = None,
        observaciones: str | None = None, tecnico: str | None = None,
        contexto_red: dict | None = None,
    ) -> ReclamoDTO:
        if not usuario:
            raise ErrorReclamo("Falta el usuario que registra el reclamo")
        if causa_id is not None and self._causas.obtener(causa_id) is None:
            raise ErrorReclamo(f"La causa {causa_id} no existe")

        # El contexto de red se copia al reclamo (ver comentario en el modelo):
        # si el cliente cambia de AP mañana, este reclamo debe seguir contando
        # contra el AP que falló hoy.
        ctx = contexto_red or {}
        r = self._reclamos.crear(
            cliente_id=cliente_id, usuario_alta=usuario, causa_id=causa_id,
            observaciones=observaciones, tecnico=tecnico,
            estado=EstadoReclamo.ABIERTO,
            ap_id=ctx.get("ap_id"), ap_nombre=ctx.get("ap_nombre"),
            olt_id=ctx.get("olt_id"), pon=ctx.get("pon"),
            tipo_servicio=ctx.get("tipo_servicio"),
        )
        return ReclamoDTO.desde_modelo(r)

    def cerrar(
        self, reclamo_id: int, usuario: str, resolucion_id: int | None = None,
        observaciones: str | None = None,
    ) -> ReclamoDTO:
        r = self._reclamos.obtener(reclamo_id)
        if r is None:
            raise ErrorReclamo(f"El reclamo {reclamo_id} no existe")
        if r.estado.es_final:
            raise ErrorReclamo(f"El reclamo ya está {r.estado.value}")
        if resolucion_id is not None and self._resoluciones.obtener(resolucion_id) is None:
            raise ErrorReclamo(f"La resolución {resolucion_id} no existe")

        r.estado = EstadoReclamo.CERRADO
        r.fecha_cierre = ahora()
        r.usuario_cierre = usuario
        r.resolucion_id = resolucion_id
        if observaciones:
            r.observaciones = f"{r.observaciones or ''}\n{observaciones}".strip()
        self._reclamos.guardar(r)
        return ReclamoDTO.desde_modelo(r)

    def historial(self, cliente_id: int) -> list[ReclamoDTO]:
        return [ReclamoDTO.desde_modelo(r) for r in self._reclamos.listar_por_cliente(cliente_id)]

    # ── estadísticas del cliente ─────────────────────────────────────────
    def estadisticas_cliente(self, cliente_id: int) -> EstadisticasCliente:
        reclamos = list(self._reclamos.listar_por_cliente(cliente_id))
        if not reclamos:
            return EstadisticasCliente(total=0, abiertos=0)

        abiertos = sum(1 for r in reclamos if not r.estado.es_final)

        por_causa: dict[str, int] = {}
        por_resolucion: dict[str, int] = {}
        for r in reclamos:
            if r.causa:
                por_causa[r.causa.nombre] = por_causa.get(r.causa.nombre, 0) + 1
            if r.resolucion:
                por_resolucion[r.resolucion.nombre] = por_resolucion.get(r.resolucion.nombre, 0) + 1

        duraciones = [r.minutos_resolucion for r in reclamos if r.minutos_resolucion is not None]
        fechas = sorted(r.fecha_alta for r in reclamos)

        return EstadisticasCliente(
            total=len(reclamos),
            abiertos=abiertos,
            por_causa=sorted(por_causa.items(), key=lambda x: -x[1]),
            por_resolucion=sorted(por_resolucion.items(), key=lambda x: -x[1]),
            mttr_minutos=round(statistics.fmean(duraciones), 1) if duraciones else None,
            mtbf_dias=self._mtbf_dias(fechas),
            dias_desde_ultimo=round((ahora() - fechas[-1]).total_seconds() / 86400, 1),
            ultimos=[ReclamoDTO.desde_modelo(r) for r in reclamos[:5]],
        )

    @staticmethod
    def _mtbf_dias(fechas: list[datetime]) -> float | None:
        """Tiempo medio entre reclamos consecutivos.

        Con un solo reclamo NO hay intervalo que medir: devuelve None, no 0.
        Un 0 se leería como "falla continuamente", que es lo contrario.
        """
        if len(fechas) < 2:
            return None
        intervalos = [
            (b - a).total_seconds() / 86400 for a, b in zip(fechas, fechas[1:])
        ]
        return round(statistics.fmean(intervalos), 1)


# ── motor de análisis global (fase 3) ────────────────────────────────────
@dataclass(frozen=True)
class RankingItem:
    nombre: str
    total: int
    extra: float | None = None
    id: int | None = None          # para que la interfaz pueda enlazar la ficha


class DirectorioNombres(Protocol):
    """Lo único que la analítica necesita saber de los clientes y las OLT: cómo
    se llaman. Declarado como protocolo para que el servicio no dependa de un
    repositorio concreto ni de las tablas heredadas."""

    def nombres(self, ids: list[int]) -> dict[int, str]: ...

    def nombres_olts(self) -> dict[int, str]: ...


class ServicioAnaliticaReclamos:
    """Indicadores agregados: quién falla más y cuánto se tarda en resolver."""

    def __init__(
        self,
        reclamos: ReclamoRepository,
        directorio: "DirectorioNombres | None" = None,
    ) -> None:
        self._r = reclamos
        # Opcional: sin él los rankings salen con id en vez de nombre, pero
        # siguen funcionando. Así las pruebas del servicio no necesitan las
        # tablas heredadas.
        self._dir = directorio

    def _ventana(self, dias: int | None) -> tuple[datetime | None, None]:
        return ((ahora() - timedelta(days=dias)) if dias else None, None)

    def top_clientes(self, dias: int | None = 90, limite: int = 20) -> list[RankingItem]:
        from pucara.models.reclamos import Reclamo as R
        desde, hasta = self._ventana(dias)
        filas = self._r.agrupar_por(R.cliente_id, desde, hasta, limite)
        nombres = self._dir.nombres([c for c, _ in filas]) if self._dir else {}
        return [
            RankingItem(nombre=nombres.get(c, f"Cliente #{c}"), total=t, id=c)
            for c, t in filas
        ]

    def top_aps(self, dias: int | None = 90, limite: int = 20) -> list[RankingItem]:
        from pucara.models.reclamos import Reclamo as R
        desde, hasta = self._ventana(dias)
        filas = self._r.agrupar_por(R.ap_nombre, desde, hasta, limite)
        return [RankingItem(nombre=a, total=t) for a, t in filas]

    def _nombres_olts(self) -> dict[int, str]:
        return self._dir.nombres_olts() if self._dir else {}

    def top_pon(self, dias: int | None = 90, limite: int = 20) -> list[RankingItem]:
        """Ranking por puerto PON identificado por su OLT.

        El PON 1 de una OLT no es el mismo puerto que el PON 1 de otra: se
        agrupa por el par (olt, pon), no por el número suelto.
        """
        desde, hasta = self._ventana(dias)
        olts = self._nombres_olts()
        return [
            RankingItem(nombre=f"{olts.get(o, f'OLT {o}')} · PON {p}", total=t, id=o)
            for o, p, t in self._r.conteo_por_olt_pon(desde, hasta, limite)
        ]

    def top_olt(self, dias: int | None = 90, limite: int = 20) -> list[RankingItem]:
        from pucara.models.reclamos import Reclamo as R
        desde, hasta = self._ventana(dias)
        olts = self._nombres_olts()
        filas = self._r.agrupar_por(R.olt_id, desde, hasta, limite)
        return [
            RankingItem(nombre=olts.get(o, f"OLT {o}"), total=t, id=o) for o, t in filas
        ]

    def mttr_global(self, dias: int | None = 90) -> float | None:
        desde, hasta = self._ventana(dias)
        dur = [
            r.minutos_resolucion
            for r in self._r.cerrados_con_duracion(desde, hasta)
            if r.minutos_resolucion is not None
        ]
        return round(statistics.fmean(dur), 1) if dur else None

    def tasa_resolucion_tecnicos(self, dias: int | None = 90) -> list[RankingItem]:
        desde, hasta = self._ventana(dias)
        out = []
        for tecnico, total, resueltos in self._r.ranking_tecnicos(desde, hasta):
            pct = round(resueltos / total * 100, 1) if total else 0.0
            out.append(RankingItem(nombre=tecnico, total=total, extra=pct))
        return out

    def resumen(self, dias: int | None = 90) -> dict:
        desde, hasta = self._ventana(dias)
        return {
            "dias": dias,
            "mttr_minutos": self.mttr_global(dias),
            "por_causa": self._r.conteo_por_causa(desde, hasta),
            "por_resolucion": self._r.conteo_por_resolucion(desde, hasta),
            "top_clientes": [vars(i) for i in self.top_clientes(dias)],
            "top_aps": [vars(i) for i in self.top_aps(dias)],
            "top_pon": [vars(i) for i in self.top_pon(dias)],
            "top_olt": [vars(i) for i in self.top_olt(dias)],
            "tecnicos": [vars(i) for i in self.tasa_resolucion_tecnicos(dias)],
        }
