"""Baja de una ONU: la operación que deja a un cliente sin servicio.

El riesgo acá no es que el comando falle, es que funcione sobre la ONU
equivocada. Estos tests protegen las dos cosas que lo evitan: que por defecto
no se envíe nada, y que un serial que no coincide frene la baja antes de que
salga el comando.
"""

from __future__ import annotations

import pytest

from gpon_module.core.enums import Fabricante
from gpon_module.core.errors import CapacidadNoSoportada, ErrorComando, ErrorValidacion
from gpon_module.core.models import OLT, CredencialesOLT
from gpon_module.core.reloj import RelojFijo
from gpon_module.services.baja_onu import ServicioBajaONU

ONU_INFO = (
    "Onuindex   Model      Profile     Mode    AuthInfo\n"
    "GPON0/1:1  V411       V2801RGW    sn      GPON00AAAA01\n"
    "GPON0/1:29 V422       V2802DAC    sn      GPON002E64F8"
)


class RepositorioOLTFalso:
    def obtener(self, _olt_id: int) -> OLT:
        return OLT(id=1, nombre="Belgrano", host="10.0.0.1", fabricante=Fabricante.VSOL)

    def obtener_credenciales(self, _olt_id: int) -> CredencialesOLT:
        return CredencialesOLT(usuario="eaguiar", password="x")


class RepositorioOperacionFalso:
    def __init__(self) -> None:
        self.registradas: list = []

    def registrar(self, operacion):
        self.registradas.append(operacion)
        return operacion


class TransporteFalso:
    def __init__(self, rechazar: str = "", inventario: str = ONU_INFO) -> None:
        self.rechazar = rechazar
        self.inventario = inventario
        self.ejecutados: list[str] = []
        self.cerrado = False

    def abrir(self) -> None: ...

    def cerrar(self) -> None:
        self.cerrado = True

    def ejecutar(self, comando: str) -> str:
        self.ejecutados.append(comando)
        if self.rechazar and comando.startswith(self.rechazar):
            raise ErrorComando("% Invalid input detected", comando=comando)
        if comando == "show onu info":
            return self.inventario
        return ""

    @property
    def escrituras(self) -> list[str]:
        return [c for c in self.ejecutados if c.startswith("no onu")]


@pytest.fixture
def armar():
    def _armar(transporte: TransporteFalso):
        operaciones = RepositorioOperacionFalso()
        servicio = ServicioBajaONU(
            repositorio_olt=RepositorioOLTFalso(),
            repositorio_operacion=operaciones,
            reloj=RelojFijo(),
            fabrica_transporte=lambda **_kwargs: transporte,
        )
        return servicio, operaciones

    return _armar


class TestSimulacion:
    def test_por_defecto_no_se_borra_nada(self, armar) -> None:
        transporte = TransporteFalso()
        servicio, _ = armar(transporte)

        resultado = servicio.eliminar(1, pon=1, onu_id=29)

        assert resultado.simulado
        assert transporte.escrituras == []
        assert "no onu 29" in resultado.comandos

    def test_la_simulacion_dice_qué_onu_hay_en_ese_indice(self, armar) -> None:
        """Es lo único que le permite al operador frenar a tiempo."""
        servicio, _ = armar(TransporteFalso())

        resultado = servicio.eliminar(1, pon=1, onu_id=29)

        assert resultado.numero_serie == "GPON002E64F8"

    def test_queda_auditada_aunque_sea_simulada(self, armar) -> None:
        servicio, operaciones = armar(TransporteFalso())

        servicio.eliminar(1, pon=1, onu_id=29)

        assert operaciones.registradas[0].simulado is True


