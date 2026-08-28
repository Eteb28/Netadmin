"""Detección temprana de degradación óptica y saturación GPON.

Casos tomados del diagnóstico de red de agosto 2026: 122 ONUs con Rx < −27 dBm,
Rx promedio −22,4 dBm, y Puerto Sánchez GPON 0/3 con 127 ONUs sobre un máximo
físico de 128.
"""
from __future__ import annotations

import pytest
from sqlalchemy import insert
from sqlalchemy.orm import sessionmaker

from pucara.models.legado import Cliente, Olt, OnuSenal, OnuSenalHist
from pucara.repositories.optica import OpticaRepository
from pucara.services.degradacion import (
    PON_ALERTA, RX_CRITICO, ServicioDegradacion,
)


@pytest.fixture()
def base():
    from tests.motores import crear_esquema, motor

    engine = motor()
    crear_esquema(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False, future=True)()
    s.execute(insert(Olt), [{"id": 1, "nombre": "Puerto Sánchez"},
                            {"id": 2, "nombre": "Alcaín"}])
    s.commit()
    try:
        yield s
    finally:
        # Cerrar de verdad: en PostgreSQL una sesión abierta bloquea el
        # DROP SCHEMA con el que la prueba siguiente limpia la base.
        s.close()
        engine.dispose()


def onu(s, pon, num, rx, nro=None, online=1, olt=1):
    s.execute(insert(OnuSenal).values(
        olt_id=olt, pon=pon, onu=num, nro_cliente=nro, rx_power=rx,
        online=online, last_check="2026-08-12 10:00"))


def historia(s, pon, num, valores, olt=1):
    s.execute(insert(OnuSenalHist), [
        {"olt_id": olt, "pon": pon, "onu": num, "rx_power": v,
         "fecha": f"2026-08-{i+1:02d}"}
        for i, v in enumerate(valores)
    ])


def srv(s):
    return ServicioDegradacion(OpticaRepository(s))


class TestDegradacion:
    def test_detecta_una_caida_de_mas_de_3_db(self, base):
        """El caso que el informe llama de mayor valor comercial: la ONU
        todavía funciona, pero se está yendo."""
        onu(base, 1, 1, -25.5, "1001")
        historia(base, 1, 1, [-21.4, -21.5, -21.3, -21.6, -21.4, -21.5, -25.5])
        base.commit()
        r = srv(base).analizar()
        assert r.degradadas == 1
        caso = r.en_riesgo[0]
        assert caso.caida_db == pytest.approx(4.1, abs=0.2)
        assert caso.severidad == "alta"
        assert "Degradación" in caso.motivo

    def test_una_caida_grave_es_critica(self, base):
        onu(base, 1, 1, -28.5, "1001")
        historia(base, 1, 1, [-21.0] * 6 + [-28.5])
        base.commit()
        assert srv(base).analizar().en_riesgo[0].severidad == "critica"

    def test_una_onu_estable_no_alerta(self, base):
        onu(base, 1, 1, -21.5, "1001")
        historia(base, 1, 1, [-21.4, -21.6, -21.3, -21.5, -21.4, -21.5])
        base.commit()
        assert srv(base).analizar().en_riesgo == []

    def test_una_variacion_menor_no_alerta(self, base):
        """1,5 dB es ruido de medición, no una falla. Alertar por eso llenaría
        la pantalla y nadie la miraría más."""
        onu(base, 1, 1, -22.9, "1001")
        historia(base, 1, 1, [-21.4] * 6)
        base.commit()
        assert srv(base).analizar().en_riesgo == []

    def test_sin_historia_suficiente_no_inventa_una_linea_base(self, base):
        onu(base, 1, 1, -22.0, "1001")
        historia(base, 1, 1, [-21.5, -21.6])      # sólo 2 lecturas
        base.commit()
        assert srv(base).analizar().en_riesgo == []

    def test_lecturas_basura_no_arruinan_la_linea_base(self, base):
        """Durante un corte el poller registra valores absurdos. Con promedio,
        la línea base se desploma y la ONU parecería estar mejorando; con
        mediana, esos valores se ignoran."""
        onu(base, 1, 1, -25.0, "1001")
        historia(base, 1, 1, [-21.0, -21.2, -40.0, -21.1, -39.5, -21.0, -21.1])
        base.commit()
        caso = srv(base).analizar().en_riesgo[0]
        assert caso.rx_base == pytest.approx(-21.1, abs=0.3)   # no ~-26
        assert caso.caida_db >= 3.0


