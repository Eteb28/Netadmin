"""Los comandos que configuran el CPE: WAN con PPPoE, y WiFi.

Nada de esto está adivinado. La WAN sale **verbatim del propio equipo**: al
pedirle ``onu 1 pri wan_conn show`` a un cliente que anda, el firmware imprime
los comandos que recrean su configuración::

    onu 1 pri wan_conn add routeQOS enable
    onu 1 pri wan_conn index 1 route internet bind_lan 1 bind_ssid 15 qos enable
        nat enable mtu 1492 pppoe proxy disable user esc_mitre_88 pwd a1b1
        server FTTH mode auto

El WiFi sale de la ayuda en línea, recorrida hasta las hojas.

**Lo que este módulo no puede hacer, y hay que decirlo de frente:** la clave del
WiFi, el modo de autenticación y el tipo de cifrado **no existen en esta CLI**.
Se recorrió el árbol entero de ``onu <id> pri`` —37 ramas hasta las hojas— y no
hay ni ``wpa``, ni ``psk``, ni ``encrypt``, ni ``key``. Lo único que se puede
tocar del SSID es el nombre y si se oculta; de la radio, el país, el canal y el
estándar. Fingir lo contrario sería peor que la limitación.

Como todo lo que escribe en este módulo, acá sólo se **arma texto**. Enviarlo o
no es decisión de la capa de arriba, y por defecto no se envía.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ...core.errors import ErrorValidacion

#: ``bind_lan``/``bind_ssid`` son máscaras de bits. Verificado contra la ONU 1:
#: ``bindingLan: lan1`` se escribe ``bind_lan 1`` y ``bindingSsid: ssid1 ssid2
#: ssid3 ssid4`` se escribe ``bind_ssid 15``. El equipo ofrece hasta ssid10.
MASCARA_MAXIMA_LAN, MASCARA_MAXIMA_SSID = 0xFF, 0x3FF

#: Los modos que declara ``wan_conn index <n> route ?``.
MODOS_WAN: frozenset[str] = frozenset(
    {
        "internet",
        "multicast",
        "tr069",
        "tr069_internet",
        "tr069_voip",
        "voip_internet",
        "tr069_voip_internet",
        "voip",
        "other",
    }
)

#: Los países que declara ``wifi_switch <n> enable ?``. ERLAN usa ``fcc``.
PAISES_WIFI: frozenset[str] = frozenset(
    {
        "fcc", "etsi", "ic", "spain", "france", "mkk", "isreal", "mkk2", "mkk3",
        "russian", "cn", "global", "world-wide", "mkk1", "ncc",
    }
)

#: Sin espacios ni caracteres que la CLI pueda interpretar: un espacio de más
#: parte el comando en dos y el resto se lee como otra cosa.
SIN_ESPACIOS = re.compile(r"^[\w.\-@]{1,64}$")

#: El nombre del SSID admite hasta 32, según ``name ?``.
NOMBRE_SSID = re.compile(r"^[\w.\-]{1,32}$")


@dataclass(frozen=True, slots=True)
class SolicitudWAN:
    """La conexión WAN de un CPE, con las credenciales del cliente.

    Los valores por defecto son los de la ONU 1 de Belgrano, que es un cliente
    andando: sirven de referencia verificada, no de invento.
    """

    onu_id: int
    indice: int = 1
    modo: str = "internet"
    #: ``lan1`` = 1, ``lan1 lan2`` = 3. Ligar las dos bocas es lo habitual.
    bind_lan: int = 0b11
    #: ``ssid1..ssid8`` = 255. Ligar todos deja el WiFi sobre la misma WAN.
    bind_ssid: int = 0xFF
    qos: bool = True
    nat: bool = True
    mtu: int = 1492
    pppoe_usuario: str = ""
    pppoe_password: str = ""
    pppoe_servicio: str = "FTTH"
    pppoe_modo: str = "auto"
    pppoe_proxy: bool = False

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return (
            f"SolicitudWAN(onu_id={self.onu_id}, indice={self.indice}, "
            f"usuario={self.pppoe_usuario!r}, password=***)"
        )

    def validar(self) -> None:
        """Rechaza lo dudoso **antes** de que salga un comando al equipo."""
        if not 1 <= self.indice <= 8:
            raise ErrorValidacion(f"El índice de WAN va de 1 a 8, y se pidió {self.indice}")
        if self.modo not in MODOS_WAN:
            raise ErrorValidacion(
                f"Modo de WAN desconocido: {self.modo!r}. "
                f"El equipo acepta: {', '.join(sorted(MODOS_WAN))}."
            )
        if not 0 < self.bind_lan <= MASCARA_MAXIMA_LAN:
            raise ErrorValidacion(
                f"La máscara de LAN debe estar entre 1 y {MASCARA_MAXIMA_LAN}, "
                f"y se pidió {self.bind_lan}. Sin ninguna boca ligada, el cliente "
                "no tendría por dónde salir."
            )
        if not 0 <= self.bind_ssid <= MASCARA_MAXIMA_SSID:
            raise ErrorValidacion(
                f"La máscara de SSID debe estar entre 0 y {MASCARA_MAXIMA_SSID}"
            )
        if not 576 <= self.mtu <= 1500:
            raise ErrorValidacion(f"MTU fuera de rango: {self.mtu}. Con PPPoE se usa 1492.")

        for etiqueta, valor in (
            ("usuario PPPoE", self.pppoe_usuario),
            ("contraseña PPPoE", self.pppoe_password),
            ("nombre de servicio", self.pppoe_servicio),
        ):
            if not valor:
                raise ErrorValidacion(f"Falta el {etiqueta}")
            if not SIN_ESPACIOS.match(valor):
                raise ErrorValidacion(
                    f"El {etiqueta} tiene caracteres que la CLI no admite. "
                    "Un espacio partiría el comando en dos."
                )


def secuencia_wan(solicitud: SolicitudWAN) -> tuple[str, ...]:
    """Los comandos que dejan la WAN configurada, sin navegación.

    Son tres pasos, y el orden importa: **crear**, **configurar** y
    **confirmar**. El ``commit`` no es decorativo — sin él el equipo se queda
    con la conexión a medio armar, que es la misma clase de problema que ya
    dejó una ONU sin servicio.
    """
    solicitud.validar()

    onu, indice = solicitud.onu_id, solicitud.indice
    parametros = " ".join(
        (
            f"onu {onu} pri wan_conn index {indice}",
            f"route {solicitud.modo}",
            f"bind_lan {solicitud.bind_lan}",
            f"bind_ssid {solicitud.bind_ssid}",
            f"qos {_si_no(solicitud.qos)}",
            f"nat {_si_no(solicitud.nat)}",
            f"mtu {solicitud.mtu}",
            f"pppoe proxy {_si_no(solicitud.pppoe_proxy)}",
            f"user {solicitud.pppoe_usuario}",
            f"pwd {solicitud.pppoe_password}",
            f"server {solicitud.pppoe_servicio}",
            f"mode {solicitud.pppoe_modo}",
        )
    )

    return (
        f"onu {onu} pri wan_conn add route qos {_si_no(solicitud.qos)}",
        parametros,
        f"onu {onu} pri wan_conn commit",
    )


@dataclass(frozen=True, slots=True)
class SolicitudRadio:
    """Una de las dos radios del CPE: 2.4 GHz o 5 GHz.

    En los equipos de ERLAN, ``wifi_switch 1`` es la de 2.4 —la de SSID1— y
    ``wifi_switch 2`` la de 5, que es la de SSID5.
    """

    onu_id: int
    radio: int = 1
    encendida: bool = True
    pais: str = "fcc"
    canal: str = "auto"

    def validar(self) -> None:
        if self.radio not in (1, 2):
            raise ErrorValidacion(f"La radio es 1 (2.4 GHz) o 2 (5 GHz), y se pidió {self.radio}")
        if self.encendida and self.pais not in PAISES_WIFI:
            raise ErrorValidacion(
                f"País de WLAN desconocido: {self.pais!r}. "
                f"El equipo acepta: {', '.join(sorted(PAISES_WIFI))}."
            )
        if self.encendida and not SIN_ESPACIOS.match(self.canal):
            raise ErrorValidacion(f"Canal con forma inesperada: {self.canal!r}")


def comando_radio(solicitud: SolicitudRadio) -> str:
    """Prende o apaga una radio, con su país y su canal."""
    solicitud.validar()
    base = f"onu {solicitud.onu_id} pri wifi_switch {solicitud.radio}"
    if not solicitud.encendida:
        return f"{base} disable"
    return f"{base} enable {solicitud.pais} {solicitud.canal}"


@dataclass(frozen=True, slots=True)
class SolicitudSSID:
    """El nombre de una red WiFi, y si se anuncia o no.

    **La clave no está acá porque el equipo no la expone por CLI.** Ver el
    encabezado del módulo.
    """

    onu_id: int
    ssid: int = 1
    nombre: str = ""
    oculto: bool = False
    habilitado: bool = True

    def validar(self) -> None:
        if not 1 <= self.ssid <= 8:
            raise ErrorValidacion(f"El SSID va de 1 a 8, y se pidió {self.ssid}")
        if self.habilitado and not NOMBRE_SSID.match(self.nombre):
            raise ErrorValidacion(
                f"Nombre de red inválido: {self.nombre!r}. Hasta 32 caracteres, "
                "sin espacios: un espacio partiría el comando en dos."
            )


def comando_ssid(solicitud: SolicitudSSID) -> str:
    """Pone el nombre de una red, o la desactiva."""
    solicitud.validar()
    base = f"onu {solicitud.onu_id} pri wifi_ssid {solicitud.ssid}"
    if not solicitud.habilitado:
        return f"{base} disable"
    return f"{base} name {solicitud.nombre} hide {_si_no(solicitud.oculto)}"


def comando_guardar(onu_id: int) -> str:
    """Graba la configuración en el CPE.

    Sin esto, todo lo anterior se pierde en el primer corte de luz del cliente
    —y un corte de luz en el domicilio es justo lo que el módulo ya sabe
    detectar como DyingGasp—. Va último, siempre.
    """
    return f"onu {onu_id} pri save_config"


def _si_no(valor: bool) -> str:
    return "enable" if valor else "disable"


__all__ = [
    "MODOS_WAN",
    "PAISES_WIFI",
    "SolicitudRadio",
    "SolicitudSSID",
    "SolicitudWAN",
    "comando_guardar",
    "comando_radio",
    "comando_ssid",
    "secuencia_wan",
]
