#!/usr/bin/env python3
"""Copia los datos de SQLite a PostgreSQL (fase 8).

Qué hace y qué NO hace:

- **No crea el esquema.** Las tablas del dominio nuevo las crea Alembic
  (`alembic upgrade head`) y las heredadas su DDL correspondiente. Este script
  sólo mueve filas: separar esquema de datos es lo que permite repetirlo.
- **Es idempotente.** Se puede correr muchas veces: cada tabla se copia con
  `ON CONFLICT DO NOTHING` sobre su clave primaria. Un corte a la mitad se
  arregla volviéndolo a correr, no restaurando un backup.
- **No borra nada** salvo que se pida `--truncar` explícitamente.
- **Verifica al final**: compara el conteo de filas tabla por tabla y sale con
  código distinto de cero si algo no cuadra. Una migración que "parece que
  anduvo" no sirve.

Uso:
    python3 scripts/migrar_a_postgres.py --origen netadmin.db \\
        --destino postgresql+psycopg://usuario@host/pucara --dry-run
    python3 scripts/migrar_a_postgres.py --origen netadmin.db --destino "$PUCARA_DB_URL"
    python3 scripts/migrar_a_postgres.py ... --solo clientes,onu_senal
"""
from __future__ import annotations

import argparse
import pathlib
import sqlite3
import sys

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

LOTE = 1000

# Tablas que NO se copian: son caché reconstruible por los pollers. Copiarlas
# alarga la ventana de migración sin aportar nada.
EFIMERAS = {"sqlite_sequence", "alembic_version"}


def tablas_de_origen(con: sqlite3.Connection) -> list[str]:
    return [
        r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]


def orden_de_copia(destino: Engine, tablas: list[str]) -> list[str]:
    """Ordena por dependencias: una tabla hija no puede entrar antes que su padre.

    Con las FOREIGN KEY activas, copiar en orden alfabético falla. Es un orden
    topológico simple; si hay un ciclo, deja las restantes al final y que el
    motor decida (o que falle con un mensaje claro).
    """
    insp = inspect(destino)
    existentes = set(insp.get_table_names())
    deps = {
        t: {fk["referred_table"] for fk in insp.get_foreign_keys(t)} & existentes - {t}
        for t in tablas if t in existentes
    }
    salida, pendientes = [], dict(deps)
    while pendientes:
        libres = [t for t, d in pendientes.items() if not (d - set(salida))]
        if not libres:                      # ciclo: el resto va como venga
            salida.extend(sorted(pendientes))
            break
        salida.extend(sorted(libres))
        for t in libres:
            pendientes.pop(t)
    return salida


def _clave_primaria(destino: Engine, tabla: str) -> list[str]:
    return inspect(destino).get_pk_constraint(tabla).get("constrained_columns") or []


def copiar_tabla(origen: sqlite3.Connection, destino: Engine, tabla: str,
                 dry_run: bool) -> tuple[int, int]:
    """Devuelve (filas en origen, filas insertadas)."""
    cols_destino = {c["name"] for c in inspect(destino).get_columns(tabla)}
    cur = origen.execute(f'SELECT * FROM "{tabla}"')
    cols_origen = [d[0] for d in cur.description]
    # Sólo las columnas que existen en los dos lados: si el esquema nuevo
    # renombró o quitó algo, la copia no debe caerse por eso.
    comunes = [c for c in cols_origen if c in cols_destino]
    if not comunes:
        return 0, 0
    faltan = [c for c in cols_origen if c not in cols_destino]
    if faltan:
        print(f"      ⚠ columnas que no existen en destino y se omiten: {faltan}")

    pk = _clave_primaria(destino, tabla)
    conflicto = f' ON CONFLICT ({", ".join(chr(34)+c+chr(34) for c in pk)}) DO NOTHING' if pk else ""
    sql = text(
        f'INSERT INTO "{tabla}" ({", ".join(chr(34)+c+chr(34) for c in comunes)}) '
        f'VALUES ({", ".join(":" + c for c in comunes)}){conflicto}'
    )

    leidas = insertadas = 0
    with destino.begin() as cx:
        while True:
            filas = cur.fetchmany(LOTE)
            if not filas:
                break
            lote = [dict(zip(cols_origen, f)) for f in filas]
            lote = [{c: r[c] for c in comunes} for r in lote]
            leidas += len(lote)
            if not dry_run:
                res = cx.execute(sql, lote)
                insertadas += res.rowcount if res.rowcount and res.rowcount > 0 else len(lote)
    return leidas, insertadas


