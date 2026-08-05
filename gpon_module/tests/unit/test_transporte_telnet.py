"""Cliente Telnet propio.

``telnetlib`` ya no existe en Python 3.13, así que el protocolo lo implementa
el módulo. Estos tests cubren lo que rompe contra un equipo real: la
negociación IAC, el login en dos pasos, la paginación y el eco del comando.
Ninguno toca la red: el socket es falso.
"""

from __future__ import annotations

import socket
from collections import deque

import pytest

from gpon_module.core.errors import ErrorAutenticacion, ErrorComando, ErrorTiempoAgotado
from gpon_module.drivers.transport.telnet import DO, IAC, WONT, TransporteTelnet

PROMPT = b"\r\nOLT_Belgrano#"


class SocketFalso:
    """Socket de mentira con un guion: a cada comando, su respuesta."""

    def __init__(self, bienvenida: bytes, guion: dict[str, bytes]) -> None:
        self.guion = guion
        self.enviado: list[bytes] = []
        self.pendiente: deque[bytes] = deque([bienvenida])
        self.cerrado = False
        self.timeout: float | None = None

    def settimeout(self, segundos: float) -> None:
        self.timeout = segundos

    def sendall(self, datos: bytes) -> None:
        self.enviado.append(datos)
        clave = datos.decode("utf-8", errors="replace").strip()
        if clave in self.guion:
            self.pendiente.append(self.guion[clave])

    def recv(self, _cantidad: int) -> bytes:
        if not self.pendiente:
            raise TimeoutError("sin datos")
        return self.pendiente.popleft()

    def close(self) -> None:
        self.cerrado = True

    # -- ayudas para los tests --
    @property
    def texto_enviado(self) -> list[str]:
        return [d.decode("utf-8", errors="replace") for d in self.enviado]


def _respuesta(comando: str, cuerpo: str) -> bytes:
    """Lo que devuelve un equipo: eco del comando, salida y prompt."""
    return f"{comando}\r\n{cuerpo}".encode() + PROMPT


@pytest.fixture
def guion_basico() -> dict[str, bytes]:
    return {
        "admin": b"\r\nPassword:",
        "Xpon@Olt9417#": PROMPT,
        "terminal length 0": _respuesta("terminal length 0", ""),
        "show version": _respuesta("show version", "Model: V1600G1\r\nFirmware: V2.3.1R"),
        "show onu": _respuesta("show onu", "% Invalid input detected at '^' marker"),
    }


@pytest.fixture
def conectar(monkeypatch, guion_basico):
    """Devuelve (transporte, socket falso) ya enchufados, sin abrir.

    Al terminar cada test cierra lo que haya quedado abierto. La sesión
    exclusiva por OLT es un bloqueo global: un test que la deje tomada haría
    esperar 120 s al siguiente, y el que fallaría sería el otro.
    """
    abiertos: list[TransporteTelnet] = []

    def _armar(bienvenida: bytes = b"\r\nUser Name:", guion=None, **kwargs):
        falso = SocketFalso(bienvenida, guion if guion is not None else guion_basico)
        monkeypatch.setattr(socket, "create_connection", lambda *_a, **_k: falso)
        transporte = TransporteTelnet(
            host="10.0.0.1",
            usuario="admin",
            password="Xpon@Olt9417#",
            timeout=1.0,
            intentos=1,
            **kwargs,
        )
        abiertos.append(transporte)
        return transporte, falso

    yield _armar

    for transporte in abiertos:
        transporte.cerrar()


class TestNegociacion:
    def test_a_toda_opcion_se_responde_que_no(self, conectar) -> None:
        """Aceptar opciones Telnet complica la sesión sin ningún beneficio."""
        bienvenida = bytes([IAC, DO, 24]) + b"\r\nUser Name:"
        transporte, falso = conectar(bienvenida=bienvenida)
        transporte.abrir()

        assert bytes([IAC, WONT, 24]) in falso.enviado
        transporte.cerrar()

    def test_los_bytes_de_negociacion_no_se_mezclan_con_la_salida(self, conectar) -> None:
        guion = {
            "admin": b"\r\nPassword:",
            "Xpon@Olt9417#": PROMPT,
            "terminal length 0": _respuesta("terminal length 0", ""),
            "show version": bytes([IAC, DO, 1]) + _respuesta("show version", "V1600G1"),
        }
        transporte, _ = conectar(guion=guion)
        transporte.abrir()

        assert transporte.ejecutar("show version") == "V1600G1"
        transporte.cerrar()