class TestOnuEquivocada:
    def test_un_serial_que_no_coincide_frena_la_baja(self, armar) -> None:
        """Dar de baja el índice de otro cliente es el error caro de acá."""
        transporte = TransporteFalso()
        servicio, _ = armar(transporte)

        with pytest.raises(ErrorValidacion, match="GPON002E64F8"):
            servicio.eliminar(
                1, pon=1, onu_id=29, numero_serie_esperado="GPON00AAAA01", dry_run=False
            )

        assert transporte.escrituras == []

    def test_el_serial_esperado_se_compara_sin_distinguir_mayusculas(self, armar) -> None:
        transporte = TransporteFalso()
        servicio, _ = armar(transporte)

        resultado = servicio.eliminar(
            1, pon=1, onu_id=29, numero_serie_esperado="gpon002e64f8", dry_run=False
        )

        assert resultado.ok

    def test_un_indice_vacio_igual_se_puede_limpiar(self, armar) -> None:
        """Un alta que quedó a medias puede no aparecer en el inventario.

        Ese es justamente el caso que hay que poder limpiar, así que no
        encontrar nada no bloquea la baja: lo que bloquea es encontrar otra.
        """
        transporte = TransporteFalso(inventario="Onuindex   Model      Profile")
        servicio, _ = armar(transporte)

        resultado = servicio.eliminar(
            1, pon=1, onu_id=29, numero_serie_esperado="GPON002E64F8", dry_run=False
        )

        assert resultado.ok
        assert transporte.escrituras == ["no onu 29"]


class TestEscrituraReal:
    def test_con_aplicar_se_envia_el_comando(self, armar) -> None:
        transporte = TransporteFalso()
        servicio, _ = armar(transporte)

        resultado = servicio.eliminar(1, pon=1, onu_id=29, dry_run=False)

        assert resultado.ok
        assert not resultado.simulado
        assert transporte.escrituras == ["no onu 29"]

    def test_se_entra_a_modo_configuracion_una_sola_vez(self, armar) -> None:
        transporte = TransporteFalso()
        servicio, _ = armar(transporte)

        servicio.eliminar(1, pon=1, onu_id=29, dry_run=False)

        assert transporte.ejecutados.count("configure terminal") == 1

    def test_un_rechazo_se_informa_y_no_se_disfraza(self, armar) -> None:
        transporte = TransporteFalso(rechazar="no onu")
        servicio, _ = armar(transporte)

        resultado = servicio.eliminar(1, pon=1, onu_id=29, dry_run=False)

        assert not resultado.ok
        assert resultado.comando_que_fallo == "no onu 29"

    def test_la_sesion_vuelve_a_exec_y_se_cierra_pase_lo_que_pase(self, armar) -> None:
        transporte = TransporteFalso(rechazar="no onu")
        servicio, _ = armar(transporte)

        servicio.eliminar(1, pon=1, onu_id=29, dry_run=False)

        assert transporte.ejecutados[-1] == "end"
        assert transporte.cerrado

    def test_una_baja_real_queda_auditada(self, armar) -> None:
        servicio, operaciones = armar(TransporteFalso())

        servicio.eliminar(1, pon=1, onu_id=29, dry_run=False, usuario="eaguiar")

        registrada = operaciones.registradas[0]
        assert registrada.simulado is False
        assert registrada.usuario == "eaguiar"
        assert registrada.ref_onu.onu_id == 29


class TestLimites:
    def test_un_indice_fuera_de_rango_no_llega_al_equipo(self, armar) -> None:
        transporte = TransporteFalso()
        servicio, _ = armar(transporte)

        with pytest.raises(ErrorValidacion):
            servicio.eliminar(1, pon=1, onu_id=999, dry_run=False)

        assert transporte.ejecutados == []

    def test_un_fabricante_sin_soporte_lo_dice(self) -> None:
        class RepositorioOtro(RepositorioOLTFalso):
            def obtener(self, _olt_id: int) -> OLT:
                return OLT(id=1, host="10.0.0.1", fabricante=Fabricante.SIMULADO)

        servicio = ServicioBajaONU(repositorio_olt=RepositorioOtro())
        with pytest.raises(CapacidadNoSoportada):
            servicio.eliminar(1, pon=1, onu_id=29)
