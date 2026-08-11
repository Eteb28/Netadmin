"""Las ONU que están esperando ser autorizadas.

Es el primer paso de dar de alta un cliente, y hoy se hace a mano: el técnico
instala la ONU y manda el número de serie; el operador lo busca en la pantalla
"ONU AutoFind" de la web del equipo y la agrega.

Este servicio hace la parte de buscar. Recorre los puertos PON, pide
``show onu auto-find`` en cada uno y devuelve lo que encontró, todo en una sola
sesión. Sigue siendo **de sólo lectura**: autorizar es otra cosa y llega
después.

El comando vive dentro de ``interface gpon 0/N``, así que hay que entrar a modo
configuración para leerlo. No se ejecuta ahí ningún comando de configuración, y
se sale con ``end`` pase lo que pase.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..core.enums import Fabricante
from ..core.errors import CapacidadNoSoportada, ErrorComando, ErrorGPON
from ..drivers.transport import crear_transporte_cli
from ..drivers.vsol.parser_tablas import ONUPendiente, parsear_onu_auto_find

log = logging.getLogger(__name__)

COMANDO_PENDIENTES = "show onu auto-find"
FABRICANTES_SOPORTADOS = (Fabricante.VSOL,)


def es_lista_vacia(error: ErrorComando) -> bool:
    """¿El rechazo es el que da el equipo cuando no hay ninguna ONU esperando?

    Verificado en la OLT de Belgrano: con una ONU esperando, ``show onu
    auto-find`` devuelve la tabla; sin ninguna, contesta un ``Error:`` pelado en
    vez de una tabla vacía. Tomarlo como falla del puerto haría que la pantalla
    dijera "no se pudieron leer los 8 puertos" todos los días en que no hay
    altas pendientes, que es la mayoría.

    Se acota a propósito: sólo el ``Error:`` sin más texto. Cualquier otro
    rechazo —sintaxis, puerto inexistente, sesión caída— sigue siendo una falla
    y se informa como tal.

    Si la suposición fuera errónea, el costo es acotado y se nota solo: el
    operador está buscando un serial concreto que el técnico acaba de instalar,
    y lo que vería es "no hay ninguna esperando" en vez de un error de puerto.
    """
    texto = str(error)
    return "Error:" in texto and "Invalid" not in texto and "Unknown" not in texto


@dataclass(frozen=True, slots=True)
class ResultadoPendientes:
    olt_id: int
    host: str
    momento: datetime
    pendientes: tuple[ONUPendiente, ...] = ()
    #: Puertos que no se pudieron leer, con su motivo. Se informan en vez de
    #: quedar en silencio: un puerto que falló no es un puerto sin ONU nuevas.
    puertos_con_falla: tuple[tuple[str, str], ...] = ()

    @property
    def completo(self) -> bool:
        return not self.puertos_con_falla

    def buscar(self, numero_serie: str) -> ONUPendiente | None:
        """Encuentra por serial, que es como llega el dato del técnico."""
        buscado = numero_serie.strip().upper()
        for pendiente in self.pendientes:
            if pendiente.numero_serie.upper() == buscado:
                return pendiente
        return None


class ServicioPendientes:
    """Busca las ONU detectadas y sin autorizar, puerto por puerto."""

    def __init__(
        self,
        repositorio_olt: Any,
        *,
        reloj: Any,
        fabrica_transporte: Any = crear_transporte_cli,
    ) -> None:
        self._olts = repositorio_olt
        self._reloj = reloj
        self._fabrica_transporte = fabrica_transporte

    def listar(
        self,
        olt_id: int,
        *,
        puertos: tuple[str, ...] = (),
        protocolo: str = "ssh",
        timeout: float = 30.0,
        ruta_traza: str | None = None,
    ) -> ResultadoPendientes:
        """Recorre los puertos PON y junta lo que está esperando autorización."""
        olt = self._olts.obtener(olt_id)
        if olt.fabricante not in FABRICANTES_SOPORTADOS:
            raise CapacidadNoSoportada(
                f"listado de ONU pendientes ({COMANDO_PENDIENTES})", olt.fabricante
            )

        a_recorrer = puertos or tuple(f"0/{numero}" for numero in range(1, 9))
        credenciales = self._olts.obtener_credenciales(olt_id)
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

        encontradas: list[ONUPendiente] = []
        vistas: set[tuple[int, str]] = set()
        fallas: list[tuple[str, str]] = []

        transporte.abrir()
        try:
            transporte.ejecutar("configure terminal")
            for pon in a_recorrer:
                try:
                    transporte.ejecutar(f"interface gpon {pon}")
                    salida = transporte.ejecutar(COMANDO_PENDIENTES)
                except ErrorComando as exc:
                    # Sin ONU esperando, este firmware contesta 'Error:' en vez
                    # de una tabla vacía. Eso es un puerto sin novedades, no un
                    # puerto que no se pudo leer.
                    if es_lista_vacia(exc):
                        log.debug("PON %s sin ONU esperando (%s)", pon, exc)
                        continue
                    # Un puerto que no existe en este chasis no es una falla del
                    # recorrido: se anota y se sigue con los demás.
                    fallas.append((pon, str(exc)))
                    continue
                except ErrorGPON as exc:
                    fallas.append((pon, f"{type(exc).__name__}: {exc}"))
                    continue
                for pendiente in parsear_onu_auto_find(salida):
                    # Sin deduplicar, un equipo que conteste la lista completa
                    # en cada puerto ofrecería la misma ONU ocho veces, y el
                    # operador no sabría cuál de las ocho es la buena.
                    clave = (pendiente.pon, pendiente.numero_serie.upper())
                    if clave not in vistas:
                        vistas.add(clave)
                        encontradas.append(pendiente)
        finally:
            try:
                transporte.ejecutar("end")
            except ErrorGPON as exc:  # pragma: no cover - sólo si la sesión ya murió
                log.warning("No se pudo volver al modo EXEC: %s", exc)
            transporte.cerrar()

        return ResultadoPendientes(
            olt_id=olt_id,
            host=olt.host,
            momento=self._reloj.ahora(),
            pendientes=tuple(encontradas),
            puertos_con_falla=tuple(fallas),
        )