class TestLogin:
    def test_login_en_dos_pasos(self, conectar) -> None:
        transporte, falso = conectar()
        transporte.abrir()

        assert "admin\r\n" in falso.texto_enviado
        assert "Xpon@Olt9417#\r\n" in falso.texto_enviado
        assert transporte.conectado
        transporte.cerrar()

    def test_una_contrasena_rechazada_no_se_confunde_con_una_sesion_abierta(self, conectar) -> None:
        """Si no, la primera lectura devolvería la pantalla de login como datos."""
        guion = {
            "admin": b"\r\nPassword:",
            "Xpon@Olt9417#": b"\r\nLogin incorrect\r\n\r\nUser Name:",
        }
        transporte, _ = conectar(guion=guion)

        with pytest.raises(ErrorAutenticacion, match="admin"):
            transporte.abrir()
        assert not transporte.conectado

    def test_no_queda_tomada_la_sesion_exclusiva_si_falla_el_login(self, conectar) -> None:
        """Un login fallido que no suelte el bloqueo deja la OLT inaccesible."""
        guion = {"admin": b"\r\nPassword:", "Xpon@Olt9417#": b"\r\nincorrect\r\nUser Name:"}
        transporte, _ = conectar(guion=guion)

        with pytest.raises(ErrorAutenticacion):
            transporte.abrir()

        # Si el bloqueo hubiera quedado tomado, este segundo intento se colgaría
        # hasta el timeout de sesión en vez de fallar por credenciales.
        transporte2, _ = conectar(guion=guion)
        with pytest.raises(ErrorAutenticacion):
            transporte2.abrir()

    def test_se_desactiva_la_paginacion_al_abrir(self, conectar) -> None:
        transporte, falso = conectar()
        transporte.abrir()
        assert "terminal length 0\r\n" in falso.texto_enviado
        transporte.cerrar()


class TestSalida:
    def test_la_salida_no_incluye_el_eco_ni_el_prompt(self, conectar) -> None:
        """El parser espera datos, no la línea que acabamos de escribir."""
        transporte, _ = conectar()
        transporte.abrir()

        salida = transporte.ejecutar("show version")

        assert salida == "Model: V1600G1\nFirmware: V2.3.1R"
        assert "OLT_Belgrano" not in salida
        transporte.cerrar()

    def test_un_comando_rechazado_levanta_excepcion(self, conectar) -> None:
        transporte, _ = conectar()
        transporte.abrir()

        with pytest.raises(ErrorComando) as excepcion:
            transporte.ejecutar("show onu")

        assert excepcion.value.comando == "show onu"
        transporte.cerrar()

    def test_la_paginacion_se_contesta_sola(self, conectar) -> None:
        """Un --More-- sin responder cuelga la sesión para siempre (riesgo R3)."""
        guion = {
            "admin": b"\r\nPassword:",
            "Xpon@Olt9417#": PROMPT,
            "terminal length 0": _respuesta("terminal length 0", ""),
            "show onu": b"show onu\r\nONU 1\r\n --More-- ",
            "": b"ONU 2" + PROMPT,  # el espacio que contesta la paginación
        }
        transporte, falso = conectar(guion=guion)
        transporte.abrir()

        salida = transporte.ejecutar("show onu")

        assert b" " in falso.enviado
        assert "ONU 1" in salida and "ONU 2" in salida
        transporte.cerrar()

    def test_un_equipo_que_deja_de_contestar_da_timeout_y_no_datos_a_medias(self, conectar) -> None:
        guion = {
            "admin": b"\r\nPassword:",
            "Xpon@Olt9417#": PROMPT,
            "terminal length 0": _respuesta("terminal length 0", ""),
            "show onu": b"show onu\r\nONU 1\r\n",  # sin prompt final: se cortó
        }
        transporte, _ = conectar(guion=guion)
        transporte.abrir()

        with pytest.raises(ErrorTiempoAgotado):
            transporte.ejecutar("show onu")


class TestAyudaEnLinea:
    def test_el_signo_de_pregunta_va_sin_enter(self, conectar) -> None:
        """Mandar Enter después del '?' ejecutaría lo tipeado. Nunca se manda."""
        guion = {
            "admin": b"\r\nPassword:",
            "Xpon@Olt9417#": PROMPT,
            "terminal length 0": _respuesta("terminal length 0", ""),
        }
        transporte, falso = conectar(guion=guion)
        transporte.abrir()
        falso.pendiente.append(b"\r\n  onu    ONU\r\n  gpon   GPON\r\nOLT_Belgrano#show ")
        falso.pendiente.append(PROMPT)

        texto = transporte.ayuda("show ")

        assert "show ?" in falso.texto_enviado
        assert "show ?\r\n" not in falso.texto_enviado
        assert "onu" in texto and "gpon" in texto

    def test_no_se_pierde_la_ultima_opcion_cuando_el_prompt_viene_pegado(self, conectar) -> None:
        """Varios equipos redibujan el prompt sin salto de línea previo.

        Descartar esa línea entera se comería la última opción de la ayuda, que
        es exactamente la que suele interesar.
        """
        transporte, falso = conectar()
        transporte.abrir()
        falso.pendiente.append(b"\r\n  onu   ONU\r\n  version VersionOLT_Belgrano#show ")
        falso.pendiente.append(PROMPT)

        texto = transporte.ayuda("show ")

        assert "version Version" in texto
        assert "OLT_Belgrano" not in texto

    def test_la_linea_tipeada_se_borra_para_no_mezclarse_con_el_comando_siguiente(
        self, conectar
    ) -> None:
        transporte, falso = conectar()
        transporte.abrir()
        falso.pendiente.append(b"\r\n  onu\r\nOLT_Belgrano#show ")
        falso.pendiente.append(PROMPT)

        transporte.ayuda("show ")

        assert b"\x15" in falso.enviado  # Ctrl-U
