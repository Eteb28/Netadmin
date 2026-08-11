"""El motivo de caída, que decide si sale una cuadrilla o no.

DyingGasp es un corte de luz en lo del cliente y LOS es fibra cortada.
Confundirlas cuesta un viaje de ida y vuelta, así que lo que se prueba acá es
que esa distinción llegue entera desde el equipo hasta el inventario.

La salida es la **real** de la OLT de Belgrano, incluido el formato de índice
``1/1/1:7`` —que no es el ``GPON0/1:7`` de las otras tablas— y el total del pie.
"""

from __future__ import annotations

import pytest

from gpon_module.core.enums import EstadoONU, Fabricante, MotivoCaida
from gpon_module.core.errors import CapacidadNoSoportada, ErrorComando
from gpon_module.core.models import OLT, ONU, CredencialesOLT, RefONU
from gpon_module.core.reloj import RelojFijo
from gpon_module.services.estados_cli import ServicioEstadosCLI

ESTADO_PON1 = """OnuIndex    Admin State    OMCC State    Phase State    Channel
---------------------------------------------------------------
1/1/1:1     enable         enable        working         1(GPON)
1/1/1:7     enable         disable       DyingGasp       1(GPON)
1/1/1:18    enable         disable       LOS             1(GPON)
1/1/1:19    enable         disable       OffLine         1(GPON)
ONU Number: 24/44"""


class RepositorioOLTFalso:
    def obtener(self, _olt_id: int) -> OLT:
        return OLT(id=1, nombre="Belgrano", host="10.0.0.1", fabricante=Fabricante.VSOL)

    def obtener_credenciales(self, _olt_id: int) -> CredencialesOLT:
        return CredencialesOLT(usuario="eaguiar", password="x")


class RepositorioONUFalso:
    def __init__(self, existentes: list[ONU]) -> None:
        self.por_ref = {(o.ref.pon, o.ref.onu_id): o for o in existentes}
        self.guardadas: list[ONU] = []

    def obtener_por_ref(self, _olt_id: int, ref: RefONU) -> ONU | None:
        return self.por_ref.get((ref.pon, ref.onu_id))

    def guardar(self, onu: ONU) -> ONU:
        self.guardadas.append(onu)
        return onu


class TransporteFalso:
    def __init__(self, por_puerto: dict[str, str] | None = None) -> None:
        self.por_puerto = por_puerto if por_puerto is not None else {"0/1": ESTADO_PON1}
        self.ejecutados: list[str] = []
        self.pon_actual = ""
        self.cerrado = False

    def abrir(self) -> None: ...

    def cerrar(self) -> None:
        self.cerrado = True

    def ejecutar(self, comando: str) -> str:
        self.ejecutados.append(comando)
        if comando.startswith("interface gpon "):
            self.pon_actual = comando.split()[-1]
            if self.pon_actual not in self.por_puerto:
                raise ErrorComando("% Invalid input", comando=comando)
            return ""
        if comando == "show onu state":
            return self.por_puerto.get(self.pon_actual, "")
        return ""


def onu_en(pon: int, onu_id: int, estado: EstadoONU, motivo: MotivoCaida) -> ONU:
    return ONU(id=onu_id, olt_id=1, ref=RefONU(pon, onu_id), estado=estado, motivo_caida=motivo)


@pytest.fixture
def armar():
    def _armar(existentes: list[ONU], transporte: TransporteFalso | None = None):
        transporte = transporte or TransporteFalso()
        onus = RepositorioONUFalso(existentes)
        servicio = ServicioEstadosCLI(
            repositorio_olt=RepositorioOLTFalso(),
            repositorio_onu=onus,
            reloj=RelojFijo(),
            fabrica_transporte=lambda **_kwargs: transporte,
        )
        return servicio, onus, transporte

    return _armar


