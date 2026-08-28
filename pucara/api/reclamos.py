"""API HTTP del dominio Reclamos.

Capa Controller: valida entrada, arma los servicios y traduce a JSON.
No contiene lógica de negocio ni acceso a datos (ADR-0001).
"""
from __future__ import annotations

from dataclasses import asdict

from flask import Blueprint, jsonify, request, session

from pucara.api.seguridad import proteger
from pucara.db import sesion
from pucara.services import factory
from pucara.services.reclamos import ErrorReclamo

bp = Blueprint("reclamos_api", __name__, url_prefix="/api/v2/reclamos")
proteger(bp, "reclamos")


def _servicio(s):
    """El ensamblado vive en services.factory: la API no conoce repositorios."""
    return factory.servicio_reclamos(s)


def _usuario() -> str:
    return session.get("username") or "sistema"


@bp.errorhandler(ErrorReclamo)
def _error_negocio(e: ErrorReclamo):
    """Un error de negocio es 400, no 500: la petición fue inválida."""
    return jsonify({"error": str(e)}), 400


# ── reclamos ─────────────────────────────────────────────────────────────
@bp.get("/cliente/<int:cliente_id>")
def historial_cliente(cliente_id: int):
    with sesion() as s:
        return jsonify([asdict(r) for r in _servicio(s).historial(cliente_id)])


@bp.get("/cliente/<int:cliente_id>/estadisticas")
def estadisticas_cliente(cliente_id: int):
    with sesion() as s:
        e = _servicio(s).estadisticas_cliente(cliente_id)
        return jsonify(asdict(e))


@bp.post("")
def registrar():
    d = request.get_json(silent=True) or {}
    if not d.get("cliente_id"):
        return jsonify({"error": "Falta cliente_id"}), 400
    with sesion() as s:
        r = _servicio(s).registrar(
            cliente_id=int(d["cliente_id"]),
            usuario=_usuario(),
            causa_id=d.get("causa_id"),
            observaciones=d.get("observaciones"),
            tecnico=d.get("tecnico"),
            contexto_red=d.get("contexto_red"),
        )
        return jsonify(asdict(r)), 201


@bp.post("/<int:reclamo_id>/cerrar")
def cerrar(reclamo_id: int):
    d = request.get_json(silent=True) or {}
    with sesion() as s:
        r = _servicio(s).cerrar(
            reclamo_id, usuario=_usuario(),
            resolucion_id=d.get("resolucion_id"),
            observaciones=d.get("observaciones"),
        )
        return jsonify(asdict(r))


# ── catálogos administrables ─────────────────────────────────────────────
@bp.get("/catalogos")
def catalogos():
    incluir = request.args.get("incluir_inactivos") == "1"
    with sesion() as s:
        return jsonify({
            "causas": [
                {"id": c.id, "nombre": c.nombre, "activo": c.activo}
                for c in factory.catalogo_causas(s).listar(incluir)
            ],
            "resoluciones": [
                {"id": r.id, "nombre": r.nombre, "activo": r.activo}
                for r in factory.catalogo_resoluciones(s).listar(incluir)
            ],
        })


@bp.post("/catalogos/<tipo>")
def crear_catalogo(tipo: str):
    if tipo not in ("causas", "resoluciones"):
        return jsonify({"error": "Tipo inválido"}), 400
    d = request.get_json(silent=True) or {}
    nombre = (d.get("nombre") or "").strip()
    if not nombre:
        return jsonify({"error": "Falta el nombre"}), 400
    with sesion() as s:
        repo = factory.catalogo_causas(s) if tipo == "causas" else factory.catalogo_resoluciones(s)
        if repo.buscar_por_nombre(nombre):
            return jsonify({"error": f"Ya existe '{nombre}'"}), 409
        obj = repo.crear(nombre, d.get("descripcion"), int(d.get("orden") or 0))
        return jsonify({"id": obj.id, "nombre": obj.nombre}), 201


@bp.delete("/catalogos/<tipo>/<int:id_>")
def desactivar_catalogo(tipo: str, id_: int):
    """Baja LÓGICA: los reclamos históricos siguen mostrando su causa."""
    if tipo not in ("causas", "resoluciones"):
        return jsonify({"error": "Tipo inválido"}), 400
    with sesion() as s:
        repo = factory.catalogo_causas(s) if tipo == "causas" else factory.catalogo_resoluciones(s)
        if not repo.desactivar(id_):
            return jsonify({"error": "No existe"}), 404
        return jsonify({"ok": True})


# ── analítica ────────────────────────────────────────────────────────────
@bp.get("/analitica")
def analitica():
    dias = request.args.get("dias", type=int, default=90)
    with sesion() as s:
        return jsonify(factory.servicio_analitica(s).resumen(dias))
