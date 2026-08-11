"""Reglas de dominio sobre potencias ópticas.

Vive en el núcleo, no en un driver: un −28 dBm significa lo mismo venga de una
VSOL o de una ZTE. Los drivers *miden*; acá se *interpreta*.
"""

from __future__ import annotations

from dataclasses import dataclass

from .enums import ClasificacionOptica


@dataclass(frozen=True, slots=True)
class UmbralesOpticos:
    """Umbrales de clasificación de la potencia de recepción, en dBm.

    ``saturacion`` existe por un hallazgo real: se encontró una ONU a
    −1,57 dBm que el sistema anterior contaba como "óptima" porque sólo miraba
    el extremo bajo. Demasiada luz satura y daña el receptor; es alarma, no un
    valor bueno.
    """

    saturacion: float = -8.0
    optima_minima: float = -25.0
    aceptable_minima: float = -27.0
    baja_minima: float = -29.0

    def __post_init__(self) -> None:
        orden = (self.saturacion, self.optima_minima, self.aceptable_minima, self.baja_minima)
        if list(orden) != sorted(orden, reverse=True):
            raise ValueError(
                "Los umbrales ópticos deben ir de mayor a menor: "
                "saturacion > optima_minima > aceptable_minima > baja_minima"
            )


UMBRALES_POR_DEFECTO = UmbralesOpticos()


def clasificar(
    rx_dbm: float | None, umbrales: UmbralesOpticos = UMBRALES_POR_DEFECTO
) -> ClasificacionOptica:
    """Clasifica una potencia de recepción.

    ``None`` no es cero ni es "malo": es ausencia de lectura, y se distingue
    para no contar como caída una ONU que simplemente no reportó.
    """
    if rx_dbm is None:
        return ClasificacionOptica.SIN_LECTURA
    if rx_dbm > umbrales.saturacion:
        return ClasificacionOptica.SATURADA
    if rx_dbm >= umbrales.optima_minima:
        return ClasificacionOptica.OPTIMA
    if rx_dbm >= umbrales.aceptable_minima:
        return ClasificacionOptica.ACEPTABLE
    if rx_dbm >= umbrales.baja_minima:
        return ClasificacionOptica.BAJA
    return ClasificacionOptica.CRITICA


def es_problematica(
    rx_dbm: float | None, umbrales: UmbralesOpticos = UMBRALES_POR_DEFECTO
) -> bool:
    """¿Esta potencia requiere atención? Incluye saturación, no sólo señal débil."""
    return clasificar(rx_dbm, umbrales) in (
        ClasificacionOptica.SATURADA,
        ClasificacionOptica.BAJA,
        ClasificacionOptica.CRITICA,
    )


def perdida_optica(tx_olt_dbm: float | None, rx_onu_dbm: float | None) -> float | None:
    """Atenuación del tramo descendente, en dB."""
    if tx_olt_dbm is None or rx_onu_dbm is None:
        return None
    return round(tx_olt_dbm - rx_onu_dbm, 2)
