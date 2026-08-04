"""Fábrica de drivers para los servicios.

Es el único punto del sistema donde se juntan una OLT de la base, sus
credenciales descifradas y el driver del fabricante. Los servicios piden
"el driver de esta OLT" y no saben nada más.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from ..core.interfaces import OLTDriver, RepositorioOLT
from ..core.models import OLT
from ..core.registry import crear_driver

log = logging.getLogger(__name__)


class FabricaDrivers:
    """Construye drivers listos para usar a partir del id de una OLT.

    ``dry_run`` por defecto en ``True``: para que una operación llegue de
    verdad al equipo hay que pedirlo explícitamente. Es la decisión de diseño
    que evita que un error de programación deje clientes sin servicio.
    """

    def __init__(
        self,
        repositorio_olt: RepositorioOLT,
        *,
        dry_run_por_defecto: bool = True,
        extras: dict[str, Any] | None = None,
    ) -> None:
        self._olts = repositorio_olt
        self.dry_run_por_defecto = dry_run_por_defecto
        # Parámetros extra que reciben todos los drivers. Lo usa el simulador
        # para compartir un mismo parque entre llamadas.
        self._extras = extras or {}

    def para_olt(self, olt_id: int, *, dry_run: bool | None = None) -> OLTDriver:
        olt = self._olts.obtener(olt_id)
        return self.para_modelo(olt, dry_run=dry_run)

    def para_modelo(self, olt: OLT, *, dry_run: bool | None = None) -> OLTDriver:
        if olt.id is None:
            raise ValueError("La OLT debe estar persistida para construir su driver")
        credenciales = self._olts.obtener_credenciales(olt.id)
        efectivo = self.dry_run_por_defecto if dry_run is None else dry_run
        if not efectivo:
            log.warning(
                "Driver de %s creado en modo REAL: los comandos se enviarán al equipo",
                olt.host,
            )
        return crear_driver(
            olt=olt, credenciales=credenciales, dry_run=efectivo, **self._extras
        )

    @contextmanager
    def sesion(self, olt_id: int, *, dry_run: bool | None = None) -> Iterator[OLTDriver]:
        """Driver conectado, con desconexión garantizada."""
        driver = self.para_olt(olt_id, dry_run=dry_run)
        driver.conectar()
        try:
            yield driver
        finally:
            driver.desconectar()
