"""Servicio de administración de ONU.

Toda escritura pasa por acá, y toda escritura queda auditada: qué se pidió,
quién lo pidió, qué comandos se armaron, qué contestó el equipo y si fue real
o simulada. Ese registro es lo que permite reconstruir después qué pasó con el
servicio de un cliente.

La interfaz web y la API nunca hablan con un driver: hablan con este servicio.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from ..core.enums import Capacidad, ClasificacionOptica, TipoEvento, TipoOperacion
from ..core.errors import CapacidadNoSoportada, ErrorGPON, ErrorValidacion, NoEncontrado
from ..core.interfaces import (
    OLTDriver,
    Reloj,
    RepositorioEvento,
    RepositorioONU,
    RepositorioOperacion,
)
from ..core.models import (
    ONU,
    ConfigWiFi,
    CredencialPPPoE,
    Evento,
    LecturaOptica,
    ONUNoAutorizada,
    Operacion,
    RefONU,
    RespaldoConfiguracion,
    ResultadoOperacion,
    SolicitudAutorizacion,
)
from ..core.optica import UMBRALES_POR_DEFECTO, UmbralesOpticos, clasificar
from ..core.reloj import RelojSistema
from .fabrica import FabricaDrivers

log = logging.getLogger(__name__)

#: Qué evento deja cada operación exitosa en la bitácora. Las que no figuran
#: acá quedan sólo en la auditoría de operaciones.
_EVENTO_DE_OPERACION: dict[TipoOperacion, TipoEvento] = {
    TipoOperacion.AUTORIZAR_ONU: TipoEvento.ONU_NUEVA,
    TipoOperacion.ELIMINAR_ONU: TipoEvento.ONU_ELIMINADA,
    TipoOperacion.REINICIAR_ONU: TipoEvento.REINICIO_ONU,
    TipoOperacion.RESTAURAR_FABRICA: TipoEvento.CAMBIO_CONFIGURACION,
    TipoOperacion.CAMBIAR_WIFI: TipoEvento.CAMBIO_CONFIGURACION,
    TipoOperacion.CAMBIAR_CLAVE_WIFI: TipoEvento.CAMBIO_CONFIGURACION,
    TipoOperacion.CAMBIAR_PPPOE: TipoEvento.CAMBIO_CONFIGURACION,
    TipoOperacion.MODO_BRIDGE: TipoEvento.CAMBIO_CONFIGURACION,
    TipoOperacion.MODO_ROUTER: TipoEvento.CAMBIO_CONFIGURACION,
}


@dataclass(frozen=True, slots=True)
class PotenciaONU:
    """Lectura óptica ya interpretada, lista para mostrar."""

    lectura: LecturaOptica
    clasificacion: ClasificacionOptica

    @property
    def rx_dbm(self) -> float | None:
        return self.lectura.rx_onu_dbm

    @property
    def perdida_db(self) -> float | None:
        return self.lectura.perdida_optica_db


class ServicioONU:
    """Consulta y administración de ONU."""

    def __init__(
        self,
        *,
        repositorio_onu: RepositorioONU,
        repositorio_operacion: RepositorioOperacion,
        repositorio_evento: RepositorioEvento,
        fabrica: FabricaDrivers,
        reloj: Reloj | None = None,
        umbrales: UmbralesOpticos = UMBRALES_POR_DEFECTO,
    ) -> None:
        self._onus = repositorio_onu
        self._operaciones = repositorio_operacion
        self._eventos = repositorio_evento
        self._fabrica = fabrica
        self._reloj = reloj or RelojSistema()
        self._umbrales = umbrales

    # --- consulta ---------------------------------------------------------

    def listar(self, olt_id: int, pon: int | None = None) -> list[ONU]:
        return self._onus.listar_de_olt(olt_id, pon)

    def obtener(self, onu_id: int) -> ONU:
        return self._onus.obtener(onu_id)

    def obtener_por_ref(self, olt_id: int, ref: RefONU) -> ONU:
        onu = self._onus.obtener_por_ref(olt_id, ref)
        if onu is None:
            raise NoEncontrado(f"No hay ninguna ONU {ref} registrada en la OLT {olt_id}")
        return onu

    def buscar_por_serie(self, numero_serie: str) -> ONU | None:
        return self._onus.obtener_por_serie(numero_serie)

    def potencia(self, olt_id: int, ref: RefONU) -> PotenciaONU:
        """Potencia actual, con su clasificación.

        La clasificación incluye la saturación: una ONU con demasiada luz
        (> −8 dBm) no está "óptima", está dañando su receptor.
        """
        with self._fabrica.sesion(olt_id) as driver:
            lectura = driver.get_signal(ref)
        return PotenciaONU(
            lectura=lectura,
            clasificacion=clasificar(lectura.rx_onu_dbm, self._umbrales),
        )

    def potencias(self, olt_id: int) -> list[PotenciaONU]:
        """Potencias de todas las ONU en una sola pasada."""
        with self._fabrica.sesion(olt_id) as driver:
            lecturas = driver.get_signals()
        return [
            PotenciaONU(
                lectura=lectura, clasificacion=clasificar(lectura.rx_onu_dbm, self._umbrales)
            )
            for lectura in lecturas
        ]

    def no_autorizadas(self, olt_id: int) -> list[ONUNoAutorizada]:
        """ONU que la OLT ve pero que todavía no están en servicio."""
        with self._fabrica.sesion(olt_id) as driver:
            return driver.discover_unauthorized_onus()

    def resumen_estado(self, olt_id: int) -> dict[str, int]:
        """Cuántas ONU hay en cada estado. Alimenta el panel principal."""
        return self._onus.contar_por_estado(olt_id)

    # --- escritura --------------------------------------------------------

    def autorizar(
        self,
        olt_id: int,
        solicitud: SolicitudAutorizacion,
        *,
        usuario: str = "sistema",
        dry_run: bool | None = None,
    ) -> ResultadoOperacion:
        """Pone una ONU en servicio.

        Expresa la intención del operador; cada driver la resuelve como puede
        en su equipo. En ZTE es un alta explícita por serial; en VSOL, donde el
        auto-learn ya la incorporó, es confirmarla y configurarla.
        """
        if not solicitud.numero_serie.strip():
            raise ErrorValidacion("La autorización requiere el número de serie de la ONU")
        if solicitud.pon <= 0:
            raise ErrorValidacion("La autorización requiere un puerto PON válido")
        return self._escribir(
            olt_id,
            Capacidad.AUTORIZAR_ONU,
            lambda driver: driver.authorize_onu(solicitud),
            usuario=usuario,
            dry_run=dry_run,
        )

    def eliminar(
        self,
        olt_id: int,
        ref: RefONU,
        *,
        usuario: str = "sistema",
        dry_run: bool | None = None,
    ) -> ResultadoOperacion:
        """Da de baja una ONU en el equipo.

        Es la operación más destructiva del módulo: deja al cliente sin
        servicio en el acto. Por eso, como todas, sale simulada salvo que se
        pida lo contrario de forma explícita.
        """
        return self._escribir(
            olt_id,
            Capacidad.ELIMINAR_ONU,
            lambda driver: driver.delete_onu(ref),
            usuario=usuario,
            dry_run=dry_run,
        )

    def reiniciar(
        self,
        olt_id: int,
        ref: RefONU,
        *,
        usuario: str = "sistema",
        dry_run: bool | None = None,
    ) -> ResultadoOperacion:
        return self._escribir(
            olt_id,
            Capacidad.REINICIAR_ONU,
            lambda driver: driver.reboot_onu(ref),
            usuario=usuario,
            dry_run=dry_run,
        )

    def restaurar_fabrica(
        self,
        olt_id: int,
        ref: RefONU,
        *,
        usuario: str = "sistema",
        dry_run: bool | None = None,
    ) -> ResultadoOperacion:
        return self._escribir(
            olt_id,
            Capacidad.RESTAURAR_FABRICA,
            lambda driver: driver.factory_reset(ref),
            usuario=usuario,
            dry_run=dry_run,
        )

    def configurar_wifi(
        self,
        olt_id: int,
        ref: RefONU,
        config: ConfigWiFi,
        *,
        usuario: str = "sistema",
        dry_run: bool | None = None,
    ) -> ResultadoOperacion:
        return self._escribir(
            olt_id,
            Capacidad.WIFI_POR_OMCI,
            lambda driver: driver.set_wifi(ref, config),
            usuario=usuario,
            dry_run=dry_run,
        )

    def cambiar_clave_wifi(
        self,
        olt_id: int,
        ref: RefONU,
        password: str,
        *,
        usuario: str = "sistema",
        dry_run: bool | None = None,
    ) -> ResultadoOperacion:
        return self._escribir(
            olt_id,
            Capacidad.WIFI_POR_OMCI,
            lambda driver: driver.change_wifi_password(ref, password),
            usuario=usuario,
            dry_run=dry_run,
        )

    def cambiar_pppoe(
        self,
        olt_id: int,
        ref: RefONU,
        credencial: CredencialPPPoE,
        *,
        usuario: str = "sistema",
        dry_run: bool | None = None,
    ) -> ResultadoOperacion:
        return self._escribir(
            olt_id,
            Capacidad.PPPOE_POR_OMCI,
            lambda driver: driver.change_pppoe(ref, credencial),
            usuario=usuario,
            dry_run=dry_run,
        )

    def modo_bridge(
        self,
        olt_id: int,
        ref: RefONU,
        vlan: int | None = None,
        *,
        usuario: str = "sistema",
        dry_run: bool | None = None,
    ) -> ResultadoOperacion:
        return self._escribir(
            olt_id,
            Capacidad.MODO_BRIDGE_ROUTER,
            lambda driver: driver.set_bridge(ref, vlan),
            usuario=usuario,
            dry_run=dry_run,
        )

    def modo_router(
        self,
        olt_id: int,
        ref: RefONU,
        credencial: CredencialPPPoE,
        vlan: int | None = None,
        *,
        usuario: str = "sistema",
        dry_run: bool | None = None,
    ) -> ResultadoOperacion:
        return self._escribir(
            olt_id,
            Capacidad.MODO_BRIDGE_ROUTER,
            lambda driver: driver.set_router(ref, credencial, vlan),
            usuario=usuario,
            dry_run=dry_run,
        )

    def respaldar_configuracion(self, olt_id: int) -> RespaldoConfiguracion:
        with self._fabrica.sesion(olt_id) as driver:
            return driver.backup_configuration()

    # --- mecánica común ---------------------------------------------------

    def _escribir(
        self,
        olt_id: int,
        capacidad: Capacidad,
        accion: Callable[[OLTDriver], ResultadoOperacion],
        *,
        usuario: str,
        dry_run: bool | None,
    ) -> ResultadoOperacion:
        """Ejecuta una escritura, la audita y registra su evento.

        Verifica la capacidad **antes** de conectarse: si el equipo no puede
        hacerlo, no tiene sentido siquiera abrir la sesión.
        """
        with self._fabrica.sesion(olt_id, dry_run=dry_run) as driver:
            if not driver.soporta(capacidad):
                raise CapacidadNoSoportada(capacidad.name, driver.fabricante)
            try:
                resultado = accion(driver)
            except ErrorGPON as exc:
                # Una operación que falló también se audita: saber qué se
                # intentó importa tanto como saber qué se logró.
                self._auditar_error(olt_id, capacidad, usuario, exc, driver.dry_run)
                raise

        self._auditar(resultado, usuario)
        if resultado.ok:
            self._registrar_evento(resultado)
        return resultado

    def _auditar(self, resultado: ResultadoOperacion, usuario: str) -> None:
        self._operaciones.registrar(
            Operacion(
                tipo=resultado.tipo,
                olt_id=resultado.olt_id,
                ref_onu=resultado.ref_onu,
                usuario=usuario,
                ok=resultado.ok,
                simulado=resultado.simulado,
                comandos=resultado.comandos_enviados,
                salida=resultado.salida_cruda,
                error=resultado.error or "",
                duracion_ms=resultado.duracion_ms,
                ejecutada_en=resultado.ejecutada_en or self._reloj.ahora(),
            )
        )

    def _auditar_error(
        self,
        olt_id: int,
        capacidad: Capacidad,
        usuario: str,
        excepcion: Exception,
        simulado: bool,
    ) -> None:
        tipo = _TIPO_POR_CAPACIDAD.get(capacidad, TipoOperacion.REINICIAR_ONU)
        self._operaciones.registrar(
            Operacion(
                tipo=tipo,
                olt_id=olt_id,
                usuario=usuario,
                ok=False,
                simulado=simulado,
                error=f"{type(excepcion).__name__}: {excepcion}",
                ejecutada_en=self._reloj.ahora(),
            )
        )

    def _registrar_evento(self, resultado: ResultadoOperacion) -> None:
        tipo_evento = _EVENTO_DE_OPERACION.get(resultado.tipo)
        if tipo_evento is None:
            return
        entidad_id = None
        if resultado.ref_onu is not None and resultado.olt_id is not None:
            onu = self._onus.obtener_por_ref(resultado.olt_id, resultado.ref_onu)
            entidad_id = onu.id if onu else None
        self._eventos.registrar(
            Evento(
                tipo=tipo_evento,
                olt_id=resultado.olt_id,
                entidad="onu",
                entidad_id=entidad_id,
                ref_onu=resultado.ref_onu,
                descripcion=(
                    f"{resultado.tipo.value}"
                    + (" (simulado)" if resultado.simulado else "")
                ),
                ocurrido_en=resultado.ejecutada_en or self._reloj.ahora(),
            )
        )

    # --- sincronía local tras una baja ------------------------------------

    def marcar_baja_local(self, olt_id: int, ref: RefONU) -> None:
        """Refleja en la base una ONU dada de baja en el equipo.

        Se llama sólo después de una eliminación real y exitosa. Nunca desde
        una lectura: que una ONU no aparezca en un walk no prueba que no exista.
        """
        onu = self._onus.obtener_por_ref(olt_id, ref)
        if onu is not None and onu.id is not None:
            self._onus.eliminar(onu.id)


_TIPO_POR_CAPACIDAD: dict[Capacidad, TipoOperacion] = {
    Capacidad.AUTORIZAR_ONU: TipoOperacion.AUTORIZAR_ONU,
    Capacidad.ELIMINAR_ONU: TipoOperacion.ELIMINAR_ONU,
    Capacidad.REINICIAR_ONU: TipoOperacion.REINICIAR_ONU,
    Capacidad.RESTAURAR_FABRICA: TipoOperacion.RESTAURAR_FABRICA,
    Capacidad.WIFI_POR_OMCI: TipoOperacion.CAMBIAR_WIFI,
    Capacidad.PPPOE_POR_OMCI: TipoOperacion.CAMBIAR_PPPOE,
    Capacidad.MODO_BRIDGE_ROUTER: TipoOperacion.MODO_BRIDGE,
}

__all__ = ["PotenciaONU", "ServicioONU"]
