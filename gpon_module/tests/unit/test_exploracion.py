"""Exploración de los modos de la CLI.

Este servicio entra a modo configuración, que es más de lo que hace el resto del
módulo. Lo que estos tests protegen es el límite exacto de ese permiso: sólo
navegar entre modos y leer, nunca configurar, y salir siempre.
"""

from __future__ import annotations

import pytest

from gpon_module.core.enums import Fabricante
from gpon_module.core.errors import ErrorComando, ErrorValidacion
from gpon_module.core.models import OLT, CredencialesOLT
from gpon_module.core.reloj import RelojFijo
from gpon_module.services.exploracion import (
    CANDIDATOS_INTERFAZ_PON,
    ServicioExploracion,
    es_navegacion,
    es_permitido,
)


class RepositorioOLTFalso:
    def obtener(self, _olt_id: int) -> OLT:
        return OLT(id=1, nombre="Belgrano", host="10.0.0.1", fabricante=Fabricante.VSOL)

    def obtener_credenciales(self, _olt_id: int) -> CredencialesOLT:
        return CredencialesOLT(usuario="eaguiar", password="x")


class TransporteFalso:
    def __init__(self, respuestas: dict[str, str] | None = None) -> None:
        self.respuestas = respuestas or {}
        self.ejecutados: list[str] = []
        self.ayudas: list[str] = []
        self.cerrado = False

    def abrir(self) -> None: ...

    def cerrar(self) -> None:
        self.cerrado = True

    def ejecutar(self, comando: str) -> str:
        self.ejecutados.append(comando)
        if comando in self.respuestas:
            return self.respuestas[comando]
        if comando.startswith("show "):
            raise ErrorComando("% Unknown command", comando=comando)
        return ""

    def ayuda(self, prefijo: str = "") -> str:
        self.ayudas.append(prefijo)
        return f"opciones de '{prefijo}'"


@pytest.fixture
def armar():
    def _armar(transporte: TransporteFalso) -> ServicioExploracion:
        return ServicioExploracion(
            RepositorioOLTFalso(),
            reloj=RelojFijo(),
            fabrica_transporte=lambda **_kwargs: transporte,
        )

    return _armar


class TestPermisos:
    @pytest.mark.parametrize(
        "comando",
        ["configure terminal", "interface gpon 0/1", "interface gpon 1/16", "exit", "end", "quit"],
    )
    def test_la_navegacion_permitida(self, comando: str) -> None:
        assert es_navegacion(comando)

    @pytest.mark.parametrize(
        "comando",
        [
            "onu add 1 profile V2802GW sn GPON002E64F8",
            "no onu auto-learn",
            "interface gigabitethernet 0/1",
            "interface gpon",
            "write memory",
            "configure",
        ],
    )
    def test_todo_lo_que_configura_queda_afuera(self, comando: str) -> None:
        assert not es_navegacion(comando)
        assert not es_permitido(comando)

    def test_los_candidatos_del_catalogo_son_todos_de_lectura(self) -> None:
        for comando, _ in CANDIDATOS_INTERFAZ_PON:
            assert es_permitido(comando), comando

    def test_un_puerto_pon_mal_escrito_se_rechaza_antes_de_conectarse(self, armar) -> None:
        transporte = TransporteFalso()
        with pytest.raises(ErrorValidacion, match="Puerto PON inválido"):
            armar(transporte).explorar(1, pon="0/1 ; reboot")
        assert transporte.ejecutados == []


class TestRecorrido:
    def test_entra_a_los_dos_modos_y_vuelve(self, armar) -> None:
        transporte = TransporteFalso()

        exploracion = armar(transporte).explorar(1, pon="0/3")

        assert transporte.ejecutados[0] == "configure terminal"
        assert "interface gpon 0/3" in transporte.ejecutados
        assert transporte.ejecutados[-1] == "end"
        assert exploracion.recorrido == (
            "exec",
            "configure terminal",
            "interface gpon 0/3",
            "end",
        )

    def test_solo_ejecuta_navegacion_y_lectura(self, armar) -> None:
        """El invariante entero del servicio, comprobado sobre lo que salió."""
        transporte = TransporteFalso()

        armar(transporte).explorar(1)

        for comando in transporte.ejecutados:
            assert es_permitido(comando), comando

    def test_vuelve_al_modo_exec_aunque_algo_falle(self, armar) -> None:
        """Dejar la sesión en modo configuración confunde a quien entre después."""

        class TransporteQueExplota(TransporteFalso):
            def ejecutar(self, comando: str) -> str:
                self.ejecutados.append(comando)
                if comando.startswith("show onu"):
                    raise RuntimeError("se cayó el equipo")
                return ""

        transporte = TransporteQueExplota()
        with pytest.raises(RuntimeError):
            armar(transporte).explorar(1)

        assert "end" in transporte.ejecutados
        assert transporte.cerrado

    def test_recoge_el_listado_de_onu_sin_autorizar(self, armar) -> None:
        autofind = "Index  Sn              State\n1      GPON002E64F8    Unknown"
        transporte = TransporteFalso({"show onu autofind": autofind})

        exploracion = armar(transporte).explorar(1)

        aceptado = next(s for s in exploracion.aceptados if s.comando == "show onu autofind")
        assert "GPON002E64F8" in aceptado.salida

    def test_el_texto_deja_constancia_de_lo_que_se_hizo(self, armar) -> None:
        transporte = TransporteFalso()

        texto = armar(transporte).explorar(1).a_texto()

        assert "No se" in texto and "configuración" in texto
        assert "exec → configure terminal" in texto
