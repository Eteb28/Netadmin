"""API de salud óptica: ONU degradándose y puertos GPON saturados.

Acciones 2.2 y 2.3 del «06 — Plan de Mejora de Pucará». Sólo lectura: no cambia
nada en la red, informa qué está por romperse.
"""
from __future__ import annotations

from dataclasses import asdict

from flask import Blueprint, jsonify, request

from pucara.api.seguridad import proteger
from pucara.db import sesion
from pucara.services import factory

bp = Blueprint("optica_api", __name__, url_prefix="/api/v2/optica")
proteger(bp, "monitoreo")


@bp.get("/salud")
def salud():
    dias = request.args.get("dias", type=int, default=30)
    severidad = request.args.get("severidad")
    with sesion() as s:
        r = factory.servicio_degradacion(s).analizar(dias)
        items = r.en_riesgo
        if severidad:
            items = [x for x in items if x.severidad == severidad]
        d = asdict(r)
        d["en_riesgo"] = [asdict(x) | {"ubicacion": x.ubicacion} for x in items]
        d["pones"] = [asdict(p) | {"ubicacion": p.ubicacion} for p in r.pones]
        return jsonify(d)
