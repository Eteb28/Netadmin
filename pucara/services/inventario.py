"""Concilia el inventario contra lo que la red ya está reportando.

Contesta la pregunta que arrastra años: **qué equipos existen de verdad, cuáles
figuran en el papel y ya no están, y cuáles están funcionando sin figurar.**

No hace falta escanear nada para empezar. La OLT reporta el serial de cada ONU,
los AP reportan la MAC y el modelo de cada equipo de cliente colgado de ellos, y
el poller sabe qué equipo de torre contestó y cuándo. Cruzar eso contra el
padrón y el depósito es gratis y dice de entrada cuán mal está el registro.

## La regla que no se negocia

**Que la red no lo vea no significa que no exista.** Un cliente suspendido tiene
la ONU apagada; un equipo inalámbrico se cae con una tormenta; el poller se
pierde una pasada. Concluir "no está" con eso sería inventar faltantes y llenar
la pantalla de ruido hasta que nadie la mire — el mismo error que ya se evitó en
el poller de OLT con las lecturas parciales.

Por eso: un cliente sin servicio que no aparece es lo ESPERADO y no se reporta;
y lo que sí se reporta lleva siempre los días que lleva sin verse, para que la
decisión la tome una persona con ese dato a la vista.

Este servicio es de SÓLO LECTURA. No escribe, no da de baja, no corrige nada:
produce la lista para revisar.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime

from pucara.repositories.inventario import (
    AvistajeEstacion, AvistajeOnu, ClienteRegistrado, EquipoTorre,
    InventarioRepository, ItemStock,
)

# ── Categorías de hallazgo ──────────────────────────────────────────────
OK = "ok"                    # la red lo ve y coincide con el registro
DIFIERE = "difiere"          # la red ve otro equipo del que figura
SIN_REGISTRO = "sin_registro"  # funciona en la red, no está en el registro
NO_VISTO = "no_visto"        # el registro dice que está, la red no lo ve
FANTASMA = "fantasma"        # figura en depósito pero está funcionando
HUERFANO = "huerfano"        # la red lo ve, no se puede atribuir a un cliente

#: Días sin aparecer a partir de los cuales vale la pena mirarlo. Por debajo es
#: ruido: un corte de luz de un día no es un equipo perdido.
DIAS_PARA_DUDAR = 7
#: A partir de acá deja de ser "raro" y pasa a ser "probablemente no está".
DIAS_PARA_ALARMA = 60

#: Dos seriales cortos coinciden por casualidad. Sólo se comparan por contención
#: cadenas de al menos este largo.
MIN_LARGO_CONTENCION = 6


def normalizar_serie(v: str | None) -> str:
    """Deja sólo alfanuméricos en mayúscula.

    El mismo equipo aparece como 'VSOL-1234 5678', 'vsol12345678' y
    'VSOL:12345678' según quién lo cargó. Sin esto, el 90 % de los cruces da
    'difiere' y el informe no sirve.
    """
    return re.sub(r"[^0-9A-Z]", "", (v or "").upper())


def normalizar_mac(v: str | None) -> str:
    """12 dígitos hexadecimales, sin separadores. Vacío si no lo es."""
    limpio = re.sub(r"[^0-9A-F]", "", (v or "").upper())
    return limpio if len(limpio) == 12 else ""


def comparar(reportado: str | None, registrado: str | None) -> str | None:
    """Compara lo que dice la red contra lo que dice el registro.

    La contención (uno adentro del otro) es a propósito y viene de un caso
    real: la OLT reporta `VSOL12345678` y en el padrón alguien cargó sólo
    `12345678`. Son el mismo equipo. Se exige un largo mínimo para que dos
    seriales cortos no coincidan de casualidad.
    """
    r, g = normalizar_serie(reportado), normalizar_serie(registrado)
    if not r:
        return None                      # la red no informó nada: no hay caso
    if not g:
        return SIN_REGISTRO
    if r == g:
        return OK
    if len(r) >= MIN_LARGO_CONTENCION and len(g) >= MIN_LARGO_CONTENCION \
            and (r in g or g in r):
        return OK
    return DIFIERE


def _dias_desde(texto: str | None, hoy: date | None = None) -> int | None:
    """Días desde una fecha guardada como texto. None si no se entiende.

    La base heredada guarda fechas como texto y sin un formato único: conviven
    'AAAA-MM-DD HH:MM:SS', 'AAAA-MM-DD HH:MM' y 'AAAA-MM-DD' pelada. Se toman
    los primeros 10 caracteres, que es la parte que siempre está.
    """
    if not texto:
        return None
    try:
        d = datetime.strptime(str(texto).strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    # Una fecha futura (reloj desincronizado del poller) es 0 días, no negativa.
    return max(((hoy or date.today()) - d).days, 0)


@dataclass(frozen=True)
class Hallazgo:
    categoria: str
    fuente: str                      # olt | inalambrico | stock | torre
    identificador: str               # serial o MAC, como lo muestra la red
    ubicacion: str
    detalle: str
    severidad: str                   # alta | media | baja
    cliente_id: int | None = None
    cliente_nombre: str | None = None
    cliente_estado: str | None = None
    registrado: str | None = None
    detectado: str | None = None
    dias_sin_ver: int | None = None


@dataclass
class Resumen:
    """El cuadro de situación del registro."""
    vistos_en_la_red: int = 0
    coinciden: int = 0
    hallazgos: list[Hallazgo] = field(default_factory=list)
    esperados_sin_servicio: int = 0   # apagados a propósito: no son hallazgo

    @property
    def por_categoria(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for h in self.hallazgos:
            out[h.categoria] = out.get(h.categoria, 0) + 1
        return out

    @property
    def cobertura(self) -> float | None:
        """Qué porcentaje de lo que la red ve está bien registrado.

        Es el número que contesta "cuán mal está el registro" de una sola
        mirada, y el que debería subir con cada tanda de correcciones.
        """
        if not self.vistos_en_la_red:
            return None
        return round(self.coinciden / self.vistos_en_la_red * 100, 1)


_ORDEN = {FANTASMA: 0, DIFIERE: 1, NO_VISTO: 2, SIN_REGISTRO: 3, HUERFANO: 4}
_ORDEN_SEV = {"alta": 0, "media": 1, "baja": 2}


class ServicioInventario:
    """Sólo lectura: arma la lista para revisar, no corrige nada."""

    def __init__(self, repo: InventarioRepository, hoy: date | None = None) -> None:
        self._r = repo
        self._hoy = hoy or date.today()

    # ── Fibra: la OLT contra el padrón ─────────────────────────────────

    def conciliar_fibra(self, res: Resumen) -> set[str]:
        """Devuelve los seriales vistos, para el cruce posterior con el depósito."""
        onus = self._r.onus_de_la_red()
        vistos = {normalizar_serie(o.serial) for o in onus if o.serial}
        vistos.discard("")
        padron = {normalizar_serie(c.nro_cliente): c
                  for c in self._r.padron("fibra") if c.nro_cliente}
        con_onu: set[int] = set()

        for o in onus:
            if not o.serial:
                continue                       # la OLT no informó serial
            res.vistos_en_la_red += 1
            cli = padron.get(normalizar_serie(o.nro_cliente))
            if cli is None:
                res.hallazgos.append(Hallazgo(
                    categoria=HUERFANO, fuente="olt", identificador=o.serial,
                    ubicacion=o.ubicacion, detectado=o.serial, severidad="media",
                    detalle=f"La OLT ve esta ONU con número de cliente "
                            f"«{o.nro_cliente or 'vacío'}», que no existe en el padrón."))
                continue

            con_onu.add(cli.id)
            veredicto = comparar(o.serial, cli.equipo_serie)
            if veredicto == OK:
                res.coinciden += 1
            elif veredicto == SIN_REGISTRO:
                res.hallazgos.append(Hallazgo(
                    categoria=SIN_REGISTRO, fuente="olt", identificador=o.serial,
                    ubicacion=o.ubicacion, detectado=o.serial, severidad="media",
                    cliente_id=cli.id, cliente_nombre=cli.nombre,
                    cliente_estado=cli.estado,
                    detalle="La ONU está funcionando pero el cliente no tiene "
                            "ningún equipo cargado en la ficha."))
            elif veredicto == DIFIERE:
                res.hallazgos.append(Hallazgo(
                    categoria=DIFIERE, fuente="olt", identificador=o.serial,
                    ubicacion=o.ubicacion, severidad="alta",
                    cliente_id=cli.id, cliente_nombre=cli.nombre,
                    cliente_estado=cli.estado,
                    registrado=cli.equipo_serie, detectado=o.serial,
                    detalle="El cliente tiene instalada una ONU distinta de la que "
                            "figura en la ficha. Probable cambio sin registrar."))

        for cli in padron.values():
            if cli.id in con_onu:
                continue
            if not cli.deberia_estar_online:
                res.esperados_sin_servicio += 1
                continue
            res.hallazgos.append(Hallazgo(
                categoria=NO_VISTO, fuente="olt",
                identificador=cli.equipo_serie or "sin serial",
                ubicacion="Ninguna OLT lo reporta", severidad="media",
                cliente_id=cli.id, cliente_nombre=cli.nombre,
                cliente_estado=cli.estado, registrado=cli.equipo_serie,
                detalle="Cliente de fibra activo del que ninguna OLT tiene ONU "
                        "registrada. O el número de cliente no coincide, o no "
                        "está instalado."))
        return vistos

    # ── Inalámbrico: los AP contra el padrón ───────────────────────────

    def conciliar_inalambrico(self, res: Resumen) -> set[str]:
        """Devuelve las MAC vistas, para el cruce posterior con el depósito."""
        estaciones = self._r.estaciones_de_la_red()
        vistos = {normalizar_mac(e.mac) for e in estaciones}
        vistos.discard("")
        padron = {c.id: c for c in self._r.padron("inalambrico")}
        con_equipo: set[int] = set()

        for e in estaciones:
            mac = normalizar_mac(e.mac)
            if not mac:
                continue
            res.vistos_en_la_red += 1
            cli = padron.get(e.cliente_id) if e.cliente_id else None
            if cli is None:
                res.hallazgos.append(Hallazgo(
                    categoria=HUERFANO, fuente="inalambrico", identificador=e.mac,
                    ubicacion=e.ubicacion, detectado=e.mac, severidad="media",
                    detalle=f"Equipo {e.modelo or 'sin modelo'} asociado al AP y "
                            "conectado, sin cliente asignado en el sistema."))
                continue

            con_equipo.add(cli.id)
            if normalizar_mac(cli.mac_address) == mac:
                res.coinciden += 1
            elif not normalizar_mac(cli.mac_address):
                res.hallazgos.append(Hallazgo(
                    categoria=SIN_REGISTRO, fuente="inalambrico", identificador=e.mac,
                    ubicacion=e.ubicacion, detectado=e.mac, severidad="media",
                    cliente_id=cli.id, cliente_nombre=cli.nombre,
                    cliente_estado=cli.estado,
                    detalle=f"Conectado con un {e.modelo or 'equipo'} sin MAC "
                            "cargada en la ficha del cliente."))
            else:
                res.hallazgos.append(Hallazgo(
                    categoria=DIFIERE, fuente="inalambrico", identificador=e.mac,
                    ubicacion=e.ubicacion, severidad="alta",
                    cliente_id=cli.id, cliente_nombre=cli.nombre,
                    cliente_estado=cli.estado,
                    registrado=cli.mac_address, detectado=e.mac,
                    detalle="La MAC conectada no es la que figura en la ficha. "
                            "Probable cambio de equipo sin registrar."))

        for cli in padron.values():
            if cli.id in con_equipo:
                continue
            if not cli.deberia_estar_online:
                res.esperados_sin_servicio += 1
                continue
            res.hallazgos.append(Hallazgo(
                categoria=NO_VISTO, fuente="inalambrico",
                identificador=cli.mac_address or "sin MAC",
                ubicacion="Ningún AP lo reporta", severidad="baja",
                cliente_id=cli.id, cliente_nombre=cli.nombre,
                cliente_estado=cli.estado, registrado=cli.mac_address,
                detalle="Cliente inalámbrico activo que ningún AP ve asociado. "
                        "Puede estar caído ahora mismo."))
        return vistos

    # ── Torres: qué contestó y hace cuánto ─────────────────────────────

    def conciliar_torres(self, res: Resumen) -> set[str]:
        """Devuelve los identificadores vistos, para el cruce con el depósito."""
        vistos: set[str] = set()
        for eq in self._r.equipos_de_torre():
            dias = _dias_desde(eq.ultimo_snmp, self._hoy)
            respondio = dias is not None and dias <= DIAS_PARA_DUDAR
            if respondio:
                res.vistos_en_la_red += 1
                res.coinciden += 1
                for ident in (normalizar_serie(eq.serie), normalizar_mac(eq.mac)):
                    if ident:
                        vistos.add(ident)
                continue
            if (eq.estado or "").lower() in ("de_baja", "repuesto"):
                continue                       # ya se sabe que no está en servicio
            if eq.ultimo_snmp is None:
                continue                       # nunca se sondeó: no es un faltante
            res.hallazgos.append(Hallazgo(
                categoria=NO_VISTO, fuente="torre",
                identificador=eq.serie or eq.mac or f"equipo #{eq.id}",
                ubicacion=eq.ubicacion, severidad="alta" if (dias or 0) >= DIAS_PARA_ALARMA else "media",
                registrado=eq.serie or eq.mac, dias_sin_ver=dias,
                detalle=f"{eq.tipo or 'Equipo'} {eq.fabricante or ''} {eq.modelo or ''}".strip()
                        + f" sin responder por SNMP hace {dias} días."))
        return vistos

    # ── Depósito: lo que el papel dice contra lo que la red ve ─────────

    def conciliar_stock(self, res: Resumen, vistos_en_red: set[str]) -> None:
        for it in self._r.items_de_stock():
            ids = {x for x in (normalizar_serie(it.serie), normalizar_mac(it.mac)) if x}
            if not ids:
                continue                       # sin serie ni MAC no hay nada que cruzar
            esta_en_la_red = bool(ids & vistos_en_red)
            descripcion = " ".join(x for x in (it.marca, it.modelo) if x) or it.tipo or "Equipo"

            if it.figura_instalado and not esta_en_la_red:
                res.hallazgos.append(Hallazgo(
                    categoria=NO_VISTO, fuente="stock",
                    identificador=it.serie or it.mac or f"item #{it.id}",
                    ubicacion=it.ubicacion or "—", severidad="alta",
                    cliente_id=it.cliente_id, cliente_nombre=it.cliente_nombre,
                    registrado=it.serie or it.mac,
                    detalle=f"{descripcion} figura instalado pero la red no lo ve "
                            "en ningún lado. Candidato a faltante."))
            elif not it.figura_instalado and esta_en_la_red:
                res.hallazgos.append(Hallazgo(
                    categoria=FANTASMA, fuente="stock",
                    identificador=it.serie or it.mac or f"item #{it.id}",
                    ubicacion=it.ubicacion or "Depósito", severidad="alta",
                    registrado=it.estado, detectado="funcionando en la red",
                    detalle=f"{descripcion} figura en «{it.estado or 'depósito'}» pero "
                            "está funcionando en la red. Salió sin registrarse."))

    # ── Todo junto ─────────────────────────────────────────────────────

    def analizar(self) -> Resumen:
        res = Resumen()
        # Cada conciliación devuelve lo que vio; el depósito se cruza contra la
        # unión de todo. Así la base se lee una sola vez por fuente.
        vistos = self.conciliar_fibra(res)
        vistos |= self.conciliar_inalambrico(res)
        vistos |= self.conciliar_torres(res)
        self.conciliar_stock(res, vistos)

        res.hallazgos.sort(key=lambda h: (
            _ORDEN_SEV.get(h.severidad, 9),
            _ORDEN.get(h.categoria, 9),
            -(h.dias_sin_ver or 0),
            h.cliente_nombre or h.ubicacion or "",
        ))
        return res
