"""Lectura del ``show running-config`` de una VSOL V1600G1.

Este parser es el que resuelve lo que SNMP no puede dar en estos equipos: el
número de serie de cada ONU. Los fragmentos de acá reproducen la estructura de
la configuración real de la OLT de ERLAN —284 ONU en 8 puertos PON— con datos
inventados: ni seriales, ni descripciones, ni contraseñas de clientes reales
entran al repositorio.
"""

from __future__ import annotations

from gpon_module.drivers.vsol.parser_config import parsear_running_config

CONFIGURACION = """Current configuration:
!
!Software Version      : V2.3.1R
!Software Created Time : 25/01/2024
!
hostname Zona_Norte
password unaClave
!
vlan 1
exit
vlan 200 - 203
vlan 300
exit
vlan 1001 - 1002
!
interface gigabitethernet 0/1
switchport mode hybrid
exit
!
interface gpon 0/1
no shutdown
mdi force
exit
!
profile dba id 1 name Internet
type 4 maximum 300000
exit
!
profile dba id 511 name default1
type 5 fixed 300000 assured 300000 maximum 1000000
exit
!
profile traffic id 1 name 5M-Dom-Dow
exit
profile traffic id 2 name 5M-Dom-Up
exit
!
interface gpon 0/1
no onu auto-learn
onu add 1 profile V2801RGW sn GPON00AAAA01
onu 1 desc GPON0/1:1_000001_NAP2
onu 1 tcont 1 name Internet dba Internet
onu 1 gemport 1 tcont 1 gemport_name Internet
onu 1 gemport 1 traffic-limit upstream 20M-Dom-UP downstream 20M-Dom-DOW
onu 1 service Internet gemport 1 vlan 1001
onu 1 service-port 1 gemport 1 uservlan 1001 vlan 1001
onu 1 portvlan veip 1 mode transparent
onu 1 pri equid VSOLV411
onu 1 pri wan_adv index 1 route ipv4 pppoe proxy disable user 000001 pwd secreta server FTTH
onu 1 pri dhcp_server 192.168.0.1 255.255.255.0 enable 86400
onu add 2 profile V2802DAC sn VSOL0000AA02
onu 2 tcont 1 dba Internet
onu 2 gemport 1 traffic-limit upstream 100M-Dom-UP downstream 100M-Dom-DOW
onu 2 service Internet gemport 1 vlan 1002
exit
!
interface gpon 0/2
onu add 7 profile V2802GW sn GPON00BBBB07
onu 7 desc GPON0/2:7_000007
onu 7 tcont 1 name Internet dba Asegurada_100M
onu 7 service PtP gemport 1 vlan 300
exit
!
"""


class TestInventario:
    def test_saca_el_serial_de_cada_onu(self) -> None:
        """Es la razón de ser del parser: por SNMP el serial no existe."""
        config = parsear_running_config(CONFIGURACION)

        series = config.series_por_ref
        assert series[(1, 1)] == "GPON00AAAA01"
        assert series[(1, 2)] == "VSOL0000AA02"
        assert series[(2, 7)] == "GPON00BBBB07"

    def test_junta_las_directivas_sueltas_de_cada_onu(self) -> None:
        """Los datos de una ONU llegan repartidos en ocho o diez líneas."""
        config = parsear_running_config(CONFIGURACION)
        onu = next(o for o in config.onus if (o.pon, o.onu_id) == (1, 1))

        assert onu.perfil == "V2801RGW"
        assert onu.descripcion == "GPON0/1:1_000001_NAP2"
        assert onu.perfil_dba == "Internet"
        assert onu.vlan == 1001
        assert onu.trafico_subida == "20M-Dom-UP"
        assert onu.trafico_bajada == "20M-Dom-DOW"

    def test_el_tcont_sin_nombre_tambien_se_entiende(self) -> None:
        """La misma OLT escribe las dos formas: con 'name' y sin él."""
        config = parsear_running_config(CONFIGURACION)
        onu = next(o for o in config.onus if (o.pon, o.onu_id) == (1, 2))

        assert onu.perfil_dba == "Internet"
        assert onu.vlan == 1002

    def test_una_onu_sin_descripcion_no_rompe_nada(self) -> None:
        config = parsear_running_config(CONFIGURACION)
        onu = next(o for o in config.onus if (o.pon, o.onu_id) == (1, 2))

        assert onu.descripcion == ""
        assert onu.numero_serie == "VSOL0000AA02"


