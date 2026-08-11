"""Enumeraciones del dominio GPON.

Vocabulario neutro respecto del fabricante. Cada driver traduce los valores
propios de su equipo (números SNMP, cadenas de la CLI) a estos enums; el núcleo
del sistema nunca ve un valor crudo de fabricante.
"""

from __future__ import annotations

from enum import Enum, StrEnum, auto


class Fabricante(StrEnum):
    """Fabricantes soportados. El valor se persiste en base de datos."""

    VSOL = "vsol"
    ZTE = "zte"
    SIMULADO = "simulado"


class Protocolo(StrEnum):
    """Canales de comunicación con la OLT."""

    SNMP = "snmp"
    TELNET = "telnet"
    SSH = "ssh"


class EstadoOLT(StrEnum):
    EN_LINEA = "en_linea"
    FUERA_DE_LINEA = "fuera_de_linea"
    DEGRADADA = "degradada"
    DESCONOCIDO = "desconocido"


class EstadoONU(StrEnum):
    """Estado operativo de una ONU, normalizado entre fabricantes."""

    EN_LINEA = "en_linea"
    FUERA_DE_LINEA = "fuera_de_linea"
    NO_AUTORIZADA = "no_autorizada"
    DESHABILITADA = "deshabilitada"
    DESCONOCIDO = "desconocido"


class MotivoCaida(StrEnum):
    """Por qué se cayó una ONU.

    La distinción entre ``APAGADO`` y ``PERDIDA_SENAL`` es operativamente
    decisiva: la primera es un corte de luz en la casa del cliente (no hay nada
    que hacer), la segunda es un problema de fibra propio (hay que ir).
    Verificado en las OLT de ERLAN: 225 ONU con ``Power Off`` y 174 con
    ``Onu Los`` (ver docs/00-investigacion.md, sección 2.1).
    """

    APAGADO = "apagado"
    PERDIDA_SENAL = "perdida_senal"
    DESACTIVADA_ADMIN = "desactivada_admin"
    NINGUNO = "ninguno"
    DESCONOCIDO = "desconocido"


class ModoServicio(StrEnum):
    """Modo de operación del CPE."""

    BRIDGE = "bridge"
    ROUTER = "router"
    DESCONOCIDO = "desconocido"


class ClasificacionOptica(StrEnum):
    """Clasificación de una potencia óptica de recepción.

    ``SATURADA`` existe desde el primer día por un hallazgo real: una ONU a
    −1,57 dBm que el sistema anterior contaba como "óptima" por mirar sólo el
    extremo bajo. Demasiada luz daña el receptor.
    """

    SATURADA = "saturada"
    OPTIMA = "optima"
    ACEPTABLE = "aceptable"
    BAJA = "baja"
    CRITICA = "critica"
    SIN_LECTURA = "sin_lectura"


class TipoMetrica(StrEnum):
    """Series temporales soportadas por el histórico."""

    RX_ONU = "rx_onu"
    TX_ONU = "tx_onu"
    RX_OLT = "rx_olt"
    TX_OLT = "tx_olt"
    TEMPERATURA_ONU = "temperatura_onu"
    TEMPERATURA_PON = "temperatura_pon"
    VOLTAJE_ONU = "voltaje_onu"
    VOLTAJE_PON = "voltaje_pon"
    DISTANCIA = "distancia"
    CPU = "cpu"
    MEMORIA = "memoria"
    TRAFICO_ENTRADA = "trafico_entrada"
    TRAFICO_SALIDA = "trafico_salida"
    ERRORES = "errores"
    PERDIDA_OPTICA = "perdida_optica"
    ONUS_EN_LINEA = "onus_en_linea"


class Granularidad(StrEnum):
    """Escalones de retención del histórico (ver 01-arquitectura.md, sección 5)."""

    FINA = "fina"
    HORARIA = "horaria"
    DIARIA = "diaria"


class Severidad(StrEnum):
    INFO = "info"
    ADVERTENCIA = "advertencia"
    MAYOR = "mayor"
    CRITICA = "critica"


class EstadoAlarma(StrEnum):
    ACTIVA = "activa"
    RECONOCIDA = "reconocida"
    RESUELTA = "resuelta"


class TipoAlarma(StrEnum):
    """Catálogo de condiciones alarmables."""

    ONU_FUERA_DE_LINEA = "onu_fuera_de_linea"
    ONU_EN_LINEA = "onu_en_linea"
    POTENCIA_BAJA = "potencia_baja"
    POTENCIA_CRITICA = "potencia_critica"
    POTENCIA_SATURADA = "potencia_saturada"
    OLT_CAIDA = "olt_caida"
    PUERTO_SATURADO = "puerto_saturado"
    TEMPERATURA_ALTA = "temperatura_alta"
    PERDIDA_OPTICA = "perdida_optica"
    CPU_ALTA = "cpu_alta"
    MEMORIA_ALTA = "memoria_alta"
    SINCRONIZACION_FALLIDA = "sincronizacion_fallida"


