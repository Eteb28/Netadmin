"""Alta de una ONU: la primera operación que escribe en un equipo real.

Todo lo que se prueba acá es una forma de la misma pregunta: qué pasa cuando
algo sale distinto de lo esperado en una OLT con 284 clientes conectados.
"""

from __future__ import annotations

import pytest

from gpon_module.core.enums import Fabricante
from gpon_module.core.errors import CapacidadNoSoportada, ErrorComando, ErrorValidacion
from gpon_module.core.models import OLT, CredencialesOLT
from gpon_module.core.reloj import RelojFijo
from gpon_module.services.alta_onu import ServicioAltaONU

AUTO_FIND = (
    "OnuIndex                 Sn                       State\n"
    "---------------------------------------------------------\n"
    "GPON0/1:1                GPON002E64F8             unknow"
)
AUTO_FIND_VACIO = "OnuIndex                 Sn                       State"

#: Un puerto con los índices 1 y 3 usados: el hueco libre más bajo es el 2.
ONU_INFO = (
    "Onuindex   Model      Profile     Mode    AuthInfo\n"
    "GPON0/1:1  V411       V2801RGW    sn      GPON00AAAA01\n"
    "GPON0/1:3  V422       V2802DAC    sn      GPON00AAAA03"
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
    """Equipo de mentira: PON 1 con una ONU esperando y dos ya dadas de alta."""

    def __init__(self, rechazar: str = "") -> None:
        self.rechazar = rechazar
        self.ejecutados: list[str] = []
        self.pon = 0
        self.cerrado = False

    def abrir(self) -> None: ...

    def cerrar(self) -> None:
        self.cerrado = True

    def ejecutar(self, comando: str) -> str:
        self.ejecutados.append(comando)
        if self.rechazar and comando.startswith(self.rechazar):
            raise ErrorComando("% Invalid input detected", comando=comando)
        if comando.startswith("interface gpon "):
            self.pon = int(comando.split("/")[-1])
            return ""
        if comando == "show onu auto-find":
            return AUTO_FIND if self.pon == 1 else AUTO_FIND_VACIO
        if comando == "show onu info":
            return ONU_INFO if self.pon == 1 else ""
        return ""

    @property
    def escrituras(self) -> list[str]:
        """Comandos que cambian algo: ni navegación ni lectura."""
        return [
            c
            for c in self.ejecutados
            if not c.startswith(("show ", "interface gpon", "configure terminal", "end"))
        ]


@pytest.fixture
def armar():
    def _armar(transporte: TransporteFalso):
        operaciones = RepositorioOperacionFalso()
        servicio = ServicioAltaONU(
            repositorio_olt=RepositorioOLTFalso(),
            repositorio_operacion=operaciones,
            reloj=RelojFijo(),
            fabrica_transporte=lambda **_kwargs: transporte,
        )
        return servicio, operaciones

    return _armar


class TestSimulacion:
    def test_por_defecto_no_se_escribe_nada(self, armar) -> None:
        """La propiedad más importante del servicio."""
        transporte = TransporteFalso()
        servicio, _ = armar(transporte)

        resultado = servicio.autorizar(1, numero_serie="GPON002E64F8", perfil_onu="V2802DAC")

        assert resultado.simulado
        assert transporte.escrituras == []
        assert any("onu add" in c for c in resultado.comandos)

    def test_la_simulacion_igual_verifica_contra_el_equipo(self, armar) -> None:
        """Sirve de poco simular un alta sobre datos inventados."""
        transporte = TransporteFalso()
        servicio, _ = armar(transporte)

        resultado = servicio.autorizar(1, numero_serie="GPON002E64F8", perfil_onu="V2802DAC")

        assert resultado.solicitud.pon == 1
        assert "show onu auto-find" in transporte.ejecutados

    def test_queda_auditada_aunque_sea_simulada(self, armar) -> None:
        transporte = TransporteFalso()
        servicio, operaciones = armar(transporte)

        servicio.autorizar(1, numero_serie="GPON002E64F8", perfil_onu="V2802DAC")

        assert len(operaciones.registradas) == 1
        assert operaciones.registradas[0].simulado is True


class TestVerificaciones:
    def test_no_se_autoriza_una_onu_que_no_esta_esperando(self, armar) -> None:
        """Si no está en auto-find, el alta ocuparía un índice para nada."""
        transporte = TransporteFalso()
        servicio, _ = armar(transporte)

        with pytest.raises(ErrorValidacion, match="no está esperando"):
            servicio.autorizar(1, numero_serie="GPON00000000", perfil_onu="V2802DAC")

        assert transporte.escrituras == []

    def test_encuentra_sola_en_que_puerto_esta(self, armar) -> None:
        transporte = TransporteFalso()
        servicio, _ = armar(transporte)

        resultado = servicio.autorizar(1, numero_serie="GPON002E64F8", perfil_onu="V2802DAC")

        assert resultado.solicitud.pon == 1

    def test_reusa_el_hueco_libre_mas_bajo(self, armar) -> None:
        """Con el 1 y el 3 ocupados, la nueva va al 2."""
        transporte = TransporteFalso()
        servicio, _ = armar(transporte)

        resultado = servicio.autorizar(1, numero_serie="GPON002E64F8", perfil_onu="V2802DAC")

        assert resultado.solicitud.onu_id == 2

    def test_un_serial_invalido_no_llega_a_la_red(self, armar) -> None:
        transporte = TransporteFalso()
        servicio, _ = armar(transporte)

        with pytest.raises(ErrorValidacion):
            servicio.autorizar(1, numero_serie="esto no es un serial", perfil_onu="V2802DAC")

        assert transporte.escrituras == []


class TestEscrituraReal:
    def test_con_aplicar_se_envia_la_secuencia_completa(self, armar) -> None:
        transporte = TransporteFalso()
        servicio, _ = armar(transporte)

        resultado = servicio.autorizar(
            1,
            numero_serie="GPON002E64F8",
            perfil_onu="V2802DAC",
            trafico_subida="100M-Dom-UP",
            trafico_bajada="100M-Dom-DOW",
            dry_run=False,
        )

        assert resultado.ok
        assert not resultado.simulado
        assert "onu add 2 profile V2802DAC sn GPON002E64F8" in transporte.ejecutados
        assert any("traffic-limit" in c for c in transporte.ejecutados)

    def test_un_rechazo_del_equipo_aborta_y_dice_dónde_quedó(self, armar) -> None:
        """Seguir después de un rechazo es lo que deja al cliente sin servicio."""
        transporte = TransporteFalso(rechazar="onu 2 service ")
        servicio, _ = armar(transporte)

        resultado = servicio.autorizar(
            1, numero_serie="GPON002E64F8", perfil_onu="V2802DAC", dry_run=False
        )

        assert not resultado.ok
        assert resultado.quedo_a_medias
        assert resultado.comando_que_fallo.startswith("onu 2 service ")
        # No se siguió con lo que venía después del rechazo.
        assert not any("service-port" in c for c in transporte.ejecutados)

    def test_se_entra_a_modo_configuracion_una_sola_vez(self, armar) -> None:
        """Desde modo interfaz, 'configure terminal' lo rechaza el equipo.

        Lo encontró la réplica de la OLT: al recorrer los ocho puertos buscando
        el serial, el segundo 'configure terminal' salía estando ya adentro.
        """
        transporte = TransporteFalso()
        servicio, _ = armar(transporte)

        servicio.autorizar(1, numero_serie="GPON002E64F8", perfil_onu="V2802DAC")

        # Uno para las verificaciones. En modo real la secuencia trae el suyo,
        # pero recién después de volver a EXEC con 'end'.
        assert transporte.ejecutados.count("configure terminal") == 1

    def test_lo_que_se_muestra_es_exactamente_lo_que_se_envia(self, armar) -> None:
        transporte = TransporteFalso()
        servicio, _ = armar(transporte)

        resultado = servicio.autorizar(
            1, numero_serie="GPON002E64F8", perfil_onu="V2802DAC", dry_run=False
        )

        assert resultado.comandos_aplicados == resultado.comandos

    def test_la_sesion_vuelve_a_exec_y_se_cierra_pase_lo_que_pase(self, armar) -> None:
        transporte = TransporteFalso(rechazar="onu add")
        servicio, _ = armar(transporte)

        servicio.autorizar(1, numero_serie="GPON002E64F8", perfil_onu="V2802DAC", dry_run=False)

        assert transporte.ejecutados[-1] == "end"
        assert transporte.cerrado

    def test_un_alta_fallida_tambien_queda_auditada(self, armar) -> None:
        """Sobre todo si falló: es lo que hay que poder reconstruir después."""
        transporte = TransporteFalso(rechazar="onu 2 desc")
        servicio, operaciones = armar(transporte)

        servicio.autorizar(1, numero_serie="GPON002E64F8", perfil_onu="V2802DAC", dry_run=False)

        assert operaciones.registradas[0].ok is False
        assert operaciones.registradas[0].simulado is False


class TestLimites:
    def test_un_fabricante_sin_soporte_lo_dice(self) -> None:
        class RepositorioOtro(RepositorioOLTFalso):
            def obtener(self, _olt_id: int) -> OLT:
                return OLT(id=1, host="10.0.0.1", fabricante=Fabricante.SIMULADO)

        servicio = ServicioAltaONU(repositorio_olt=RepositorioOtro())
        with pytest.raises(CapacidadNoSoportada):
            servicio.autorizar(1, numero_serie="GPON002E64F8", perfil_onu="V2802DAC")
