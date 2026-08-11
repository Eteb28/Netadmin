"""Driver VSOL: capacidades declaradas, parseo e inventario.

Los tests de parseo son la red de contención del riesgo R2 (la CLI y las MIB
cambian entre versiones de firmware). Cuando lleguen los walks reales de la
V1600G1-B, van acá y cualquier diferencia salta como un test que falla.
"""

from __future__ import annotations

import pytest

from gpon_module.core.enums import Capacidad, EstadoONU, Fabricante, MotivoCaida
from gpon_module.core.errors import CapacidadNoSoportada, ErrorLecturaParcial, ErrorTiempoAgotado
from gpon_module.core.models import OLT, CredencialesOLT, RefONU
from gpon_module.core.registry import describir
from gpon_module.drivers.vsol import DriverVSOL
from gpon_module.drivers.vsol import parsers as p
from gpon_module.drivers.vsol.snmp_simulado import SNMPSimuladoVSOL

CREDENCIALES = CredencialesOLT(comunidad_snmp_lectura="publica")


def _driver(**kwargs) -> DriverVSOL:
    snmp = kwargs.pop("snmp", None) or SNMPSimuladoVSOL(**kwargs)
    return DriverVSOL(
        olt=OLT(id=1, nombre="OLT Centro", host="10.0.0.1", fabricante=Fabricante.VSOL),
        credenciales=CREDENCIALES,
        transporte_snmp=snmp,
    )


class TestCapacidadesVerificadas:
    """Lo que estos equipos NO pueden. Cada ausencia salió de un walk real."""

    @pytest.mark.parametrize(
        "capacidad",
        [
            Capacidad.SERIAL_POR_SNMP,
            Capacidad.TRAFICO_POR_ONU,
            Capacidad.CPU,
            Capacidad.MEMORIA,
            Capacidad.TEMPERATURA_CHASIS,
            Capacidad.DESCUBRIR_NO_AUTORIZADAS,
        ],
    )
    def test_lo_que_no_expone_queda_declarado_como_ausente(self, capacidad) -> None:
        assert capacidad not in describir(Fabricante.VSOL).capacidades

    @pytest.mark.parametrize(
        "capacidad",
        [
            Capacidad.DESCUBRIR_ONUS,
            Capacidad.DESCUBRIR_PUERTOS,
            Capacidad.POTENCIA_OPTICA,
            Capacidad.POTENCIA_MASIVA,
            Capacidad.MOTIVO_CAIDA,
        ],
    )
    def test_lo_que_si_expone(self, capacidad) -> None:
        assert capacidad in describir(Fabricante.VSOL).capacidades

    def test_ninguna_escritura_esta_declarada_todavia(self) -> None:
        """La escritura es Fase 5: hasta entonces el equipo no la ofrece."""
        capacidades = describir(Fabricante.VSOL).capacidades
        escrituras = {
            Capacidad.AUTORIZAR_ONU,
            Capacidad.ELIMINAR_ONU,
            Capacidad.REINICIAR_ONU,
            Capacidad.RESTAURAR_FABRICA,
            Capacidad.WIFI_POR_OMCI,
        }
        assert capacidades & escrituras == set()

    def test_pedir_una_escritura_falla_sin_tocar_el_equipo(self) -> None:
        snmp = SNMPSimuladoVSOL()
        driver = _driver(snmp=snmp)
        with pytest.raises(CapacidadNoSoportada):
            driver.reboot_onu(RefONU(1, 1))
        assert snmp.consultas == []

    def test_los_datos_ausentes_son_none_y_nunca_cero(self) -> None:
        info = _driver().get_system_info()
        assert info.cpu_porcentaje is None
        assert info.memoria_porcentaje is None
        assert info.temperatura_celsius is None


class TestIdentidad:
    def test_lee_modelo_firmware_y_serie(self) -> None:
        info = _driver().get_system_info()
        assert info.modelo == "V1600G1B"
        assert info.firmware == "V2.1.7_2023"
        assert info.numero_serie == "VS2023110001"
        assert info.fabricante is Fabricante.VSOL

    def test_convierte_el_uptime_a_segundos(self) -> None:
        assert _driver().get_uptime() == 1234567


