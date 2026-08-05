"""Traducción de los valores crudos de VSOL a los modelos del dominio.

Dos criterios rigen todo este archivo:

1. **Ante la duda, ``None``.** Un valor que no se entiende no se convierte en
   cero: un cero se grafica, se promedia y termina en una decisión operativa
   equivocada. ``None`` dice la verdad — "no sé" — y el histórico registra la
   ausencia.
2. **Un código desconocido no se adivina.** Se mapea a ``DESCONOCIDO`` y se
   registra en el log, para que aparezca al revisar y no se entierre.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime

from ...core.enums import EstadoONU, MotivoCaida

log = logging.getLogger(__name__)

# --- Estado de la ONU -----------------------------------------------------
#
# Valores observados en el parque real: 3 (386 ONU), 4 y 6. El 3 es "en línea";
# se confirmó contra la interfaz web del equipo.

_ESTADOS: dict[int, EstadoONU] = {
    1: EstadoONU.FUERA_DE_LINEA,
    2: EstadoONU.FUERA_DE_LINEA,
    3: EstadoONU.EN_LINEA,
    4: EstadoONU.FUERA_DE_LINEA,
    5: EstadoONU.FUERA_DE_LINEA,
    6: EstadoONU.FUERA_DE_LINEA,
}

_codigos_desconocidos: set[str] = set()


def parsear_estado(crudo: str | None) -> EstadoONU:
    if crudo is None or crudo == "":
        return EstadoONU.DESCONOCIDO
    texto = crudo.strip()
    if texto.isdigit():
        estado = _ESTADOS.get(int(texto))
        if estado is not None:
            return estado
    if texto not in _codigos_desconocidos:
        _codigos_desconocidos.add(texto)
        log.warning(
            "Código de estado de ONU no reconocido: %r. Se registra como DESCONOCIDO; "
            "revisar si el firmware cambió.",
            texto,
        )
    return EstadoONU.DESCONOCIDO


# --- Motivo de caída ------------------------------------------------------
#
# Valores medidos: "Power Off" (225 ONU), "Onu Los" (174) y "N/A" (74).
# La distinción es operativamente decisiva y hoy Pucará no la usa.

_MOTIVOS: dict[str, MotivoCaida] = {
    "power off": MotivoCaida.APAGADO,
    "poweroff": MotivoCaida.APAGADO,
    "dying gasp": MotivoCaida.APAGADO,
    "dyinggasp": MotivoCaida.APAGADO,
    "onu los": MotivoCaida.PERDIDA_SENAL,
    "los": MotivoCaida.PERDIDA_SENAL,
    "lossofsignal": MotivoCaida.PERDIDA_SENAL,
    "deactive": MotivoCaida.DESACTIVADA_ADMIN,
    "deactivated": MotivoCaida.DESACTIVADA_ADMIN,
    "admin": MotivoCaida.DESACTIVADA_ADMIN,
    "n/a": MotivoCaida.NINGUNO,
    "na": MotivoCaida.NINGUNO,
    "none": MotivoCaida.NINGUNO,
    "normal": MotivoCaida.NINGUNO,
}


def parsear_motivo(crudo: str | None) -> MotivoCaida:
    if crudo is None or crudo.strip() == "":
        return MotivoCaida.DESCONOCIDO
    clave = crudo.strip().lower()
    motivo = _MOTIVOS.get(clave)
    if motivo is not None:
        return motivo
    for parcial, valor in _MOTIVOS.items():
        if parcial in clave:
            return valor
    if clave not in _codigos_desconocidos:
        _codigos_desconocidos.add(clave)
        log.warning("Motivo de caída no reconocido: %r. Se registra como DESCONOCIDO.", crudo)
    return MotivoCaida.DESCONOCIDO


# --- Magnitudes analógicas ------------------------------------------------
#
# [VERIFICADO contra una V1600G1, firmware V2.3.1R]: este equipo publica las
# magnitudes **con la unidad puesta y ya convertida** — "-25.378(dBm)",
# "34.801(C)", "3.44(V)". No hay ninguna escala que aplicar, y por eso cuando
# la unidad viene explícita el parser usa el número tal cual.
#
# La inferencia por orden de magnitud queda igual como respaldo, para firmwares
# que publiquen enteros sin unidad. Se apoya en el lote completo y no en el
# valor suelto: "-157" puede ser −15,7 o −1,57 dBm, y con una sola lectura no
# hay forma de decidir.

_NUMERO = re.compile(r"-?\d+(?:\.\d+)?")


def _numero(crudo: str | None) -> float | None:
    if crudo is None:
        return None
    coincidencia = _NUMERO.search(crudo.strip())
    if coincidencia is None:
        return None
    try:
        return float(coincidencia.group())
    except ValueError:  # pragma: no cover - la regex ya garantiza el formato
        return None


#: Rango físicamente posible en GPON.
RANGO_FISICO_DBM = (-40.0, 10.0)

#: Rango donde cae la enorme mayoría de las ONU de un parque sano. Se usa sólo
#: para *inferir la escala*, nunca para descartar una lectura: una ONU saturada
#: a −1,57 dBm es justamente la que hay que ver.
RANGO_TIPICO_DBM = (-32.0, -5.0)

#: Escalas con las que los equipos suelen publicar dBm.
ESCALAS_POSIBLES = (1, 10, 100, 1000)

#: Valores centinela que significan "sin medición", no "cero dBm".
CENTINELAS = (0, 65535, -65535, 2147483647, -2147483648)


#: Unidades que el equipo agrega al valor. Cuando están, no hay nada que
#: inferir: la V1600G1 con firmware V2.3.1R publica "-25.378(dBm)" y "34.801(C)",
#: es decir, el número ya viene en la unidad final.
_UNIDADES_EXPLICITAS = ("dbm", "(c)", "(v)", "celsius")


def trae_unidad(crudo: str | None) -> bool:
    """¿El equipo publicó la unidad junto al número?"""
    if not crudo:
        return False
    minuscula = crudo.lower()
    return any(unidad in minuscula for unidad in _UNIDADES_EXPLICITAS)


def inferir_escala_dbm(valores) -> int:
    """Deduce el divisor con el que el equipo publica las potencias.

    Un valor suelto es ambiguo: ``-157`` puede ser −15,7 dBm o −1,57 dBm, y las
    dos son potencias posibles. Un **lote** de lecturas no lo es: con 473 ONU,
    la escala correcta es la que ubica a la mayoría en el rango donde vive un
    parque real. Por eso la escala se infiere una vez sobre el conjunto y se
    aplica pareja, en vez de adivinarla valor por valor.
    """
    valores = list(valores)
    # Si el equipo publica la unidad, el número ya está en dBm: dividirlo sería
    # inventar una escala donde no la hay.
    if any(trae_unidad(v) for v in valores):
        return 1

    numeros = [n for n in (_numero(v) for v in valores) if n is not None and n not in CENTINELAS]
    if not numeros:
        return 100
    minimo, maximo = RANGO_TIPICO_DBM
    mejor, mejor_puntaje = 100, -1
    for divisor in ESCALAS_POSIBLES:
        puntaje = sum(1 for n in numeros if minimo <= n / divisor <= maximo)
        if puntaje > mejor_puntaje:
            mejor, mejor_puntaje = divisor, puntaje
    return mejor


def parsear_dbm(crudo: str | None, escala: int | None = None) -> float | None:
    """Potencia óptica en dBm.

    Con ``escala`` conocida (la que devuelve ``inferir_escala_dbm``) la
    conversión es exacta. Sin ella cae en una heurística por orden de magnitud,
    que alcanza para un valor suelto pero **es ambigua**: para leer un parque
    entero, inferir la escala del lote y pasarla acá.
    """
    valor = _numero(crudo)
    if valor is None or valor in CENTINELAS:
        return None
    minimo, maximo = RANGO_FISICO_DBM
    if trae_unidad(crudo):
        # El equipo ya dijo la unidad: se respeta y no se aplica ninguna escala.
        return round(valor, 2) if minimo <= valor <= maximo else None
    if escala:
        candidato = valor / escala
        return round(candidato, 2) if minimo <= candidato <= maximo else None
    for divisor in ESCALAS_POSIBLES:
        candidato = valor / divisor
        if minimo <= candidato <= maximo:
            return round(candidato, 2)
    return None


def parsear_temperatura(crudo: str | None) -> float | None:
    """Temperatura en grados Celsius. Rango admitido: −20 a 120."""
    valor = _numero(crudo)
    if valor is None:
        return None
    if trae_unidad(crudo):
        return round(valor, 1) if -20.0 <= valor <= 120.0 else None
    for divisor in (1, 10, 100, 256):
        candidato = valor / divisor
        if -20.0 <= candidato <= 120.0:
            return round(candidato, 1)
    return None


def parsear_voltaje(crudo: str | None) -> float | None:
    """Voltaje de alimentación en voltios. Rango admitido: 0 a 6."""
    valor = _numero(crudo)
    if valor is None:
        return None
    if trae_unidad(crudo):
        return round(valor, 2) if 0.5 <= valor <= 6.0 else None
    for divisor in (1, 10, 100, 1000, 10000):
        candidato = valor / divisor
        if 0.5 <= candidato <= 6.0:
            return round(candidato, 2)
    return None


def parsear_distancia(crudo: str | None) -> int | None:
    """Distancia en metros. GPON llega a 20 km; más que eso no es una distancia."""
    valor = _numero(crudo)
    if valor is None or valor < 0:
        return None
    if valor > 60_000:
        return None
    return int(valor)


# --- Tiempo ---------------------------------------------------------------


def parsear_uptime(crudo: str | None) -> int | None:
    """Convierte el sysUpTime a segundos.

    Acepta las dos formas en que puede llegar: centésimas de segundo, o el
    texto ``"(123456) 0:20:34.56"`` que devuelven algunas herramientas.
    """
    if crudo is None:
        return None
    texto = crudo.strip()
    entre_parentesis = re.search(r"\((\d+)\)", texto)
    if entre_parentesis:
        return int(entre_parentesis.group(1)) // 100
    if texto.isdigit():
        return int(texto) // 100
    partes = re.match(r"(?:(\d+)\s+days?,\s*)?(\d+):(\d+):(\d+)", texto)
    if partes:
        dias = int(partes.group(1) or 0)
        return dias * 86400 + int(partes.group(2)) * 3600 + int(partes.group(3)) * 60 + int(
            partes.group(4)
        )
    return None


def parsear_fecha(crudo: str | None) -> datetime | None:
    """Interpreta las marcas de tiempo que devuelve el equipo.

    Devuelve ``None`` si no se entiende, en vez de la fecha actual: una fecha
    inventada en el histórico es peor que una fecha ausente.
    """
    if crudo is None or crudo.strip() in ("", "0", "N/A", "-"):
        return None
    texto = crudo.strip()
    for formato in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%d/%m/%Y %H:%M:%S"):
        try:
            return datetime.strptime(texto, formato).replace(tzinfo=UTC)
        except ValueError:
            continue
    if texto.isdigit() and len(texto) >= 9:  # epoch en segundos
        try:
            return datetime.fromtimestamp(int(texto), tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    return None


# --- Nombres de interfaz --------------------------------------------------

#: Formas conocidas de nombrar una ONU en ifDescr. Es tolerante a propósito:
#: cambia entre versiones de firmware, y no vale la pena romper el inventario
#: por un separador distinto.
_PATRON_ONU = re.compile(r"(?:gpon|pon)\s*0?[/_]?(\d+)[:.](\d+)", re.IGNORECASE)
_PATRON_PON = re.compile(r"^(?:gpon|pon)\s*0?[/_](\d+)$", re.IGNORECASE)


def ref_desde_descripcion(descripcion: str) -> tuple[int, int] | None:
    """Extrae ``(pon, onu)`` del nombre de una interfaz, si lo tiene."""
    coincidencia = _PATRON_ONU.search(descripcion)
    if coincidencia is None:
        return None
    return int(coincidencia.group(1)), int(coincidencia.group(2))


def pon_desde_descripcion(descripcion: str) -> int | None:
    """Extrae el número de puerto PON del nombre de una interfaz."""
    coincidencia = _PATRON_PON.match(descripcion.strip())
    return int(coincidencia.group(1)) if coincidencia else None
