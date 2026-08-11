"""Disciplina de la sesión CLI.

Cada test corresponde a un riesgo identificado en la Fase 0. Son los detalles
que rompen contra equipos reales, y por eso se prueban desde el primer día,
antes de que exista el driver VSOL.
"""

from __future__ import annotations

import threading
import time

import pytest

from gpon_module.core.errors import ErrorComando, ErrorTiempoAgotado, OLTOcupada
from gpon_module.drivers.mock import TransporteCLISimulado
from gpon_module.drivers.transport import detectar_rechazo, reintentar, sesion_exclusiva


class TestPaginacion:
    def test_se_desactiva_la_paginacion_al_abrir(self) -> None:
        """Sin esto, la primera salida larga cuelga la sesión esperando --More--."""
        transporte = TransporteCLISimulado()
        transporte.abrir()
        assert "terminal length 0" in transporte.enviados

    def test_un_equipo_que_no_conoce_el_comando_no_rompe_la_apertura(self) -> None:
        transporte = TransporteCLISimulado(rechazar_desconocidos=True)
        transporte.abrir()  # el comando inicial es rechazado y se sigue igual
        assert transporte.conectado


class TestRechazoDeComandos:
    def test_se_detecta_el_rechazo_tipico_de_una_cli_cisco(self) -> None:
        assert detectar_rechazo("% Invalid input detected at '^' marker")
        assert detectar_rechazo("Error: parameter out of range")
        assert detectar_rechazo("todo bien") is None

    def test_un_comando_rechazado_levanta_excepcion_en_vez_de_devolver_basura(self) -> None:
        """Si no, el parser toma el mensaje de error como si fueran datos."""
        transporte = TransporteCLISimulado(rechazar_desconocidos=True)
        with pytest.raises(ErrorComando) as excepcion:
            transporte.ejecutar("show onu inexistente")
        assert excepcion.value.comando == "show onu inexistente"

    def test_la_secuencia_se_aborta_en_el_primer_rechazo(self) -> None:
        """Seguir enviando comandos tras un rechazo deja la OLT a medio configurar."""
        transporte = TransporteCLISimulado(
            respuestas={"configure terminal": "ok", "interface gpon 0/1": "ok"},
            rechazar_desconocidos=True,
        )
        transporte.abrir()
        enviados_antes = len(transporte.enviados)

        with pytest.raises(ErrorComando, match="secuencia abortada"):
            transporte.ejecutar_secuencia(
                [
                    "configure terminal",
                    "interface gpon 0/1",
                    "comando mal escrito",
                    "write memory",  # no debe llegar a enviarse
                ]
            )

        posteriores = transporte.enviados[enviados_antes:]
        assert "write memory" not in posteriores
        assert len(posteriores) == 3


class TestReintentos:
    def test_reintenta_los_timeouts_con_espera_creciente(self) -> None:
        esperas: list[float] = []
        intentos = {"n": 0}

        def operacion() -> str:
            intentos["n"] += 1
            if intentos["n"] < 3:
                raise ErrorTiempoAgotado("sin respuesta")
            return "ok"

        resultado = reintentar(
            operacion, intentos=4, espera_inicial=1.0, dormir=esperas.append
        )

        assert resultado == "ok"
        assert esperas == [1.0, 2.0]  # backoff exponencial

    def test_no_reintenta_un_comando_invalido(self) -> None:
        """Reenviar un comando mal formado no lo va a hacer válido."""
        intentos = {"n": 0}

        def operacion() -> str:
            intentos["n"] += 1
            raise ErrorComando("% Invalid input detected")

        with pytest.raises(ErrorComando):
            reintentar(operacion, intentos=3, dormir=lambda _: None)
        assert intentos["n"] == 1

    def test_la_apertura_de_sesion_sobrevive_a_un_timeout_pasajero(self) -> None:
        transporte = TransporteCLISimulado(fallas_de_apertura=2, intentos=3)
        transporte.abrir()
        assert transporte.conectado
        assert transporte.aperturas == 3


class TestSesionExclusiva:
    def test_dos_operaciones_no_entran_a_la_vez_en_la_misma_olt(self) -> None:
        """La CLI de estas OLT es de sesión única: el entrelazado es impredecible."""
        orden: list[str] = []

        def trabajo(nombre: str) -> None:
            with sesion_exclusiva("olt-a"):
                orden.append(f"{nombre}-entra")
                time.sleep(0.05)
                orden.append(f"{nombre}-sale")

        hilos = [threading.Thread(target=trabajo, args=(n,)) for n in ("uno", "dos")]
        for hilo in hilos:
            hilo.start()
        for hilo in hilos:
            hilo.join()

        # Nadie entra mientras otro no salió.
        assert orden[1].endswith("-sale")
        assert orden[3].endswith("-sale")

    def test_distintas_olt_no_se_bloquean_entre_si(self) -> None:
        with sesion_exclusiva("olt-a"), sesion_exclusiva("olt-b"):
            pass  # no debe trabarse

    def test_esperar_de_mas_avisa_en_vez_de_colgarse(self) -> None:
        with sesion_exclusiva("olt-lenta"):
            resultado: list[Exception] = []

            def intentar() -> None:
                try:
                    with sesion_exclusiva("olt-lenta", timeout_segundos=0.05):
                        pass
                except OLTOcupada as exc:
                    resultado.append(exc)

            hilo = threading.Thread(target=intentar)
            hilo.start()
            hilo.join()

        assert resultado and isinstance(resultado[0], OLTOcupada)
