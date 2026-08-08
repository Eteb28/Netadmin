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
from datetime import UTC, datetime
from typing import Any

from ..config import Configuracion
from ..core.cifrado import CifradorFernet, CifradorNulo
from ..core.errors import ErrorCifrado, ErrorConfiguracion
from ..core.interfaces import Cifrador, Reloj
from ..core.reloj import RelojSistema
from ..database.conexion import Conexion, a_texto, crear_conexion
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
from .captura import ServicioCaptura
from .descubrimiento import ServicioDescubrimiento
from .exploracion import ServicioExploracion
from .fabrica import FabricaDrivers
from .inventario_cli import ServicioInventarioCLI
from .olt import ServicioOLT
from .onu import ServicioONU
from .pendientes import ServicioPendientes

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
    servicio_captura: ServicioCaptura
    servicio_inventario_cli: ServicioInventarioCLI
    servicio_exploracion: ServicioExploracion
    servicio_pendientes: ServicioPendientes

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
        _verificar_clave_de_cifrado(conexion, cifrador)

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
        servicio_captura=ServicioCaptura(repositorio_olt, reloj=reloj),
        servicio_exploracion=ServicioExploracion(repositorio_olt, reloj=reloj),
        servicio_pendientes=ServicioPendientes(repositorio_olt, reloj=reloj),
        servicio_inventario_cli=ServicioInventarioCLI(
            repositorio_olt=repositorio_olt,
            repositorio_onu=repositorio_onu,
            repositorio_perfiles=repositorio_perfiles,
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


#: Texto que se guarda cifrado para poder detectar un cambio de clave.
_TEXTO_VERIFICADOR = "gpon-verificacion"
_CLAVE_VERIFICADOR = "verificador_cifrado"


def _verificar_clave_de_cifrado(conexion: Conexion, cifrador: Cifrador) -> None:
    """Comprueba que la clave actual sea la que cifró esta base.

    Sin esto, cambiar ``GPON_CLAVE_CIFRADO`` no da error hasta que alguien
    intenta conectarse a una OLT, y el mensaje que aparece —"la clave no
    corresponde o el dato está corrupto"— no dice qué hacer. Acá el módulo se
    entera al arrancar y explica las dos salidas posibles.
    """
    fila = conexion.consultar_uno(
        "SELECT valor FROM configuracion_modulo WHERE clave = ?", (_CLAVE_VERIFICADOR,)
    )

    if fila is None:
        # Base nueva, o creada antes de que existiera el verificador: se graba
        # con la clave actual y queda establecida desde ahora.
        conexion.ejecutar(
            "INSERT INTO configuracion_modulo (clave, valor, creada_en) VALUES (?, ?, ?)",
            (
                _CLAVE_VERIFICADOR,
                cifrador.cifrar(_TEXTO_VERIFICADOR),
                a_texto(datetime.now(UTC)),
            ),
        )
        return

    try:
        descifrado = cifrador.descifrar(fila["valor"])
    except ErrorCifrado as exc:
        raise ErrorConfiguracion(
            "La clave de cifrado no es la que se usó para crear esta base de datos.\n"
            "\n"
            "Las credenciales guardadas están cifradas con otra clave, así que no se\n"
            "pueden leer. Hay dos salidas:\n"
            "\n"
            "  1. Recuperar la clave original y exportarla en GPON_CLAVE_CIFRADO.\n"
            "  2. Si la clave se perdió, empezar de cero: borrar el archivo de base\n"
            "     de datos y volver a dar de alta las OLT.\n"
            "\n"
            "Generar una clave nueva con 'gpon generar-clave' NO recupera las\n"
            "credenciales: sólo agrava el problema si se pisa la que todavía sirve."
        ) from exc

    if descifrado != _TEXTO_VERIFICADOR:  # pragma: no cover - defensa extra
        raise ErrorConfiguracion("El verificador de cifrado de la base está corrupto.")


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