class TestPrivacidad:
    def test_no_se_guarda_la_contrasena_pppoe_del_cliente(self) -> None:
        """Está en la configuración, en texto plano. No hay razón para guardarla.

        Que el módulo pueda leerla no significa que deba: hoy no la necesita
        para nada, y una base con las credenciales PPPoE de todos los clientes
        es un problema que conviene no crear.
        """
        config = parsear_running_config(CONFIGURACION)

        texto = repr(config)
        assert "secreta" not in texto
        assert "pppoe" not in texto.lower()
        assert "dhcp" not in texto.lower()


class TestPerfilesYVlan:
    def test_lee_los_perfiles_dba_con_su_ancho_de_banda(self) -> None:
        config = parsear_running_config(CONFIGURACION)

        por_nombre = {p.nombre: p for p in config.perfiles_dba}
        assert por_nombre["Internet"].maximo_kbps == 300000
        assert por_nombre["default1"].fijo_kbps == 300000
        assert por_nombre["default1"].asegurado_kbps == 300000

    def test_lee_los_perfiles_de_trafico(self) -> None:
        config = parsear_running_config(CONFIGURACION)

        assert [p.nombre for p in config.perfiles_trafico] == ["5M-Dom-Dow", "5M-Dom-Up"]

    def test_expande_los_rangos_de_vlan(self) -> None:
        """'vlan 200 - 203' son cuatro VLAN, no dos."""
        config = parsear_running_config(CONFIGURACION)

        assert config.vlans == (1, 200, 201, 202, 203, 300, 1001, 1002)


class TestPuertosPON:
    def test_lista_los_puertos_pon(self) -> None:
        config = parsear_running_config(CONFIGURACION)
        assert config.puertos_pon == ("0/1", "0/2")

    def test_marca_los_puertos_sin_autoaprendizaje(self) -> None:
        """Sin autoaprendizaje, una ONU nueva no aparece sola: hay que darla de alta."""
        config = parsear_running_config(CONFIGURACION)
        assert config.pon_sin_autoaprendizaje == ("0/1",)

    def test_una_interfaz_que_no_es_pon_cierra_la_seccion(self) -> None:
        """Si no, las líneas de un puerto ethernet se leerían como ONU."""
        config = parsear_running_config(CONFIGURACION)
        assert all(onu.pon in (1, 2) for onu in config.onus)


class TestTolerancia:
    def test_una_directiva_desconocida_no_hace_fallar_la_lectura(self) -> None:
        """Otro firmware agrega líneas nuevas; perder 284 ONU por una sería peor."""
        config = parsear_running_config(
            CONFIGURACION + "\ninterface gpon 0/3\nonu add 1 profile X sn GPON1\n"
            "onu 1 directiva-que-no-existe con parametros raros\nexit\n"
        )

        assert config.series_por_ref[(3, 1)] == "GPON1"

    def test_una_directiva_de_una_onu_no_declarada_se_descarta(self) -> None:
        """Sin 'onu add' no hay serial, y una entrada sin serial es un fantasma."""
        config = parsear_running_config(
            "interface gpon 0/4\nonu 9 desc suelta\nonu 9 service X gemport 1 vlan 5\nexit\n"
        )

        assert config.onus == ()

    def test_una_configuracion_vacia_no_explota(self) -> None:
        config = parsear_running_config("")
        assert config.onus == ()
        assert config.nombre_equipo == ""


class TestIdentidad:
    def test_toma_el_nombre_y_el_firmware_del_equipo(self) -> None:
        config = parsear_running_config(CONFIGURACION)

        assert config.nombre_equipo == "Zona_Norte"
        assert config.firmware == "V2.3.1R"
