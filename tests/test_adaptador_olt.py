"""El puente entre olt_poller.py y el motor de incidentes.

Lo que se verifica acá es la traducción: que un diccionario del poller se
convierta en la lectura correcta, que la basura no rompa el ciclo, y que una
lectura parcial no abra incidentes.
"""
from __future__ import annotations

import pytest
from sqlalchemy import insert
from sqlalchemy.orm import sessionmaker

import pucara.db as db
from pucara.adaptadores.incidentes_olt import procesar_sondeo_olt, referencia_onu
from pucara.models.incidentes import EstadoIncidente, Incidente
from pucara.models.legado import OnuSenal
from tests.motores import crear_esquema, motor


@pytest.fixture()
def base(tmp_path, monkeypatch):
    engine = motor(tmp_path)
    crear_esquema(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    monkeypatch.setattr(db, "_engine", engine)
    monkeypatch.setattr(db, "_Session", Session)
    with Session() as s:
        # El motor consulta cuántas ONU tiene el PON para el umbral porcentual.
        s.execute(insert(OnuSenal), [
            {"olt_id": 1, "pon": 3, "onu": i, "nro_cliente": f"100{i}"}
            for i in range(1, 11)
        ])
        s.commit()
    return Session


def caida(onu, pon=3, olt=1, online=False):
    return {"olt_id": olt, "pon": pon, "onu": onu, "online": online,
            "nro_cliente": f"100{onu}"}


class TestTraduccion:
    def test_referencia_usa_la_posicion_fisica(self):
        assert referencia_onu(1, 3, 7) == "olt:1/pon:3/onu:7"

    def test_ignora_filas_sin_datos_de_posicion(self, base):
        """Una fila corrupta del poller no puede tumbar el ciclo entero."""
        r = procesar_sondeo_olt([
            {"olt_id": None, "pon": 3, "onu": 1, "online": False},
            {"pon": 3, "online": False},
            {"olt_id": "x", "pon": "y", "onu": "z", "online": False},
            caida(1),
        ])
        assert r["nuevos"] == 1      # sólo la válida


class TestProcesamiento:
    def test_una_caida_suelta_abre_un_incidente_individual(self, base):
        r = procesar_sondeo_olt([caida(1)])
        assert r["nuevos"] == 1 and r["masivos"] == 0

    def test_varias_en_el_mismo_pon_abren_uno_solo(self, base):
        r = procesar_sondeo_olt([caida(1), caida(2), caida(3), caida(4)])
        assert r["masivos"] == 1
        assert r["nuevos"] == 0      # no se crean cuatro incidentes sueltos

    def test_no_duplica_entre_ciclos(self, base):
        procesar_sondeo_olt([caida(1)])
        r = procesar_sondeo_olt([caida(1)])
        assert r["nuevos"] == 0

    def test_la_recuperacion_marca_el_incidente(self, base):
        procesar_sondeo_olt([caida(1)])
        r = procesar_sondeo_olt([caida(1, online=True)])
        assert r["recuperados"] == 1

    def test_lectura_parcial_no_abre_incidentes(self, base):
        """Un walk truncado no puede inventar una caída masiva."""
        r = procesar_sondeo_olt([caida(1), caida(2), caida(3)], lectura_completa=False)
        assert r["omitido_por_lectura_parcial"] is True
        assert r["nuevos"] == 0 and r["masivos"] == 0

    def test_lectura_parcial_si_procesa_recuperaciones(self, base):
        procesar_sondeo_olt([caida(1)])
        r = procesar_sondeo_olt([caida(1, online=True)], lectura_completa=False)
        assert r["recuperados"] == 1

    def test_sin_lecturas_igual_cierra_lo_estable(self, base):
        """Si la OLT no responde, los incidentes ya recuperados deben poder
        cerrarse igual; si no, quedarían abiertos para siempre."""
        r = procesar_sondeo_olt([])
        assert r["nuevos"] == 0 and "cerrados" in r


class TestPersistencia:
    def test_el_incidente_queda_guardado_y_con_afectados(self, base):
        from sqlalchemy import select
        procesar_sondeo_olt([caida(1), caida(2), caida(3)])
        with base() as s:
            inc = s.scalars(select(Incidente)).one()
            assert inc.estado is EstadoIncidente.ACTIVA
            assert inc.referencia == "olt:1/pon:3"
            assert len(inc.afectados) == 3
            assert {a.nro_cliente for a in inc.afectados} == {"1001", "1002", "1003"}
