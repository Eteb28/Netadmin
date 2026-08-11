"""Configuración: falla temprano y con motivo."""

from __future__ import annotations

import pytest

from gpon_module.config import Configuracion, cargar_archivo_entorno
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
            Configuracion(permitir_cifrado_nulo=True, url_base_datos="mysql://x/y").validar()


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

    def test_un_entero_mal_escrito_avisa_cual_es(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GPON_TIMEOUT_SNMP", "cinco")
        with pytest.raises(ErrorConfiguracion, match="TIMEOUT_SNMP"):
            Configuracion.desde_entorno()

    def test_acepta_si_y_true_como_verdadero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for valor in ("1", "true", "si", "sí", "on"):
            monkeypatch.setenv("GPON_DRY_RUN", valor)
            assert Configuracion.desde_entorno().dry_run_por_defecto is True


class TestArchivoDeEntorno:
    """El .env evita reescribir la clave de cifrado en cada terminal nueva."""

    def test_carga_las_variables_del_archivo(self, tmp_path, monkeypatch) -> None:
        archivo = tmp_path / ".env"
        archivo.write_text("GPON_BASE_DATOS=sqlite:///erlan.db\nGPON_CLAVE_CIFRADO=abc\n")
        monkeypatch.delenv("GPON_BASE_DATOS", raising=False)
        monkeypatch.delenv("GPON_CLAVE_CIFRADO", raising=False)

        configuracion = Configuracion.desde_entorno(archivo_entorno=archivo)

        assert configuracion.url_base_datos == "sqlite:///erlan.db"
        assert configuracion.clave_cifrado == "abc"

    def test_lo_exportado_a_mano_le_gana_al_archivo(self, tmp_path, monkeypatch) -> None:
        """Una variable puesta para una prueba puntual no debe quedar tapada."""
        archivo = tmp_path / ".env"
        archivo.write_text("GPON_BASE_DATOS=sqlite:///del-archivo.db\n")
        monkeypatch.setenv("GPON_BASE_DATOS", "sqlite:///de-la-terminal.db")

        configuracion = Configuracion.desde_entorno(archivo_entorno=archivo)

        assert configuracion.url_base_datos == "sqlite:///de-la-terminal.db"

    def test_una_contrasena_con_numeral_no_se_toma_como_comentario(
        self, tmp_path, monkeypatch
    ) -> None:
        """'#eAguiar457' es una contraseña válida y frecuente en equipos."""
        archivo = tmp_path / ".env"
        archivo.write_text("# un comentario\nGPON_OLT_PASSWORD=#eAguiar457\n")
        monkeypatch.delenv("GPON_OLT_PASSWORD", raising=False)

        cargadas = cargar_archivo_entorno(archivo)

        assert cargadas["GPON_OLT_PASSWORD"] == "#eAguiar457"

    def test_sin_archivo_no_pasa_nada(self, tmp_path) -> None:
        assert cargar_archivo_entorno(tmp_path / "no-existe") == {}
