"""Captura de la CLI: lo que se le pregunta al equipo antes de escribirle.

La propiedad que estos tests protegen es una sola y no es negociable: la
captura **no puede** enviar un comando de escritura. Se corre contra equipos en
producción, con 283 clientes conectados, y a cualquier hora.
"""

from __future__ import annotations

import pytest

from gpon_module.core.enums import Fabricante
from gpon_module.core.errors import ErrorComando, ErrorValidacion
from gpon_module.core.models import OLT, CredencialesOLT
from gpon_module.core.reloj import RelojFijo
from gpon_module.drivers.catalogo import catalogo_de
from gpon_module.services.captura import ServicioCaptura, es_solo_lectura


class RepositorioOLTFalso:
    def __init__(self, olt: OLT) -> None:
        self._olt = olt

    def obtener(self, _olt_id: int) -> OLT:
        return self._olt

    def obtener_credenciales(self, _olt_id: int) -> CredencialesOLT:
        return CredencialesOLT(usuario="admin", password="secreta")


class TransporteFalso:
    """Transporte que contesta según un guion y anota todo lo que recibió."""

    def __init__(self, respuestas: dict[str, str] | None = None) -> None:
        self.respuestas = respuestas or {}
        self.ejecutados: list[str] = []
        self.ayudas_pedidas: list[str] = []
        self.abierto = False
        self.cerrado = False

    def abrir(self) -> None:
        self.abierto = True

    def cerrar(self) -> None:
        self.cerrado = True

    def ejecutar(self, comando: str) -> str:
        self.ejecutados.append(comando)
        if comando not in self.respuestas:
            raise ErrorComando("% Invalid input detected", comando=comando)
        return self.respuestas[comando]

    def ayuda(self, prefijo: str = "") -> str:
        self.ayudas_pedidas.append(prefijo)
        return f"opciones de '{prefijo}'"


@pytest.fixture
def olt() -> OLT:
    return OLT(id=1, nombre="Zona Belgrano", host="192.168.1.10", fabricante=Fabricante.VSOL)


@pytest.fixture
def armar(olt):
    def _armar(transporte: TransporteFalso) -> ServicioCaptura:
        return ServicioCaptura(
            RepositorioOLTFalso(olt),
            reloj=RelojFijo(),
            fabrica_transporte=lambda **_kwargs: transporte,
        )

    return _armar


class TestFiltroDeEscritura:
    @pytest.mark.parametrize(
        "comando",
        [
            "show version",
            "display board 0",
            "dir flash:",
            "  show onu  ",
            "SHOW ONU",
        ],
    )
    def test_los_comandos_de_lectura_pasan(self, comando: str) -> None:
        assert es_solo_lectura(comando)

    @pytest.mark.parametrize(
        "comando",
        [
            "configure terminal",
            "onu delete 1",
            "reboot",
            "write memory",
            "no onu 3",
            "show version | delete",  # redirección: podría escribir
            "show version; reboot",  # dos comandos en uno
            "",
            "   ",
        ],
    )
    def test_todo_lo_demas_se_rechaza(self, comando: str) -> None:
        assert not es_solo_lectura(comando)

    def test_un_comando_de_escritura_no_llega_a_abrir_la_sesion(self, armar) -> None:
        """Se corta antes de tocar la red, no después."""
        transporte = TransporteFalso()
        servicio = armar(transporte)

        with pytest.raises(ErrorValidacion, match="sólo envía comandos de lectura"):
            servicio.capturar(1, comandos=["show version", "onu delete 1"])

        assert not transporte.abierto
        assert transporte.ejecutados == []

    def test_el_catalogo_propio_pasa_por_el_mismo_filtro(self) -> None:
        """Un error de tipeo en el catálogo no puede volverse un comando real."""
        for candidato in catalogo_de(Fabricante.VSOL):
            assert es_solo_lectura(candidato.comando), candidato.comando


class TestCaptura:
    def test_guarda_la_salida_de_lo_que_el_equipo_contesta(self, armar) -> None:
        transporte = TransporteFalso({"show version": "Model: V1600G1"})
        captura = armar(transporte).capturar(1, comandos=["show version"], incluir_ayuda=False)

        assert len(captura.aceptados) == 1
        assert captura.aceptados[0].salida == "Model: V1600G1"

    def test_un_comando_inexistente_se_registra_en_vez_de_abortar(self, armar) -> None:
        """Que el firmware no conozca un comando es información, no una falla."""
        transporte = TransporteFalso({"show version": "V1600G1"})
        captura = armar(transporte).capturar(
            1, comandos=["show version", "show onu autofind"], incluir_ayuda=False
        )

        assert [s.comando for s in captura.aceptados] == ["show version"]
        assert [s.comando for s in captura.rechazados] == ["show onu autofind"]
        # y sobre todo: se siguió probando después del rechazo
        assert len(transporte.ejecutados) == 2

    def test_pide_la_ayuda_en_linea_del_fabricante(self, armar) -> None:
        transporte = TransporteFalso({"show version": "V1600G1"})
        captura = armar(transporte).capturar(1, comandos=["show version"])

        assert transporte.ayudas_pedidas  # el árbol de comandos del equipo real
        assert len(captura.ayudas) == len(transporte.ayudas_pedidas)

    def test_la_sesion_se_cierra_aunque_algo_falle(self, armar) -> None:
        class TransporteQueExplota(TransporteFalso):
            def ejecutar(self, comando: str) -> str:
                raise RuntimeError("se cayó el equipo")

        transporte = TransporteQueExplota()
        with pytest.raises(RuntimeError):
            armar(transporte).capturar(1, comandos=["show version"], incluir_ayuda=False)

        assert transporte.cerrado

    def test_el_texto_dice_que_no_se_modifico_nada(self, armar) -> None:
        """Quien reciba el archivo tiene que poder confiar en eso sin leerlo entero."""
        transporte = TransporteFalso({"show version": "V1600G1"})
        captura = armar(transporte).capturar(1, comandos=["show version"], incluir_ayuda=False)

        texto = captura.a_texto()
        assert "Ninguna configuración fue" in texto
        assert "show version" in texto
        assert "V1600G1" in texto
        assert "192.168.1.10" in texto
