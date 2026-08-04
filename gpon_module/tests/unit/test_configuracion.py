"""Configuración: falla temprano y con motivo."""

from __future__ import annotations

import pytest

from gpon_module.config import Configuracion
from gpon_module.core.errors import ErrorConfiguracion


class TestValidacion:
    def test_sin_clave_de_cifrado_no_arranca(self) -> None:
        """Guardar credenciales de OLT en claro no puede ser el camino por descuido."""
        with pytest.raises(ErrorConfiguracion, match="CLAVE_CIFRADO"):
            Configuracion().validar()

    def test_el_cifrado_nulo_hay_que_pedirlo_explicitamente(self) -> None:
        Configuracion(permitir_cifrado_nulo=True).validar()  # no levanta

    def test_porcentaje_de_lectura_fuera_de_rango(self) -> None:
        with pytest.raises(ErrorConfiguracion, match="PORCENTAJE_MINIMO_LECTURA"):
            Configuracion(permitir_cifrado_nulo=True, porcentaje_minimo_lectura=0).validar()

    def test_base_de_datos_no_soportada(self) -> None:
        with pytest.raises(ErrorConfiguracion, match="no soportada"):
            Configuracion(
                permitir_cifrado_nulo=True, url_base_datos="mysql://x/y"
            ).validar()


class TestValoresPorDefecto:
    def test_el_modo_simulacion_viene_activado(self) -> None:
        assert Configuracion().dry_run_por_defecto is True

    def test_retencion_escalonada(self) -> None:
        """7 días de detalle, 90 de promedios horarios, 2 años de diarios."""
        retencion = Configuracion().retencion
        assert (retencion.dias_fina, retencion.dias_horaria, retencion.dias_diaria) == (
            7,
            90,
            730,
        )


class TestDesdeEntorno:
    def test_lee_las_variables_gpon(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GPON_BASE_DATOS", "sqlite:///otra.db")
        monkeypatch.setenv("GPON_DRY_RUN", "0")
        monkeypatch.setenv("GPON_RETENCION_FINA", "3")

        configuracion = Configuracion.desde_entorno()

        assert configuracion.url_base_datos == "sqlite:///otra.db"
        assert configuracion.dry_run_por_defecto is False
        assert configuracion.retencion.dias_fina == 3

    def test_un_entero_mal_escrito_avisa_cual_es(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GPON_TIMEOUT_SNMP", "cinco")
        with pytest.raises(ErrorConfiguracion, match="TIMEOUT_SNMP"):
            Configuracion.desde_entorno()

    def test_acepta_si_y_true_como_verdadero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for valor in ("1", "true", "si", "sí", "on"):
            monkeypatch.setenv("GPON_DRY_RUN", valor)
            assert Configuracion.desde_entorno().dry_run_por_defecto is True
