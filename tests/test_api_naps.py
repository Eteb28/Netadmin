"""Pruebas de integración del endpoint de reubicación de NAPs."""
from __future__ import annotations

import pytest
from flask import Flask
from sqlalchemy import insert, text
from sqlalchemy.orm import sessionmaker

import pucara.db as db
from pucara.api import seguridad
from pucara.models.legado import Nap
from tests.motores import crear_esquema, motor

PARANA = {"lat": -31.7346, "lng": -60.5289}


@pytest.fixture()
def app_naps(tmp_path, monkeypatch):
    engine = motor(tmp_path)
    crear_esquema(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    monkeypatch.setattr(db, "_engine", engine)
    monkeypatch.setattr(db, "_Session", Session)
    monkeypatch.setattr(seguridad, "_autorizador", None)

    with Session() as s:
        s.execute(insert(Nap).values(
            id=1, nombre="PROCREAR - CDO 21 - NAP 6", lat=-31.70, lng=-60.50))
        s.commit()

    from pucara.api.naps import bp

    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(bp)
    return app


def _cliente(app, rol="admin"):
    c = app.test_client()
    with c.session_transaction() as s:
        s["user_id"] = 1
        s["username"] = "eaguiar"
        s["rol"] = rol
    return c


class TestMover:
    def test_mueve_y_devuelve_el_movimiento(self, app_naps):
        r = _cliente(app_naps).put("/api/v2/naps/1/ubicacion", json=PARANA)
        assert r.status_code == 200
        d = r.get_json()
        assert d["ok"] is True
        assert d["lat"] == pytest.approx(PARANA["lat"])
        assert d["lat_anterior"] == pytest.approx(-31.70)
        assert d["metros_movidos"] > 0
        assert d["fuera_de_zona"] is False

    def test_persiste(self, app_naps):
        c = _cliente(app_naps)
        c.put("/api/v2/naps/1/ubicacion", json=PARANA)
        assert c.put("/api/v2/naps/1/ubicacion", json=PARANA).get_json()["metros_movidos"] == 0

    def test_deja_constancia_en_el_historial(self, app_naps):
        _cliente(app_naps).put("/api/v2/naps/1/ubicacion", json=PARANA)
        from pucara.db import sesion
        with sesion() as s:
            fila = s.execute(text(
                "SELECT usuario, modulo, titulo FROM historial ORDER BY id DESC LIMIT 1")).first()
        assert fila[0] == "eaguiar" and fila[1] == "naps"
        assert "coordenadas corregidas" in fila[2]

    def test_avisa_si_quedo_fuera_de_zona(self, app_naps):
        r = _cliente(app_naps).put("/api/v2/naps/1/ubicacion",
                                   json={"lat": -60.5289, "lng": -31.7346})
        assert r.get_json()["fuera_de_zona"] is True


class TestErrores:
    def test_coordenada_invalida_da_400(self, app_naps):
        r = _cliente(app_naps).put("/api/v2/naps/1/ubicacion", json={"lat": 500, "lng": 0})
        assert r.status_code == 400
        assert "rango" in r.get_json()["error"]

    def test_cuerpo_vacio_da_400_no_500(self, app_naps):
        assert _cliente(app_naps).put("/api/v2/naps/1/ubicacion", json={}).status_code == 400

    def test_nap_inexistente_da_404(self, app_naps):
        r = _cliente(app_naps).put("/api/v2/naps/999/ubicacion", json=PARANA)
        assert r.status_code == 404


class TestPermisos:
    def test_sin_sesion_da_401(self, app_naps):
        assert app_naps.test_client().put("/api/v2/naps/1/ubicacion", json=PARANA).status_code == 401

    def test_sin_permiso_de_edicion_da_403(self, app_naps, monkeypatch):
        monkeypatch.setattr(seguridad, "_autorizador", lambda uid, rol, mod, acc: False)
        c = _cliente(app_naps, rol="operador")
        assert c.put("/api/v2/naps/1/ubicacion", json=PARANA).status_code == 403

    def test_el_autorizador_recibe_modulo_y_accion(self, app_naps, monkeypatch):
        """Mover una NAP es editar: no alcanza con poder ver el módulo."""
        visto = {}
        def _espia(uid, rol, mod, acc):
            visto.update(modulo=mod, accion=acc)
            return True
        monkeypatch.setattr(seguridad, "_autorizador", _espia)
        _cliente(app_naps, rol="operador").put("/api/v2/naps/1/ubicacion", json=PARANA)
        assert visto == {"modulo": "naps", "accion": "editar"}

    def test_no_hay_otros_verbos(self, app_naps):
        """El endpoint sólo mueve: no borra ni crea NAPs."""
        c = _cliente(app_naps)
        for verbo in ("post", "delete", "get"):
            assert getattr(c, verbo)("/api/v2/naps/1/ubicacion").status_code == 405
