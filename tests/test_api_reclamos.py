"""Pruebas de integración de la API de Reclamos."""
from __future__ import annotations

import pytest
from flask import Flask
from sqlalchemy import insert
from sqlalchemy.orm import sessionmaker

import pucara.db as db
from pucara.models.legado import Cliente, Olt
from tests.motores import crear_esquema, motor


@pytest.fixture()
def cliente_http(tmp_path, monkeypatch):
    """App Flask mínima con la base apuntando a un archivo temporal."""
    engine = motor(tmp_path)
    crear_esquema(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    monkeypatch.setattr(db, "_engine", engine)
    monkeypatch.setattr(db, "_Session", Session)

    # La analítica resuelve nombres contra las tablas heredadas: en producción
    # siempre existen, así que la prueba las reproduce en vez de esconderlas.
    with Session() as s:
        s.execute(insert(Cliente).values(id=10, nombre="Ana Pérez"))
        s.execute(insert(Olt).values(id=1, nombre="OLT Crespo"))
        s.commit()

    from pucara.api.reclamos import bp

    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(bp)
    with app.test_client() as c:
        with c.session_transaction() as s:
            s["username"] = "admin"
            s["user_id"] = 1
            s["rol"] = "admin"
        yield c


class TestFlujoCompleto:
    def test_alta_cierre_y_estadisticas(self, cliente_http):
        # catálogo
        r = cliente_http.post("/api/v2/reclamos/catalogos/causas", json={"nombre": "Sin servicio"})
        assert r.status_code == 201
        causa_id = r.get_json()["id"]

        # alta
        r = cliente_http.post("/api/v2/reclamos", json={"cliente_id": 10, "causa_id": causa_id})
        assert r.status_code == 201
        reclamo = r.get_json()
        assert reclamo["estado"] == "abierto"
        assert reclamo["usuario_alta"] == "admin"      # sale de la sesión

        # cierre
        r = cliente_http.post(f"/api/v2/reclamos/{reclamo['id']}/cerrar", json={})
        assert r.status_code == 200
        assert r.get_json()["estado"] == "cerrado"

        # estadísticas
        r = cliente_http.get("/api/v2/reclamos/cliente/10/estadisticas")
        e = r.get_json()
        assert e["total"] == 1 and e["abiertos"] == 0

    def test_historial_vacio(self, cliente_http):
        assert cliente_http.get("/api/v2/reclamos/cliente/999").get_json() == []


class TestValidaciones:
    def test_falta_cliente_id(self, cliente_http):
        r = cliente_http.post("/api/v2/reclamos", json={})
        assert r.status_code == 400

    def test_causa_inexistente_da_400_no_500(self, cliente_http):
        """Un error de negocio es 400: la petición era inválida, no falló el servidor."""
        r = cliente_http.post("/api/v2/reclamos", json={"cliente_id": 1, "causa_id": 9999})
        assert r.status_code == 400
        assert "no existe" in r.get_json()["error"]

    def test_catalogo_duplicado_da_409(self, cliente_http):
        cliente_http.post("/api/v2/reclamos/catalogos/causas", json={"nombre": "Lentitud"})
        r = cliente_http.post("/api/v2/reclamos/catalogos/causas", json={"nombre": "Lentitud"})
        assert r.status_code == 409

    def test_tipo_de_catalogo_invalido(self, cliente_http):
        r = cliente_http.post("/api/v2/reclamos/catalogos/inventado", json={"nombre": "X"})
        assert r.status_code == 400


class TestCatalogos:
    def test_la_baja_logica_lo_saca_del_listado(self, cliente_http):
        r = cliente_http.post("/api/v2/reclamos/catalogos/causas", json={"nombre": "Router"})
        cid = r.get_json()["id"]
        cliente_http.delete(f"/api/v2/reclamos/catalogos/causas/{cid}")

        activos = cliente_http.get("/api/v2/reclamos/catalogos").get_json()["causas"]
        assert cid not in [c["id"] for c in activos]

        todos = cliente_http.get("/api/v2/reclamos/catalogos?incluir_inactivos=1").get_json()
        assert cid in [c["id"] for c in todos["causas"]]


class TestAnalitica:
    def test_resumen_responde_con_las_secciones_esperadas(self, cliente_http):
        r = cliente_http.get("/api/v2/reclamos/analitica?dias=30")
        d = r.get_json()
        for clave in ("mttr_minutos", "por_causa", "top_clientes", "top_aps", "top_pon", "tecnicos"):
            assert clave in d

    def test_los_rankings_muestran_nombres_y_no_ids(self, cliente_http):
        """Un listado de 'Cliente 10, Cliente 37' es inútil para quien lo mira."""
        cliente_http.post("/api/v2/reclamos", json={"cliente_id": 10})
        top = cliente_http.get("/api/v2/reclamos/analitica").get_json()["top_clientes"]
        assert top[0]["nombre"] == "Ana Pérez"
        assert top[0]["id"] == 10          # el id sigue estando, para enlazar la ficha

    def test_cliente_borrado_no_rompe_el_ranking(self, cliente_http):
        """Si el reclamo apunta a un cliente que ya no está, cae al id."""
        cliente_http.post("/api/v2/reclamos", json={"cliente_id": 999})
        top = cliente_http.get("/api/v2/reclamos/analitica").get_json()["top_clientes"]
        assert top[0]["nombre"] == "Cliente #999"
