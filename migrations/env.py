"""Entorno de Alembic.

La URL NO se toma de alembic.ini sino de `pucara.db.url_base_datos()`, que lee
la variable PUCARA_DB_URL. Así las migraciones apuntan siempre a la misma base
que la aplicación, y el cambio a PostgreSQL (fase 7) es una variable de entorno
y no editar un archivo de configuración.
"""
from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from pucara.db import Base, url_base_datos

# Importar los modelos los registra en Base.metadata (autogenerate los necesita)
from pucara.models import adjuntos, incidentes, reclamos  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", url_base_datos())

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _incluir_objeto(objeto, nombre, tipo, reflejado, comparar_con):
    """Ignora las tablas heredadas que todavía no están modeladas.

    Sin esto, `alembic revision --autogenerate` propondría BORRAR las ~40 tablas
    del sistema actual (clientes, onu_senal, torres…) por no encontrarlas en los
    modelos. Se van incorporando a medida que la fase 7 las migre.
    """
    if tipo == "table" and nombre not in target_metadata.tables:
        return False
    return True


def migraciones_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        include_object=_incluir_objeto,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def migraciones_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=_incluir_objeto,
            compare_type=True,
            # Necesario en SQLite: no soporta ALTER de columnas y Alembic
            # necesita recrear la tabla. En PostgreSQL es inocuo.
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    migraciones_offline()
else:
    migraciones_online()
