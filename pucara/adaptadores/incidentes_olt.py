"""Puente entre `olt_poller.py` y el motor de incidentes (fase 4).

El poller sigue siendo un script con sqlite3 crudo: migrarlo entero es parte de
la fase 7. Mientras tanto le alcanza con llamar a `procesar_sondeo_olt()` con
una lista de diccionarios simples. Toda la lógica —correlación, causa probable,
no duplicar, cierre por estabilidad— vive en el servicio, no acá.

Este módulo es deliberadamente delgado: si crece, algo se está escribiendo en el
lugar equivocado.
"""
from __future__ import annotations

from collections.abc import Iterable

from pucara.db import sesion
from pucara.services import factory
from pucara.services.incidentes import LecturaOnu


def referencia_onu(olt_id: int, pon: int, onu: int) -> str:
    """Identificador estable de una ONU.

    Es la clave con la que el motor reconoce que "esto ya lo tengo abierto".
    Se arma con la posición física (OLT/PON/ONU) y no con el número de cliente:
    si mañana se reasigna el puerto a otro abonado, el incidente que sigue
    abierto es el del puerto, que es lo que está fallando.
    """
    return f"olt:{olt_id}/pon:{pon}/onu:{onu}"


def _a_lectura(d: dict) -> LecturaOnu | None:
    try:
        olt_id, pon, onu = int(d["olt_id"]), int(d["pon"]), int(d["onu"])
    except (KeyError, TypeError, ValueError):
        return None
    return LecturaOnu(
        referencia=referencia_onu(olt_id, pon, onu),
        olt_id=olt_id,
        pon=pon,
        online=bool(d.get("online")),
        cliente_id=d.get("cliente_id"),
        nro_cliente=d.get("nro_cliente"),
        # El motivo ('Power Off' / 'Onu Los') permite distinguir un corte de luz
        # de un corte de fibra. Todavía no se lee por SNMP: hace falta confirmar
        # el OID de causa de baja en la rama VSOL contra un walk del equipo. Sin
        # él, el motor deja la causa en DESCONOCIDA y todo lo demás funciona.
        motivo_caida=d.get("motivo_caida"),
    )


def procesar_sondeo_olt(
    lecturas: Iterable[dict], lectura_completa: bool = True
) -> dict:
    """Procesa un ciclo del poller. Devuelve el resumen del motor.

    `lectura_completa=False` cuando el walk óptico vino truncado: el motor no
    abre incidentes con datos parciales, sólo procesa recuperaciones.
    """
    convertidas = [x for x in (_a_lectura(d) for d in lecturas) if x is not None]
    if not convertidas and lectura_completa:
        # Sin lecturas no hay nada que concluir; igual conviene cerrar lo que
        # ya venía estable de ciclos anteriores.
        with sesion() as s:
            return {"nuevos": 0, "recuperados": 0, "masivos": 0,
                    "cerrados": factory.motor_incidentes(s).cerrar_estables(),
                    "omitido_por_lectura_parcial": False}

    with sesion() as s:
        return factory.motor_incidentes(s).procesar_sondeo(convertidas, lectura_completa)
