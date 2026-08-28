"""Punto de ensamblado (composition root).

Único lugar donde se sabe qué repositorio concreto usa cada servicio. La capa
API pide servicios acá y nunca importa repositorios: así puede cambiarse la
implementación de persistencia (por ejemplo al migrar a PostgreSQL en la fase 7)
sin tocar un solo controlador.
"""
from __future__ import annotations

import os
import pathlib

from sqlalchemy.orm import Session

from pucara.almacen import AlmacenArchivos
from pucara.repositories.adjuntos import AdjuntoRepository, TareaLegadaRepository
from pucara.repositories.auditoria import AuditoriaRepository
from pucara.repositories.clientes import ClienteAnaliticaRepository
from pucara.repositories.incidentes import IncidenteRepository
from pucara.repositories.naps import NapRepository
from pucara.repositories.optica import OpticaRepository
from pucara.repositories.reclamos import (
    CausaRepository, ReclamoRepository, ResolucionRepository,
)
from pucara.services.adjuntos import ServicioAdjuntos
from pucara.services.antiguedad import ServicioAntiguedad
from pucara.services.degradacion import ServicioDegradacion
from pucara.services.incidentes import ConfiguracionMotor, MotorIncidentes
from pucara.services.reclamos import ServicioAnaliticaReclamos, ServicioReclamos
from pucara.services.rescisiones import ServicioRescisiones
from pucara.services.ubicaciones import ServicioUbicacionNap


def servicio_reclamos(s: Session) -> ServicioReclamos:
    return ServicioReclamos(ReclamoRepository(s), CausaRepository(s), ResolucionRepository(s))


def servicio_analitica(s: Session) -> ServicioAnaliticaReclamos:
    # El segundo repositorio sólo resuelve nombres (cliente, OLT) para los
    # rankings; el servicio funciona sin él, pero mostraría ids.
    return ServicioAnaliticaReclamos(ReclamoRepository(s), ClienteAnaliticaRepository(s))


def servicio_antiguedad(s: Session) -> ServicioAntiguedad:
    return ServicioAntiguedad(ClienteAnaliticaRepository(s))


def servicio_rescisiones(s: Session) -> ServicioRescisiones:
    return ServicioRescisiones(ClienteAnaliticaRepository(s))


def servicio_degradacion(s: Session) -> ServicioDegradacion:
    return ServicioDegradacion(OpticaRepository(s))


def servicio_ubicacion_naps(s: Session) -> ServicioUbicacionNap:
    return ServicioUbicacionNap(NapRepository(s), AuditoriaRepository(s))


def motor_incidentes(s: Session, config: ConfiguracionMotor | None = None) -> MotorIncidentes:
    return MotorIncidentes(IncidenteRepository(s), config)


def directorio_adjuntos() -> pathlib.Path:
    """Dónde viven las imágenes de las notas.

    Configurable por `PUCARA_UPLOADS`; por defecto `uploads/tareas` al lado del
    proyecto, que es donde ya guarda archivos el sistema actual.
    """
    base = os.environ.get("PUCARA_UPLOADS")
    if base:
        return pathlib.Path(base) / "tareas"
    return pathlib.Path(__file__).resolve().parent.parent.parent / "uploads" / "tareas"


def servicio_adjuntos(s: Session, almacen: AlmacenArchivos | None = None) -> ServicioAdjuntos:
    return ServicioAdjuntos(
        AdjuntoRepository(s),
        TareaLegadaRepository(s),
        almacen or AlmacenArchivos(directorio_adjuntos()),
    )


def catalogo_causas(s: Session) -> CausaRepository:
    """Los catálogos se exponen tal cual: son ABM puro, sin lógica de negocio
    que justifique un servicio intermedio que sólo reenvíe llamadas."""
    return CausaRepository(s)


def catalogo_resoluciones(s: Session) -> ResolucionRepository:
    return ResolucionRepository(s)
