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
from collections import deque
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

#: Prefijos cuyas ramas se recorren solas, un nivel más abajo. Se aplica también
#: a las ramas que van apareciendo, así que listar un hijo lo hace bajar otro
#: nivel: es lo que convierte esto en un recorrido del árbol y no en un salto.
#:
#: ``onu 1 pri ?`` contestó 37 opciones y ``wan_conn ?`` otras cuatro, pero para
#: escribir un comando hace falta llegar hasta las hojas. Sin esto haría falta
#: una corrida por nivel, con el equipo del otro lado y una persona esperando.
#: El ``?`` sigue sin ejecutar nada, así que bajar no cambia lo que el servicio
#: puede hacer: sólo cuántas preguntas hace en el mismo viaje.
#:
#: No se baja por todo el árbol: son cientos de preguntas y la mayoría —VoIP,
#: CATV, tr069— no hacen falta para lo que se está construyendo.
AYUDAS_A_PROFUNDIZAR: tuple[str, ...] = ("onu 1 pri ",)

#: Subárboles que sí se recorren **enteros**, con la profundidad que haga falta.
#:
#: Antes esto era una lista de prefijos exactos y se quedó corta dos veces: la
#: primera no llegaba a ``wan_conn add``, la segunda no llegaba a
#: ``wan_conn add route`` ni a ``wifi_ssid 1 name``. Cada vez costó una corrida
#: contra el equipo con alguien esperando. Enumerar los nodos de un árbol que
#: todavía no se conoce es el error; lo que se conoce es **por dónde** hay que
#: entrar, y eso es lo que se declara acá.
#: Cada raíz con **cuántos niveles** se baja por debajo de ella. La profundidad
#: es por subárbol y no global porque las formas son distintas: ``wan_conn`` se
#: agota en tres niveles y esconde una combinatoria en ``bind``, mientras que el
#: WiFi es una cadena larga de pares clave-valor —``name <str> auth <modo>
#: encrypt <tipo> key <clave>``— que hay que recorrer entera.
SUBARBOLES_A_RECORRER: dict[str, int] = {
    "onu 1 pri wan_conn ": 5,
    "onu 1 pri wan_adv ": 3,
    "onu 1 pri wifi_ssid ": 8,
    "onu 1 pri wifi_switch ": 4,
    "onu 1 pri username ": 4,
}

#: Tope global de preguntas del recorrido. Es la red de contención que hace
#: seguro decir "recorré el subárbol entero" sin conocerlo de antemano.
MAXIMO_NODOS = 150

#: Cuántos niveles se baja por debajo de la raíz de un subárbol.
#:
#: Existe por un caso concreto que costó una corrida entera. ``wan_adv index 1
#: bind`` acepta una **lista repetida** de interfaces: ``bind lan1 ?`` ofrece
#: ``lan2 … ssid10``, ``bind lan1 lan2 ?`` ofrece el resto, y así. El árbol no
#: es un árbol, es una combinatoria. Un recorrido en profundidad se hundió ahí
#: y gastó las 150 preguntas sin llegar nunca a ``wan_conn`` ni a
#: ``wifi_ssid``, que era justamente lo que se estaba buscando.
#:
#: Tres niveles alcanzan para la WAN —``wan_conn add route``, ``wan_adv index 1
#: bind``— y cortan la combinatoria en el primer escalón. El WiFi necesita más,
#: y por eso la profundidad se declara por subárbol.
PROFUNDIDAD_POR_DEFECTO = 3

#: Con qué se rellena un ``<string>`` para poder seguir preguntando.
#:
#: ``wifi_ssid 1 name ?`` contesta sólo ``<string>``, y lo que interesa —el modo
#: de autenticación, el cifrado, la clave— está **después** del nombre. Sin
#: rellenarlo el recorrido se corta justo antes de lo único que falta. El ``?``
#: no ejecuta nada, así que poner un valor de prueba no configura ninguna ONU:
#: es texto tipeado que después se borra con Ctrl-U.
VALOR_DE_PRUEBA = "X"

#: Tope de ramas a recorrer por prefijo. Existe para que un firmware con una
#: ayuda enorme no convierta la exploración en una sesión de media hora.
MAXIMO_RAMAS = 60

#: Una opción de la ayuda: dos espacios, la palabra, y su descripción.
OPCION_AYUDA = re.compile(r"^\s{2,}(?P<palabra>[A-Za-z][\w.\-]*)\s\s+\S")

#: ``  <1-8>  Specify onu wifi ssid number.`` — un rango numérico. No es una
#: rama, es un hueco; pero sin llenarlo no se puede seguir bajando, y justo
#: detrás está lo que interesa (los parámetros de cada SSID). Se usa el extremo
#: bajo, que existe siempre. El ``?`` no ejecuta nada, así que elegir un número
#: no configura ninguna ONU.
RANGO_AYUDA = re.compile(r"^\s{2,}<(?P<desde>\d+)-\d+>\s\s+\S")

