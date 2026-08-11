"""Transportes: la mecánica de hablar con un equipo.

``base`` concentra lo que no depende del fabricante ni del protocolo.
``interactivo`` agrega la conversación con una CLI (prompts, paginación,
login), y sobre ella se apoyan ``telnet`` y ``ssh``, que sólo mueven bytes.
"""

from __future__ import annotations

from ...core.errors import ErrorValidacion
from .base import (
    MARCADORES_ERROR,
    TransporteCLIBase,
    detectar_rechazo,
    reintentar,
    sesion_exclusiva,
)
from .interactivo import TransporteInteractivo

#: Protocolos de CLI que el módulo sabe hablar.
PROTOCOLOS_CLI = ("telnet", "ssh")


def crear_transporte_cli(
    *,
    host: str,
    usuario: str = "",
    password: str = "",
    password_enable: str = "",
    protocolo: str = "telnet",
    puerto: int | None = None,
    timeout: float = 20.0,
    intentos: int = 3,
    ruta_traza: str | None = None,
) -> TransporteCLIBase:
    """Devuelve el transporte CLI pedido, ya configurado y sin abrir.

    El protocolo se elige explícitamente y no se adivina: probar Telnet y caer
    a SSH (o al revés) duplicaría los intentos de login fallidos, y varios de
    estos equipos bloquean la cuenta tras unos pocos.
    """
    normalizado = protocolo.strip().lower()
    if normalizado not in PROTOCOLOS_CLI:
        raise ErrorValidacion(
            f"Protocolo CLI desconocido: '{protocolo}'. Disponibles: {', '.join(PROTOCOLOS_CLI)}"
        )

    if normalizado == "ssh":
        # Import diferido: paramiko es una dependencia opcional.
        from .ssh import TransporteSSH

        clase: type[TransporteInteractivo] = TransporteSSH
        puerto_efectivo = puerto or 22
    else:
        from .telnet import TransporteTelnet

        clase = TransporteTelnet
        puerto_efectivo = puerto or 23

    return clase(
        host=host,
        usuario=usuario,
        password=password,
        password_enable=password_enable,
        puerto=puerto_efectivo,
        timeout=timeout,
        intentos=intentos,
        ruta_traza=ruta_traza,
    )


__all__ = [
    "MARCADORES_ERROR",
    "PROTOCOLOS_CLI",
    "TransporteCLIBase",
    "TransporteInteractivo",
    "crear_transporte_cli",
    "detectar_rechazo",
    "reintentar",
    "sesion_exclusiva",
]
