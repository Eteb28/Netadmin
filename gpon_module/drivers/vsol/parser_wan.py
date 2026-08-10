"""La WAN de un CPE, leída de ``onu <id> pri wan_conn show``.

Este comando es el mejor regalo que dio la exploración: además de listar los
valores, **el equipo imprime los comandos que recrean esa configuración**. Es
la sintaxis contada por el propio firmware, que es exactamente lo que hacía
falta y lo que no se podía adivinar.

Salida real de la ONU 1 de Belgrano::

    wanNumber:1
    ********************************
    wanIndex            : 1
    bindingLan          : lan1
    bindingSsid         : ssid1 ssid2 ssid3 ssid4
    wanMode             : internet
    wanConnType         : route
    wanVlanId           : 1001
    wanConnMode         : PPPOE
    pppoeUserName       : esc_mitre_88
    pppoePassword       : a1b1
    pppoeServName       : FTTH
    wanMTU              : 1492
    wanStatus           : connected
    onu 1 pri wan_conn add routeQOS enable
    onu 1 pri wan_conn index 1 route internet bind_lan 1 bind_ssid 15 ...

Las dos últimas líneas se guardan aparte, sin interpretar: son el molde con el
que se va a escribir, y modificarlas al leerlas sería perder la única fuente
confiable que hay.

**Acá hay contraseñas de clientes.** El PPPoE viaja en texto plano en esta
salida, así que el modelo lo oculta al imprimirse y esto no debería loguearse
entero nunca.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: ``  pppoeUserName       : esc_mitre_88``
CAMPO = re.compile(r"^\s*(?P<clave>[A-Za-z][\w]*)\s*:\s*(?P<valor>.*?)\s*$")

#: Las líneas que el equipo imprime como comandos reproducibles.
COMANDO_ECO = re.compile(r"^\s*(onu\s+\d+\s+pri\s+wan_\w+\s+.*)$")

#: ``lan1``, ``ssid3`` → el número. El equipo los lista por nombre y los recibe
#: como máscara de bits, así que hay que poder ir y volver.
INTERFAZ = re.compile(r"^(?:lan|ssid)(?P<numero>\d+)$", re.IGNORECASE)


def mascara_de(nombres: str) -> int:
    """``ssid1 ssid2 ssid3 ssid4`` → ``15``.

    El equipo muestra los nombres pero el comando recibe una máscara de bits:
    en la ONU 1, ``bindingSsid: ssid1 ssid2 ssid3 ssid4`` se escribe
    ``bind_ssid 15`` (1+2+4+8), y ``bindingLan: lan1`` se escribe
    ``bind_lan 1``. Sin esta traducción, la lectura y la escritura hablarían
    idiomas distintos.
    """
    mascara = 0
    for pedazo in nombres.split():
        encontrado = INTERFAZ.match(pedazo.strip())
        if encontrado is not None:
            mascara |= 1 << (int(encontrado.group("numero")) - 1)
    return mascara


def nombres_de(mascara: int, prefijo: str, cantidad: int = 8) -> str:
    """El camino inverso: ``15`` → ``ssid1 ssid2 ssid3 ssid4``."""
    return " ".join(
        f"{prefijo}{n}" for n in range(1, cantidad + 1) if mascara & (1 << (n - 1))
    )


@dataclass(frozen=True, slots=True)
class ConfigWANLeida:
    """Lo que el equipo dice que tiene configurado un CPE."""

    indice: int = 0
    tipo_conexion: str = ""
    modo_servicio: str = ""
    modo_conexion: str = ""
    vlan: int | None = None
    vlan_cos: int | None = None
    mtu: int | None = None
    nat: str = ""
    qos: str = ""
    pppoe_usuario: str = ""
    pppoe_password: str = ""
    pppoe_servicio: str = ""
    pppoe_modo: str = ""
    lan_ligadas: str = ""
    ssid_ligados: str = ""
    nombre: str = ""
    estado: str = ""
    #: Los comandos que el propio equipo imprime para recrear esta WAN. Se
    #: guardan crudos: son el molde con el que se va a escribir.
    comandos_eco: tuple[str, ...] = field(default_factory=tuple)

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return (
            f"ConfigWANLeida(indice={self.indice}, vlan={self.vlan}, "
            f"usuario={self.pppoe_usuario!r}, password=***)"
        )

    @property
    def mascara_lan(self) -> int:
        return mascara_de(self.lan_ligadas)

    @property
    def mascara_ssid(self) -> int:
        return mascara_de(self.ssid_ligados)

    @property
    def conectada(self) -> bool:
        return self.estado.lower() == "connected"


#: Nombre del campo en el equipo → atributo del modelo. Los que no están acá se
#: ignoran a propósito: agregar un campo es una decisión, no un accidente.
CAMPOS: dict[str, str] = {
    "wanindex": "indice",
    "wanconntype": "tipo_conexion",
    "wanmode": "modo_servicio",
    "wanconnmode": "modo_conexion",
    "wanvlanid": "vlan",
    "wancos": "vlan_cos",
    "wanmtu": "mtu",
    "wannatenable": "nat",
    "qosenable": "qos",
    "pppoeusername": "pppoe_usuario",
    "pppoepassword": "pppoe_password",
    "pppoeservname": "pppoe_servicio",
    "pppoemode": "pppoe_modo",
    "bindinglan": "lan_ligadas",
    "bindingssid": "ssid_ligados",
    "wanname": "nombre",
    "wanstatus": "estado",
}

ENTEROS = frozenset({"indice", "vlan", "vlan_cos", "mtu"})


def parsear_wan_conn_show(texto: str) -> list[ConfigWANLeida]:
    """Lee las WAN que el equipo reporta para una ONU.

    Un CPE puede tener varias (internet, VoIP, TR069), separadas por la línea
    de asteriscos. Se devuelven todas: quedarse con la primera daría una foto
    incompleta justo en los clientes que tienen teléfono.
    """
    conexiones: list[ConfigWANLeida] = []
    actual: dict[str, object] = {}
    ecos: list[str] = []

    def cerrar() -> None:
        if actual:
            conexiones.append(ConfigWANLeida(**actual, comandos_eco=tuple(ecos)))  # type: ignore[arg-type]

    for linea in texto.splitlines():
        if set(linea.strip()) == {"*"}:
            cerrar()
            actual, ecos = {}, []
            continue

        if encontrado := COMANDO_ECO.match(linea):
            ecos.append(encontrado.group(1).strip())
            continue

        campo = CAMPO.match(linea)
        if campo is None:
            continue
        atributo = CAMPOS.get(campo.group("clave").lower())
        if atributo is None:
            continue
        valor: object = campo.group("valor")
        if atributo in ENTEROS:
            try:
                valor = int(str(valor))
            except ValueError:
                continue
        actual[atributo] = valor

    cerrar()
    return conexiones


__all__ = ["CAMPOS", "ConfigWANLeida", "mascara_de", "nombres_de", "parsear_wan_conn_show"]
