"""Dar de baja una ONU de la OLT.

Es la operación más destructiva del módulo: deja al cliente sin servicio en el
momento en que se ejecuta, y el equipo no pregunta dos veces. Por eso acá el
cuidado no está puesto en que el comando salga, sino en **confirmar qué se está
borrando** antes de que salga.

* ``dry_run`` por defecto, como todo lo que escribe.
* Se lee el puerto primero y se informa el serial que hay en ese índice. Que el
  índice exista no alcanza: el operador tiene que poder ver que el 29 del PON 1
  es la ONU que él cree que es, y no la de otro cliente.
* Si se indica un serial esperado y no coincide con el que está en el equipo,
  no se borra nada. Esa comprobación es la que evita dejar sin internet a un
  vecino por un dígito mal tipeado.

El uso previsto es limpiar un alta que quedó a medias: la secuencia de alta se
aborta en el primer rechazo, y lo que quedó escrito hasta ahí hay que sacarlo
antes de reintentar.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from ..core.enums import Fabricante, TipoOperacion
from ..core.errors import CapacidadNoSoportada, ErrorComando, ErrorValidacion
from ..core.models import Operacion, RefONU
from ..drivers.transport import crear_transporte_cli
from ..drivers.vsol.comandos_alta import secuencia_baja
from ..drivers.vsol.parser_tablas import parsear_onu_info

log = logging.getLogger(__name__)

FABRICANTES_SOPORTADOS = (Fabricante.VSOL,)
COMANDO_INVENTARIO = "show onu info"


@dataclass(frozen=True, slots=True)
class ResultadoBaja:
    """Qué se borró, o qué se habría borrado."""

    pon: int
    onu_id: int
    comandos: tuple[str, ...]
    simulado: bool
    #: El serial que el equipo reporta en ese índice, si lo reporta. Es el dato
    #: que le permite al operador confirmar que va a borrar lo que quiere.
    numero_serie: str = ""
    ok: bool = True
    error: str = ""
    comando_que_fallo: str = ""


class ServicioBajaONU:
    """Elimina una ONU de un puerto PON."""

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

    def eliminar(
        self,
        olt_id: int,
        *,
        pon: int,
        onu_id: int,
        numero_serie_esperado: str = "",
        dry_run: bool = True,
        protocolo: str = "ssh",
        timeout: float = 30.0,
        usuario: str = "",
        ruta_traza: str | None = None,
    ) -> ResultadoBaja:
        """Da de baja la ONU ``onu_id`` del puerto ``pon``."""
        olt = self._olts.obtener(olt_id)
        if olt.fabricante not in FABRICANTES_SOPORTADOS:
            raise CapacidadNoSoportada("baja de ONU por CLI", olt.fabricante)

        comandos = secuencia_baja(pon, onu_id)
        transporte = self._crear_transporte(olt, olt_id, protocolo, timeout, ruta_traza)

        transporte.abrir()
        try:
            transporte.ejecutar("configure terminal")
            transporte.ejecutar(f"interface gpon 0/{pon}")
            serie = self._serie_en_el_indice(transporte, onu_id)
            self._confirmar_que_es_la_correcta(pon, onu_id, serie, numero_serie_esperado)

            if dry_run:
                log.info("Baja simulada de %s:%s: no se envió nada", pon, onu_id)
                resultado = ResultadoBaja(
                    pon=pon,
                    onu_id=onu_id,
                    comandos=comandos,
                    simulado=True,
                    numero_serie=serie,
                )
            else:
                # La sesión ya está adentro del puerto: se aplica desde acá, sin
                # repetir la navegación que el equipo rechazaría.
                resultado = self._aplicar(transporte, pon, onu_id, comandos, serie)
        finally:
            self._volver_a_exec(transporte)
            transporte.cerrar()

        self._auditar(olt_id, resultado, usuario)
        return resultado

    # --- verificaciones previas -------------------------------------------

    @staticmethod
    def _serie_en_el_indice(transporte: Any, onu_id: int) -> str:
        """Pregunta qué ONU hay en ese índice, para poder mostrarla."""
        try:
            salida = transporte.ejecutar(COMANDO_INVENTARIO)
        except ErrorComando as exc:  # pragma: no cover - el puerto ya respondió
            log.warning("No se pudo leer el inventario del puerto: %s", exc)
            return ""
        for informada in parsear_onu_info(salida):
            if informada.onu_id == onu_id:
                return informada.numero_serie
        return ""

    @staticmethod
    def _confirmar_que_es_la_correcta(
        pon: int, onu_id: int, serie: str, esperado: str
    ) -> None:
        """Compara con el serial que el operador dijo esperar.

        Un alta a medias puede haber dejado la ONU declarada sin llegar a
        aparecer en el inventario, así que un índice vacío no bloquea la baja:
        justamente ese es el caso que hay que poder limpiar. Lo que sí bloquea
        es encontrar **otra** ONU, que es el error caro.
        """
        buscado = esperado.strip().upper()
        if not buscado or not serie:
            return
        if serie.upper() != buscado:
            raise ErrorValidacion(
                f"En {pon}:{onu_id} hay la ONU {serie}, no {buscado}. No se borró nada.\n"
                "Revisá el índice antes de reintentar: dar de baja la ONU equivocada "
                "deja sin servicio a otro cliente."
            )

    # --- escritura ---------------------------------------------------------

    def _aplicar(
        self,
        transporte: Any,
        pon: int,
        onu_id: int,
        comandos: tuple[str, ...],
        serie: str,
    ) -> ResultadoBaja:
        comando = f"no onu {onu_id}"
        try:
            transporte.ejecutar(comando)
        except ErrorComando as exc:
            log.error("La baja de %s:%s fue rechazada: %s", pon, onu_id, exc)
            return ResultadoBaja(
                pon=pon,
                onu_id=onu_id,
                comandos=comandos,
                simulado=False,
                numero_serie=serie,
                ok=False,
                error=str(exc),
                comando_que_fallo=comando,
            )
        log.warning("ONU %s:%s (%s) dada de baja", pon, onu_id, serie or "sin serial")
        return ResultadoBaja(
            pon=pon,
            onu_id=onu_id,
            comandos=comandos,
            simulado=False,
            numero_serie=serie,
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

    def _auditar(self, olt_id: int, resultado: ResultadoBaja, usuario: str) -> None:
        """Una baja sin registro es un cliente caído sin explicación."""
        if self._operaciones is None:
            return
        try:
            self._operaciones.registrar(
                Operacion(
                    tipo=TipoOperacion.ELIMINAR_ONU,
                    olt_id=olt_id,
                    ref_onu=RefONU(resultado.pon, resultado.onu_id),
                    usuario=usuario or "modulo-gpon",
                    ok=resultado.ok,
                    simulado=resultado.simulado,
                    comandos=resultado.comandos,
                    error=resultado.error,
                    ejecutada_en=self._reloj.ahora() if self._reloj is not None else None,
                )
            )
        except Exception as exc:
            log.error(
                "No se pudo auditar la baja de %s:%s: %s", resultado.pon, resultado.onu_id, exc
            )


__all__ = ["ResultadoBaja", "ServicioBajaONU"]
