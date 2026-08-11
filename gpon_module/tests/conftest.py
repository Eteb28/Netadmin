"""Piezas compartidas por los tests.

Todo corre en memoria y con reloj controlado: ningún test toca la red, el
disco ni el reloj del sistema, así que fallan siempre que deben fallar y nunca
por casualidad.
"""

from __future__ import annotations

import pytest

from gpon_module.config import Configuracion
from gpon_module.core.cifrado import CifradorNulo
from gpon_module.core.enums import Fabricante
from gpon_module.core.models import OLT, CredencialesOLT
from gpon_module.core.reloj import RelojFijo
from gpon_module.database.conexion import ConexionSQLite
from gpon_module.drivers.mock import DriverSimulado, generar_parque
from gpon_module.services import crear_contenedor

CREDENCIALES = CredencialesOLT(
    usuario="admin",
    password="Xpon@Olt9417#",
    comunidad_snmp_lectura="publica",
)


@pytest.fixture
def reloj() -> RelojFijo:
    return RelojFijo()


@pytest.fixture
def conexion() -> ConexionSQLite:
    conexion = ConexionSQLite(":memory:")
    conexion.inicializar_esquema()
    yield conexion
    conexion.cerrar()


@pytest.fixture
def parque():
    """Parque simulado chico: los tests no necesitan 473 ONU para probar lógica."""
    return generar_parque(cantidad_onus=24, cantidad_pon=4, cantidad_no_autorizadas=2)


@pytest.fixture
def configuracion() -> Configuracion:
    return Configuracion(
        url_base_datos="sqlite:///:memory:",
        permitir_cifrado_nulo=True,
        dry_run_por_defecto=True,
    )


@pytest.fixture
def sistema(configuracion, reloj, parque):
    """Módulo completo armado en memoria, con la OLT simulada compartida."""
    contenedor = crear_contenedor(
        configuracion,
        reloj=reloj,
        cifrador=CifradorNulo(),
        extras_driver={"parque": parque, "reloj": reloj},
    )
    yield contenedor
    contenedor.cerrar()


@pytest.fixture
def olt(sistema) -> OLT:
    return sistema.servicio_olt.registrar(
        nombre="OLT de prueba",
        host="10.255.0.1",
        fabricante=Fabricante.SIMULADO,
        credenciales=CREDENCIALES,
    )


@pytest.fixture
def driver(parque, reloj) -> DriverSimulado:
    """Driver suelto, sin base de datos, en modo simulación."""
    return DriverSimulado(
        olt=OLT(id=1, nombre="suelta", host="10.255.0.9", fabricante=Fabricante.SIMULADO),
        credenciales=CREDENCIALES,
        parque=parque,
        reloj=reloj,
    )


@pytest.fixture
def driver_real(parque, reloj) -> DriverSimulado:
    """Driver que sí ejecuta: para probar que las escrituras cambian el estado."""
    return DriverSimulado(
        olt=OLT(id=1, nombre="suelta", host="10.255.0.9", fabricante=Fabricante.SIMULADO),
        credenciales=CREDENCIALES,
        parque=parque,
        reloj=reloj,
        dry_run=False,
    )
