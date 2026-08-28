"""API de los adjuntos de las notas de "Mis Tareas".

Protegido con `modulo=None`: alcanza con tener sesión, porque las notas son
personales y **el servicio verifica la pertenencia en cada operación**, incluida
la descarga. No hay un permiso por módulo que agregue nada acá.
"""
from __future__ import annotations

from dataclasses import asdict

from flask import Blueprint, jsonify, request, send_file, session

from pucara.api.seguridad import proteger
from pucara.db import sesion
from pucara.services import factory
from pucara.services.adjuntos import ErrorAdjunto, NoAutorizado

bp = Blueprint("adjuntos_api", __name__, url_prefix="/api/v2")
proteger(bp, None)


def _usuario() -> str:
    return session.get("username") or ""


@bp.errorhandler(ErrorAdjunto)
def _error_negocio(e: ErrorAdjunto):
    return jsonify({"error": str(e)}), 400


@bp.errorhandler(NoAutorizado)
def _no_autorizado(e: NoAutorizado):
    """404 y no 403: un 403 confirmaría que el recurso existe y es de otro."""
    return jsonify({"error": str(e)}), 404


@bp.get("/tareas/<int:tarea_id>/adjuntos")
def listar(tarea_id: int):
    with sesion() as s:
        items = factory.servicio_adjuntos(s).listar(tarea_id, _usuario())
        return jsonify([asdict(a) for a in items])


@bp.post("/tareas/<int:tarea_id>/adjuntos")
def subir(tarea_id: int):
    archivo = request.files.get("imagen")
    if archivo is None:
        return jsonify({"error": "Falta el archivo 'imagen'"}), 400
    datos = archivo.read()
    with sesion() as s:
        a = factory.servicio_adjuntos(s).guardar(
            tarea_id, _usuario(), datos, archivo.filename
        )
        return jsonify(asdict(a)), 201


@bp.get("/adjuntos/<int:adjunto_id>")
def descargar(adjunto_id: int):
    with sesion() as s:
        ruta, mime = factory.servicio_adjuntos(s).leer(adjunto_id, _usuario())
    # El mimetype sale de la detección por bytes que hizo el servicio, nunca de
    # lo que declaró quien subió el archivo. Con el `X-Content-Type-Options:
    # nosniff` global, el navegador no puede reinterpretarlo como otra cosa.
    resp = send_file(ruta, mimetype=mime, max_age=0)
    resp.headers["Cache-Control"] = "private, no-store"
    resp.headers["Content-Disposition"] = "inline"
    return resp


@bp.delete("/adjuntos/<int:adjunto_id>")
def borrar(adjunto_id: int):
    with sesion() as s:
        factory.servicio_adjuntos(s).borrar(adjunto_id, _usuario())
        return jsonify({"ok": True})


@bp.post("/adjuntos/consulta")
def listar_lote():
    """Adjuntos de varias notas en una sola llamada.

    El tablero pinta N post-its; pedirlos de a uno serían N peticiones. Es POST
    y no GET porque la lista de ids puede ser larga para una query string.
    """
    ids = (request.get_json(silent=True) or {}).get("ids") or []
    ids = [int(x) for x in ids if str(x).isdigit()][:200]
    with sesion() as s:
        por_tarea = factory.servicio_adjuntos(s).listar_por_tarea(ids, _usuario())
        return jsonify({
            str(tid): [asdict(a) for a in lista] for tid, lista in por_tarea.items()
        })
