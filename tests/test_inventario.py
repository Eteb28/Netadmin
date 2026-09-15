"""Conciliación del inventario contra lo que la red reporta.

Lo que se prueba acá no es que el cruce corra: es que **no invente faltantes**.
Un informe que lista como perdido cada equipo que estuvo apagado un rato es
peor que no tener informe, porque nadie lo mira más y el problema de fondo
—años de registros malos— sigue igual.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import insert
from sqlalchemy.orm import sessionmaker

from pucara.models.legado import (
    Cliente, Olt, OnuSenal, SnmpEstacion, StockItem, Torre, TorreEquipo,
)
from pucara.repositories.inventario import InventarioRepository
from pucara.services.inventario import (
    DIFIERE, FANTASMA, HUERFANO, NO_VISTO, SIN_REGISTRO,
    ServicioInventario, comparar, normalizar_mac, normalizar_serie,
)
from tests.motores import crear_esquema, motor

HOY = date(2026, 9, 14)


def _hace(dias: int) -> str:
    return (HOY - timedelta(days=dias)).isoformat() + " 03:00:00"


@pytest.fixture()
def base():
    engine = motor()
    crear_esquema(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False, future=True)()
    s.execute(insert(Olt).values(id=1, nombre="Puerto Sánchez"))
    s.execute(insert(Torre).values(id=1, nombre="Torre Crespo"))
    s.commit()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def srv(s):
    return ServicioInventario(InventarioRepository(s), hoy=HOY)


def cliente(s, cid, nro, estado="activo", tipo="fibra", serie=None, mac=None):
    s.execute(insert(Cliente).values(
        id=cid, nombre=f"Cliente {cid}", nro_cliente=nro, estado=estado,
        tipo_servicio=tipo, equipo_serie=serie, mac_address=mac))


def onu(s, pon, num, serial, nro, online=1):
    s.execute(insert(OnuSenal).values(
        olt_id=1, pon=pon, onu=num, serial_onu=serial, nro_cliente=nro,
        online=online, last_check=_hace(0)))


def estacion(s, mac, cliente_id=None, modelo="ePMP Force 300", ap=1):
    s.execute(insert(SnmpEstacion).values(
        equipo_id=ap, mac=mac, cliente_id=cliente_id, modelo_sm=modelo,
        nombre_ap="AP Crespo Norte", fecha=_hace(0)))


def equipo_torre(s, eid, serie=None, mac=None, dias_sin_ver=0, estado="operativo"):
    s.execute(insert(TorreEquipo).values(
        id=eid, torre_id=1, tipo="Radio", fabricante="Cambium", modelo="ePMP 3000",
        nro_serie=serie, mac=mac, estado=estado,
        ultimo_snmp=None if dias_sin_ver is None else _hace(dias_sin_ver)))


def item(s, iid, serie=None, mac=None, estado="deposito", cliente_id=None):
    s.execute(insert(StockItem).values(
        id=iid, serie=serie, mac=mac, marca="VSOL", modelo="V2802",
        tipo="ONU", estado=estado, cliente_id=cliente_id))


# ══════════════════════════════════════════════════════════════════════

class TestNormalizacion:
    @pytest.mark.parametrize("crudo,esperado", [
        ("VSOL-1234 5678", "VSOL12345678"),
        ("vsol:12345678", "VSOL12345678"),
        ("  VSOL12345678  ", "VSOL12345678"),
        (None, ""),
    ])
    def test_el_mismo_serial_cargado_de_cinco_formas_es_uno_solo(self, crudo, esperado):
        """Sin esto casi todo daría «difiere» y el informe no serviría."""
        assert normalizar_serie(crudo) == esperado

    @pytest.mark.parametrize("crudo,esperado", [
        ("AA:BB:CC:11:22:33", "AABBCC112233"),
        ("aa-bb-cc-11-22-33", "AABBCC112233"),
        ("AABBCC112233", "AABBCC112233"),
        ("AA:BB:CC", ""),          # incompleta: no es una MAC
        ("no es una mac", ""),
    ])
    def test_las_mac_se_comparan_sin_separadores(self, crudo, esperado):
        assert normalizar_mac(crudo) == esperado


class TestComparacion:
    def test_el_serial_parcial_cargado_a_mano_cuenta_como_coincidencia(self):
        """Caso real: la OLT reporta VSOL12345678 y alguien cargó sólo los
        dígitos. Es el mismo equipo, no una diferencia."""
        assert comparar("VSOL12345678", "12345678") == "ok"

    def test_dos_seriales_cortos_no_coinciden_de_casualidad(self):
        """Sin largo mínimo, '123' estaría dentro de medio padrón."""
        assert comparar("ABC123", "123") == DIFIERE

    def test_sin_dato_del_registro_es_sin_registro(self):
        assert comparar("VSOL12345678", None) == SIN_REGISTRO

    def test_sin_dato_de_la_red_no_dice_nada(self):
        """Que la OLT no informe serial no es un hallazgo del registro."""
        assert comparar(None, "VSOL12345678") is None


class TestFibra:
    def test_la_onu_que_coincide_no_genera_hallazgo(self, base):
        cliente(base, 1, "1001", serie="VSOL12345678")
        onu(base, 1, 10, "VSOL12345678", "1001")
        base.commit()
        r = srv(base).analizar()
        assert r.hallazgos == [] and r.coinciden == 1

    def test_detecta_el_cambio_de_onu_sin_registrar(self, base):
        cliente(base, 1, "1001", serie="VSOL11111111")
        onu(base, 1, 10, "VSOL99999999", "1001")
        base.commit()
        h = srv(base).analizar().hallazgos[0]
        assert h.categoria == DIFIERE and h.severidad == "alta"
        assert h.registrado == "VSOL11111111" and h.detectado == "VSOL99999999"

    def test_detecta_la_onu_funcionando_sin_equipo_en_la_ficha(self, base):
        cliente(base, 1, "1001", serie=None)
        onu(base, 1, 10, "VSOL12345678", "1001")
        base.commit()
        assert srv(base).analizar().hallazgos[0].categoria == SIN_REGISTRO

    def test_una_onu_de_un_cliente_que_no_existe_es_huerfana(self, base):
        onu(base, 1, 10, "VSOL12345678", "9999")
        base.commit()
        h = srv(base).analizar().hallazgos[0]
        assert h.categoria == HUERFANO and "9999" in h.detalle

    def test_el_cruce_ignora_espacios_en_el_numero_de_cliente(self, base):
        """En producción hay nro_cliente cargados con espacios."""
        cliente(base, 1, " 1001 ", serie="VSOL12345678")
        onu(base, 1, 10, "VSOL12345678", "1001")
        base.commit()
        assert srv(base).analizar().hallazgos == []


class TestNoInventarFaltantes:
    """El corazón del asunto: no ver ≠ no existir."""

    def test_un_cliente_suspendido_sin_onu_no_es_un_faltante(self, base):
        """Se le cortó el servicio a propósito. Listarlo sería ruido."""
        cliente(base, 1, "1001", estado="suspendido", serie="VSOL12345678")
        base.commit()
        r = srv(base).analizar()
        assert r.hallazgos == [] and r.esperados_sin_servicio == 1

    @pytest.mark.parametrize("estado", ["suspendido", "rescision", "pte_rescision", "baja"])
    def test_ningun_estado_sin_servicio_genera_faltante(self, base, estado):
        cliente(base, 1, "1001", estado=estado, serie="VSOL1")
        base.commit()
        assert srv(base).analizar().hallazgos == []

    def test_un_cliente_activo_sin_onu_si_se_reporta(self, base):
        cliente(base, 1, "1001", estado="activo", serie="VSOL12345678")
        base.commit()
        h = srv(base).analizar().hallazgos[0]
        assert h.categoria == NO_VISTO and h.cliente_id == 1

    def test_un_equipo_de_torre_que_contesto_hoy_no_es_faltante(self, base):
        equipo_torre(base, 1, serie="SN-TORRE-1", dias_sin_ver=0)
        base.commit()
        assert srv(base).analizar().hallazgos == []

    def test_un_corte_de_un_dia_no_convierte_un_equipo_en_faltante(self, base):
        equipo_torre(base, 1, serie="SN-TORRE-1", dias_sin_ver=1)
        base.commit()
        assert srv(base).analizar().hallazgos == []

    def test_una_semana_sin_contestar_si_se_reporta(self, base):
        equipo_torre(base, 1, serie="SN-TORRE-1", dias_sin_ver=30)
        base.commit()
        h = srv(base).analizar().hallazgos[0]
        assert h.categoria == NO_VISTO and h.dias_sin_ver == 30
        assert h.severidad == "media"

    def test_dos_meses_sin_contestar_sube_a_severidad_alta(self, base):
        equipo_torre(base, 1, serie="SN-TORRE-1", dias_sin_ver=90)
        base.commit()
        assert srv(base).analizar().hallazgos[0].severidad == "alta"

    def test_un_equipo_dado_de_baja_no_se_reporta(self, base):
        equipo_torre(base, 1, serie="SN-1", dias_sin_ver=200, estado="de_baja")
        base.commit()
        assert srv(base).analizar().hallazgos == []

    def test_un_equipo_que_nunca_se_sondeo_no_es_un_faltante(self, base):
        """Nunca haberlo mirado no es evidencia de que no esté."""
        equipo_torre(base, 1, serie="SN-1", dias_sin_ver=None)
        base.commit()
        assert srv(base).analizar().hallazgos == []


class TestInalambrico:
    def test_la_mac_que_coincide_no_genera_hallazgo(self, base):
        cliente(base, 1, "2001", tipo="inalambrico", mac="AA:BB:CC:11:22:33")
        estacion(base, "AABBCC112233", cliente_id=1)
        base.commit()
        r = srv(base).analizar()
        assert r.hallazgos == [] and r.coinciden == 1

    def test_detecta_el_cambio_de_equipo_sin_registrar(self, base):
        cliente(base, 1, "2001", tipo="inalambrico", mac="AA:BB:CC:11:22:33")
        estacion(base, "DDEEFF445566", cliente_id=1)
        base.commit()
        assert srv(base).analizar().hallazgos[0].categoria == DIFIERE

    def test_un_equipo_conectado_sin_cliente_asignado_es_huerfano(self, base):
        estacion(base, "AABBCC112233", cliente_id=None)
        base.commit()
        h = srv(base).analizar().hallazgos[0]
        assert h.categoria == HUERFANO and "ePMP" in h.detalle


class TestDeposito:
    """Lo que el usuario pidió medir: figura en el papel y ya no está."""

    def test_lo_que_figura_instalado_y_la_red_no_ve_es_candidato_a_faltante(self, base):
        item(base, 1, serie="VSOL77777777", estado="instalado", cliente_id=5)
        base.commit()
        h = srv(base).analizar().hallazgos[0]
        assert h.categoria == NO_VISTO and h.fuente == "stock"
        assert h.severidad == "alta"

    def test_lo_que_figura_en_deposito_pero_esta_funcionando_es_un_fantasma(self, base):
        """Salió del depósito sin que nadie lo registrara. Es el agujero que
        hace que el stock no cierre."""
        cliente(base, 1, "1001", serie="VSOL12345678")
        onu(base, 1, 10, "VSOL12345678", "1001")
        item(base, 1, serie="VSOL12345678", estado="deposito")
        base.commit()
        h = [x for x in srv(base).analizar().hallazgos if x.categoria == FANTASMA][0]
        assert h.severidad == "alta" and "sin registrarse" in h.detalle

    def test_un_item_en_deposito_que_la_red_no_ve_esta_bien(self, base):
        """Está guardado y apagado: es exactamente lo que dice el papel."""
        item(base, 1, serie="VSOL77777777", estado="deposito")
        base.commit()
        assert srv(base).analizar().hallazgos == []

    def test_se_cruza_tambien_por_mac_y_no_solo_por_serie(self, base):
        cliente(base, 1, "2001", tipo="inalambrico", mac="AABBCC112233")
        estacion(base, "AABBCC112233", cliente_id=1)
        item(base, 1, mac="AA:BB:CC:11:22:33", estado="deposito")
        base.commit()
        assert [h.categoria for h in srv(base).analizar().hallazgos] == [FANTASMA]

    def test_un_item_sin_serie_ni_mac_se_saltea(self, base):
        """No hay nada con qué cruzarlo; inventar un hallazgo sería mentir."""
        item(base, 1, serie=None, mac=None, estado="instalado", cliente_id=5)
        base.commit()
        assert srv(base).analizar().hallazgos == []


class TestResumen:
    def test_la_cobertura_mide_cuan_bien_esta_el_registro(self, base):
        cliente(base, 1, "1001", serie="VSOL11111111")
        cliente(base, 2, "1002", serie="VSOL22222222")
        cliente(base, 3, "1003", serie=None)
        cliente(base, 4, "1004", serie="VSOL44444444")
        onu(base, 1, 10, "VSOL11111111", "1001")     # ok
        onu(base, 1, 11, "VSOL22222222", "1002")     # ok
        onu(base, 1, 12, "VSOL33333333", "1003")     # sin registro
        onu(base, 1, 13, "VSOL99999999", "1004")     # difiere
        base.commit()
        r = srv(base).analizar()
        assert r.vistos_en_la_red == 4 and r.coinciden == 2
        assert r.cobertura == 50.0

    def test_sin_datos_la_cobertura_es_desconocida_y_no_cero(self, base):
        """Cero por ciento diría «está todo mal»; la verdad es «no se sabe»."""
        assert srv(base).analizar().cobertura is None

    def test_lo_grave_va_primero(self, base):
        cliente(base, 1, "1001", serie=None)
        onu(base, 1, 10, "VSOL12345678", "1001")     # sin_registro, media
        cliente(base, 2, "1002", serie="VSOL11111111")
        onu(base, 1, 11, "VSOL22222222", "1002")     # difiere, alta
        base.commit()
        assert srv(base).analizar().hallazgos[0].categoria == DIFIERE

    def test_cuenta_los_hallazgos_por_categoria(self, base):
        cliente(base, 1, "1001", serie="VSOL11111111")
        onu(base, 1, 10, "VSOL99999999", "1001")
        onu(base, 1, 11, "VSOL88888888", "7777")
        base.commit()
        assert srv(base).analizar().por_categoria == {DIFIERE: 1, HUERFANO: 1}
