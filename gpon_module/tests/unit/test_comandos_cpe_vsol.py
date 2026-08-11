"""Los comandos que configuran el CPE.

La prueba que más vale de todo este archivo es una sola: que lo que el módulo
arma para la ONU 1 sea **idéntico** a lo que el propio equipo imprime para esa
misma ONU. No es un test contra una expectativa escrita a mano, es un test
contra el firmware.
"""

from __future__ import annotations

import pytest

from gpon_module.core.errors import ErrorValidacion
from gpon_module.drivers.vsol.comandos_cpe import (
    SolicitudRadio,
    SolicitudSSID,
    SolicitudWAN,
    comando_guardar,
    comando_radio,
    comando_ssid,
    secuencia_wan,
)

#: La línea que imprime `onu 1 pri wan_conn show` en la OLT de Belgrano.
ECO_DEL_EQUIPO = (
    "onu 1 pri wan_conn index 1 route internet bind_lan 1 bind_ssid 15 "
    "qos enable nat enable mtu 1492 pppoe proxy disable "
    "user esc_mitre_88 pwd a1b1 server FTTH mode auto"
)

ONU1 = SolicitudWAN(
    onu_id=1,
    indice=1,
    bind_lan=1,
    bind_ssid=15,
    pppoe_usuario="esc_mitre_88",
    pppoe_password="a1b1",
    pppoe_servicio="FTTH",
)


class TestLaWANContraElEquipo:
    def test_reproduce_exacto_lo_que_imprime_el_firmware(self) -> None:
        """Si esto se rompe, el comando dejó de ser el que el equipo acepta."""
        assert secuencia_wan(ONU1)[1] == ECO_DEL_EQUIPO

    def test_son_tres_pasos_y_el_ultimo_confirma(self) -> None:
        """Sin 'commit' la conexión queda a medio armar en el equipo."""
        comandos = secuencia_wan(ONU1)

        assert len(comandos) == 3
        assert comandos[0].endswith("wan_conn add route qos enable")
        assert comandos[2].endswith("wan_conn commit")

    def test_los_valores_por_defecto_son_para_un_cliente_nuevo(self) -> None:
        """Las dos bocas y los ocho SSID ligados, que es lo habitual."""
        nueva = SolicitudWAN(onu_id=29, pppoe_usuario="034716", pppoe_password="fdcc")

        aplicado = secuencia_wan(nueva)[1]

        assert "bind_lan 3" in aplicado
        assert "bind_ssid 255" in aplicado
        assert "mtu 1492" in aplicado
        assert "server FTTH" in aplicado


class TestLaVLAN:
    """``wan_conn index <n> vlan enable vid <id>``, verificado en la ayuda.

    Va en su propio comando y no en la línea larga: el eco del equipo no la
    incluye ahí, y `vlan enable` existe como rama aparte.
    """

    def test_la_vlan_va_en_su_propio_comando(self) -> None:
        con_vlan = secuencia_wan(
            SolicitudWAN(onu_id=29, pppoe_usuario="034716", pppoe_password="fdcc", vlan=1001)
        )

        assert len(con_vlan) == 4
        assert con_vlan[2] == "onu 29 pri wan_conn index 1 vlan enable vid 1001"
        assert con_vlan[-1].endswith("commit")

    def test_sin_vlan_no_se_emite_el_comando(self) -> None:
        """Ninguna es dejar la que el equipo tenga; no es lo mismo que 1001."""
        sin_vlan = secuencia_wan(
            SolicitudWAN(onu_id=29, pppoe_usuario="034716", pppoe_password="fdcc")
        )

        assert not any("vlan" in c for c in sin_vlan)

    def test_una_vlan_fuera_de_rango_se_rechaza(self) -> None:
        with pytest.raises(ErrorValidacion, match="VLAN"):
            secuencia_wan(
                SolicitudWAN(onu_id=1, vlan=5000, pppoe_usuario="u", pppoe_password="p")
            )


