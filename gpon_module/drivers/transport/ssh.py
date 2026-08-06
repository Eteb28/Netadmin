"""Sesión SSH contra la OLT, sobre paramiko.

Se usa un **canal interactivo** (``invoke_shell``), no ``exec_command``: la CLI
de estos equipos es modal —hay que entrar a ``configure terminal``, a la
interfaz, y salir— y cada ``exec_command`` abre una sesión nueva que pierde el
modo. Con un shell interactivo la conversación es la misma que por Telnet, y
por eso comparte toda la lógica de ``TransporteInteractivo``.

paramiko es una dependencia **opcional**: quien sólo use Telnet no necesita
instalarla. Si falta, se avisa cómo instalarla en vez de reventar con un
ImportError sin contexto.
"""

from __future__ import annotations

import logging
from typing import Any

from ...core.errors import ErrorAutenticacion, ErrorConexion, ErrorTiempoAgotado
from .interactivo import TransporteInteractivo

log = logging.getLogger(__name__)

AVISO_SIN_PARAMIKO = (
    "El transporte SSH necesita paramiko, que no está instalado. "
    "Instalalo con:  pip install paramiko\n"
    "O usá Telnet, que no requiere nada extra (--protocolo telnet)."
)


def _cargar_paramiko() -> Any:
    try:
        import paramiko
    except ImportError as exc:  # pragma: no cover - depende del entorno
        raise ErrorConexion(AVISO_SIN_PARAMIKO) from exc
    return paramiko


class TransporteSSH(TransporteInteractivo):
    """Sesión SSH interactiva contra una OLT.

    A diferencia de Telnet, acá las credenciales las valida el propio
    handshake: cuando el canal se abre, ya estamos autenticados. Lo único que
    puede faltar es el ``enable``, y de eso se ocupa la clase base.
    """

    PROTOCOLO = "ssh"

    def __init__(self, **kwargs: object) -> None:
        kwargs.setdefault("puerto", 22)
        super().__init__(**kwargs)
        self._cliente: Any = None
        self._canal: Any = None

    # --- conexión ---------------------------------------------------------

    def _abrir_sesion(self) -> None:
        paramiko = _cargar_paramiko()

        cliente = paramiko.SSHClient()
        # Estos equipos viven en la red de gestión y su clave de host cambia
        # con cada actualización de firmware. Exigir una known_hosts acá
        # dejaría el módulo inutilizable sin ganar seguridad real.
        cliente.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            cliente.connect(
                hostname=self.host,
                port=self.puerto,
                username=self.usuario,
                password=self.password,
                timeout=self.timeout,
                allow_agent=False,
                look_for_keys=False,
                # Muchas OLT sólo hablan algoritmos viejos. Sin esto, paramiko
                # corta el handshake antes de intentar la contraseña.
                disabled_algorithms={"pubkeys": ["rsa-sha2-256", "rsa-sha2-512"]},
            )
        except paramiko.AuthenticationException as exc:
            cliente.close()
            raise ErrorAutenticacion(
                f"{self.host} rechazó el usuario '{self.usuario}' por SSH"
            ) from exc
        except TimeoutError as exc:
            cliente.close()
            raise ErrorTiempoAgotado(f"{self.host}:{self.puerto} no respondió por SSH") from exc
        except OSError as exc:
            cliente.close()
            raise ErrorConexion(f"No se pudo conectar a {self.host}:{self.puerto}: {exc}") from exc
        except paramiko.SSHException as exc:
            cliente.close()
            raise ErrorConexion(f"Falló la negociación SSH con {self.host}: {exc}") from exc

        self._cliente = cliente
        self._canal = cliente.invoke_shell(width=200, height=1000)
        self._canal.settimeout(self.timeout)
        self._pendiente = b""
        self._autenticar()

    def _cerrar_sesion(self) -> None:
        canal, self._canal = self._canal, None
        cliente, self._cliente = self._cliente, None
        if canal is not None:
            try:
                canal.send(b"exit" + self.FIN_DE_LINEA)
            except OSError:
                pass
            finally:
                canal.close()
        if cliente is not None:
            cliente.close()

    # --- bytes ------------------------------------------------------------

    def _escribir_canal(self, datos: bytes) -> None:
        if self._canal is None:
            raise ErrorConexion(f"La sesión SSH con {self.host} no está abierta")
        self._canal.sendall(datos)

    def _fijar_timeout_lectura(self, segundos: float) -> None:
        if self._canal is not None:
            self._canal.settimeout(segundos)

    def _leer_canal(self, cantidad: int) -> bytes:
        if self._canal is None:
            raise ErrorConexion(f"La sesión SSH con {self.host} no está abierta")
        try:
            return self._canal.recv(cantidad)
        except TimeoutError as exc:
            raise ErrorTiempoAgotado(f"{self.host} dejó de responder") from exc
        except OSError as exc:
            raise ErrorConexion(f"Se cortó la sesión SSH con {self.host}: {exc}") from exc
