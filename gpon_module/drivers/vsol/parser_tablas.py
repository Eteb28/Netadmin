"""Lectura de las tablas que la VSOL devuelve dentro de ``interface gpon 0/N``.

Los comandos de GPON de este firmware no están en el modo EXEC: viven dentro de
``configure terminal`` → ``interface gpon 0/N``. Ahí aparecen los tres que
importan, verificados contra la OLT de ERLAN:

``show onu auto-find``
    Las ONU detectadas y **sin autorizar**. Es lo que la web muestra como "ONU
    AutoFind" y el punto de partida del alta de un cliente.

``show onu info``
    Inventario con modelo, perfil y **número de serie** de cada ONU.

``show onu state``
    Estado de cada ONU con su ``Phase State``: ``working``, ``OffLine``,
    ``DyingGasp`` o ``LOS``. Esto es **el motivo de caída que SNMP no da** en
    estos equipos: DyingGasp es un corte de luz en el domicilio y LOS es un
    problema de fibra. Son dos cuadrillas distintas.

Las filas llegan alineadas con saltos de columna ANSI, no con espacios; de eso
se ocupa el transporte antes de que estos parsers vean el texto.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ...core.enums import EstadoONU, MotivoCaida

#: ``GPON0/1:1`` o ``1/1/1:1`` — el equipo usa las dos formas según el comando.
REFERENCIA = re.compile(r"^(?:GPON)?(?:\d+/)*(?P<pon>\d+):(?P<onu>\d+)$", re.IGNORECASE)

#: Líneas de adorno que no son datos.
SEPARADOR = re.compile(r"^[-=\s]*$")
TOTAL = re.compile(r"^\s*(ONU\s+Number|Total)\s*[:.]", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ONUPendiente:
    """Una ONU detectada por el equipo y todavía sin autorizar."""

    pon: int
    numero_serie: str
    indice_propuesto: int | None = None
    estado_informado: str = ""


@dataclass(frozen=True, slots=True)
class ONUInformada:
    """Una fila de ``show onu info``."""

    pon: int
    onu_id: int
    numero_serie: str
    modelo: str = ""
    perfil: str = ""
    modo_autenticacion: str = ""


@dataclass(frozen=True, slots=True)
class EstadoInformado:
    """Una fila de ``show onu state``, ya traducida al vocabulario del módulo."""

    pon: int
    onu_id: int
    estado: EstadoONU
    motivo: MotivoCaida
    fase: str = ""
    administrativo: str = ""
    omcc: str = ""


def _referencia(campo: str) -> tuple[int, int] | None:
    encontrado = REFERENCIA.match(campo.strip())
    if encontrado is None:
        return None
    return int(encontrado.group("pon")), int(encontrado.group("onu"))


def _filas(texto: str, encabezado: str) -> list[list[str]]:
    """Devuelve las filas de datos, ya partidas en campos.

    Se descartan el encabezado, los separadores y los totales. Todo lo demás se
    parte por espacios: el transporte ya dejó las columnas alineadas.
    """
    filas: list[list[str]] = []
    for linea in texto.splitlines():
        limpia = linea.strip()
        if not limpia or SEPARADOR.match(limpia) or TOTAL.match(limpia):
            continue
        if encabezado.lower() in limpia.lower():
            continue
        campos = limpia.split()
        if campos:
            filas.append(campos)
    return filas


def parsear_onu_auto_find(texto: str) -> list[ONUPendiente]:
    """``show onu auto-find`` — las ONU esperando ser autorizadas.

    Formato real::

        OnuIndex                 Sn                       State
        ---------------------------------------------------------
        GPON0/1:1                GPON002E64F8             unknow
    """
    pendientes: list[ONUPendiente] = []
    for campos in _filas(texto, "OnuIndex"):
        if len(campos) < 2:
            continue
        referencia = _referencia(campos[0])
        if referencia is None:
            continue
        pon, indice = referencia
        pendientes.append(
            ONUPendiente(
                pon=pon,
                numero_serie=campos[1],
                indice_propuesto=indice,
                estado_informado=campos[2] if len(campos) > 2 else "",
            )
        )
    return pendientes


def parsear_onu_info(texto: str) -> list[ONUInformada]:
    """``show onu info`` — inventario con serial, modelo y perfil.

    Formato real::

        Onuindex   Model                Profile                Mode    AuthInfo
        GPON0/1:1  V411                 V2801RGW               sn      GPON0049BA70
    """
    informadas: list[ONUInformada] = []
    for campos in _filas(texto, "Onuindex"):
        if len(campos) < 5:
            continue
        referencia = _referencia(campos[0])
        if referencia is None:
            continue
        pon, onu_id = referencia
        informadas.append(
            ONUInformada(
                pon=pon,
                onu_id=onu_id,
                modelo="" if campos[1].lower() == "unknown" else campos[1],
                perfil=campos[2],
                modo_autenticacion=campos[3],
                numero_serie=campos[4],
            )
        )
    return informadas


#: ``Phase State`` → qué significa para el módulo.
#:
#: La distinción entre DyingGasp y LOS es la que decide si hay que mandar una
#: cuadrilla: **DyingGasp es un corte de luz en el domicilio del cliente** —la
#: ONU alcanzó a avisar que se quedaba sin energía— y **LOS es pérdida de señal
#: óptica**, es decir un problema de fibra. Confundirlas cuesta un viaje.
FASES: dict[str, tuple[EstadoONU, MotivoCaida]] = {
    "working": (EstadoONU.EN_LINEA, MotivoCaida.NINGUNO),
    "offline": (EstadoONU.FUERA_DE_LINEA, MotivoCaida.DESCONOCIDO),
    "dyinggasp": (EstadoONU.FUERA_DE_LINEA, MotivoCaida.APAGADO),
    "los": (EstadoONU.FUERA_DE_LINEA, MotivoCaida.PERDIDA_SENAL),
}


def parsear_onu_state(texto: str) -> list[EstadoInformado]:
    """``show onu state`` — estado y motivo de caída de cada ONU.

    Formato real::

        OnuIndex    Admin State    OMCC State    Phase State    Channel
        1/1/1:7     enable         disable       DyingGasp      1(GPON)
    """
    estados: list[EstadoInformado] = []
    for campos in _filas(texto, "OnuIndex"):
        if len(campos) < 4:
            continue
        referencia = _referencia(campos[0])
        if referencia is None:
            continue
        pon, onu_id = referencia

        fase = campos[3]
        estado, motivo = FASES.get(fase.lower(), (EstadoONU.DESCONOCIDO, MotivoCaida.DESCONOCIDO))
        estados.append(
            EstadoInformado(
                pon=pon,
                onu_id=onu_id,
                estado=estado,
                motivo=motivo,
                fase=fase,
                administrativo=campos[1],
                omcc=campos[2],
            )
        )
    return estados
