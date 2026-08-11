"""La WAN de un CPE, tal como la reporta la OLT de Belgrano.

La salida es la **real** de la ONU 1, que es un cliente que anda. Su valor no
es sólo el listado de campos: el equipo termina imprimiendo **los comandos que
recrean esa configuración**, que es la sintaxis contada por el propio firmware
y lo único confiable que hay para escribirla.
"""

from __future__ import annotations

import pytest

from gpon_module.drivers.vsol.parser_wan import (
    ConfigWANLeida,
    mascara_de,
    nombres_de,
    parsear_wan_conn_show,
)

WAN_ONU1 = """wanNumber:1
********************************
wanIndex            : 1
bindingLan          : lan1
bindingSsid         : ssid1 ssid2 ssid3 ssid4
wanMode             : internet
wanConnType         : route
wanVlanId           : 1001
wanCos              : 0
wanNatEnable        : enable
wanConnMode         : PPPOE
pppoeProxy          : disable
pppoeUserName       : esc_mitre_88
pppoePassword       : a1b1
pppoeServName       : FTTH
pppoeMode           : Auto connect
wanMTU              : 1492
qosEnable           : enable
wanName             : 1_INTERNET_R_VID
wanStatus           : connected
onu 1 pri wan_conn add routeQOS enable
onu 1 pri wan_conn index 1 route internet bind_lan 1 bind_ssid 15 qos enable \
nat enable mtu 1492 pppoe proxy disable user esc_mitre_88 pwd a1b1 server FTTH mode auto"""


class TestLectura:
    def test_lee_los_datos_del_servicio(self) -> None:
        wan = parsear_wan_conn_show(WAN_ONU1)[0]

        assert wan.indice == 1
        assert wan.vlan == 1001
        assert wan.mtu == 1492
        assert wan.modo_conexion == "PPPOE"
        assert wan.tipo_conexion == "route"
        assert wan.modo_servicio == "internet"

    def test_lee_las_credenciales_pppoe(self) -> None:
        """Son las que hay que poder escribir para dar de alta a un cliente."""
        wan = parsear_wan_conn_show(WAN_ONU1)[0]

        assert wan.pppoe_usuario == "esc_mitre_88"
        assert wan.pppoe_password == "a1b1"
        assert wan.pppoe_servicio == "FTTH"

    def test_dice_si_la_conexion_esta_levantada(self) -> None:
        assert parsear_wan_conn_show(WAN_ONU1)[0].conectada

    def test_una_salida_vacia_no_rompe(self) -> None:
        assert parsear_wan_conn_show("") == []

    def test_un_cpe_con_varias_wan_las_devuelve_todas(self) -> None:
        """Quedarse con la primera daría una foto incompleta en los que tienen
        teléfono, que es justo donde importa no equivocarse."""
        dos = WAN_ONU1 + "\n********************************\nwanIndex : 2\nwanMode : voip\n"

        conexiones = parsear_wan_conn_show(dos)

        assert [c.indice for c in conexiones] == [1, 2]
        assert conexiones[1].modo_servicio == "voip"


class TestComandosQueImprimeElEquipo:
    """Lo más valioso de esta salida: el firmware dicta su propia sintaxis."""

    def test_se_guardan_los_comandos_reproducibles(self) -> None:
        wan = parsear_wan_conn_show(WAN_ONU1)[0]

        assert len(wan.comandos_eco) == 2
        assert wan.comandos_eco[1].startswith("onu 1 pri wan_conn index 1 route internet")

    def test_se_guardan_crudos_sin_interpretar(self) -> None:
        """Retocarlos al leerlos sería perder la única fuente confiable."""
        wan = parsear_wan_conn_show(WAN_ONU1)[0]

        assert "user esc_mitre_88 pwd a1b1 server FTTH mode auto" in wan.comandos_eco[1]


class TestMascaras:
    """El equipo muestra nombres y recibe bits. Hay que poder ir y volver."""

    @pytest.mark.parametrize(
        ("nombres", "mascara"),
        [
            ("lan1", 1),
            ("lan1 lan2", 3),
            ("ssid1 ssid2 ssid3 ssid4", 15),
            ("ssid1 ssid2 ssid3 ssid4 ssid5 ssid6 ssid7 ssid8", 255),
            ("ssid5", 16),
            ("", 0),
        ],
    )
    def test_de_nombres_a_mascara(self, nombres, mascara) -> None:
        assert mascara_de(nombres) == mascara

    def test_la_onu_1_confirma_la_lectura(self) -> None:
        """``bindingSsid: ssid1..4`` se escribe ``bind_ssid 15`` en el mismo
        volcado. Es la comprobación cruzada que valida la interpretación."""
        wan = parsear_wan_conn_show(WAN_ONU1)[0]

        assert wan.mascara_lan == 1
        assert wan.mascara_ssid == 15
        assert "bind_lan 1 bind_ssid 15" in wan.comandos_eco[1]

    def test_de_mascara_a_nombres(self) -> None:
        assert nombres_de(15, "ssid") == "ssid1 ssid2 ssid3 ssid4"
        assert nombres_de(3, "lan", cantidad=2) == "lan1 lan2"

    def test_un_nombre_raro_no_rompe_la_mascara(self) -> None:
        assert mascara_de("lan1 loquesea ssid2") == 0b11


class TestSecretos:
    def test_la_contrasena_no_se_filtra_al_imprimir(self) -> None:
        """Esta salida trae la clave PPPoE de un cliente en texto plano."""
        wan = parsear_wan_conn_show(WAN_ONU1)[0]

        assert "a1b1" not in repr(wan)
        assert "***" in repr(ConfigWANLeida(pppoe_password="secreta"))
