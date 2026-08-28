"""Pruebas del generador de DDL de las tablas heredadas.

Este script es el que llena el hueco de la fase 8 paso 1: las ~50 tablas que
`init_db()` crea con DDL de SQLite y que PostgreSQL no acepta. Lo que puede
salir mal no es que falle —eso se ve—, es que produzca un DDL que se aplica sin
error y guarda otra cosa: el caso real fue `DEFAULT 'CURRENT_TIMESTAMP'`
entrecomillado, que deja el texto literal en la columna en vez de la hora.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sqlite3

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

RUTA = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "esquema_heredado_a_postgres.py"
_spec = importlib.util.spec_from_file_location("esquema_heredado", RUTA)
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)


@pytest.fixture()
def origen(tmp_path):
    """Un SQLite con las rarezas que tiene el esquema real de Pucará."""
    ruta = tmp_path / "netadmin.db"
    con = sqlite3.connect(ruta)
    con.executescript("""
        CREATE TABLE clientes(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            precio REAL DEFAULT 0,
            activo INTEGER DEFAULT 1,
            estado TEXT DEFAULT 'activo',
            creado TEXT DEFAULT(datetime('now','localtime')),
            alta TEXT DEFAULT(date('now','localtime'))
        );
        CREATE TABLE snmp_estaciones(
            equipo_id INTEGER NOT NULL, mac TEXT NOT NULL, rssi REAL,
            PRIMARY KEY(equipo_id, mac)
        );
        -- SQLite permite declarar una columna SIN tipo. Es el caso que
        -- devuelve NullType al reflejar y hace fallar create_all.
        CREATE TABLE raro(id INTEGER PRIMARY KEY, valor, otro CUALQUIERCOSA);
    """)
    con.commit(); con.close()
    return str(ruta)


def _ddl(metadata, tabla: str) -> str:
    return str(CreateTable(metadata.tables[tabla])
               .compile(dialect=postgresql.dialect()))


class TestDefaults:
    def test_la_hora_de_sqlite_se_traduce_y_no_se_entrecomilla(self, origen):
        """El error que hubo: `DEFAULT 'CURRENT_TIMESTAMP'` con comillas guarda
        la cadena literal en cada fila en vez de la fecha."""
        md, _ = gen.esquema_portado(origen)
        ddl = _ddl(md, "clientes")
        assert "DEFAULT CURRENT_TIMESTAMP" in ddl
        assert "'CURRENT_TIMESTAMP'" not in ddl

    def test_la_fecha_de_sqlite_se_traduce(self, origen):
        assert "DEFAULT CURRENT_DATE" in _ddl(gen.esquema_portado(origen)[0], "clientes")

    def test_un_literal_de_texto_conserva_una_sola_capa_de_comillas(self, origen):
        assert "DEFAULT 'activo'" in _ddl(gen.esquema_portado(origen)[0], "clientes")

    def test_los_numeros_no_salen_como_texto(self, origen):
        ddl = _ddl(gen.esquema_portado(origen)[0], "clientes")
        assert "DEFAULT 1" in ddl and "DEFAULT '1'" not in ddl

    @pytest.mark.parametrize("entrada,esperado", [
        ("(datetime('now','localtime'))", "CURRENT_TIMESTAMP"),
        ("datetime('now', 'localtime')", "CURRENT_TIMESTAMP"),
        ("(date('now','localtime'))", "CURRENT_DATE"),
        ("CURRENT_TIMESTAMP", "CURRENT_TIMESTAMP"),
        ("0", "0"), ("-1.5", "-1.5"), ("'texto'", "'texto'"),
    ])
    def test_traduccion_directa(self, entrada, esperado):
        assert gen._traducir_default(entrada, [], "x.y") == esperado

    def test_un_default_que_no_se_entiende_se_descarta_con_aviso(self):
        """Mejor sin default que con uno inventado: un default mal traducido
        escribe datos equivocados en silencio."""
        avisos = []
        assert gen._traducir_default("(random())", avisos, "t.c") is None
        assert avisos and "no traducible" in avisos[0]


class TestTipos:
    def test_una_columna_sin_tipo_pasa_a_texto(self, origen):
        """SQLite permite declarar una columna sin tipo; sin esto la reflexión
        devuelve NullType y `create_all` se cae."""
        md, avisos = gen.esquema_portado(origen)
        assert "valor TEXT" in _ddl(md, "raro")
        assert any("raro.valor" in a for a in avisos)

    def test_un_tipo_desconocido_queda_numeric_y_eso_hay_que_mirarlo(self, origen):
        """SQLite le da afinidad NUMERIC a cualquier nombre de tipo que no
        reconoce, y ahí guarda texto igual. PostgreSQL con NUMERIC **no**: un
        valor no numérico lo rechaza al insertar.

        Hoy el esquema real de Pucará no tiene ninguna columna así (verificado),
        pero si alguien agrega una, esta prueba deja escrito qué va a pasar.
        """
        assert "otro NUMERIC" in _ddl(gen.esquema_portado(origen)[0], "raro")

    def test_la_clave_primaria_entera_sale_como_serial(self, origen):
        """La aplicación inserta sin id: si no es SERIAL, falla el primer alta."""
        assert "id SERIAL" in _ddl(gen.esquema_portado(origen)[0], "clientes")

    def test_una_clave_compuesta_no_se_vuelve_serial(self, origen):
        """`snmp_estaciones` tiene PK (equipo_id, mac): ahí no hay autoincremento
        y convertirlo rompería el UPSERT del poller."""
        ddl = _ddl(gen.esquema_portado(origen)[0], "snmp_estaciones")
        assert "SERIAL" not in ddl
        assert "PRIMARY KEY (equipo_id, mac)" in ddl


class TestAlcance:
    def test_no_toca_las_tablas_que_administra_alembic(self, tmp_path):
        """Si este script creara `incidentes`, el `alembic upgrade head`
        posterior fallaría, o quedarían dos definiciones peleando."""
        ruta = tmp_path / "x.db"
        con = sqlite3.connect(ruta)
        con.executescript(
            "CREATE TABLE incidentes(id INTEGER PRIMARY KEY);"
            "CREATE TABLE alembic_version(version_num TEXT);"
            "CREATE TABLE torres(id INTEGER PRIMARY KEY, nombre TEXT);"
        )
        con.commit(); con.close()
        md, _ = gen.esquema_portado(str(ruta))
        assert set(md.tables) == {"torres"}

    def test_no_copia_las_claves_foraneas(self, tmp_path):
        """La base heredada tiene filas huérfanas (pagos de clientes borrados).
        Con las FK puestas antes de migrar, la copia se cae a la mitad."""
        ruta = tmp_path / "y.db"
        con = sqlite3.connect(ruta)
        con.executescript(
            "CREATE TABLE olts(id INTEGER PRIMARY KEY);"
            "CREATE TABLE onu_senal(id INTEGER PRIMARY KEY, olt_id INTEGER "
            "REFERENCES olts(id));"
        )
        con.commit(); con.close()
        md, _ = gen.esquema_portado(str(ruta))
        assert "REFERENCES" not in _ddl(md, "onu_senal")
