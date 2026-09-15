"""Censo de ONU por modelo y firmware leyendo la OLT por SNMP.

No hace falta una OLT: lo que puede fallar en silencio es el parseo de la
salida de `snmpbulkwalk`, y eso se prueba con las líneas exactas que el
comando devuelve en las VSOL de ERLAN.
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

RUTA = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "censo_onu_vsol.py"
_spec = importlib.util.spec_from_file_location("censo_onu_vsol", RUTA)
censo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(censo)

BASE = censo.TABLA_ONU + ".3"


class TestParseo:
    def test_extrae_indice_y_valor(self):
        """El índice de la tabla es <pon>.<onu>: es lo que después cruza
        contra onu_senal."""
        lineas = [
            f'.{BASE}.1.1 = STRING: "VSOL12345678"',
            f'.{BASE}.1.2 = STRING: "VSOL87654321"',
            f'.{BASE}.3.17 = STRING: "VSOLAABBCCDD"',
        ]
        r = censo.parsear_columna(lineas, BASE)
        assert r == {"1.1": "VSOL12345678", "1.2": "VSOL87654321",
                     "3.17": "VSOLAABBCCDD"}

    @pytest.mark.parametrize("crudo,esperado", [
        ('STRING: "V2802GW"', "V2802GW"),
        ("INTEGER: 3", "3"),
        ("Gauge32: 41", "41"),
        ('STRING: "TIGRE-V1.0"', "TIGRE-V1.0"),
        ("STRING: V3.2.00", "V3.2.00"),
    ])
    def test_saca_el_prefijo_de_tipo_y_las_comillas(self, crudo, esperado):
        r = censo.parsear_columna([f".{BASE}.1.1 = {crudo}"], BASE)
        assert r["1.1"] == esperado

    def test_ignora_las_filas_sin_dato(self):
        """Una ONU dada de baja en la OLT devuelve 'No Such Instance'; contarla
        inflaría el censo con equipos que ya no existen."""
        lineas = [
            f'.{BASE}.1.1 = STRING: "VSOL11111111"',
            f".{BASE}.1.2 = No Such Instance currently exists at this OID",
            f'.{BASE}.1.3 = STRING: "VSOL33333333"',
        ]
        assert len(censo.parsear_columna(lineas, BASE)) == 2

    def test_ignora_lo_que_quedo_fuera_de_la_rama(self):
        """snmpbulkwalk se pasa del final de la tabla y sigue con el OID que
        viene después. Esas filas no son de esta columna."""
        lineas = [
            f'.{BASE}.1.1 = STRING: "VSOL11111111"',
            '.1.3.6.1.4.1.37950.1.1.6.1.2.1.1.4.1.1 = STRING: "otra columna"',
        ]
        r = censo.parsear_columna(lineas, BASE)
        assert list(r) == ["1.1"]

    def test_tolera_el_punto_inicial_o_su_ausencia(self):
        """snmpbulkwalk -On antepone un punto; otras versiones no."""
        con = censo.parsear_columna([f'.{BASE}.1.1 = STRING: "A"'], BASE)
        sin = censo.parsear_columna([f'{BASE}.1.1 = STRING: "A"'], BASE)
        assert con == sin == {"1.1": "A"}

    def test_una_salida_vacia_no_rompe(self):
        assert censo.parsear_columna([], BASE) == {}


class TestReconocimiento:
    """Las heurísticas que sugieren qué columna es cuál. Son una PISTA para la
    persona que mira el informe, no una confirmación: por eso alcanza con que
    acierten en los valores reales de ERLAN."""

    @pytest.mark.parametrize("v", ["V2802DAC", "V2802GW", "V1600G1"])
    def test_reconoce_los_modelos_de_erlan(self, v):
        assert censo.parece_modelo(v)

    @pytest.mark.parametrize("v", ["V3.2.00", "V1.9.1.2", "TIGRE-V1.0", "V2.1.06"])
    def test_reconoce_los_firmwares_de_erlan(self, v):
        """Los cuatro que ERLAN tiene instalados, incluido el TIGRE-V1.0, que
        no sigue la nomenclatura de VSOL."""
        assert censo.parece_version(v)

    @pytest.mark.parametrize("v", ["VSOL12345678", "online", "1", ""])
    def test_no_confunde_un_serial_ni_un_estado_con_un_modelo(self, v):
        assert not censo.parece_modelo(v)


class TestCoherencia:
    def test_la_columna_del_serial_es_la_que_dejo_documentada_el_poller(self):
        """Si alguien cambia esta constante sin verificar contra el equipo,
        el censo entero queda mal. `olt_poller.py` la confirmó con walks
        reales de una V1600G1 y una V1600G1B."""
        poller = (pathlib.Path(__file__).resolve().parent.parent
                  / "olt_poller.py").read_text(encoding="utf-8")
        assert f"{censo.TABLA_ONU}.{censo.COL_SERIAL}" in poller

    def test_es_solo_lectura(self):
        """Este script no puede escribir en la OLT ni en la base. Si alguien
        le agrega un snmpset, que falle acá."""
        texto = RUTA.read_text(encoding="utf-8")
        assert "snmpset" not in texto
        assert "sqlite3" not in texto
