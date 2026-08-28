"""Configuración común de las pruebas.

Cada prueba corre sobre una base creada desde los modelos: no toca netadmin.db
ni depende de datos previos. Es lo que permite ejecutarlas en cualquier máquina
y en CI sin preparar nada.

El motor lo elige `tests/motores.py`: SQLite en memoria por defecto, PostgreSQL
si se define `PUCARA_TEST_PG_URL`. La misma suite, los dos motores.
"""
from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from tests.motores import crear_esquema, motor


@pytest.fixture()
def sesion() -> Session:
    engine = motor()
    crear_esquema(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False, future=True)()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


@pytest.fixture()
def catalogos(sesion):
    """Catálogos mínimos precargados."""
    from pucara.repositories.reclamos import CausaRepository, ResolucionRepository

    causas = CausaRepository(sesion)
    resol = ResolucionRepository(sesion)
    c1 = causas.crear("Sin servicio")
    c2 = causas.crear("Lentitud")
    r1 = resol.crear("Reinicio ONU")
    sesion.commit()
    return {"causas": causas, "resoluciones": resol, "c1": c1, "c2": c2, "r1": r1}


@pytest.fixture()
def servicio(sesion, catalogos):
    from pucara.repositories.reclamos import ReclamoRepository
    from pucara.services.reclamos import ServicioReclamos

    return ServicioReclamos(
        ReclamoRepository(sesion), catalogos["causas"], catalogos["resoluciones"]
    )
