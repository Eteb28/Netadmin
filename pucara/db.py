"""Configuración de la base de datos (SQLAlchemy).

Punto ÚNICO donde se crea el engine y la sesión. Ningún otro módulo debe abrir
conexiones por su cuenta: esa dispersión (19 archivos con `sqlite3.connect`) es
justamente lo que la etapa viene a corregir.

Sobre el motor: la URL se toma de la variable de entorno PUCARA_DB_URL. Por
defecto usa el SQLite actual, así lo nuevo convive con el sistema en producción
hasta que se ejecute la migración a PostgreSQL (fase 7, ver ADR-0002).
Ese default es lo que permite que las fases 1-6 se desarrollen y prueben sin
depender de que Postgres ya esté levantado.
"""
from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from datetime import datetime, timezone

from sqlalchemy import DateTime, TypeDecorator, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class UtcDateTime(TypeDecorator):
    """Fecha/hora SIEMPRE consciente de zona horaria, en UTC.

    Por qué existe: SQLite no guarda el offset. Con `DateTime(timezone=True)` a
    secas, se escribe una fecha con zona y se lee una SIN zona, y cualquier
    resta contra `datetime.now(timezone.utc)` explota con
    "can't subtract offset-naive and offset-aware datetimes".

    PostgreSQL con `timestamptz` sí lo conserva. Este tipo hace que ambos
    motores se comporten igual, que es condición para que la migración de la
    fase 7 no cambie el comportamiento del cálculo de duraciones (MTTR, MTBF,
    tiempo de caída).
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:                 # se asume UTC si viene sin zona
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:                 # caso SQLite
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

_RUTA_SQLITE_POR_DEFECTO = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "netadmin.db"
)


def url_base_datos() -> str:
    """URL de conexión. PostgreSQL en producción, SQLite mientras se migra."""
    return os.environ.get("PUCARA_DB_URL") or f"sqlite:///{_RUTA_SQLITE_POR_DEFECTO}"


class Base(DeclarativeBase):
    """Base declarativa de todos los modelos."""


def crear_engine(url: str | None = None, echo: bool = False) -> Engine:
    url = url or url_base_datos()
    if url.startswith("sqlite"):
        # check_same_thread=False: los pollers corren en hilos aparte.
        engine = create_engine(
            url, echo=echo, future=True, connect_args={"check_same_thread": False}
        )

        @event.listens_for(engine, "connect")
        def _pragmas(dbapi_con, _record):  # pragma: no cover - depende del motor
            # SQLite NO respeta las claves foráneas salvo que se pidan
            # explícitamente en cada conexión. Sin esto, las FK que declaramos
            # en los modelos serían decorativas y las pruebas darían un falso
            # verde respecto de lo que hará PostgreSQL, que sí las aplica.
            cur = dbapi_con.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

        return engine
    return create_engine(url, echo=echo, future=True, pool_pre_ping=True)


_engine: Engine | None = None
_Session: sessionmaker[Session] | None = None


def engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = crear_engine()
    return _engine


def fabrica_sesiones() -> sessionmaker[Session]:
    global _Session
    if _Session is None:
        _Session = sessionmaker(bind=engine(), expire_on_commit=False, future=True)
    return _Session


@contextmanager
def sesion() -> Iterator[Session]:
    """Sesión transaccional: confirma al salir bien, revierte ante cualquier error.

    Que el rollback esté acá y no en cada servicio es lo que evita que una
    operación a medias quede escrita.
    """
    s = fabrica_sesiones()()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def reiniciar_para_pruebas(url: str) -> Engine:
    """Reapunta el engine a otra base. Uso exclusivo de las pruebas."""
    global _engine, _Session
    _engine = crear_engine(url)
    _Session = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine
