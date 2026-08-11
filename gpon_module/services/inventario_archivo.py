"""Alta de OLT desde un archivo, para no recargarlas a mano en cada prueba.

Un archivo TOML describe los equipos y este servicio los aplica: crea los que
faltan y actualiza los que ya están, identificándolos por su dirección. Es
idempotente a propósito —correrlo dos veces no duplica nada— porque durante el
desarrollo se corre muchas veces.

Las contraseñas se pueden escribir en el archivo o dejarlas en una variable de
entorno y referenciarlas con ``password_entorno``. Lo primero es cómodo, lo
segundo es lo que corresponde en un servidor compartido; el módulo admite las
dos y avisa si el archivo quedó legible para todo el mundo.
"""

from __future__ import annotations

import logging
import os
import stat
import tomllib
from dataclasses import dataclass
from pathlib import Path

from ..core.enums import Fabricante
from ..core.errors import ErrorConfiguracion, ErrorValidacion
from ..core.models import OLT, CredencialesOLT
from ..core.registry import fabricantes_registrados

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class EquipoDeclarado:
    """Una OLT tal como quedó descrita en el archivo."""

    nombre: str
    host: str
    fabricante: Fabricante
    credenciales: CredencialesOLT
    descripcion: str = ""


@dataclass(frozen=True, slots=True)
class ResultadoCarga:
    creadas: tuple[str, ...] = ()
    actualizadas: tuple[str, ...] = ()

    @property
    def total(self) -> int:
        return len(self.creadas) + len(self.actualizadas)


def leer_equipos(ruta: str | Path) -> list[EquipoDeclarado]:
    """Lee y valida el archivo de equipos. No toca la base ni la red."""
    archivo = Path(ruta)
    if not archivo.is_file():
        raise ErrorConfiguracion(
            f"No existe el archivo de equipos: {archivo}\n"
            "Copiá 'equipos.toml.ejemplo' y completalo con tus datos."
        )

    _avisar_si_es_legible_por_todos(archivo)

    try:
        datos = tomllib.loads(archivo.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ErrorConfiguracion(f"{archivo} no es un TOML válido: {exc}") from exc

    declaraciones = datos.get("olt")
    if not declaraciones:
        raise ErrorConfiguracion(
            f"{archivo} no declara ninguna OLT. Cada equipo va en un bloque [[olt]]."
        )

    conocidos = {str(f): f for f in fabricantes_registrados()}
    return [_a_equipo(bloque, indice, conocidos) for indice, bloque in enumerate(declaraciones, 1)]


def _a_equipo(bloque: dict, indice: int, conocidos: dict[str, Fabricante]) -> EquipoDeclarado:
    ubicacion = f"bloque [[olt]] número {indice}"

    for obligatorio in ("nombre", "host", "fabricante"):
        if not bloque.get(obligatorio):
            raise ErrorValidacion(f"Falta '{obligatorio}' en el {ubicacion}")

    fabricante = str(bloque["fabricante"]).strip().lower()
    if fabricante not in conocidos:
        raise ErrorValidacion(
            f"Fabricante '{fabricante}' sin driver ({ubicacion}). "
            f"Disponibles: {', '.join(sorted(conocidos))}"
        )

    password = bloque.get("password", "")
    variable = bloque.get("password_entorno")
    if variable:
        password = os.environ.get(str(variable), "")
        if not password:
            raise ErrorConfiguracion(
                f"El {ubicacion} pide la contraseña de la variable {variable}, "
                "que no está definida."
            )

    return EquipoDeclarado(
        nombre=str(bloque["nombre"]),
        host=str(bloque["host"]),
        fabricante=conocidos[fabricante],
        descripcion=str(bloque.get("descripcion", "")),
        credenciales=CredencialesOLT(
            usuario=str(bloque.get("usuario", "admin")),
            password=str(password),
            password_enable=str(bloque.get("password_enable", "")),
            comunidad_snmp_lectura=str(bloque.get("comunidad", "public")),
            puerto_snmp=int(bloque.get("puerto_snmp", 161)),
            puerto_telnet=int(bloque.get("puerto_telnet", 23)),
            puerto_ssh=int(bloque.get("puerto_ssh", 22)),
        ),
    )


def _avisar_si_es_legible_por_todos(archivo: Path) -> None:
    """El archivo tiene contraseñas de equipos: no debería leerlo cualquiera."""
    try:
        modo = archivo.stat().st_mode
    except OSError:  # pragma: no cover - sistemas sin permisos POSIX
        return
    if modo & (stat.S_IRGRP | stat.S_IROTH):
        log.warning(
            "%s tiene contraseñas de OLT y es legible por otros usuarios del sistema. "
            "Restringilo con:  chmod 600 %s",
            archivo,
            archivo,
        )


class ServicioInventarioArchivo:
    """Aplica un archivo de equipos sobre la base del módulo."""

    def __init__(self, servicio_olt, repositorio_olt) -> None:
        self._servicio = servicio_olt
        self._olts = repositorio_olt

    def aplicar(self, equipos: list[EquipoDeclarado]) -> ResultadoCarga:
        """Crea las OLT que faltan y actualiza las que ya están.

        La identidad es la dirección: es lo único que no cambia cuando alguien
        renombra un equipo. Actualizar en vez de fallar es lo que permite
        corregir una contraseña editando el archivo y volviendo a correrlo.
        """
        creadas: list[str] = []
        actualizadas: list[str] = []

        for equipo in equipos:
            existente: OLT | None = self._olts.obtener_por_host(equipo.host)
            if existente is None:
                nueva = self._servicio.registrar(
                    nombre=equipo.nombre,
                    host=equipo.host,
                    fabricante=equipo.fabricante,
                    credenciales=equipo.credenciales,
                    descripcion=equipo.descripcion,
                )
                creadas.append(f"#{nueva.id} {nueva.nombre} ({nueva.host})")
                continue

            self._servicio.actualizar_credenciales(existente.id, equipo.credenciales)
            actualizadas.append(f"#{existente.id} {existente.nombre} ({existente.host})")

        return ResultadoCarga(tuple(creadas), tuple(actualizadas))