#: ``  <string>  Specify onu wifi ssid name string, max length 32.`` — un texto
#: libre. Igual que el rango, es un hueco y no una rama, pero detrás puede haber
#: más comando. ``<cr>`` queda afuera: ahí el comando termina de verdad.
TEXTO_AYUDA = re.compile(r"^\s{2,}<(?!cr>)[a-z_]+>\s\s+\S", re.IGNORECASE)


def _hay_que_bajar(prefijo: str) -> bool:
    """¿Se sigue por las ramas de este prefijo?

    Un prefijo exacto de ``AYUDAS_A_PROFUNDIZAR`` baja un nivel. Dentro de un
    subárbol declarado se baja hasta la profundidad que ese subárbol declare:
    sin ese
    tope, una rama que acepta listas repetidas se traga el recorrido entero.
    """
    if prefijo in AYUDAS_A_PROFUNDIZAR:
        return True
    for raiz, profundidad in SUBARBOLES_A_RECORRER.items():
        if prefijo.startswith(raiz):
            bajo_la_raiz = len(prefijo.split()) - len(raiz.split())
            return bajo_la_raiz < profundidad
    return False


def ramas_de(ayuda: str) -> tuple[str, ...]:
    """Por dónde se puede seguir bajando en la ayuda.

    Las palabras son el camino. Cuando no hay ninguna se rellena el hueco, para
    poder seguir: un rango numérico con su extremo bajo, un ``<string>`` con un
    valor de prueba. ``<cr>`` no se rellena —ahí el comando termina de verdad— y
    ``<A.B.C.D>`` tampoco, porque una IP inventada no lleva a ningún lado.

    El orden importa: si el equipo ofrece palabras **y** un hueco, las palabras
    ganan. Rellenar igual llevaría a preguntar de más por un camino que ya está
    enumerado.
    """
    palabras: list[str] = []
    rangos: list[str] = []
    hay_texto = False
    for linea in ayuda.splitlines():
        if encontrado := OPCION_AYUDA.match(linea):
            palabra = encontrado.group("palabra")
            if palabra not in palabras:
                palabras.append(palabra)
        elif encontrado := RANGO_AYUDA.match(linea):
            desde = encontrado.group("desde")
            if desde not in rangos:
                rangos.append(desde)
        elif TEXTO_AYUDA.match(linea):
            hay_texto = True

    elegidas = palabras or rangos or ([VALOR_DE_PRUEBA] if hay_texto else [])
    return tuple(elegidas[:MAXIMO_RAMAS])

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
    # Cómo ve el equipo la configuración del CPE. En esta CLI el 'show' va al
    # final, así que no empiezan con un verbo permitido: hay una excepción
    # explícita para esta forma exacta en es_solo_lectura().
    #
    # La ONU 1 es un cliente que anda: leerle la WAN muestra los nombres reales
    # de cada parámetro, que es lo que hay que saber escribir.
    ("onu 1 pri wan_conn show", "WAN de una ONU ya configurada, con el PPPoE"),
    ("onu 1 pri wan_adv show", "Parámetros avanzados de esa WAN"),
    ("onu 1 pri acl show", "Accesos permitidos al CPE"),
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
        ayudas_extra: tuple[str, ...] = (),
    ) -> Exploracion:
        """Entra a modo configuración, lee las ayudas y vuelve.

        ``ayudas_extra`` agrega prefijos puntuales a los del modo interfaz. Es
        para cuando falta un pedazo concreto del árbol y no tiene sentido pagar
        el recorrido entero: preguntar por dos prefijos toma segundos, y una
        exploración completa toma minutos con alguien esperando.
        """
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
                transporte,
                AYUDAS_INTERFAZ_PON + tuple(ayudas_extra),
                f"interface gpon {pon}",
                ayudas,
                al_avanzar,
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
        """Recorre la ayuda **a lo ancho**, nivel por nivel.

        En profundidad, la primera rama que se abre se lleva todo el
        presupuesto. Pasó: ``wan_adv index 1 bind`` acepta listas repetidas, el
        recorrido se hundió ahí y gastó las 150 preguntas sin llegar nunca a
        ``wan_conn`` ni a ``wifi_ssid``, que era lo que se estaba buscando.

        A lo ancho, lo poco profundo —que es lo que casi siempre importa— se
        pregunta primero, y lo que queda afuera al agotarse el presupuesto es lo
        más hondo. El orden en que se piden las cosas es el orden en que se
        pierden si algo se corta.
        """
        pendientes: deque[str] = deque(prefijos)
        vistos: set[str] = set()

        while pendientes:
            if len(vistos) >= MAXIMO_NODOS:
                log.warning(
                    "Tope de %d preguntas alcanzado; quedaron %d prefijos sin recorrer",
                    MAXIMO_NODOS,
                    len(pendientes),
                )
                break

            prefijo = pendientes.popleft()
            if prefijo in vistos:
                continue
            vistos.add(prefijo)

            resultado = self._una_ayuda(transporte, prefijo, modo)
            acumulador.append(resultado)
            if al_avanzar is not None:
                al_avanzar(resultado)

            if not resultado.ok or not _hay_que_bajar(prefijo):
                continue
            pendientes.extend(f"{prefijo}{rama} " for rama in ramas_de(resultado.salida))

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
