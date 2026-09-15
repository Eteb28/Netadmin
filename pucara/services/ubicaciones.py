"""Reubicación de NAPs en el mapa.

Nace de un problema concreto: varias NAPs quedaron mal georreferenciadas y
corregirlas a mano, tipeando coordenadas, es lento y propenso a errar de nuevo.
Este servicio permite moverlas desde el mapa, con validación y auditoría.
"""
from __future__ import annotations

from dataclasses import dataclass

from pucara.repositories.auditoria import AuditoriaRepository
from pucara.repositories.naps import NapRepository


class ErrorUbicacion(Exception):
    """Error de negocio. La capa API lo traduce a HTTP 400."""


class NapInexistente(Exception):
    """La NAP no existe. Se traduce a 404."""


# Caja aproximada de la Argentina continental. NO se usa para rechazar —sería
# arrogante—, sino para avisar. El error típico al cargar coordenadas a mano es
# invertir latitud y longitud: (-31.7, -60.5) tipeado al revés da (-60.5, -31.7),
# que cae en el Atlántico Sur. Avisar ahí evita justamente el problema que este
# servicio vino a resolver.
ZONA_LAT = (-56.0, -21.0)
ZONA_LNG = (-74.0, -53.0)


@dataclass(frozen=True)
class MovimientoNap:
    nap_id: int
    nombre: str
    lat_anterior: float | None
    lng_anterior: float | None
    lat: float
    lng: float
    metros_movidos: int | None
    fuera_de_zona: bool


class ServicioUbicacionNap:
    def __init__(self, repo: NapRepository, auditoria: AuditoriaRepository) -> None:
        self._r = repo
        self._aud = auditoria

    def mover(self, nap_id: int, lat, lng, usuario: str = "sistema") -> MovimientoNap:
        lat_f = _a_float(lat, "latitud")
        lng_f = _a_float(lng, "longitud")

        if not -90 <= lat_f <= 90:
            raise ErrorUbicacion(f"La latitud {lat_f} está fuera del rango −90..90")
        if not -180 <= lng_f <= 180:
            raise ErrorUbicacion(f"La longitud {lng_f} está fuera del rango −180..180")

        nap = self._r.obtener(nap_id)
        if nap is None:
            raise NapInexistente(f"No existe la NAP {nap_id}")

        self._r.mover(nap_id, lat_f, lng_f)

        movimiento = MovimientoNap(
            nap_id=nap_id, nombre=nap.nombre,
            lat_anterior=nap.lat, lng_anterior=nap.lng,
            lat=lat_f, lng=lng_f,
            metros_movidos=_metros(nap.lat, nap.lng, lat_f, lng_f),
            fuera_de_zona=not (
                ZONA_LAT[0] <= lat_f <= ZONA_LAT[1] and ZONA_LNG[0] <= lng_f <= ZONA_LNG[1]
            ),
        )

        # Misma transacción que el UPDATE: si el cambio se revierte, la
        # constancia también. Ver el comentario de AuditoriaRepository.
        self._aud.registrar(
            tipo="mod",
            modulo="naps",
            titulo=f"NAP {nap.nombre}: coordenadas corregidas",
            detalle=(
                f"De ({_fmt(nap.lat)}, {_fmt(nap.lng)}) a ({lat_f:.6f}, {lng_f:.6f})"
                + (f" — {movimiento.metros_movidos} m"
                   if movimiento.metros_movidos is not None else "")
                + (" — FUERA de la zona de cobertura" if movimiento.fuera_de_zona else "")
            ),
            usuario=usuario,
        )
        return movimiento


def _a_float(valor, campo: str) -> float:
    if valor is None or valor == "":
        raise ErrorUbicacion(f"Falta la {campo}")
    try:
        return float(valor)
    except (TypeError, ValueError):
        raise ErrorUbicacion(f"La {campo} '{valor}' no es un número") from None


def _fmt(v) -> str:
    return f"{v:.6f}" if isinstance(v, (int, float)) else "sin coordenada"


def _metros(lat1, lng1, lat2, lng2) -> int | None:
    """Distancia aproximada del movimiento, para que la auditoría diga algo útil.

    Equirectangular en vez de Haversine: a estas distancias (metros o pocos
    kilómetros) la diferencia es despreciable y se lee de un vistazo.
    """
    if lat1 is None or lng1 is None:
        return None
    import math

    lat_media = math.radians((lat1 + lat2) / 2)
    dx = math.radians(lng2 - lng1) * math.cos(lat_media)
    dy = math.radians(lat2 - lat1)
    return int(round(math.hypot(dx, dy) * 6_371_000))
