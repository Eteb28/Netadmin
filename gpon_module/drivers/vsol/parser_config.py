"""Lectura del ``show running-config`` de una VSOL V1600G1.

Este parser resuelve, de una sola lectura y sin escribir nada, todo lo que SNMP
no puede dar en estos equipos: **el número de serie de cada ONU**, su perfil, su
descripción, su VLAN y sus perfiles de tráfico. Verificado contra la
configuración real de la OLT de ERLAN: 284 ONU repartidas en 8 puertos PON.

La configuración se lee así::

    interface gpon 0/7
    no onu auto-learn
    onu add 1 profile V2802GW sn GPON00225D48
    onu 1 desc GPON0/7:1_032074
    onu 1 tcont 1 name Internet dba Internet
    onu 1 gemport 1 traffic-limit upstream 300M-Pymes-UP downstream 300M-Pymes-Dowm
    onu 1 service Internet gemport 1 vlan 1001
    onu 1 service-port 1 gemport 1 uservlan 1001 vlan 1001

**Las líneas ``onu N pri ...`` se ignoran a propósito.** Ahí viven la contraseña
PPPoE del cliente y la clave de su WiFi, en texto plano. No hay ninguna razón
para que esos datos entren a la base del módulo hoy, así que no entran. Cuando
la gestión de PPPoE y WiFi llegue (Fase 7) será una decisión explícita, no un
efecto secundario de haber leído la configuración.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: ``interface gpon 0/7`` — abre la sección de un puerto PON.
INTERFAZ_PON = re.compile(r"^interface\s+gpon\s+(\d+)/(\d+)\s*$", re.IGNORECASE)

#: Cualquier otra ``interface`` cierra la sección PON en curso.
OTRA_INTERFAZ = re.compile(r"^interface\s+(?!gpon\b)", re.IGNORECASE)

#: ``onu add 1 profile V2802GW sn GPON00225D48``
ONU_ALTA = re.compile(
    r"^onu\s+add\s+(?P<onu>\d+)\s+profile\s+(?P<perfil>\S+)\s+sn\s+(?P<serie>\S+)",
    re.IGNORECASE,
)

#: ``onu 1 desc GPON0/7:1_032074``
ONU_DESCRIPCION = re.compile(
    r"^onu\s+(?P<onu>\d+)\s+desc\s+(?P<descripcion>.+?)\s*$", re.IGNORECASE
)

#: ``onu 1 tcont 1 name Internet dba Internet`` (el ``name`` puede faltar)
ONU_TCONT = re.compile(
    r"^onu\s+(?P<onu>\d+)\s+tcont\s+\d+(?:\s+name\s+\S+)?\s+dba\s+(?P<dba>\S+)", re.IGNORECASE
)

#: ``onu 1 gemport 1 traffic-limit upstream 300M-Pymes-UP downstream 300M-Pymes-Dowm``
ONU_TRAFICO = re.compile(
    r"^onu\s+(?P<onu>\d+)\s+gemport\s+\d+\s+traffic-limit\s+"
    r"upstream\s+(?P<subida>\S+)\s+downstream\s+(?P<bajada>\S+)",
    re.IGNORECASE,
)

#: ``onu 1 service Internet gemport 1 vlan 1001``
ONU_SERVICIO = re.compile(
    r"^onu\s+(?P<onu>\d+)\s+service\s+(?P<servicio>\S+)\s+gemport\s+\d+\s+vlan\s+(?P<vlan>\d+)",
    re.IGNORECASE,
)

#: ``no onu auto-learn`` dentro de un puerto PON.
SIN_AUTOAPRENDIZAJE = re.compile(r"^no\s+onu\s+auto-learn\s*$", re.IGNORECASE)

#: ``profile dba id 1 name Internet`` y su cuerpo ``type 4 maximum 300000``
PERFIL_DBA = re.compile(
    r"^profile\s+dba\s+id\s+(?P<id>\d+)\s+name\s+(?P<nombre>\S+)", re.IGNORECASE
)
CUERPO_DBA = re.compile(
    r"^type\s+(?P<tipo>\d+)"
    r"(?:\s+fixed\s+(?P<fijo>\d+))?"
    r"(?:\s+assured\s+(?P<asegurado>\d+))?"
    r"(?:\s+maximum\s+(?P<maximo>\d+))?",
    re.IGNORECASE,
)

#: ``profile traffic id 1 name 5M-Dom-Dow``
PERFIL_TRAFICO = re.compile(
    r"^profile\s+traffic\s+id\s+(?P<id>\d+)\s+name\s+(?P<nombre>\S+)", re.IGNORECASE
)

#: ``vlan 300`` y ``vlan 200 - 207`` (rango)
DECLARACION_VLAN = re.compile(
    r"^vlan\s+(?P<desde>\d+)(?:\s*-\s*(?P<hasta>\d+))?\s*$", re.IGNORECASE
)

IDENTIDAD = {
    "hostname": re.compile(r"^hostname\s+(?P<valor>.+?)\s*$", re.IGNORECASE),
    "firmware": re.compile(r"^!Software Version\s*:\s*(?P<valor>.+?)\s*$", re.IGNORECASE),
}


@dataclass(frozen=True, slots=True)
class ONUConfigurada:
    """Una ONU tal como está dada de alta en la configuración del equipo."""

    pon: int
    onu_id: int
    numero_serie: str
    perfil: str = ""
    descripcion: str = ""
    perfil_dba: str = ""
    servicio: str = ""
    vlan: int | None = None
    trafico_subida: str = ""
    trafico_bajada: str = ""


@dataclass(frozen=True, slots=True)
class PerfilDBAConfigurado:
    identificador: int
    nombre: str
    tipo: str = ""
    fijo_kbps: int | None = None
    asegurado_kbps: int | None = None
    maximo_kbps: int | None = None


@dataclass(frozen=True, slots=True)
class PerfilTraficoConfigurado:
    identificador: int
    nombre: str


@dataclass(frozen=True, slots=True)
class ConfiguracionOLT:
    """Todo lo que la configuración en vivo dice del equipo."""

    nombre_equipo: str = ""
    firmware: str = ""
    puertos_pon: tuple[str, ...] = ()
    onus: tuple[ONUConfigurada, ...] = ()
    perfiles_dba: tuple[PerfilDBAConfigurado, ...] = ()
    perfiles_trafico: tuple[PerfilTraficoConfigurado, ...] = ()
    vlans: tuple[int, ...] = ()
    #: Puertos PON con el autoaprendizaje apagado: ahí una ONU nueva no aparece
    #: sola, hay que darla de alta a mano.
    pon_sin_autoaprendizaje: tuple[str, ...] = ()

    @property
    def series_por_ref(self) -> dict[tuple[int, int], str]:
        """``{(pon, onu_id): serial}``, que es como lo consume el inventario."""
        return {(onu.pon, onu.onu_id): onu.numero_serie for onu in self.onus}


@dataclass
class _ONUEnConstruccion:
    """Acumulador mutable: las directivas de una ONU llegan en varias líneas."""

    pon: int
    onu_id: int
    numero_serie: str
    perfil: str = ""
    datos: dict[str, object] = field(default_factory=dict)

    def a_configurada(self) -> ONUConfigurada:
        return ONUConfigurada(
            pon=self.pon,
            onu_id=self.onu_id,
            numero_serie=self.numero_serie,
            perfil=self.perfil,
            descripcion=str(self.datos.get("descripcion", "")),
            perfil_dba=str(self.datos.get("perfil_dba", "")),
            servicio=str(self.datos.get("servicio", "")),
            vlan=self.datos.get("vlan"),  # type: ignore[arg-type]
            trafico_subida=str(self.datos.get("trafico_subida", "")),
            trafico_bajada=str(self.datos.get("trafico_bajada", "")),
        )


def parsear_running_config(texto: str) -> ConfiguracionOLT:
    """Interpreta la configuración en vivo del equipo.

    Es tolerante por diseño: una línea que no se reconoce se ignora en vez de
    hacer fallar la lectura entera. Un firmware distinto agrega directivas que
    este parser no conoce, y perder el inventario completo de 284 ONU por una
    línea nueva sería el peor de los intercambios.
    """
    onus: dict[tuple[int, int], _ONUEnConstruccion] = {}
    perfiles_dba: list[PerfilDBAConfigurado] = []
    perfiles_trafico: list[PerfilTraficoConfigurado] = []
    puertos: list[str] = []
    sin_autoaprendizaje: list[str] = []
    vlans: set[int] = set()
    identidad: dict[str, str] = {}

    pon_actual: int | None = None
    nombre_pon: str = ""
    dba_pendiente: PerfilDBAConfigurado | None = None

    for linea_cruda in texto.splitlines():
        linea = linea_cruda.strip()
        if not linea:
            continue

        for clave, patron in IDENTIDAD.items():
            if clave not in identidad and (encontrado := patron.match(linea)):
                identidad[clave] = encontrado.group("valor")

        if interfaz := INTERFAZ_PON.match(linea):
            ranura, puerto = interfaz.group(1), interfaz.group(2)
            nombre_pon = f"{ranura}/{puerto}"
            pon_actual = int(puerto)
            if nombre_pon not in puertos:
                puertos.append(nombre_pon)
            continue

        if OTRA_INTERFAZ.match(linea) or linea.lower() == "exit":
            pon_actual = None
            continue

        if dba_pendiente is not None:
            if cuerpo := CUERPO_DBA.match(linea):
                perfiles_dba.append(_completar_dba(dba_pendiente, cuerpo))
                dba_pendiente = None
                continue
            perfiles_dba.append(dba_pendiente)
            dba_pendiente = None

        if perfil := PERFIL_DBA.match(linea):
            dba_pendiente = PerfilDBAConfigurado(
                identificador=int(perfil.group("id")), nombre=perfil.group("nombre")
            )
            continue

        if perfil := PERFIL_TRAFICO.match(linea):
            perfiles_trafico.append(
                PerfilTraficoConfigurado(
                    identificador=int(perfil.group("id")), nombre=perfil.group("nombre")
                )
            )
            continue

        if pon_actual is None:
            if rango := DECLARACION_VLAN.match(linea):
                desde = int(rango.group("desde"))
                hasta = int(rango.group("hasta") or desde)
                vlans.update(range(desde, hasta + 1))
            continue

        # --- dentro de un puerto PON ---
        if SIN_AUTOAPRENDIZAJE.match(linea):
            if nombre_pon not in sin_autoaprendizaje:
                sin_autoaprendizaje.append(nombre_pon)
            continue

        if alta := ONU_ALTA.match(linea):
            clave = (pon_actual, int(alta.group("onu")))
            onus[clave] = _ONUEnConstruccion(
                pon=pon_actual,
                onu_id=int(alta.group("onu")),
                numero_serie=alta.group("serie"),
                perfil=alta.group("perfil"),
            )
            continue

        _aplicar_directiva(onus, pon_actual, linea)

    if dba_pendiente is not None:
        perfiles_dba.append(dba_pendiente)

    return ConfiguracionOLT(
        nombre_equipo=identidad.get("hostname", ""),
        firmware=identidad.get("firmware", ""),
        puertos_pon=tuple(puertos),
        onus=tuple(constructor.a_configurada() for constructor in onus.values()),
        perfiles_dba=tuple(perfiles_dba),
        perfiles_trafico=tuple(perfiles_trafico),
        vlans=tuple(sorted(vlans)),
        pon_sin_autoaprendizaje=tuple(sin_autoaprendizaje),
    )


def _completar_dba(base: PerfilDBAConfigurado, cuerpo: re.Match[str]) -> PerfilDBAConfigurado:
    def entero(grupo: str) -> int | None:
        valor = cuerpo.group(grupo)
        return int(valor) if valor else None

    return PerfilDBAConfigurado(
        identificador=base.identificador,
        nombre=base.nombre,
        tipo=cuerpo.group("tipo") or "",
        fijo_kbps=entero("fijo"),
        asegurado_kbps=entero("asegurado"),
        maximo_kbps=entero("maximo"),
    )


def _aplicar_directiva(
    onus: dict[tuple[int, int], _ONUEnConstruccion], pon: int, linea: str
) -> None:
    """Suma a una ONU ya dada de alta lo que dice una línea suya.

    Si la ONU no fue declarada antes con ``onu add``, la línea se descarta: sin
    número de serie no hay ONU que completar, y inventar una a partir de una
    directiva suelta daría una entrada fantasma.
    """
    for patron, aplicar in _DIRECTIVAS:
        if encontrado := patron.match(linea):
            constructor = onus.get((pon, int(encontrado.group("onu"))))
            if constructor is not None:
                aplicar(constructor.datos, encontrado)
            return


def _guardar_descripcion(datos: dict[str, object], encontrado: re.Match[str]) -> None:
    datos["descripcion"] = encontrado.group("descripcion")


def _guardar_dba(datos: dict[str, object], encontrado: re.Match[str]) -> None:
    datos["perfil_dba"] = encontrado.group("dba")


def _guardar_trafico(datos: dict[str, object], encontrado: re.Match[str]) -> None:
    datos["trafico_subida"] = encontrado.group("subida")
    datos["trafico_bajada"] = encontrado.group("bajada")


def _guardar_servicio(datos: dict[str, object], encontrado: re.Match[str]) -> None:
    datos["servicio"] = encontrado.group("servicio")
    datos["vlan"] = int(encontrado.group("vlan"))


_DIRECTIVAS = (
    (ONU_DESCRIPCION, _guardar_descripcion),
    (ONU_TCONT, _guardar_dba),
    (ONU_TRAFICO, _guardar_trafico),
    (ONU_SERVICIO, _guardar_servicio),
)
