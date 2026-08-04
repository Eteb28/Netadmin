"""Generador del parque simulado.

Reproduce, con números tomados de las OLT reales de ERLAN, un escenario lo
bastante parecido como para que los servicios y la interfaz se prueben en
serio: 8 puertos PON, 473 ONU, la misma proporción de ONU en línea y la misma
mezcla de motivos de caída (``Power Off`` contra ``Onu Los``).

Es determinista: con la misma semilla sale exactamente el mismo parque. Un
simulador que cambia entre corridas no sirve para hacer tests que fallen
siempre que deban fallar.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from ...core.enums import EstadoONU, Fabricante, ModoServicio, MotivoCaida
from ...core.models import (
    ONU,
    VLAN,
    InfoSistema,
    LecturaOptica,
    ONUNoAutorizada,
    PerfilDBA,
    Perfiles,
    PerfilLinea,
    PerfilServicio,
    PuertoPON,
    RefONU,
    ServicePort,
)

# Proporciones medidas en el parque real (ver docs/00-investigacion.md, 2.1):
# 473 ONU, 386 en línea; entre las caídas, 225 por corte de luz y 174 por
# pérdida de señal.
PROPORCION_EN_LINEA = 386 / 473
PROPORCION_APAGADO = 225 / (225 + 174)

# Rango de potencias observado: de −32,22 dBm (la peor) a −1,57 dBm (una ONU
# saturada que el sistema anterior contaba como "óptima").
RX_MINIMO_DBM = -32.22
RX_MAXIMO_DBM = -1.57


@dataclass
class ONUSimulada:
    """Estado mutable de una ONU dentro del simulador."""

    ref: RefONU
    numero_serie: str
    nombre: str
    modelo: str
    firmware: str
    estado: EstadoONU
    motivo_caida: MotivoCaida
    modo_servicio: ModoServicio
    rx_onu_dbm: float | None
    tx_onu_dbm: float | None
    rx_olt_dbm: float | None
    tx_olt_dbm: float
    temperatura_celsius: float
    voltaje_voltios: float
    distancia_metros: int
    perfil_linea: str
    perfil_servicio: str
    vlan: int
    ssid: str = ""
    clave_wifi: str = ""
    usuario_pppoe: str = ""
    clave_pppoe: str = ""
    ultima_subida: datetime | None = None
    ultima_bajada: datetime | None = None
    reinicios: int = 0

    def a_modelo(self, olt_id: int | None) -> ONU:
        return ONU(
            olt_id=olt_id,
            ref=self.ref,
            numero_serie=self.numero_serie,
            nombre=self.nombre,
            modelo=self.modelo,
            firmware=self.firmware,
            estado=self.estado,
            motivo_caida=self.motivo_caida,
            modo_servicio=self.modo_servicio,
            autorizada=True,
            distancia_metros=self.distancia_metros,
            perfil_linea=self.perfil_linea,
            perfil_servicio=self.perfil_servicio,
            vlan=self.vlan,
            ultima_subida=self.ultima_subida,
            ultima_bajada=self.ultima_bajada,
        )

    def a_lectura(self, momento: datetime) -> LecturaOptica:
        return LecturaOptica(
            ref=self.ref,
            rx_onu_dbm=self.rx_onu_dbm,
            tx_onu_dbm=self.tx_onu_dbm,
            rx_olt_dbm=self.rx_olt_dbm,
            tx_olt_dbm=self.tx_olt_dbm,
            temperatura_celsius=self.temperatura_celsius,
            voltaje_voltios=self.voltaje_voltios,
            distancia_metros=self.distancia_metros,
            leido_en=momento,
        )


@dataclass
class ParqueSimulado:
    """Todo el estado de una OLT simulada."""

    info: InfoSistema
    puertos: list[PuertoPON]
    onus: dict[RefONU, ONUSimulada]
    no_autorizadas: list[ONUNoAutorizada] = field(default_factory=list)
    perfiles: Perfiles = field(default_factory=Perfiles)
    running_config: str = ""

    def siguiente_id_libre(self, pon: int) -> int:
        usados = {ref.onu_id for ref in self.onus if ref.pon == pon}
        candidato = 1
        while candidato in usados:
            candidato += 1
        return candidato


def _serie(azar: random.Random, prefijo: str = "VSOL") -> str:
    return prefijo + "".join(azar.choice("0123456789ABCDEF") for _ in range(8))


def _potencia_rx(azar: random.Random) -> float:
    """Genera una potencia con forma parecida a la real.

    La mayoría cae en el rango sano; una minoría queda floja, y unas pocas
    quedan saturadas. Esa cola alta es la que hace falta para que los tests de
    la alarma de saturación tengan con qué dispararse.
    """
    sorteo = azar.random()
    if sorteo < 0.03:
        return round(azar.uniform(-7.5, RX_MAXIMO_DBM), 2)
    if sorteo < 0.10:
        return round(azar.uniform(RX_MINIMO_DBM, -27.5), 2)
    return round(azar.uniform(-26.5, -15.0), 2)


def generar_parque(
    *,
    semilla: int = 20260804,
    cantidad_pon: int = 8,
    cantidad_onus: int = 473,
    cantidad_no_autorizadas: int = 3,
    modelo: str = "V1600G1B",
    momento: datetime | None = None,
) -> ParqueSimulado:
    """Construye un parque completo y determinista."""
    azar = random.Random(semilla)
    ahora = momento or datetime(2026, 8, 4, 12, 0, tzinfo=UTC)

    info = InfoSistema(
        modelo=modelo,
        fabricante=Fabricante.SIMULADO,
        firmware="V2.1.7_2023",
        hardware="R1.0",
        numero_serie=_serie(azar, "OLT"),
        mac="00:1E:C0:" + ":".join(f"{azar.randrange(256):02X}" for _ in range(3)),
        nombre_equipo="OLT-SIMULADA",
        uptime_segundos=azar.randrange(86_400, 30 * 86_400),
        cpu_porcentaje=round(azar.uniform(5, 35), 1),
        memoria_porcentaje=round(azar.uniform(30, 65), 1),
        temperatura_celsius=round(azar.uniform(38, 45), 1),
        leido_en=ahora,
    )

    puertos = [
        PuertoPON(
            indice=indice,
            nombre=f"GPON0/{indice}",
            descripcion=f"Puerto PON {indice}",
            habilitado=True,
            operativo=True,
            potencia_tx_dbm=round(azar.uniform(2.5, 5.0), 2),
            temperatura_celsius=round(azar.uniform(39, 42), 1),
            voltaje_voltios=round(azar.uniform(3.25, 3.35), 2),
            corriente_ma=round(azar.uniform(15, 25), 2),
            leido_en=ahora,
        )
        for indice in range(1, cantidad_pon + 1)
    ]
    tx_por_pon = {p.indice: (p.potencia_tx_dbm or 3.0) for p in puertos}

    onus: dict[RefONU, ONUSimulada] = {}
    for numero in range(cantidad_onus):
        pon = numero % cantidad_pon + 1
        onu_id = numero // cantidad_pon + 1
        ref = RefONU(pon=pon, onu_id=onu_id)
        en_linea = azar.random() < PROPORCION_EN_LINEA

        if en_linea:
            estado = EstadoONU.EN_LINEA
            motivo = MotivoCaida.NINGUNO
            rx = _potencia_rx(azar)
            tx = round(rx + azar.uniform(22, 28), 2)
            rx_olt = round(rx + azar.uniform(-1.5, 1.5), 2)
        else:
            estado = EstadoONU.FUERA_DE_LINEA
            motivo = (
                MotivoCaida.APAGADO
                if azar.random() < PROPORCION_APAGADO
                else MotivoCaida.PERDIDA_SENAL
            )
            # Una ONU caída no reporta potencia. Devolver 0 sería inventar un
            # dato: se devuelve None y el histórico registra la ausencia.
            rx = tx = rx_olt = None

        cliente = 1000 + numero
        onus[ref] = ONUSimulada(
            ref=ref,
            numero_serie=_serie(azar),
            nombre=f"CLI{cliente}-CDO{pon}-NAP{onu_id:02d}",
            modelo=azar.choice(("HG323", "V2802RW", "V2801F")),
            firmware=azar.choice(("V1.2.3", "V1.3.0", "V2.0.1")),
            estado=estado,
            motivo_caida=motivo,
            modo_servicio=azar.choice((ModoServicio.BRIDGE, ModoServicio.ROUTER)),
            rx_onu_dbm=rx,
            tx_onu_dbm=tx,
            rx_olt_dbm=rx_olt,
            tx_olt_dbm=tx_por_pon[pon],
            temperatura_celsius=round(azar.uniform(35, 55), 1),
            voltaje_voltios=round(azar.uniform(3.2, 3.4), 2),
            distancia_metros=azar.randrange(150, 12_000, 50),
            perfil_linea="linea_100m",
            perfil_servicio="internet",
            vlan=azar.choice((2001, 2026, 2542)),
            ssid=f"ERLAN-{cliente}",
            clave_wifi="clave-inicial",
            usuario_pppoe=f"cliente{cliente}",
            clave_pppoe="pppoe-inicial",
            ultima_subida=ahora - timedelta(seconds=azar.randrange(3600, 600_000)),
            ultima_bajada=(
                None if en_linea else ahora - timedelta(seconds=azar.randrange(60, 90_000))
            ),
        )

    no_autorizadas = [
        ONUNoAutorizada(
            numero_serie=_serie(azar),
            pon=azar.randrange(1, cantidad_pon + 1),
            modelo="HG323",
            fabricante_onu="VSOL",
            detectada_en=ahora - timedelta(minutes=azar.randrange(1, 240)),
        )
        for _ in range(cantidad_no_autorizadas)
    ]

    perfiles = Perfiles(
        dba=(
            PerfilDBA(
                nombre="dba_100m",
                identificador_equipo="1",
                tipo="type4",
                ancho_banda_maximo_kbps=102_400,
            ),
            PerfilDBA(
                nombre="dba_300m",
                identificador_equipo="2",
                tipo="type4",
                ancho_banda_maximo_kbps=307_200,
            ),
        ),
        linea=(
            PerfilLinea(
                nombre="linea_100m",
                identificador_equipo="1",
                perfil_dba="dba_100m",
                cantidad_tcont=1,
                cantidad_gemport=1,
            ),
        ),
        servicio=(PerfilServicio(nombre="internet", identificador_equipo="1", vlan=2026),),
        vlans=(
            VLAN(vlan_id=2001, nombre="gestion"),
            VLAN(vlan_id=2026, nombre="internet"),
            VLAN(vlan_id=2542, nombre="corporativo"),
        ),
        service_ports=(
            ServicePort(
                indice=1,
                ref_onu=RefONU(1, 1),
                gemport=1,
                vlan_usuario=2001,
                vlan_servicio=2026,
                perfil_trafico="dba_100m",
            ),
        ),
    )

    running_config = "\n".join(
        [
            "!",
            f"hostname {info.nombre_equipo}",
            f"! modelo {info.modelo} firmware {info.firmware}",
            "!",
            *[f"interface {p.nombre}\n no shutdown\n!" for p in puertos],
            "line vty 0 4",
            " exec-timeout 30 0",
            "!",
            "end",
        ]
    )

    return ParqueSimulado(
        info=info,
        puertos=puertos,
        onus=onus,
        no_autorizadas=no_autorizadas,
        perfiles=perfiles,
        running_config=running_config,
    )
