"""Almacenamiento de archivos en disco.

Se aísla en su propia clase para que el servicio no sepa de rutas ni de `open()`:
en las pruebas se le pasa un directorio temporal y no hace falta tocar `uploads/`.

**El nombre del archivo lo genera esta clase, nunca el cliente.** Un nombre que
venga del navegador puede contener `../` o pisar un archivo existente; acá se usa
un UUID y una extensión de una lista cerrada.
"""
from __future__ import annotations

import pathlib
import uuid

EXTENSIONES_PERMITIDAS = frozenset({"png", "jpg", "gif", "webp"})


class AlmacenArchivos:
    def __init__(self, base: str | pathlib.Path) -> None:
        self._base = pathlib.Path(base)
        self._base.mkdir(parents=True, exist_ok=True)

    def guardar(self, datos: bytes, extension: str) -> str:
        if extension not in EXTENSIONES_PERMITIDAS:
            raise ValueError(f"Extensión no permitida: {extension}")
        nombre = f"{uuid.uuid4().hex}.{extension}"
        (self._base / nombre).write_bytes(datos)
        return nombre

    def ruta(self, nombre: str) -> pathlib.Path | None:
        """Ruta absoluta de un archivo ya guardado, o None si no existe.

        Vuelve a validar que el nombre no se escape del directorio aunque lo
        haya generado esta misma clase: si mañana alguien guarda un nombre en la
        base por otro camino, esto sigue siendo lo que impide leer /etc/passwd.
        """
        if not nombre or "/" in nombre or "\\" in nombre or nombre.startswith("."):
            return None
        p = (self._base / nombre).resolve()
        if p.parent != self._base.resolve() or not p.is_file():
            return None
        return p

    def borrar(self, nombre: str) -> bool:
        p = self.ruta(nombre)
        if p is None:
            return False
        p.unlink()
        return True
