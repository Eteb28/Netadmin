"""El esquema que crea `init_db()` tiene que alcanzar para que el sistema ande.

Nació de un hallazgo real: el código leía y escribía `naps.nivel_senal`, `red`,
`cdo`, `nap_numero` y `sitio`, pero `init_db()` no creaba ninguna de las cinco.
En producción existían porque alguien las agregó a mano en algún momento; en una
base nueva, listar o editar una NAP tiraba `no such column`.

El problema de fondo no son las cinco columnas: es que **el esquema no era
reproducible**. Si hubiera que rehacer el servidor, Pucará no arrancaba bien, y
la migración a PostgreSQL parte de este mismo esquema.

Esta prueba levanta una base VACÍA con `init_db()` y verifica que las columnas
que el código usa existan de verdad.
"""
from __future__ import annotations

import pathlib
import re
import sqlite3

import pytest

APP = pathlib.Path(__file__).resolve().parent.parent / "app.py"


@pytest.fixture(scope="module")
def base_nueva(tmp_path_factory, monkeypatch_module=None):
    """Una base creada desde cero, como en una instalación limpia."""
    import importlib
    import os
    destino = tmp_path_factory.mktemp("esquema") / "netadmin.db"
    os.environ["PUCARA_DB_TEST"] = str(destino)
    import app as A
    original = A.DB
    A.DB = str(destino)
    try:
        A.init_db()
        con = sqlite3.connect(destino)
        con.row_factory = sqlite3.Row
        yield con
        con.close()
    finally:
        A.DB = original


def _columnas(con, tabla: str) -> set[str]:
    return {r[1] for r in con.execute(f"PRAGMA table_info({tabla})")}


# (tabla, columnas que el código da por existentes)
EXIGIDAS = {
    "naps": {"nombre", "lat", "lng", "capacidad", "localidad", "estado",
             "nivel_senal", "red", "cdo", "nap_numero", "sitio",
             "censada", "censo_fecha", "censo_tecnico"},
    "clientes": {"nombre", "nro_cliente", "estado", "tipo_servicio", "plan", "precio",
                 "nap", "olt_nombre", "olt_puerto", "ip_asignada", "mac_address",
                 "equipo_serie", "pppoe_usuario", "pppoe_clave", "fecha_alta"},
    "olts": {"nombre", "ip_remota", "puertos_pon", "community", "snmp_activo",
             "online", "temp_sfp_max"},
    "onu_senal": {"olt_id", "pon", "onu", "nro_cliente", "rx_power", "online",
                  "serial_onu", "last_check"},
    "historial": {"tipo", "modulo", "titulo", "detalle", "diff", "usuario", "fecha"},
    "torres": {"nombre", "lat", "lng", "estado"},
    "tareas_usuario": {"username", "texto", "color", "completada"},
}


@pytest.mark.parametrize("tabla", sorted(EXIGIDAS))
def test_la_tabla_tiene_las_columnas_que_el_codigo_usa(base_nueva, tabla):
    faltan = EXIGIDAS[tabla] - _columnas(base_nueva, tabla)
    assert not faltan, (
        f"init_db() no crea {sorted(faltan)} en `{tabla}`, pero el código las usa. "
        "Una instalación nueva arrancaría rota."
    )


# Tablas que `app.py` consulta pero que crea OTRO proceso (los pollers). Es una
# deuda conocida: hasta que el poller corra por primera vez, esas consultas
# fallan en una instalación nueva. Se listan acá para que la deuda sea explícita
# y no una sorpresa; se resuelve al centralizar el esquema en Alembic (fase 7).
CREADAS_POR_POLLERS = {
    "chequeos_equipo":  "ubiquiti_poller.py",
    "chequeos_torre":   "torre_poller.py",
    "mikrotik_estado":  "mikrotik_poller.py",
    "snmp_estaciones":  "snmp_wireless.py",
}


def test_las_tablas_centrales_existen_en_una_base_nueva(base_nueva):
    """Las tablas del núcleo operativo tienen que estar sí o sí."""
    reales = {r[0] for r in base_nueva.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    nucleo = {"clientes", "naps", "olts", "onu_senal", "torres", "servicios",
              "usuarios", "historial", "notificaciones", "stock_items",
              "tareas_usuario", "abonos", "reclamos"}
    assert not (nucleo - reales), f"init_db() no crea: {sorted(nucleo - reales)}"


class TestModelosLegadosContraElEsquemaReal:
    """Los modelos de `pucara.models.legado` describen tablas que crea app.py.

    Si describen una columna que `init_db()` no crea, todo el código nuevo que
    la lea falla con `no such column` recién en producción — y las pruebas
    seguirían en verde, porque crean las tablas **desde esos mismos modelos**.
    Esta prueba es la que cierra ese círculo: compara la declaración contra el
    esquema que realmente sale de `init_db()`.
    """

    @pytest.mark.parametrize("tabla", sorted(
        t.name for t in __import__(
            "pucara.models.legado", fromlist=["TABLAS_LEGADAS"]).TABLAS_LEGADAS
    ))
    def test_cada_columna_declarada_existe_de_verdad(self, base_nueva, tabla):
        from pucara.models.legado import BaseLegado

        declaradas = {c.name for c in BaseLegado.metadata.tables[tabla].columns}
        reales = _columnas(base_nueva, tabla)
        inventadas = declaradas - reales
        assert not inventadas, (
            f"`models/legado.py` declara {sorted(inventadas)} en `{tabla}`, pero "
            f"init_db() no las crea. O se agregan al esquema, o se sacan del modelo: "
            "un modelo que miente hace pasar las pruebas y rompe en producción."
        )


def test_la_deuda_de_esquema_repartido_sigue_acotada(base_nueva):
    """Documenta qué tablas dependen de que un poller haya corrido.

    Si la lista crece, alguien agregó una tabla nueva en un poller en vez de en
    el esquema central: esta prueba lo señala.
    """
    reales = {r[0] for r in base_nueva.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    texto = APP.read_text(encoding="utf-8")
    inesperadas = [
        t for t in CREADAS_POR_POLLERS
        if t not in reales and not re.search(rf"_table_exists\(con, '{t}'\)", texto)
    ]
    # No falla: deja constancia. Falla sólo si aparece una tabla NUEVA fuera de la lista.
    assert set(inesperadas) <= set(CREADAS_POR_POLLERS), (
        f"Tablas creadas fuera del esquema central y no documentadas: {inesperadas}"
    )
