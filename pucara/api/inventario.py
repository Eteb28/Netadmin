"""API de conciliación de inventario.

Qué equipos existen de verdad según la red, cuáles figuran en el papel y ya no
están, y cuáles funcionan sin figurar. SÓLO LECTURA: informa, no corrige.
"""
from __future__ import annotations

from dataclasses import asdict

from flask import Blueprint, jsonify, request

from pucara.api.seguridad import proteger
from pucara.db import sesion
from pucara.services import factory

bp = Blueprint("inventario_api", __name__, url_prefix="/api/v2/inventario")
proteger(bp, "stock")


@bp.get("/conciliacion")
def conciliacion():
    """Cuadro de situación del registro contra lo que la red reporta.

    Filtros opcionales: `categoria`, `fuente`, `severidad`. El resumen se
    calcula sobre TODO y no sobre lo filtrado — si no, la cobertura cambiaría
    según lo que se está mirando y dejaría de ser comparable entre semanas.
    """
    categoria = request.args.get("categoria")
    fuente = request.args.get("fuente")
    severidad = request.args.get("severidad")

    with sesion() as s:
        r = factory.servicio_inventario(s).analizar()
        items = r.hallazgos
        if categoria:
            items = [h for h in items if h.categoria == categoria]
        if fuente:
            items = [h for h in items if h.fuente == fuente]
        if severidad:
            items = [h for h in items if h.severidad == severidad]
        return jsonify({
            "vistos_en_la_red": r.vistos_en_la_red,
            "coinciden": r.coinciden,
            "cobertura": r.cobertura,
            "esperados_sin_servicio": r.esperados_sin_servicio,
            "total_hallazgos": len(r.hallazgos),
            "por_categoria": r.por_categoria,
            "hallazgos": [asdict(h) for h in items],
        })


@bp.get("/resumen")
def resumen():
    """Sólo los números, sin la lista. Para el tablero."""
    with sesion() as s:
        r = factory.servicio_inventario(s).analizar()
        return jsonify({
            "vistos_en_la_red": r.vistos_en_la_red,
            "coinciden": r.coinciden,
            "cobertura": r.cobertura,
            "esperados_sin_servicio": r.esperados_sin_servicio,
            "total_hallazgos": len(r.hallazgos),
            "por_categoria": r.por_categoria,
        })
