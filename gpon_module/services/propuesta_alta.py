"""Del número de cliente al alta completa, sin retipear nada.

Hoy el operador junta a mano cuatro cosas que ya están escritas en algún lado:
el plan contratado, las credenciales PPPoE, la NAP y el modelo de ONU. Cada una
de esas copias es una oportunidad de equivocarse, y ya se cobró una: un plan
mal tipeado dejó una ONU declarada y sin servicio.

Este servicio arma la **propuesta**: junta lo que el sistema comercial sabe del
cliente y lo traduce al vocabulario de la OLT. No escribe nada en ningún lado.
Lo que devuelve va a la pantalla para que alguien lo mire y lo confirme, y por
eso viene con dos cosas además de los valores:

* **el motivo de cada elección**, para que se pueda discutir;
* **las advertencias**, para lo que el sistema comercial no contesta o contesta
  raro. Un campo vacío que llega en silencio es peor que uno que avisa.

Nada de esto reemplaza la verificación contra el equipo: el alta sigue
comprobando que la ONU esté esperando, que el índice esté libre y que el plan
exista. Esto sólo evita el tecleo.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from ..core.models import Cliente
from .planes import ParPlanes, elegir_planes, segmento_de

log = logging.getLogger(__name__)

#: La VLAN con la que va todo el parque de ERLAN. Es un valor por defecto, no
#: una regla: el formulario lo deja editar, y lo que se elija ahí manda también
#: en la WAN del CPE.
VLAN_POR_DEFECTO = 1001

ESTADOS_QUE_MERECEN_AVISO = ("baja", "suspendido", "rescindido")


@dataclass(frozen=True, slots=True)
class PropuestaAlta:
    """Todo lo que se puede completar solo, con su justificación."""

    cliente: Cliente
    perfil_onu: str = ""
    trafico_subida: str = ""
    trafico_bajada: str = ""
    vlan: int = VLAN_POR_DEFECTO
    #: ``034716_CDO8_NAP3``. El prefijo ``GPON0/1:29_`` lo pone el alta, que es
    #: la que sabe en qué puerto e índice terminó la ONU.
    sufijo_descripcion: str = ""
    pppoe_usuario: str = ""
    pppoe_password: str = ""
    motivo_plan: str = ""
    advertencias: tuple[str, ...] = field(default_factory=tuple)

    @property
    def completa(self) -> bool:
        """Si falta algo, el formulario lo pide; no se completa con inventos."""
        return bool(self.perfil_onu and self.trafico_subida and self.trafico_bajada)


class ServicioPropuestaAlta:
    """Arma el alta de un cliente a partir de su número."""

    def __init__(self, *, repositorio_clientes: Any, repositorio_perfiles: Any) -> None:
        self._clientes = repositorio_clientes
        self._perfiles = repositorio_perfiles

    @property
    def disponible(self) -> bool:
        """Sin sistema comercial a mano, el alta se sigue haciendo a mano."""
        return self._clientes is not None and getattr(self._clientes, "disponible", False)

    def proponer(
        self, olt_id: int, numero_cliente: str, *, vlan: int = VLAN_POR_DEFECTO
    ) -> PropuestaAlta:
        """Junta lo que se sabe del cliente y lo traduce al vocabulario de la OLT."""
        cliente = self._clientes.buscar(numero_cliente)
        avisos: list[str] = []

        planes = self._planes(olt_id, cliente)
        if not planes.completo:
            avisos.append(f"No se pudo elegir el plan de tráfico: {planes.motivo}.")

        if not cliente.modelo_equipo:
            avisos.append(
                "El sistema comercial no dice qué modelo de ONU tiene el cliente. "
                "Hay que cargar el perfil a mano."
            )
        if not cliente.pppoe_usuario or not cliente.pppoe_password:
            avisos.append(
                "Faltan las credenciales PPPoE del cliente en el sistema comercial."
            )
        if cliente.cdo is None or cliente.nap is None:
            avisos.append(
                "No se pudo leer el CDO y la NAP del cliente, así que la descripción "
                "va sin esa parte. Revisá la NAP en el sistema comercial."
            )
        if cliente.estado.lower() in ESTADOS_QUE_MERECEN_AVISO:
            # No se bloquea: puede ser una reconexión, que es un caso legítimo.
            # Pero dar de alta a un cliente dado de baja tiene que costar una
            # decisión consciente.
            avisos.append(f"El cliente figura como '{cliente.estado}' en el sistema comercial.")

        return PropuestaAlta(
            cliente=cliente,
            perfil_onu=cliente.modelo_equipo,
            trafico_subida=planes.subida,
            trafico_bajada=planes.bajada,
            vlan=vlan,
            sufijo_descripcion=_sufijo(cliente),
            pppoe_usuario=cliente.pppoe_usuario,
            pppoe_password=cliente.pppoe_password,
            motivo_plan=planes.motivo,
            advertencias=tuple(avisos),
        )

    def _planes(self, olt_id: int, cliente: Cliente) -> ParPlanes:
        perfiles = self._perfiles.obtener_de_olt(olt_id).trafico
        return elegir_planes(
            perfiles, megabits=cliente.megabits_bajada, segmento=segmento_de(cliente)
        )


def _sufijo(cliente: Cliente) -> str:
    """``034716_CDO8_NAP3``, el sufijo con que ERLAN nombra sus ONU.

    Sin ubicación queda sólo el número de cliente, que ya es como están las 284
    ONU viejas del parque.
    """
    partes = [p for p in (cliente.numero, cliente.ubicacion) if p]
    return "_".join(partes)


__all__ = ["VLAN_POR_DEFECTO", "PropuestaAlta", "ServicioPropuestaAlta"]
