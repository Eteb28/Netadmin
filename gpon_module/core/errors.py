"""Jerarquía de excepciones propia del módulo GPON.

Toda excepción que cruce la frontera de un driver debe ser una de éstas: el
núcleo nunca debe atrapar ``socket.timeout`` ni ``pysnmp.Error``. Así los
servicios pueden decidir sin conocer el transporte.

Distinción crítica: ``ErrorTiempoAgotado`` **no** significa "no existe". Un
timeout intermitente (visto en 192.141.23.2) que se interprete como ausencia
genera una baja masiva falsa. Ver riesgo R5 en docs/00-investigacion.md.
"""

from __future__ import annotations


class ErrorGPON(Exception):
    """Raíz de todos los errores del módulo."""


# --- Transporte -----------------------------------------------------------


class ErrorTransporte(ErrorGPON):
    """Falla de comunicación con el equipo."""


class ErrorConexion(ErrorTransporte):
    """No se pudo establecer la conexión."""


class ErrorAutenticacion(ErrorTransporte):
    """Credenciales rechazadas por el equipo."""


class ErrorTiempoAgotado(ErrorTransporte):
    """Venció el tiempo de espera.

    Nunca debe traducirse a "el objeto no existe": ver el docstring del módulo.
    """


class ErrorLecturaParcial(ErrorTransporte):
    """La lectura se completó a medias (walk truncado, sesión cortada).

    Los datos obtenidos pueden ser válidos, pero el conjunto está incompleto.
    Quien la reciba debe marcar la corrida como parcial y **no** disparar
    alarmas de baja masiva.
    """

    def __init__(self, mensaje: str, obtenidos: int = 0, esperados: int | None = None) -> None:
        super().__init__(mensaje)
        self.obtenidos = obtenidos
        self.esperados = esperados


# --- CLI ------------------------------------------------------------------


class ErrorComando(ErrorGPON):
    """El equipo rechazó un comando (p. ej. ``% Invalid input detected``).

    Aborta la secuencia en curso: seguir enviando comandos después de un
    rechazo es lo que deja una OLT a medio configurar.
    """

    def __init__(self, mensaje: str, comando: str = "", salida: str = "") -> None:
        super().__init__(mensaje)
        self.comando = comando
        self.salida = salida


class ErrorParseo(ErrorGPON):
    """La salida del equipo no tiene la forma esperada.

    Habitualmente significa que cambió la versión de firmware (riesgo R2).
    """

    def __init__(self, mensaje: str, texto_crudo: str = "") -> None:
        super().__init__(mensaje)
        self.texto_crudo = texto_crudo


# --- Dominio --------------------------------------------------------------


class CapacidadNoSoportada(ErrorGPON):
    """El equipo no puede hacer lo que se le pidió, y lo declaró de antemano."""

    def __init__(self, capacidad: object, fabricante: object = None) -> None:
        detalle = f" en {fabricante}" if fabricante is not None else ""
        super().__init__(f"Capacidad no soportada{detalle}: {capacidad}")
        self.capacidad = capacidad
        self.fabricante = fabricante


class DriverNoRegistrado(ErrorGPON):
    """No hay driver para ese fabricante."""


class ErrorValidacion(ErrorGPON):
    """Datos de entrada inválidos, detectados antes de tocar el equipo."""


class ErrorRepositorio(ErrorGPON):
    """Falla de acceso a datos."""


class NoEncontrado(ErrorRepositorio):
    """La entidad solicitada no existe en la base."""


class ErrorConfiguracion(ErrorGPON):
    """Configuración del módulo incompleta o inconsistente."""


class ErrorCifrado(ErrorGPON):
    """No se pudo cifrar o descifrar un secreto."""


class OLTOcupada(ErrorGPON):
    """Otra operación tiene tomada la sesión CLI de esa OLT (riesgo R4)."""
