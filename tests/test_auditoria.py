"""Trazabilidad de cambios (plan estratégico §21).

El riesgo de este módulo no es que falle: es que genere ruido. Si guardar un
formulario sin tocarlo produce 30 "cambios", nadie va a mirar el historial y la
auditoría deja de existir en la práctica aunque el código funcione.
"""
from __future__ import annotations

import json

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from pucara.repositories.auditoria import AuditoriaRepository
from pucara.services.auditoria import CAMPOS_SECRETOS, calcular_diff
from tests.motores import crear_esquema, motor


@pytest.fixture()
def repo():
    engine = motor()
    crear_esquema(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False, future=True)()
    try:
        yield AuditoriaRepository(s), s
    finally:
        s.close()
        engine.dispose()


class TestDiff:
    def test_detecta_lo_que_cambio(self):
        d = calcular_diff({"plan": "100 Mbps", "estado": "activo"},
                          {"plan": "300 Mbps", "estado": "activo"})
        assert [c.campo for c in d.cambios] == ["plan"]
        assert str(d.cambios[0]) == "Plan: 100 Mbps → 300 Mbps"

    def test_sin_cambios_no_reporta_nada(self):
        igual = {"plan": "100", "estado": "activo", "nap": "NAP-1"}
        assert calcular_diff(igual, dict(igual)).hubo_cambios is False

    @pytest.mark.parametrize("a,b", [
        (None, ""), ("", None), ("  ", ""), (None, "   "),
    ])
    def test_vacio_y_nulo_son_lo_mismo(self, a, b):
        """La base guarda NULL y el formulario manda "". Sin esto, cada guardado
        inventaría cambios en todos los campos opcionales."""
        assert calcular_diff({"email": a}, {"email": b}).hubo_cambios is False

    @pytest.mark.parametrize("a,b", [(100, "100"), ("100.0", 100), (2500.0, "2500")])
    def test_numero_y_texto_del_mismo_valor_no_son_un_cambio(self, a, b):
        """Los formularios HTML mandan todo como texto; la base devuelve números."""
        assert calcular_diff({"precio": a}, {"precio": b}).hubo_cambios is False

    def test_un_cambio_real_de_precio_si_se_detecta(self):
        assert calcular_diff({"precio": 2500}, {"precio": 3000}).hubo_cambios is True

    def test_solo_compara_los_campos_pedidos(self):
        """La ruta define qué es editable; lo demás no se audita aunque venga."""
        d = calcular_diff({"plan": "A", "interno": "x"},
                          {"plan": "B", "interno": "y"}, campos=["plan"])
        assert [c.campo for c in d.cambios] == ["plan"]

    def test_ignora_claves_que_no_vienen_en_el_envio(self):
        """Un PATCH parcial no puede parecer que borró los campos ausentes."""
        d = calcular_diff({"plan": "A", "nap": "NAP-1"}, {"plan": "A"})
        assert d.hubo_cambios is False


class TestSecretos:
    @pytest.mark.parametrize("campo", ["pppoe_clave", "password", "community", "token"])
    def test_nunca_escribe_el_valor_de_un_secreto(self, campo):
        """El historial lo ve cualquiera con permiso del módulo."""
        d = calcular_diff({campo: "viejo123"}, {campo: "nuevo456"})
        assert d.hubo_cambios is True            # se registra QUE cambió
        assert d.cambios[0].antes == "(oculto)"  # pero no A QUÉ
        assert d.cambios[0].despues == "(oculto)"
        assert "viejo123" not in d.a_json() and "nuevo456" not in d.a_json()

    def test_la_lista_de_secretos_cubre_lo_que_hay_en_el_sistema(self):
        for c in ("pppoe_clave", "telegram_token", "pg_password", "community"):
            assert c in CAMPOS_SECRETOS


class TestResumen:
    def test_los_campos_criticos_van_primero(self):
        """Quien abre el historial busca el cambio de plan, no el de teléfono."""
        d = calcular_diff({"telefono": "1", "plan": "A", "email": "x@y"},
                          {"telefono": "2", "plan": "B", "email": "z@y"})
        assert d.resumen().startswith("Plan: A → B")

    def test_resume_y_cuenta_el_resto(self):
        antes = {f"c{i}": i for i in range(8)}
        despues = {f"c{i}": i + 1 for i in range(8)}
        assert "(+5 campos)" in calcular_diff(antes, despues).resumen()

    def test_muestra_los_vacios_de_forma_legible(self):
        d = calcular_diff({"nap": None}, {"nap": "NAP-034"})
        assert str(d.cambios[0]) == "NAP: (vacío) → NAP-034"


class TestPersistencia:
    def test_guarda_titulo_detalle_y_diff(self, repo):
        r, s = repo
        d = calcular_diff({"plan": "100 Mbps", "precio": 2500},
                          {"plan": "300 Mbps", "precio": 3800})
        assert r.registrar_cambio("clientes", "Cliente", 4532, d, usuario="Esteban") is True

        fila = s.execute(text("SELECT * FROM historial")).mappings().one()
        assert fila["usuario"] == "Esteban" and fila["modulo"] == "clientes"
        assert "Cliente #4532" in fila["titulo"]
        assert "100 Mbps → 300 Mbps" in fila["titulo"]
        # El diff estructurado permite reconstruir el cambio, no sólo leerlo
        campos = {c["campo"]: c for c in json.loads(fila["diff"])}
        assert campos["precio"]["antes"] == 2500
        assert campos["precio"]["despues"] == 3800
        assert campos["plan"]["critico"] is True

    def test_no_escribe_una_fila_si_no_cambio_nada(self, repo):
        r, s = repo
        assert r.registrar_cambio("clientes", "Cliente", 1,
                                  calcular_diff({"plan": "A"}, {"plan": "A"})) is False
        assert s.execute(text("SELECT COUNT(*) FROM historial")).scalar() == 0

    def test_recupera_el_historial_de_una_entidad(self, repo):
        r, s = repo
        r.registrar_cambio("clientes", "Cliente", 10, calcular_diff({"plan": "A"}, {"plan": "B"}))
        r.registrar_cambio("clientes", "Cliente", 10, calcular_diff({"plan": "B"}, {"plan": "C"}))
        r.registrar_cambio("clientes", "Cliente", 99, calcular_diff({"plan": "X"}, {"plan": "Y"}))
        historial = r.historial_de("clientes", 10)
        assert len(historial) == 2
        assert "B → C" in historial[0]["titulo"]     # el más reciente primero
