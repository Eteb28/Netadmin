"""Explorar los modos de la CLI para encontrar los comandos de GPON.

La captura del modo EXEC dejó una sorpresa: en este firmware ``show`` sólo tiene
comandos de switch —access-list, spanning-tree, vlan— y ni uno de GPON. Los
comandos que interesan (listar las ONU pendientes, autorizarlas) viven en otro
modo: dentro de ``configure terminal`` y de ``interface gpon 0/N``.

Averiguar cuáles son exige **entrar a esos modos**, y eso es distinto de lo que
hace ``gpon capturar``. Entrar a modo configuración no cambia ninguna
configuración —es lo que hace cualquiera que se conecta a mirar— pero sí cambia
el estado de la sesión, así que este servicio lo dice de frente y se limita a lo
mínimo:

* los únicos comandos que ejecuta son de **navegación** (``configure terminal``,
  ``interface gpon 0/1``, ``exit``, ``end``) y de **lectura** (``show ...``);
* todo lo demás se pide con la ayuda en línea (``?``), que enumera la sintaxis
  sin ejecutar nada, porque nunca se manda Enter;
* al terminar vuelve al modo EXEC con ``end``, pase lo que pase.

Hay una lista blanca que lo impone, y no se puede saltear por parámetro.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ..core.errors import ErrorComando, ErrorGPON, ErrorValidacion
from ..drivers.transport import crear_transporte_cli
from .captura import SalidaComando, es_solo_lectura

log = logging.getLogger(__name__)

#: Comandos de navegación permitidos. Ninguno modifica configuración: cambian
#: el modo de la sesión, nada más.
NAVEGACION_FIJA: frozenset[str] = frozenset({"configure terminal", "exit", "end", "quit"})

#: ``interface gpon 0/1`` — entrar a un puerto PON. Sólo esta forma exacta.
NAVEGACION_INTERFAZ = re.compile(r"^interface\s+gpon\s+\d+/\d+$", re.IGNORECASE)


def es_navegacion(comando: str) -> bool:
    """¿Es un cambio de modo, y sólo eso?"""
    limpio = " ".join(comando.strip().lower().split())
    return limpio in NAVEGACION_FIJA or bool(NAVEGACION_INTERFAZ.match(limpio))


def es_permitido(comando: str) -> bool:
    """Lo único que este servicio puede enviar: navegar o leer."""
    return es_navegacion(comando) or es_solo_lectura(comando)


#: Ayudas a pedir en cada modo. La clave es el prefijo tipeado antes del ``?``.
AYUDAS_EXEC: tuple[str, ...] = ("", "show ")
AYUDAS_CONFIGURACION: tuple[str, ...] = (
    "",
    "interface ",
    "onu ",
    "profile ",
    # 'profile ?' contestó: «pri  Specify private profile interface». Ahí es
    # donde este firmware guarda la configuración del CPE —la WAN con PPPoE y
    # el WiFi—, que es lo que en el running-config aparece como 'onu N pri ...'.
    "profile pri ",
    "profile srv ",
    "profile onu ",
)
AYUDAS_INTERFAZ_PON: tuple[str, ...] = (
    "",
    "onu ",
    "onu add ",
    "show ",
    "no onu ",
    # La configuración del CPE —WAN con PPPoE, y WiFi— vive en las líneas
    # 'onu N pri ...' del running-config, que el parser saltea a propósito
    # porque ahí están las contraseñas de los clientes en texto plano. Para
    # poder *escribirlas* hace falta la sintaxis, y la sintaxis se pide con
    # '?', que enumera sin ejecutar nada.
    #
    # 'onu 1 ?' es el que importa: 'onu add ?' contestó los subcomandos del
    # alta (desc, tcont, gemport, service…) y ahí no había ninguno de CPE.
    "onu 1 ",
    "onu 1 modify ",
    "onu 1 pri ",
)

#: Prefijos cuyas ramas se recorren solas, un nivel más abajo.
#:
#: ``onu 1 pri ?`` contestó 34 opciones —entre ellas ``wan_conn``, ``wifi_ssid``
#: y ``save_config``—, pero para escribir un comando hace falta saber qué va
#: *después* de cada una. Sin esto haría falta una corrida por nivel, con el
#: equipo del otro lado y una persona esperando. El ``?`` sigue sin ejecutar
#: nada, así que bajar un nivel no cambia lo que el servicio puede hacer: sólo
#: cuántas preguntas hace en el mismo viaje.
AYUDAS_A_PROFUNDIZAR: tuple[str, ...] = ("onu 1 pri ",)

#: Tope de ramas a recorrer por prefijo. Existe para que un firmware con una
#: ayuda enorme no convierta la exploración en una sesión de media hora.
MAXIMO_RAMAS = 60

#: Una opción de la ayuda: dos espacios, la palabra, y su descripción. Se
#: descartan los marcadores ``<1-128>``, ``<cr>`` y ``<onu_list>``: no son
#: ramas por las que se pueda seguir preguntando, son valores que hay que
#: poner.
OPCION_AYUDA = re.compile(r"^\s{2,}(?P<palabra>[A-Za-z][\w.\-]*)\s\s+\S")


def ramas_de(ayuda: str) -> tuple[str, ...]:
    """Las palabras por las que se puede seguir bajando en la ayuda."""
    vistas: list[str] = []
    for linea in ayuda.splitlines():
        encontrado = OPCION_AYUDA.match(linea)
        if encontrado is None:
            continue
        palabra = encontrado.group("palabra")
        if palabra not in vistas:
            vistas.append(palabra)
    return tuple(vistas[:MAXIMO_RAMAS])

#: Candidatos de sólo lectura a probar dentro de ``interface gpon 0/N``. Es
#: donde debería estar el listado que la web muestra como "ONU AutoFind".
CANDIDATOS_INTERFAZ_PON: tuple[tuple[str, str], ...] = (
    ("show onu autofind", "ONU detectadas y sin autorizar (lo que la web llama AutoFind)"),
    ("show onu auto-find", "Variante con guion"),
    ("show onu unauth", "Variante corta"),
    ("show onu unauthorized", "Variante larga"),
    ("show onu discovery", "Variante"),
    ("show onu", "Inventario de ONU del puerto"),
    ("show onu info", "Detalle por ONU"),
    ("show onu state", "Estado de cada ONU"),
    ("show onu optical", "Potencias por ONU"),
    ("show onu optical-info", "Variante"),
    # Cómo ve el equipo la configuración del CPE: es el bloque que la web de la
    # OLT muestra como "WAN" y "WiFi", y el que hay que saber escribir.
    ("show onu 1 pri", "Configuración WAN/servicio de una ONU"),
    ("show onu wan", "Variante"),
    ("show onu 1 wan", "Variante con índice"),
    ("show onu wifi", "Configuración WiFi"),
    ("show onu 1 wifi", "Variante con índice"),
)


@dataclass(frozen=True, slots=True)
class Exploracion:
    """Lo que contestó cada modo de la CLI."""

    olt_id: int
    host: str
    pon: str
    momento: datetime
    ayudas: tuple[SalidaComando, ...] = field(default_factory=tuple)
    comandos: tuple[SalidaComando, ...] = field(default_factory=tuple)
    #: Modos por los que se pasó, en orden, para poder auditarlo después.
    recorrido: tuple[str, ...] = field(default_factory=tuple)

    @property
    def aceptados(self) -> tuple[SalidaComando, ...]:
        return tuple(s for s in self.comandos if s.tiene_datos)

    def a_texto(self) -> str:
        partes = [
            "=" * 78,
            f"EXPLORACIÓN DE LA CLI — OLT #{self.olt_id} ({self.host}), puerto {self.pon}",
            f"Fecha : {self.momento.isoformat()}",
            "",
            "Se entró a modo configuración para leer la ayuda en línea. No se",
            "ejecutó ningún comando de configuración: sólo navegación entre modos",
            "y comandos 'show'. La sesión volvió al modo EXEC con 'end'.",
            "",
            f"Recorrido: {' → '.join(self.recorrido)}",
            "=" * 78,
        ]

        partes += ["", "#" * 78, "# AYUDA EN LÍNEA POR MODO", "#" * 78]
        for ayuda in self.ayudas:
            partes += [
                "",
                "-" * 78,
                f"--- [{ayuda.grupo}] '{ayuda.comando}?'",
                "-" * 78,
                ayuda.salida or "(vacío)",
            ]

        partes += ["", "#" * 78, "# COMANDOS DE LECTURA PROBADOS", "#" * 78]
        for salida in self.comandos:
            cuerpo = (
                (salida.salida or "(salida vacía)")
                if salida.ok
                else f"NO DISPONIBLE: {salida.error}"
            )
            partes += [
                "",
                "-" * 78,
                f"--- $ {salida.comando}    [{salida.grupo}]",
                f"--- {salida.proposito}",
                "-" * 78,
                cuerpo,
            ]

        return "\n".join(partes) + "\n"


class ServicioExploracion:
    """Recorre los modos de la CLI y anota qué comandos ofrece cada uno."""

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

    def explorar(
        self,
        olt_id: int,
        *,
        pon: str = "0/1",
        protocolo: str = "ssh",
        timeout: float = 30.0,
        ruta_traza: str | None = None,
        al_avanzar: Any = None,
    ) -> Exploracion:
        """Entra a modo configuración, lee las ayudas y vuelve."""
        if not NAVEGACION_INTERFAZ.match(f"interface gpon {pon}"):
            raise ErrorValidacion(
                f"Puerto PON inválido: '{pon}'. Se espera la forma 'ranura/puerto', p. ej. 0/1."
            )

        olt = self._olts.obtener(olt_id)
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

        ayudas: list[SalidaComando] = []
        comandos: list[SalidaComando] = []
        recorrido: list[str] = ["exec"]

        transporte.abrir()
        try:
            self._pedir_ayudas(transporte, AYUDAS_EXEC, "exec", ayudas, al_avanzar)

            self._navegar(transporte, "configure terminal")
            recorrido.append("configure terminal")
            self._pedir_ayudas(
                transporte, AYUDAS_CONFIGURACION, "configuracion", ayudas, al_avanzar
            )

            self._navegar(transporte, f"interface gpon {pon}")
            recorrido.append(f"interface gpon {pon}")
            self._pedir_ayudas(
                transporte, AYUDAS_INTERFAZ_PON, f"interface gpon {pon}", ayudas, al_avanzar
            )

            for comando, proposito in CANDIDATOS_INTERFAZ_PON:
                resultado = self._correr(transporte, comando, proposito, f"interface gpon {pon}")
                comandos.append(resultado)
                if al_avanzar is not None:
                    al_avanzar(resultado)
        finally:
            # Volver al modo EXEC siempre, incluso si algo falló en el medio:
            # dejar la sesión colgada en modo configuración es lo que después
            # confunde a quien entra a mirar desde otra terminal.
            self._volver(transporte)
            recorrido.append("end")
            transporte.cerrar()

        return Exploracion(
            olt_id=olt_id,
            host=olt.host,
            pon=pon,
            momento=self._reloj.ahora(),
            ayudas=tuple(ayudas),
            comandos=tuple(comandos),
            recorrido=tuple(recorrido),
        )

    # --- internos ---------------------------------------------------------

    def _navegar(self, transporte: Any, comando: str) -> None:
        if not es_navegacion(comando):  # pragma: no cover - defensa del invariante
            raise ErrorValidacion(f"'{comando}' no es un comando de navegación")
        log.info("Cambiando de modo: %s", comando)
        transporte.ejecutar(comando)

    def _volver(self, transporte: Any) -> None:
        try:
            transporte.ejecutar("end")
        except ErrorGPON as exc:
            log.warning("No se pudo volver al modo EXEC con 'end': %s", exc)

    def _pedir_ayudas(
        self,
        transporte: Any,
        prefijos: tuple[str, ...],
        modo: str,
        acumulador: list[SalidaComando],
        al_avanzar: Any,
    ) -> None:
        for prefijo in prefijos:
            resultado = self._una_ayuda(transporte, prefijo, modo)
            acumulador.append(resultado)
            if al_avanzar is not None:
                al_avanzar(resultado)

            if prefijo not in AYUDAS_A_PROFUNDIZAR or not resultado.ok:
                continue
            for rama in ramas_de(resultado.salida):
                hijo = self._una_ayuda(transporte, f"{prefijo}{rama} ", modo)
                acumulador.append(hijo)
                if al_avanzar is not None:
                    al_avanzar(hijo)

    @staticmethod
    def _una_ayuda(transporte: Any, prefijo: str, modo: str) -> SalidaComando:
        inicio = time.monotonic()
        try:
            salida = transporte.ayuda(prefijo)
        except ErrorGPON as exc:
            return SalidaComando(
                comando=prefijo,
                proposito="Ayuda en línea del equipo",
                grupo=modo,
                ok=False,
                error=str(exc),
                duracion_ms=int((time.monotonic() - inicio) * 1000),
            )
        return SalidaComando(
            comando=prefijo,
            proposito="Ayuda en línea del equipo",
            grupo=modo,
            salida=salida,
            ok=True,
            duracion_ms=int((time.monotonic() - inicio) * 1000),
        )

    @staticmethod
    def _correr(transporte: Any, comando: str, proposito: str, modo: str) -> SalidaComando:
        if not es_solo_lectura(comando):  # pragma: no cover - defensa del invariante
            raise ErrorValidacion(f"'{comando}' no es de sólo lectura")

        inicio = time.monotonic()
        try:
            salida = transporte.ejecutar(comando)
        except ErrorComando as exc:
            return SalidaComando(
                comando=comando,
                proposito=proposito,
                grupo=modo,
                ok=False,
                error=str(exc),
                duracion_ms=int((time.monotonic() - inicio) * 1000),
            )
        return SalidaComando(
            comando=comando,
            proposito=proposito,
            grupo=modo,
            salida=salida,
            ok=True,
            duracion_ms=int((time.monotonic() - inicio) * 1000),
        )
