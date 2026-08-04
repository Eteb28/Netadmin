"""Contenedor de dependencias.

Un único lugar donde se arma el sistema: configuración → conexión → cifrador →
repositorios → fábrica de drivers → servicios. Todo lo demás recibe lo que
necesita ya construido, y por eso todo lo demás se puede probar sustituyendo
piezas.

Sin esto, cada servicio terminaría creando su propia conexión y buscando la
clave de cifrado por su cuenta, que es exactamente el acoplamiento que el
diseño evita.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from ..config import Configuracion
from ..core.cifrado import CifradorFernet, CifradorNulo
from ..core.interfaces import Cifrador, Reloj
from ..core.reloj import RelojSistema
from ..database.conexion import Conexion, crear_conexion
from ..database.repositories import (
    RepositorioAlarmaSQL,
    RepositorioEventoSQL,
    RepositorioMetricaSQL,
    RepositorioOLTSQL,
    RepositorioONUSQL,
    RepositorioOperacionSQL,
    RepositorioPerfilesSQL,
    RepositorioPuertoPONSQL,
    RepositorioSincronizacionSQL,
)
from .descubrimiento import ServicioDescubrimiento
from .fabrica import FabricaDrivers
from .olt import ServicioOLT
from .onu import ServicioONU

log = logging.getLogger(__name__)


@dataclass
class Contenedor:
    """Sistema armado y listo para usar."""

    configuracion: Configuracion
    conexion: Conexion
    cifrador: Cifrador
    reloj: Reloj

    repositorio_olt: RepositorioOLTSQL
    repositorio_onu: RepositorioONUSQL
    repositorio_puerto: RepositorioPuertoPONSQL
    repositorio_perfiles: RepositorioPerfilesSQL
    repositorio_metrica: RepositorioMetricaSQL
    repositorio_evento: RepositorioEventoSQL
    repositorio_alarma: RepositorioAlarmaSQL
    repositorio_operacion: RepositorioOperacionSQL
    repositorio_sincronizacion: RepositorioSincronizacionSQL

    fabrica_drivers: FabricaDrivers
    servicio_olt: ServicioOLT
    servicio_onu: ServicioONU
    servicio_descubrimiento: ServicioDescubrimiento

    def cerrar(self) -> None:
        self.conexion.cerrar()

    def __enter__(self) -> Contenedor:
        return self

    def __exit__(self, *_excepcion: object) -> None:
        self.cerrar()


def crear_contenedor(
    configuracion: Configuracion | None = None,
    *,
    reloj: Reloj | None = None,
    cifrador: Cifrador | None = None,
    conexion: Conexion | None = None,
    extras_driver: dict[str, Any] | None = None,
    inicializar_esquema: bool = True,
) -> Contenedor:
    """Arma el módulo completo.

    Todos los parámetros son sustituibles: los tests inyectan una base en
    memoria, un reloj fijo y un cifrador de desarrollo sin tocar el código de
    producción.
    """
    configuracion = configuracion or Configuracion.desde_entorno()
    configuracion.validar()

    reloj = reloj or RelojSistema()
    cifrador = cifrador or _elegir_cifrador(configuracion)
    conexion = conexion or crear_conexion(configuracion.url_base_datos)
    if inicializar_esquema:
        conexion.inicializar_esquema()

    repositorio_olt = RepositorioOLTSQL(conexion, cifrador)
    repositorio_onu = RepositorioONUSQL(conexion)
    repositorio_puerto = RepositorioPuertoPONSQL(conexion)
    repositorio_perfiles = RepositorioPerfilesSQL(conexion)
    repositorio_metrica = RepositorioMetricaSQL(conexion)
    repositorio_evento = RepositorioEventoSQL(conexion)
    repositorio_alarma = RepositorioAlarmaSQL(conexion)
    repositorio_operacion = RepositorioOperacionSQL(conexion)
    repositorio_sincronizacion = RepositorioSincronizacionSQL(conexion)

    fabrica_drivers = FabricaDrivers(
        repositorio_olt,
        dry_run_por_defecto=configuracion.dry_run_por_defecto,
        extras=extras_driver,
    )

    return Contenedor(
        configuracion=configuracion,
        conexion=conexion,
        cifrador=cifrador,
        reloj=reloj,
        repositorio_olt=repositorio_olt,
        repositorio_onu=repositorio_onu,
        repositorio_puerto=repositorio_puerto,
        repositorio_perfiles=repositorio_perfiles,
        repositorio_metrica=repositorio_metrica,
        repositorio_evento=repositorio_evento,
        repositorio_alarma=repositorio_alarma,
        repositorio_operacion=repositorio_operacion,
        repositorio_sincronizacion=repositorio_sincronizacion,
        fabrica_drivers=fabrica_drivers,
        servicio_olt=ServicioOLT(repositorio_olt, fabrica_drivers, reloj=reloj),
        servicio_onu=ServicioONU(
            repositorio_onu=repositorio_onu,
            repositorio_operacion=repositorio_operacion,
            repositorio_evento=repositorio_evento,
            fabrica=fabrica_drivers,
            reloj=reloj,
        ),
        servicio_descubrimiento=ServicioDescubrimiento(
            repositorio_olt=repositorio_olt,
            repositorio_onu=repositorio_onu,
            repositorio_puerto=repositorio_puerto,
            repositorio_evento=repositorio_evento,
            repositorio_sincronizacion=repositorio_sincronizacion,
            repositorio_perfiles=repositorio_perfiles,
            fabrica=fabrica_drivers,
            reloj=reloj,
        ),
    )


def _elegir_cifrador(configuracion: Configuracion) -> Cifrador:
    """Cifrado real si hay clave; el de desarrollo sólo si se pidió explícitamente."""
    if configuracion.clave_cifrado:
        return CifradorFernet(configuracion.clave_cifrado)
    if configuracion.permitir_cifrado_nulo:
        log.warning(
            "Cifrado desactivado por configuración: las credenciales de OLT quedan "
            "legibles en la base. Aceptable en desarrollo, nunca en producción."
        )
        return CifradorNulo()
    # No debería llegarse acá: Configuracion.validar() ya lo habría cortado.
    raise RuntimeError("Configuración de cifrado inconsistente")
