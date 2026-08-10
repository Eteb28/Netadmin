"""Traducir el plan contratado al perfil de tráfico de la OLT.

Los nombres de esta prueba son los **reales** de la OLT de ERLAN, con todas sus
inconsistencias. Ahí está el valor: si el emparejador funciona sobre estos 26,
funciona sobre cualquier cosa que el equipo tenga cargada, porque no supone
ninguna convención.
"""

from __future__ import annotations

import pytest

from gpon_module.core.models import Cliente, PerfilTrafico
from gpon_module.drivers.vsol.planes_conocidos import PLANES_ERLAN
from gpon_module.services.planes import (
    SEGMENTO_EMPRESA,
    SEGMENTO_HOGAR,
    elegir_planes,
    segmento_de,
)

PERFILES = tuple(PerfilTrafico(nombre=n) for n in PLANES_ERLAN)


class TestEmparejado:
    @pytest.mark.parametrize(
        ("megas", "segmento", "subida", "bajada"),
        [
            # El caso que rompió un alta: el nombre real termina en 'Dow'.
            (10, SEGMENTO_HOGAR, "10M-Dom-UP", "10M-Dom-Dow"),
            # Mayúsculas distintas en el mismo escalón.
            (5, SEGMENTO_HOGAR, "5M-Dom-Up", "5M-Dom-Dow"),
            (100, SEGMENTO_HOGAR, "100M-Dom-UP", "100M-Dom-DOW"),
            # 'Dowm' con M final, que no es un error de tipeo nuestro.
            (100, SEGMENTO_EMPRESA, "100M-Pymes-UP", "100M-Pymes-Dowm"),
            # Segmento todo en mayúsculas.
            (50, SEGMENTO_EMPRESA, "50M-PYMES-UP", "50M-PYMES-DOW"),
            (600, SEGMENTO_EMPRESA, "600M-Pymes-UP", "600M-Pymes-Dowm"),
        ],
    )
    def test_encuentra_el_par_exacto(self, megas, segmento, subida, bajada) -> None:
        elegidos = elegir_planes(PERFILES, megabits=megas, segmento=segmento)

        assert (elegidos.subida, elegidos.bajada) == (subida, bajada)
        assert elegidos.completo

    def test_no_confunde_hogar_con_empresa(self) -> None:
        """En 50 MB existen los dos, y son planes distintos."""
        hogar = elegir_planes(PERFILES, megabits=50, segmento=SEGMENTO_HOGAR)
        empresa = elegir_planes(PERFILES, megabits=50, segmento=SEGMENTO_EMPRESA)

        assert hogar.bajada == "50M-Dom-DOW"
        assert empresa.bajada == "50M-PYMES-DOW"

    def test_no_confunde_100_con_10(self) -> None:
        """El emparejado es por número, no por prefijo de texto."""
        diez = elegir_planes(PERFILES, megabits=10, segmento=SEGMENTO_HOGAR)

        assert diez.bajada == "10M-Dom-Dow"


class TestHonestidad:
    """Cuando no hay con qué, se dice. Proponer el parecido es el bug original."""

    def test_una_velocidad_que_la_olt_no_tiene_no_se_aproxima(self) -> None:
        elegidos = elegir_planes(PERFILES, megabits=25, segmento=SEGMENTO_HOGAR)

        assert not elegidos.completo
        assert elegidos.subida == "" and elegidos.bajada == ""
        assert "25 MB" in elegidos.motivo

    def test_600_para_hogar_no_cae_en_el_de_empresa(self) -> None:
        """Existe 600M-Pymes pero no 600M-Dom: son precios distintos."""
        elegidos = elegir_planes(PERFILES, megabits=600, segmento=SEGMENTO_HOGAR)

        assert not elegidos.completo

    def test_sin_megas_declarados_no_se_inventa(self) -> None:
        elegidos = elegir_planes(PERFILES, megabits=None)

        assert not elegidos.completo
        assert "megas" in elegidos.motivo

    def test_sin_perfiles_inventariados_lo_dice(self) -> None:
        elegidos = elegir_planes((), megabits=10)

        assert not elegidos.completo
        assert "inventariados" in elegidos.motivo

    def test_un_par_a_medias_se_descarta_entero(self) -> None:
        """Aplicar sólo la bajada deja la subida en el DBA y nadie se entera.

        El cliente termina con un servicio que no contrató y la única señal es
        que se queje.
        """
        solo_bajada = (PerfilTrafico(nombre="10M-Dom-Dow"),)

        elegidos = elegir_planes(solo_bajada, megabits=10)

        assert not elegidos.completo
        assert elegidos.bajada == ""
        assert "a mano" in elegidos.motivo

    def test_un_nombre_que_no_sigue_el_formato_no_rompe_el_resto(self) -> None:
        """Los equipos traen perfiles de fábrica con nombres cualesquiera."""
        raros = (
            PerfilTrafico(nombre="default"),
            PerfilTrafico(nombre="10M-Dom-Dow"),
            PerfilTrafico(nombre="10M-Dom-UP"),
        )

        elegidos = elegir_planes(raros, megabits=10)

        assert (elegidos.subida, elegidos.bajada) == ("10M-Dom-UP", "10M-Dom-Dow")


class TestSegmento:
    def test_un_plan_residencial_es_hogar(self) -> None:
        assert segmento_de(Cliente(plan="INTERNET 10 MB")) == SEGMENTO_HOGAR

    @pytest.mark.parametrize(
        "plan",
        ["INTERNET 1 MB PYME", "EMPRESA 2MB IP PUBLICA", "INTERNET 2 MB SEMI DEDICADO"],
    )
    def test_los_planes_de_empresa_se_reconocen(self, plan) -> None:
        assert segmento_de(Cliente(plan=plan)) == SEGMENTO_EMPRESA
