"""Del número de cliente al alta completa.

Lo que se protege acá es que la propuesta sea **honesta**: que complete lo que
puede, que avise lo que no, y que no invente nada en el medio. Un campo mal
completado en silencio es peor que un campo vacío, porque nadie lo revisa.
"""

from __future__ import annotations

import pytest

from gpon_module.core.errors import NoEncontrado
from gpon_module.core.models import Cliente, Perfiles, PerfilTrafico
from gpon_module.drivers.vsol.comandos_alta import SolicitudAlta
from gpon_module.drivers.vsol.planes_conocidos import PLANES_ERLAN
from gpon_module.services.propuesta_alta import ServicioPropuestaAlta

#: El cliente 034716 de ERLAN, tal como está cargado en Pucará.
CABRERA = Cliente(
    numero="034716",
    nombre="CABRERA JONAS LAZARO MARIANO",
    plan="INTERNET 10 MB",
    tipo_servicio="fibra",
    estado="activo",
    megabits_bajada=10,
    sitio="PUERTOSANCHEZ",
    cdo=8,
    nap=3,
    pppoe_usuario="034716",
    pppoe_password="fdcc",
    modelo_equipo="V2802DAC",
    numero_serie="GPON00780CBB",
)


class RepositorioClientesFalso:
    disponible = True

    def __init__(self, cliente: Cliente | None = CABRERA) -> None:
        self._cliente = cliente

    def buscar(self, numero: str) -> Cliente:
        if self._cliente is None or self._cliente.numero != numero.strip():
            raise NoEncontrado(f"No hay cliente {numero}")
        return self._cliente


class RepositorioPerfilesFalso:
    def __init__(self, nombres: tuple[str, ...] = PLANES_ERLAN) -> None:
        self._nombres = nombres

    def obtener_de_olt(self, _olt_id: int) -> Perfiles:
        return Perfiles(trafico=tuple(PerfilTrafico(nombre=n) for n in self._nombres))


@pytest.fixture
def armar():
    def _armar(cliente: Cliente | None = CABRERA, planes: tuple[str, ...] = PLANES_ERLAN):
        return ServicioPropuestaAlta(
            repositorio_clientes=RepositorioClientesFalso(cliente),
            repositorio_perfiles=RepositorioPerfilesFalso(planes),
        )

    return _armar


class TestAutocompletado:
    def test_completa_todo_lo_que_el_operador_tipearia(self, armar) -> None:
        propuesta = armar().proponer(1, "034716")

        assert propuesta.perfil_onu == "V2802DAC"
        assert propuesta.trafico_bajada == "10M-Dom-Dow"
        assert propuesta.trafico_subida == "10M-Dom-UP"
        assert propuesta.pppoe_usuario == "034716"
        assert propuesta.pppoe_password == "fdcc"
        assert propuesta.vlan == 1001
        assert propuesta.completa
        assert propuesta.advertencias == ()

    def test_la_descripcion_lleva_cliente_cdo_y_nap(self, armar) -> None:
        """``GPON0/2:3_035235_CDO21_NAP2`` es como ERLAN nombra sus ONU."""
        propuesta = armar().proponer(1, "034716")

        assert propuesta.sufijo_descripcion == "034716_CDO8_NAP3"

    def test_la_descripcion_final_la_arma_el_alta_con_puerto_e_indice(self, armar) -> None:
        propuesta = armar().proponer(1, "034716")

        solicitud = SolicitudAlta(
            pon=2,
            onu_id=3,
            numero_serie="GPON002E64F8",
            perfil_onu=propuesta.perfil_onu,
            sufijo_descripcion=propuesta.sufijo_descripcion,
        )

        assert solicitud.descripcion_efectiva == "GPON0/2:3_034716_CDO8_NAP3"

    def test_la_vlan_se_puede_cambiar(self, armar) -> None:
        """1001 es un valor por defecto, no una regla del módulo."""
        propuesta = armar().proponer(1, "034716", vlan=1002)

        assert propuesta.vlan == 1002

    def test_un_cliente_que_no_existe_lo_dice(self, armar) -> None:
        with pytest.raises(NoEncontrado):
            armar().proponer(1, "999999")


class TestHonestidad:
    def test_sin_plan_en_la_olt_avisa_y_no_completa(self, armar) -> None:
        """No proponer nada es correcto; proponer el parecido fue el bug."""
        servicio = armar(planes=("100M-Dom-DOW", "100M-Dom-UP"))

        propuesta = servicio.proponer(1, "034716")

        assert propuesta.trafico_bajada == ""
        assert not propuesta.completa
        assert any("10 MB" in a for a in propuesta.advertencias)

    def test_sin_modelo_de_onu_pide_cargarlo_a_mano(self, armar) -> None:
        propuesta = armar(Cliente(numero="1", megabits_bajada=10, cdo=1, nap=1)).proponer(1, "1")

        assert propuesta.perfil_onu == ""
        assert any("modelo de ONU" in a for a in propuesta.advertencias)

    def test_sin_pppoe_avisa(self, armar) -> None:
        sin_credenciales = Cliente(numero="1", megabits_bajada=10, modelo_equipo="V2802DAC",
                                   cdo=1, nap=1)

        propuesta = armar(sin_credenciales).proponer(1, "1")

        assert any("PPPoE" in a for a in propuesta.advertencias)

    def test_sin_cdo_ni_nap_la_descripcion_queda_con_el_cliente_solo(self, armar) -> None:
        """Media ubicación es peor que ninguna: parece completa."""
        sin_nap = Cliente(numero="034716", megabits_bajada=10, modelo_equipo="V2802DAC",
                          pppoe_usuario="x", pppoe_password="y")

        propuesta = armar(sin_nap).proponer(1, "034716")

        assert propuesta.sufijo_descripcion == "034716"
        assert any("NAP" in a for a in propuesta.advertencias)

    def test_un_cliente_dado_de_baja_avisa_pero_no_bloquea(self, armar) -> None:
        """Puede ser una reconexión, que es legítima. Pero tiene que verse."""
        de_baja = Cliente(
            numero="034716", plan="INTERNET 10 MB", megabits_bajada=10, estado="baja",
            modelo_equipo="V2802DAC", pppoe_usuario="x", pppoe_password="y", cdo=1, nap=1,
        )

        propuesta = armar(de_baja).proponer(1, "034716")

        assert propuesta.completa
        assert any("baja" in a for a in propuesta.advertencias)


class TestDisponibilidad:
    def test_sin_sistema_comercial_el_servicio_lo_declara(self) -> None:
        """El alta a mano tiene que poder hacerse igual."""
        servicio = ServicioPropuestaAlta(
            repositorio_clientes=None, repositorio_perfiles=RepositorioPerfilesFalso()
        )

        assert not servicio.disponible
