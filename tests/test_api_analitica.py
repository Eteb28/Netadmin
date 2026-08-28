"""Pruebas de integración de la API de antigüedad (fase 5) y rescisiones (fase 6)."""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from flask import Flask
from sqlalchemy import insert
from sqlalchemy.orm import sessionmaker

import pucara.db as db
from pucara.models.legado import Cliente, Olt, OnuSenal
from tests.motores import crear_esquema, motor


@pytest.fixture()
def cliente_http(tmp_path, monkeypatch):
    engine = motor(tmp_path)
    crear_esquema(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    monkeypatch.setattr(db, "_engine", engine)
    monkeypatch.setattr(db, "_Session", Session)

    hace_100 = (date.today() - timedelta(days=100)).isoformat()
    with Session() as s:
        s.execute(insert(Olt).values(id=1, nombre="OLT Centro"))
        s.execute(insert(Cliente), [
            {"id": 1, "nombre": "Ana", "nro_cliente": "1001", "estado": "rescision",
             "tipo_servicio": "fibra", "fecha_alta": "2022-01-01",
             "fecha_rescision": hace_100},
            {"id": 2, "nombre": "Beto", "nro_cliente": "1002", "estado": "pte_rescision",
             "tipo_servicio": "fibra", "fecha_alta": "2023-01-01",
             "fecha_rescision": None},
            {"id": 3, "nombre": "Cora", "nro_cliente": "1003", "estado": "activo",
             "tipo_servicio": "fibra", "fecha_alta": "2024-01-01",
             "fecha_rescision": None},
        ])
        s.execute(insert(OnuSenal), [
            {"olt_id": 1, "pon": 1, "onu": 10, "nro_cliente": "1001", "serial_onu": "SN1",
             "online": 1},
            {"olt_id": 1, "pon": 2, "onu": 11, "nro_cliente": "1002", "serial_onu": "SN2",
             "online": 1},
            {"olt_id": 1, "pon": 3, "onu": 12, "nro_cliente": "1003", "serial_onu": "SN3",
             "online": 1},
        ])
        s.commit()

    from pucara.api.analitica import bp, bp_rescisiones

    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(bp)
    app.register_blueprint(bp_rescisiones)
    with app.test_client() as c:
        with c.session_transaction() as s:
            s["user_id"] = 1
            s["rol"] = "admin"
        yield c


class TestAntiguedad:
    def test_devuelve_los_kpi_esperados(self, cliente_http):
        d = cliente_http.get("/api/v2/antiguedad").get_json()
        for clave in ("total_activos", "total_bajas", "permanencia_media_meses",
                      "distribucion_activos", "altas_por_mes", "churn_mensual",
                      "churn_anual"):
            assert clave in d
        assert d["total_activos"] == 2      # activo + pte_rescision (todavía no es baja)
        assert d["total_bajas"] == 1

    def test_tipo_de_servicio_inexistente_da_ceros_no_error(self, cliente_http):
        d = cliente_http.get("/api/v2/antiguedad?tipo_servicio=satelital").get_json()
        assert d["total_activos"] == 0


class TestPendientesRescision:
    def test_lista_con_resumen(self, cliente_http):
        d = cliente_http.get("/api/v2/pendientes-rescision").get_json()
        assert d["solo_lectura"] is True
        assert d["resumen"]["total"] == 2
        assert {i["nro_cliente"] for i in d["items"]} == {"1001", "1002"}
        assert d["items"][0]["ubicacion"].startswith("OLT Centro")

    def test_filtros(self, cliente_http):
        d = cliente_http.get("/api/v2/pendientes-rescision?estado=pte_rescision").get_json()
        assert d["resumen"]["total"] == 1
        d = cliente_http.get("/api/v2/pendientes-rescision?dias_minimos=90").get_json()
        assert d["resumen"]["total"] == 1      # sólo Ana, con 100 días

    def test_no_existe_ninguna_ruta_de_escritura(self, cliente_http):
        """La fase 6 es sólo listar: cualquier verbo de escritura debe dar 405."""
        for verbo in ("post", "delete", "put"):
            r = getattr(cliente_http, verbo)("/api/v2/pendientes-rescision")
            assert r.status_code == 405