class TestInventario:
    def test_descubre_todas_las_onu_con_su_posicion(self) -> None:
        driver = _driver(cantidad_pon=4, onus_por_pon=3)
        onus = driver.discover_onus()

        assert len(onus) == 12
        assert onus[0].ref == RefONU(1, 1)
        assert {o.ref.pon for o in onus} == {1, 2, 3, 4}

    def test_el_serial_queda_vacio_porque_el_equipo_no_lo_publica(self) -> None:
        """Verificado: la rama de seriales no existe en la G1-B."""
        onus = _driver(cantidad_pon=2, onus_por_pon=2).discover_onus()
        assert all(o.numero_serie == "" for o in onus)

    def test_toma_el_nombre_del_cliente_desde_ifalias(self) -> None:
        onus = _driver(cantidad_pon=2, onus_por_pon=2).discover_onus()
        assert onus[0].nombre.startswith("CLI")
        assert "CDO" in onus[0].nombre

    def test_distingue_corte_de_luz_de_fibra_cortada(self) -> None:
        onus = _driver(cantidad_pon=8, onus_por_pon=6).discover_onus()
        motivos = {o.motivo_caida for o in onus if o.estado is EstadoONU.FUERA_DE_LINEA}
        assert MotivoCaida.APAGADO in motivos
        assert MotivoCaida.PERDIDA_SENAL in motivos

    def test_una_onu_en_linea_no_lleva_motivo_de_caida(self) -> None:
        onus = _driver(cantidad_pon=4, onus_por_pon=4).discover_onus()
        en_linea = [o for o in onus if o.estado is EstadoONU.EN_LINEA]
        assert en_linea
        assert all(o.motivo_caida is MotivoCaida.NINGUNO for o in en_linea)

    def test_una_tabla_vacia_se_reporta_como_lectura_parcial(self) -> None:
        """Cero ONU en una OLT que las tiene es un problema, no un inventario."""
        driver = _driver(tabla_onu_vacia=True)
        with pytest.raises(ErrorLecturaParcial):
            driver.discover_onus()

    def test_un_timeout_no_se_convierte_en_inventario_vacio(self) -> None:
        driver = _driver(sin_respuesta=True)
        with pytest.raises(ErrorTiempoAgotado):
            driver.discover_onus()


class TestPuertosPON:
    def test_descubre_los_puertos_con_su_conteo_de_onu(self) -> None:
        puertos = _driver(cantidad_pon=4, onus_por_pon=5).discover_ports()

        assert len(puertos) == 4
        assert sum(p_.cantidad_onus for p_ in puertos) == 20
        for puerto in puertos:
            assert puerto.cantidad_onus_en_linea <= puerto.cantidad_onus
            assert puerto.temperatura_celsius is not None


class TestPotencias:
    def test_lectura_masiva(self) -> None:
        lecturas = _driver(cantidad_pon=4, onus_por_pon=4).get_signals()
        assert len(lecturas) == 16
        assert all(-40 <= le.rx_onu_dbm <= 10 for le in lecturas if le.rx_onu_dbm is not None)

    def test_lectura_individual(self) -> None:
        lectura = _driver().get_signal(RefONU(1, 1))
        assert lectura.rx_onu_dbm is not None
        assert lectura.temperatura_celsius is not None

    @pytest.mark.parametrize("escala", [1, 10, 100, 1000])
    def test_la_escala_se_infiere_del_orden_de_magnitud(self, escala: int) -> None:
        """El punto [POR CONFIRMAR] del driver, acotado por rango físico.

        No sabemos con qué divisor publica el equipo las potencias, así que el
        parser lo deduce. Mientras el resultado caiga en el rango posible de
        GPON, la lectura es correcta con cualquiera de las escalas usuales.
        """
        lecturas = _driver(cantidad_pon=2, onus_por_pon=2, escala_potencia=escala).get_signals()
        assert all(-40 <= le.rx_onu_dbm <= 10 for le in lecturas if le.rx_onu_dbm is not None)


