"""Configuración del módulo, tomada del entorno.

Un solo objeto inmutable, construido una vez y pasado por inyección. Nada de
constantes globales dispersas ni de leer ``os.environ`` desde el medio de un
servicio.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .core.errors import ErrorConfiguracion

PREFIJO = "GPON_"

#: Archivo de entorno que se lee al arrancar, si existe en el directorio actual.
ARCHIVO_ENTORNO = ".env"


def cargar_archivo_entorno(ruta: str | Path = ARCHIVO_ENTORNO) -> dict[str, str]:
    """Carga variables desde un archivo ``.env``, sin pisar las ya definidas.

    Existe para no tener que reescribir la clave de cifrado y la base de datos
    en cada terminal nueva. Lo que ya está exportado gana: una variable puesta a
    mano para una prueba puntual no debería quedar tapada por el archivo.

    Formato: ``CLAVE=valor`` por línea, ``#`` para comentarios. El valor se toma
    tal cual —sin interpretar barras invertidas ni expandir nada— porque las
    contraseñas de equipos suelen tener ``#``, ``$`` y comillas, y cualquier
    interpretación las rompería en silencio.
    """
    archivo = Path(ruta)
    if not archivo.is_file():
        return {}

    cargadas: dict[str, str] = {}
    for linea in archivo.read_text(encoding="utf-8").splitlines():
        limpia = linea.strip()
        if not limpia or limpia.startswith("#") or "=" not in limpia:
            continue
        clave, _, valor = limpia.partition("=")
        clave = clave.strip().removeprefix("export ").strip()
        valor = valor.strip()
        # Sólo se quitan las comillas si envuelven todo el valor.
        if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "\"'":
            valor = valor[1:-1]
        if clave and clave not in os.environ:
            os.environ[clave] = valor
            cargadas[clave] = valor
    return cargadas


def _entero(nombre: str, por_defecto: int) -> int:
    valor = os.environ.get(PREFIJO + nombre)
    if valor is None or valor == "":
        return por_defecto
    try:
        return int(valor)
    except ValueError as exc:
        raise ErrorConfiguracion(f"{PREFIJO}{nombre} debe ser un entero, es {valor!r}") from exc


def _booleano(nombre: str, por_defecto: bool) -> bool:
    valor = os.environ.get(PREFIJO + nombre)
    if valor is None or valor == "":
        return por_defecto
    return valor.strip().lower() in ("1", "true", "si", "sí", "yes", "on")


@dataclass(frozen=True, slots=True)
class ConfiguracionRetencion:
    """Escalones de retención del histórico (ver 01-arquitectura.md, sección 5).

    Con 473 ONU en una sola OLT y sondeo cada 5 minutos, una tabla plana son
    ~50 millones de filas al año. Estos escalones son lo que hace la diferencia
    entre un histórico consultable y una base inmanejable a los seis meses.
    """

    dias_fina: int = 7
    dias_horaria: int = 90
    dias_diaria: int = 730


@dataclass(frozen=True, slots=True)
class Configuracion:
    """Configuración completa del módulo GPON."""

    # Base de datos
    url_base_datos: str = "sqlite:///gpon.db"

    # Seguridad
    clave_cifrado: str = ""
    permitir_cifrado_nulo: bool = False

    # Comportamiento de los drivers
    dry_run_por_defecto: bool = True
    timeout_snmp_segundos: int = 5
    reintentos_snmp: int = 2
    timeout_cli_segundos: int = 20
    reintentos_cli: int = 2

    # Sincronización
    intervalo_sincronizacion_rapida_segundos: int = 300
    intervalo_sincronizacion_media_segundos: int = 1800
    intervalo_sincronizacion_lenta_segundos: int = 86400

    # Umbral de tolerancia de una corrida parcial: si se leyó menos de este
    # porcentaje de las ONU esperadas, la corrida se marca PARCIAL y no se
    # dispara ninguna alarma de baja. Es la regla que evita repetir la falsa
    # baja masiva que ya ocurrió en producción.
    porcentaje_minimo_lectura: int = 80

    retencion: ConfiguracionRetencion = field(default_factory=ConfiguracionRetencion)

    # Registro
    nivel_log: str = "INFO"
    archivo_log: str = ""

    @classmethod
    def desde_entorno(
        cls, *, archivo_entorno: str | Path | None = ARCHIVO_ENTORNO
    ) -> Configuracion:
        """Construye la configuración leyendo variables ``GPON_*``.

        Si hay un ``.env`` en el directorio actual, se carga primero. Lo ya
        exportado en la terminal tiene prioridad.
        """
        if archivo_entorno is not None:
            cargar_archivo_entorno(archivo_entorno)
        return cls(
            url_base_datos=os.environ.get(PREFIJO + "BASE_DATOS", "sqlite:///gpon.db"),
            clave_cifrado=os.environ.get(PREFIJO + "CLAVE_CIFRADO", ""),
            permitir_cifrado_nulo=_booleano("PERMITIR_CIFRADO_NULO", False),
            dry_run_por_defecto=_booleano("DRY_RUN", True),
            timeout_snmp_segundos=_entero("TIMEOUT_SNMP", 5),
            reintentos_snmp=_entero("REINTENTOS_SNMP", 2),
            timeout_cli_segundos=_entero("TIMEOUT_CLI", 20),
            reintentos_cli=_entero("REINTENTOS_CLI", 2),
            intervalo_sincronizacion_rapida_segundos=_entero("SINC_RAPIDA", 300),
            intervalo_sincronizacion_media_segundos=_entero("SINC_MEDIA", 1800),
            intervalo_sincronizacion_lenta_segundos=_entero("SINC_LENTA", 86400),
            porcentaje_minimo_lectura=_entero("PORCENTAJE_MINIMO_LECTURA", 80),
            retencion=ConfiguracionRetencion(
                dias_fina=_entero("RETENCION_FINA", 7),
                dias_horaria=_entero("RETENCION_HORARIA", 90),
                dias_diaria=_entero("RETENCION_DIARIA", 730),
            ),
            nivel_log=os.environ.get(PREFIJO + "NIVEL_LOG", "INFO"),
            archivo_log=os.environ.get(PREFIJO + "ARCHIVO_LOG", ""),
        )

    @property
    def ruta_sqlite(self) -> Path | None:
        """Ruta del archivo SQLite, si la base es SQLite."""
        if not self.url_base_datos.startswith("sqlite:"):
            return None
        ruta = self.url_base_datos.split("///", 1)[-1]
        return Path(ruta) if ruta and ruta != ":memory:" else None

    @property
    def es_sqlite(self) -> bool:
        return self.url_base_datos.startswith("sqlite:")

    @property
    def es_postgres(self) -> bool:
        return self.url_base_datos.startswith(("postgres:", "postgresql:"))

    def validar(self) -> None:
        """Verifica coherencia antes de arrancar. Falla temprano y con motivo."""
        if not self.clave_cifrado and not self.permitir_cifrado_nulo:
            raise ErrorConfiguracion(
                f"Falta {PREFIJO}CLAVE_CIFRADO. Las credenciales de OLT no pueden "
                f"guardarse sin cifrar en producción. Para desarrollo, definí "
                f"{PREFIJO}PERMITIR_CIFRADO_NULO=1 de forma explícita."
            )
        if not 1 <= self.porcentaje_minimo_lectura <= 100:
            raise ErrorConfiguracion(f"{PREFIJO}PORCENTAJE_MINIMO_LECTURA debe estar entre 1 y 100")
        if not (self.es_sqlite or self.es_postgres):
            raise ErrorConfiguracion(
                f"Base de datos no soportada: {self.url_base_datos!r}. "
                "Se admite sqlite:///ruta o postgresql://usuario@host/base"
            )
