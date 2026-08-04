"""Base común de todos los drivers.

Concentra lo que no debe reescribirse por fabricante: control de capacidades,
modo simulación, construcción de resultados auditables y medición de tiempos.
Lo que sí es propio de cada fabricante —comandos y OIDs— vive únicamente en
``drivers/<fabricante>/``.

Un driver que hereda de ``DriverBase`` obtiene gratis:

* ``dry_run`` respetado en toda escritura, sin tener que acordarse;
* ``CapacidadNoSoportada`` antes de tocar el equipo, no después de fallar;
* un ``ResultadoOperacion`` completo, con comandos, salida y duración.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from typing import Any

from ..core.enums import Capacidad, Fabricante, TipoOperacion
from ..core.errors import CapacidadNoSoportada, ErrorGPON
from ..core.models import (
    OLT,
    ClienteConectado,
    CredencialesOLT,
    LecturaTrafico,
    Perfiles,
    PuertoLAN,
    RefONU,
    ResultadoOperacion,
)
from ..core.reloj import RelojSistema

log = logging.getLogger(__name__)


class DriverBase:
    """Comportamiento compartido por todos los drivers de OLT.

    No implementa ninguna lectura ni escritura concreta: eso es de cada
    fabricante. Provee la mecánica que hace que todos se comporten igual.
    """

    #: Capacidades del driver. Cada subclase la redefine con lo que su equipo
    #: realmente puede hacer, verificado, no lo que promete el folleto.
    CAPACIDADES: frozenset[Capacidad] = frozenset()

    #: Fabricante que atiende este driver.
    FABRICANTE: Fabricante = Fabricante.SIMULADO

    #: Modelos con los que se probó.
    MODELOS: tuple[str, ...] = ()

    def __init__(
        self,
        *,
        olt: OLT,
        credenciales: CredencialesOLT,
        dry_run: bool = True,
        reloj: Any | None = None,
    ) -> None:
        self.olt = olt
        self.olt_id = olt.id
        self.fabricante = self.FABRICANTE
        self.credenciales = credenciales
        self._dry_run = dry_run
        self._reloj = reloj or RelojSistema()
        self._conectado = False

        if dry_run:
            log.debug(
                "Driver %s para %s creado en modo simulación: no se enviará ningún comando",
                type(self).__name__,
                olt.host,
            )

    # --- capacidades ------------------------------------------------------

    def capacidades(self) -> frozenset[Capacidad]:
        return self.CAPACIDADES

    def soporta(self, capacidad: Capacidad) -> bool:
        return capacidad in self.CAPACIDADES

    def _exigir(self, capacidad: Capacidad) -> None:
        """Corta la operación si el equipo no la soporta.

        Falla *antes* de abrir una sesión o mandar un comando: un equipo que no
        puede hacer algo no debería siquiera ser contactado para intentarlo.
        """
        if capacidad not in self.CAPACIDADES:
            raise CapacidadNoSoportada(capacidad.name, self.FABRICANTE)

    # --- ciclo de vida ----------------------------------------------------

    @property
    def dry_run(self) -> bool:
        return self._dry_run

    @property
    def conectado(self) -> bool:
        return self._conectado

    def conectar(self) -> None:
        self._conectado = True

    def desconectar(self) -> None:
        self._conectado = False

    def __enter__(self):
        self.conectar()
        return self

    def __exit__(self, *_excepcion: object) -> None:
        self.desconectar()

    # --- construcción de resultados --------------------------------------

    def _exito(
        self,
        tipo: TipoOperacion,
        comandos: Sequence[str],
        salida: str = "",
        *,
        ref: RefONU | None = None,
        duracion_ms: int | None = None,
    ) -> ResultadoOperacion:
        return ResultadoOperacion(
            ok=True,
            tipo=tipo,
            comandos_enviados=tuple(comandos),
            salida_cruda=salida,
            error=None,
            simulado=self._dry_run,
            olt_id=self.olt_id,
            ref_onu=ref,
            duracion_ms=duracion_ms,
            ejecutada_en=self._reloj.ahora(),
        )

    def _fallo(
        self,
        tipo: TipoOperacion,
        comandos: Sequence[str],
        error: str,
        salida: str = "",
        *,
        ref: RefONU | None = None,
        duracion_ms: int | None = None,
    ) -> ResultadoOperacion:
        return ResultadoOperacion(
            ok=False,
            tipo=tipo,
            comandos_enviados=tuple(comandos),
            salida_cruda=salida,
            error=error,
            simulado=self._dry_run,
            olt_id=self.olt_id,
            ref_onu=ref,
            duracion_ms=duracion_ms,
            ejecutada_en=self._reloj.ahora(),
        )

    def _operacion(
        self,
        tipo: TipoOperacion,
        comandos: Sequence[str],
        ejecutor: Callable[[Sequence[str]], str],
        *,
        ref: RefONU | None = None,
    ) -> ResultadoOperacion:
        """Ejecuta una escritura respetando el modo simulación.

        En ``dry_run`` arma la lista de comandos y **no la envía**: devuelve un
        resultado exitoso marcado como simulado, con los comandos exactos que
        se habrían ejecutado. Es la única defensa real contra dejar clientes
        sin servicio por un comando mal formado (riesgo R1).
        """
        comandos = list(comandos)
        if self._dry_run:
            log.info(
                "[SIMULACIÓN] %s en %s: %d comando(s) NO enviados",
                tipo.value,
                self.olt.host,
                len(comandos),
            )
            return self._exito(
                tipo,
                comandos,
                salida="[simulación] los comandos no se enviaron al equipo",
                ref=ref,
                duracion_ms=0,
            )

        inicio = time.monotonic()
        try:
            salida = ejecutor(comandos)
        except ErrorGPON as exc:
            duracion = int((time.monotonic() - inicio) * 1000)
            log.warning("%s falló en %s: %s", tipo.value, self.olt.host, exc)
            return self._fallo(
                tipo,
                comandos,
                error=f"{type(exc).__name__}: {exc}",
                salida=getattr(exc, "salida", ""),
                ref=ref,
                duracion_ms=duracion,
            )
        duracion = int((time.monotonic() - inicio) * 1000)
        return self._exito(tipo, comandos, salida=salida, ref=ref, duracion_ms=duracion)

    # --- valores por defecto para lo no soportado -------------------------
    #
    # Un driver cuyo equipo no expone un dato **no** debe devolver 0: un cero
    # se grafica, se promedia y se convierte en una mentira. Devuelve None, y
    # la capacidad declarada le dice a la interfaz que ni siquiera lo muestre.

    def get_temperature(self) -> float | None:
        self._exigir(Capacidad.TEMPERATURA_CHASIS)
        return None

    def get_cpu(self) -> float | None:
        self._exigir(Capacidad.CPU)
        return None

    def get_memory(self) -> float | None:
        self._exigir(Capacidad.MEMORIA)
        return None

    def get_traffic(self, ref: RefONU) -> LecturaTrafico:
        self._exigir(Capacidad.TRAFICO_POR_ONU)
        raise NotImplementedError

    def get_distance(self, ref: RefONU) -> int | None:
        self._exigir(Capacidad.DISTANCIA)
        return None

    def get_connected_clients(self, ref: RefONU) -> list[ClienteConectado]:
        self._exigir(Capacidad.CLIENTES_CONECTADOS)
        return []

    def get_lan_ports(self, ref: RefONU) -> list[PuertoLAN]:
        self._exigir(Capacidad.PUERTOS_LAN)
        return []

    def get_profiles(self) -> Perfiles:
        self._exigir(Capacidad.DESCUBRIR_PERFILES)
        return Perfiles()

    def __repr__(self) -> str:
        modo = "simulación" if self._dry_run else "REAL"
        return f"<{type(self).__name__} {self.olt.host} fabricante={self.FABRICANTE} modo={modo}>"
