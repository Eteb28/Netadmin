"""Contratos del módulo GPON.

Son ``Protocol`` de tipado estructural: un driver o un repositorio no necesita
heredar de nada, sólo cumplir la forma. Eso mantiene los drivers desacoplados
del núcleo y hace triviales los dobles de prueba.

Regla que ordena todo el diseño: **un comando CLI o un OID sólo puede existir
dentro de ``drivers/<fabricante>/``**. Si aparece un string con un comando en
``core/``, ``services/`` o ``api/``, el diseño se rompió.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from .enums import (
    Capacidad,
    Fabricante,
    Granularidad,
    TipoMetrica,
)
from .models import (
    OLT,
    ONU,
    Alarma,
    ClienteConectado,
    ConfigWiFi,
    CredencialesOLT,
    CredencialPPPoE,
    Evento,
    InfoSistema,
    LecturaOptica,
    LecturaTrafico,
    Metrica,
    ONUNoAutorizada,
    Operacion,
    Perfiles,
    PuertoLAN,
    PuertoPON,
    RefONU,
    RespaldoConfiguracion,
    ResultadoOperacion,
    Sincronizacion,
    SolicitudAutorizacion,
)

# --- Servicios transversales ---------------------------------------------


class Reloj(Protocol):
    """Fuente de tiempo inyectable: los tests no deben depender del reloj real."""

    def ahora(self) -> datetime: ...


class Cifrador(Protocol):
    """Cifrado en reposo de credenciales de OLT (mitiga R8)."""

    def cifrar(self, texto: str) -> str: ...

    def descifrar(self, texto_cifrado: str) -> str: ...


# --- Transporte -----------------------------------------------------------


@runtime_checkable
class TransporteSNMP(Protocol):
    """Lectura SNMP. Canal barato y masivo, pero de sólo lectura en VSOL."""

    def get(self, oid: str) -> str | None:
        """Devuelve el valor de un OID, o ``None`` si no existe."""

    def walk(self, oid_base: str) -> dict[str, str]:
        """Recorre una rama. Las claves son OIDs completos.

        Un resultado vacío significa "la rama no existe"; una falla de
        comunicación debe levantar ``ErrorTransporte``, nunca devolver ``{}``.
        Confundir ambos casos genera bajas masivas falsas.
        """

    def cerrar(self) -> None: ...


@runtime_checkable
class TransporteCLI(Protocol):
    """Sesión de línea de comandos (Telnet o SSH).

    Implementaciones obligadas a: desactivar la paginación al abrir (riesgo R3),
    serializar el acceso por OLT (riesgo R4) y detectar el rechazo de comandos
    para abortar la secuencia (riesgo R2).
    """

    def abrir(self) -> None: ...

    def cerrar(self) -> None: ...

    def ejecutar(self, comando: str) -> str:
        """Envía un comando y devuelve su salida cruda.

        Levanta ``ErrorComando`` si el equipo lo rechaza.
        """

    def ejecutar_secuencia(self, comandos: list[str]) -> list[str]:
        """Envía comandos en orden, abortando en el primer rechazo."""

    @property
    def conectado(self) -> bool: ...


# --- Driver de OLT --------------------------------------------------------


@runtime_checkable
class OLTDriver(Protocol):
    """Contrato único que todo fabricante debe cumplir.

    Los nombres de método están en inglés por pedido explícito del diseño
    (``authorize_onu()``, ``discover_onus()``, …); el resto del módulo usa
    castellano. Es deliberado: éste es el contrato que se compara entre
    fabricantes.

    Ningún método de esta interfaz recibe ni devuelve texto de comandos. Las
    operaciones de escritura devuelven siempre ``ResultadoOperacion``, nunca
    ``bool``, para que toda escritura sea auditable.
    """

    fabricante: Fabricante
    olt_id: int | None

    # --- ciclo de vida ---

    @property
    def dry_run(self) -> bool:
        """Si es ``True``, las escrituras arman los comandos y no los envían."""

    def capacidades(self) -> frozenset[Capacidad]:
        """Lo que este equipo sabe hacer. Se consulta antes de intentar, no después."""

    def soporta(self, capacidad: Capacidad) -> bool: ...

    def conectar(self) -> None: ...

    def desconectar(self) -> None: ...

    # --- descubrimiento y telemetría (sólo lectura) ---

    def get_system_info(self) -> InfoSistema: ...

    def discover_ports(self) -> list[PuertoPON]: ...

    def discover_onus(self) -> list[ONU]: ...

    def discover_unauthorized_onus(self) -> list[ONUNoAutorizada]:
        """ONUs vistas por la OLT y todavía sin dar de alta.

        En VSOL exige CLI: el serial no está expuesto por SNMP (verificado).
        """

    def get_signal(self, ref: RefONU) -> LecturaOptica: ...

    def get_signals(self) -> list[LecturaOptica]:
        """Potencias de todas las ONU en una sola pasada (SNMP masivo)."""

    def get_traffic(self, ref: RefONU) -> LecturaTrafico: ...

    def get_temperature(self) -> float | None:
        """Temperatura del chasis. ``None`` si el equipo no la expone."""

    def get_distance(self, ref: RefONU) -> int | None: ...

    def get_cpu(self) -> float | None: ...

    def get_memory(self) -> float | None: ...

    def get_uptime(self) -> int | None: ...

    def get_profiles(self) -> Perfiles: ...

    def get_connected_clients(self, ref: RefONU) -> list[ClienteConectado]: ...

    def get_lan_ports(self, ref: RefONU) -> list[PuertoLAN]: ...

    def generate_running_config(self) -> str: ...

    # --- aprovisionamiento (escritura) ---

    def authorize_onu(self, solicitud: SolicitudAutorizacion) -> ResultadoOperacion: ...

    def delete_onu(self, ref: RefONU) -> ResultadoOperacion: ...

    def reboot_onu(self, ref: RefONU) -> ResultadoOperacion: ...

    def factory_reset(self, ref: RefONU) -> ResultadoOperacion: ...

    def set_wifi(self, ref: RefONU, config: ConfigWiFi) -> ResultadoOperacion: ...

    def change_wifi_password(self, ref: RefONU, password: str) -> ResultadoOperacion: ...

    def change_pppoe(self, ref: RefONU, credencial: CredencialPPPoE) -> ResultadoOperacion: ...

    def set_bridge(self, ref: RefONU, vlan: int | None = None) -> ResultadoOperacion: ...

    def set_router(
        self,
        ref: RefONU,
        credencial: CredencialPPPoE,
        vlan: int | None = None,
    ) -> ResultadoOperacion: ...

    def backup_configuration(self) -> RespaldoConfiguracion: ...

    def restore_configuration(self, respaldo: RespaldoConfiguracion) -> ResultadoOperacion: ...


class FabricaDriver(Protocol):
    """Construye un driver para una OLT concreta."""

    def __call__(
        self,
        *,
        olt: OLT,
        credenciales: CredencialesOLT,
        dry_run: bool = True,
    ) -> OLTDriver: ...


# --- Persistencia (Repository Pattern) -----------------------------------


class RepositorioOLT(Protocol):
    def crear(self, olt: OLT, credenciales: CredencialesOLT) -> OLT: ...

    def actualizar(self, olt: OLT) -> OLT: ...

    def eliminar(self, olt_id: int) -> None: ...

    def obtener(self, olt_id: int) -> OLT: ...

    def obtener_por_host(self, host: str) -> OLT | None: ...

    def listar(self, solo_activas: bool = False) -> list[OLT]: ...

    def obtener_credenciales(self, olt_id: int) -> CredencialesOLT: ...

    def guardar_credenciales(self, olt_id: int, credenciales: CredencialesOLT) -> None: ...


class RepositorioPuertoPON(Protocol):
    def reemplazar_de_olt(self, olt_id: int, puertos: list[PuertoPON]) -> list[PuertoPON]: ...

    def listar_de_olt(self, olt_id: int) -> list[PuertoPON]: ...


class RepositorioONU(Protocol):
    def guardar(self, onu: ONU) -> ONU:
        """Alta o actualización según ``(olt_id, pon, onu_id)``."""

    def guardar_muchas(self, onus: list[ONU]) -> list[ONU]: ...

    def obtener(self, onu_id: int) -> ONU: ...

    def obtener_por_ref(self, olt_id: int, ref: RefONU) -> ONU | None: ...

    def obtener_por_serie(self, numero_serie: str) -> ONU | None: ...

    def listar_de_olt(self, olt_id: int, pon: int | None = None) -> list[ONU]: ...

    def eliminar(self, onu_id: int) -> None: ...

    def contar_de_olt(self, olt_id: int) -> int: ...


class RepositorioMetrica(Protocol):
    def registrar(self, metrica: Metrica) -> None: ...

    def registrar_muchas(self, metricas: list[Metrica]) -> None: ...

    def serie(
        self,
        *,
        entidad: str,
        entidad_id: int,
        tipo: TipoMetrica,
        desde: datetime,
        hasta: datetime,
        granularidad: Granularidad = Granularidad.FINA,
    ) -> list[Metrica]: ...

    def ultimo_valor(
        self, *, entidad: str, entidad_id: int, tipo: TipoMetrica
    ) -> Metrica | None: ...


class RepositorioAlarma(Protocol):
    def abrir(self, alarma: Alarma) -> Alarma: ...

    def resolver(self, alarma_id: int, momento: datetime) -> None: ...

    def reconocer(self, alarma_id: int, usuario: str, momento: datetime) -> None: ...

    def listar_activas(self, olt_id: int | None = None) -> list[Alarma]: ...

    def buscar_activa(self, *, tipo: str, entidad: str, entidad_id: int) -> Alarma | None: ...


class RepositorioEvento(Protocol):
    def registrar(self, evento: Evento) -> Evento: ...

    def registrar_muchos(self, eventos: list[Evento]) -> None: ...

    def listar(
        self, *, olt_id: int | None = None, limite: int = 100, desplazamiento: int = 0
    ) -> list[Evento]: ...


class RepositorioOperacion(Protocol):
    """Auditoría de escrituras. Toda operación queda aquí, incluidas las simuladas."""

    def registrar(self, operacion: Operacion) -> Operacion: ...

    def listar(
        self, *, olt_id: int | None = None, limite: int = 100, desplazamiento: int = 0
    ) -> list[Operacion]: ...


class RepositorioSincronizacion(Protocol):
    def registrar(self, sincronizacion: Sincronizacion) -> Sincronizacion: ...

    def ultima_de_olt(self, olt_id: int) -> Sincronizacion | None: ...

    def listar(self, *, olt_id: int | None = None, limite: int = 50) -> list[Sincronizacion]: ...
