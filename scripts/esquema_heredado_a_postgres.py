#!/usr/bin/env python3
"""Crea en PostgreSQL las tablas heredadas, derivándolas del SQLite real.

Fase 8, paso 1. El plan decía "alembic upgrade head + el DDL de las tablas
heredadas": Alembic cubre las 7 tablas del dominio nuevo, y las otras ~50 las
crea `init_db()` con DDL de SQLite que PostgreSQL no acepta. Este script cubre
ese hueco sin escribir 50 CREATE TABLE a mano —que se desincronizarían al día
siguiente— leyendo el esquema que existe de verdad.

Qué traduce, y por qué cada cosa:

- **Tipos sin equivalente.** SQLite acepta cualquier nombre de tipo; lo que no
  reconoce queda como `NullType` y `create_all` falla. Se mapea a `TEXT`, que
  es lo que SQLite estaba guardando igual.
- **`DEFAULT (datetime('now','localtime'))`.** No existe en PostgreSQL. Se
  reemplaza por `CURRENT_TIMESTAMP` / `CURRENT_DATE`; cualquier otro default
  con paréntesis se descarta y se avisa, porque un default que no se entiende
  es peor que no tenerlo.
- **`AUTOINCREMENT`.** Una PK entera de una sola columna sale como `SERIAL`,
  que es lo que la aplicación espera al insertar sin id.
- **Tablas que ya administra Alembic.** Se omiten: si este script las creara,
  `alembic upgrade head` fallaría después, o peor, se pisarían dos definiciones.

Uso:
    python3 scripts/esquema_heredado_a_postgres.py --origen netadmin.db --sql
    python3 scripts/esquema_heredado_a_postgres.py --origen netadmin.db \\
        --destino "$PUCARA_DB_URL"

Con `--sql` sólo imprime el DDL para revisarlo. **Revisalo antes de aplicarlo**:
lo que sale de acá es una traducción mecánica, no una decisión de diseño. Los
tipos definitivos (booleanos de verdad, fechas como `date`) son trabajo aparte
y posterior, con los datos ya limpios.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

from sqlalchemy import (
    Column, Integer, MetaData, Table, Text, create_engine, inspect, text,
)
from sqlalchemy.schema import CreateTable
from sqlalchemy.types import NullType

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from pucara.db import Base  # noqa: E402
from pucara.models import adjuntos, incidentes, reclamos  # noqa: F401,E402

#: Defaults de SQLite que sí tienen equivalente directo.
DEFAULTS_TRADUCIBLES = {
    "datetime('now','localtime')": "CURRENT_TIMESTAMP",
    "datetime('now', 'localtime')": "CURRENT_TIMESTAMP",
    "datetime('now')": "CURRENT_TIMESTAMP",
    "date('now','localtime')": "CURRENT_DATE",
    "date('now', 'localtime')": "CURRENT_DATE",
    "date('now')": "CURRENT_DATE",
    "current_timestamp": "CURRENT_TIMESTAMP",
}


def _traducir_default(valor: str | None, aviso: list[str], donde: str) -> str | None:
    """Devuelve el default para PostgreSQL, o None si hay que descartarlo."""
    if valor is None:
        return None
    limpio = valor.strip()
    while limpio.startswith("(") and limpio.endswith(")"):
        limpio = limpio[1:-1].strip()
    clave = re.sub(r"\s+", "", limpio).lower()
    for original, equivalente in DEFAULTS_TRADUCIBLES.items():
        if re.sub(r"\s+", "", original).lower() == clave:
            return equivalente
    # Literales (números, textos entre comillas) pasan tal cual.
    if re.fullmatch(r"-?\d+(\.\d+)?", limpio) or re.fullmatch(r"'[^']*'", limpio):
        return limpio
    aviso.append(f"{donde}: se descarta DEFAULT {valor!r} (no traducible)")
    return None


def esquema_portado(origen: str) -> tuple[MetaData, list[str]]:
    """Refleja el SQLite y devuelve una metadata apta para PostgreSQL."""
    eng = create_engine(f"sqlite:///{origen}", future=True)
    reflejada = MetaData()
    reflejada.reflect(bind=eng)

    administradas_por_alembic = set(Base.metadata.tables) | {"alembic_version"}
    avisos: list[str] = []
    salida = MetaData()

    for nombre, tabla in sorted(reflejada.tables.items()):
        if nombre in administradas_por_alembic or nombre.startswith("sqlite_"):
            continue
        columnas = []
        for col in tabla.columns:
            tipo = col.type
            if isinstance(tipo, NullType):
                avisos.append(f"{nombre}.{col.name}: tipo desconocido → TEXT")
                tipo = Text()
            default = _traducir_default(
                col.server_default.arg.text
                if col.server_default is not None
                and hasattr(col.server_default.arg, "text")
                else (str(col.server_default.arg) if col.server_default is not None else None),
                avisos, f"{nombre}.{col.name}",
            )
            columnas.append(
                Column(
                    col.name, tipo,
                    primary_key=col.primary_key,
                    nullable=col.nullable,
                    # text() y no la cadena pelada: un str se emite ENTRECOMILLADO,
                    # y `DEFAULT 'CURRENT_TIMESTAMP'` guarda el literal en vez de
                    # la hora. Con un literal ya citado ('activa') salía además
                    # triplemente entrecomillado.
                    server_default=text(default) if default is not None else None,
                    # PK entera de una sola columna → SERIAL, que es lo que la
                    # aplicación necesita para insertar sin id explícito.
                    autoincrement=(
                        col.primary_key
                        and isinstance(tipo, Integer)
                        and len(tabla.primary_key.columns) == 1
                    ),
                )
            )
        # Las FOREIGN KEY no se copian: el orden de creación las volvería
        # obligatorias y la base heredada tiene filas huérfanas (clientes
        # borrados con pagos asociados). Se agregan después de migrar los
        # datos y de limpiarlos, no antes.
        Table(nombre, salida, *columnas)

    eng.dispose()
    return salida, avisos


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--origen", required=True, help="Ruta al archivo SQLite")
    ap.add_argument("--destino", help="URL de PostgreSQL donde crear las tablas")
    ap.add_argument("--sql", action="store_true", help="Sólo imprimir el DDL")
    a = ap.parse_args()

    if not pathlib.Path(a.origen).exists():
        print(f"✗ No existe {a.origen}")
        return 2
    if not a.sql and not a.destino:
        print("✗ Indicá --destino para crear, o --sql para sólo ver el DDL")
        return 2

    metadata, avisos = esquema_portado(a.origen)
    print(f"-- {len(metadata.tables)} tablas heredadas (las de Alembic quedan afuera)")
    for aviso in avisos:
        print(f"-- ⚠ {aviso}")

    if a.sql:
        from sqlalchemy.dialects import postgresql
        for tabla in metadata.sorted_tables:
            print(str(CreateTable(tabla).compile(dialect=postgresql.dialect())).strip() + ";")
        return 0

    if not a.destino.startswith("postgresql"):
        print("✗ El destino tiene que ser una URL de PostgreSQL")
        return 2

    eng = create_engine(a.destino, future=True)
    ya_estan = set(inspect(eng).get_table_names())
    nuevas = [t for n, t in metadata.tables.items() if n not in ya_estan]
    if not nuevas:
        print("✓ Ya estaban todas: no hay nada que crear.")
        return 0
    metadata.create_all(eng, tables=nuevas)
    print(f"✓ Creadas {len(nuevas)} tablas: {', '.join(sorted(t.name for t in nuevas))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
