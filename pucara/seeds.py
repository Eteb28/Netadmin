"""Carga inicial de los catálogos administrables de reclamos.

Son un **punto de partida**, no una lista cerrada: el objetivo del catálogo es
que se administre desde Configuración sin tocar código. Por eso el sembrado es
idempotente y no destructivo: agrega lo que falte y jamás pisa ni borra lo que
el usuario haya cargado o desactivado.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from pucara.repositories.reclamos import CausaRepository, ResolucionRepository

CAUSAS: tuple[str, ...] = (
    "Sin servicio",
    "Lentitud",
    "Microcortes",
    "Problema WiFi",
    "Router",
    "ONU",
    "Señal inalámbrica",
    "Cableado interno",
    "Corte eléctrico",
    "OLT",
    "AP saturado",
    "Backbone",
    "Configuración",
    "Facturación",
    "Instalación",
    "Otro",
)

RESOLUCIONES: tuple[str, ...] = (
    "Reinicio ONU",
    "Reinicio Router",
    "Cambio de ONU",
    "Cambio Router",
    "Cambio Fuente",
    "Cambio Patchcord",
    "Reconfiguración PPPoE",
    "Cambio AP",
    "Cambio Canal",
    "Ajuste Señal",
    "Cambio Splitter",
    "Cambio Puerto OLT",
    "Cambio Radio",
    "Cambio Cable",
    "Visita Técnica",
    "Derivado",
    "Sin Falla Encontrada",
    "Otro",
)


def sembrar(s: Session) -> dict[str, int]:
    """Inserta lo que falte. Devuelve cuántos agregó de cada catálogo.

    Correr esto dos veces no duplica nada: la búsqueda es por nombre, sin
    distinguir mayúsculas. Y si alguien desactivó "Facturación" porque no la
    usa, sigue desactivada — se busca **incluyendo inactivos**.
    """
    agregados = {"causas": 0, "resoluciones": 0}

    for clave, repo, nombres in (
        ("causas", CausaRepository(s), CAUSAS),
        ("resoluciones", ResolucionRepository(s), RESOLUCIONES),
    ):
        for orden, nombre in enumerate(nombres, start=10):
            if repo.buscar_por_nombre(nombre) is None:
                # "Otro" al final siempre, aunque después se agreguen opciones.
                repo.crear(nombre, orden=999 if nombre == "Otro" else orden)
                agregados[clave] += 1

    return agregados
