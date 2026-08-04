"""Entidades del dominio: invariantes y protección de secretos."""

from __future__ import annotations

import dataclasses

import pytest

from gpon_module.core.enums import TipoOperacion
from gpon_module.core.models import (
    ConfigWiFi,
    CredencialesOLT,
    CredencialPPPoE,
    LecturaOptica,
    RefONU,
    ReglaAlarma,
    ResultadoOperacion,
)


class TestRefONU:
    def test_texto_y_vuelta(self) -> None:
        ref = RefONU(pon=3, onu_id=17)
        assert str(ref) == "3:17"
        assert RefONU.desde_texto("3:17") == ref

    def test_es_comparable_y_ordenable(self) -> None:
        """Se usa como clave de diccionario y para ordenar inventarios."""
        refs = [RefONU(2, 5), RefONU(1, 9), RefONU(1, 2)]
        assert sorted(refs) == [RefONU(1, 2), RefONU(1, 9), RefONU(2, 5)]
        assert len({RefONU(1, 1), RefONU(1, 1)}) == 1

    def test_es_inmutable(self) -> None:
        with pytest.raises(dataclasses.FrozenInstanceError):
            RefONU(1, 1).pon = 2  # type: ignore[misc]


class TestResultadoOperacion:
    def test_exitoso_no_puede_llevar_error(self) -> None:
        with pytest.raises(ValueError, match="no puede llevar error"):
            ResultadoOperacion(ok=True, tipo=TipoOperacion.REINICIAR_ONU, error="algo")

    def test_fallido_debe_explicar_el_motivo(self) -> None:
        """Un fallo sin explicación es inauditable: no se admite."""
        with pytest.raises(ValueError, match="debe explicar el error"):
            ResultadoOperacion(ok=False, tipo=TipoOperacion.REINICIAR_ONU)

    def test_guarda_los_comandos_para_auditar(self) -> None:
        resultado = ResultadoOperacion(
            ok=True,
            tipo=TipoOperacion.REINICIAR_ONU,
            comandos_enviados=("interface gpon 0/1", "onu 3 reboot"),
            simulado=True,
        )
        assert resultado.comandos_enviados[1] == "onu 3 reboot"
        assert resultado.simulado is True


class TestSecretos:
    """Las credenciales nunca deben salir en un log ni en una traza."""

    def test_credenciales_de_olt_no_exponen_la_clave(self) -> None:
        texto = repr(CredencialesOLT(usuario="admin", password="Xpon@Olt9417#"))
        assert "Xpon@Olt9417#" not in texto
        assert "admin" in texto

    def test_config_wifi_no_expone_la_clave(self) -> None:
        texto = repr(ConfigWiFi(ssid="ERLAN-1000", password="secreta123"))
        assert "secreta123" not in texto
        assert "ERLAN-1000" in texto

    def test_credencial_pppoe_no_expone_la_clave(self) -> None:
        texto = repr(CredencialPPPoE(usuario="cliente1000", password="secreta123"))
        assert "secreta123" not in texto


class TestLecturaOptica:
    def test_calcula_la_atenuacion_del_enlace(self) -> None:
        lectura = LecturaOptica(ref=RefONU(1, 1), rx_onu_dbm=-22.5, tx_olt_dbm=3.0)
        assert lectura.perdida_optica_db == 25.5

    def test_sin_potencia_no_inventa_atenuacion(self) -> None:
        lectura = LecturaOptica(ref=RefONU(1, 1), rx_onu_dbm=None, tx_olt_dbm=3.0)
        assert lectura.perdida_optica_db is None


class TestReglaAlarma:
    def test_sin_histeresis_explicita_se_usa_el_propio_umbral(self) -> None:
        regla = ReglaAlarma(umbral=-27.0)
        assert regla.umbral_recuperacion == -27.0

    def test_la_histeresis_configurada_se_respeta(self) -> None:
        regla = ReglaAlarma(umbral=-27.0, umbral_recuperacion=-26.0)
        assert regla.umbral_recuperacion == -26.0
