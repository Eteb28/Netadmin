"""Las rutas /api/v2 no pueden quedar abiertas.

Los blueprints nuevos no usan los decoradores de app.py: usan `proteger()`. Esta
prueba verifica que la protección efectivamente actúa, y que no depende de que
alguien se acuerde de decorar cada ruta nueva.
"""
from __future__ import annotations

import pathlib
import re

import pytest
from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import pucara.db as db
from pucara.api import seguridad
from pucara.db import Base
from pucara.models import adjuntos, incidentes, reclamos  # noqa: F401

API = pathlib.Path(__file__).resolve().parent.parent / "pucara" / "api"


@pytest.fixture()
def app_v2(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path/'t.db'}", future=True)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(db, "_engine", engine)
    monkeypatch.setattr(db, "_Session", sessionmaker(bind=engine, future=True))
    monkeypatch.setattr(seguridad, "_autorizador", None)

    from pucara.api.analitica import bp as bp_a
    from pucara.api.analitica import bp_rescisiones as bp_res
    from pucara.api.reclamos import bp as bp_r

    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(bp_r)
    app.register_blueprint(bp_a)
    app.register_blueprint(bp_res)
    return app


RUTAS = [
    "/api/v2/reclamos/catalogos",
    "/api/v2/reclamos/cliente/1",
    "/api/v2/reclamos/analitica",
    "/api/v2/antiguedad",
    "/api/v2/pendientes-rescision",
]


@pytest.mark.parametrize("ruta", RUTAS)
def test_sin_sesion_da_401(app_v2, ruta):
    assert app_v2.test_client().get(ruta).status_code == 401


def test_escribir_sin_sesion_tambien_da_401(app_v2):
    r = app_v2.test_client().post("/api/v2/reclamos", json={"cliente_id": 1})
    assert r.status_code == 401


def test_usuario_sin_el_modulo_da_403(app_v2, monkeypatch):
    """Con autorizador registrado, un usuario común sin el módulo no entra."""
    monkeypatch.setattr(seguridad, "_autorizador", lambda uid, rol, mod, acc: False)
    c = app_v2.test_client()
    with c.session_transaction() as s:
        s["user_id"] = 7
        s["rol"] = "operador"
    assert c.get("/api/v2/reclamos/catalogos").status_code == 403


def test_admin_pasa_aunque_el_autorizador_diga_que_no(app_v2, monkeypatch):
    monkeypatch.setattr(seguridad, "_autorizador", lambda *a: False)
    c = app_v2.test_client()
    with c.session_transaction() as s:
        s["user_id"] = 1
        s["rol"] = "admin"
    assert c.get("/api/v2/reclamos/catalogos").status_code == 200


def test_todo_blueprint_nuevo_declara_su_proteccion():
    """Crear un archivo en pucara/api/ sin llamar a proteger() deja rutas
    abiertas. Que falle acá y no en producción."""
    sin_proteger = [
        p.name for p in API.glob("*.py")
        if p.name not in ("__init__.py", "seguridad.py")
        and re.search(r"Blueprint\(", p.read_text(encoding="utf-8"))
        and "proteger(" not in p.read_text(encoding="utf-8")
    ]
    assert not sin_proteger, f"Blueprints sin proteger(): {sin_proteger}"
