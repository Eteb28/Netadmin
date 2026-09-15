"""Detección temprana de fallas ópticas y de saturación GPON.

Implementa las acciones 2.2 y 2.3 del informe «06 — Plan de Mejora de Pucará»,
que el propio informe califica como las de mayor valor comercial:

    «La 2.2 es la de mayor valor comercial: convierte a la empresa de reactiva a
     preventiva. Llamar al cliente antes de que se corte cambia por completo la
     percepción del servicio.»

El diagnóstico de red que la motiva: 9.019 caídas en 2026 con mediana de 50
segundos. Un corte de 50 s corta una videollamada pero no genera reclamo — el
cliente acumula bronca en silencio y a los meses pide la baja. Detectar la ONU
que se está degradando **antes** de que corte es lo que rompe ese ciclo.

Todo se calcula sobre datos que Pucará ya tiene: `onu_senal` (última lectura del
poller) y `onu_senal_hist` (histórico). No hace falta ningún equipo nuevo.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from pucara.repositories.optica import OpticaRepository

# ── Umbrales ─────────────────────────────────────────────────────────────
# Caída de Rx respecto de la línea base de la propia ONU. El informe pide 3 dB.
# 3 dB es la mitad de la potencia recibida: no es ruido de medición, es algo
# físico que cambió (humedad en un empalme, curvatura, conector sucio).
CAIDA_AVISO = 3.0
CAIDA_GRAVE = 6.0

# Niveles absolutos. Por debajo de −27 dBm la ONU está al borde de perder
# sincronismo: cualquier degradación adicional la desconecta.
RX_CRITICO = -27.0
RX_LIMITE = -25.0
# Por arriba de −8 dBm la ONU está SATURADA: demasiada potencia también rompe.
RX_SATURADO = -8.0

# Mínimo de lecturas para que una línea base signifique algo.
MIN_LECTURAS = 5

# Ocupación de un puerto GPON. El split sano es 1:64; el máximo físico, 128.
PON_ALERTA = 64
PON_CRITICO = 100


@dataclass(frozen=True)
class OnuEnRiesgo:
    olt_id: int
    olt_nombre: str | None
    pon: int
    onu: int
    nro_cliente: str | None
    cliente_nombre: str | None
    cliente_id: int | None
    rx: float | None
    rx_base: float | None
    caida_db: float | None
    motivo: str
    severidad: str          # 'critica' | 'alta' | 'media'
    online: bool

    @property
    def ubicacion(self) -> str:
        olt = self.olt_nombre or f"OLT {self.olt_id}"
        return f"{olt} · GPON0/{self.pon}:{self.onu}"


@dataclass(frozen=True)
class PonSaturado:
    olt_id: int
    olt_nombre: str | None
    pon: int
    onus: int
    online: int
    severidad: str

    @property
    def ubicacion(self) -> str:
        return f"{self.olt_nombre or f'OLT {self.olt_id}'} · GPON0/{self.pon}"


@dataclass(frozen=True)
class ResumenOptico:
    total_onus: int
    online: int
    offline: int
    degradadas: int
    criticas: int
    saturadas: int
    pon_sobre_umbral: int
    rx_promedio: float | None
    en_riesgo: list[OnuEnRiesgo] = field(default_factory=list)
    pones: list[PonSaturado] = field(default_factory=list)


class ServicioDegradacion:
    def __init__(self, repo: OpticaRepository) -> None:
        self._r = repo

    def analizar(self, dias_historia: int = 30) -> ResumenOptico:
        actuales = self._r.lecturas_actuales()
        historia = self._r.historico_rx(dias_historia)

        en_riesgo: list[OnuEnRiesgo] = []
        rx_validos: list[float] = []
        online = offline = 0

        for l in actuales:
            if l.online:
                online += 1
            else:
                offline += 1
            if l.rx is not None:
                rx_validos.append(l.rx)

            riesgo = self._evaluar(l, historia.get((l.olt_id, l.pon, l.onu), []))
            if riesgo is not None:
                en_riesgo.append(riesgo)

        # Primero lo que hay que atender hoy.
        orden = {"critica": 0, "alta": 1, "media": 2}
        en_riesgo.sort(key=lambda r: (orden[r.severidad], -(r.caida_db or 0)))

        pones = [p for p in map(self._evaluar_pon, self._r.ocupacion_por_pon()) if p]

        return ResumenOptico(
            total_onus=len(actuales),
            online=online,
            offline=offline,
            degradadas=sum(1 for r in en_riesgo if r.caida_db is not None),
            criticas=sum(1 for r in en_riesgo if r.severidad == "critica"),
            saturadas=sum(1 for r in en_riesgo if "saturada" in r.motivo.lower()),
            pon_sobre_umbral=len(pones),
            rx_promedio=round(statistics.fmean(rx_validos), 1) if rx_validos else None,
            en_riesgo=en_riesgo,
            pones=pones,
        )

    # ── evaluación de una ONU ────────────────────────────────────────────
    def _evaluar(self, l, historicos: list[float]) -> OnuEnRiesgo | None:
        """Devuelve el riesgo de una ONU, o None si está sana.

        Una ONU caída NO se evalúa acá: de eso se ocupa el motor de incidentes.
        Esto busca la que **todavía funciona** pero se está yendo.
        """
        if l.rx is None or not l.online:
            return None

        base = _linea_base(historicos, l.rx)
        caida = round(base - l.rx, 1) if base is not None else None

        # El nivel absoluto manda sobre la tendencia: una ONU en −28 dBm es
        # urgente aunque siempre haya estado ahí.
        if l.rx <= RX_CRITICO:
            return self._armar(l, base, caida, "critica",
                               f"Señal crítica ({l.rx} dBm) — al borde de perder sincronismo")
        if l.rx >= RX_SATURADO:
            return self._armar(l, base, caida, "alta",
                               f"ONU saturada ({l.rx} dBm) — demasiada potencia recibida")
        if caida is not None and caida >= CAIDA_GRAVE:
            return self._armar(l, base, caida, "critica",
                               f"Degradación grave: cayó {caida} dB respecto de su normal ({base} dBm)")
        if caida is not None and caida >= CAIDA_AVISO:
            return self._armar(l, base, caida, "alta",
                               f"Degradación: cayó {caida} dB respecto de su normal ({base} dBm)")
        if l.rx <= RX_LIMITE:
            return self._armar(l, base, caida, "media",
                               f"Señal baja ({l.rx} dBm) — sin margen ante cualquier empeoramiento")
        return None

    @staticmethod
    def _armar(l, base, caida, severidad, motivo) -> OnuEnRiesgo:
        return OnuEnRiesgo(
            olt_id=l.olt_id, olt_nombre=l.olt_nombre, pon=l.pon, onu=l.onu,
            nro_cliente=l.nro_cliente, cliente_nombre=l.cliente_nombre,
            cliente_id=l.cliente_id, rx=l.rx, rx_base=base, caida_db=caida,
            motivo=motivo, severidad=severidad, online=l.online,
        )

    @staticmethod
    def _evaluar_pon(o) -> PonSaturado | None:
        if o.onus <= PON_ALERTA:
            return None
        return PonSaturado(
            olt_id=o.olt_id, olt_nombre=o.olt_nombre, pon=o.pon,
            onus=o.onus, online=o.online,
            severidad="critica" if o.onus > PON_CRITICO else "alta",
        )


def _linea_base(historicos: list[float], actual: float) -> float | None:
    """Lo que es «normal» para esta ONU, en dBm.

    Mediana y no promedio: si el poller registró tres lecturas basura durante un
    corte, el promedio se desploma y la ONU parecería estar mejorando. La
    mediana ignora esos valores.

    La lectura actual se excluye del cálculo — comparar un valor contra un
    conjunto que lo incluye diluye justamente la caída que se quiere detectar.
    """
    if len(historicos) < MIN_LECTURAS:
        return None
    previos = historicos[:-1] if len(historicos) > MIN_LECTURAS else historicos
    return round(statistics.median(previos), 1)
