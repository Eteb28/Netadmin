"""Un solo lugar donde se decide contra qué motor corren las pruebas.

Por defecto, SQLite en memoria: rápido y sin nada que instalar, que es lo que
permite correr la suite en cualquier máquina y en CI.

Si se define `PUCARA_TEST_PG_URL`, **la misma suite corre contra PostgreSQL**:

    export PUCARA_TEST_PG_URL="postgresql+psycopg2://pucara@127.0.0.1:5432/pucara_test"
    python3 -m pytest -q

Ése es el paso 1 de la fase 7 ("pruebas de caracterización"): no alcanza con
razonar que una consulta es portable, hay que ejecutarla en el motor destino.
Las diferencias que encontró esta doble ejecución están anotadas en
`docs/PREPARACION-FASES-7-8.md`.

Las tablas heredadas se crean desde `pucara.models.legado` y no con DDL escrito
a mano en cada archivo: esas copias se desincronizaban del esquema real (así
pasaron inadvertidas las cinco columnas faltantes de `naps`).
"""
from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool

from pucara.db import Base
from pucara.models import adjuntos, incidentes, reclamos  # noqa: F401
from pucara.models.legado import BaseLegado


def url_postgres() -> str | None:
    return os.environ.get("PUCARA_TEST_PG_URL")


#: Marca para saltear una prueba que sólo tiene sentido en un motor.
solo_postgres = pytest.mark.skipif(
    url_postgres() is None, reason="requiere PUCARA_TEST_PG_URL"
)


def motor(tmp_path=None) -> Engine:
    """Motor limpio para una prueba.

    Con PostgreSQL se borra y recrea el esquema `public`: es la forma más
    rápida y confiable de dejar la base como nueva, y no depende de acordarse
    de qué tablas creó cada prueba.
    """
    url = url_postgres()
    if url:
        eng = create_engine(url, future=True, poolclass=NullPool)
        with eng.connect() as con:
            # Cortar primero las conexiones que quedaron abiertas de la prueba
            # anterior. Varios fixtures devuelven la sesión con `return` y no la
            # cierran; en SQLite eso es inofensivo, pero PostgreSQL bloquea el
            # DROP SCHEMA hasta que el otro backend suelte el lock y la suite
            # se cuelga sin decir por qué. Es la misma diferencia que va a
            # aparecer en producción: en Postgres una sesión olvidada frena un
            # DDL, en SQLite no.
            con.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = current_database() AND pid <> pg_backend_pid()"
                )
            )
            con.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            con.execute(text("CREATE SCHEMA public"))
            con.commit()
        return eng

    if tmp_path is not None:
        # Algunas pruebas necesitan un archivo: la app abre su propia sesión y
        # una base ":memory:" sería otra base distinta para cada conexión.
        eng = create_engine(f"sqlite:///{tmp_path}/t.db", future=True)
    else:
        eng = create_engine("sqlite://", future=True)

    @event.listens_for(eng, "connect")
    def _fk(dbapi_con, _record):
        # Igual que en producción: sin esto las claves foráneas de los modelos
        # son decorativas en SQLite y darían un falso verde frente a PostgreSQL.
        cur = dbapi_con.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    return eng


def crear_esquema(eng: Engine, legado: bool = True) -> None:
    """Tablas del dominio nuevo y, si se piden, las heredadas."""
    Base.metadata.create_all(eng)
    if legado:
        BaseLegado.metadata.create_all(eng)
