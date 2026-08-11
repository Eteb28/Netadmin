"""Por qué se cayó cada ONU, leído de la CLI.

Es la diferencia entre mandar una cuadrilla y no mandarla:

* **DyingGasp** — la ONU alcanzó a avisar que se quedaba sin energía. Es un
  corte de luz en el domicilio del cliente. En la red no hay nada que hacer.
* **LOS** — pérdida de señal óptica. Eso sí es fibra, y sí necesita una
  cuadrilla.
* **OffLine** — se cayó sin avisar y sin LOS. Puede ser cualquiera de las dos,
  y por eso se informa como desconocido en vez de elegir una.

SNMP no publica esta distinción en estos equipos: sólo dice que la ONU no está.
``show onu state`` sí la publica, puerto por puerto, y este servicio la trae y
la guarda para que el panel pueda separar "cortes de luz" de "fibra cortada".

Es de **sólo lectura**: entra a modo configuración porque el comando vive
adentro de ``interface gpon 0/N``, no ejecuta ni un comando de configuración, y
sale con ``end`` pase lo que pase.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from ..core.enums import EstadoONU, Fabricante, MotivoCaida
from ..core.errors import CapacidadNoSoportada, ErrorComando, ErrorGPON
from ..core.models import RefONU
from ..drivers.transport import crear_transporte_cli
from ..drivers.vsol.parser_tablas import parsear_onu_state

log = logging.getLogger(__name__)

COMANDO_ESTADO = "show onu state"
FABRICANTES_SOPORTADOS = (Fabricante.VSOL,)


@dataclass(frozen=True, slots=True)
class ResultadoEstados:
    """Qué se leyó y qué cambió."""

    olt_id: int
    momento: datetime | None = None
    onus_leidas: int = 0
    onus_actualizadas: int = 0
    #: Cuántas hay en cada fase, para poder mirarlo de un vistazo.
    por_motivo: dict[str, int] = field(default_factory=dict)
    #: ONU que la CLI informa y que el inventario no tiene. No se crean: puede
    #: ser una ONU dada de alta y todavía sin descubrir por SNMP.
    solo_en_el_equipo: tuple[str, ...] = ()
    puertos_con_falla: tuple[tuple[str, str], ...] = ()

    @property
    def completo(self) -> bool:
        return not self.puertos_con_falla


class ServicioEstadosCLI:
    """Trae el motivo de caída de cada ONU y lo guarda en el inventario."""

    def __init__(
        self,
        *,
        repositorio_olt: Any,
        repositorio_onu: Any,
        reloj: Any = None,
        fabrica_transporte: Any = crear_transporte_cli,
    ) -> None:
        self._olts = repositorio_olt
        self._onus = repositorio_onu
        self._reloj = reloj
        self._fabrica_transporte = fabrica_transporte

    def actualizar(
        self,
        olt_id: int,
        *,
        puertos: tuple[str, ...] = (),
        protocolo: str = "ssh",
        timeout: float = 60.0,
        ruta_traza: str | None = None,
    ) -> ResultadoEstados:
        """Recorre los puertos PON, lee el estado y actualiza lo que cambió."""
        olt = self._olts.obtener(olt_id)
        if olt.fabricante not in FABRICANTES_SOPORTADOS:
            raise CapacidadNoSoportada(
                f"motivo de caída por CLI ({COMANDO_ESTADO})", olt.fabricante
            )

        a_recorrer = puertos or tuple(f"0/{numero}" for numero in range(1, 9))
        transporte = self._crear_transporte(olt, olt_id, protocolo, timeout, ruta_traza)

        informados = []
        fallas: list[tuple[str, str]] = []

        transporte.abrir()
        try:
            transporte.ejecutar("configure terminal")
            for pon in a_recorrer:
                try:
                    transporte.ejecutar(f"interface gpon {pon}")
                    salida = transporte.ejecutar(COMANDO_ESTADO)
                except ErrorComando as exc:
                    # Un puerto que no existe en este chasis no es una falla del
                    # recorrido: se anota y se sigue con los demás.
                    fallas.append((pon, str(exc)))
                    continue
                except ErrorGPON as exc:
                    fallas.append((pon, f"{type(exc).__name__}: {exc}"))
                    continue
                informados.extend(parsear_onu_state(salida))
        finally:
            self._volver_a_exec(transporte)
            transporte.cerrar()

        return self._guardar(olt_id, informados, fallas)

    # --- internos ---------------------------------------------------------

    def _guardar(
        self, olt_id: int, informados: list[Any], fallas: list[tuple[str, str]]
    ) -> ResultadoEstados:
        actualizadas = 0
        ausentes: list[str] = []
        por_motivo: dict[str, int] = {}

        for informado in informados:
            por_motivo[str(informado.motivo)] = por_motivo.get(str(informado.motivo), 0) + 1

            ref = RefONU(informado.pon, informado.onu_id)
            existente = self._onus.obtener_por_ref(olt_id, ref)
            if existente is None:
                # No se inventa una entrada: puede estar dada de alta y todavía
                # sin descubrir por SNMP. Se informa, que es lo honesto.
                ausentes.append(str(ref))
                continue

            cambios = self._cambios(existente, informado)
            if not cambios:
                continue
            self._onus.guardar(replace(existente, **cambios))
            actualizadas += 1

        return ResultadoEstados(
            olt_id=olt_id,
            momento=self._reloj.ahora() if self._reloj is not None else None,
            onus_leidas=len(informados),
            onus_actualizadas=actualizadas,
            por_motivo=por_motivo,
            solo_en_el_equipo=tuple(ausentes),
            puertos_con_falla=tuple(fallas),
        )

    @staticmethod
    def _cambios(existente: Any, informado: Any) -> dict[str, Any]:
        """Qué hay que corregir de lo guardado.

        Una fase que el módulo no conoce **no pisa** lo que ya sabe: un firmware
        con una fase nueva no debe convertir un inventario bueno en un inventario
        de ONU en estado desconocido.
        """
        if informado.estado is EstadoONU.DESCONOCIDO:
            log.warning("Fase no reconocida en %s: %r", informado.onu_id, informado.fase)
            return {}

        cambios: dict[str, Any] = {}
        if existente.estado is not informado.estado:
            cambios["estado"] = informado.estado
        if existente.motivo_caida is not informado.motivo:
            cambios["motivo_caida"] = informado.motivo
        # Una ONU en línea no tiene motivo de caída: dejarle el anterior haría
        # que el panel contara un corte de luz que ya terminó.
        if informado.estado is EstadoONU.EN_LINEA:
            cambios["motivo_caida"] = MotivoCaida.NINGUNO
            if existente.motivo_caida is MotivoCaida.NINGUNO:
                cambios.pop("motivo_caida")
        return cambios

    def _crear_transporte(
        self, olt: Any, olt_id: int, protocolo: str, timeout: float, ruta_traza: str | None
    ) -> Any:
        credenciales = self._olts.obtener_credenciales(olt_id)
        return self._fabrica_transporte(
            host=olt.host,
            usuario=credenciales.usuario,
            password=credenciales.password,
            password_enable=credenciales.password_enable,
            protocolo=protocolo,
            puerto=credenciales.puerto_ssh if protocolo == "ssh" else credenciales.puerto_telnet,
            timeout=timeout,
            ruta_traza=ruta_traza,
        )

    @staticmethod
    def _volver_a_exec(transporte: Any) -> None:
        try:
            transporte.ejecutar("end")
        except ErrorGPON as exc:  # pragma: no cover - sólo si la sesión ya murió
            log.warning("No se pudo volver al modo EXEC: %s", exc)


__all__ = ["ResultadoEstados", "ServicioEstadosCLI"]
