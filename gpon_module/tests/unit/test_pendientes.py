"""Listado de ONU esperando autorización.

Es el primer paso del alta de un cliente: el técnico manda un serial y hay que
encontrarlo. Lo que estos tests protegen es que el recorrido sea completo y
honesto — que un puerto que falló no se confunda con un puerto sin ONU nuevas—
y que la sesión salga del modo configuración siempre.
"""

from __future__ import annotations

import pytest

from gpon_module.core.enums import Fabricante
from gpon_module.core.errors import CapacidadNoSoportada, ErrorComando
from gpon_module.core.models import OLT, CredencialesOLT
from gpon_module.core.reloj import RelojFijo
from gpon_module.services.pendientes import ServicioPendientes

AUTO_FIND_PON1 = (
    "OnuIndex                 Sn                       State\n"
    "---------------------------------------------------------\n"
    "GPON0/1:1                GPON002E64F8             unknow"
)
AUTO_FIND_VACIO = "OnuIndex                 Sn                       State\n----------------"


class RepositorioOLTFalso:
    def obtener(self, _olt_id: int) -> OLT:
        return OLT(id=1, nombre="Belgrano", host="10.0.0.1", fabricante=Fabricante.VSOL)

    def obtener_credenciales(self, _olt_id: int) -> CredencialesOLT:
        return CredencialesOLT(usuario="eaguiar", password="x")


class TransporteFalso:
    def __init__(self, por_puerto: dict[str, str] | None = None) -> None:
        self.por_puerto = por_puerto or {}
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
        if comando == "show onu auto-find":
            return self.por_puerto.get(self.pon_actual, AUTO_FIND_VACIO)
        return ""


@pytest.fixture
def armar():
    def _armar(transporte: TransporteFalso) -> ServicioPendientes:
        return ServicioPendientes(
            RepositorioOLTFalso(),
            reloj=RelojFijo(),
            fabrica_transporte=lambda **_kwargs: transporte,
        )

    return _armar


class TestListado:
    def test_encuentra_la_onu_que_espera(self, armar) -> None:
        transporte = TransporteFalso({"0/1": AUTO_FIND_PON1})

        resultado = armar(transporte).listar(1, puertos=("0/1",))

        assert len(resultado.pendientes) == 1
        assert resultado.pendientes[0].numero_serie == "GPON002E64F8"
        assert resultado.pendientes[0].pon == 1

    def test_recorre_los_ocho_puertos_por_defecto(self, armar) -> None:
        transporte = TransporteFalso({f"0/{n}": AUTO_FIND_VACIO for n in range(1, 9)})

        armar(transporte).listar(1)

        entradas = [c for c in transporte.ejecutados if c.startswith("interface gpon")]
        assert len(entradas) == 8

    def test_no_ofrece_la_misma_onu_dos_veces(self, armar) -> None:
        """Algunos equipos contestan la lista completa en cada puerto.

        Ofrecerla ocho veces dejaría al operador sin saber cuál de las ocho es
        la buena.
        """
        transporte = TransporteFalso(dict.fromkeys(("0/1", "0/2", "0/3"), AUTO_FIND_PON1))

        resultado = armar(transporte).listar(1, puertos=("0/1", "0/2", "0/3"))

        assert len(resultado.pendientes) == 1

    def test_busca_por_serial_sin_distinguir_mayusculas(self, armar) -> None:
        """El serial llega tipeado a mano por el técnico."""
        transporte = TransporteFalso({"0/1": AUTO_FIND_PON1})

        resultado = armar(transporte).listar(1, puertos=("0/1",))

        assert resultado.buscar("gpon002e64f8") is not None
        assert resultado.buscar(" GPON002E64F8 ") is not None
        assert resultado.buscar("GPON00000000") is None


