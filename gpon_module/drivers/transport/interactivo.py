"""Sesión CLI interactiva: lo común entre Telnet y SSH.

Hablar con la CLI de una OLT no es "mandar un comando y leer la respuesta". Es
leer hasta reconocer un prompt, contestar la paginación si aparece, distinguir
el eco del comando de la salida real, y darse cuenta de cuándo el equipo dejó
de contestar. Eso es idéntico en Telnet y en SSH; lo único distinto es por
dónde viajan los bytes.

Acá vive todo lo idéntico. Las subclases sólo aportan ``_recibir`` y
``_transmitir``.
"""

from __future__ import annotations

import logging
import re
import time

from ...core.errors import ErrorAutenticacion, ErrorConexion, ErrorTiempoAgotado
from .base import TransporteCLIBase, sesion_exclusiva

log = logging.getLogger(__name__)

#: Prompts habituales de una CLI estilo Cisco, que es la de VSOL y la de ZTE.
PROMPT_USUARIO = re.compile(rb"(?i)(user\s*name|login|username)\s*:\s*$")
PROMPT_PASSWORD = re.compile(rb"(?i)password\s*:\s*$")

#: El prompt de comando se exige "con forma de prompt": desde el principio de
#: una línea, un nombre sin espacios y después ``#`` o ``>``. Aceptar cualquier
#: línea terminada en ``>`` haría que una salida que contenga ese carácter
#: cortara la lectura por la mitad.
#:
#: Dos detalles que costaron una sesión cada uno contra la OLT de ERLAN:
#:
#: * ``(?:^|[\r\n])`` y no sólo ``[\r\n]``: por SSH el primer prompt llega al
#:   principio del canal, sin ningún salto de línea delante.
#: * el nombre se acepta con **cualquier byte imprimible**, no con ``\w``. En un
#:   patrón de bytes ``\w`` es sólo ASCII, y el equipo se llama
#:   ``Zona_Bº_Belgrano``: esa ``º`` viaja como ``\xc2\xba`` y hacía que el
#:   módulo no reconociera un prompt que tenía delante.
PROMPT_COMANDO = re.compile(rb"(?:^|[\r\n])[^\s\x00-\x1f]{1,60}\s*[#>]\s?$")
PROMPT_PRIVILEGIADO = re.compile(rb"(?:^|[\r\n])[^\s\x00-\x1f]{1,60}\s*#\s?$")
PROMPT_PAGINACION = re.compile(rb"(?i)(--\s*more\s*--|<space>|press any key|--more--)")

#: Notificaciones que el equipo empuja a la sesión por su cuenta, sin que nadie
#: las pida. La VSOL de ERLAN anuncia así cada ONU que entra o sale::
#:
#:     2026/08/06 12:15:28   ONU Offline   PON 0/7 ONU 22 sn GPON00B8FF21
#:
#: Llegan en cualquier momento, también en medio de la salida de un comando, y
#: si no se sacan el parser las toma por datos.
LINEA_ASINCRONA = re.compile(
    r"^\s*\d{4}/\d{2}/\d{2}\s+\d{1,2}:\d{2}:\d{2}\s+ONU\s+(Online|Offline)\b.*$",
    re.IGNORECASE,
)

#: ``ESC[<n>C`` — el equipo alinea las columnas de sus tablas moviendo el cursor
#: en vez de escribir espacios. Verificado contra la V1600G1: el número es la
#: **columna absoluta** donde arranca el campo, y coincide exactamente con la
#: posición del encabezado. Sin traducirlo, una fila llega así::
#:
#:     GPON0/1:1\x1b[25CGPON002E64F8\x1b[50Cunknow
#:
#: que ningún parser puede separar en columnas.
SECUENCIA_COLUMNA = re.compile(r"\x1b\[(\d+)C")

#: El resto de las secuencias ANSI (colores, borrados) no aporta nada y se saca.
SECUENCIA_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b[()][AB0-2]|\x1b[=>]")


def expandir_columnas(linea: str) -> str:
    """Reemplaza los saltos de columna ANSI por los espacios equivalentes.

    Deja la fila alineada igual que en la pantalla del operador, que es como el
    encabezado promete que está.
    """
    partes: list[str] = []
    ancho = 0
    desde = 0

    for salto in SECUENCIA_COLUMNA.finditer(linea):
        trozo = linea[desde : salto.start()]
        partes.append(trozo)
        ancho += len(trozo)

        objetivo = int(salto.group(1))
        # Si el texto ya pasó la columna pedida, al menos hay que separar los
        # campos: pegarlos volvería a dejar la fila sin poder partirse.
        relleno = max(objetivo - ancho, 1)
        partes.append(" " * relleno)
        ancho += relleno
        desde = salto.end()

    partes.append(linea[desde:])
    return "".join(partes)