class TestParsers:
    @pytest.mark.parametrize(
        ("crudo", "esperado"),
        [
            ("3", EstadoONU.EN_LINEA),
            ("4", EstadoONU.FUERA_DE_LINEA),
            ("6", EstadoONU.FUERA_DE_LINEA),
        ],
    )
    def test_estados_medidos_en_el_parque_real(self, crudo, esperado) -> None:
        assert p.parsear_estado(crudo) is esperado

    def test_un_codigo_desconocido_no_se_adivina(self) -> None:
        assert p.parsear_estado("99") is EstadoONU.DESCONOCIDO
        assert p.parsear_estado(None) is EstadoONU.DESCONOCIDO

    @pytest.mark.parametrize(
        ("crudo", "esperado"),
        [
            ("Power Off", MotivoCaida.APAGADO),
            ("Onu Los", MotivoCaida.PERDIDA_SENAL),
            ("N/A", MotivoCaida.NINGUNO),
            ("dying gasp", MotivoCaida.APAGADO),
        ],
    )
    def test_motivos_medidos_en_el_parque_real(self, crudo, esperado) -> None:
        assert p.parsear_motivo(crudo) is esperado

    @pytest.mark.parametrize(
        ("crudo", "escala", "esperado"),
        [
            ("-2322", 100, -23.22),
            ("-23.22", 1, -23.22),
            ("-232", 10, -23.2),
            ("-157", 100, -1.57),
            ("-157", 10, -15.7),
        ],
    )
    def test_con_la_escala_conocida_la_conversion_es_exacta(self, crudo, escala, esperado) -> None:
        assert p.parsear_dbm(crudo, escala) == pytest.approx(esperado, abs=0.01)

    def test_un_valor_suelto_es_ambiguo_y_por_eso_la_escala_sale_del_lote(self) -> None:
        """`-157` puede ser −15,7 dBm o −1,57 dBm: las dos son potencias reales.

        Con un solo valor no hay forma de decidir. Con el lote completo sí: la
        escala correcta es la que ubica a la mayoría del parque en el rango
        donde vive una red sana.
        """
        lote_decimas = ["-157", "-203", "-188", "-225", "-176"]
        assert p.inferir_escala_dbm(lote_decimas) == 10

        lote_centesimas = ["-1570", "-2030", "-1880", "-2250", "-1760"]
        assert p.inferir_escala_dbm(lote_centesimas) == 100

    def test_la_escala_inferida_no_descarta_una_onu_saturada(self) -> None:
        """La saturada es justamente la que hay que ver: no puede caerse del lote."""
        lote = ["-2322", "-2050", "-1980", "-157"]  # la última, saturada
        escala = p.inferir_escala_dbm(lote)
        assert p.parsear_dbm("-157", escala) == pytest.approx(-1.57, abs=0.01)

    @pytest.mark.parametrize("crudo", ["0", "65535", "no-es-un-numero", None, ""])
    def test_valores_sin_medicion_devuelven_none_y_no_cero(self, crudo) -> None:
        """Un cero se grafica y se promedia: se convierte en una mentira."""
        assert p.parsear_dbm(crudo) is None

    def test_temperatura_y_voltaje(self) -> None:
        assert p.parsear_temperatura("42") == 42.0
        assert p.parsear_temperatura("4200") == 42.0
        assert p.parsear_voltaje("3300") == 3.3
        assert p.parsear_voltaje("3.3") == 3.3

    def test_una_fecha_ilegible_no_se_reemplaza_por_hoy(self) -> None:
        assert p.parsear_fecha("cualquier cosa") is None
        assert p.parsear_fecha("0") is None
        assert p.parsear_fecha("2026-08-01 09:15:00") is not None

    @pytest.mark.parametrize(
        ("descripcion", "esperado"),
        [
            ("GPON0/2:15", (2, 15)),
            ("gpon 0/2:15", (2, 15)),
            ("CLI1042-CDO3-NAP07 GPON0/3:7", (3, 7)),
            ("GE0/1", None),
        ],
    )
    def test_referencias_desde_el_nombre_de_interfaz(self, descripcion, esperado) -> None:
        assert p.ref_desde_descripcion(descripcion) == esperado


