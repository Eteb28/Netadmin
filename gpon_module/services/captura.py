"""Captura de la CLI de una OLT: qué comandos existen y qué devuelven.

Este servicio existe por una razón muy concreta. Para autorizar y configurar
ONU hay que hablar CLI —en VSOL el número de serie no viaja por SNMP, y menos
todavía el aprovisionamiento—, y la sintaxis exacta cambia entre versiones de
firmware. Escribir un comando de configuración a partir de un manual de otra
versión es exactamente el error que deja clientes sin servicio.

Así que primero se le pregunta al equipo. La captura:

* pide la **ayuda en línea** (``?``), que enumera la sintaxis real sin ejecutar
  absolutamente nada;
* prueba una lista de comandos **de sólo lectura** y guarda la salida cruda;
* registra también los rechazos, que son información igual de útil: dicen qué
  comando *no* existe en ese firmware.

Y sobre todo, lo que **no** hace: no envía un solo comando de escritura. Hay un
filtro explícito que lo impide, y no se puede saltear por parámetro. Un comando
que no esté en la lista blanca no sale de acá.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from ..core.enums import Fabricante
from ..core.errors import ErrorComando, ErrorGPON, ErrorValidacion
from ..core.interfaces import RepositorioOLT
from ..drivers.catalogo import ComandoCandidato, ayudas_de, catalogo_de
from ..drivers.transport import crear_transporte_cli

log = logging.getLogger(__name__)

#: Únicos verbos que la captura tiene permitido enviar. Todo lo demás se
#: rechaza antes de tocar la red, aunque venga de un catálogo o del usuario.
#: Es la barrera que hace que esta herramienta sea segura de correr en
#: producción a cualquier hora.
VERBOS_PERMITIDOS: frozenset[str] = frozenset({"show", "display", "dir", "get"})

#: Palabras que descalifican un comando aunque empiece con un verbo permitido
#: (``show`` seguido de un ``|`` que redirige, por ejemplo).
FRAGMENTOS_PROHIBIDOS: tuple[str, ...] = ("|", ">", ";", "&", "\n", "\r", "delete", "erase")


def es_solo_lectura(comando: str) -> bool:
    """¿Este comando es inofensivo?

    Criterio deliberadamente estrecho: ante la duda, no. Un ``show`` de más que
    no se corre no cuesta nada; un comando de escritura que se cuela, sí.
    """
    limpio = comando.strip()
    if not limpio:
        return False
    if any(fragmento in limpio for fragmento in FRAGMENTOS_PROHIBIDOS):
        return False
    return limpio.split()[0].lower() in VERBOS_PERMITIDOS


class TransporteCLI(Protocol):
    """Lo que la captura necesita de un transporte, y nada más."""

    def abrir(self) -> None: ...

    def cerrar(self) -> None: ...

    def ejecutar(self, comando: str) -> str: ...

    def ayuda(self, prefijo: str = "") -> str: ...


@dataclass(frozen=True, slots=True)
class SalidaComando:
    """Resultado de un comando de la captura."""

    comando: str
    proposito: str = ""
    grupo: str = "general"
    salida: str = ""
    ok: bool = False
    error: str = ""
    duracion_ms: int = 0

    @property
    def tiene_datos(self) -> bool:
        return self.ok and bool(self.salida.strip())


@dataclass(frozen=True, slots=True)
class Captura:
    """Todo lo que la OLT contestó, listo para leer o para mandar."""

    olt_id: int
    host: str
    fabricante: Fabricante
    protocolo: str
    momento: datetime
    ayudas: tuple[SalidaComando, ...] = field(default_factory=tuple)
    comandos: tuple[SalidaComando, ...] = field(default_factory=tuple)

    @property
    def aceptados(self) -> tuple[SalidaComando, ...]:
        return tuple(s for s in self.comandos if s.tiene_datos)

    @property
    def rechazados(self) -> tuple[SalidaComando, ...]:
        return tuple(s for s in self.comandos if not s.ok)

    def a_texto(self) -> str:
        """Vuelca la captura completa en texto plano, con encabezado.

        El formato está pensado para que el archivo se pueda mandar tal cual:
        cada bloque dice qué comando lo produjo y qué se buscaba con él.
        """
        partes = [
            "=" * 78,
            f"CAPTURA CLI — OLT #{self.olt_id} ({self.host})",
            f"Fabricante : {self.fabricante}",
            f"Protocolo  : {self.protocolo}",
            f"Fecha      : {self.momento.isoformat()}",
            f"Comandos   : {len(self.aceptados)} con datos, "
            f"{len(self.rechazados)} rechazados, {len(self.comandos)} probados",
            "",
            "Sólo se enviaron comandos de lectura. Ninguna configuración fue",
            "modificada por esta captura.",
            "=" * 78,
        ]

        if self.ayudas:
            partes += ["", "#" * 78, "# AYUDA EN LÍNEA DEL EQUIPO ('?')", "#" * 78]
            for ayuda in self.ayudas:
                etiqueta = f"'{ayuda.comando}?'" if ayuda.comando else "'?' (modo privilegiado)"
                partes += ["", "-" * 78, f"--- {etiqueta}", "-" * 78, ayuda.salida or "(vacío)"]

        partes += ["", "#" * 78, "# SALIDA DE LOS COMANDOS", "#" * 78]
        for salida in self.comandos:
            partes += [
                "",
                "-" * 78,
                f"--- $ {salida.comando}",
                f"--- {salida.proposito} [{salida.grupo}] · {salida.duracion_ms} ms",
                "-" * 78,
            ]
            if salida.ok:
                partes.append(salida.salida or "(salida vacía)")
            else:
                partes.append(f"NO DISPONIBLE EN ESTE FIRMWARE: {salida.error}")

        return "\n".join(partes) + "\n"


class ServicioCaptura:
    """Abre una sesión CLI y registra lo que el equipo sabe contestar."""

    def __init__(
        self,
        repositorio_olt: RepositorioOLT,
        *,
        reloj: Any,
        fabrica_transporte: Any = crear_transporte_cli,
    ) -> None:
        self._olts = repositorio_olt
        self._reloj = reloj
        self._fabrica_transporte = fabrica_transporte

    def capturar(
        self,
        olt_id: int,
        *,
        protocolo: str = "telnet",
        comandos: Sequence[str] | None = None,
        incluir_ayuda: bool = True,
        timeout: float = 20.0,
        al_avanzar: Any = None,
    ) -> Captura:
        """Corre la captura contra la OLT y devuelve todo lo obtenido.

        ``al_avanzar`` recibe cada ``SalidaComando`` apenas se completa, para
        poder mostrar progreso: una captura contra un equipo con 283 ONU tarda
        varios minutos y quedarse mirando una pantalla quieta no ayuda.
        """
        olt = self._olts.obtener(olt_id)
        if olt.id is None:  # pragma: no cover - el repositorio siempre lo trae
            raise ErrorValidacion("La OLT debe estar persistida")
        credenciales = self._olts.obtener_credenciales(olt.id)

        candidatos = self._resolver_candidatos(olt.fabricante, comandos)
        prefijos_ayuda = ayudas_de(olt.fabricante) if incluir_ayuda else ()

        transporte = self._fabrica_transporte(
            host=olt.host,
            usuario=credenciales.usuario,
            password=credenciales.password,
            password_enable=credenciales.password_enable,
            protocolo=protocolo,
            puerto=credenciales.puerto_ssh if protocolo == "ssh" else credenciales.puerto_telnet,
            timeout=timeout,
        )

        ayudas: list[SalidaComando] = []
        salidas: list[SalidaComando] = []

        transporte.abrir()
        try:
            for prefijo in prefijos_ayuda:
                resultado = self._pedir_ayuda(transporte, prefijo)
                ayudas.append(resultado)
                if al_avanzar is not None:
                    al_avanzar(resultado)

            for candidato in candidatos:
                resultado = self._correr(transporte, candidato)
                salidas.append(resultado)
                if al_avanzar is not None:
                    al_avanzar(resultado)
        finally:
            transporte.cerrar()

        return Captura(
            olt_id=olt.id,
            host=olt.host,
            fabricante=olt.fabricante,
            protocolo=protocolo,
            momento=self._reloj.ahora(),
            ayudas=tuple(ayudas),
            comandos=tuple(salidas),
        )

    # --- internos ---------------------------------------------------------

    @staticmethod
    def _resolver_candidatos(
        fabricante: Fabricante, comandos: Sequence[str] | None
    ) -> tuple[ComandoCandidato, ...]:
        if comandos is None:
            candidatos = catalogo_de(fabricante)
        else:
            candidatos = tuple(
                ComandoCandidato(comando=c, proposito="pedido a mano", grupo="manual")
                for c in comandos
            )

        # El filtro se aplica al catálogo propio con el mismo rigor que a lo
        # que venga de afuera: un error de tipeo en el catálogo no debe poder
        # convertirse en un comando de configuración.
        prohibidos = [c.comando for c in candidatos if not es_solo_lectura(c.comando)]
        if prohibidos:
            raise ErrorValidacion(
                "La captura sólo envía comandos de lectura "
                f"({', '.join(sorted(VERBOS_PERMITIDOS))}). Rechazados: {', '.join(prohibidos)}"
            )
        return candidatos

    def _correr(self, transporte: TransporteCLI, candidato: ComandoCandidato) -> SalidaComando:
        inicio = time.monotonic()
        try:
            salida = transporte.ejecutar(candidato.comando)
        except ErrorComando as exc:
            # Que el equipo rechace el comando es un resultado esperado y útil:
            # significa "esa sintaxis no existe en este firmware".
            return self._resultado(candidato, inicio, ok=False, error=str(exc))
        except ErrorGPON as exc:
            log.warning("Falló '%s': %s", candidato.comando, exc)
            detalle = f"{type(exc).__name__}: {exc}"
            return self._resultado(candidato, inicio, ok=False, error=detalle)
        return self._resultado(candidato, inicio, ok=True, salida=salida)

    def _pedir_ayuda(self, transporte: TransporteCLI, prefijo: str) -> SalidaComando:
        candidato = ComandoCandidato(prefijo, "Ayuda en línea del equipo", "ayuda")
        inicio = time.monotonic()
        try:
            salida = transporte.ayuda(prefijo)
        except ErrorGPON as exc:
            return self._resultado(candidato, inicio, ok=False, error=str(exc))
        return self._resultado(candidato, inicio, ok=True, salida=salida)

    @staticmethod
    def _resultado(
        candidato: ComandoCandidato,
        inicio: float,
        *,
        ok: bool,
        salida: str = "",
        error: str = "",
    ) -> SalidaComando:
        return SalidaComando(
            comando=candidato.comando,
            proposito=candidato.proposito,
            grupo=candidato.grupo,
            salida=salida,
            ok=ok,
            error=error,
            duracion_ms=int((time.monotonic() - inicio) * 1000),
        )
