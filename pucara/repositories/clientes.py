"""Repositorio de lectura sobre las tablas heredadas de clientes y ONU.

Las tablas las sigue creando `app.py`, pero ya están descritas en
`pucara.models.legado`: las consultas se arman con SQLAlchemy, no con texto.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pucara.models.legado import Cliente, Olt, OnuSenal

#: Estados comerciales que ponen a una ONU en el listado de bajas pendientes.
#: `pte_rescision` entra por el alcance corregido de la fase 6.
ESTADOS_A_DAR_DE_BAJA = ("rescision", "pte_rescision", "baja")


@dataclass(frozen=True)
class ClienteAntiguedad:
    id: int
    nombre: str
    fecha_alta: date | None
    fecha_baja: date | None
    estado: str
    meses: float | None


@dataclass(frozen=True)
class OnuPendienteBaja:
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


class ClienteAnaliticaRepository:
    def __init__(self, sesion: Session) -> None:
        self._s = sesion

    def clientes_con_antiguedad(self, tipo_servicio: str = "fibra") -> list[ClienteAntiguedad]:
        """Altas y bajas con su permanencia en meses.

        La aritmética de fechas se resuelve en Python y no en SQL a propósito:
        `julianday()` es de SQLite y no existe en PostgreSQL. Dejarlo afuera del
        SQL hace que esta consulta sobreviva a la migración sin cambios.
        """
        filas = self._s.execute(
            select(
                Cliente.id, Cliente.nombre, Cliente.fecha_alta,
                Cliente.fecha_baja, Cliente.estado,
            ).where(
                Cliente.tipo_servicio == tipo_servicio,
                Cliente.fecha_alta.is_not(None),
                func.trim(Cliente.fecha_alta) != "",
            )
        ).all()

        out: list[ClienteAntiguedad] = []
        for cid, nombre, alta, baja, estado in filas:
            f_alta = _a_fecha(alta)
            if f_alta is None:
                continue
            f_baja = _a_fecha(baja)
            fin = f_baja or date.today()
            meses = round((fin - f_alta).days / 30.44, 1)
            out.append(ClienteAntiguedad(cid, nombre, f_alta, f_baja, estado or "", meses))
        return out

    def nombres(self, ids: list[int]) -> dict[int, str]:
        """id → nombre, para poner cara a los rankings de la analítica.

        El reclamo guarda `cliente_id` (no el nombre) a propósito: si el cliente
        se renombra, el histórico no debe quedar con el nombre viejo. La
        traducción a texto se hace acá, al momento de mostrar.
        """
        if not ids:
            return {}
        filas = self._s.execute(
            select(Cliente.id, Cliente.nombre).where(Cliente.id.in_(list(ids)))
        ).all()
        return {i: n for i, n in filas}

    def nombres_olts(self) -> dict[int, str]:
        return {i: n for i, n in self._s.execute(select(Olt.id, Olt.nombre)).all()}

    def onus_de_clientes_a_dar_de_baja(self) -> list[OnuPendienteBaja]:
        """ONU que siguen registradas en la OLT pero cuyo cliente ya no está activo.

        Incluye rescindidos Y pendientes de rescisión (fase 6). Es SÓLO LECTURA:
        arma el listado para revisar, no ejecuta ninguna baja en la OLT.
        """
        # COALESCE y no `or` en Python: hay clientes con fecha_rescision cargada
        # y fecha_baja vacía, y al revés. Se toma la que exista.
        fecha_estado = func.coalesce(Cliente.fecha_rescision, Cliente.fecha_baja)
        filas = self._s.execute(
            select(
                Cliente.id, Cliente.nombre, Cliente.nro_cliente, Cliente.estado,
                OnuSenal.olt_id, Olt.nombre, OnuSenal.pon, OnuSenal.onu,
                OnuSenal.serial_onu, fecha_estado,
                OnuSenal.online, OnuSenal.last_check,
            )
            .select_from(OnuSenal)
            .join(
                Cliente,
                func.trim(Cliente.nro_cliente) == func.trim(OnuSenal.nro_cliente),
            )
            .outerjoin(Olt, Olt.id == OnuSenal.olt_id)
            .where(Cliente.estado.in_(ESTADOS_A_DAR_DE_BAJA))
            .order_by(Cliente.nombre)
        ).all()

        out: list[OnuPendienteBaja] = []
        hoy = date.today()
        for f_ in filas:
            (cid, nombre, nro, estado, olt_id, olt_nombre, pon, onu,
             serial, fecha_est, online, last_check) = f_
            f = _a_fecha(fecha_est)
            out.append(
                OnuPendienteBaja(
                    cliente_id=cid, nombre=nombre, nro_cliente=nro,
                    estado_comercial=estado, olt_id=olt_id, olt_nombre=olt_nombre,
                    pon=pon, onu=onu, serial=serial,
                    fecha_estado=fecha_est,
                    dias_desde_cambio=(hoy - f).days if f else None,
                    online=bool(online), ultimo_chequeo=last_check,
                )
            )
        return out


def _a_fecha(valor) -> date | None:
    """Convierte a date lo que hoy viene como texto en la base heredada."""
    if not valor:
        return None
    if isinstance(valor, date):
        return valor
    texto = str(valor).strip()[:10]
    try:
        return date.fromisoformat(texto)
    except ValueError:
        return None