class TestValidacionDeLaWAN:
    def test_un_usuario_con_espacio_no_llega_a_la_red(self) -> None:
        """Partiría el comando en dos y el resto se leería como otra cosa."""
        with pytest.raises(ErrorValidacion, match="espacio"):
            secuencia_wan(
                SolicitudWAN(onu_id=1, pppoe_usuario="cliente 034716", pppoe_password="x")
            )

    def test_sin_credenciales_no_se_arma_nada(self) -> None:
        with pytest.raises(ErrorValidacion, match="usuario PPPoE"):
            secuencia_wan(SolicitudWAN(onu_id=1, pppoe_password="x"))

    def test_un_modo_que_el_equipo_no_conoce_se_rechaza(self) -> None:
        with pytest.raises(ErrorValidacion, match="Modo de WAN"):
            secuencia_wan(
                SolicitudWAN(onu_id=1, modo="fibra", pppoe_usuario="u", pppoe_password="p")
            )

    def test_sin_ninguna_boca_ligada_el_cliente_no_sale(self) -> None:
        with pytest.raises(ErrorValidacion, match="máscara de LAN"):
            secuencia_wan(
                SolicitudWAN(onu_id=1, bind_lan=0, pppoe_usuario="u", pppoe_password="p")
            )

    def test_un_mtu_absurdo_se_rechaza(self) -> None:
        with pytest.raises(ErrorValidacion, match="MTU"):
            secuencia_wan(
                SolicitudWAN(onu_id=1, mtu=9000, pppoe_usuario="u", pppoe_password="p")
            )

    def test_la_contrasena_no_se_filtra_al_imprimir(self) -> None:
        assert "a1b1" not in repr(ONU1)


class TestWiFi:
    def test_prende_la_radio_con_pais_y_canal(self) -> None:
        assert comando_radio(SolicitudRadio(onu_id=29, radio=1, pais="fcc")) == (
            "onu 29 pri wifi_switch 1 enable fcc auto"
        )

    def test_las_dos_radios_son_24_y_5(self) -> None:
        """``wifi_switch 1`` es la de SSID1 y ``wifi_switch 2`` la de SSID5."""
        assert "wifi_switch 2" in comando_radio(SolicitudRadio(onu_id=29, radio=2))

        with pytest.raises(ErrorValidacion, match="radio"):
            comando_radio(SolicitudRadio(onu_id=29, radio=3))

    def test_apagar_no_lleva_pais(self) -> None:
        apagada = comando_radio(SolicitudRadio(onu_id=29, radio=2, encendida=False))

        assert apagada == "onu 29 pri wifi_switch 2 disable"

    def test_un_pais_que_el_equipo_no_conoce_se_rechaza(self) -> None:
        with pytest.raises(ErrorValidacion, match="País"):
            comando_radio(SolicitudRadio(onu_id=29, pais="argentina"))

    def test_pone_el_nombre_de_la_red(self) -> None:
        assert comando_ssid(SolicitudSSID(onu_id=29, ssid=1, nombre="ERLAN-034716")) == (
            "onu 29 pri wifi_ssid 1 name ERLAN-034716 hide disable"
        )

    def test_una_red_oculta_se_pide_explicito(self) -> None:
        oculta = comando_ssid(SolicitudSSID(onu_id=29, ssid=5, nombre="Red", oculto=True))

        assert oculta.endswith("hide enable")

    def test_un_nombre_con_espacio_no_llega_a_la_red(self) -> None:
        with pytest.raises(ErrorValidacion, match="espacios"):
            comando_ssid(SolicitudSSID(onu_id=29, ssid=1, nombre="Mi Red"))

    def test_un_nombre_de_mas_de_32_se_rechaza(self) -> None:
        """El equipo declara el límite en ``name ?``."""
        with pytest.raises(ErrorValidacion):
            comando_ssid(SolicitudSSID(onu_id=29, ssid=1, nombre="R" * 33))


class TestGuardar:
    def test_el_ultimo_comando_graba_en_el_cpe(self) -> None:
        """Sin esto, todo se pierde en el primer corte de luz del cliente."""
        assert comando_guardar(29) == "onu 29 pri save_config"
