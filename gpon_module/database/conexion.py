"""Acceso al motor de base de datos.

Los repositorios no conocen ``sqlite3`` ni ``psycopg``: hablan con esta capa.
El SQL se escribe siempre con el marcador ``?``; cada conexión lo traduce al
que use su motor. Así el mismo repositorio sirve para SQLite y para PostgreSQL.

SQLite alcanza para desarrollo, tests e instalaciones chicas. PostgreSQL es lo
recomendado en producción por el volumen del histórico (473 ONU por OLT cada
5 minutos). El esquema de ambos vive en ``schema_sqlite.sql`` y
``schema_postgres.sql``, con los mismos nombres de tabla y columna.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from ..core.errors import ErrorConfiguracion, ErrorRepositorio

RUTA_ESQUEMA_SQLITE = Path(__file__).parent / "schema_sqlite.sql"
RUTA_ESQUEMA_POSTGRES = Path(__file__).parent / "schema_postgres.sql"

VERSION_ESQUEMA = 2


# --- Conversión de tipos --------------------------------------------------


def a_texto(momento: datetime | None) -> str | None:
    """Fecha → texto ISO 8601 en UTC. Toda fecha se guarda en UTC, sin excepción."""
    if momento is None:
        return None
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=UTC)
    return momento.astimezone(UTC).isoformat()


def a_fecha(texto: str | datetime | None) -> datetime | None:
    """Texto ISO 8601 → fecha con zona horaria."""
    if texto is None or texto == "":
        return None
    if isinstance(texto, datetime):
        return texto if texto.tzinfo else texto.replace(tzinfo=UTC)
    try:
        momento = datetime.fromisoformat(texto)
    except ValueError as exc:
        raise ErrorRepositorio(f"Fecha ilegible en base de datos: {texto!r}") from exc
    return momento if momento.tzinfo else momento.replace(tzinfo=UTC)


# --- Contrato -------------------------------------------------------------


class Conexion(Protocol):
    """Lo que un repositorio necesita de la base, y nada más."""

    def ejecutar(self, sql: str, parametros: Sequence[Any] = ()) -> int:
        """Ejecuta una sentencia de escritura y devuelve el id generado."""

    def ejecutar_muchos(self, sql: str, parametros: Sequence[Sequence[Any]]) -> None: ...

    def consultar_uno(self, sql: str, parametros: Sequence[Any] = ()) -> dict[str, Any] | None: ...

    def consultar_todos(self, sql: str, parametros: Sequence[Any] = ()) -> list[dict[str, Any]]: ...

    def transaccion(self) -> Any: ...

    def inicializar_esquema(self) -> None: ...

    def cerrar(self) -> None: ...


# --- SQLite ---------------------------------------------------------------


class ConexionSQLite:
    """Conexión SQLite con escrituras serializadas.

    SQLite admite un solo escritor. El bloqueo evita ``database is locked``
    cuando la sincronización de varias OLT escribe en paralelo.
    """

    marcador = "?"

    def __init__(self, ruta: str | Path = ":memory:") -> None:
        self.ruta = str(ruta)
        if self.ruta != ":memory:":
            Path(self.ruta).parent.mkdir(parents=True, exist_ok=True)
        self._conexion = sqlite3.connect(self.ruta, check_same_thread=False)
        self._conexion.row_factory = sqlite3.Row
        self._conexion.execute("PRAGMA foreign_keys = ON")
        # WAL mejora la concurrencia lectura/escritura; no aplica en memoria.
        if self.ruta != ":memory:":
            self._conexion.execute("PRAGMA journal_mode = WAL")
        self._bloqueo = threading.RLock()

    # --- operaciones ---

    def ejecutar(self, sql: str, parametros: Sequence[Any] = ()) -> int:
        with self._bloqueo:
            try:
                cursor = self._conexion.execute(sql, tuple(parametros))
                self._conexion.commit()
                return int(cursor.lastrowid or 0)
            except sqlite3.Error as exc:
                self._conexion.rollback()
                raise ErrorRepositorio(f"{exc} — SQL: {sql.strip().splitlines()[0]}") from exc

    def ejecutar_muchos(self, sql: str, parametros: Sequence[Sequence[Any]]) -> None:
        if not parametros:
            return
        with self._bloqueo:
            try:
                self._conexion.executemany(sql, [tuple(p) for p in parametros])
                self._conexion.commit()
            except sqlite3.Error as exc:
                self._conexion.rollback()
                raise ErrorRepositorio(f"{exc} — SQL: {sql.strip().splitlines()[0]}") from exc

    def consultar_uno(self, sql: str, parametros: Sequence[Any] = ()) -> dict[str, Any] | None:
        with self._bloqueo:
            try:
                fila = self._conexion.execute(sql, tuple(parametros)).fetchone()
            except sqlite3.Error as exc:
                raise ErrorRepositorio(f"{exc} — SQL: {sql.strip().splitlines()[0]}") from exc
        return dict(fila) if fila is not None else None

    def consultar_todos(self, sql: str, parametros: Sequence[Any] = ()) -> list[dict[str, Any]]:
        with self._bloqueo:
            try:
                filas = self._conexion.execute(sql, tuple(parametros)).fetchall()
            except sqlite3.Error as exc:
                raise ErrorRepositorio(f"{exc} — SQL: {sql.strip().splitlines()[0]}") from exc
        return [dict(fila) for fila in filas]

    @contextmanager
    def transaccion(self) -> Iterator[ConexionSQLite]:
        """Agrupa varias escrituras: o entran todas, o no entra ninguna.

        Lo usa la sincronización, donde persistir el inventario a medias sería
        peor que no persistir nada.
        """
        with self._bloqueo:
            try:
                yield self
                self._conexion.commit()
            except Exception:
                self._conexion.rollback()
                raise

    # --- esquema ---

    def inicializar_esquema(self) -> None:
        """Crea las tablas si no existen. Es idempotente."""
        sql = RUTA_ESQUEMA_SQLITE.read_text(encoding="utf-8")
        with self._bloqueo:
            self._conexion.executescript(sql)
            fila = self._conexion.execute("SELECT COUNT(*) AS c FROM esquema_version").fetchone()
            if fila["c"] == 0:
                self._conexion.execute(
                    "INSERT INTO esquema_version (version, aplicada_en) VALUES (?, ?)",
                    (VERSION_ESQUEMA, a_texto(datetime.now(UTC))),
                )
            self._conexion.commit()

    def version_esquema(self) -> int:
        fila = self.consultar_uno("SELECT MAX(version) AS v FROM esquema_version")
        return int(fila["v"]) if fila and fila["v"] is not None else 0

    def cerrar(self) -> None:
        with self._bloqueo:
            self._conexion.close()

    def __enter__(self) -> ConexionSQLite:
        return self

    def __exit__(self, *_excepcion: object) -> None:
        self.cerrar()


# --- Fábrica --------------------------------------------------------------


def crear_conexion(url: str) -> Conexion:
    """Construye la conexión que corresponda a la URL configurada.

    Formatos admitidos::

        sqlite:///ruta/al/archivo.db
        sqlite:///:memory:
        postgresql://usuario:clave@host:5432/base     (Fase 4)
    """
    if url.startswith("sqlite:"):
        ruta = url.split("///", 1)[-1] if "///" in url else ":memory:"
        return ConexionSQLite(ruta or ":memory:")
    if url.startswith(("postgres:", "postgresql:")):
        raise ErrorConfiguracion(
            "La conexión PostgreSQL llega en la Fase 4, junto con los históricos. "
            "El esquema ya está escrito en database/schema_postgres.sql y los "
            "repositorios no necesitan cambios: sólo falta la clase de conexión. "
            "Por ahora usá sqlite:///gpon.db."
        )
    raise ErrorConfiguracion(f"URL de base de datos no reconocida: {url!r}")
