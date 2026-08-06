"""Sondeo de los puertos de gestión de una OLT.

Cuando la CLI no abre, la primera pregunta es siempre la misma: ¿el equipo no
escucha ahí, o directamente no llega el paquete? Son dos problemas distintos con
soluciones distintas, y el error de un socket solo no alcanza para separarlos.

* **rechazado** (RST inmediato): se llega al equipo, pero ese servicio está
  apagado. Se arregla en la OLT.
* **sin respuesta** (timeout): un firewall o una ACL descarta el paquete en
  silencio. Se arregla en el camino, o en la lista de gestión del equipo.

Distinguirlos ahorra la tarde entera de revisar credenciales cuando el problema
era otro.
"""

from __future__ import annotations

import socket
from dataclasses import dataclass
from enum import StrEnum

#: Puertos de gestión habituales y qué es cada uno.
PUERTOS_CONOCIDOS: dict[int, str] = {
    22: "SSH",
    23: "Telnet",
    80: "web (HTTP)",
    443: "web (HTTPS)",
}


class EstadoPuerto(StrEnum):
    ABIERTO = "abierto"
    RECHAZADO = "rechazado"
    SIN_RESPUESTA = "sin respuesta"


@dataclass(frozen=True, slots=True)
class SondeoPuerto:
    puerto: int
    estado: EstadoPuerto
    servicio: str = ""

    @property
    def abierto(self) -> bool:
        return self.estado is EstadoPuerto.ABIERTO

    @property
    def explicacion(self) -> str:
        if self.estado is EstadoPuerto.ABIERTO:
            return "el equipo escucha acá"
        if self.estado is EstadoPuerto.RECHAZADO:
            return "se llega al equipo, pero el servicio está apagado"
        return "no llega el paquete: firewall, ACL o servicio filtrado"


def sondear_puerto(host: str, puerto: int, timeout: float = 3.0) -> SondeoPuerto:
    """Abre y cierra una conexión TCP para ver qué contesta el equipo."""
    servicio = PUERTOS_CONOCIDOS.get(puerto, "")
    try:
        conexion = socket.create_connection((host, puerto), timeout=timeout)
    except TimeoutError:
        return SondeoPuerto(puerto, EstadoPuerto.SIN_RESPUESTA, servicio)
    except OSError:
        # ConnectionRefused y compañía: hay alguien del otro lado diciendo que
        # no. Es una respuesta, y es muy distinta del silencio.
        return SondeoPuerto(puerto, EstadoPuerto.RECHAZADO, servicio)
    conexion.close()
    return SondeoPuerto(puerto, EstadoPuerto.ABIERTO, servicio)


def sondear_gestion(
    host: str, puertos: tuple[int, ...] = (23, 22, 443, 80), timeout: float = 3.0
) -> list[SondeoPuerto]:
    """Sondea los puertos de gestión de un equipo, en orden."""
    return [sondear_puerto(host, puerto, timeout) for puerto in puertos]
