"""Entidades del dominio GPON.

Todas son ``dataclass`` inmutables (``frozen=True``): un modelo que representa
una lectura de un equipo no debe poder mutar a mitad de camino entre el driver
y la base de datos. Para derivar un valor cambiado se usa ``dataclasses.replace``.

Estos modelos son **propios del módulo**. Pucará, cuando integre, adaptará
estos objetos a los suyos en su propia capa; el módulo no conoce Pucará.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .enums import (
    Capacidad,
    EstadoAlarma,
    EstadoOLT,
    EstadoONU,
    Fabricante,
    Granularidad,
    ModoServicio,
    MotivoCaida,
    NivelSincronizacion,
    ResultadoSincronizacion,
    Severidad,
    TipoAlarma,
    TipoEvento,
    TipoMetrica,
    TipoOperacion,
)

# --- Identificación -------------------------------------------------------


@dataclass(frozen=True, slots=True, order=True)
class RefONU:
    """Dirección de una ONU dentro de su OLT.

    Es la única forma de nombrar una ONU en la interfaz de drivers. Cada driver
    la traduce a la sintaxis de su fabricante: ``GPON0/2:15`` en VSOL,
    ``gpon-onu_1/2/2:15`` en ZTE. El núcleo nunca ve esas cadenas.
    """

    pon: int
    onu_id: int

    def __str__(self) -> str:
        return f"{self.pon}:{self.onu_id}"

    @classmethod
    def desde_texto(cls, texto: str) -> RefONU:
        """Reconstruye una referencia desde ``"<pon>:<onu>"``."""
        pon, _, onu = texto.partition(":")
        return cls(pon=int(pon), onu_id=int(onu))


# --- Credenciales y conexión ---------------------------------------------


@dataclass(frozen=True, slots=True)
class CredencialesOLT:
    """Datos de acceso a una OLT.

    En base de datos se guardan cifrados (riesgo R8). Este objeto sólo existe
    descifrado en memoria y durante el tiempo de una operación.
    """

    usuario: str = ""
    password: str = ""
    password_enable: str = ""
    comunidad_snmp_lectura: str = "public"
    comunidad_snmp_escritura: str = ""
    puerto_snmp: int = 161
    puerto_telnet: int = 23
    puerto_ssh: int = 22

    def __repr__(self) -> str:  # pragma: no cover - trivial
        # Nunca exponer secretos en logs ni en trazas de excepción.
        return (
            f"CredencialesOLT(usuario={self.usuario!r}, password=***, "
            f"comunidad_snmp_lectura=***, puerto_snmp={self.puerto_snmp})"
        )


# --- OLT ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class InfoSistema:
    """Identidad y salud de la OLT, tal como la reporta el equipo."""

    modelo: str = ""
    fabricante: Fabricante = Fabricante.SIMULADO
    firmware: str = ""
    hardware: str = ""
    numero_serie: str = ""
    mac: str = ""
    nombre_equipo: str = ""
    uptime_segundos: int | None = None
    cpu_porcentaje: float | None = None
    memoria_porcentaje: float | None = None
    temperatura_celsius: float | None = None
    leido_en: datetime | None = None


@dataclass(frozen=True, slots=True)
class OLT:
    """Una OLT administrada por el módulo."""

    id: int | None = None
    nombre: str = ""
    host: str = ""
    fabricante: Fabricante = Fabricante.SIMULADO
    modelo: str = ""
    firmware: str = ""
    numero_serie: str = ""
    mac: str = ""
    descripcion: str = ""
    estado: EstadoOLT = EstadoOLT.DESCONOCIDO
    activa: bool = True
    cantidad_pon: int = 0
    cantidad_onus: int = 0
    uptime_segundos: int | None = None
    ultima_sincronizacion: datetime | None = None
    creada_en: datetime | None = None
    actualizada_en: datetime | None = None


@dataclass(frozen=True, slots=True)
class PuertoPON:
    """Puerto PON (interfaz óptica) de una OLT."""

    id: int | None = None
    olt_id: int | None = None
    indice: int = 0
    nombre: str = ""
    descripcion: str = ""
    habilitado: bool = True
    operativo: bool = True
    cantidad_onus: int = 0
    cantidad_onus_en_linea: int = 0
    potencia_tx_dbm: float | None = None
    temperatura_celsius: float | None = None
    voltaje_voltios: float | None = None
    corriente_ma: float | None = None
    leido_en: datetime | None = None


# --- ONU ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ONU:
    """Una ONU/ONT registrada en una OLT."""

    id: int | None = None
    olt_id: int | None = None
    ref: RefONU = field(default_factory=lambda: RefONU(0, 0))
    numero_serie: str = ""
    nombre: str = ""
    descripcion: str = ""
    modelo: str = ""
    fabricante_onu: str = ""
    firmware: str = ""
    estado: EstadoONU = EstadoONU.DESCONOCIDO
    motivo_caida: MotivoCaida = MotivoCaida.DESCONOCIDO
    modo_servicio: ModoServicio = ModoServicio.DESCONOCIDO
    autorizada: bool = True
    distancia_metros: int | None = None
    perfil_linea: str = ""
    perfil_servicio: str = ""
    vlan: int | None = None
    ultima_subida: datetime | None = None
    ultima_bajada: datetime | None = None
    tiempo_en_estado: str = ""
    primera_vez_vista: datetime | None = None
    ultima_vez_vista: datetime | None = None

    @property
    def pon(self) -> int:
        return self.ref.pon

    @property
    def onu_id(self) -> int:
        return self.ref.onu_id


@dataclass(frozen=True, slots=True)
class ONUNoAutorizada:
    """ONU detectada por la OLT pero todavía sin dar de alta.

    En VSOL sólo se obtiene por CLI: el número de serie **no existe por SNMP**
    (verificado, ver docs/00-investigacion.md sección 2.2).
    """

    numero_serie: str
    pon: int
    modelo: str = ""
    fabricante_onu: str = ""
    detectada_en: datetime | None = None


# --- Telemetría -----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LecturaOptica:
    """Potencias ópticas de un enlace ONU↔OLT, en dBm."""

    ref: RefONU
    rx_onu_dbm: float | None = None
    tx_onu_dbm: float | None = None
    rx_olt_dbm: float | None = None
    tx_olt_dbm: float | None = None
    temperatura_celsius: float | None = None
    voltaje_voltios: float | None = None
    corriente_ma: float | None = None
    distancia_metros: int | None = None
    leido_en: datetime | None = None

    @property
    def perdida_optica_db(self) -> float | None:
        """Atenuación del enlace descendente (TX de la OLT − RX de la ONU)."""
        if self.tx_olt_dbm is None or self.rx_onu_dbm is None:
            return None
        return round(self.tx_olt_dbm - self.rx_onu_dbm, 2)


@dataclass(frozen=True, slots=True)
class LecturaTrafico:
    """Contadores de tráfico de una interfaz.

    Son acumulados: el módulo guarda el valor crudo y calcula tasas por
    diferencia entre lecturas. Nunca se guarda una tasa sin su par de crudos.
    """

    octetos_entrada: int = 0
    octetos_salida: int = 0
    paquetes_entrada: int = 0
    paquetes_salida: int = 0
    errores_entrada: int = 0
    errores_salida: int = 0
    leido_en: datetime | None = None


@dataclass(frozen=True, slots=True)
class Metrica:
    """Un punto de una serie temporal.

    ``entidad`` identifica a qué se refiere: ``"olt"``, ``"pon"`` o ``"onu"``;
    ``entidad_id`` es la clave interna correspondiente.
    """

    id: int | None = None
    olt_id: int | None = None
    entidad: str = "olt"
    entidad_id: int | None = None
    tipo: TipoMetrica = TipoMetrica.RX_ONU
    valor: float = 0.0
    granularidad: Granularidad = Granularidad.FINA
    muestras: int = 1
    valor_minimo: float | None = None
    valor_maximo: float | None = None
    registrada_en: datetime | None = None


# --- Perfiles y servicios -------------------------------------------------


@dataclass(frozen=True, slots=True)
class PerfilDBA:
    """Perfil de asignación dinámica de ancho de banda."""

    id: int | None = None
    olt_id: int | None = None
    nombre: str = ""
    identificador_equipo: str = ""
    tipo: str = ""
    ancho_banda_fijo_kbps: int | None = None
    ancho_banda_asegurado_kbps: int | None = None
    ancho_banda_maximo_kbps: int | None = None


@dataclass(frozen=True, slots=True)
class PerfilTrafico:
    """Perfil de límite de tráfico: el "plan" que se le aplica a una ONU.

    Se guardan porque elegir uno que no existe es un alta que el equipo rechaza
    a mitad de camino. En la OLT de ERLAN hay 26, con nombres que ni siquiera
    son consistentes entre sí —``100M-Dom-DOW``, ``100M-Pymes-Dowm``,
    ``50M-PYMES-DOW``—, así que escribirlos a mano es pedir problemas.
    """

    id: int | None = None
    olt_id: int | None = None
    nombre: str = ""
    identificador_equipo: str = ""


@dataclass(frozen=True, slots=True)
class PerfilLinea:
    """Perfil de línea (tcont/gemport) aplicable a una ONU."""

    id: int | None = None
    olt_id: int | None = None
    nombre: str = ""
    identificador_equipo: str = ""
    perfil_dba: str = ""
    cantidad_tcont: int = 0
    cantidad_gemport: int = 0


@dataclass(frozen=True, slots=True)
class PerfilServicio:
    """Perfil de servicio (mapeo de VLAN y puertos del CPE)."""

    id: int | None = None
    olt_id: int | None = None
    nombre: str = ""
    identificador_equipo: str = ""
    vlan: int | None = None


@dataclass(frozen=True, slots=True)
class VLAN:
    id: int | None = None
    olt_id: int | None = None
    vlan_id: int = 0
    nombre: str = ""
    descripcion: str = ""


@dataclass(frozen=True, slots=True)
class ServicePort:
    """Asociación gemport ↔ VLAN de usuario ↔ VLAN de servicio."""

    id: int | None = None
    olt_id: int | None = None
    indice: int = 0
    ref_onu: RefONU | None = None
    gemport: int | None = None
    vlan_usuario: int | None = None
    vlan_servicio: int | None = None
    perfil_trafico: str = ""


@dataclass(frozen=True, slots=True)
class Perfiles:
    """Todo lo que una OLT tiene definido, leído de una sola pasada."""

    dba: tuple[PerfilDBA, ...] = ()
    trafico: tuple[PerfilTrafico, ...] = ()
    linea: tuple[PerfilLinea, ...] = ()
    servicio: tuple[PerfilServicio, ...] = ()
    vlans: tuple[VLAN, ...] = ()
    service_ports: tuple[ServicePort, ...] = ()


# --- Configuración del CPE ------------------------------------------------


@dataclass(frozen=True, slots=True)
class ConfigWiFi:
    """Parámetros WiFi de un CPE."""

    ssid: str = ""
    password: str = ""
    habilitado: bool = True
    banda: str = "2.4G"
    canal: int | None = None
    oculto: bool = False

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"ConfigWiFi(ssid={self.ssid!r}, password=***, banda={self.banda!r})"


@dataclass(frozen=True, slots=True)
class CredencialPPPoE:
    usuario: str = ""
    password: str = ""

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"CredencialPPPoE(usuario={self.usuario!r}, password=***)"


@dataclass(frozen=True, slots=True)
class SolicitudAutorizacion:
    """Intención del operador de poner una ONU en servicio.

    Deliberadamente expresa la *intención*, no una secuencia de comandos: en
    ZTE significa dar de alta explícitamente por serial, y en VSOL confirmar y
    configurar la que ya entró sola por ``auto-learn``. Cada driver lo resuelve
    como puede en su equipo (ver 00-investigacion.md, sección 3).
    """

    numero_serie: str
    pon: int
    onu_id: int | None = None
    nombre: str = ""
    descripcion: str = ""
    modelo_onu: str = ""
    perfil_linea: str = ""
    perfil_servicio: str = ""
    perfil_dba: str = ""
    vlan: int | None = None
    vlan_usuario: int | None = None
    modo_servicio: ModoServicio = ModoServicio.DESCONOCIDO
    pppoe: CredencialPPPoE | None = None
    wifi: ConfigWiFi | None = None


@dataclass(frozen=True, slots=True)
class ClienteConectado:
    """Dispositivo visto detrás del CPE."""

    mac: str = ""
    ip: str = ""
    nombre: str = ""
    interfaz: str = ""


@dataclass(frozen=True, slots=True)
class PuertoLAN:
    numero: int = 0
    habilitado: bool = True
    enlace: bool = False
    velocidad_mbps: int | None = None


# --- Resultado de operaciones --------------------------------------------


@dataclass(frozen=True, slots=True)
class ResultadoOperacion:
    """Desenlace auditable de una operación de escritura.

    Nunca ``bool``: una operación de aprovisionamiento debe poder explicarse
    después. Qué comandos se enviaron, qué contestó el equipo, si fue real o
    simulada. Esto es lo que se persiste en la tabla ``operaciones``.
    """

    ok: bool
    tipo: TipoOperacion
    comandos_enviados: tuple[str, ...] = ()
    salida_cruda: str = ""
    error: str | None = None
    simulado: bool = True
    olt_id: int | None = None
    ref_onu: RefONU | None = None
    duracion_ms: int | None = None
    ejecutada_en: datetime | None = None

    def __post_init__(self) -> None:
        if self.ok and self.error:
            raise ValueError("Un resultado exitoso no puede llevar error")
        if not self.ok and not self.error:
            raise ValueError("Un resultado fallido debe explicar el error")


@dataclass(frozen=True, slots=True)
class RespaldoConfiguracion:
    """Copia de la configuración de una OLT."""

    olt_id: int | None = None
    contenido: str = ""
    formato: str = "running-config"
    hash_contenido: str = ""
    tomado_en: datetime | None = None


# --- Alarmas, eventos y auditoría ----------------------------------------


@dataclass(frozen=True, slots=True)
class ReglaAlarma:
    """Condición configurable que genera alarmas."""

    id: int | None = None
    tipo: TipoAlarma = TipoAlarma.ONU_FUERA_DE_LINEA
    nombre: str = ""
    severidad: Severidad = Severidad.ADVERTENCIA
    habilitada: bool = True
    olt_id: int | None = None
    umbral: float | None = None
    umbral_recuperacion: float | None = None
    ocurrencias_para_disparar: int = 1
    silencio_minutos: int = 0

    def __post_init__(self) -> None:
        # La histéresis evita el parpadeo de alarmas alrededor del umbral.
        if self.umbral is not None and self.umbral_recuperacion is None:
            object.__setattr__(self, "umbral_recuperacion", self.umbral)


@dataclass(frozen=True, slots=True)
class Alarma:
    id: int | None = None
    regla_id: int | None = None
    tipo: TipoAlarma = TipoAlarma.ONU_FUERA_DE_LINEA
    severidad: Severidad = Severidad.ADVERTENCIA
    estado: EstadoAlarma = EstadoAlarma.ACTIVA
    olt_id: int | None = None
    entidad: str = "olt"
    entidad_id: int | None = None
    mensaje: str = ""
    valor: float | None = None
    abierta_en: datetime | None = None
    reconocida_en: datetime | None = None
    reconocida_por: str = ""
    resuelta_en: datetime | None = None


@dataclass(frozen=True, slots=True)
class Evento:
    """Cambio detectado por la sincronización. Es el histórico del inventario."""

    id: int | None = None
    tipo: TipoEvento = TipoEvento.CAMBIO_ESTADO
    olt_id: int | None = None
    entidad: str = "onu"
    entidad_id: int | None = None
    ref_onu: RefONU | None = None
    descripcion: str = ""
    valor_anterior: str = ""
    valor_nuevo: str = ""
    ocurrido_en: datetime | None = None


@dataclass(frozen=True, slots=True)
class Operacion:
    """Registro de auditoría de una escritura. Quién, cuándo, qué y con qué respuesta."""

    id: int | None = None
    tipo: TipoOperacion = TipoOperacion.REINICIAR_ONU
    olt_id: int | None = None
    ref_onu: RefONU | None = None
    usuario: str = "sistema"
    ok: bool = False
    simulado: bool = True
    comandos: tuple[str, ...] = ()
    salida: str = ""
    error: str = ""
    duracion_ms: int | None = None
    ejecutada_en: datetime | None = None


@dataclass(frozen=True, slots=True)
class Sincronizacion:
    """Una corrida del proceso de sincronización."""

    id: int | None = None
    olt_id: int | None = None
    nivel: NivelSincronizacion = NivelSincronizacion.RAPIDO
    resultado: ResultadoSincronizacion = ResultadoSincronizacion.COMPLETA
    onus_leidas: int = 0
    onus_esperadas: int | None = None
    eventos_generados: int = 0
    detalle: str = ""
    iniciada_en: datetime | None = None
    finalizada_en: datetime | None = None
    duracion_ms: int | None = None


# --- Descripción de un driver --------------------------------------------


@dataclass(frozen=True, slots=True)
class DescripcionDriver:
    """Metadatos declarativos de un driver, consultables sin instanciarlo."""

    fabricante: Fabricante
    nombre: str
    modelos_soportados: tuple[str, ...]
    capacidades: frozenset[Capacidad]
    protocolos: tuple[str, ...] = ()
    version: str = "1.0"
