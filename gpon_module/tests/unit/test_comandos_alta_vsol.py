"""La secuencia de alta de una ONU en la VSOL.

Estos comandos son los únicos del módulo que **cambian** algo en un equipo con
clientes conectados. Los tests fijan dos cosas: que la secuencia sea exactamente
la que el equipo escribe en su propia configuración, y que nada dudoso llegue a
convertirse en un comando.
"""

from __future__ import annotations

import pytest

from gpon_module.core.errors import ErrorValidacion
from gpon_module.drivers.vsol.comandos_alta import (
    SolicitudAlta,
    primer_indice_libre,
    secuencia_alta,
    secuencia_baja,
)

#: Un alta como las 284 que ya tiene la OLT de ERLAN, con datos inventados.
SOLICITUD = SolicitudAlta(
    pon=1,
    onu_id=29,
    numero_serie="GPON002E64F8",
    perfil_onu="V2802DAC",
    descripcion="GPON0/1:29_040001",
    perfil_dba="Internet",
    trafico_subida="100M-Dom-UP",
    trafico_bajada="100M-Dom-DOW",
    vlan=1001,
)


class TestSecuencia:
    def test_es_la_misma_que_escribe_el_equipo(self) -> None:
        """Comparada línea por línea con el running-config de una ONU real."""
        assert secuencia_alta(SOLICITUD) == (
            "configure terminal",
            "interface gpon 0/1",
            "onu add 29 profile V2802DAC sn GPON002E64F8",
            "onu 29 desc GPON0/1:29_040001",
            "onu 29 tcont 1 name Internet dba Internet",
            "onu 29 gemport 1 tcont 1 gemport_name Internet",
            "onu 29 gemport 1 traffic-limit upstream 100M-Dom-UP downstream 100M-Dom-DOW",
            "onu 29 service Internet gemport 1 vlan 1001",
            "onu 29 service-port 1 gemport 1 uservlan 1001 vlan 1001",
            "onu 29 service-port 1 description Internet",
            "onu 29 portvlan veip 1 mode transparent",
            "end",
        )

    def test_empieza_entrando_al_puerto_y_termina_saliendo(self) -> None:
        """Quedarse en modo configuración deja la sesión en un estado raro."""
        comandos = secuencia_alta(SOLICITUD)

        assert comandos[0] == "configure terminal"
        assert comandos[1] == "interface gpon 0/1"
        assert comandos[-1] == "end"

    def test_sin_plan_de_trafico_no_se_manda_el_comando_vacio(self) -> None:
        """Sin plan la ONU queda con el ancho del DBA; mandarlo vacío es mandarlo mal."""
        comandos = secuencia_alta(
            SolicitudAlta(pon=1, onu_id=29, numero_serie="GPON002E64F8", perfil_onu="V2802DAC")
        )

        assert not any("traffic-limit" in c for c in comandos)
        assert any("onu 29 service Internet" in c for c in comandos)

    def test_sin_descripcion_se_arma_una_coherente_con_el_parque(self) -> None:
        comandos = secuencia_alta(
            SolicitudAlta(pon=7, onu_id=3, numero_serie="GPON002E64F8", perfil_onu="V2802DAC")
        )

        assert "onu 3 desc GPON0/7:3" in comandos


class TestValidacion:
    """Lo que no puede pasar de acá.

    Un comando mal formado en modo configuración no devuelve un error prolijo:
    deja una ONU a medio dar de alta, con un cliente sin servicio.
    """

    @pytest.mark.parametrize("serie", ["", "GPON", "no-es-un-serial", "GPON002E64F8 extra"])
    def test_un_serial_mal_tipeado_no_llega_al_equipo(self, serie: str) -> None:
        """El serial lo tipea un técnico y llega por mensaje. Es el dato más frágil."""
        with pytest.raises(ErrorValidacion, match="serie"):
            secuencia_alta(
                SolicitudAlta(pon=1, onu_id=1, numero_serie=serie, perfil_onu="V2802DAC")
            )

    @pytest.mark.parametrize("indice", [0, -1, 129, 999])
    def test_un_indice_fuera_de_rango_se_rechaza(self, indice: int) -> None:
        with pytest.raises(ErrorValidacion, match="índice"):
            secuencia_alta(
                SolicitudAlta(
                    pon=1, onu_id=indice, numero_serie="GPON002E64F8", perfil_onu="V2802DAC"
                )
            )

    @pytest.mark.parametrize(
        "perfil", ["perfil con espacios", "perfil\nsegunda-linea", "a;reboot", "b`c`"]
    )
    def test_un_nombre_con_caracteres_raros_no_puede_partir_el_comando(self, perfil: str) -> None:
        """Un espacio de más convierte un comando en dos."""
        with pytest.raises(ErrorValidacion):
            secuencia_alta(
                SolicitudAlta(pon=1, onu_id=1, numero_serie="GPON002E64F8", perfil_onu=perfil)
            )

    def test_una_descripcion_con_espacios_se_rechaza(self) -> None:
        with pytest.raises(ErrorValidacion, match="descripción"):
            secuencia_alta(
                SolicitudAlta(
                    pon=1,
                    onu_id=1,
                    numero_serie="GPON002E64F8",
                    perfil_onu="V2802DAC",
                    descripcion="Cliente Juan Perez",
                )
            )

    def test_una_vlan_fuera_de_rango_se_rechaza(self) -> None:
        with pytest.raises(ErrorValidacion, match="VLAN"):
            secuencia_alta(
                SolicitudAlta(
                    pon=1, onu_id=1, numero_serie="GPON002E64F8", perfil_onu="V2802DAC", vlan=9999
                )
            )


class TestBaja:
    def test_la_baja_usa_la_forma_que_declara_el_equipo(self) -> None:
        assert secuencia_baja(pon=3, onu_id=17) == (
            "configure terminal",
            "interface gpon 0/3",
            "no onu 17",
            "end",
        )

    def test_un_indice_invalido_no_llega_al_equipo(self) -> None:
        with pytest.raises(ErrorValidacion):
            secuencia_baja(pon=3, onu_id=0)


class TestIndiceLibre:
    def test_reusa_el_hueco_mas_bajo(self) -> None:
        """En el PON 1 de ERLAN el 29 quedó libre entre el 28 y el 30."""
        ocupados = set(range(1, 29)) | set(range(30, 46))

        assert primer_indice_libre(ocupados) == 29

    def test_en_un_puerto_vacio_arranca_en_uno(self) -> None:
        assert primer_indice_libre(set()) == 1

    def test_un_puerto_lleno_lo_dice_en_vez_de_devolver_algo_invalido(self) -> None:
        with pytest.raises(ErrorValidacion, match="no tiene índices libres"):
            primer_indice_libre(set(range(1, 129)))
