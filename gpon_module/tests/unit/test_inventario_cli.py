"""Completar el inventario con los seriales que sólo da la CLI.

La regla que se protege acá: la configuración **completa** lo que SNMP dejó
vacío, y no inventa entradas. Una ONU que está en la configuración pero que
SNMP no vio se informa, no se crea: puede estar dada de alta y todavía sin
conectar, y meterla al inventario como si estuviera activa sería mentir.
"""

from __future__ import annotations

import pytest

from gpon_module.core.enums import EstadoONU, Fabricante
from gpon_module.core.errors import CapacidadNoSoportada
from gpon_module.core.models import OLT, ONU, CredencialesOLT, RefONU
from gpon_module.drivers.vsol.parser_config import parsear_running_config
from gpon_module.services.inventario_cli import ServicioInventarioCLI

CONFIGURACION = """
vlan 1001
exit
!
interface gpon 0/1
onu add 1 profile V2801RGW sn GPON00AAAA01
onu 1 desc CLIENTE-000001
onu 1 tcont 1 name Internet dba Internet
onu 1 service Internet gemport 1 vlan 1001
onu add 2 profile V2802DAC sn GPON00AAAA02
exit
!
profile dba id 1 name Internet
type 4 maximum 300000
exit
"""


class RepositorioOLTFalso:
    def obtener(self, _olt_id: int) -> OLT:
        return OLT(id=1, nombre="Belgrano", host="10.0.0.1", fabricante=Fabricante.VSOL)

    def obtener_credenciales(self, _olt_id: int) -> CredencialesOLT:
        return CredencialesOLT(usuario="eaguiar", password="x")


class RepositorioONUFalso:
    def __init__(self, existentes: list[ONU]) -> None:
        self.por_ref = {(o.pon, o.onu_id): o for o in existentes}
        self.guardadas: list[ONU] = []

    def obtener_por_ref(self, _olt_id: int, ref: RefONU) -> ONU | None:
        return self.por_ref.get((ref.pon, ref.onu_id))

    def guardar(self, onu: ONU) -> ONU:
        self.guardadas.append(onu)
        return onu


class RepositorioPerfilesFalso:
    def __init__(self) -> None:
        self.guardados = None

    def reemplazar_de_olt(self, _olt_id: int, perfiles):
        self.guardados = perfiles
        return perfiles


@pytest.fixture
def armar():
    def _armar(existentes: list[ONU]):
        onus = RepositorioONUFalso(existentes)
        perfiles = RepositorioPerfilesFalso()
        servicio = ServicioInventarioCLI(
            repositorio_olt=RepositorioOLTFalso(),
            repositorio_onu=onus,
            repositorio_perfiles=perfiles,
        )
        return servicio, onus, perfiles

    return _armar


class TestCompletado:
    def test_le_pone_el_serial_a_una_onu_que_no_lo_tenia(self, armar) -> None:
        """Es lo que SNMP no puede dar, y sin eso no se identifica a un cliente."""
        existente = ONU(id=5, olt_id=1, ref=RefONU(1, 1), estado=EstadoONU.EN_LINEA)
        servicio, onus, _ = armar([existente])

        resultado = servicio.aplicar(1, parsear_running_config(CONFIGURACION))

        assert resultado.series_nuevas == 1
        assert onus.guardadas[0].numero_serie == "GPON00AAAA01"
        assert onus.guardadas[0].descripcion == "CLIENTE-000001"
        assert onus.guardadas[0].vlan == 1001

    def test_no_pisa_el_estado_que_trajo_snmp(self, armar) -> None:
        """La configuración dice cómo está dada de alta, no cómo está andando."""
        existente = ONU(id=5, olt_id=1, ref=RefONU(1, 1), estado=EstadoONU.FUERA_DE_LINEA)
        servicio, onus, _ = armar([existente])

        servicio.aplicar(1, parsear_running_config(CONFIGURACION))

        assert onus.guardadas[0].estado is EstadoONU.FUERA_DE_LINEA

    def test_una_onu_que_snmp_no_vio_se_informa_pero_no_se_crea(self, armar) -> None:
        servicio, onus, _ = armar([])

        resultado = servicio.aplicar(1, parsear_running_config(CONFIGURACION))

        assert onus.guardadas == []
        assert len(resultado.onus_solo_en_configuracion) == 2
        assert "GPON00AAAA01" in resultado.onus_solo_en_configuracion[0]

    def test_no_se_reescribe_una_onu_que_ya_estaba_completa(self, armar) -> None:
        """Sin esto, cada corrida marcaría 284 ONU como modificadas sin cambio real."""
        completa = ONU(
            id=5,
            olt_id=1,
            ref=RefONU(1, 2),
            numero_serie="GPON00AAAA02",
            perfil_servicio="V2802DAC",
        )
        servicio, onus, _ = armar([completa])

        resultado = servicio.aplicar(1, parsear_running_config(CONFIGURACION))

        assert onus.guardadas == []
        assert resultado.onus_actualizadas == 0

    def test_guarda_los_perfiles_dba_y_las_vlan(self, armar) -> None:
        servicio, _, perfiles = armar([])

        servicio.aplicar(1, parsear_running_config(CONFIGURACION))

        assert [p.nombre for p in perfiles.guardados.dba] == ["Internet"]
        assert [v.vlan_id for v in perfiles.guardados.vlans] == [1001]


class TestLimites:
    def test_un_fabricante_sin_parser_lo_dice_en_vez_de_intentarlo(self) -> None:
        class RepositorioZTE(RepositorioOLTFalso):
            def obtener(self, _olt_id: int) -> OLT:
                return OLT(id=1, host="10.0.0.1", fabricante=Fabricante.SIMULADO)

        servicio = ServicioInventarioCLI(
            repositorio_olt=RepositorioZTE(),
            repositorio_onu=RepositorioONUFalso([]),
            repositorio_perfiles=RepositorioPerfilesFalso(),
        )

        with pytest.raises(CapacidadNoSoportada):
            servicio.importar(1)
