"""Del plan que el cliente tiene contratado al perfil de tráfico de la OLT.

Son dos vocabularios distintos para la misma cosa. El sistema comercial dice
``INTERNET 10 MB``; la OLT tiene un perfil que se llama ``10M-Dom-Dow``. Nadie
los conectó nunca salvo la cabeza del operador, y esa traducción a mano fue
exactamente lo que dejó una ONU a medio configurar.

La traducción se hace por **megabits, segmento y sentido**, y el resultado se
busca en los perfiles que la OLT declaró. Eso es lo importante: acá no se
construye ningún nombre, se elige uno de los que el equipo dijo tener. Por eso
da igual que se llamen ``10M-Dom-Dow``, ``100M-Dom-DOW`` o ``100M-Pymes-Dowm``:
la inconsistencia la resuelve el equipo, no una convención inventada.

Si no hay un perfil que corresponda, se dice que no lo hay. Proponer el más
parecido sería reintroducir el problema original con otra cara.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..core.models import Cliente, PerfilTrafico

#: ``100M-Pymes-Dowm`` → 100 / ``Pymes`` / ``Dowm``. El sentido se interpreta
#: después: el equipo escribe ``DOW``, ``DOWN``, ``Dow``, ``Dowm`` y ``UP``.
NOMBRE_PERFIL = re.compile(
    r"^(?P<megas>\d{1,4})\s*M-(?P<segmento>[A-Za-z]+)-(?P<sentido>[A-Za-z]+)$"
)

#: Planes de empresa. Todo lo demás es residencial, que es la enorme mayoría.
SENAL_EMPRESA = re.compile(r"\b(?:PYMES?|EMPRESA|CORPORATIVO|DEDICADO)\b", re.IGNORECASE)

SEGMENTO_HOGAR, SEGMENTO_EMPRESA = "dom", "pymes"


@dataclass(frozen=True, slots=True)
class ParPlanes:
    """El par de perfiles que hay que aplicarle a una ONU."""

    subida: str = ""
    bajada: str = ""
    #: Qué se usó para elegirlos, en palabras. Va a la pantalla: el operador
    #: tiene que poder ver el razonamiento antes de aceptarlo.
    motivo: str = ""

    @property
    def completo(self) -> bool:
        return bool(self.subida and self.bajada)


def segmento_de(cliente: Cliente) -> str:
    """Hogar o empresa, según cómo esté nombrado el plan contratado."""
    if SENAL_EMPRESA.search(f"{cliente.plan} {cliente.tipo_servicio}"):
        return SEGMENTO_EMPRESA
    return SEGMENTO_HOGAR


def elegir_planes(
    perfiles: tuple[PerfilTrafico, ...],
    *,
    megabits: int | None,
    segmento: str = SEGMENTO_HOGAR,
) -> ParPlanes:
    """Elige el par de perfiles de ``megabits`` en ese segmento.

    Devuelve un par vacío —con el motivo— cuando no hay con qué elegir o
    cuando la OLT no tiene ese plan definido. Un par a medias también se
    descarta: aplicar sólo la bajada dejaría al cliente con la subida del
    perfil DBA y nadie se enteraría hasta que se queje.
    """
    if megabits is None:
        return ParPlanes(motivo="el sistema comercial no dice de cuántos megas es el plan")
    if not perfiles:
        return ParPlanes(motivo="esta OLT todavía no tiene perfiles de tráfico inventariados")

    subida, bajada = "", ""
    for perfil in perfiles:
        partes = NOMBRE_PERFIL.match(perfil.nombre.strip())
        if partes is None:
            continue
        if int(partes.group("megas")) != megabits:
            continue
        if partes.group("segmento").lower() != segmento.lower():
            continue
        sentido = partes.group("sentido").lower()
        if sentido.startswith("up"):
            subida = subida or perfil.nombre
        elif sentido.startswith("dow"):
            bajada = bajada or perfil.nombre

    etiqueta = "hogar" if segmento.lower() == SEGMENTO_HOGAR else "empresa"
    if subida and bajada:
        return ParPlanes(subida=subida, bajada=bajada, motivo=f"{megabits} MB, {etiqueta}")
    if not subida and not bajada:
        return ParPlanes(motivo=f"la OLT no tiene un plan de {megabits} MB para {etiqueta}")
    falta = "de subida" if not subida else "de bajada"
    return ParPlanes(
        motivo=(
            f"la OLT tiene el plan {falta.replace('de ', '')} de {megabits} MB para "
            f"{etiqueta} pero le falta el otro; hay que elegirlos a mano"
        )
    )


__all__ = ["SEGMENTO_EMPRESA", "SEGMENTO_HOGAR", "ParPlanes", "elegir_planes", "segmento_de"]