def limpiar_ansi(texto: str) -> str:
    """Deja el texto tal como se vería en pantalla, sin códigos de control."""
    return SECUENCIA_ANSI.sub("", expandir_columnas(texto))


#: Textos con los que el equipo rechaza las credenciales.
RECHAZOS_LOGIN = (
    b"incorrect",
    b"invalid password",
    b"authentication fail",
    b"login fail",
    b"access denied",
    b"permission denied",
)


class TransporteInteractivo(TransporteCLIBase):
    """Sesión CLI conversacional sobre un canal de bytes.

    Implementa el ciclo completo —login, ``enable``, envío de comandos,
    paginación, cierre— delegando en la subclase solamente el transporte de
    bytes. La exclusión mutua por OLT se toma acá: la CLI de estos equipos es
    de sesión única y dos operaciones simultáneas no dan un error prolijo, dan
    una configuración entrelazada (riesgo R4).
    """

    #: Nombre corto del protocolo, para mensajes y para la clave del bloqueo.
    PROTOCOLO = "cli"

    #: Cuánto se espera como máximo por la sesión exclusiva de una OLT. Es
    #: mucho más largo que el timeout de lectura a propósito: una operación en
    #: curso puede tardar, y hacerla fallar por impaciencia es peor.
    TIMEOUT_SESION = 120.0

    #: Cuánto se espera un bloque de datos antes de considerar que el equipo se
    #: calló. No es el límite de la lectura —ese es ``timeout``—, sino el
    #: intervalo tras el cual conviene volver a mirar si hay que estimular al
    #: equipo con un Enter.
    SILENCIO_SEGUNDOS = 2.0

    #: Con qué se termina cada línea que se le manda al equipo.
    #:
    #: **CR solo, no CR LF.** Es lo que manda una terminal real cuando se
    #: aprieta Enter, y estos equipos corren en "character mode": procesan cada
    #: byte según llega. Un ``\n`` detrás del ``\r`` es un segundo Enter, y en
    #: el login eso significa mandar el usuario y acto seguido una contraseña
    #: vacía — que es exactamente lo que pasó contra la OLT de ERLAN.
    FIN_DE_LINEA = b"\r"

    def __init__(self, **kwargs: object) -> None:
        # La traza no es asunto de TransporteCLIBase: se saca antes de delegar.
        ruta_traza = kwargs.pop("ruta_traza", None)
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._bloqueo: object | None = None
        self._pendiente = b""
        #: Archivo donde volcar todo lo que se manda y se recibe. Se escribe en
        #: el momento, no al final: si la sesión revienta, la traza igual queda.
        self._ruta_traza = str(ruta_traza) if ruta_traza else ""
        #: Prompt real de esta sesión, aprendido al conectarse. Saberlo permite
        #: recortarlo con exactitud en vez de adivinar dónde termina la salida.
        self._prompt = b""

    # --- a implementar por cada protocolo ---------------------------------

    def _leer_canal(self, cantidad: int) -> bytes:
        """Lee bytes del canal. Devuelve ``b""`` sólo si el otro lado cerró."""
        raise NotImplementedError

    def _escribir_canal(self, datos: bytes) -> None:
        """Escribe bytes crudos en el canal."""
        raise NotImplementedError

    def _fijar_timeout_lectura(self, segundos: float) -> None:
        """Cambia cuánto espera una lectura antes de darse por vencida."""
        raise NotImplementedError

    # --- entrada y salida -------------------------------------------------

    def _recibir(self, cantidad: int) -> bytes:
        datos = self._leer_canal(cantidad)
        self._anotar_traza("<<", datos)
        return datos

    def _transmitir(self, datos: bytes) -> None:
        self._anotar_traza(">>", datos)
        self._escribir_canal(datos)

    def _anotar_traza(self, direccion: str, datos: bytes) -> None:
        """Registra la conversación, si se pidió una traza.

        Se escribe en el momento y no al final: cuando una sesión falla es
        justamente cuando la traza hace falta, y guardarla al cerrar sería
        guardarla nunca.
        """
        if not self._ruta_traza or not datos:
            return
        try:
            with open(self._ruta_traza, "a", encoding="utf-8") as archivo:
                archivo.write(f"{direccion} {datos!r}\n")
        except OSError as exc:  # pragma: no cover - la traza nunca corta la sesión
            log.warning("No se pudo escribir la traza en %s: %s", self._ruta_traza, exc)

    def _escribir(self, texto: str) -> None:
        self._transmitir(texto.encode("ascii", errors="replace") + self.FIN_DE_LINEA)

    def _enviar(self, comando: str) -> str:
        self._escribir(comando)
        crudo = self._leer_hasta((PROMPT_COMANDO,))
        return self._limpiar_salida(crudo, comando)

    def _leer_hasta(
        self, patrones: tuple[re.Pattern[bytes], ...], *, estimular: bool = True
    ) -> bytes:
        """Lee hasta encontrar alguno de los patrones, o hasta el timeout.

        Dos cosas que no son obvias y que hacen falta contra equipos reales:

        * **La paginación se contesta sola.** Si el equipo ignoró
          ``terminal length 0``, un ``--More--`` sin responder deja la sesión
          colgada para siempre (riesgo R3).
        * **Al primer silencio se manda un Enter.** Varios equipos no imprimen
          el prompt hasta recibir uno, sobre todo por SSH. Sin ese estímulo, la
          sesión espera un prompt que el equipo nunca va a mandar por su cuenta.
          Un Enter de más es inofensivo: no ejecuta ningún comando.
        """
        limite = time.monotonic() + self.timeout
        acumulado = self._pendiente
        self._pendiente = b""
        estimulado = not estimular

        # Lecturas cortas para poder reaccionar al silencio. El límite real de
        # la operación sigue siendo 'timeout'.
        self._fijar_timeout_lectura(min(self.SILENCIO_SEGUNDOS, self.timeout))
        try:
            while True:
                for patron in patrones:
                    if patron.search(acumulado):
                        self._recordar_prompt(acumulado)
                        return acumulado

                if PROMPT_PAGINACION.search(acumulado):
                    self._transmitir(b" ")
                    acumulado = PROMPT_PAGINACION.sub(b"", acumulado)
                    limite = time.monotonic() + self.timeout
                    continue

                if time.monotonic() > limite:
                    raise ErrorTiempoAgotado(self._sin_prompt(acumulado))

                try:
                    datos = self._recibir(8192)
                except ErrorTiempoAgotado:
                    # Sólo se estimula si el equipo no dijo absolutamente nada.
                    # Si ya venía mandando datos, está vivo y trabajando: meterle
                    # un Enter en medio de una salida larga ensuciaría la lectura.
                    if not estimulado and not acumulado:
                        log.debug("%s no dijo nada: se manda un Enter", self.host)
                        self._transmitir(self.FIN_DE_LINEA)
                        estimulado = True
                    continue  # el límite global decide cuándo rendirse
                if not datos:
                    raise ErrorConexion(f"{self.host} cerró la conexión")
                acumulado += datos
        finally:
            self._fijar_timeout_lectura(self.timeout)

    def _sin_prompt(self, acumulado: bytes) -> str:
        """Mensaje de un timeout que además explica qué llegó.

        Sin esto el error dice sólo "dejó de responder", que no alcanza para
        saber si el equipo no mandó nada, mandó un banner sin prompt, o mandó un
        prompt con una forma que el módulo todavía no reconoce.
        """
        if not acumulado:
            return (
                f"{self.host} no envió nada en {self.timeout:g} s por {self.PROTOCOLO}. "
                "La sesión abrió pero el equipo quedó mudo."
            )
        texto = acumulado[-400:].decode("utf-8", errors="replace")
        return (
            f"{self.host} respondió pero no apareció un prompt reconocible en "
            f"{self.timeout:g} s. Esto es lo último que mandó:\n"
            f"---\n{texto}\n---\n"
            "Si eso de arriba termina en un prompt, es que tiene una forma que el "
            "módulo todavía no reconoce. Guardá la sesión completa con "
            "'--traza sesion.log' y mandala."
        )

    def _recordar_prompt(self, salida: bytes) -> None:
        """Aprende el prompt de esta sesión, si la salida termina en uno.

        Sólo se llama cuando la lectura terminó porque apareció un prompt al
        final del buffer, así que lo que se guarda es el prompt de verdad y no
        un carácter suelto que apareció en medio de la salida.
        """
        coincidencia = PROMPT_COMANDO.search(salida)
        if coincidencia:
            self._prompt = coincidencia.group().strip()

    def _leer_hasta_silencio(self, silencio: float = 1.5, maximo: float | None = None) -> bytes:
        """Lee hasta que el equipo se calla, sin esperar ningún prompt.

        Hace falta para la ayuda en línea (``?``): el equipo no termina con un
        prompt limpio sino repitiendo lo que había tipeado, así que no hay
        patrón que buscar. Lo único que marca el final es el silencio.
        """
        limite = time.monotonic() + (maximo if maximo is not None else self.timeout)
        acumulado = self._pendiente
        self._pendiente = b""

        self._fijar_timeout_lectura(silencio)
        try:
            while time.monotonic() < limite:
                try:
                    datos = self._recibir(8192)
                except ErrorTiempoAgotado:
                    break  # se calló: eso es el final
                if not datos:
                    break
                acumulado += datos
                if PROMPT_PAGINACION.search(acumulado):
                    self._transmitir(b" ")
                    acumulado = PROMPT_PAGINACION.sub(b"", acumulado)
        finally:
            self._fijar_timeout_lectura(self.timeout)
        return acumulado

    def ayuda(self, prefijo: str = "") -> str:
        """Pide la ayuda en línea del equipo y deja la sesión limpia.

        ``?`` en una CLI estilo Cisco lista las opciones válidas **sin ejecutar
        nada**: no se manda Enter, así que no hay comando que aplicar. Es la
        forma más segura que existe de averiguar la sintaxis real de un
        firmware, y por eso es la base de ``gpon capturar``: mejor preguntarle
        al equipo qué acepta que adivinarlo desde un manual de otra versión.

        Después de leer, la línea se borra con Ctrl-U para que lo tipeado no
        quede colgando y se mezcle con el comando siguiente.
        """
        self._transmitir(prefijo.encode("ascii", errors="replace") + b"?")
        crudo = self._leer_hasta_silencio()

        self._transmitir(b"\x15")  # Ctrl-U: borra la línea tipeada
        self._transmitir(self.FIN_DE_LINEA)
        try:
            self._leer_hasta((PROMPT_COMANDO,))
        except ErrorTiempoAgotado:
            log.debug("%s no devolvió el prompt tras la ayuda de '%s'", self.host, prefijo)

        texto = crudo.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "")
        texto = "\n".join(limpiar_ansi(linea) for linea in texto.split("\n"))

        # Al terminar, el equipo redibuja el prompt con lo que quedó tipeado, y
        # varios lo pegan al último renglón sin salto de línea. Descartar esa
        # línea entera se comería la última opción de la ayuda, que suele ser
        # justo la que interesa. Por eso se corta en el prompt exacto.
        #
        # Se corta en la **primera** aparición: de ahí en adelante ya no hay
        # ayuda, sólo el redibujo y lo que haya contestado el equipo al borrado
        # de la línea, que a veces llega dentro de la misma lectura.
        prompt = self._prompt.decode("utf-8", errors="replace")
        corte = texto.find(prompt) if prompt else -1
        if corte != -1:
            texto = texto[:corte]
        else:
            lineas = texto.split("\n")
            if lineas and re.search(r"[#>]", lineas[-1]):
                texto = "\n".join(lineas[:-1])

        return texto.strip("\n")

    @staticmethod
    def _limpiar_salida(crudo: bytes, comando: str) -> str:
        """Quita el eco del comando, la línea del prompt y los avisos del equipo.

        Lo que queda es la salida del comando y nada más, que es lo que el
        parser espera ver.

        Los avisos hay que sacarlos aparte porque no los pidió nadie: la OLT los
        empuja a la sesión cuando una ONU entra o sale, y pueden caer en medio
        de una tabla. Dejarlos ahí sería darle al parser una fila inventada.
        """
        texto = crudo.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "")
        lineas = [
            limpiar_ansi(linea)
            for linea in texto.split("\n")
            if not LINEA_ASINCRONA.match(linea)
        ]
        if lineas and comando.strip() and comando.strip() in lineas[0]:
            lineas = lineas[1:]
        while lineas and re.search(r"[#>]\s*$", lineas[-1]):
            lineas = lineas[:-1]
        return "\n".join(lineas).strip("\n")

    # --- login ------------------------------------------------------------

    def _autenticar(self) -> None:
        """Login y paso a modo privilegiado.

        El mismo camino sirve para Telnet y para SSH. Por SSH el handshake ya
        autenticó y normalmente aparece el prompt directo, pero varios equipos
        **vuelven a pedir usuario y contraseña dentro de la sesión**. Esperar
        sólo el prompt en ese caso dejaba la sesión colgada contra una pantalla
        de login.
        """
        salida = self._leer_hasta((PROMPT_USUARIO, PROMPT_PASSWORD, PROMPT_COMANDO))

        if PROMPT_USUARIO.search(salida):
            self._escribir(self.usuario)
            # Se vigila también que vuelva a aparecer el prompt de usuario: es
            # cómo el equipo dice "no" sin decirlo. Sin esto, un rechazo se
            # descubría recién al vencer el timeout, y cada reintento gastaba un
            # intento de login contra un equipo que puede bloquear la cuenta.
            salida = self._leer_hasta((PROMPT_PASSWORD, PROMPT_COMANDO, PROMPT_USUARIO))
            self._exigir_que_no_haya_rechazo(salida)

        if PROMPT_PASSWORD.search(salida):
            self._escribir(self.password)
            salida = self._leer_hasta((PROMPT_COMANDO, PROMPT_USUARIO, PROMPT_PASSWORD))
            self._exigir_que_no_haya_rechazo(salida)

        if PROMPT_USUARIO.search(salida) or PROMPT_PASSWORD.search(salida):
            # Seguimos en la pantalla de login sin un motivo escrito.
            raise ErrorAutenticacion(
                f"{self.host} sigue pidiendo credenciales: no aceptó el usuario "
                f"'{self.usuario}' por {self.PROTOCOLO}"
            )

        self._elevar_privilegios(salida)

    def _exigir_que_no_haya_rechazo(self, salida: bytes) -> None:
        """Corta apenas el equipo dice que las credenciales no sirven."""
        minuscula = salida.lower()
        for rechazo in RECHAZOS_LOGIN:
            if rechazo in minuscula:
                raise ErrorAutenticacion(
                    f"{self.host} rechazó el usuario '{self.usuario}' por "
                    f"{self.PROTOCOLO}: «{rechazo.decode()}»"
                )

    def _elevar_privilegios(self, salida: bytes) -> None:
        """``enable``, si el prompt todavía no es privilegiado.

        No pasar a modo privilegiado no es un error fatal: buena parte de los
        ``show`` funciona igual. Se avisa y se sigue, porque abortar dejaría al
        operador sin la lectura que sí podía hacer.
        """
        if PROMPT_PRIVILEGIADO.search(salida):
            return

        # Todo este bloque es "mejor si sale, no pasa nada si no". Ni siquiera
        # sabemos si este firmware tiene 'enable': si se lo come, si pide una
        # contraseña que no tenemos o si directamente no contesta, se sigue con
        # la sesión que ya está abierta. Perder la lectura entera por no haber
        # podido elevar privilegios sería el peor de los desenlaces.
        try:
            self._escribir("enable")
            salida = self._leer_hasta((PROMPT_PASSWORD, PROMPT_COMANDO))
            if PROMPT_PASSWORD.search(salida):
                self._escribir(self.password_enable or self.password)
                salida = self._leer_hasta((PROMPT_COMANDO, PROMPT_PASSWORD))
        except ErrorTiempoAgotado as exc:
            log.warning("%s no respondió al 'enable': %s. Se sigue igual.", self.host, exc)
            return

        if not PROMPT_PRIVILEGIADO.search(salida):
            log.warning(
                "%s quedó en modo no privilegiado (prompt '%s'). Algunos comandos "
                "de consulta pueden no estar disponibles.",
                self.host,
                self._prompt.decode("utf-8", errors="replace"),
            )

    # --- exclusión por OLT ------------------------------------------------

    def abrir(self) -> None:
        if self.conectado:
            return
        self._bloqueo = sesion_exclusiva(
            f"{self.PROTOCOLO}:{self.host}:{self.puerto}",
            timeout_segundos=self.TIMEOUT_SESION,
        )
        self._bloqueo.__enter__()  # type: ignore[attr-defined]
        try:
            super().abrir()
        except BaseException:
            self._liberar_bloqueo()
            raise

    def cerrar(self) -> None:
        try:
            super().cerrar()
        finally:
            self._liberar_bloqueo()

    def _liberar_bloqueo(self) -> None:
        bloqueo, self._bloqueo = self._bloqueo, None
        if bloqueo is not None:
            bloqueo.__exit__(None, None, None)  # type: ignore[attr-defined]
