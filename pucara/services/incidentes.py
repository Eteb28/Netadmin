"""Motor unificado de incidentes (fase 4, ADR-0003).

Implementa la máquina de estados ACTIVA → RECUPERADA → CERRADA, el cierre
automático por estabilidad sostenida y la correlación de caídas masivas.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import timedelta

from pucara.models.incidentes import (
    AlcanceIncidente, CausaProbable, EstadoIncidente, Incidente, IncidenteAfectado,
)
from pucara.models.reclamos import ahora
from pucara.repositories.incidentes import IncidenteRepository


@dataclass(frozen=True)
class ConfiguracionMotor:
    """Parámetros configurables (el pedido pide que el tiempo sea ajustable)."""

    minutos_estabilidad: int = 5        # cuánto debe aguantar antes de cerrar
    umbral_masivo: int = 3              # ONU caídas para considerarlo masivo
    pct_masivo_pon: float = 0.30        # ...o este % del PON
    ventana_correlacion_min: int = 10   # dentro de esta ventana


@dataclass(frozen=True)
class LecturaOnu:
    """Estado de una ONU en un sondeo. Entrada del motor."""

    referencia: str
    olt_id: int
    pon: int
    online: bool
    cliente_id: int | None = None
    nro_cliente: str | None = None
    motivo_caida: str | None = None     # 'Power Off' | 'Onu Los' | None


class MotorIncidentes:
    def __init__(self, repo: IncidenteRepository, config: ConfiguracionMotor | None = None) -> None:
        self._r = repo
        self._cfg = config or ConfiguracionMotor()

    # ── procesamiento de un sondeo ───────────────────────────────────────
    def procesar_sondeo(self, lecturas: list[LecturaOnu], lectura_completa: bool = True) -> dict:
        """Procesa un ciclo del poller.

        `lectura_completa=False` desactiva la creación de incidentes: una lectura
        truncada NO significa que todo se cayó. Esta regla viene de un incidente
        real de producción, donde un walk óptico cortado marcó PONs enteros como
        caídos y disparó una tanda de avisos por Telegram.
        """
        resumen = {"nuevos": 0, "recuperados": 0, "cerrados": 0, "masivos": 0,
                   "omitido_por_lectura_parcial": False}

        if not lectura_completa:
            # Las recuperaciones SÍ se procesan: confirmar que algo volvió con
            # datos parciales es seguro; concluir que se cayó, no.
            resumen["omitido_por_lectura_parcial"] = True
            resumen["recuperados"] = self._procesar_recuperaciones(
                [l for l in lecturas if l.online]
            )
            resumen["cerrados"] = self.cerrar_estables()
            return resumen

        caidas = [l for l in lecturas if not l.online]
        vueltas = [l for l in lecturas if l.online]

        # 1) Correlación: agrupar por PON antes de crear incidentes sueltos
        masivos = self._detectar_masivos(caidas)
        refs_en_masivo = {ref for grupo in masivos.values() for ref in grupo}
        for (olt_id, pon), grupo in masivos.items():
            if self._crear_o_actualizar_masivo(olt_id, pon, grupo, caidas):
                resumen["masivos"] += 1

        # 2) Las caídas que no entraron en un incidente masivo van individuales
        for l in caidas:
            if l.referencia in refs_en_masivo:
                continue
            if self._abrir_individual(l):
                resumen["nuevos"] += 1

        # 3) Recuperaciones y cierres por estabilidad
        resumen["recuperados"] = self._procesar_recuperaciones(vueltas)
        resumen["cerrados"] = self.cerrar_estables()
        return resumen

    # ── detección de eventos masivos ─────────────────────────────────────
    def _detectar_masivos(self, caidas: list[LecturaOnu]) -> dict[tuple[int, int], set[str]]:
        """Agrupa por (OLT, PON) las caídas que superan el umbral."""
        por_pon: dict[tuple[int, int], list[LecturaOnu]] = {}
        for l in caidas:
            por_pon.setdefault((l.olt_id, l.pon), []).append(l)

        masivos = {}
        for clave, grupo in por_pon.items():
            total_pon = self._r.total_onus_en_pon(*clave)
            supera_absoluto = len(grupo) >= self._cfg.umbral_masivo
            supera_pct = total_pon and (len(grupo) / total_pon) >= self._cfg.pct_masivo_pon
            if supera_absoluto or supera_pct:
                masivos[clave] = {l.referencia for l in grupo}
        return masivos

    @staticmethod
    def inferir_causa(motivos: list[str | None]) -> CausaProbable:
        """Deduce la causa a partir de los motivos que reporta la propia OLT.

        Es la diferencia entre "hay 30 clientes caídos" y "hay un corte de luz en
        el barrio" o "se cortó la fibra del PON 5".
        """
        if not motivos:
            return CausaProbable.DESCONOCIDA
        cuenta = Counter((m or "").strip().lower() for m in motivos)
        total = sum(cuenta.values())
        power = cuenta.get("power off", 0)
        los = cuenta.get("onu los", 0)
        if total and power / total >= 0.7:
            return CausaProbable.CORTE_ELECTRICO
        if total and los / total >= 0.7:
            return CausaProbable.CORTE_FIBRA
        return CausaProbable.DESCONOCIDA

    def _crear_o_actualizar_masivo(
        self, olt_id: int, pon: int, refs: set[str], caidas: list[LecturaOnu]
    ) -> bool:
        referencia = f"olt:{olt_id}/pon:{pon}"
        del_grupo = [l for l in caidas if l.referencia in refs]
        causa = self.inferir_causa([l.motivo_caida for l in del_grupo])

        inc = self._r.buscar_abierto(AlcanceIncidente.PON, referencia)
        if inc is None:
            inc = self._r.crear(
                alcance=AlcanceIncidente.PON,
                referencia=referencia,
                titulo=f"Caída masiva en PON {pon} ({len(refs)} ONU)",
                causa_probable=causa,
                olt_id=olt_id, pon=pon,
            )
            nuevo = True
        else:
            # Ya existía: si había recuperado y volvió a caer, suma un ciclo.
            if inc.estado is EstadoIncidente.RECUPERADA:
                inc.estado = EstadoIncidente.ACTIVA
                inc.recuperado = None
                inc.ciclos += 1
            inc.causa_probable = causa
            nuevo = False

        existentes = {a.referencia for a in inc.afectados}
        for l in del_grupo:
            if l.referencia not in existentes:
                inc.afectados.append(IncidenteAfectado(
                    referencia=l.referencia, cliente_id=l.cliente_id,
                    nro_cliente=l.nro_cliente, motivo_caida=l.motivo_caida,
                ))
        inc.titulo = f"Caída masiva en PON {pon} ({len(inc.afectados)} ONU)"
        self._r.guardar(inc)
        return nuevo

    def _abrir_individual(self, l: LecturaOnu) -> bool:
        inc = self._r.buscar_abierto(AlcanceIncidente.ONU, l.referencia)
        if inc is not None:
            if inc.estado is EstadoIncidente.RECUPERADA:
                inc.estado = EstadoIncidente.ACTIVA
                inc.recuperado = None
                inc.ciclos += 1
                self._r.guardar(inc)
            return False        # ya estaba abierto: NO se duplica
        self._r.crear(
            alcance=AlcanceIncidente.ONU,
            referencia=l.referencia,
            titulo=f"ONU caída ({l.nro_cliente or l.referencia})",
            causa_probable=self.inferir_causa([l.motivo_caida]),
            olt_id=l.olt_id, pon=l.pon,
        )
        return True

    # ── recuperación y cierre automático ─────────────────────────────────
    def _procesar_recuperaciones(self, vueltas: list[LecturaOnu]) -> int:
        n = 0
        refs = {l.referencia for l in vueltas}
        for inc in self._r.listar_activos():
            if inc.alcance is AlcanceIncidente.ONU:
                if inc.referencia in refs and inc.estado is EstadoIncidente.ACTIVA:
                    inc.estado = EstadoIncidente.RECUPERADA
                    inc.recuperado = ahora()
                    self._r.guardar(inc)
                    n += 1
            elif inc.alcance is AlcanceIncidente.PON:
                # Un incidente masivo sólo se da por recuperado cuando volvieron
                # TODAS sus ONU: si vuelve la mitad, el problema sigue.
                pendientes = [a for a in inc.afectados if a.referencia not in refs]
                for a in inc.afectados:
                    if a.referencia in refs and a.recuperado is None:
                        a.recuperado = ahora()
                if not pendientes and inc.estado is EstadoIncidente.ACTIVA:
                    inc.estado = EstadoIncidente.RECUPERADA
                    inc.recuperado = ahora()
                    n += 1
                self._r.guardar(inc)
        return n

    def cerrar_estables(self) -> int:
        """Cierra los incidentes que llevan el tiempo de estabilidad exigido.

        No se cierra apenas vuelve: una ONU que oscila abriría y cerraría
        incidencias en bucle. Se exige que se sostenga.
        """
        limite = ahora() - timedelta(minutes=self._cfg.minutos_estabilidad)
        n = 0
        for inc in self._r.listar_recuperados_antes_de(limite):
            inc.estado = EstadoIncidente.CERRADA
            inc.cierre = ahora()
            inc.usuario_cierre = "Sistema"
            inc.motivo_cierre = "Recuperación automática"
            self._r.guardar(inc)
            n += 1
        return n
