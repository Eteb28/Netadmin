"""API de antigüedad/churn (fase 5) y pendientes de rescisión (fase 6).

Son dos blueprints y no uno porque los consumen pantallas distintas y por lo
tanto los protege un módulo de permisos distinto: la antigüedad es información
comercial de la cartera; los pendientes de rescisión se miran desde el panel de
alertas de ONU, que es operación de red.

Fase 6 es SÓLO LECTURA: no hay ninguna ruta de escritura acá, a propósito.
"""
from __future__ import annotations

from dataclasses import asdict

from flask import Blueprint, jsonify, request

from pucara.api.seguridad import proteger
from pucara.db import sesion
from pucara.services import factory

bp = Blueprint("antiguedad_api", __name__, url_prefix="/api/v2")
proteger(bp, "antiguedad")

bp_rescisiones = Blueprint("rescisiones_api", __name__, url_prefix="/api/v2")
proteger(bp_rescisiones, "monitoreo")


@bp.get("/antiguedad")
def antiguedad():
    tipo = request.args.get("tipo_servicio", "fibra")
    with sesion() as s:
        return jsonify(asdict(factory.servicio_antiguedad(s).calcular(tipo)))


@bp_rescisiones.get("/pendientes-rescision")
def pendientes_rescision():
    """ONU todavía registradas en la OLT de clientes que ya no están activos.

    Devuelve el listado para revisión manual. La baja en la OLT NO se hace desde
    acá (decisión del alcance de la fase 6).
    """
    with sesion() as s:
        srv = factory.servicio_rescisiones(s)
        filas = srv.listar(
            estado=request.args.get("estado") or None,
            olt_id=request.args.get("olt_id", type=int),
            dias_minimos=request.args.get("dias_minimos", type=int),
        )
        return jsonify({
            "solo_lectura": True,
            "resumen": asdict(srv.resumen(filas)),
            "items": [asdict(f) for f in filas],
        })
