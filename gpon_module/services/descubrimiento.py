"""Servicio de descubrimiento.

Lee todo lo que la OLT sabe de sí misma —identidad, puertos, ONU, perfiles— y
lo persiste. Es la operación que convierte una dirección IP en un inventario.

La regla que gobierna este servicio: **una lectura incompleta no es una baja
masiva**. Si el walk viene truncado o la sesión se corta, se guarda lo leído,
la corrida queda marcada como parcial y no se concluye nada sobre lo que no se
alcanzó a ver. Este error ya ocurrió en producción con Pucará y no se repite.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, replace
from datetime import datetime

from ..core.enums import (
    Capacidad,
    EstadoOLT,
    NivelSincronizacion,
    ResultadoSincronizacion,
    TipoEvento,
)
from ..core.errors import CapacidadNoSoportada, ErrorLecturaParcial, ErrorTransporte
from ..core.interfaces import (
    OLTDriver,
    Reloj,
    RepositorioEvento,
    RepositorioOLT,
    RepositorioONU,
    RepositorioPuertoPON,
    RepositorioSincronizacion,
)
from ..core.models import OLT, ONU, Evento, ONUNoAutorizada, Perfiles, PuertoPON, Sincronizacion
from ..core.reloj import RelojSistema
from ..database.repositories.perfiles import RepositorioPerfilesSQL
from .fabrica import FabricaDrivers

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ResultadoDescubrimiento:
    """Qué se encontró y con qué grado de confianza.

    ``completo=False`` es información de primer orden: significa que lo que no
    aparece acá **no** puede darse por inexistente.
    """

    olt: OLT
    resultado: ResultadoSincronizacion
    puertos: tuple[PuertoPON, ...] = ()
    onus: tuple[ONU, ...] = ()
    no_autorizadas: tuple[ONUNoAutorizada, ...] = ()
    perfiles: Perfiles = field(default_factory=Perfiles)
    onus_nuevas: int = 0
    onus_leidas: int = 0
    onus_esperadas: int | None = None
    advertencias: tuple[str, ...] = ()
    duracion_ms: int = 0

    @property
    def completo(self) -> bool:
        return self.resultado is ResultadoSincronizacion.COMPLETA

    @property
    def fallido(self) -> bool:
        """No se pudo leer nada. Distinto de "no hay nada"."""
        return self.resultado is ResultadoSincronizacion.FALLIDA


class ServicioDescubrimiento:
    """Descubre y persiste todo lo que la OLT expone."""

    def __init__(
        self,
        *,
        repositorio_olt: RepositorioOLT,
        repositorio_onu: RepositorioONU,
        repositorio_puerto: RepositorioPuertoPON,
        repositorio_evento: RepositorioEvento,
        repositorio_sincronizacion: RepositorioSincronizacion,
        repositorio_perfiles: RepositorioPerfilesSQL,
        fabrica: FabricaDrivers,
        reloj: Reloj | None = None,
    ) -> None:
        self._olts = repositorio_olt
        self._onus = repositorio_onu
        self._puertos = repositorio_puerto
        self._eventos = repositorio_evento
        self._sincronizaciones = repositorio_sincronizacion
        self._perfiles = repositorio_perfiles
        self._fabrica = fabrica
        self._reloj = reloj or RelojSistema()

    # --- API pública ------------------------------------------------------

    def descubrir(self, olt_id: int) -> ResultadoDescubrimiento:
        """Recorre la OLT entera y actualiza la base.

        Nunca levanta excepción por una capacidad ausente: si el equipo no
        expone algo, queda como advertencia y el resto del descubrimiento sigue.
        """
        inicio_reloj = time.monotonic()
        inicio = self._reloj.ahora()
        olt = self._olts.obtener(olt_id)
        # Dos listas distintas a propósito. Una limitación conocida del equipo
        # (VSOL no expone las ONU sin autorizar por SNMP) no vuelve incompleta
        # una corrida: si lo hiciera, toda lectura de una VSOL quedaría marcada
        # como parcial y la marca dejaría de significar algo.
        advertencias: list[str] = []
        fallas: list[str] = []
        puertos: list[PuertoPON] = []
        onus: list[ONU] = []
        no_autorizadas: list[ONUNoAutorizada] = []
        perfiles = Perfiles()
        identidad_ok = False
        inventario_ok = False
        esperadas: int | None = None

        try:
            with self._fabrica.sesion(olt_id) as driver:
                olt, identidad_ok = self._descubrir_identidad(driver, olt, fallas)
                puertos = self._descubrir_puertos(driver, olt, advertencias, fallas)
                onus, inventario_ok, esperadas = self._descubrir_onus(
                    driver, olt, advertencias, fallas
                )
                no_autorizadas = self._descubrir_no_autorizadas(driver, advertencias, fallas)
                perfiles = self._descubrir_perfiles(driver, olt, advertencias, fallas)
        except ErrorTransporte as exc:
            # No se pudo ni abrir la sesión. Es un resultado, no una excepción
            # que deba propagarse: queda registrado y no se toca el inventario.
            fallas.append(f"No se pudo establecer la sesión: {exc}")

        # Que no se haya leído nada no prueba que no haya nada. Sólo prueba que
        # no se pudo mirar.
        nada_leido = not (identidad_ok or puertos or onus)
        if nada_leido:
            resultado = ResultadoSincronizacion.FALLIDA
        elif inventario_ok and identidad_ok and not fallas:
            resultado = ResultadoSincronizacion.COMPLETA
        else:
            resultado = ResultadoSincronizacion.PARCIAL
        completo = resultado is ResultadoSincronizacion.COMPLETA

        nuevas = self._persistir_onus(olt, onus, inicio)
        olt = self._olts.actualizar(
            replace(
                olt,
                cantidad_pon=len(puertos) or olt.cantidad_pon,
                # Con una lectura incompleta no se pisa el total conocido: sería
                # convertir un problema de red en una baja masiva en la base.
                cantidad_onus=len(onus) if inventario_ok else olt.cantidad_onus,
                estado=EstadoOLT.EN_LINEA if completo else _estado_degradado(resultado),
                ultima_sincronizacion=inicio,
            )
        )

        duracion_ms = int((time.monotonic() - inicio_reloj) * 1000)
        self._sincronizaciones.registrar(
            Sincronizacion(
                olt_id=olt_id,
                nivel=NivelSincronizacion.MEDIO,
                resultado=resultado,
                onus_leidas=len(onus),
                onus_esperadas=esperadas,
                eventos_generados=nuevas,
                detalle=" | ".join(fallas + advertencias),
                iniciada_en=inicio,
                finalizada_en=self._reloj.ahora(),
                duracion_ms=duracion_ms,
            )
        )

        if not completo:
            log.warning(
                "Descubrimiento %s en %s: %d de %s ONU. No se infiere ninguna baja.",
                resultado.value.upper(),
                olt.host,
                len(onus),
                esperadas if esperadas is not None else "?",
            )

        return ResultadoDescubrimiento(
            olt=olt,
            resultado=resultado,
            puertos=tuple(puertos),
            onus=tuple(onus),
            no_autorizadas=tuple(no_autorizadas),
            perfiles=perfiles,
            onus_nuevas=nuevas,
            onus_leidas=len(onus),
            onus_esperadas=esperadas,
            advertencias=tuple(fallas + advertencias),
            duracion_ms=duracion_ms,
        )

    # --- pasos ------------------------------------------------------------

    def _descubrir_identidad(
        self, driver: OLTDriver, olt: OLT, fallas: list[str]
    ) -> tuple[OLT, bool]:
        """Lee la identidad del equipo. Si falla, el descubrimiento sigue igual.

        Un timeout leyendo el modelo no puede abortar la corrida entera: lo que
        importa —el inventario y las potencias— puede leerse perfectamente bien
        aunque esta consulta haya fallado.
        """
        try:
            info = driver.get_system_info()
        except ErrorTransporte as exc:
            fallas.append(f"No se pudo leer la identidad del equipo: {exc}")
            return olt, False
        return (
            replace(
                olt,
                modelo=info.modelo or olt.modelo,
                firmware=info.firmware or olt.firmware,
                numero_serie=info.numero_serie or olt.numero_serie,
                mac=info.mac or olt.mac,
                uptime_segundos=info.uptime_segundos,
            ),
            True,
        )

    def _descubrir_puertos(
        self, driver: OLTDriver, olt: OLT, advertencias: list[str], fallas: list[str]
    ) -> list[PuertoPON]:
        try:
            puertos = driver.discover_ports()
        except CapacidadNoSoportada as exc:
            advertencias.append(f"Puertos PON no disponibles: {exc}")
            return []
        except ErrorLecturaParcial as exc:
            fallas.append(f"Lectura parcial de puertos PON: {exc}")
            return []
        except ErrorTransporte as exc:
            fallas.append(f"No se pudieron leer los puertos PON: {exc}")
            return []
        puertos = [replace(p, olt_id=olt.id) for p in puertos]
        return self._puertos.reemplazar_de_olt(olt.id, puertos)  # type: ignore[arg-type]

    def _descubrir_onus(
        self, driver: OLTDriver, olt: OLT, advertencias: list[str], fallas: list[str]
    ) -> tuple[list[ONU], bool, int | None]:
        """Lee el inventario de ONU y dice si la lectura fue completa.

        Ante una lectura truncada devuelve lo que sí se leyó y ``completo=False``.
        Ante un timeout devuelve vacío y ``completo=False``: un timeout no es
        "no hay ONU", es "no sé".
        """
        try:
            onus = driver.discover_onus()
        except ErrorLecturaParcial as exc:
            fallas.append(
                f"Lectura parcial del inventario: {exc.obtenidos} de "
                f"{exc.esperados if exc.esperados is not None else '?'} ONU"
            )
            return [], False, exc.esperados
        except ErrorTransporte as exc:
            fallas.append(f"No se pudo leer el inventario de ONU: {exc}")
            return [], False, None
        except CapacidadNoSoportada as exc:
            advertencias.append(f"Inventario de ONU no disponible: {exc}")
            return [], False, None
        return onus, True, len(onus)

    def _descubrir_no_autorizadas(
        self, driver: OLTDriver, advertencias: list[str], fallas: list[str]
    ) -> list[ONUNoAutorizada]:
        try:
            return driver.discover_unauthorized_onus()
        except CapacidadNoSoportada:
            # En VSOL el serial no viene por SNMP, así que esto exige CLI. Que
            # no esté disponible es una limitación conocida, no un error.
            advertencias.append(
                "Este equipo no expone las ONU sin autorizar por el canal disponible"
            )
            return []
        except ErrorTransporte as exc:
            fallas.append(f"No se pudieron leer las ONU sin autorizar: {exc}")
            return []

    def _descubrir_perfiles(
        self, driver: OLTDriver, olt: OLT, advertencias: list[str], fallas: list[str]
    ) -> Perfiles:
        if not driver.soporta(Capacidad.DESCUBRIR_PERFILES):
            advertencias.append("Este equipo no expone sus perfiles")
            return Perfiles()
        try:
            perfiles = driver.get_profiles()
        except ErrorTransporte as exc:
            fallas.append(f"No se pudieron leer los perfiles: {exc}")
            return Perfiles()
        return self._perfiles.reemplazar_de_olt(olt.id, perfiles)  # type: ignore[arg-type]

    def _persistir_onus(self, olt: OLT, onus: list[ONU], momento: datetime) -> int:
        """Guarda el inventario y registra las ONU que aparecieron por primera vez."""
        if not onus:
            return 0
        conocidas = {o.ref for o in self._onus.listar_de_olt(olt.id)}  # type: ignore[arg-type]
        eventos: list[Evento] = []
        for onu in onus:
            guardada = self._onus.guardar(
                replace(onu, olt_id=olt.id, ultima_vez_vista=momento)
            )
            if onu.ref not in conocidas:
                eventos.append(
                    Evento(
                        tipo=TipoEvento.ONU_NUEVA,
                        olt_id=olt.id,
                        entidad="onu",
                        entidad_id=guardada.id,
                        ref_onu=onu.ref,
                        descripcion=(
                            f"ONU {onu.ref} descubierta"
                            + (f" (serie {onu.numero_serie})" if onu.numero_serie else "")
                        ),
                        valor_nuevo=str(onu.estado),
                        ocurrido_en=momento,
                    )
                )
        self._eventos.registrar_muchos(eventos)
        return len(eventos)


def _estado_degradado(resultado: ResultadoSincronizacion) -> EstadoOLT:
    """Una corrida fallida deja la OLT fuera de línea; una parcial, degradada."""
    return (
        EstadoOLT.FUERA_DE_LINEA
        if resultado is ResultadoSincronizacion.FALLIDA
        else EstadoOLT.DEGRADADA
    )
