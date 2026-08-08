"""La secuencia de comandos que da de alta una ONU en una VSOL V1600G1.

No está inventada ni sacada de un manual: es **la que el propio equipo escribe**
en su ``show running-config`` para cada una de las 284 ONU ya autorizadas de la
OLT de ERLAN. Se leyó de ahí, se comparó entre puertos y clientes, y se armó el
molde.

Una ONU dada de alta se ve así en la configuración::

    interface gpon 0/7
    onu add 1 profile V2802GW sn GPON00225D48
    onu 1 desc GPON0/7:1_032074
    onu 1 tcont 1 name Internet dba Internet
    onu 1 gemport 1 tcont 1 gemport_name Internet
    onu 1 gemport 1 traffic-limit upstream 300M-Pymes-UP downstream 300M-Pymes-Dowm
    onu 1 service Internet gemport 1 vlan 1001
    onu 1 service-port 1 gemport 1 uservlan 1001 vlan 1001
    onu 1 service-port 1 description Internet
    onu 1 portvlan veip 1 mode transparent

Este módulo sólo arma el texto. Enviarlo o no es decisión de la capa de arriba,
y por defecto **no se envía**.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ...core.errors import ErrorValidacion

#: Rango de índices de ONU que admite un puerto PON de este equipo, según su
#: propia ayuda: ``<1-128>  Input onu id number, 1-128``.
INDICE_MINIMO, INDICE_MAXIMO = 1, 128

#: Los seriales que usa el parque de ERLAN: ``GPON…``, ``VSOL…``, ``MONU…``.
#: Se exige la forma para no mandar al equipo un serial mal tipeado por el
#: técnico, que es de donde viene el dato.
NUMERO_SERIE = re.compile(r"^[A-Z]{4}[0-9A-F]{8}$", re.IGNORECASE)

#: Nombres de perfil, VLAN y descripciones: sin espacios ni caracteres que la
#: CLI pueda interpretar. Un espacio de más parte el comando en dos.
NOMBRE = re.compile(r"^[\w.\-]{1,32}$")
DESCRIPCION = re.compile(r"^[\w.\-:/]{1,63}$")


@dataclass(frozen=True, slots=True)
class SolicitudAlta:
    """Todo lo que hace falta para dar de alta una ONU.

    Los nombres de perfil y de plan son los que el equipo ya tiene definidos: se
    eligen de los que devuelve el inventario, no se inventan acá.
    """

    pon: int
    onu_id: int
    numero_serie: str
    perfil_onu: str
    descripcion: str = ""
    perfil_dba: str = "Internet"
    nombre_tcont: str = "Internet"
    servicio: str = "Internet"
    trafico_subida: str = ""
    trafico_bajada: str = ""
    vlan: int = 1001
    ranura: int = 0

    def validar(self) -> None:
        """Rechaza todo lo dudoso **antes** de que salga un comando al equipo.

        Es la barrera que importa: un comando mal formado en modo configuración
        no devuelve un error prolijo, deja una ONU a medio dar de alta.
        """
        if not INDICE_MINIMO <= self.onu_id <= INDICE_MAXIMO:
            raise ErrorValidacion(
                f"El índice de ONU debe estar entre {INDICE_MINIMO} y {INDICE_MAXIMO}, "
                f"y se pidió {self.onu_id}"
            )
        if not NUMERO_SERIE.match(self.numero_serie):
            raise ErrorValidacion(
                f"Número de serie con forma inesperada: {self.numero_serie!r}. "
                "Se espera algo como GPON002E64F8 (cuatro letras y ocho dígitos hexadecimales)."
            )
        for etiqueta, valor in (
            ("perfil de ONU", self.perfil_onu),
            ("perfil DBA", self.perfil_dba),
            ("nombre de tcont", self.nombre_tcont),
            ("servicio", self.servicio),
        ):
            if not NOMBRE.match(valor):
                raise ErrorValidacion(f"El {etiqueta} {valor!r} tiene caracteres no admitidos")

        for etiqueta, valor in (
            ("plan de subida", self.trafico_subida),
            ("plan de bajada", self.trafico_bajada),
        ):
            if valor and not NOMBRE.match(valor):
                raise ErrorValidacion(f"El {etiqueta} {valor!r} tiene caracteres no admitidos")

        if self.descripcion and not DESCRIPCION.match(self.descripcion):
            raise ErrorValidacion(
                f"La descripción {self.descripcion!r} tiene caracteres no admitidos. "
                "Se admiten letras, números, punto, guion, dos puntos y barra."
            )
        if not 1 <= self.vlan <= 4094:
            raise ErrorValidacion(f"VLAN fuera de rango: {self.vlan}")

    @property
    def descripcion_efectiva(self) -> str:
        """La descripción a aplicar, con el formato que ya usa el parque.

        En ERLAN todas siguen la forma ``GPON0/7:1_032074``: puerto, índice y
        número de cliente. Si no se indica otra, se arma la parte que el equipo
        conoce y queda coherente con las 284 que ya están.
        """
        return self.descripcion or f"GPON{self.ranura}/{self.pon}:{self.onu_id}"


def secuencia_alta(solicitud: SolicitudAlta) -> tuple[str, ...]:
    """Arma los comandos del alta, en orden. **No envía nada.**"""
    solicitud.validar()

    onu = solicitud.onu_id
    comandos = [
        "configure terminal",
        f"interface gpon {solicitud.ranura}/{solicitud.pon}",
        f"onu add {onu} profile {solicitud.perfil_onu} sn {solicitud.numero_serie}",
        f"onu {onu} desc {solicitud.descripcion_efectiva}",
        f"onu {onu} tcont 1 name {solicitud.nombre_tcont} dba {solicitud.perfil_dba}",
        f"onu {onu} gemport 1 tcont 1 gemport_name {solicitud.nombre_tcont}",
    ]

    # El límite de tráfico es opcional: sin plan asignado, la ONU queda con el
    # ancho de banda del perfil DBA y nada más. Mandar el comando con nombres
    # vacíos sería mandarlo mal.
    if solicitud.trafico_subida and solicitud.trafico_bajada:
        comandos.append(
            f"onu {onu} gemport 1 traffic-limit "
            f"upstream {solicitud.trafico_subida} downstream {solicitud.trafico_bajada}"
        )

    comandos += [
        f"onu {onu} service {solicitud.servicio} gemport 1 vlan {solicitud.vlan}",
        f"onu {onu} service-port 1 gemport 1 uservlan {solicitud.vlan} vlan {solicitud.vlan}",
        f"onu {onu} service-port 1 description {solicitud.servicio}",
        f"onu {onu} portvlan veip 1 mode transparent",
        "end",
    ]
    return tuple(comandos)


def secuencia_baja(pon: int, onu_id: int, ranura: int = 0) -> tuple[str, ...]:
    """Comandos para dar de baja una ONU.

    ``no onu <id>`` es la forma que declara la ayuda del equipo::

        no onu
          <1-128>     Specify onuid index num.
    """
    if not INDICE_MINIMO <= onu_id <= INDICE_MAXIMO:
        raise ErrorValidacion(f"Índice de ONU fuera de rango: {onu_id}")
    return (
        "configure terminal",
        f"interface gpon {ranura}/{pon}",
        f"no onu {onu_id}",
        "end",
    )


def primer_indice_libre(ocupados: set[int]) -> int:
    """Elige el índice más bajo que esté libre en el puerto.

    Reusar los huecos es lo que hace el operador a mano y lo que mantiene el
    puerto ordenado. En el PON 1 de ERLAN, por ejemplo, el 29 quedó libre entre
    el 28 y el 30.
    """
    for indice in range(INDICE_MINIMO, INDICE_MAXIMO + 1):
        if indice not in ocupados:
            return indice
    raise ErrorValidacion(
        f"El puerto PON no tiene índices libres: están ocupados los "
        f"{INDICE_MINIMO} a {INDICE_MAXIMO}."
    )
