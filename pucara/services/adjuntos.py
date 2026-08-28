"""Adjuntos de las notas de "Mis Tareas".

Las notas son **privadas**: sólo las ve quien las escribió. Por eso cada
operación de este servicio empieza verificando la pertenencia, incluida la
descarga. Un adjunto al que se llega sabiendo el id no es aceptable.
"""
from __future__ import annotations

import pathlib
from dataclasses import dataclass
from datetime import datetime

from pucara.almacen import AlmacenArchivos
from pucara.models.adjuntos import (
    MAX_BYTES, MAX_POR_NOTA, AdjuntoTarea, detectar_formato,
)
from pucara.repositories.adjuntos import AdjuntoRepository, TareaLegadaRepository


class ErrorAdjunto(Exception):
    """Error de negocio. La capa API lo traduce a HTTP 400."""


class NoAutorizado(Exception):
    """La nota no es de quien la pide (o no existe). Se traduce a 404.

    404 y no 403 a propósito: un 403 confirmaría que la nota existe y es de otro,
    que es información que no hace falta dar.
    """


@dataclass(frozen=True)
class AdjuntoDTO:
    id: int
    tarea_id: int
    mime: str
    bytes: int
    nombre_original: str | None
    creado: datetime

    @classmethod
    def desde_modelo(cls, a: AdjuntoTarea) -> AdjuntoDTO:
        return cls(
            id=a.id, tarea_id=a.tarea_id, mime=a.mime, bytes=a.bytes_,
            nombre_original=a.nombre_original, creado=a.creado,
        )


class ServicioAdjuntos:
    def __init__(
        self,
        adjuntos: AdjuntoRepository,
        tareas: TareaLegadaRepository,
        almacen: AlmacenArchivos,
    ) -> None:
        self._a = adjuntos
        self._t = tareas
        self._alm = almacen

    # ── verificación de pertenencia ──────────────────────────────────────
    def _exigir_nota_propia(self, tarea_id: int, usuario: str) -> None:
        if not usuario or self._t.duenio(tarea_id) != usuario:
            raise NoAutorizado("La nota no existe")

    def _exigir_adjunto_propio(self, adjunto_id: int, usuario: str) -> AdjuntoTarea:
        a = self._a.obtener(adjunto_id)
        if a is None or not usuario or a.propietario != usuario:
            raise NoAutorizado("El adjunto no existe")
        return a

    # ── operaciones ──────────────────────────────────────────────────────
    def guardar(
        self, tarea_id: int, usuario: str, datos: bytes,
        nombre_original: str | None = None,
    ) -> AdjuntoDTO:
        self._exigir_nota_propia(tarea_id, usuario)

        if not datos:
            raise ErrorAdjunto("El archivo está vacío")
        if len(datos) > MAX_BYTES:
            raise ErrorAdjunto(
                f"La imagen pesa {len(datos)//1024} KB y el máximo es "
                f"{MAX_BYTES//1024//1024} MB"
            )

        # El tipo sale de los bytes, no de lo que dijo el navegador.
        formato = detectar_formato(datos)
        if formato is None:
            raise ErrorAdjunto("El archivo no es una imagen PNG, JPG, GIF o WEBP")
        mime, extension = formato

        if self._a.contar_de_tarea(tarea_id) >= MAX_POR_NOTA:
            raise ErrorAdjunto(f"Una nota admite hasta {MAX_POR_NOTA} imágenes")

        archivo = self._alm.guardar(datos, extension)
        a = self._a.crear(
            tarea_id=tarea_id, propietario=usuario, archivo=archivo, mime=mime,
            bytes_=len(datos),
            # El nombre original es sólo una etiqueta para mostrar; el archivo en
            # disco se llama distinto y nunca se sirve con este nombre.
            nombre_original=(nombre_original or "").strip()[:200] or None,
        )
        return AdjuntoDTO.desde_modelo(a)

    def listar(self, tarea_id: int, usuario: str) -> list[AdjuntoDTO]:
        self._exigir_nota_propia(tarea_id, usuario)
        return [AdjuntoDTO.desde_modelo(a) for a in self._a.listar_de_tarea(tarea_id)]

    def listar_por_tarea(self, tarea_ids: list[int], usuario: str) -> dict[int, list[AdjuntoDTO]]:
        """Adjuntos de varias notas. Filtra por propietario en vez de verificar
        una por una: es una sola consulta y el resultado es el mismo."""
        crudos = self._a.listar_de_tareas(tarea_ids)
        return {
            tid: [AdjuntoDTO.desde_modelo(a) for a in lista if a.propietario == usuario]
            for tid, lista in crudos.items()
            if any(a.propietario == usuario for a in lista)
        }

    def leer(self, adjunto_id: int, usuario: str) -> tuple[pathlib.Path, str]:
        """(ruta en disco, mime) para servir el archivo. Verifica pertenencia."""
        a = self._exigir_adjunto_propio(adjunto_id, usuario)
        ruta = self._alm.ruta(a.archivo)
        if ruta is None:
            raise NoAutorizado("El adjunto no existe")
        return ruta, a.mime

    def borrar(self, adjunto_id: int, usuario: str) -> None:
        a = self._exigir_adjunto_propio(adjunto_id, usuario)
        archivo = a.archivo
        self._a.borrar(a)
        # El archivo se borra DESPUÉS de la ficha: si el disco falla, queda un
        # archivo huérfano (inofensivo) y no una ficha apuntando a la nada.
        self._alm.borrar(archivo)

    def borrar_los_de_la_nota(self, tarea_id: int, usuario: str) -> int:
        """Se llama al eliminar una nota, para no dejar archivos colgados."""
        self._exigir_nota_propia(tarea_id, usuario)
        archivos = self._a.borrar_de_tarea(tarea_id)
        for nombre in archivos:
            self._alm.borrar(nombre)
        return len(archivos)
