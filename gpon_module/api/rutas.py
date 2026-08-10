"""API interna del módulo GPON.

Es la **única** puerta de entrada de la interfaz gráfica. La web no importa
servicios ni drivers: hace ``fetch`` contra estas rutas. Ese límite es lo que
permite que mañana la consuma Pucará, una app móvil o un script, sin cambiar
nada de acá.

Convenciones:

* Todo error del módulo se traduce a un JSON con ``error`` y ``detalle``, y al
  código HTTP que corresponde. La interfaz nunca ve una traza de Python.
* Las escrituras van en modo simulación salvo que se pida ``dry_run=false``
  explícitamente en el cuerpo. El valor por defecto no depende del navegador.
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, current_app, jsonify, request

from ..core.enums import Capacidad, EstadoONU
from ..core.errors import (
    CapacidadNoSoportada,
    ErrorGPON,
    ErrorTransporte,
    ErrorValidacion,
    NoEncontrado,
)
from ..core.models import RefONU
from ..core.registry import describir, fabricantes_registrados
from ..services import Contenedor
from . import serializadores as ser

log = logging.getLogger(__name__)

api = Blueprint("api", __name__, url_prefix="/api")


def _sistema() -> Contenedor:
    return current_app.config["CONTENEDOR"]


def _entero(nombre: str, por_defecto: int) -> int:
    valor = request.args.get(nombre)
    try:
        return int(valor) if valor not in (None, "") else por_defecto
    except ValueError as exc:
        raise ErrorValidacion(f"El parámetro '{nombre}' debe ser un número") from exc


# --- manejo de errores ----------------------------------------------------


@api.errorhandler(NoEncontrado)
def _no_encontrado(exc: NoEncontrado):
    return jsonify({"error": "no_encontrado", "detalle": str(exc)}), 404


@api.errorhandler(ErrorValidacion)
def _validacion(exc: ErrorValidacion):
    return jsonify({"error": "validacion", "detalle": str(exc)}), 400


@api.errorhandler(CapacidadNoSoportada)
def _capacidad(exc: CapacidadNoSoportada):
    # 501 y no 400: la petición es válida, el equipo no sabe hacerlo.
    return jsonify({"error": "capacidad_no_soportada", "detalle": str(exc)}), 501


@api.errorhandler(ErrorTransporte)
def _transporte(exc: ErrorTransporte):
    # 502: el problema está entre nosotros y la OLT, no en la petición.
    return jsonify({"error": "sin_comunicacion", "detalle": str(exc)}), 502


@api.errorhandler(ErrorGPON)
def _generico(exc: ErrorGPON):
    log.exception("Error no clasificado en la API")
    return jsonify({"error": type(exc).__name__, "detalle": str(exc)}), 500


# --- estado del módulo ----------------------------------------------------


@api.get("/salud")
def salud():
    sistema = _sistema()
    return jsonify(
        {
            "ok": True,
            "olts": len(sistema.servicio_olt.listar()),
            "dry_run_por_defecto": sistema.configuracion.dry_run_por_defecto,
            "base_datos": sistema.configuracion.url_base_datos.split("///")[0] + "///…",
        }
    )


@api.get("/fabricantes")
def fabricantes():
    """Drivers disponibles y lo que cada uno sabe hacer.

    La interfaz lo usa para armar el formulario de alta y para saber, antes de
    conectarse, qué funciones mostrar.
    """
    salida = []
    for fabricante in fabricantes_registrados():
        descripcion = describir(fabricante)
        salida.append(
            {
                "fabricante": str(fabricante),
                "nombre": descripcion.nombre,
                "modelos": list(descripcion.modelos_soportados),
                "protocolos": list(descripcion.protocolos),
                "version": descripcion.version,
                "capacidades": sorted(c.name for c in descripcion.capacidades),
            }
        )
    return jsonify(salida)


# --- OLT ------------------------------------------------------------------


@api.get("/olts")
def listar_olts():
    sistema = _sistema()
    solo_activas = request.args.get("activas") == "1"
    return jsonify([ser.olt(o) for o in sistema.servicio_olt.listar(solo_activas)])


@api.get("/olts/<int:olt_id>")
def obtener_olt(olt_id: int):
    sistema = _sistema()
    entidad = sistema.servicio_olt.obtener(olt_id)
    datos = ser.olt(entidad)
    datos["capacidades"] = sorted(c.name for c in sistema.servicio_olt.capacidades(olt_id))
    ultima = sistema.repositorio_sincronizacion.ultima_de_olt(olt_id)
    datos["ultima_corrida"] = ser.sincronizacion(ultima) if ultima else None
    return jsonify(datos)


@api.get("/olts/<int:olt_id>/capacidades")
def capacidades_de_olt(olt_id: int):
    sistema = _sistema()
    capacidades = sistema.servicio_olt.capacidades(olt_id)
    return jsonify(
        {
            "soportadas": sorted(c.name for c in capacidades),
            "no_soportadas": sorted(c.name for c in Capacidad if c not in capacidades),
        }
    )


@api.post("/olts/<int:olt_id>/probar")
def probar_olt(olt_id: int):
    sistema = _sistema()
    ok, detalle = sistema.servicio_olt.probar_conexion(olt_id)
    return jsonify({"ok": ok, "detalle": detalle}), (200 if ok else 502)


@api.post("/olts/<int:olt_id>/descubrir")
def descubrir_olt(olt_id: int):
    sistema = _sistema()
    resultado = sistema.servicio_descubrimiento.descubrir(olt_id)
    return jsonify(ser.resultado_descubrimiento(resultado))


@api.get("/olts/<int:olt_id>/puertos")
def puertos_de_olt(olt_id: int):
    sistema = _sistema()
    return jsonify([ser.puerto_pon(p) for p in sistema.repositorio_puerto.listar_de_olt(olt_id)])


@api.get("/olts/<int:olt_id>/perfiles")
def perfiles_de_olt(olt_id: int):
    sistema = _sistema()
    return jsonify(ser.perfiles(sistema.repositorio_perfiles.obtener_de_olt(olt_id)))


@api.get("/olts/<int:olt_id>/resumen")
def resumen_de_olt(olt_id: int):
    """Cifras del panel: estados, motivos de caída y corrida más reciente."""
    sistema = _sistema()
    onus = sistema.servicio_onu.listar(olt_id)
    por_estado: dict[str, int] = {}
    por_motivo: dict[str, int] = {}
    for entidad in onus:
        clave = str(entidad.estado)
        por_estado[clave] = por_estado.get(clave, 0) + 1
        if entidad.estado is EstadoONU.FUERA_DE_LINEA:
            motivo = str(entidad.motivo_caida)
            por_motivo[motivo] = por_motivo.get(motivo, 0) + 1

    ultima = sistema.repositorio_sincronizacion.ultima_de_olt(olt_id)
    return jsonify(
        {
            "olt": ser.olt(sistema.servicio_olt.obtener(olt_id)),
            "total_onus": len(onus),
            "por_estado": por_estado,
            "por_motivo_caida": por_motivo,
            "puertos": len(sistema.repositorio_puerto.listar_de_olt(olt_id)),
            "ultima_corrida": ser.sincronizacion(ultima) if ultima else None,
        }
    )


# --- ONU ------------------------------------------------------------------


@api.get("/olts/<int:olt_id>/onus")
def listar_onus(olt_id: int):
    """Inventario con filtros. La paginación es del servidor, no del navegador."""
    sistema = _sistema()
    pon = request.args.get("pon", type=int)
    estado = request.args.get("estado")
    buscar = (request.args.get("buscar") or "").strip().lower()
    limite = min(_entero("limite", 100), 2000)
    desplazamiento = _entero("desplazamiento", 0)

    onus = sistema.servicio_onu.listar(olt_id, pon)
    if estado:
        onus = [o for o in onus if str(o.estado) == estado]
    if buscar:
        onus = [
            o
            for o in onus
            if buscar in o.nombre.lower()
            or buscar in o.numero_serie.lower()
            or buscar in str(o.ref)
        ]

    total = len(onus)
    pagina = onus[desplazamiento : desplazamiento + limite]
    return jsonify(
        {
            "total": total,
            "limite": limite,
            "desplazamiento": desplazamiento,
            "resultados": [ser.onu(o) for o in pagina],
        }
    )


@api.get("/olts/<int:olt_id>/onus/<int:pon>/<int:numero>")
def obtener_onu(olt_id: int, pon: int, numero: int):
    sistema = _sistema()
    entidad = sistema.servicio_onu.obtener_por_ref(olt_id, RefONU(pon, numero))
    return jsonify(ser.onu(entidad))


@api.get("/olts/<int:olt_id>/onus/<int:pon>/<int:numero>/potencia")
def potencia_de_onu(olt_id: int, pon: int, numero: int):
    sistema = _sistema()
    potencia = sistema.servicio_onu.potencia(olt_id, RefONU(pon, numero))
    datos = ser.lectura_optica(potencia.lectura)
    datos["clasificacion"] = str(potencia.clasificacion)
    return jsonify(datos)


@api.get("/olts/<int:olt_id>/potencias")
def potencias_de_olt(olt_id: int):
    """Potencias de todo el parque, en una sola lectura del equipo."""
    sistema = _sistema()
    potencias = sistema.servicio_onu.potencias(olt_id)
    resumen: dict[str, int] = {}
    for potencia in potencias:
        clave = str(potencia.clasificacion)
        resumen[clave] = resumen.get(clave, 0) + 1
    return jsonify(
        {
            "resumen": resumen,
            "lecturas": [
                dict(ser.lectura_optica(p.lectura), clasificacion=str(p.clasificacion))
                for p in potencias
            ],
        }
    )


@api.get("/olts/<int:olt_id>/no-autorizadas")
def no_autorizadas(olt_id: int):
    sistema = _sistema()
    return jsonify([ser.onu_no_autorizada(n) for n in sistema.servicio_onu.no_autorizadas(olt_id)])


# --- escrituras -----------------------------------------------------------


def _dry_run_pedido() -> bool | None:
    """Lee ``dry_run`` del cuerpo. Ausente significa "usar el valor por defecto".

    Nunca se asume ``false``: para que una operación llegue de verdad al equipo,
    el pedido tiene que decirlo.
    """
    cuerpo: dict[str, Any] = request.get_json(silent=True) or {}
    valor = cuerpo.get("dry_run")
    if valor is None:
        return None
    return bool(valor)


@api.post("/olts/<int:olt_id>/onus/<int:pon>/<int:numero>/reiniciar")
def reiniciar_onu(olt_id: int, pon: int, numero: int):
    sistema = _sistema()
    cuerpo = request.get_json(silent=True) or {}
    resultado = sistema.servicio_onu.reiniciar(
        olt_id,
        RefONU(pon, numero),
        usuario=cuerpo.get("usuario", "web"),
        dry_run=_dry_run_pedido(),
    )
    return jsonify(
        {
            "ok": resultado.ok,
            "simulado": resultado.simulado,
            "comandos": list(resultado.comandos_enviados),
            "salida": resultado.salida_cruda,
            "error": resultado.error,
        }
    )


@api.get("/olts/<int:olt_id>/pendientes")
def pendientes(olt_id: int):
    """ONU detectadas por el equipo y todavía sin autorizar.

    Consulta el equipo en vivo: es una lista que cambia sola cuando un técnico
    conecta una ONU, así que no tendría sentido servirla de la base.
    """
    sistema = _sistema()
    puertos = tuple(request.args.getlist("pon"))
    resultado = sistema.servicio_pendientes.listar(
        olt_id, puertos=puertos, protocolo=request.args.get("protocolo", "ssh")
    )
    return jsonify(
        {
            "momento": resultado.momento.isoformat(),
            "completo": resultado.completo,
            "pendientes": [
                {
                    "pon": p.pon,
                    "numero_serie": p.numero_serie,
                    "indice_propuesto": p.indice_propuesto,
                    "estado": p.estado_informado,
                }
                for p in resultado.pendientes
            ],
            "puertos_con_falla": [
                {"pon": pon, "motivo": motivo} for pon, motivo in resultado.puertos_con_falla
            ],
        }
    )


@api.post("/olts/<int:olt_id>/autorizar")
def autorizar_onu(olt_id: int):
    """Da de alta una ONU. **Simulado salvo que el pedido diga lo contrario.**

    El cuerpo pide ``dry_run: false`` explícitamente para que los comandos
    salgan al equipo. Ausente significa simulación, igual que en el resto del
    módulo: nunca se asume que se quiere escribir.
    """
    sistema = _sistema()
    cuerpo: dict[str, Any] = request.get_json(silent=True) or {}

    if not cuerpo.get("numero_serie"):
        raise ErrorValidacion("Falta el número de serie de la ONU")
    if not cuerpo.get("perfil_onu"):
        raise ErrorValidacion("Falta el perfil de ONU")

    pedido = _dry_run_pedido()
    resultado = sistema.servicio_alta_onu.autorizar(
        olt_id,
        numero_serie=cuerpo["numero_serie"],
        perfil_onu=cuerpo["perfil_onu"],
        pon=cuerpo.get("pon"),
        onu_id=cuerpo.get("onu_id"),
        descripcion=cuerpo.get("descripcion", ""),
        perfil_dba=cuerpo.get("perfil_dba", "Internet"),
        trafico_subida=cuerpo.get("trafico_subida", ""),
        trafico_bajada=cuerpo.get("trafico_bajada", ""),
        vlan=int(cuerpo.get("vlan", 1001)),
        dry_run=True if pedido is None else pedido,
        usuario=cuerpo.get("usuario", "web"),
        protocolo=cuerpo.get("protocolo", "ssh"),
    )
    return jsonify(
        {
            "ok": resultado.ok,
            "simulado": resultado.simulado,
            "pon": resultado.solicitud.pon,
            "onu_id": resultado.solicitud.onu_id,
            "numero_serie": resultado.solicitud.numero_serie,
            "descripcion": resultado.solicitud.descripcion_efectiva,
            "comandos": list(resultado.comandos),
            "comandos_aplicados": list(resultado.comandos_aplicados),
            "quedo_a_medias": resultado.quedo_a_medias,
            "comando_que_fallo": resultado.comando_que_fallo,
            "error": resultado.error,
        }
    )


@api.post("/olts/<int:olt_id>/baja-onu")
def baja_onu(olt_id: int):
    """Da de baja una ONU. **Simulado salvo que el pedido diga lo contrario.**

    ``numero_serie_esperado`` es opcional pero conviene mandarlo: si en ese
    índice hay otra ONU, la baja se rechaza sin tocar el equipo. Sin él, lo
    único que identifica al cliente que se queda sin servicio es el número de
    índice.
    """
    sistema = _sistema()
    cuerpo: dict[str, Any] = request.get_json(silent=True) or {}

    if cuerpo.get("pon") is None or cuerpo.get("onu_id") is None:
        raise ErrorValidacion("Faltan el puerto PON y el índice de la ONU")

    pedido = _dry_run_pedido()
    resultado = sistema.servicio_baja_onu.eliminar(
        olt_id,
        pon=int(cuerpo["pon"]),
        onu_id=int(cuerpo["onu_id"]),
        numero_serie_esperado=cuerpo.get("numero_serie_esperado", ""),
        dry_run=True if pedido is None else pedido,
        usuario=cuerpo.get("usuario", "web"),
        protocolo=cuerpo.get("protocolo", "ssh"),
    )
    return jsonify(
        {
            "ok": resultado.ok,
            "simulado": resultado.simulado,
            "pon": resultado.pon,
            "onu_id": resultado.onu_id,
            "numero_serie": resultado.numero_serie,
            "comandos": list(resultado.comandos),
            "comando_que_fallo": resultado.comando_que_fallo,
            "error": resultado.error,
        }
    )


# --- bitácoras ------------------------------------------------------------


@api.get("/eventos")
def eventos():
    sistema = _sistema()
    olt_id = request.args.get("olt_id", type=int)
    return jsonify(
        [
            ser.evento(e)
            for e in sistema.repositorio_evento.listar(
                olt_id=olt_id,
                limite=min(_entero("limite", 100), 1000),
                desplazamiento=_entero("desplazamiento", 0),
            )
        ]
    )


@api.get("/operaciones")
def operaciones():
    """Auditoría de escrituras, incluidas las simuladas."""
    sistema = _sistema()
    olt_id = request.args.get("olt_id", type=int)
    return jsonify(
        [
            ser.operacion(o)
            for o in sistema.repositorio_operacion.listar(
                olt_id=olt_id,
                limite=min(_entero("limite", 100), 1000),
                desplazamiento=_entero("desplazamiento", 0),
            )
        ]
    )


@api.get("/sincronizaciones")
def sincronizaciones():
    sistema = _sistema()
    olt_id = request.args.get("olt_id", type=int)
    return jsonify(
        [
            ser.sincronizacion(s)
            for s in sistema.repositorio_sincronizacion.listar(
                olt_id=olt_id, limite=min(_entero("limite", 50), 500)
            )
        ]
    )


@api.get("/alarmas")
def alarmas():
    sistema = _sistema()
    olt_id = request.args.get("olt_id", type=int)
    return jsonify([ser.alarma(a) for a in sistema.repositorio_alarma.listar_activas(olt_id)])
