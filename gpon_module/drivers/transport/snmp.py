"""Transporte SNMP.

Canal principal de lectura: barato, masivo y —en VSOL— de sólo lectura.

Hay dos implementaciones porque en la práctica una u otra falta según el
servidor: ``pysnmp`` (biblioteca Python) y las herramientas ``net-snmp``
(``snmpget``/``snmpwalk``, presentes en casi cualquier servidor de ISP). La
fábrica elige la que esté disponible; el resto del módulo no se entera.

La regla que gobierna este archivo, y que vale más que cualquier optimización:

    Una rama vacía y una falla de comunicación **no son lo mismo**.

``walk`` devuelve ``{}`` sólo cuando el equipo contestó y esa rama no existe.
Si no hubo respuesta, levanta ``ErrorTiempoAgotado``. Confundir ambos casos es
exactamente lo que produce una baja masiva falsa (riesgo R5).
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess

from ...core.errors import (
    ErrorAutenticacion,
    ErrorConfiguracion,
    ErrorTiempoAgotado,
    ErrorTransporte,
)

log = logging.getLogger(__name__)

#: Respuestas que significan "ese objeto no existe", no "hubo un problema".
_AUSENCIAS = (
    "no such object",
    "no such instance",
    "nosuchobject",
    "nosuchinstance",
    "endofmibview",
)

_SIN_RESPUESTA = ("timeout", "no response", "unreachable")


def _es_ausencia(texto: str) -> bool:
    minuscula = texto.lower()
    return any(marca in minuscula for marca in _AUSENCIAS)


def _es_sin_respuesta(texto: str) -> bool:
    minuscula = texto.lower()
    return any(marca in minuscula for marca in _SIN_RESPUESTA)


def _limpiar(valor: str) -> str:
    """Quita comillas y espacios que agregan las herramientas SNMP."""
    valor = valor.strip()
    if len(valor) >= 2 and valor[0] == valor[-1] == '"':
        valor = valor[1:-1]
    return valor.strip()


class TransporteSNMPNetSNMP:
    """Implementación sobre las herramientas ``net-snmp`` del sistema.

    Es la más robusta en servidores de producción: ``snmpget`` y ``snmpwalk``
    suelen estar instalados, y su comportamiento es idéntico al que el operador
    ve cuando prueba a mano.
    """

    def __init__(
        self,
        *,
        host: str,
        comunidad: str,
        puerto: int = 161,
        timeout: float = 5.0,
        reintentos: int = 2,
        version: str = "2c",
    ) -> None:
        self.host = host
        self.comunidad = comunidad
        self.puerto = puerto
        self.timeout = timeout
        self.reintentos = reintentos
        self.version = version

    @staticmethod
    def disponible() -> bool:
        return bool(shutil.which("snmpwalk") and shutil.which("snmpget"))

    def _ejecutar(self, herramienta: str, oid: str) -> list[str]:
        comando = [
            herramienta,
            "-v",
            self.version,
            "-c",
            self.comunidad,
            "-t",
            str(self.timeout),
            "-r",
            str(self.reintentos),
            "-On",  # OIDs numéricos: no dependemos de que haya MIBs cargadas
            "-Oe",  # enteros crudos, sin traducir a nombres simbólicos
            f"{self.host}:{self.puerto}",
            oid,
        ]
        try:
            proceso = subprocess.run(
                comando,
                capture_output=True,
                text=True,
                timeout=self.timeout * (self.reintentos + 1) + 30,
            )
        except FileNotFoundError as exc:
            raise ErrorConfiguracion(
                f"No se encontró '{herramienta}'. Instalá net-snmp "
                "(Debian/Ubuntu: sudo apt install snmp)."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise ErrorTiempoAgotado(
                f"{herramienta} no terminó al consultar {self.host}"
            ) from exc

        salida_error = proceso.stderr.strip()
        if proceso.returncode != 0 or salida_error:
            if _es_sin_respuesta(salida_error) or _es_sin_respuesta(proceso.stdout):
                raise ErrorTiempoAgotado(f"{self.host} no respondió a SNMP: {salida_error}")
            minusculas = salida_error.lower()
            if "authorizationerror" in minusculas or "authentication" in minusculas:
                raise ErrorAutenticacion(f"{self.host} rechazó la community SNMP")
            if not _es_ausencia(salida_error) and proceso.returncode != 0:
                raise ErrorTransporte(f"SNMP falló contra {self.host}: {salida_error}")

        return [linea for linea in proceso.stdout.splitlines() if linea.strip()]

    def get(self, oid: str) -> str | None:
        lineas = self._ejecutar("snmpget", oid)
        if not lineas:
            return None
        _, _, valor = lineas[0].partition("=")
        if not valor:
            return None
        # El formato es "<tipo>: <valor>"; el tipo no nos interesa.
        _, _, crudo = valor.partition(":")
        crudo = _limpiar(crudo or valor)
        return None if _es_ausencia(crudo) or crudo == "" else crudo

    def walk(self, oid_base: str) -> dict[str, str]:
        lineas = self._ejecutar("snmpwalk", oid_base)
        resultado: dict[str, str] = {}
        for linea in lineas:
            oid, _, valor = linea.partition("=")
            oid = oid.strip().lstrip(".")
            if not valor:
                continue
            _, _, crudo = valor.partition(":")
            crudo = _limpiar(crudo or valor)
            if _es_ausencia(crudo):
                continue
            resultado[oid] = crudo
        return resultado

    def cerrar(self) -> None:
        """No hay sesión que cerrar: cada consulta es un proceso aparte."""


class TransporteSNMPPysnmp:
    """Implementación sobre ``pysnmp``. Evita lanzar un proceso por consulta."""

    def __init__(
        self,
        *,
        host: str,
        comunidad: str,
        puerto: int = 161,
        timeout: float = 5.0,
        reintentos: int = 2,
    ) -> None:
        self.host = host
        self.comunidad = comunidad
        self.puerto = puerto
        self.timeout = timeout
        self.reintentos = reintentos
        self._hlapi = self._importar()

    @staticmethod
    def disponible() -> bool:
        try:
            import pysnmp.hlapi  # noqa: F401
        except ImportError:
            return False
        return True

    @staticmethod
    def _importar():
        try:
            from pysnmp import hlapi
        except ImportError as exc:  # pragma: no cover - depende del entorno
            raise ErrorConfiguracion(
                "Falta 'pysnmp'. Instalalo con: pip install 'gpon-module[equipos]'"
            ) from exc
        return hlapi

    def _contexto(self):
        hlapi = self._hlapi
        return (
            hlapi.SnmpEngine(),
            hlapi.CommunityData(self.comunidad, mpModel=1),
            hlapi.UdpTransportTarget(
                (self.host, self.puerto), timeout=self.timeout, retries=self.reintentos
            ),
            hlapi.ContextData(),
        )

    def get(self, oid: str) -> str | None:
        hlapi = self._hlapi
        motor, comunidad, destino, contexto = self._contexto()
        iterador = hlapi.getCmd(
            motor, comunidad, destino, contexto, hlapi.ObjectType(hlapi.ObjectIdentity(oid))
        )
        error_motor, error_estado, _, enlaces = next(iterador)
        if error_motor:
            raise ErrorTiempoAgotado(f"{self.host} no respondió a SNMP: {error_motor}")
        if error_estado:
            raise ErrorTransporte(f"SNMP falló contra {self.host}: {error_estado.prettyPrint()}")
        for _, valor in enlaces:
            texto = _limpiar(valor.prettyPrint())
            return None if _es_ausencia(texto) or texto == "" else texto
        return None

    def walk(self, oid_base: str) -> dict[str, str]:
        hlapi = self._hlapi
        motor, comunidad, destino, contexto = self._contexto()
        resultado: dict[str, str] = {}
        for error_motor, error_estado, _, enlaces in hlapi.nextCmd(
            motor,
            comunidad,
            destino,
            contexto,
            hlapi.ObjectType(hlapi.ObjectIdentity(oid_base)),
            lexicographicMode=False,
        ):
            if error_motor:
                raise ErrorTiempoAgotado(f"{self.host} no respondió a SNMP: {error_motor}")
            if error_estado:
                raise ErrorTransporte(
                    f"SNMP falló contra {self.host}: {error_estado.prettyPrint()}"
                )
            for oid, valor in enlaces:
                texto = _limpiar(valor.prettyPrint())
                if _es_ausencia(texto):
                    continue
                resultado[str(oid).lstrip(".")] = texto
        return resultado

    def cerrar(self) -> None:
        """pysnmp administra sus propios recursos por consulta."""


def crear_transporte_snmp(
    *,
    host: str,
    comunidad: str,
    puerto: int = 161,
    timeout: float = 5.0,
    reintentos: int = 2,
    preferencia: str | None = None,
):
    """Devuelve el transporte SNMP disponible en este sistema.

    ``preferencia`` fuerza una implementación (``"netsnmp"`` o ``"pysnmp"``);
    sin ella se elige net-snmp primero, por ser lo que el operador ya tiene y
    puede reproducir a mano desde una terminal.
    """
    parametros = {
        "host": host,
        "comunidad": comunidad,
        "puerto": puerto,
        "timeout": timeout,
        "reintentos": reintentos,
    }

    if preferencia == "netsnmp":
        return TransporteSNMPNetSNMP(**parametros)
    if preferencia == "pysnmp":
        return TransporteSNMPPysnmp(**parametros)

    if TransporteSNMPNetSNMP.disponible():
        return TransporteSNMPNetSNMP(**parametros)
    if TransporteSNMPPysnmp.disponible():
        return TransporteSNMPPysnmp(**parametros)

    raise ErrorConfiguracion(
        "No hay forma de hablar SNMP en este sistema. Instalá una de las dos:\n"
        "  · net-snmp:  sudo apt install snmp        (recomendado)\n"
        "  · pysnmp:    pip install 'gpon-module[equipos]'"
    )


# --- utilidades de índices ------------------------------------------------

_INDICE = re.compile(r"\.(\d+)\.(\d+)$")


def indice_doble(oid: str) -> tuple[int, int] | None:
    """Extrae ``(pon, onu)`` del final de un OID de tabla de ONU.

    Devuelve ``None`` si el OID no termina en dos índices numéricos, en vez de
    inventar una posición: una ONU mal ubicada es peor que una ONU ausente.
    """
    coincidencia = _INDICE.search(oid)
    if coincidencia is None:
        return None
    return int(coincidencia.group(1)), int(coincidencia.group(2))


def indice_simple(oid: str) -> int | None:
    """Extrae el último índice numérico de un OID."""
    ultimo = oid.rsplit(".", 1)[-1]
    return int(ultimo) if ultimo.isdigit() else None
