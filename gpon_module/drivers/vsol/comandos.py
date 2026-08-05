"""Comandos CLI de las VSOL V1600G1 / V1600G1-B.

**Nada de lo que hay acá es una suposición aplicada al equipo.** Es una lista
de *candidatos* de sólo lectura para que ``gpon capturar`` averigüe, contra la
OLT real, cuáles existen en ese firmware y qué forma tiene su salida. Los que
el equipo rechace quedan registrados como rechazados y se descartan.

Por qué este rodeo en vez de escribir los comandos directamente: la sintaxis de
estos equipos cambia entre versiones de firmware, y los manuales que circulan
son de otras. Un comando de lectura mal escrito devuelve un error y no pasa
nada; un comando de escritura mal escrito deja clientes sin servicio. Por eso
la lectura se descubre y la escritura se implementa recién con la salida real
en la mano.

Los comandos de escritura (autorizar, borrar, reiniciar) llegan en la Fase 5 y
van en un módulo aparte, para que nadie pueda confundir una lista con la otra.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ComandoCandidato:
    """Un comando a probar, con el motivo por el que interesa."""

    comando: str
    proposito: str
    grupo: str = "general"


#: Prefijos con los que se pide la ayuda en línea (``?``). Es lo más valioso de
#: toda la captura: el equipo enumera su propia sintaxis, sin ejecutar nada.
AYUDAS_VSOL: tuple[str, ...] = (
    "",  # árbol completo del modo privilegiado
    "show ",
    "show gpon ",
    "show onu ",
    "show ont ",
    "display ",
    "configure ",
)

CATALOGO_VSOL: tuple[ComandoCandidato, ...] = (
    # --- identidad del equipo -------------------------------------------
    ComandoCandidato("show version", "Modelo y versión de firmware exactos", "identidad"),
    ComandoCandidato("show system", "Datos generales del chasis", "identidad"),
    ComandoCandidato("show system-info", "Variante del anterior", "identidad"),
    ComandoCandidato("show device", "Variante del anterior", "identidad"),
    # --- puertos PON ------------------------------------------------------
    ComandoCandidato("show interface gpon", "Lista de puertos PON", "puertos"),
    ComandoCandidato("show gpon interface", "Variante del anterior", "puertos"),
    ComandoCandidato("show pon", "Variante corta", "puertos"),
    ComandoCandidato("show interface brief", "Resumen de interfaces", "puertos"),
    # --- ONU autorizadas --------------------------------------------------
    # El serial NO viaja por SNMP en estos equipos: es la razón principal de
    # existir del transporte CLI. Sin serial no se puede autorizar nada.
    ComandoCandidato("show onu", "Inventario de ONU con su serial", "inventario"),
    ComandoCandidato("show onu all", "Inventario completo", "inventario"),
    ComandoCandidato("show onu info", "Detalle por ONU", "inventario"),
    ComandoCandidato("show ont info", "Variante estilo Huawei", "inventario"),
    ComandoCandidato("show gpon onu", "Variante con prefijo gpon", "inventario"),
    ComandoCandidato("show gpon onu state", "Estado de cada ONU", "inventario"),
    ComandoCandidato("show onu state", "Variante del anterior", "inventario"),
    ComandoCandidato("show onu optical-info", "Potencias por ONU", "inventario"),
    ComandoCandidato("show onu distance", "Distancia de cada ONU", "inventario"),
    # --- ONU sin autorizar ------------------------------------------------
    # Esto es lo que hoy no se puede ver de ninguna forma, y es el paso previo
    # obligatorio a dar de alta un cliente nuevo.
    ComandoCandidato("show onu unauthorized", "ONU detectadas sin autorizar", "no-autorizadas"),
    ComandoCandidato("show onu unauth", "Variante corta", "no-autorizadas"),
    ComandoCandidato("show gpon onu unauthorized", "Variante con prefijo", "no-autorizadas"),
    ComandoCandidato("show onu autofind", "Variante estilo Huawei", "no-autorizadas"),
    ComandoCandidato("show ont autofind all", "Variante estilo Huawei", "no-autorizadas"),
    ComandoCandidato("show onu discovery", "Variante", "no-autorizadas"),
    # --- perfiles y servicio ---------------------------------------------
    ComandoCandidato("show onu-profile", "Perfiles de ONU disponibles", "perfiles"),
    ComandoCandidato("show profile", "Variante", "perfiles"),
    ComandoCandidato("show dba-profile", "Perfiles DBA (ancho de banda)", "perfiles"),
    ComandoCandidato("show line-profile", "Perfiles de línea", "perfiles"),
    ComandoCandidato("show service-port", "Asociación ONU ↔ VLAN de servicio", "servicio"),
    ComandoCandidato("show vlan", "VLAN configuradas", "servicio"),
    # --- configuración completa ------------------------------------------
    # Se deja al final: es la salida más larga y la que más tarda.
    ComandoCandidato("show running-config", "Configuración completa en vivo", "configuracion"),
)
