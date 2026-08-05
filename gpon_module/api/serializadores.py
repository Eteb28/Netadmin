"""Conversión de los modelos del dominio a JSON.

Vive acá y no en los modelos a propósito: las entidades del núcleo no deben
saber que existe una API. Si mañana hay que exponer los mismos datos en otro
formato, se agrega otro serializador y el dominio no se toca.

Dos criterios que se sostienen en toda la capa:

* **``None`` viaja como ``null``, nunca como 0.** Un dato que el equipo no
  expone tiene que llegar a la interfaz como ausencia, para que se muestre "—"
  y no un cero que parece una medición.
* **Ningún secreto sale por la API.** Las credenciales de OLT no se serializan.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..core.models import (
    OLT,
    ONU,
    Alarma,
    Evento,
    InfoSistema,
    LecturaOptica,
    ONUNoAutorizada,
    Operacion,
    Perfiles,
    PuertoPON,
    Sincronizacion,
)
from ..core.optica import clasificar
from ..services.descubrimiento import ResultadoDescubrimiento


def _fecha(momento: datetime | None) -> str | None:
    return momento.isoformat() if momento else None


def olt(entidad: OLT) -> dict[str, Any]:
    return {
        "id": entidad.id,
        "nombre": entidad.nombre,
        "host": entidad.host,
        "fabricante": str(entidad.fabricante),
        "modelo": entidad.modelo,
        "firmware": entidad.firmware,
        "numero_serie": entidad.numero_serie,
        "mac": entidad.mac,
        "descripcion": entidad.descripcion,
        "estado": str(entidad.estado),
        "activa": entidad.activa,
        "cantidad_pon": entidad.cantidad_pon,
        "cantidad_onus": entidad.cantidad_onus,
        "uptime_segundos": entidad.uptime_segundos,
        "ultima_sincronizacion": _fecha(entidad.ultima_sincronizacion),
    }


def puerto_pon(entidad: PuertoPON) -> dict[str, Any]:
    return {
        "id": entidad.id,
        "olt_id": entidad.olt_id,
        "indice": entidad.indice,
        "nombre": entidad.nombre,
        "habilitado": entidad.habilitado,
        "operativo": entidad.operativo,
        "cantidad_onus": entidad.cantidad_onus,
        "cantidad_onus_en_linea": entidad.cantidad_onus_en_linea,
        "temperatura_celsius": entidad.temperatura_celsius,
        "voltaje_voltios": entidad.voltaje_voltios,
        "potencia_tx_dbm": entidad.potencia_tx_dbm,
        "leido_en": _fecha(entidad.leido_en),
    }


def onu(entidad: ONU) -> dict[str, Any]:
    return {
        "id": entidad.id,
        "olt_id": entidad.olt_id,
        "ref": str(entidad.ref),
        "pon": entidad.ref.pon,
        "onu_id": entidad.ref.onu_id,
        "numero_serie": entidad.numero_serie,
        "nombre": entidad.nombre,
        "modelo": entidad.modelo,
        "firmware": entidad.firmware,
        "estado": str(entidad.estado),
        "motivo_caida": str(entidad.motivo_caida),
        "modo_servicio": str(entidad.modo_servicio),
        "autorizada": entidad.autorizada,
        "distancia_metros": entidad.distancia_metros,
        "vlan": entidad.vlan,
        "perfil_linea": entidad.perfil_linea,
        "perfil_servicio": entidad.perfil_servicio,
        "ultima_subida": _fecha(entidad.ultima_subida),
        "ultima_bajada": _fecha(entidad.ultima_bajada),
        "tiempo_en_estado": entidad.tiempo_en_estado,
        "primera_vez_vista": _fecha(entidad.primera_vez_vista),
        "ultima_vez_vista": _fecha(entidad.ultima_vez_vista),
    }


def onu_no_autorizada(entidad: ONUNoAutorizada) -> dict[str, Any]:
    return {
        "numero_serie": entidad.numero_serie,
        "pon": entidad.pon,
        "modelo": entidad.modelo,
        "fabricante_onu": entidad.fabricante_onu,
        "detectada_en": _fecha(entidad.detectada_en),
    }


def lectura_optica(entidad: LecturaOptica) -> dict[str, Any]:
    return {
        "ref": str(entidad.ref),
        "pon": entidad.ref.pon,
        "onu_id": entidad.ref.onu_id,
        "rx_onu_dbm": entidad.rx_onu_dbm,
        "tx_onu_dbm": entidad.tx_onu_dbm,
        "rx_olt_dbm": entidad.rx_olt_dbm,
        "tx_olt_dbm": entidad.tx_olt_dbm,
        "perdida_optica_db": entidad.perdida_optica_db,
        "temperatura_celsius": entidad.temperatura_celsius,
        "voltaje_voltios": entidad.voltaje_voltios,
        "distancia_metros": entidad.distancia_metros,
        # La clasificación viaja calculada: la regla de qué es "saturada" o
        # "crítica" pertenece al dominio, no al navegador.
        "clasificacion": str(clasificar(entidad.rx_onu_dbm)),
        "leido_en": _fecha(entidad.leido_en),
    }


def info_sistema(entidad: InfoSistema) -> dict[str, Any]:
    return {
        "modelo": entidad.modelo,
        "fabricante": str(entidad.fabricante),
        "firmware": entidad.firmware,
        "numero_serie": entidad.numero_serie,
        "mac": entidad.mac,
        "nombre_equipo": entidad.nombre_equipo,
        "uptime_segundos": entidad.uptime_segundos,
        "cpu_porcentaje": entidad.cpu_porcentaje,
        "memoria_porcentaje": entidad.memoria_porcentaje,
        "temperatura_celsius": entidad.temperatura_celsius,
        "leido_en": _fecha(entidad.leido_en),
    }


def evento(entidad: Evento) -> dict[str, Any]:
    return {
        "id": entidad.id,
        "tipo": str(entidad.tipo),
        "olt_id": entidad.olt_id,
        "entidad": entidad.entidad,
        "entidad_id": entidad.entidad_id,
        "ref": str(entidad.ref_onu) if entidad.ref_onu else None,
        "descripcion": entidad.descripcion,
        "valor_anterior": entidad.valor_anterior,
        "valor_nuevo": entidad.valor_nuevo,
        "ocurrido_en": _fecha(entidad.ocurrido_en),
    }


def operacion(entidad: Operacion) -> dict[str, Any]:
    return {
        "id": entidad.id,
        "tipo": str(entidad.tipo),
        "olt_id": entidad.olt_id,
        "ref": str(entidad.ref_onu) if entidad.ref_onu else None,
        "usuario": entidad.usuario,
        "ok": entidad.ok,
        "simulado": entidad.simulado,
        "comandos": list(entidad.comandos),
        "salida": entidad.salida,
        "error": entidad.error,
        "duracion_ms": entidad.duracion_ms,
        "ejecutada_en": _fecha(entidad.ejecutada_en),
    }


def alarma(entidad: Alarma) -> dict[str, Any]:
    return {
        "id": entidad.id,
        "tipo": str(entidad.tipo),
        "severidad": str(entidad.severidad),
        "estado": str(entidad.estado),
        "olt_id": entidad.olt_id,
        "entidad": entidad.entidad,
        "entidad_id": entidad.entidad_id,
        "mensaje": entidad.mensaje,
        "valor": entidad.valor,
        "abierta_en": _fecha(entidad.abierta_en),
        "reconocida_en": _fecha(entidad.reconocida_en),
        "reconocida_por": entidad.reconocida_por,
        "resuelta_en": _fecha(entidad.resuelta_en),
    }


def sincronizacion(entidad: Sincronizacion) -> dict[str, Any]:
    return {
        "id": entidad.id,
        "olt_id": entidad.olt_id,
        "nivel": str(entidad.nivel),
        "resultado": str(entidad.resultado),
        "onus_leidas": entidad.onus_leidas,
        "onus_esperadas": entidad.onus_esperadas,
        "eventos_generados": entidad.eventos_generados,
        "detalle": entidad.detalle,
        "iniciada_en": _fecha(entidad.iniciada_en),
        "finalizada_en": _fecha(entidad.finalizada_en),
        "duracion_ms": entidad.duracion_ms,
    }


def perfiles(entidad: Perfiles) -> dict[str, Any]:
    return {
        "dba": [
            {
                "nombre": p.nombre,
                "identificador_equipo": p.identificador_equipo,
                "tipo": p.tipo,
                "ancho_banda_maximo_kbps": p.ancho_banda_maximo_kbps,
                "ancho_banda_asegurado_kbps": p.ancho_banda_asegurado_kbps,
            }
            for p in entidad.dba
        ],
        "linea": [
            {
                "nombre": p.nombre,
                "perfil_dba": p.perfil_dba,
                "cantidad_tcont": p.cantidad_tcont,
                "cantidad_gemport": p.cantidad_gemport,
            }
            for p in entidad.linea
        ],
        "servicio": [{"nombre": p.nombre, "vlan": p.vlan} for p in entidad.servicio],
        "vlans": [{"vlan_id": v.vlan_id, "nombre": v.nombre} for v in entidad.vlans],
        "service_ports": [
            {
                "indice": s.indice,
                "ref": str(s.ref_onu) if s.ref_onu else None,
                "gemport": s.gemport,
                "vlan_usuario": s.vlan_usuario,
                "vlan_servicio": s.vlan_servicio,
            }
            for s in entidad.service_ports
        ],
    }


def resultado_descubrimiento(entidad: ResultadoDescubrimiento) -> dict[str, Any]:
    return {
        "olt": olt(entidad.olt),
        "resultado": str(entidad.resultado),
        "completo": entidad.completo,
        "onus_leidas": entidad.onus_leidas,
        "onus_nuevas": entidad.onus_nuevas,
        "onus_esperadas": entidad.onus_esperadas,
        "puertos": len(entidad.puertos),
        "no_autorizadas": [onu_no_autorizada(n) for n in entidad.no_autorizadas],
        "advertencias": list(entidad.advertencias),
        "duracion_ms": entidad.duracion_ms,
    }
