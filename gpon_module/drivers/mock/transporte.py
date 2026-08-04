"""Transporte CLI simulado.

Permite probar la disciplina de sesión —desactivar paginación, abortar la
secuencia ante un rechazo, reintentar timeouts— sin ninguna OLT del otro lado.
"""

from __future__ import annotations

from collections.abc import Callable

from ...core.errors import ErrorTiempoAgotado
from ..transport.base import TransporteCLIBase


class TransporteCLISimulado(TransporteCLIBase):
    """Sesión CLI de mentira, con respuestas programables.

    ``respuestas`` mapea comando → salida. Un comando sin entrada devuelve la
    respuesta por defecto, o el rechazo típico de una CLI estilo Cisco si se
    pide ``rechazar_desconocidos``, que es lo que hace un equipo real.
    """

    def __init__(
        self,
        *,
        host: str = "olt-simulada",
        respuestas: dict[str, str] | None = None,
        respuesta_por_defecto: str = "",
        rechazar_desconocidos: bool = False,
        fallas_de_apertura: int = 0,
        timeouts_programados: int = 0,
        **kwargs: object,
    ) -> None:
        super().__init__(host=host, **kwargs)  # type: ignore[arg-type]
        self.respuestas = respuestas or {}
        self.respuesta_por_defecto = respuesta_por_defecto
        self.rechazar_desconocidos = rechazar_desconocidos
        #: Aperturas que fallarán antes de que una funcione (para probar el reintento).
        self.fallas_de_apertura = fallas_de_apertura
        #: Comandos que vencerán por tiempo antes de responder bien.
        self.timeouts_programados = timeouts_programados
        #: Todo lo que se envió, en orden. Incluye los comandos de apertura.
        self.enviados: list[str] = []
        self.aperturas = 0
        self.cierres = 0

    def _abrir_sesion(self) -> None:
        self.aperturas += 1
        if self.fallas_de_apertura > 0:
            self.fallas_de_apertura -= 1
            raise ErrorTiempoAgotado(f"No hubo respuesta de {self.host} (simulado)")

    def _cerrar_sesion(self) -> None:
        self.cierres += 1

    def _enviar(self, comando: str) -> str:
        if self.timeouts_programados > 0:
            self.timeouts_programados -= 1
            raise ErrorTiempoAgotado(f"'{comando}' venció por tiempo en {self.host} (simulado)")
        self.enviados.append(comando)
        if comando in self.respuestas:
            return self.respuestas[comando]
        if self.rechazar_desconocidos:
            return f"% Invalid input detected at '^' marker\n{comando}"
        return self.respuesta_por_defecto


def transporte_con_guion(guion: Callable[[str], str], **kwargs: object) -> TransporteCLISimulado:
    """Transporte cuya respuesta la decide una función. Para casos complejos."""
    transporte = TransporteCLISimulado(**kwargs)  # type: ignore[arg-type]
    transporte._enviar = lambda comando: (  # type: ignore[method-assign]
        transporte.enviados.append(comando) or guion(comando)
    )
    return transporte
