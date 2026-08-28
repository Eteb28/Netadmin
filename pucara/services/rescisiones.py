"""Fase 6 — ONU de clientes dados de baja que siguen registradas en la OLT.

**SÓLO LECTURA.** Este servicio arma el listado para que alguien lo revise y
decida. No escribe en la OLT ni cambia el estado del cliente: fue una corrección
explícita del alcance de la fase.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from pucara.repositories.clientes import ClienteAnaliticaRepository, OnuPendienteBaja

# Cuánto tiempo tiene que llevar un cliente en estado de baja para que dejar su
# ONU dada de alta sea llamativo. Un par de días es normal (papeleo, retiro del
# equipo); tres meses ya es un puerto ocupado sin facturar.
DIAS_PARA_ALERTA = 90

# `pte_rescision` es un estado en trámite: el cliente todavía puede arrepentirse.
# Se lista igual, pero separado, porque la acción a tomar no es la misma.
ESTADOS_EN_TRAMITE = {"pte_rescision"}


@dataclass(frozen=True)
class ResumenRescisiones:
    """Contadores para el encabezado de la pantalla."""

    total: int
    en_tramite: int
    confirmadas: int
    online: int
    antiguas: int
    por_olt: list[tuple[str, int]] = field(default_factory=list)
    por_estado: list[tuple[str, int]] = field(default_factory=list)


@dataclass(frozen=True)
class PendienteRescision:
    """Una fila del listado, ya enriquecida con lo que la interfaz necesita."""

    cliente_id: int | None
    nombre: str | None
    nro_cliente: str | None
    estado_comercial: str | None
    olt_id: int | None
    olt_nombre: str | None
    pon: int | None
    onu: int | None
    serial: str | None
    fecha_estado: str | None
    dias_desde_cambio: int | None
    online: bool
    ultimo_chequeo: str | None
    en_tramite: bool
    antigua: bool
    ubicacion: str


class ServicioRescisiones:
    def __init__(self, repo: ClienteAnaliticaRepository) -> None:
        self._r = repo

    def listar(
        self,
        estado: str | None = None,
        olt_id: int | None = None,
        dias_minimos: int | None = None,
    ) -> list[PendienteRescision]:
        filas = [_enriquecer(f) for f in self._r.onus_de_clientes_a_dar_de_baja()]
        if estado:
            filas = [f for f in filas if f.estado_comercial == estado]
        if olt_id is not None:
            filas = [f for f in filas if f.olt_id == olt_id]
        if dias_minimos is not None:
            filas = [
                f for f in filas
                if f.dias_desde_cambio is not None and f.dias_desde_cambio >= dias_minimos
            ]
        # Primero lo más viejo: es lo que más tiempo lleva ocupando un puerto.
        return sorted(filas, key=lambda f: (-(f.dias_desde_cambio or 0), f.nombre or ""))

    def resumen(self, filas: list[PendienteRescision] | None = None) -> ResumenRescisiones:
        filas = self.listar() if filas is None else filas
        return ResumenRescisiones(
            total=len(filas),
            en_tramite=sum(1 for f in filas if f.en_tramite),
            confirmadas=sum(1 for f in filas if not f.en_tramite),
            online=sum(1 for f in filas if f.online),
            antiguas=sum(1 for f in filas if f.antigua),
            por_olt=sorted(
                Counter(f.olt_nombre or f"OLT {f.olt_id}" for f in filas).items(),
                key=lambda kv: -kv[1],
            ),
            por_estado=sorted(
                Counter(f.estado_comercial or "sin estado" for f in filas).items(),
                key=lambda kv: -kv[1],
            ),
        )


def _enriquecer(o: OnuPendienteBaja) -> PendienteRescision:
    dias = o.dias_desde_cambio
    return PendienteRescision(
        cliente_id=o.cliente_id,
        nombre=o.nombre,
        nro_cliente=o.nro_cliente,
        estado_comercial=o.estado_comercial,
        olt_id=o.olt_id,
        olt_nombre=o.olt_nombre,
        pon=o.pon,
        onu=o.onu,
        serial=o.serial,
        fecha_estado=o.fecha_estado,
        dias_desde_cambio=dias,
        online=o.online,
        ultimo_chequeo=o.ultimo_chequeo,
        en_tramite=(o.estado_comercial or "") in ESTADOS_EN_TRAMITE,
        antigua=dias is not None and dias >= DIAS_PARA_ALERTA,
        ubicacion=_ubicacion(o),
    )


def _ubicacion(o: OnuPendienteBaja) -> str:
    """Etiqueta legible del puerto: lo que el técnico busca en la OLT."""
    olt = o.olt_nombre or (f"OLT {o.olt_id}" if o.olt_id else "OLT ?")
    if o.pon is None or o.onu is None:
        return olt
    return f"{olt} · GPON0/{o.pon}:{o.onu}"
