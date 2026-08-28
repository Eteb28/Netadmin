"""Pruebas del script de copia de datos a PostgreSQL.

No hace falta un PostgreSQL corriendo: la lógica riesgosa —orden por
dependencias, idempotencia, columnas que no coinciden, verificación de
conteos— es independiente del motor y se ejercita contra SQLite. Lo único
específico de PostgreSQL es `resincronizar_secuencias()`, que se prueba en el
entorno real.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sqlite3

import pytest
from sqlalchemy import create_engine, text

RUTA = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "migrar_a_postgres.py"
_spec = importlib.util.spec_from_file_location("migrar_a_postgres", RUTA)
mig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mig)


DDL_PADRE = "CREATE TABLE olts(id INTEGER PRIMARY KEY, nombre TEXT)"
DDL_HIJA = (
    "CREATE TABLE onu_senal(id INTEGER PRIMARY KEY, olt_id INTEGER, serial TEXT, "
    "FOREIGN KEY(olt_id) REFERENCES olts(id))"
)


@pytest.fixture()
def par(tmp_path):
    """Un SQLite de origen con datos y otro de destino con el esquema vacío."""
    o = tmp_path / "origen.db"
    con = sqlite3.connect(o)
    con.execute(DDL_PADRE)
    con.execute(DDL_HIJA)
    con.execute("INSERT INTO olts VALUES(1,'OLT Crespo'),(2,'OLT El Pingo')")
    con.executemany("INSERT INTO onu_senal VALUES(?,?,?)",
                    [(i, 1, f"SN{i}") for i in range(1, 2501)])   # dos lotes y medio
    con.commit()
    con.close()

    destino = create_engine(f"sqlite:///{tmp_path/'destino.db'}", future=True)
    with destino.begin() as cx:
        cx.execute(text(DDL_PADRE))
        cx.execute(text(DDL_HIJA))
    return sqlite3.connect(o), destino


class TestOrden:
    def test_el_padre_va_antes_que_la_hija(self, par):
        _, destino = par
        assert mig.orden_de_copia(destino, ["onu_senal", "olts"]) == ["olts", "onu_senal"]

    def test_un_ciclo_no_cuelga(self, tmp_path):
        d = create_engine(f"sqlite:///{tmp_path/'c.db'}", future=True)
        with d.begin() as cx:
            cx.execute(text("CREATE TABLE a(id INTEGER PRIMARY KEY, b_id INTEGER REFERENCES b(id))"))
            cx.execute(text("CREATE TABLE b(id INTEGER PRIMARY KEY, a_id INTEGER REFERENCES a(id))"))
        assert sorted(mig.orden_de_copia(d, ["a", "b"])) == ["a", "b"]


class TestCopia:
    def test_copia_todo_incluidos_varios_lotes(self, par):
        origen, destino = par
        for t in ("olts", "onu_senal"):
            mig.copiar_tabla(origen, destino, t, dry_run=False)
        with destino.connect() as cx:
            assert cx.execute(text("SELECT COUNT(*) FROM onu_senal")).scalar() == 2500

    def test_es_idempotente(self, par):
        """Correrlo dos veces no duplica ni explota: es lo que permite retomar
        una migración interrumpida sin restaurar un backup."""
        origen, destino = par
        for _ in range(2):
            for t in ("olts", "onu_senal"):
                mig.copiar_tabla(origen, destino, t, dry_run=False)
        with destino.connect() as cx:
            assert cx.execute(text("SELECT COUNT(*) FROM olts")).scalar() == 2
            assert cx.execute(text("SELECT COUNT(*) FROM onu_senal")).scalar() == 2500

    def test_dry_run_no_escribe(self, par):
        origen, destino = par
        leidas, insertadas = mig.copiar_tabla(origen, destino, "olts", dry_run=True)
        assert leidas == 2 and insertadas == 0
        with destino.connect() as cx:
            assert cx.execute(text("SELECT COUNT(*) FROM olts")).scalar() == 0

    def test_una_columna_que_ya_no_existe_no_rompe_la_copia(self, tmp_path):
        """El esquema nuevo puede haber quitado una columna: eso no puede
        abortar la migración de las 300.000 filas restantes."""
        o = tmp_path / "o.db"
        con = sqlite3.connect(o)
        con.execute("CREATE TABLE t(id INTEGER PRIMARY KEY, vivo TEXT, obsoleta TEXT)")
        con.execute("INSERT INTO t VALUES(1,'si','basura')")
        con.commit(); con.close()

        d = create_engine(f"sqlite:///{tmp_path/'d.db'}", future=True)
        with d.begin() as cx:
            cx.execute(text("CREATE TABLE t(id INTEGER PRIMARY KEY, vivo TEXT)"))

        leidas, _ = mig.copiar_tabla(sqlite3.connect(o), d, "t", dry_run=False)
        assert leidas == 1
        with d.connect() as cx:
            assert cx.execute(text("SELECT vivo FROM t")).scalar() == "si"


class TestVerificacion:
    def test_detecta_una_copia_incompleta(self, par):
        origen, destino = par
        mig.copiar_tabla(origen, destino, "olts", dry_run=False)   # falta onu_senal
        problemas = mig.verificar(origen, destino, ["olts", "onu_senal"])
        assert len(problemas) == 1 and "onu_senal" in problemas[0]

    def test_no_reporta_nada_cuando_esta_completo(self, par):
        origen, destino = par
        for t in ("olts", "onu_senal"):
            mig.copiar_tabla(origen, destino, t, dry_run=False)
        assert mig.verificar(origen, destino, ["olts", "onu_senal"]) == []
