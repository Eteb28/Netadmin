"""Registro de drivers: fabricante → fábrica de driver.

Es el único punto donde el núcleo "conoce" que existen fabricantes, y sólo por
su nombre. Ningún servicio importa un driver concreto: pide uno al registro.

Los drivers se registran declarativamente::

    @registrar_driver(Fabricante.VSOL, modelos=("V1600G1", "V1600G1-B"))
    class DriverVSOL: ...
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from .enums import Capacidad, Fabricante
from .errors import DriverNoRegistrado
from .interfaces import OLTDriver
from .models import OLT, CredencialesOLT, DescripcionDriver

T = TypeVar("T")

_DRIVERS: dict[Fabricante, type] = {}
_DESCRIPCIONES: dict[Fabricante, DescripcionDriver] = {}


def registrar_driver(
    fabricante: Fabricante,
    *,
    nombre: str = "",
    modelos: tuple[str, ...] = (),
    protocolos: tuple[str, ...] = (),
    version: str = "1.0",
) -> Callable[[type[T]], type[T]]:
    """Decorador que inscribe una clase de driver para un fabricante."""

    def decorador(clase: type[T]) -> type[T]:
        if fabricante in _DRIVERS and _DRIVERS[fabricante] is not clase:
            raise ValueError(
                f"Ya hay un driver registrado para {fabricante}: "
                f"{_DRIVERS[fabricante].__name__}"
            )
        capacidades = getattr(clase, "CAPACIDADES", frozenset())
        _DRIVERS[fabricante] = clase
        _DESCRIPCIONES[fabricante] = DescripcionDriver(
            fabricante=fabricante,
            nombre=nombre or clase.__name__,
            modelos_soportados=modelos,
            capacidades=frozenset(capacidades),
            protocolos=protocolos,
            version=version,
        )
        return clase

    return decorador


def obtener_clase_driver(fabricante: Fabricante) -> type:
    """Clase de driver registrada para un fabricante."""
    try:
        return _DRIVERS[fabricante]
    except KeyError:
        raise DriverNoRegistrado(
            f"No hay driver para el fabricante '{fabricante}'. "
            f"Registrados: {', '.join(sorted(f.value for f in _DRIVERS)) or 'ninguno'}"
        ) from None


def crear_driver(
    *,
    olt: OLT,
    credenciales: CredencialesOLT,
    dry_run: bool = True,
    **extras: object,
) -> OLTDriver:
    """Instancia el driver que corresponde a la OLT.

    ``dry_run`` es ``True`` por defecto a propósito: ejecutar de verdad contra
    una OLT en producción debe pedirse explícitamente (mitiga R1).
    """
    clase = obtener_clase_driver(olt.fabricante)
    return clase(olt=olt, credenciales=credenciales, dry_run=dry_run, **extras)


def describir(fabricante: Fabricante) -> DescripcionDriver:
    """Metadatos de un driver sin necesidad de instanciarlo ni conectarse."""
    try:
        return _DESCRIPCIONES[fabricante]
    except KeyError:
        raise DriverNoRegistrado(f"No hay driver para el fabricante '{fabricante}'") from None


def fabricantes_registrados() -> tuple[Fabricante, ...]:
    return tuple(sorted(_DRIVERS, key=lambda f: f.value))


def capacidades_de(fabricante: Fabricante) -> frozenset[Capacidad]:
    """Capacidades declaradas, consultables antes de conectar.

    Sirve para que la interfaz web decida qué mostrar sin tocar el equipo.
    """
    return describir(fabricante).capacidades


def limpiar_registro() -> None:
    """Vacía el registro. Uso exclusivo de tests."""
    _DRIVERS.clear()
    _DESCRIPCIONES.clear()
