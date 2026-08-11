"""Servicio de administración de OLT."""

from __future__ import annotations

import logging
from dataclasses import replace

from ..core.enums import Capacidad, EstadoOLT, Fabricante
from ..core.errors import ErrorTransporte, ErrorValidacion
from ..core.interfaces import Reloj, RepositorioOLT
from ..core.models import OLT, CredencialesOLT, DescripcionDriver
from ..core.registry import describir, fabricantes_registrados
from ..core.reloj import RelojSistema
from .fabrica import FabricaDrivers

log = logging.getLogger(__name__)


class ServicioOLT:
    """Alta, baja y consulta de OLT, más la verificación de conectividad."""

    def __init__(
        self,
        repositorio_olt: RepositorioOLT,
        fabrica: FabricaDrivers,
        *,
        reloj: Reloj | None = None,
    ) -> None:
        self._olts = repositorio_olt
        self._fabrica = fabrica
        self._reloj = reloj or RelojSistema()

    # --- alta y baja ---

    def registrar(
        self,
        *,
        nombre: str,
        host: str,
        fabricante: Fabricante,
        credenciales: CredencialesOLT,
        descripcion: str = "",
        activa: bool = True,
    ) -> OLT:
        """Da de alta una OLT. No se conecta: eso es ``descubrir``."""
        if not nombre.strip():
            raise ErrorValidacion("La OLT necesita un nombre")
        if not host.strip():
            raise ErrorValidacion("La OLT necesita una dirección")
        if fabricante not in fabricantes_registrados():
            raise ErrorValidacion(
                f"No hay driver para el fabricante '{fabricante}'. "
                f"Disponibles: {', '.join(str(f) for f in fabricantes_registrados())}"
            )
        existente = self._olts.obtener_por_host(host.strip())
        if existente is not None:
            # El mensaje dice qué hacer: sin esto se entra en un callejón sin
            # salida — el alta rebota y no hay forma obvia de corregir la que ya
            # está registrada.
            raise ErrorValidacion(
                f"Ya hay una OLT registrada en {host}: #{existente.id} "
                f"'{existente.nombre}' ({existente.fabricante}).\n"
                f"  Para cambiarle las credenciales:  gpon credenciales {existente.id}\n"
                f"  Para borrarla y empezar de nuevo: gpon eliminar-olt {existente.id}"
            )

        olt = OLT(
            nombre=nombre.strip(),
            host=host.strip(),
            fabricante=fabricante,
            descripcion=descripcion,
            activa=activa,
            estado=EstadoOLT.DESCONOCIDO,
        )
        creada = self._olts.crear(olt, credenciales)
        log.info("OLT registrada: %s (%s, %s)", creada.nombre, creada.host, fabricante)
        return creada

    def eliminar(self, olt_id: int) -> None:
        olt = self._olts.obtener(olt_id)
        self._olts.eliminar(olt_id)
        log.info("OLT eliminada: %s (%s)", olt.nombre, olt.host)

    def actualizar_credenciales(self, olt_id: int, credenciales: CredencialesOLT) -> None:
        self._olts.obtener(olt_id)  # valida que exista
        self._olts.guardar_credenciales(olt_id, credenciales)

    # --- consulta ---

    def obtener(self, olt_id: int) -> OLT:
        return self._olts.obtener(olt_id)

    def listar(self, solo_activas: bool = False) -> list[OLT]:
        return self._olts.listar(solo_activas=solo_activas)

    def capacidades(self, olt_id: int) -> frozenset[Capacidad]:
        """Qué puede hacer esta OLT.

        Lo consulta la interfaz web para ocultar lo que el equipo no soporta,
        en vez de mostrar un botón que va a fallar.
        """
        olt = self._olts.obtener(olt_id)
        return describir(olt.fabricante).capacidades

    def descripcion_driver(self, olt_id: int) -> DescripcionDriver:
        return describir(self._olts.obtener(olt_id).fabricante)

    # --- conectividad ---

    def probar_conexion(self, olt_id: int) -> tuple[bool, str]:
        """Intenta hablar con el equipo y actualiza su estado.

        Devuelve ``(ok, detalle)`` en vez de levantar excepción: es una
        verificación, y que falle es un resultado esperable.
        """
        olt = self._olts.obtener(olt_id)
        try:
            with self._fabrica.sesion(olt_id) as driver:
                info = driver.get_system_info()
        except ErrorTransporte as exc:
            self._olts.actualizar(replace(olt, estado=EstadoOLT.FUERA_DE_LINEA))
            return False, f"{type(exc).__name__}: {exc}"

        self._olts.actualizar(
            replace(
                olt,
                estado=EstadoOLT.EN_LINEA,
                modelo=info.modelo or olt.modelo,
                firmware=info.firmware or olt.firmware,
                numero_serie=info.numero_serie or olt.numero_serie,
                mac=info.mac or olt.mac,
                uptime_segundos=info.uptime_segundos,
            )
        )
        return True, f"{info.modelo or 'equipo'} firmware {info.firmware or 'desconocido'}"