class TestPuertoSinNovedades:
    """Verificado en Belgrano: sin ONU esperando, el equipo contesta 'Error:'.

    Con una ONU esperando devuelve la tabla; con ninguna, un ``Error:`` pelado
    en vez de una tabla vacía. Tomarlo como falla haría que la pantalla dijera
    "no se pudieron leer los 8 puertos" todos los días sin altas pendientes,
    que son la mayoría.
    """

    def test_el_error_pelado_es_un_puerto_sin_onu_esperando(self, armar) -> None:
        class TransporteQueDaError(TransporteFalso):
            def ejecutar(self, comando: str) -> str:
                self.ejecutados.append(comando)
                if comando.startswith("interface gpon "):
                    self.pon_actual = comando.split()[-1]
                    return ""
                if comando == "show onu auto-find":
                    if self.pon_actual == "0/1":
                        return AUTO_FIND_PON1
                    raise ErrorComando("Error:", comando=comando)
                return ""

        transporte = TransporteQueDaError()

        resultado = armar(transporte).listar(1, puertos=("0/1", "0/2", "0/3"))

        assert len(resultado.pendientes) == 1
        assert resultado.puertos_con_falla == ()
        assert resultado.completo

    def test_un_rechazo_de_sintaxis_sigue_siendo_una_falla(self, armar) -> None:
        """La excepción es angosta a propósito: sólo el 'Error:' sin más texto."""
        transporte = TransporteFalso({"0/1": AUTO_FIND_PON1})  # 0/2 no existe

        resultado = armar(transporte).listar(1, puertos=("0/1", "0/2"))

        assert [pon for pon, _ in resultado.puertos_con_falla] == ["0/2"]


class TestHonestidad:
    def test_un_puerto_que_falla_se_informa_y_no_se_confunde_con_vacio(self, armar) -> None:
        """Decir 'no hay ONU nuevas' cuando en realidad no se pudo mirar es peor
        que no decir nada: el operador deja de buscar."""
        transporte = TransporteFalso({"0/1": AUTO_FIND_PON1})  # 0/2 no existe

        resultado = armar(transporte).listar(1, puertos=("0/1", "0/2"))

        assert len(resultado.pendientes) == 1
        assert [pon for pon, _ in resultado.puertos_con_falla] == ["0/2"]
        assert not resultado.completo

    def test_un_puerto_que_falla_no_corta_el_recorrido(self, armar) -> None:
        transporte = TransporteFalso({"0/3": AUTO_FIND_PON1})

        resultado = armar(transporte).listar(1, puertos=("0/1", "0/2", "0/3"))

        assert len(resultado.pendientes) == 1


class TestSesion:
    def test_entra_a_configuracion_y_sale_con_end(self, armar) -> None:
        transporte = TransporteFalso({"0/1": AUTO_FIND_VACIO})

        armar(transporte).listar(1, puertos=("0/1",))

        assert transporte.ejecutados[0] == "configure terminal"
        assert transporte.ejecutados[-1] == "end"
        assert transporte.cerrado

    def test_sale_del_modo_configuracion_aunque_algo_explote(self, armar) -> None:
        class TransporteQueExplota(TransporteFalso):
            def ejecutar(self, comando: str) -> str:
                self.ejecutados.append(comando)
                if comando == "show onu auto-find":
                    raise RuntimeError("se cayó el equipo")
                return ""

        transporte = TransporteQueExplota({"0/1": AUTO_FIND_VACIO})
        with pytest.raises(RuntimeError):
            armar(transporte).listar(1, puertos=("0/1",))

        assert transporte.ejecutados[-1] == "end"
        assert transporte.cerrado

    def test_solo_se_envian_comandos_de_navegacion_y_lectura(self, armar) -> None:
        transporte = TransporteFalso({"0/1": AUTO_FIND_VACIO})

        armar(transporte).listar(1, puertos=("0/1",))

        permitidos = {"configure terminal", "end", "interface gpon 0/1", "show onu auto-find"}
        assert set(transporte.ejecutados) <= permitidos


class TestLimites:
    def test_un_fabricante_sin_soporte_lo_dice(self) -> None:
        class RepositorioOtro(RepositorioOLTFalso):
            def obtener(self, _olt_id: int) -> OLT:
                return OLT(id=1, host="10.0.0.1", fabricante=Fabricante.SIMULADO)

        servicio = ServicioPendientes(RepositorioOtro(), reloj=RelojFijo())
        with pytest.raises(CapacidadNoSoportada):
            servicio.listar(1)
