"""El esquema nuevo tiene que convivir con el heredado, no pisarlo.

Esta prueba nació de un choque real: el modelo `Reclamo` se llamaba `reclamos`,
que es el nombre de la tabla espejo de los tickets de Tero HelpDesk. En una base
nueva la migración de Alembic la creaba primero y después `init_db()` la daba por
existente (`CREATE TABLE IF NOT EXISTS`), dejando la sincronización de Tero rota
por columnas que no existían. En la base actual, al revés, la migración falla.

Ninguna de las dos se nota hasta el despliegue. Acá se nota en CI.
"""
from __future__ import annotations

import pathlib
import re

from pucara.db import Base
from pucara.models import adjuntos, incidentes, reclamos  # noqa: F401

APP = pathlib.Path(__file__).resolve().parent.parent / "app.py"


def _tablas_del_legado() -> set[str]:
    texto = APP.read_text(encoding="utf-8")
    return {
        m.lower()
        for m in re.findall(r"CREATE TABLE (?:IF NOT EXISTS )?[\"']?(\w+)", texto, re.I)
    }


def test_ningun_modelo_pisa_una_tabla_heredada():
    choques = sorted(set(Base.metadata.tables) & _tablas_del_legado())
    assert not choques, (
        f"Estos modelos usan un nombre de tabla que app.py ya crea: {choques}. "
        "Elegí otro nombre o migrá la tabla heredada por completo."
    )


def test_el_legado_declara_las_tablas_que_las_consultas_nuevas_leen():
    """Los repositorios de las fases 5 y 6 leen tablas heredadas. Si alguien
    las renombra en app.py, esto avisa."""
    legado = _tablas_del_legado()
    for tabla in ("clientes", "onu_senal", "olts"):
        assert tabla in legado, f"Falta la tabla heredada {tabla}"


class TestAislamientoDeAlembic:
    """La regla más importante de la fase 7, y la más fácil de romper sin querer.

    Los modelos de `pucara.models.legado` describen tablas que administra
    `app.py`. Si alguien los mueve a `pucara.db.Base` —cambiando una sola línea
    de herencia—, `migrations/env.py` deja de ignorarlas y el próximo
    `alembic revision --autogenerate` genera ALTERs sobre `clientes` y
    `onu_senal` a imagen de unas declaraciones que son PARCIALES a propósito.
    Aplicado en producción, eso borra columnas.
    """

    def test_los_modelos_heredados_no_estan_en_la_metadata_de_alembic(self):
        from pucara.models.legado import BaseLegado

        invasores = sorted(set(BaseLegado.metadata.tables) & set(Base.metadata.tables))
        assert not invasores, (
            f"Estas tablas heredadas entraron en Base.metadata: {invasores}. "
            "Alembic las administraría y las tablas de producción quedan expuestas "
            "a un autogenerate. Tienen que heredar de BaseLegado."
        )

    def test_alembic_sigue_ignorando_lo_que_no_modela(self):
        """`_incluir_objeto` es lo que protege a las ~40 tablas heredadas."""
        env = (pathlib.Path(__file__).resolve().parent.parent
               / "migrations" / "env.py").read_text(encoding="utf-8")
        assert "include_object=_incluir_objeto" in env
        assert env.count("include_object=_incluir_objeto") == 2, (
            "Tiene que estar en los dos modos, online y offline"
        )


def test_las_pruebas_no_escriben_ddl_de_tablas_heredadas():
    """Una sola declaración de cada tabla heredada: la de `models/legado.py`.

    Antes, cada archivo de pruebas escribía su propio `CREATE TABLE naps(...)`.
    Esas copias se desincronizaban del esquema real y por eso las cinco
    columnas faltantes de `naps` pasaron meses sin que ninguna prueba las
    señalara: el DDL de juguete tampoco las tenía.
    """
    from pucara.models.legado import BaseLegado

    #: Dos archivos sí escriben DDL a mano, y está bien: no arman el esquema de
    #: la aplicación, arman una base de ORIGEN falsa —con el esquema viejo, con
    #: rarezas de SQLite, a veces con columnas que ya no existen— para probar
    #: que el copiador y el generador de DDL las sobreviven. Usar los modelos
    #: ahí anularía justamente lo que esas pruebas verifican.
    EXENTOS = {
        "test_migracion_datos.py",
        "test_esquema_heredado.py",
        pathlib.Path(__file__).name,
    }

    heredadas = set(BaseLegado.metadata.tables)
    infractores = []
    for p in pathlib.Path(__file__).resolve().parent.glob("test_*.py"):
        if p.name in EXENTOS:
            continue
        texto = p.read_text(encoding="utf-8")
        for tabla in re.findall(r"CREATE TABLE (?:IF NOT EXISTS )?[\"']?(\w+)", texto, re.I):
            if tabla.lower() in heredadas:
                infractores.append(f"{p.name} → {tabla}")
    assert not infractores, (
        f"DDL a mano de tablas ya modeladas: {infractores}. "
        "Usá tests.motores.crear_esquema()."
    )
