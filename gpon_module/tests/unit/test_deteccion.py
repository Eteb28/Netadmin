"""Sondeo de los puertos de gestión.

Lo que estos tests protegen es la distinción entre dos fallas que se parecen y
no lo son: el equipo dice que no (servicio apagado) y el equipo no dice nada
(firewall o ACL). Confundirlas cuesta una tarde de revisar credenciales que
estaban bien.
"""

from __future__ import annotations

import socket

import pytest

from gpon_module.drivers.transport.deteccion import (
    EstadoPuerto,
    sondear_gestion,
    sondear_puerto,
)


class SocketFalso:
    def close(self) -> None:
        self.cerrado = True


@pytest.fixture
def simular_conexion(monkeypatch):
    def _simular(resultado):
        def _crear(*_a, **_k):
            if isinstance(resultado, BaseException):
                raise resultado
            return resultado

        monkeypatch.setattr(socket, "create_connection", _crear)

    return _simular


def test_un_puerto_que_atiende_esta_abierto(simular_conexion) -> None:
    simular_conexion(SocketFalso())
    sondeo = sondear_puerto("192.168.10.247", 23)

    assert sondeo.estado is EstadoPuerto.ABIERTO
    assert sondeo.abierto
    assert sondeo.servicio == "Telnet"


def test_un_rechazo_no_es_lo_mismo_que_un_silencio(simular_conexion) -> None:
    """Rechazado significa que se llega al equipo: el problema está en el equipo."""
    simular_conexion(ConnectionRefusedError(111, "Connection refused"))
    sondeo = sondear_puerto("192.168.10.247", 23)

    assert sondeo.estado is EstadoPuerto.RECHAZADO
    assert "servicio está apagado" in sondeo.explicacion


def test_un_timeout_apunta_al_camino_y_no_al_equipo(simular_conexion) -> None:
    simular_conexion(TimeoutError("timed out"))
    sondeo = sondear_puerto("192.168.10.247", 23)

    assert sondeo.estado is EstadoPuerto.SIN_RESPUESTA
    assert "firewall" in sondeo.explicacion


def test_se_sondean_los_puertos_de_gestion_en_orden(simular_conexion) -> None:
    simular_conexion(TimeoutError("timed out"))
    sondeos = sondear_gestion("192.168.10.247", timeout=0.1)

    assert [s.puerto for s in sondeos] == [23, 22, 443, 80]
    assert all(not s.abierto for s in sondeos)
