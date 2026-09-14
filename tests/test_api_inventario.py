"""Pruebas de integración de la API de conciliación de inventario."""
from __future__ import annotations

import pytest
from flask import Flask
from sqlalchemy import insert
from sqlalchemy.orm import sessionmaker

import pucara.db as db
from pucara.api import seguridad
from pucara.models.legado import Cliente, Olt, OnuSenal, StockItem
from tests.motores import crear_esquema, motor


@pytest.fixture()
def cliente_http(tmp_path, monkeypatch):
    engine = motor(tmp_path)
    crear_esquema(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    monkeypatch.setattr(db, "_engine", engine)
    monkeypatch.setattr(db, "_Session", Session)
    monkeypatch.setattr(seguridad, "_autorizador", None)

    with Session() as s:
        s.execute(insert(Olt).values(id=1, nombre="Puerto Sánchez"))
        s.execute(insert(Cliente), [
            {"id": 1, "nombre": "Ana", "nro_cliente": "1001", "estado": "activo",
             "tipo_servicio": "fibra", "equipo_serie": "VSOL11111111"},
            {"id": 2, "nombre": "Beto", "nro_cliente": "1002", "estado": "activo",
             "tipo_servicio": "fibra", "equipo_serie": "VSOL22222222"},
        ])
        s.execute(insert(OnuSenal), [
            {"olt_id": 1, "pon": 1, "onu": 10, "serial_onu": "VSOL11111111",
             "nro_cliente": "1001", "online": 1},
            # Beto tiene puesta otra ONU de la que figura en su ficha.
            {"olt_id": 1, "pon": 1, "onu": 11, "serial_onu": "VSOL99999999",
             "nro_cliente": "1002", "online": 1},
        ])
        s.execute(insert(StockItem).values(
            id=1, serie="VSOL77777777", modelo="V2802", estado="instalado",
            cliente_id=5))
        s.commit()

    from pucara.api.inventario import bp

    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(bp)
    with app.test_client() as c:
        with c.session_transaction() as s:
            s["user_id"] = 1
            s["username"] = "eaguiar"
            s["rol"] = "admin"
        yield c


class TestConciliacion:
    def test_devuelve_los_hallazgos_y_el_resumen(self, cliente_http):
        d = cliente_http.get("/api/v2/inventario/conciliacion").get_json()
        assert d["vistos_en_la_red"] == 2
        assert d["coinciden"] == 1
        assert d["cobertura"] == 50.0
        assert d["por_categoria"] == {"difiere": 1, "no_visto": 1}

    def test_cada_hallazgo_dice_qué_hay_y_qué_debería_haber(self, cliente_http):
        d = cliente_http.get("/api/v2/inventario/conciliacion?categoria=difiere").get_json()
        h = d["hallazgos"][0]
        assert h["cliente_nombre"] == "Beto"
        assert h["registrado"] == "VSOL22222222"
        assert h["detectado"] == "VSOL99999999"
        assert h["severidad"] == "alta"

    def test_filtra_por_fuente(self, cliente_http):
        d = cliente_http.get("/api/v2/inventario/conciliacion?fuente=stock").get_json()
        assert [h["fuente"] for h in d["hallazgos"]] == ["stock"]

    def test_el_resumen_no_cambia_al_filtrar(self, cliente_http):
        """La cobertura tiene que ser comparable entre semanas; si dependiera
        del filtro que alguien dejó puesto, dejaría de medir nada."""
        entero = cliente_http.get("/api/v2/inventario/conciliacion").get_json()
        filtrado = cliente_http.get(
            "/api/v2/inventario/conciliacion?categoria=difiere").get_json()
        assert filtrado["cobertura"] == entero["cobertura"]
        assert filtrado["total_hallazgos"] == entero["total_hallazgos"]
        assert len(filtrado["hallazgos"]) == 1


class TestResumen:
    def test_devuelve_los_numeros_sin_la_lista(self, cliente_http):
        d = cliente_http.get("/api/v2/inventario/resumen").get_json()
        assert d["cobertura"] == 50.0 and "hallazgos" not in d


class TestSeguridad:
    @pytest.mark.parametrize("ruta", [
        "/api/v2/inventario/conciliacion", "/api/v2/inventario/resumen",
    ])
    def test_sin_sesion_no_se_expone_el_padron(self, cliente_http, ruta):
        """Estos endpoints listan clientes, seriales y MAC: no pueden quedar
        abiertos."""
        with cliente_http.session_transaction() as s:
            s.clear()
        assert cliente_http.get(ruta).status_code == 401
