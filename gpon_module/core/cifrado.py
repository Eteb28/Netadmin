"""Cifrado en reposo de las credenciales de OLT (mitiga el riesgo R8).

Una base con la contraseña de administrador de todas las OLT en texto plano es
un problema de seguridad de primer orden: con eso se borran ONUs. Las
credenciales se guardan cifradas y sólo existen en claro en memoria durante la
operación que las necesita.

La clave se toma de la variable de entorno ``GPON_CLAVE_CIFRADO`` (formato
Fernet, base64 de 32 bytes). Para generarla::

    python -m gpon_module.cli generar-clave
"""

from __future__ import annotations

import base64
import os

from .errors import ErrorCifrado, ErrorConfiguracion

VARIABLE_CLAVE = "GPON_CLAVE_CIFRADO"
_PREFIJO_PLANO = "plano:"


class CifradorFernet:
    """Cifrado simétrico autenticado sobre ``cryptography.Fernet``."""

    def __init__(self, clave: str | bytes | None = None) -> None:
        try:
            from cryptography.fernet import Fernet, InvalidToken
        except ImportError as exc:  # pragma: no cover - depende del entorno
            raise ErrorConfiguracion(
                "Falta el paquete 'cryptography'. Instalá las dependencias del módulo "
                "o usá CifradorNulo explícitamente en desarrollo."
            ) from exc

        self._InvalidToken = InvalidToken
        material = clave or os.environ.get(VARIABLE_CLAVE)
        if not material:
            raise ErrorConfiguracion(
                f"No hay clave de cifrado. Definí {VARIABLE_CLAVE} "
                f"(generala con: python -m gpon_module.cli generar-clave)."
            )
        if isinstance(material, str):
            material = material.encode()
        try:
            self._fernet = Fernet(material)
        except (ValueError, TypeError) as exc:
            raise ErrorConfiguracion(f"Clave de cifrado inválida: {exc}") from exc

    @staticmethod
    def generar_clave() -> str:
        """Genera una clave nueva lista para ``GPON_CLAVE_CIFRADO``."""
        from cryptography.fernet import Fernet

        return Fernet.generate_key().decode()

    def cifrar(self, texto: str) -> str:
        if not texto:
            return ""
        return self._fernet.encrypt(texto.encode()).decode()

    def descifrar(self, texto_cifrado: str) -> str:
        if not texto_cifrado:
            return ""
        try:
            return self._fernet.decrypt(texto_cifrado.encode()).decode()
        except self._InvalidToken as exc:
            raise ErrorCifrado(
                "No se pudo descifrar la credencial: la clave no corresponde "
                "o el dato está corrupto."
            ) from exc


class CifradorNulo:
    """Sin cifrado real. **Sólo para desarrollo y tests.**

    Marca los valores con un prefijo para que quede evidente en la base que no
    están protegidos, y para que nunca se confunda un valor de desarrollo con
    uno cifrado de verdad.
    """

    def cifrar(self, texto: str) -> str:
        if not texto:
            return ""
        return _PREFIJO_PLANO + base64.b64encode(texto.encode()).decode()

    def descifrar(self, texto_cifrado: str) -> str:
        if not texto_cifrado:
            return ""
        if not texto_cifrado.startswith(_PREFIJO_PLANO):
            raise ErrorCifrado(
                "El valor está cifrado con una clave real; CifradorNulo no puede leerlo."
            )
        return base64.b64decode(texto_cifrado[len(_PREFIJO_PLANO) :]).decode()
