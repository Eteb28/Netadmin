"""Pruebas de integración de la API de adjuntos de notas."""
from __future__ import annotations

import io

import pytest
from flask import Flask
from sqlalchemy import insert
from sqlalchemy.orm import sessionmaker

import pucara.db as db
import pucara.services.factory as factory
from pucara.almacen import AlmacenArchivos
from pucara.models.legado import TareaUsuario
from tests.motores import crear_esquema, motor

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40


@pytest.fixture()
def app_y_cliente(tmp_path, monkeypatch):
    engine = motor(tmp_path)
    crear_esquema(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    monkeypatch.setattr(db, "_engine", engine)
    monkeypatch.setattr(db, "_Session", Session)
    # El almacén apunta al tmp de la prueba, no a uploads/ del proyecto.
    monkeypatch.setattr(factory, "directorio_adjuntos", lambda: tmp_path / "adj")

    with Session() as s:
        s.execute(insert(TareaUsuario), [{"id": 1, "username": "ana"},
                                         {"id": 2, "username": "beto"}])
        s.commit()

    from pucara.api.adjuntos import bp

    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(bp)
    return app


def _sesion(app, usuario="ana", uid=1):
    c = app.test_client()
    with c.session_transaction() as s:
        s["user_id"] = uid
        s["username"] = usuario
        s["rol"] = "operador"
    return c


def _subir(c, tarea=1, datos=PNG, nombre="captura.png"):
    return c.post(f"/api/v2/tareas/{tarea}/adjuntos",
                  data={"imagen": (io.BytesIO(datos), nombre)},
                  content_type="multipart/form-data")


class TestFlujo:
    def test_subir_listar_descargar_y_borrar(self, app_y_cliente):
        c = _sesion(app_y_cliente)
        r = _subir(c)
        assert r.status_code == 201
        aid = r.get_json()["id"]

        assert len(c.get("/api/v2/tareas/1/adjuntos").get_json()) == 1

        d = c.get(f"/api/v2/adjuntos/{aid}")
        assert d.status_code == 200
        assert d.mimetype == "image/png"
        assert d.data == PNG
        # No debe quedar cacheada: es contenido privado
        assert "no-store" in d.headers["Cache-Control"]

        assert c.delete(f"/api/v2/adjuntos/{aid}").status_code == 200
        assert c.get("/api/v2/tareas/1/adjuntos").get_json() == []

    def test_consulta_por_lote(self, app_y_cliente):
        c = _sesion(app_y_cliente)
        _subir(c, tarea=1)
        r = c.post("/api/v2/adjuntos/consulta", json={"ids": [1, 2, 3]})
        assert list(r.get_json()) == ["1"]

    def test_ids_no_numericos_no_rompen_la_consulta(self, app_y_cliente):
        c = _sesion(app_y_cliente)
        r = c.post("/api/v2/adjuntos/consulta", json={"ids": ["1; DROP TABLE", None, "x"]})
        assert r.status_code == 200


class TestValidacion:
    def test_sin_archivo_da_400(self, app_y_cliente):
        c = _sesion(app_y_cliente)
        assert c.post("/api/v2/tareas/1/adjuntos", data={}).status_code == 400

    def test_archivo_que_no_es_imagen_da_400(self, app_y_cliente):
        c = _sesion(app_y_cliente)
        r = _subir(c, datos=b"<html><script>alert(1)</script>", nombre="x.png")
        assert r.status_code == 400
        assert "no es una imagen" in r.get_json()["error"]


class TestAislamientoEntreUsuarios:
    def test_no_se_puede_subir_a_la_nota_de_otro(self, app_y_cliente):
        c = _sesion(app_y_cliente, "ana")
        assert _subir(c, tarea=2).status_code == 404      # la nota 2 es de beto

    def test_no_se_puede_descargar_el_adjunto_de_otro(self, app_y_cliente):
        aid = _subir(_sesion(app_y_cliente, "ana"), tarea=1).get_json()["id"]
        otro = _sesion(app_y_cliente, "beto", uid=2)
        assert otro.get(f"/api/v2/adjuntos/{aid}").status_code == 404

    def test_no_se_puede_borrar_el_adjunto_de_otro(self, app_y_cliente):
        aid = _subir(_sesion(app_y_cliente, "ana"), tarea=1).get_json()["id"]
        otro = _sesion(app_y_cliente, "beto", uid=2)
        assert otro.delete(f"/api/v2/adjuntos/{aid}").status_code == 404
        assert len(_sesion(app_y_cliente, "ana").get("/api/v2/tareas/1/adjuntos").get_json()) == 1


class TestSesion:
    @pytest.mark.parametrize("metodo,ruta", [
        ("get", "/api/v2/tareas/1/adjuntos"),
        ("post", "/api/v2/tareas/1/adjuntos"),
        ("get", "/api/v2/adjuntos/1"),
        ("delete", "/api/v2/adjuntos/1"),
        ("post", "/api/v2/adjuntos/consulta"),
    ])
    def test_sin_sesion_da_401(self, app_y_cliente, metodo, ruta):
        c = app_y_cliente.test_client()
        assert getattr(c, metodo)(ruta).status_code == 401