class TestFormatoDelEquipoReal:
    """Formatos capturados de una V1600G1 con firmware V2.3.1R.

    Son datos de primera mano, no supuestos. Cada uno corrigió algo que el
    driver hacía mal contra el equipo de verdad.
    """

    def test_el_modelo_llega_en_hexadecimal_y_se_decodifica(self) -> None:
        """net-snmp publica en hex toda cadena con bytes no imprimibles.

        La V1600G1 rellena el modelo con un cero final, así que su nombre viaja
        como "56 31 36 30 30 47 31 00". Sin decodificar, la interfaz mostraba
        esa tirada de hexadecimales en vez de "V1600G1".
        """
        from gpon_module.drivers.transport.snmp import decodificar

        assert decodificar("Hex-STRING", "56 31 36 30 30 47 31 00") == "V1600G1"

    def test_los_acentos_del_nombre_sobreviven(self) -> None:
        from gpon_module.drivers.transport.snmp import decodificar

        crudo = "5A 6F 6E 61 5F 42 C2 BA 5F 42 65 6C 67 72 61 6E"
        assert decodificar("Hex-STRING", crudo) == "Zona_Bº_Belgran"

    def test_una_cadena_normal_no_se_toca(self) -> None:
        from gpon_module.drivers.transport.snmp import decodificar

        assert decodificar("STRING", "V2.3.1R") == "V2.3.1R"

    @pytest.mark.parametrize(
        ("crudo", "esperado"),
        [("-25.378(dBm)", -25.38), ("1.914(dBm)", 1.91)],
    )
    def test_las_potencias_vienen_con_la_unidad_puesta(self, crudo, esperado) -> None:
        """Este firmware ya publica dBm: aplicarle una escala sería arruinarlo."""
        assert p.parsear_dbm(crudo) == pytest.approx(esperado, abs=0.01)

    def test_temperatura_y_voltaje_con_unidad(self) -> None:
        assert p.parsear_temperatura("34.801(C)") == 34.8
        assert p.parsear_voltaje("3.44(V)") == 3.44

    def test_con_unidad_explicita_no_se_infiere_ninguna_escala(self) -> None:
        assert p.inferir_escala_dbm(["-25.378(dBm)", "-22.100(dBm)"]) == 1

    def test_la_escala_pasada_no_pisa_a_la_unidad_explicita(self) -> None:
        """Aunque alguien pase una escala, la unidad del equipo manda."""
        assert p.parsear_dbm("-25.378(dBm)", 100) == pytest.approx(-25.38, abs=0.01)

    def test_el_uptime_real_del_equipo(self) -> None:
        assert p.parsear_uptime("(1122823048) 129 days, 22:57:10.48") == 11228230

    def test_inventario_completo_con_el_formato_real(self) -> None:
        driver = _driver(cantidad_pon=8, onus_por_pon=4, con_unidades=True)
        lecturas = driver.get_signals()
        con_lectura = [le for le in lecturas if le.rx_onu_dbm is not None]
        assert con_lectura
        assert all(-40 <= le.rx_onu_dbm <= 10 for le in con_lectura)


class TestSondeo:
    def test_devuelve_crudo_e_interpretado_para_poder_verificar(self) -> None:
        muestras = _driver().sondear()
        descripciones = [m.descripcion for m in muestras]

        assert "Modelo" in descripciones
        assert any("RX" in d for d in descripciones)
        # El OID engañoso aparece marcado, para que nadie lo tome por temperatura.
        enganoso = next(m for m in muestras if "engañoso" in m.descripcion)
        assert "NO" in enganoso.descripcion or "no lo usa" in enganoso.nota

    def test_informa_la_cobertura_de_la_rama_de_seriales(self) -> None:
        """Su disponibilidad varía entre modelos y firmwares: el sondeo la mide."""
        muestras = _driver().sondear()
        serial = next(m for m in muestras if "Serial" in m.descripcion)
        assert "de" in (serial.crudo or "")

    def test_muestra_una_onu_caida_para_ver_el_motivo(self) -> None:
        """Una ONU en línea no publica motivo de caída: hay que mirar una caída."""
        muestras = _driver(cantidad_pon=8, onus_por_pon=6).sondear()
        assert any("CAÍDA" in m.descripcion and "motivo" in m.descripcion for m in muestras)