def resincronizar_secuencias(destino: Engine, tablas: list[str]) -> None:
    """Pone cada secuencia por encima del id máximo copiado.

    Sin esto el primer INSERT desde la aplicación choca con una clave que ya
    existe: la secuencia arrancaría en 1. Es el error clásico de estas
    migraciones y aparece recién cuando alguien da de alta un cliente.
    """
    with destino.begin() as cx:
        for t in tablas:
            pk = _clave_primaria(destino, t)
            if len(pk) != 1:
                continue
            col = pk[0]
            seq = cx.execute(
                text("SELECT pg_get_serial_sequence(:t, :c)"), {"t": t, "c": col}
            ).scalar()
            if not seq:
                continue
            cx.execute(text(
                f'SELECT setval(:s, COALESCE((SELECT MAX("{col}") FROM "{t}"), 0) + 1, false)'
            ), {"s": seq})


def verificar(origen: sqlite3.Connection, destino: Engine, tablas: list[str]) -> list[str]:
    problemas = []
    with destino.connect() as cx:
        for t in tablas:
            a = origen.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            b = cx.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar()
            if a != b:
                problemas.append(f"{t}: origen {a} · destino {b}")
    return problemas


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--origen", required=True, help="Ruta al archivo SQLite")
    ap.add_argument("--destino", required=True, help="URL SQLAlchemy de PostgreSQL")
    ap.add_argument("--solo", help="Lista de tablas separadas por coma")
    ap.add_argument("--dry-run", action="store_true", help="No escribe: sólo informa")
    ap.add_argument("--truncar", action="store_true",
                    help="Vacía cada tabla del destino antes de copiar (DESTRUCTIVO)")
    a = ap.parse_args()

    if not pathlib.Path(a.origen).exists():
        print(f"✗ No existe {a.origen}")
        return 2
    if not a.destino.startswith("postgresql"):
        print("✗ El destino tiene que ser una URL de PostgreSQL")
        return 2

    origen = sqlite3.connect(a.origen)
    destino = create_engine(a.destino, future=True)

    disponibles = set(inspect(destino).get_table_names())
    candidatas = [t for t in tablas_de_origen(origen) if t not in EFIMERAS]
    if a.solo:
        pedidas = {x.strip() for x in a.solo.split(",") if x.strip()}
        candidatas = [t for t in candidatas if t in pedidas]

    faltantes = [t for t in candidatas if t not in disponibles]
    if faltantes:
        print("⚠ Estas tablas no existen todavía en PostgreSQL y se omiten.")
        print("  Creá el esquema primero (alembic upgrade head + DDL heredado):")
        for t in faltantes:
            print(f"    · {t}")
    tablas = orden_de_copia(destino, [t for t in candidatas if t in disponibles])
    if not tablas:
        print("✗ No hay ninguna tabla para copiar.")
        return 2

    if a.truncar and not a.dry_run:
        print("⚠ Vaciando el destino…")
        with destino.begin() as cx:
            cx.execute(text("TRUNCATE " + ", ".join(f'"{t}"' for t in tablas) + " CASCADE"))

    print(f"{'[SIMULACIÓN] ' if a.dry_run else ''}Copiando {len(tablas)} tablas…")
    total = 0
    for t in tablas:
        leidas, insertadas = copiar_tabla(origen, destino, t, a.dry_run)
        total += insertadas
        print(f"  · {t:<28} {leidas:>8,} filas leídas · {insertadas:>8,} insertadas")

    if a.dry_run:
        print("\nSimulación terminada: no se escribió nada.")
        origen.close()
        return 0

    print("\nResincronizando secuencias…")
    resincronizar_secuencias(destino, tablas)

    print("Verificando conteos…")
    problemas = verificar(origen, destino, tablas)
    origen.close()

    if problemas:
        print("\n✗ La verificación encontró diferencias:")
        for p in problemas:
            print(f"    {p}")
        print("\n  Volvé a correr el script: es idempotente y completa lo que falte.")
        return 1

    print(f"\n✓ {total:,} filas migradas. Los conteos coinciden en las {len(tablas)} tablas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
