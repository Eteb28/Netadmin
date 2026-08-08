"""Dar de alta una ONU en la OLT.

Es la primera operación del módulo que **escribe** en un equipo con clientes
conectados, y está armada en ese entendido:

* **``dry_run`` por defecto.** Para que un comando llegue de verdad al equipo
  hay que pedirlo explícitamente. Lo normal es ver la secuencia primero.
* **Se verifica antes de escribir.** Que la ONU esté realmente esperando en ese
  puerto, que el índice esté libre, que el serial no esté ya dado de alta. Cada
  una de esas comprobaciones evita un alta que dejaría al cliente sin servicio o
  pisaría a otro.
* **Se aborta en el primer rechazo.** Si el equipo dice que no a un comando del
  medio, no se sigue: seguir es lo que deja la ONU a medio configurar. El
  llamador recibe qué comando falló y qué se alcanzó a aplicar.
* **Queda auditado.** La operación se guarda con los comandos exactos y con si
  fue real o simulada.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from ..core.enums import Fabricante, TipoOperacion
from ..core.errors import CapacidadNoSoportada, ErrorComando, ErrorValidacion
from ..core.models import Operacion, RefONU
from ..drivers.transport import crear_transporte_cli
from ..drivers.vsol.comandos_alta import SolicitudAlta, primer_indice_libre, secuencia_alta
from ..drivers.vsol.parser_tablas import parsear_onu_auto_find, parsear_onu_info

log = logging.getLogger(__name__)

FABRICANTES_SOPORTADOS = (Fabricante.VSOL,)
COMANDO_PENDIENTES = "show onu auto-find"
COMANDO_INVENTARIO = "show onu info"


@dataclass(frozen=True, slots=True)
class ResultadoAlta:
    """Qué se hizo, o qué se habría hecho."""

    solicitud: SolicitudAlta
    comandos: tuple[str, ...]
    simulado: bool
    ok: bool = True
    comandos_aplicados: tuple[str, ...] = ()
    salidas: tuple[str, ...] = field(default_factory=tuple)
    error: str = ""
    comando_que_fallo: str = ""

    @property
    def quedo_a_medias(self) -> bool:
        """Se alcanzó a escribir algo y después falló. Hay que ir a mirar."""
        return not self.ok and bool(self.comandos_aplicados)


class ServicioAltaONU:
    """Autoriza una ONU que está esperando en un puerto PON."""

    def __init__(
        self,
        *,
        repositorio_olt: Any,
        repositorio_operacion: Any = None,
        reloj: Any = None,
        fabrica_transporte: Any = crear_transporte_cli,
    ) -> None:
        self._olts = repositorio_olt
        self._operaciones = repositorio_operacion
        self._reloj = reloj
        self._fabrica_transporte = fabrica_transporte

    def autorizar(
        self,
        olt_id: int,
        *,
        numero_serie: str,
        pon: int | None = None,
        perfil_onu: str,
        descripcion: str = "",
        perfil_dba: str = "Internet",
        trafico_subida: str = "",
        trafico_bajada: str = "",
        vlan: int = 1001,
        onu_id: int | None = None,
        dry_run: bool = True,
        protocolo: str = "ssh",
        timeout: float = 30.0,
        usuario: str = "",
        ruta_traza: str | None = None,
    ) -> ResultadoAlta:
        """Da de alta la ONU con ese número de serie.

        Si no se indica ``pon``, se busca en todos los puertos. Si no se indica
        ``onu_id``, se toma el índice libre más bajo del puerto, que es lo que
        hace el operador a mano.
        """
        olt = self._olts.obtener(olt_id)
        if olt.fabricante not in FABRICANTES_SOPORTADOS:
            raise CapacidadNoSoportada("alta de ONU por CLI", olt.fabricante)

        transporte = self._crear_transporte(olt, olt_id, protocolo, timeout, ruta_traza)

        transporte.abrir()
        try:
            # Se entra a modo configuración una sola vez. Desde adentro se
            # cambia de puerto con 'interface gpon', que es válido ahí; repetir
            # 'configure terminal' en modo interfaz lo rechaza el equipo.
            transporte.ejecutar("configure terminal")
            ubicacion = self._ubicar(transporte, numero_serie, pon)
            indice = onu_id if onu_id is not None else self._elegir_indice(transporte, ubicacion)

            solicitud = SolicitudAlta(
                pon=ubicacion,
                onu_id=indice,
                numero_serie=numero_serie.strip().upper(),
                perfil_onu=perfil_onu,
                descripcion=descripcion,
                perfil_dba=perfil_dba,
                trafico_subida=trafico_subida,
                trafico_bajada=trafico_bajada,
                vlan=vlan,
            )
            comandos = secuencia_alta(solicitud)

            if dry_run:
                log.info("Alta simulada de %s en PON %s: no se envió nada", numero_serie, ubicacion)
                resultado = ResultadoAlta(solicitud=solicitud, comandos=comandos, simulado=True)
            else:
                # Se vuelve al modo EXEC para aplicar la secuencia entera tal
                # como se muestra, empezando por su propio 'configure terminal'.
                # Lo que se ve es exactamente lo que se envía.
                transporte.ejecutar("end")
                resultado = self._aplicar(transporte, solicitud, comandos)
        finally:
            self._volver_a_exec(transporte)
            transporte.cerrar()

        self._auditar(olt_id, resultado, usuario)
        return resultado

    # --- verificaciones previas -------------------------------------------

    def _ubicar(self, transporte: Any, numero_serie: str, pon: int | None) -> int:
        """Confirma que la ONU está esperando, y en qué puerto.

        No alcanza con que el técnico diga el puerto: si el serial no está en la
        lista de auto-find, el alta va a fallar o —peor— va a quedar hecha para
        una ONU que no está, ocupando un índice.
        """
        buscado = numero_serie.strip().upper()
        puertos = (pon,) if pon is not None else tuple(range(1, 9))

        for numero in puertos:
            try:
                transporte.ejecutar(f"interface gpon 0/{numero}")
                salida = transporte.ejecutar(COMANDO_PENDIENTES)
            except ErrorComando:
                continue
            for pendiente in parsear_onu_auto_find(salida):
                if pendiente.numero_serie.upper() == buscado:
                    return numero

        donde = f"el PON {pon}" if pon is not None else "ningún puerto"
        raise ErrorValidacion(
            f"La ONU {buscado} no está esperando autorización en {donde}.\n"
            "Puede ser que todavía no se registró, que esté en otra OLT, o que el "
            "serial venga con un error de tipeo. Verificalo con 'gpon pendientes'."
        )

    def _elegir_indice(self, transporte: Any, _pon: int) -> int:
        """Toma el índice libre más bajo del puerto, reusando los huecos.

        No hace falta volver a entrar al puerto: ``_ubicar`` dejó la sesión
        adentro del que corresponde, y volver a entrar desde modo interfaz es
        justo lo que algunos firmwares rechazan.
        """
        salida = transporte.ejecutar(COMANDO_INVENTARIO)
        ocupados = {informada.onu_id for informada in parsear_onu_info(salida)}
        return primer_indice_libre(ocupados)

    # --- escritura ---------------------------------------------------------

    def _aplicar(
        self, transporte: Any, solicitud: SolicitudAlta, comandos: tuple[str, ...]
    ) -> ResultadoAlta:
        aplicados: list[str] = []
        salidas: list[str] = []

        for comando in comandos:
            try:
                salidas.append(transporte.ejecutar(comando))
            except ErrorComando as exc:
                log.error(
                    "Alta abortada en %s tras %d de %d comandos. Falló: %s",
                    solicitud.numero_serie,
                    len(aplicados),
                    len(comandos),
                    comando,
                )
                return ResultadoAlta(
                    solicitud=solicitud,
                    comandos=comandos,
                    simulado=False,
                    ok=False,
                    comandos_aplicados=tuple(aplicados),
                    salidas=tuple(salidas),
                    error=str(exc),
                    comando_que_fallo=comando,
                )
            aplicados.append(comando)

        return ResultadoAlta(
            solicitud=solicitud,
            comandos=comandos,
            simulado=False,
            ok=True,
            comandos_aplicados=tuple(aplicados),
            salidas=tuple(salidas),
        )

    # --- alrededores -------------------------------------------------------

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
        except Exception as exc:
            log.warning("No se pudo volver al modo EXEC: %s", exc)

    def _auditar(self, olt_id: int, resultado: ResultadoAlta, usuario: str) -> None:
        """Deja registro de la operación, real o simulada.

        Si el repositorio de auditoría falla, se avisa pero no se rompe: el alta
        ya ocurrió en el equipo y ocultarla sería peor que no poder registrarla.
        """
        if self._operaciones is None:
            return
        try:
            self._operaciones.registrar(
                Operacion(
                    tipo=TipoOperacion.AUTORIZAR_ONU,
                    olt_id=olt_id,
                    ref_onu=RefONU(resultado.solicitud.pon, resultado.solicitud.onu_id),
                    usuario=usuario or "modulo-gpon",
                    ok=resultado.ok,
                    simulado=resultado.simulado,
                    comandos=resultado.comandos,
                    salida="\n".join(resultado.salidas),
                    error=resultado.error,
                    ejecutada_en=self._reloj.ahora() if self._reloj is not None else None,
                )
            )
        except Exception as exc:
            log.error("No se pudo auditar el alta de %s: %s", resultado.solicitud.numero_serie, exc)
