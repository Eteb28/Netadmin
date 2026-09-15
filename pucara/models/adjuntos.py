"""Imágenes adjuntas a las notas de "Mis Tareas".

Los bytes NO se guardan en la base: van al disco y acá queda sólo la ficha. Una
captura de pantalla pesa entre 100 KB y 2 MB; meterlas en SQLite haría que
cualquier `SELECT *` sobre las notas arrastre megabytes, y que el backup diario
crezca sin control.

`tarea_id` no tiene FOREIGN KEY porque `tareas_usuario` todavía es una tabla
heredada sin modelo (se migra en la fase 7). El borrado en cascada lo hace el
servicio, no el motor. Está anotado como deuda a propósito.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from pucara.db import Base, UtcDateTime
from pucara.models.reclamos import ahora

# Formatos aceptados: mapa de firma binaria → (mime, extensión).
# Se valida por los **bytes reales**, no por lo que declara el navegador: el
# Content-Type de una subida lo elige el cliente y no prueba nada.
# SVG queda deliberadamente afuera: es XML y puede contener <script>.
FIRMAS: tuple[tuple[bytes, str, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png", "png"),
    (b"\xff\xd8\xff", "image/jpeg", "jpg"),
    (b"GIF87a", "image/gif", "gif"),
    (b"GIF89a", "image/gif", "gif"),
)

MAX_BYTES = 5 * 1024 * 1024      # 5 MB por imagen
MAX_POR_NOTA = 6


def detectar_formato(datos: bytes) -> tuple[str, str] | None:
    """(mime, extensión) si los bytes son una imagen soportada; si no, None."""
    for firma, mime, ext in FIRMAS:
        if datos.startswith(firma):
            return mime, ext
    # WEBP es RIFF con el marcador en el byte 8
    if len(datos) >= 12 and datos[:4] == b"RIFF" and datos[8:12] == b"WEBP":
        return "image/webp", "webp"
    return None


class AdjuntoTarea(Base):
    __tablename__ = "tarea_adjuntos"
    __table_args__ = (
        Index("ix_adjunto_tarea", "tarea_id"),
        # El propietario se guarda acá y no se resuelve por JOIN: cada descarga
        # verifica la pertenencia con una sola consulta a esta tabla.
        Index("ix_adjunto_propietario", "propietario"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tarea_id: Mapped[int] = mapped_column(Integer, nullable=False)
    propietario: Mapped[str] = mapped_column(String(80), nullable=False)

    archivo: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    mime: Mapped[str] = mapped_column(String(40), nullable=False)
    bytes_: Mapped[int] = mapped_column("bytes", Integer, nullable=False)
    nombre_original: Mapped[str | None] = mapped_column(String(200))

    creado: Mapped[datetime] = mapped_column(UtcDateTime, default=ahora, nullable=False)