class TestMotivos:
    def test_distingue_corte_de_luz_de_fibra_cortada(self, armar) -> None:
        """Es la razón de ser de todo esto."""
        caidas = [
            onu_en(1, 7, EstadoONU.EN_LINEA, MotivoCaida.NINGUNO),
            onu_en(1, 18, EstadoONU.EN_LINEA, MotivoCaida.NINGUNO),
        ]
        servicio, onus, _ = armar(caidas)

        servicio.actualizar(1, puertos=("0/1",))

        guardadas = {o.ref.onu_id: o for o in onus.guardadas}
        assert guardadas[7].motivo_caida is MotivoCaida.APAGADO
        assert guardadas[18].motivo_caida is MotivoCaida.PERDIDA_SENAL

    def test_una_caida_sin_motivo_no_se_adivina(self, armar) -> None:
        """OffLine puede ser cualquiera de las dos: inventar una es peor."""
        servicio, onus, _ = armar([onu_en(1, 19, EstadoONU.EN_LINEA, MotivoCaida.NINGUNO)])

        servicio.actualizar(1, puertos=("0/1",))

        assert onus.guardadas[0].motivo_caida is MotivoCaida.DESCONOCIDO

    def test_cuenta_cuantas_hay_de_cada_motivo(self, armar) -> None:
        servicio, _, _ = armar([])

        resultado = servicio.actualizar(1, puertos=("0/1",))

        assert resultado.por_motivo == {
            "ninguno": 1,
            "apagado": 1,
            "perdida_senal": 1,
            "desconocido": 1,
        }

    def test_una_onu_que_volvio_pierde_el_motivo_anterior(self, armar) -> None:
        """Si no, el panel seguiría contando un corte de luz que ya terminó."""
        servicio, onus, _ = armar(
            [onu_en(1, 1, EstadoONU.FUERA_DE_LINEA, MotivoCaida.APAGADO)]
        )

        servicio.actualizar(1, puertos=("0/1",))

        assert onus.guardadas[0].estado is EstadoONU.EN_LINEA
        assert onus.guardadas[0].motivo_caida is MotivoCaida.NINGUNO

    def test_una_fase_desconocida_no_pisa_lo_que_ya_se_sabe(self, armar) -> None:
        """Un firmware con una fase nueva no debe vaciar un inventario bueno."""
        rara = "OnuIndex  Admin State  OMCC State  Phase State  Channel\n" \
               "1/1/1:1   enable       enable      Renegociando  1(GPON)"
        buena = onu_en(1, 1, EstadoONU.EN_LINEA, MotivoCaida.NINGUNO)
        servicio, onus, _ = armar([buena], TransporteFalso({"0/1": rara}))

        servicio.actualizar(1, puertos=("0/1",))

        assert onus.guardadas == []


class TestHonestidad:
    def test_una_onu_que_no_esta_en_el_inventario_se_informa_y_no_se_crea(self, armar) -> None:
        """Puede estar dada de alta y todavía sin descubrir por SNMP."""
        servicio, onus, _ = armar([])

        resultado = servicio.actualizar(1, puertos=("0/1",))

        assert onus.guardadas == []
        assert len(resultado.solo_en_el_equipo) == 4
        assert resultado.onus_leidas == 4

    def test_un_puerto_que_falla_se_informa_y_no_corta_el_recorrido(self, armar) -> None:
        servicio, _, _ = armar([], TransporteFalso({"0/3": ESTADO_PON1}))

        resultado = servicio.actualizar(1, puertos=("0/1", "0/2", "0/3"))

        assert resultado.onus_leidas == 4
        assert [pon for pon, _ in resultado.puertos_con_falla] == ["0/1", "0/2"]
        assert not resultado.completo


class TestSesion:
    def test_solo_lee_y_siempre_vuelve_a_exec(self, armar) -> None:
        servicio, _, transporte = armar([])

        servicio.actualizar(1, puertos=("0/1",))

        permitidos = {"configure terminal", "end", "interface gpon 0/1", "show onu state"}
        assert set(transporte.ejecutados) <= permitidos
        assert transporte.ejecutados[-1] == "end"
        assert transporte.cerrado

    def test_recorre_los_ocho_puertos_por_defecto(self, armar) -> None:
        transporte = TransporteFalso(dict.fromkeys((f"0/{n}" for n in range(1, 9)), ESTADO_PON1))
        servicio, _, _ = armar([], transporte)

        servicio.actualizar(1)

        entradas = [c for c in transporte.ejecutados if c.startswith("interface gpon")]
        assert len(entradas) == 8


class TestLimites:
    def test_un_fabricante_sin_soporte_lo_dice(self) -> None:
        class RepositorioOtro(RepositorioOLTFalso):
            def obtener(self, _olt_id: int) -> OLT:
                return OLT(id=1, host="10.0.0.1", fabricante=Fabricante.SIMULADO)

        servicio = ServicioEstadosCLI(
            repositorio_olt=RepositorioOtro(), repositorio_onu=RepositorioONUFalso([])
        )
        with pytest.raises(CapacidadNoSoportada):
            servicio.actualizar(1)
