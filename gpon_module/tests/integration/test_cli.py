"""Comandos de la CLI que tocan credenciales guardadas.

Son los que más caro cuestan cuando se equivocan: dejan una OLT en producción
sin poder leerse, y el error aparece recién en la corrida siguiente.
"""

from __future__ import annotations

import pytest

from gpon_module.cli import main
from gpon_module.config import Configuracion
from gpon_module.services import crear_contenedor


@pytest.fixture
def base(tmp_path, monkeypatch) -> str:
    monkeypatch.setenv("GPON_PERMITIR_CIFRADO_NULO", "1")
    monkeypatch.delenv("GPON_CLAVE_CIFRADO", raising=False)
    return f"sqlite:///{tmp_path / 'gpon.db'}"


def _credenciales(base: str, olt_id: int = 1):
    configuracion = Configuracion.desde_entorno()
    from dataclasses import replace

    with crear_contenedor(replace(configuracion, url_base_datos=base)) as sistema:
        return sistema.repositorio_olt.obtener_credenciales(olt_id)


def _alta(base: str, monkeypatch) -> None:
    monkeypatch.setenv("GPON_OLT_PASSWORD", "contrasena-vieja")
    monkeypatch.setenv("GPON_OLT_COMUNIDAD", "comunidad-de-erlan")
    codigo = main(
        [
            "--base-datos",
            base,
            "alta-olt",
            "--nombre",
            "OLT Belgrano",
            "--host",
            "192.168.10.247",
            "--fabricante",
            "vsol",
            "--puerto-ssh",
            "2222",
        ]
    )
    assert codigo == 0
    monkeypatch.delenv("GPON_OLT_COMUNIDAD")


class TestCredenciales:
    def test_cambiar_la_contrasena_no_pisa_la_community_snmp(self, base, monkeypatch) -> None:
        """El caso real: corregir la contraseña de la CLI rompía la lectura SNMP.

        Con valores por defecto en los parámetros, un 'gpon credenciales 1' para
        arreglar el acceso a la CLI devolvía la community a 'public' y dejaba de
        leerse una OLT que venía funcionando.
        """
        _alta(base, monkeypatch)
        monkeypatch.setenv("GPON_OLT_PASSWORD", "contrasena-nueva")

        assert main(["--base-datos", base, "credenciales", "1"]) == 0

        guardadas = _credenciales(base)
        assert guardadas.password == "contrasena-nueva"
        assert guardadas.comunidad_snmp_lectura == "comunidad-de-erlan"

    def test_tampoco_pisa_los_puertos_configurados(self, base, monkeypatch) -> None:
        _alta(base, monkeypatch)
        monkeypatch.setenv("GPON_OLT_PASSWORD", "otra")

        main(["--base-datos", base, "credenciales", "1"])

        assert _credenciales(base).puerto_ssh == 2222

    def test_lo_que_se_indica_sí_se_cambia(self, base, monkeypatch) -> None:
        _alta(base, monkeypatch)
        monkeypatch.setenv("GPON_OLT_PASSWORD", "otra")

        main(["--base-datos", base, "credenciales", "1", "--usuario", "root"])

        guardadas = _credenciales(base)
        assert guardadas.usuario == "root"
        assert guardadas.comunidad_snmp_lectura == "comunidad-de-erlan"