class TestNivelAbsoluto:
    def test_una_onu_bajo_menos_27_es_critica_aunque_este_estable(self, base):
        """122 clientes están así según el diagnóstico: al borde del umbral de
        pérdida de sincronismo. Cualquier lluvia los desconecta."""
        onu(base, 1, 1, -28.2, "1001")
        historia(base, 1, 1, [-28.1] * 6)
        base.commit()
        caso = srv(base).analizar().en_riesgo[0]
        assert caso.severidad == "critica"
        assert "crítica" in caso.motivo.lower()

    def test_detecta_la_onu_saturada(self, base):
        """Demasiada potencia también rompe: el técnico dejó la ONU muy cerca."""
        onu(base, 1, 1, -5.2, "1001")
        base.commit()
        r = srv(base).analizar()
        assert r.saturadas == 1
        assert "saturada" in r.en_riesgo[0].motivo.lower()

    def test_señal_baja_sin_caida_es_media(self, base):
        onu(base, 1, 1, -25.8, "1001")
        base.commit()
        assert srv(base).analizar().en_riesgo[0].severidad == "media"


class TestOnusCaidas:
    def test_una_onu_caida_no_entra_acá(self, base):
        """De las caídas se ocupa el motor de incidentes. Esto busca las que
        todavía funcionan pero se están yendo."""
        onu(base, 1, 1, -30.0, "1001", online=0)
        base.commit()
        r = srv(base).analizar()
        assert r.en_riesgo == []
        assert r.offline == 1


class TestSaturacionPon:
    def test_detecta_el_puerto_con_127_onus(self, base):
        """El caso real de Puerto Sánchez GPON 0/3."""
        for i in range(1, 128):
            onu(base, 3, i, -22.0)
        base.commit()
        r = srv(base).analizar()
        assert r.pon_sobre_umbral == 1
        p = r.pones[0]
        assert p.onus == 127 and p.severidad == "critica"
        assert p.ubicacion == "Puerto Sánchez · GPON0/3"

    def test_un_puerto_dentro_del_split_no_alerta(self, base):
        for i in range(1, PON_ALERTA + 1):
            onu(base, 2, i, -22.0)
        base.commit()
        assert srv(base).analizar().pon_sobre_umbral == 0

    def test_entre_64_y_100_es_alta_no_critica(self, base):
        for i in range(1, 81):
            onu(base, 4, i, -22.0)
        base.commit()
        assert srv(base).analizar().pones[0].severidad == "alta"


class TestResumen:
    def test_ordena_primero_lo_que_hay_que_atender_hoy(self, base):
        onu(base, 1, 1, -25.5, "1001")            # media
        onu(base, 1, 2, -28.5, "1002")            # crítica
        onu(base, 1, 3, -26.0, "1003")            # media
        base.commit()
        assert srv(base).analizar().en_riesgo[0].severidad == "critica"

    def test_cuenta_online_offline_y_promedio(self, base):
        onu(base, 1, 1, -22.0, online=1)
        onu(base, 1, 2, -24.0, online=1)
        onu(base, 1, 3, -30.0, online=0)
        base.commit()
        r = srv(base).analizar()
        assert (r.total_onus, r.online, r.offline) == (3, 2, 1)
        assert r.rx_promedio == pytest.approx(-25.3, abs=0.1)

    def test_cruza_el_nombre_del_cliente(self, base):
        base.execute(insert(Cliente).values(
            id=7, nombre="ABERKON MARIA JOSE", nro_cliente="1001"))
        onu(base, 1, 1, -28.0, "1001")
        base.commit()
        caso = srv(base).analizar().en_riesgo[0]
        assert caso.cliente_nombre == "ABERKON MARIA JOSE"
        assert caso.cliente_id == 7        # para poder abrir la ficha y llamarlo

    def test_umbral_critico_coincide_con_el_del_diagnostico(self):
        assert RX_CRITICO == -27.0
