"""Tablas de ``interface gpon 0/N`` de una VSOL V1600G1.

Las filas de acá son las que devolvió la OLT de ERLAN, con los saltos de columna
ANSI incluidos tal como llegan por la red. Los seriales están cambiados; la
forma es exactamente la real.
"""

from __future__ import annotations

from gpon_module.core.enums import EstadoONU, MotivoCaida
from gpon_module.drivers.transport.interactivo import limpiar_ansi
from gpon_module.drivers.vsol.parser_tablas import (
    parsear_onu_auto_find,
    parsear_onu_info,
    parsear_onu_state,
)


def _como_llega(*lineas: str) -> str:
    """Pasa el texto por la misma limpieza que aplica el transporte."""
    return "\n".join(limpiar_ansi(linea) for linea in lineas)


AUTO_FIND = _como_llega(
    "OnuIndex                 Sn                       State",
    "---------------------------------------------------------",
    "GPON0/1:1\x1b[25CGPON00AAAA01\x1b[50Cunknow",
    "GPON0/1:2\x1b[25CVSOL0000AA02\x1b[50Cunknow",
)

ONU_INFO = _como_llega(
    "Onuindex   Model                Profile                Mode    AuthInfo",
    "-------------------------------------------------------------------------",
    "GPON0/1:1\x1b[11CV411\x1b[32CV2801RGW\x1b[55Csn\x1b[63CGPON00AAAA01",
    "GPON0/1:6\x1b[11Cunknown\x1b[32CV2802DAC\x1b[55Csn\x1b[63CGPON00AAAA06",
)

ONU_STATE = _como_llega(
    "OnuIndex    Admin State    OMCC State    Phase State    Channel",
    "---------------------------------------------------------------",
    "1/1/1:1\x1b[12Cenable\x1b[27Cenable\x1b[41Cworking\x1b[56C\x1b[56C1(GPON)",
    "1/1/1:6\x1b[12Cenable\x1b[27Cdisable\x1b[41COffLine\x1b[56C\x1b[56C1(GPON)",
    "1/1/1:7\x1b[12Cenable\x1b[27Cdisable\x1b[41CDyingGasp\x1b[56C\x1b[56C1(GPON)",
    "1/1/1:18\x1b[12Cenable\x1b[27Cdisable\x1b[41CLOS\x1b[56C\x1b[56C1(GPON)",
    "ONU Number: 23/44",
)


class TestAlineacion:
    def test_una_fila_queda_alineada_con_su_encabezado(self) -> None:
        """El equipo alinea moviendo el cursor, no con espacios.

        Sin traducir esos saltos, la fila llega como
        'GPON0/1:1\\x1b[25CGPON00AAAA01' y no hay parser que la separe.
        """
        fila = limpiar_ansi("GPON0/1:1\x1b[25CGPON00AAAA01\x1b[50Cunknow")

        assert fila[25:37] == "GPON00AAAA01"
        assert "\x1b" not in fila

    def test_dos_campos_nunca_quedan_pegados(self) -> None:
        """Si el texto ya pasó la columna pedida, igual hay que separarlos."""
        fila = limpiar_ansi("UN-NOMBRE-MUY-LARGO-QUE-PASA-LA-COLUMNA\x1b[10CVALOR")

        assert "COLUMNA VALOR" in fila


class TestONUPendientes:
    def test_encuentra_las_onu_sin_autorizar(self) -> None:
        """Es el punto de partida del alta: el técnico manda el Sn y hay que hallarlo."""
        pendientes = parsear_onu_auto_find(AUTO_FIND)

        assert [p.numero_serie for p in pendientes] == ["GPON00AAAA01", "VSOL0000AA02"]
        assert pendientes[0].pon == 1
        assert pendientes[0].indice_propuesto == 1
        assert pendientes[0].estado_informado == "unknow"

    def test_un_listado_vacio_no_es_un_error(self) -> None:
        """Que no haya ONU esperando es lo normal, no una falla."""
        vacio = _como_llega(
            "OnuIndex                 Sn                       State",
            "---------------------------------------------------------",
        )
        assert parsear_onu_auto_find(vacio) == []


class TestInventario:
    def test_saca_el_serial_y_el_perfil_de_cada_onu(self) -> None:
        informadas = parsear_onu_info(ONU_INFO)

        assert len(informadas) == 2
        assert informadas[0].numero_serie == "GPON00AAAA01"
        assert informadas[0].modelo == "V411"
        assert informadas[0].perfil == "V2801RGW"
        assert (informadas[0].pon, informadas[0].onu_id) == (1, 1)

    def test_un_modelo_desconocido_queda_vacio_y_no_dice_unknown(self) -> None:
        """'unknown' no es un modelo: mostrarlo como tal ensucia el inventario."""
        informadas = parsear_onu_info(ONU_INFO)
        assert informadas[1].modelo == ""
        assert informadas[1].numero_serie == "GPON00AAAA06"


class TestEstados:
    def test_dying_gasp_es_corte_de_luz_y_los_es_fibra(self) -> None:
        """La distinción que decide si sale una cuadrilla o no.

        Es exactamente el motivo de caída que SNMP no publica en estos equipos.
        """
        estados = {(e.pon, e.onu_id): e for e in parsear_onu_state(ONU_STATE)}

        assert estados[(1, 7)].motivo is MotivoCaida.APAGADO
        assert estados[(1, 18)].motivo is MotivoCaida.PERDIDA_SENAL
        assert estados[(1, 7)].estado is EstadoONU.FUERA_DE_LINEA

    def test_working_es_en_linea_sin_motivo(self) -> None:
        estados = {(e.pon, e.onu_id): e for e in parsear_onu_state(ONU_STATE)}

        assert estados[(1, 1)].estado is EstadoONU.EN_LINEA
        assert estados[(1, 1)].motivo is MotivoCaida.NINGUNO

    def test_offline_sin_mas_datos_no_se_inventa_un_motivo(self) -> None:
        """El equipo dice que está caída pero no por qué. Eso es 'desconocido'."""
        estados = {(e.pon, e.onu_id): e for e in parsear_onu_state(ONU_STATE)}

        assert estados[(1, 6)].estado is EstadoONU.FUERA_DE_LINEA
        assert estados[(1, 6)].motivo is MotivoCaida.DESCONOCIDO

    def test_la_linea_del_total_no_se_toma_por_una_onu(self) -> None:
        assert len(parsear_onu_state(ONU_STATE)) == 4

    def test_una_fase_que_no_conocemos_no_rompe_la_lectura(self) -> None:
        otra = _como_llega(
            "OnuIndex    Admin State    OMCC State    Phase State    Channel",
            "1/1/1:9\x1b[12Cenable\x1b[27Cdisable\x1b[41CFaseNueva\x1b[56C1(GPON)",
        )
        estados = parsear_onu_state(otra)

        assert estados[0].estado is EstadoONU.DESCONOCIDO
        assert estados[0].fase == "FaseNueva"
