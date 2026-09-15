"""API de ubicación de NAPs.

Endpoint acotado a mover el marcador. No reemplaza al `PUT /api/naps/<id>`
heredado, que sigue siendo el que edita la ficha completa: acá sólo se tocan
`lat` y `lng`, para que arrastrar un pin en el mapa no pueda borrar el resto.
"""
from __future__ import annotations

from dataclasses import asdict

from flask import Blueprint, jsonify, request, session

from pucara.api.seguridad import proteger
from pucara.db import sesion
from pucara.services import factory
from pucara.services.ubicaciones import ErrorUbicacion, NapInexistente

bp = Blueprint("naps_api", __name__, url_prefix="/api/v2/naps")
proteger(bp, "naps", "editar")


@bp.errorhandler(ErrorUbicacion)
def _error_negocio(e: ErrorUbicacion):
    return jsonify({"error": str(e)}), 400


@bp.errorhandler(NapInexistente)
def _no_existe(e: NapInexistente):
    return jsonify({"error": str(e)}), 404


@bp.put("/<int:nap_id>/ubicacion")
def mover(nap_id: int):
    d = request.get_json(silent=True) or {}
    with sesion() as s:
        m = factory.servicio_ubicacion_naps(s).mover(
            nap_id, d.get("lat"), d.get("lng"),
            usuario=session.get("username") or "sistema",
        )
        return jsonify({"ok": True, **asdict(m)})
