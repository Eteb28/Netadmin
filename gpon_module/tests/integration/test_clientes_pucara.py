"""Lectura de la base comercial, contra una copia de su estructura real.

Las columnas y los formatos son los de Pucará —``nro_cliente``, ``nap`` escrito
como ``PUERTOSANCHEZ - CDO: 8 - NAP: 3``, el modelo de ONU adentro de una
descripción larga—, porque son justamente esos formatos los que hay que
interpretar bien. Un test contra datos idealizados no probaría nada.
"""

from __future__ import annotations

import sqlite3

import pytest

from gpon_module.core.errors import ErrorRepositorio, NoEncontrado
from gpon_module.database.repositories import RepositorioClientesPucara

ESQUEMA = """
CREATE TABLE clientes (
    nro_cliente TEXT, nombre TEXT, plan TEXT, tipo_servicio TEXT, estado TEXT,
    nap TEXT, pppoe_usuario TEXT, pppoe_clave TEXT,
    equipo_modelo TEXT, equipo_serie TEXT
);
CREATE TABLE abonos (nombre TEXT, velocidad_bajada INTEGER, velocidad_subida INTEGER);
"""

FILAS = [
    (
        "034716", "CABRERA JONAS LAZARO MARIANO", "INTERNET 10 MB", "fibra", "activo",
        "PUERTOSANCHEZ - CDO: 8 - NAP: 3", "034716", "fdcc",
        "ONU VSOL 2GE+1POTS+WIFI AC BRIDGE/ROUTER V2802DAC XPON", "GPON00780CBB",
    ),
    (
        "035235", "RONDAN ROCIO GRISELDA", "INTERNET 50 MB", "fibra", "activo",
        "ESCHOGAR - CDO: 21 - NAP: 2", "035235", "a91e",
        "ONU VSOL 2GE+1POTS+WIFI AC BRIDGE/ROUTER V2802DAC XPON", "VSOL000D700E",
    ),
    # Un plan tipeado a mano que no existe en la tabla de abonos.
    (
        "040001", "SIN ABONO CARGADO", "Abono residencial FIBRA 100 MB (Efectivo)",
        "fibra", "activo", "CHARRUA - CDO: 2 - NAP: 1", "040001", "beef",
        "ONU VSOL V2801RGW", "GPON00AAAA01",
    ),
    # Sin NAP cargada y sin equipo: el caso incompleto, que existe.
    ("040002", "SIN NAP", "INTERNET 20 MB", "fibra", "activo", "", "", "", "", ""),
]


@pytest.fixture
def repositorio(tmp_path):
    base = tmp_path / "netadmin.db"
    with sqlite3.connect(base) as conexion:
        conexion.executescript(ESQUEMA)
        conexion.executemany("INSERT INTO clientes VALUES (?,?,?,?,?,?,?,?,?,?)", FILAS)
        conexion.executemany(
            "INSERT INTO abonos VALUES (?,?,?)",
            [("INTERNET 10 MB", 10, 5), ("INTERNET 50 MB", 50, 25), ("INTERNET 20 MB", 20, 10)],
        )
    return RepositorioClientesPucara(base)


class TestLectura:
    def test_trae_al_cliente_con_todo_lo_que_hace_falta(self, repositorio) -> None:
        cliente = repositorio.buscar("034716")

        assert cliente.nombre == "CABRERA JONAS LAZARO MARIANO"
        assert cliente.plan == "INTERNET 10 MB"
        assert cliente.megabits_bajada == 10
        assert cliente.pppoe_usuario == "034716"
        assert cliente.pppoe_password == "fdcc"

    def test_parte_la_ubicacion_en_sitio_cdo_y_nap(self, repositorio) -> None:
        """``ESCHOGAR - CDO: 21 - NAP: 2`` → el sufijo ``CDO21_NAP2``."""
        cliente = repositorio.buscar("035235")

        assert (cliente.sitio, cliente.cdo, cliente.nap) == ("ESCHOGAR", 21, 2)
        assert cliente.ubicacion == "CDO21_NAP2"

    def test_saca_el_modelo_de_onu_de_la_descripcion_larga(self, repositorio) -> None:
        assert repositorio.buscar("034716").modelo_equipo == "V2802DAC"
        assert repositorio.buscar("040001").modelo_equipo == "V2801RGW"

    def test_los_megas_salen_del_nombre_cuando_no_hay_abono(self, repositorio) -> None:
        """Hay planes tipeados a mano que no están en la tabla de abonos."""
        cliente = repositorio.buscar("040001")

        assert cliente.megabits_bajada == 100

    def test_un_numero_con_espacios_igual_se_encuentra(self, repositorio) -> None:
        """El número llega copiado de un mensaje."""
        assert repositorio.buscar("  034716  ").numero == "034716"

    def test_un_cliente_inexistente_lo_dice(self, repositorio) -> None:
        with pytest.raises(NoEncontrado, match="999999"):
            repositorio.buscar("999999")


class TestDatosIncompletos:
    def test_sin_nap_no_se_inventa_la_ubicacion(self, repositorio) -> None:
        cliente = repositorio.buscar("040002")

        assert cliente.cdo is None and cliente.nap is None
        assert cliente.ubicacion == ""

    def test_sin_equipo_el_modelo_queda_vacio(self, repositorio) -> None:
        assert repositorio.buscar("040002").modelo_equipo == ""


class TestAislamiento:
    def test_sin_base_configurada_lo_dice_en_vez_de_romper(self, tmp_path) -> None:
        repositorio = RepositorioClientesPucara(tmp_path / "no-existe.db")

        assert not repositorio.disponible
        with pytest.raises(ErrorRepositorio, match="No se encuentra"):
            repositorio.buscar("034716")

    def test_la_contrasena_no_se_filtra_al_imprimir(self, repositorio) -> None:
        """Un log con la clave PPPoE de un cliente es una fuga de credenciales."""
        cliente = repositorio.buscar("034716")

        assert "fdcc" not in repr(cliente)
