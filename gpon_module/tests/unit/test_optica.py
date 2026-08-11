"""Reglas de interpretación de potencias ópticas."""

from __future__ import annotations

import pytest

from gpon_module.core.enums import ClasificacionOptica
from gpon_module.core.optica import (
    UmbralesOpticos,
    clasificar,
    es_problematica,
    perdida_optica,
)


class TestClasificacion:
    def test_potencia_sana_es_optima(self) -> None:
        assert clasificar(-22.0) is ClasificacionOptica.OPTIMA

    @pytest.mark.parametrize("rx", [-26.0, -25.1])
    def test_potencia_intermedia_es_aceptable(self, rx: float) -> None:
        assert clasificar(rx) is ClasificacionOptica.ACEPTABLE

    def test_potencia_debil_es_baja(self) -> None:
        assert clasificar(-28.0) is ClasificacionOptica.BAJA

    def test_potencia_muy_debil_es_critica(self) -> None:
        assert clasificar(-32.22) is ClasificacionOptica.CRITICA

    def test_exceso_de_luz_es_saturacion_y_no_optima(self) -> None:
        """El caso que motivó incluir la saturación desde el primer día.

        Se encontró en el parque real una ONU a −1,57 dBm que el sistema
        anterior contaba como "óptima" por mirar sólo el extremo bajo. Demasiada
        luz daña el receptor: es alarma, no un valor bueno.
        """
        assert clasificar(-1.57) is ClasificacionOptica.SATURADA
        assert clasificar(-1.57) is not ClasificacionOptica.OPTIMA
        assert es_problematica(-1.57)

    def test_sin_lectura_no_es_lo_mismo_que_potencia_mala(self) -> None:
        """Ausencia de dato no es un valor bajo: una ONU apagada no reporta."""
        assert clasificar(None) is ClasificacionOptica.SIN_LECTURA
        assert not es_problematica(None)

    def test_los_limites_caen_del_lado_esperado(self) -> None:
        umbrales = UmbralesOpticos()
        assert clasificar(umbrales.saturacion) is ClasificacionOptica.OPTIMA
        assert clasificar(umbrales.saturacion + 0.01) is ClasificacionOptica.SATURADA
        assert clasificar(umbrales.optima_minima) is ClasificacionOptica.OPTIMA
        assert clasificar(umbrales.optima_minima - 0.01) is ClasificacionOptica.ACEPTABLE

    def test_umbrales_a_medida(self) -> None:
        estrictos = UmbralesOpticos(
            saturacion=-10.0, optima_minima=-20.0, aceptable_minima=-24.0, baja_minima=-27.0
        )
        assert clasificar(-22.0, estrictos) is ClasificacionOptica.ACEPTABLE
        assert clasificar(-22.0) is ClasificacionOptica.OPTIMA


class TestUmbrales:
    def test_umbrales_desordenados_se_rechazan(self) -> None:
        """Un umbral mal cargado desde la interfaz debe fallar al construirse."""
        with pytest.raises(ValueError, match="de mayor a menor"):
            UmbralesOpticos(optima_minima=-30.0, aceptable_minima=-25.0)


class TestPerdidaOptica:
    def test_atenuacion_del_enlace(self) -> None:
        assert perdida_optica(3.0, -22.5) == 25.5

    def test_sin_alguno_de_los_extremos_no_hay_atenuacion(self) -> None:
        assert perdida_optica(None, -22.5) is None
        assert perdida_optica(3.0, None) is None