class TipoEvento(StrEnum):
    """Cambios detectados por la sincronización, registrados históricamente."""

    ONU_NUEVA = "onu_nueva"
    ONU_ELIMINADA = "onu_eliminada"
    CAMBIO_ESTADO = "cambio_estado"
    CAMBIO_POTENCIA = "cambio_potencia"
    CAMBIO_FIRMWARE = "cambio_firmware"
    CAMBIO_PERFIL = "cambio_perfil"
    CAMBIO_CONFIGURACION = "cambio_configuracion"
    CAMBIO_DISTANCIA = "cambio_distancia"
    REINICIO_ONU = "reinicio_onu"
    REINICIO_OLT = "reinicio_olt"
    SINCRONIZACION_PARCIAL = "sincronizacion_parcial"


class TipoOperacion(StrEnum):
    """Operaciones de escritura auditables."""

    AUTORIZAR_ONU = "autorizar_onu"
    ELIMINAR_ONU = "eliminar_onu"
    REINICIAR_ONU = "reiniciar_onu"
    RESTAURAR_FABRICA = "restaurar_fabrica"
    CAMBIAR_WIFI = "cambiar_wifi"
    CAMBIAR_CLAVE_WIFI = "cambiar_clave_wifi"
    CAMBIAR_PPPOE = "cambiar_pppoe"
    MODO_BRIDGE = "modo_bridge"
    MODO_ROUTER = "modo_router"
    RESPALDAR_CONFIGURACION = "respaldar_configuracion"
    RESTAURAR_CONFIGURACION = "restaurar_configuracion"


class ResultadoSincronizacion(StrEnum):
    """Desenlace de una corrida de sincronización.

    ``PARCIAL`` no es un detalle cosmético: una lectura incompleta jamás debe
    interpretarse como "se cayó todo". Ver 01-arquitectura.md, sección 6.
    """

    COMPLETA = "completa"
    PARCIAL = "parcial"
    FALLIDA = "fallida"


class NivelSincronizacion(StrEnum):
    RAPIDO = "rapido"
    MEDIO = "medio"
    LENTO = "lento"


class Capacidad(Enum):
    """Lo que cada equipo sabe hacer realmente.

    El sistema consulta esto *antes* de intentar una operación, en vez de
    intentarla y fallar. La interfaz web oculta lo que el equipo no soporta.

    Con lo verificado en Fase 0, el driver VSOL declarará ``TEMPERATURA_CHASIS``,
    ``TRAFICO_POR_ONU``, ``CPU``, ``MEMORIA`` y ``SERIAL_POR_SNMP`` como **no**
    soportadas.
    """

    # Descubrimiento
    DESCUBRIR_PUERTOS = auto()
    DESCUBRIR_ONUS = auto()
    DESCUBRIR_NO_AUTORIZADAS = auto()
    SERIAL_POR_SNMP = auto()
    DESCUBRIR_PERFILES = auto()

    # Telemetría
    POTENCIA_OPTICA = auto()
    POTENCIA_MASIVA = auto()
    TRAFICO_POR_ONU = auto()
    TEMPERATURA_CHASIS = auto()
    TEMPERATURA_PON = auto()
    TEMPERATURA_ONU = auto()
    VOLTAJE = auto()
    DISTANCIA = auto()
    CPU = auto()
    MEMORIA = auto()
    UPTIME = auto()
    MOTIVO_CAIDA = auto()

    # Aprovisionamiento
    AUTORIZAR_ONU = auto()
    ELIMINAR_ONU = auto()
    REINICIAR_ONU = auto()
    RESTAURAR_FABRICA = auto()
    MOVER_ONU = auto()
    GESTION_PERFILES = auto()
    GESTION_VLAN = auto()
    GESTION_SERVICE_PORT = auto()

    # Gestión del CPE
    WIFI_POR_OMCI = auto()
    PPPOE_POR_OMCI = auto()
    MODO_BRIDGE_ROUTER = auto()
    CLIENTES_CONECTADOS = auto()
    PUERTOS_LAN = auto()

    # Configuración
    RESPALDO_CONFIGURACION = auto()
    RESTAURACION_CONFIGURACION = auto()
    ACTUALIZAR_FIRMWARE = auto()
