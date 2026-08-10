"""Completar el inventario con lo que sólo la CLI sabe.

SNMP da el estado en vivo de cada ONU —si está en línea, su potencia óptica, su
temperatura— pero en estos equipos **no da el número de serie**, y sin serial no
se puede identificar un cliente ni autorizar nada. Eso vive en la configuración,
y la configuración se lee por CLI.

Este servicio hace un solo viaje: abre la sesión, pide ``show running-config``,
lo interpreta y completa el inventario que ya está en la base. No borra ni da de
baja nada: sólo agrega lo que faltaba.

Es de **sólo lectura** sobre el equipo, igual que ``gpon capturar``: el único
comando que envía es un ``show``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Any

from ..core.enums import Fabricante
from ..core.errors import CapacidadNoSoportada, ErrorValidacion
from ..core.models import ONU, VLAN, PerfilDBA, Perfiles, PerfilTrafico, RefONU
from ..drivers.transport import crear_transporte_cli
from ..drivers.vsol.parser_config import ConfiguracionOLT, parsear_running_config

log = logging.getLogger(__name__)

#: El único comando que este servicio manda al equipo.
COMANDO_CONFIGURACION = "show running-config"

#: Fabricantes cuya configuración este módulo sabe interpretar.
FABRICANTES_SOPORTADOS = (Fabricante.VSOL,)


@dataclass(frozen=True, slots=True)
class ResultadoInventarioCLI:
    """Qué se completó, y qué quedó sin poder completarse."""

    onus_en_configuracion: int = 0
    onus_actualizadas: int = 0
    series_nuevas: int = 0
    onus_solo_en_configuracion: tuple[str, ...] = ()
    perfiles_dba: int = 0
    perfiles_trafico: int = 0
    vlans: int = 0
    pon_sin_autoaprendizaje: tuple[str, ...] = ()

    @property
    def hubo_cambios(self) -> bool:
        return bool(self.onus_actualizadas or self.perfiles_dba or self.vlans)


class ServicioInventarioCLI:
    """Completa el inventario leyendo la configuración en vivo de la OLT."""

    def __init__(
        self,
        *,
        repositorio_olt: Any,
        repositorio_onu: Any,
        repositorio_perfiles: Any,
        fabrica_transporte: Any = crear_transporte_cli,
    ) -> None:
        self._olts = repositorio_olt
        self._onus = repositorio_onu
        self._perfiles = repositorio_perfiles
        self._fabrica_transporte = fabrica_transporte

    def importar(
        self,
        olt_id: int,
        *,
        protocolo: str = "ssh",
        timeout: float = 60.0,
        ruta_traza: str | None = None,
    ) -> ResultadoInventarioCLI:
        """Lee la configuración del equipo y completa el inventario."""
        olt = self._olts.obtener(olt_id)
        if olt.fabricante not in FABRICANTES_SOPORTADOS:
            raise CapacidadNoSoportada(
                f"lectura de configuración por CLI ({COMANDO_CONFIGURACION})", olt.fabricante
            )

        texto = self._leer_configuracion(olt, protocolo, timeout, ruta_traza)
        configuracion = parsear_running_config(texto)
        return self.aplicar(olt_id, configuracion)

    def aplicar(self, olt_id: int, configuracion: ConfiguracionOLT) -> ResultadoInventarioCLI:
        """Vuelca sobre la base una configuración ya interpretada.

        Separado de la lectura a propósito: así se puede aplicar una captura
        guardada en archivo, sin volver a tocar el equipo.
        """
        actualizadas = 0
        series_nuevas = 0
        solo_en_configuracion: list[str] = []

        for onu_configurada in configuracion.onus:
            ref = RefONU(onu_configurada.pon, onu_configurada.onu_id)
            existente: ONU | None = self._onus.obtener_por_ref(olt_id, ref)
            if existente is None:
                # Está en la configuración pero SNMP no la vio. Puede ser una
                # ONU dada de alta y todavía no conectada. No se inventa una
                # entrada: se informa, que es lo honesto.
                solo_en_configuracion.append(f"{ref} {onu_configurada.numero_serie}")
                continue

            completada = self._completar(existente, onu_configurada)
            if completada is existente:
                continue
            if not existente.numero_serie and completada.numero_serie:
                series_nuevas += 1
            self._onus.guardar(completada)
            actualizadas += 1

        perfiles = self._a_perfiles(olt_id, configuracion)
        self._perfiles.reemplazar_de_olt(olt_id, perfiles)

        return ResultadoInventarioCLI(
            onus_en_configuracion=len(configuracion.onus),
            onus_actualizadas=actualizadas,
            series_nuevas=series_nuevas,
            onus_solo_en_configuracion=tuple(solo_en_configuracion),
            perfiles_dba=len(perfiles.dba),
            perfiles_trafico=len(perfiles.trafico),
            vlans=len(perfiles.vlans),
            pon_sin_autoaprendizaje=configuracion.pon_sin_autoaprendizaje,
        )

    # --- internos ---------------------------------------------------------

    def _leer_configuracion(
        self, olt: Any, protocolo: str, timeout: float, ruta_traza: str | None
    ) -> str:
        if olt.id is None:  # pragma: no cover - el repositorio siempre lo trae
            raise ErrorValidacion("La OLT debe estar persistida")
        credenciales = self._olts.obtener_credenciales(olt.id)

        transporte = self._fabrica_transporte(
            host=olt.host,
            usuario=credenciales.usuario,
            password=credenciales.password,
            password_enable=credenciales.password_enable,
            protocolo=protocolo,
            puerto=credenciales.puerto_ssh if protocolo == "ssh" else credenciales.puerto_telnet,
            timeout=timeout,
            ruta_traza=ruta_traza,
        )
        transporte.abrir()
        try:
            return transporte.ejecutar(COMANDO_CONFIGURACION)
        finally:
            transporte.cerrar()

    @staticmethod
    def _completar(existente: ONU, configurada: Any) -> ONU:
        """Agrega a la ONU de la base lo que aporta la configuración.

        Lo que ya tiene valor no se pisa: el estado en vivo lo sabe SNMP, y la
        configuración es una foto de cómo está dada de alta, no de cómo está
        funcionando ahora.
        """
        cambios: dict[str, Any] = {}
        if configurada.numero_serie and existente.numero_serie != configurada.numero_serie:
            cambios["numero_serie"] = configurada.numero_serie
        if configurada.descripcion and existente.descripcion != configurada.descripcion:
            cambios["descripcion"] = configurada.descripcion
        if configurada.perfil and existente.perfil_servicio != configurada.perfil:
            cambios["perfil_servicio"] = configurada.perfil
        if configurada.perfil_dba and existente.perfil_linea != configurada.perfil_dba:
            cambios["perfil_linea"] = configurada.perfil_dba
        if configurada.vlan is not None and existente.vlan != configurada.vlan:
            cambios["vlan"] = configurada.vlan

        return replace(existente, **cambios) if cambios else existente

    @staticmethod
    def _a_perfiles(olt_id: int, configuracion: ConfiguracionOLT) -> Perfiles:
        return Perfiles(
            dba=tuple(
                PerfilDBA(
                    olt_id=olt_id,
                    nombre=perfil.nombre,
                    identificador_equipo=str(perfil.identificador),
                    tipo=perfil.tipo,
                    ancho_banda_fijo_kbps=perfil.fijo_kbps,
                    ancho_banda_asegurado_kbps=perfil.asegurado_kbps,
                    ancho_banda_maximo_kbps=perfil.maximo_kbps,
                )
                for perfil in configuracion.perfiles_dba
            ),
            trafico=tuple(
                PerfilTrafico(
                    olt_id=olt_id,
                    nombre=perfil.nombre,
                    identificador_equipo=str(perfil.identificador),
                )
                for perfil in configuracion.perfiles_trafico
            ),
            vlans=tuple(VLAN(olt_id=olt_id, vlan_id=vlan_id) for vlan_id in configuracion.vlans),
        )
