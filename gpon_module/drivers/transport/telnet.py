"""Cliente Telnet propio, sobre sockets.

``telnetlib`` quedó obsoleto en Python 3.11 y **fue eliminado en 3.13**. Como
el módulo tiene que correr en los Python que hay hoy en los servidores, se
implementa acá lo mínimo del protocolo: negociación IAC —a todo se responde
que no— y lectura de bytes.

Es poco código y es el que hace falta. La conversación con la CLI (prompts,
paginación, login, ``enable``) vive en ``TransporteInteractivo`` y se hereda
entera; acá sólo están los bytes.
"""

from __future__ import annotations

import logging
import socket

from ...core.errors import ErrorConexion, ErrorTiempoAgotado
from .interactivo import TransporteInteractivo

log = logging.getLogger(__name__)

# Bytes de control del protocolo Telnet (RFC 854).
IAC = 255  # interpretar como comando
DONT, DO, WONT, WILL = 254, 253, 252, 251
SB, SE = 250, 240  # subnegociación


class TransporteTelnet(TransporteInteractivo):
    """Sesión Telnet contra una OLT.

    Telnet va en claro y es el canal que estos equipos traen habilitado de
    fábrica. Si la OLT admite SSH conviene usarlo: el módulo lo soporta y las
    credenciales dejan de viajar legibles por la red de gestión.
    """

    PROTOCOLO = "telnet"

    def __init__(self, **kwargs: object) -> None:
        kwargs.setdefault("puerto", 23)
        super().__init__(**kwargs)
        self._socket: socket.socket | None = None

    # --- conexión ---------------------------------------------------------

    def _abrir_sesion(self) -> None:
        try:
            self._socket = socket.create_connection((self.host, self.puerto), timeout=self.timeout)
        except TimeoutError as exc:
            raise ErrorTiempoAgotado(f"{self.host}:{self.puerto} no respondió") from exc
        except OSError as exc:
            raise ErrorConexion(f"No se pudo conectar a {self.host}:{self.puerto}: {exc}") from exc

        self._socket.settimeout(self.timeout)
        self._pendiente = b""
        self._autenticar()

    def _cerrar_sesion(self) -> None:
        socket_actual, self._socket = self._socket, None
        if socket_actual is None:
            return
        try:
            socket_actual.sendall(b"exit\r\n")
        except OSError:
            pass  # el equipo pudo cerrar primero; da igual, ya nos estamos yendo
        finally:
            socket_actual.close()

    # --- bytes ------------------------------------------------------------

    def _escribir_canal(self, datos: bytes) -> None:
        if self._socket is None:
            raise ErrorConexion(f"La sesión Telnet con {self.host} no está abierta")
        self._socket.sendall(datos)

    def _fijar_timeout_lectura(self, segundos: float) -> None:
        if self._socket is not None:
            self._socket.settimeout(segundos)

    def _leer_canal(self, cantidad: int) -> bytes:
        """Devuelve texto. ``b""`` significa que el equipo cerró, y nada más.

        Un bloque de pura negociación IAC no deja texto, y devolverlo vacío se
        leería como un cierre de conexión que no ocurrió. Por eso se sigue
        leyendo hasta tener algo que mostrar.
        """
        if self._socket is None:
            raise ErrorConexion(f"La sesión Telnet con {self.host} no está abierta")

        while True:
            try:
                datos = self._socket.recv(cantidad)
            except TimeoutError as exc:
                raise ErrorTiempoAgotado(f"{self.host} dejó de responder") from exc
            except OSError as exc:
                raise ErrorConexion(f"Se cortó la sesión con {self.host}: {exc}") from exc

            if not datos:
                return b""  # el equipo cerró la conexión
            limpio = self._responder_negociacion(datos)
            if limpio:
                return limpio

    def _responder_negociacion(self, datos: bytes) -> bytes:
        """Contesta la negociación Telnet y devuelve sólo el texto.

        A toda opción se responde que no (DONT/WONT): no se necesita ninguna, y
        aceptar alguna complica la sesión sin ningún beneficio.

        Puede devolver ``b""`` si el bloque recibido era pura negociación; eso
        no significa que el equipo cerró. El cierre se detecta antes, cuando
        ``recv`` devuelve vacío.
        """
        if IAC not in datos:
            return datos

        limpio = bytearray()
        respuesta = bytearray()
        indice = 0
        while indice < len(datos):
            byte = datos[indice]
            if byte != IAC:
                limpio.append(byte)
                indice += 1
                continue

            if indice + 1 >= len(datos):
                break
            orden = datos[indice + 1]

            if orden in (DO, DONT, WILL, WONT):
                if indice + 2 >= len(datos):
                    break
                opcion = datos[indice + 2]
                negativa = WONT if orden in (DO, DONT) else DONT
                respuesta += bytes([IAC, negativa, opcion])
                indice += 3
            elif orden == SB:
                fin = datos.find(bytes([IAC, SE]), indice)
                indice = len(datos) if fin == -1 else fin + 2
            elif orden == IAC:
                limpio.append(IAC)  # IAC IAC es un 255 literal
                indice += 2
            else:
                indice += 2

        if respuesta:
            self._transmitir(bytes(respuesta))
        return bytes(limpio)
