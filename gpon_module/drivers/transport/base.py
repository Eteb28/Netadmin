"""Base del transporte: lo que hace que la CLI funcione en producción.

Los detalles concentrados acá son exactamente los que rompen cuando se habla
con una OLT real, y ninguno es específico de un fabricante:

* la paginación (``--More--``) cuelga la sesión → se desactiva al abrir (R3);
* la CLI es de **sesión única** → acceso serializado por OLT (R4);
* los timeouts son intermitentes → reintento con espera creciente, y un
  timeout **jamás** se traduce a "no existe" (R5);
* un comando rechazado pasa desapercibido → se detecta y se aborta la
  secuencia en el acto (R2).
"""

from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from typing import TypeVar

from ...core.errors import ErrorComando, ErrorConexion, ErrorTiempoAgotado, OLTOcupada

log = logging.getLogger(__name__)

T = TypeVar("T")

#: Marcadores de rechazo habituales en CLI de estilo Cisco (VSOL y ZTE lo son).
#: Cada driver puede ampliarlos, nunca reemplazar la detección por completo.
MARCADORES_ERROR: tuple[str, ...] = (
    "% Invalid input detected",
    "% Unknown command",
    "% Incomplete command",
    "Invalid input",
    "Error:",
    "%Error",
    "Command not found",
)

_bloqueos: dict[str, threading.Lock] = {}
_bloqueo_maestro = threading.Lock()


def _bloqueo_para(clave: str) -> threading.Lock:
    with _bloqueo_maestro:
        return _bloqueos.setdefault(clave, threading.Lock())


@contextmanager
def sesion_exclusiva(clave: str, timeout_segundos: float = 60.0) -> Iterator[None]:
    """Serializa el acceso a una OLT: nunca dos operaciones a la vez (R4).

    La CLI de estas OLT es de sesión única. Dos hilos configurando el mismo
    equipo al mismo tiempo no producen un error prolijo: producen una
    configuración entrelazada e impredecible.
    """
    bloqueo = _bloqueo_para(clave)
    if not bloqueo.acquire(timeout=timeout_segundos):
        raise OLTOcupada(
            f"La sesión CLI de {clave} sigue ocupada tras {timeout_segundos:g} s. "
            "Otra operación está en curso."
        )
    try:
        yield
    finally:
        bloqueo.release()


def reintentar(
    operacion: Callable[[], T],
    *,
    intentos: int = 3,
    espera_inicial: float = 1.0,
    excepciones: tuple[type[BaseException], ...] = (ErrorTiempoAgotado, ErrorConexion),
    descripcion: str = "operación",
    dormir: Callable[[float], None] = time.sleep,
) -> T:
    """Reintenta con espera creciente (1 s, 2 s, 4 s…).

    Sólo reintenta fallas de comunicación. Un comando rechazado por el equipo
    no se reintenta: reenviarlo no lo va a hacer válido.
    """
    ultimo: BaseException | None = None
    espera = espera_inicial
    for intento in range(1, intentos + 1):
        try:
            return operacion()
        except excepciones as exc:
            ultimo = exc
            if intento == intentos:
                break
            log.warning(
                "%s falló (intento %d/%d): %s. Reintento en %.1f s",
                descripcion,
                intento,
                intentos,
                exc,
                espera,
            )
            dormir(espera)
            espera *= 2
    assert ultimo is not None
    raise ultimo


def detectar_rechazo(salida: str, marcadores: Sequence[str] = MARCADORES_ERROR) -> str | None:
    """Devuelve el marcador de error hallado en la salida, o ``None``."""
    for marcador in marcadores:
        if marcador.lower() in salida.lower():
            return marcador
    return None


class TransporteCLIBase(ABC):
    """Esqueleto de una sesión CLI, independiente de Telnet o SSH.

    Las subclases sólo implementan ``_abrir_sesion``, ``_cerrar_sesion`` y
    ``_enviar``. Toda la disciplina —paginación, exclusión mutua, detección de
    rechazos, aborto de secuencia— vive acá y se aplica igual a todos.
    """

    #: Comandos que se envían al abrir. ``terminal length 0`` es imprescindible:
    #: sin él, la primera salida larga deja la sesión esperando ``--More--``.
    COMANDOS_INICIALES: tuple[str, ...] = ("terminal length 0",)

    def __init__(
        self,
        *,
        host: str,
        usuario: str = "",
        password: str = "",
        password_enable: str = "",
        puerto: int = 23,
        timeout: float = 20.0,
        intentos: int = 3,
        marcadores_error: Sequence[str] = MARCADORES_ERROR,
    ) -> None:
        self.host = host
        self.usuario = usuario
        self.password = password
        self.password_enable = password_enable
        self.puerto = puerto
        self.timeout = timeout
        self.intentos = intentos
        self.marcadores_error = tuple(marcadores_error)
        self._conectado = False

    # --- a implementar por cada transporte concreto ----------------------

    @abstractmethod
    def _abrir_sesion(self) -> None:
        """Establece la conexión y deja la sesión en modo privilegiado."""

    @abstractmethod
    def _cerrar_sesion(self) -> None: ...

    @abstractmethod
    def _enviar(self, comando: str) -> str:
        """Envía un comando crudo y devuelve la salida, sin interpretarla."""

    # --- comportamiento común --------------------------------------------

    @property
    def conectado(self) -> bool:
        return self._conectado

    def abrir(self) -> None:
        if self._conectado:
            return
        reintentar(
            self._abrir_sesion,
            intentos=self.intentos,
            descripcion=f"apertura de sesión CLI con {self.host}",
        )
        self._conectado = True
        for comando in self.COMANDOS_INICIALES:
            # Si el equipo no conoce el comando de paginación no es motivo de
            # aborto: se registra y se sigue.
            try:
                self._enviar(comando)
            except ErrorComando as exc:
                log.debug("Comando inicial '%s' rechazado por %s: %s", comando, self.host, exc)

    def cerrar(self) -> None:
        if not self._conectado:
            return
        try:
            self._cerrar_sesion()
        finally:
            self._conectado = False

    def ejecutar(self, comando: str) -> str:
        """Envía un comando y valida la respuesta.

        Levanta ``ErrorComando`` si el equipo lo rechazó, en vez de devolver
        una salida de error que el parser tomaría por datos.
        """
        if not self._conectado:
            self.abrir()
        salida = self._enviar(comando)
        marcador = detectar_rechazo(salida, self.marcadores_error)
        if marcador is not None:
            raise ErrorComando(
                f"{self.host} rechazó el comando ({marcador})",
                comando=comando,
                salida=salida,
            )
        return salida

    def ejecutar_secuencia(self, comandos: Sequence[str]) -> list[str]:
        """Envía comandos en orden y **aborta en el primer rechazo**.

        Seguir enviando comandos después de un rechazo es lo que deja una OLT a
        medio configurar. El llamador recibe la excepción con el comando exacto
        que falló, y decide si aplica un rollback.
        """
        salidas: list[str] = []
        for comando in comandos:
            try:
                salidas.append(self.ejecutar(comando))
            except ErrorComando as exc:
                log.error(
                    "Secuencia abortada en %s tras %d de %d comandos. Falló: %s",
                    self.host,
                    len(salidas),
                    len(comandos),
                    comando,
                )
                exc.args = (
                    f"{exc.args[0]} — secuencia abortada tras {len(salidas)} "
                    f"de {len(comandos)} comandos",
                )
                raise
        return salidas

    def __enter__(self):
        self.abrir()
        return self

    def __exit__(self, *_excepcion: object) -> None:
        self.cerrar()
