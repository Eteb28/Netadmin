#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
snmp_poller.py — Poller SNMP de equipos inalámbricos para Pucará.

Cierra el circuito de las Fases 4/5/8:
  1. Lee del inventario los equipos marcados como AP (torre_equipos.es_ap=1).
  2. Sondea cada uno con el adaptador del fabricante (snmp_wireless).
  3. Cruza cada estación con su cliente (MAC → IP → nombre).
  4. Escribe la señal en historial_senal_cliente con source='snmp'
     (misma tabla que ya usa la pestaña Monitoreo → aparece solo).
  5. Actualiza el estado SNMP del equipo en el inventario.

REUTILIZA el histórico existente (no crea una segunda estructura): la señal va
a historial_senal_cliente.nivel_dbm; CCQ/airMAX/tasas van en observaciones para
verse en el tooltip del gráfico. El campo source distingue el origen del dato.

DÓNDE CORRE: donde haya alcance de red a los APs (la VM con las VPNs) y acceso a
netadmin.db. Si Pucará no llega a los equipos, montar/sincronizar la DB o usar
el endpoint de ingesta (ver README al pie).

Uso:
    python3 snmp_poller.py --db /ruta/netadmin.db          # sondea todos los AP
    python3 snmp_poller.py --db /ruta/netadmin.db --ap 5   # solo el equipo id=5
    python3 snmp_poller.py --db /ruta/netadmin.db --dry    # no escribe, muestra
"""

import sqlite3
import argparse
import sys
from datetime import datetime

import snmp_wireless as sw


def _log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}")


def pollear_ap(con, equipo, dry=False):
    """Sondea un AP del inventario y guarda la señal de sus estaciones.
    Devuelve (n_estaciones, n_vinculadas)."""
    ip = equipo['snmp_ip'] or equipo['ip']
    fab = (equipo['snmp_fabricante'] or equipo['fabricante'] or 'ubiquiti').lower()
    comm = equipo['snmp_community'] or 'public'
    nombre_ap = equipo['modelo'] or f"equipo #{equipo['id']}"
    if not ip:
        _log(f"  ⚠ {nombre_ap}: sin IP para sondear")
        return 0, 0
    if fab not in sw.ADAPTADORES:
        _log(f"  ⚠ {nombre_ap}: sin adaptador para '{fab}' (disponibles: {list(sw.ADAPTADORES)})")
        return 0, 0

    try:
        data = sw.poll(ip, fab, comm)
    except Exception as e:
        _log(f"  ✗ {nombre_ap} ({ip}): {e}")
        if not dry:
            con.execute("UPDATE torre_equipos SET snmp_estado='offline', ultimo_snmp=? WHERE id=?",
                        (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), equipo['id']))
            _ev_equipo(con, equipo, 'snmp_caido', True, f"{nombre_ap} no responde SNMP")
            con.commit()
        return 0, 0

    if data.get('error'):
        _log(f"  ✗ {nombre_ap} ({ip}): {data['error']}")
        if not dry:
            con.execute("UPDATE torre_equipos SET snmp_estado='offline', ultimo_snmp=? WHERE id=?",
                        (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), equipo['id']))
            _ev_equipo(con, equipo, 'snmp_caido', True, f"{nombre_ap}: {data['error']}")
            con.commit()
        return 0, 0

    estaciones = data.get('estaciones', [])
    ahora = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    ssid_ap = (data.get('device') or {}).get('essid')
    vinculadas = 0
    macs_vistas = []
    for est in estaciones:
        cid, criterio = sw.match_cliente(est, con)
        # Instantánea para la Vista de APs: entra toda estación reportada,
        # cruce o no con un cliente (ver _guardar_estacion_snmp en app.py).
        if est.get('mac') and not dry:
            macs_vistas.append(est['mac'])
            sw.guardar_estacion(con, equipo['id'], est, cid, ssid_ap, ahora)
        if est.get('rssi') is None or not cid:
            continue
        vinculadas += 1
        obs = sw.obs_metricas(est)
        if criterio != 'mac':
            obs = (obs + f" · [match:{criterio}]").strip(' ·')
        if not dry:
            con.execute("""INSERT INTO historial_senal_cliente
                           (cliente_id, nivel_dbm, tipo, observaciones, fecha, usuario, source)
                           VALUES(?,?,?,?,?,?,?)""",
                        (cid, est['rssi'], 'snmp', obs, ahora, 'snmp_poller', 'snmp'))
            # Torre fehaciente: este cliente está tomando servicio de la torre del AP
            try:
                sw.marcar_torre_cliente(con, cid, equipo['id'], equipo['torre_id'], ahora)
            except (KeyError, IndexError):
                pass  # el row del equipo podría no traer torre_id

    if not dry:
        sw.purgar_estaciones(con, equipo['id'], macs_vistas)
        con.execute("""UPDATE torre_equipos SET snmp_estado='online', ultimo_snmp=? WHERE id=?""",
                    (ahora, equipo['id']))
        _ev_equipo(con, equipo, 'snmp_caido', False)   # recuperado si estaba caído
        # Interfaces LAN (IF-MIB): detectar 10 Mbps y puertos down como eventos
        try:
            ver = equipo['snmp_version'] if 'snmp_version' in equipo.keys() else '1'
            ifdata = sw.walk_ifmib(ip, comm, ver or '1')
            _procesar_eventos_lan(con, equipo, ifdata)
        except Exception as e:
            _log(f"    (IF-MIB no disponible: {e})")
        con.commit()

    _log(f"  ✓ {nombre_ap} ({ip}): {len(estaciones)} estaciones, {vinculadas} vinculadas a clientes"
         + (" [DRY]" if dry else ""))
    return len(estaciones), vinculadas


def _ev_equipo(con, equipo, tipo, activo, detalle='', interfaz=None, valor=None):
    """Wrapper de procesar_evento con el torre_id del equipo."""
    torre_id = equipo['torre_id'] if 'torre_id' in equipo.keys() else None
    res = sw.procesar_evento(con, equipo['id'], torre_id, tipo, activo, detalle, interfaz, valor)
    if res == 'inicio':
        _log(f"    🔔 EVENTO {tipo}" + (f" [{interfaz}]" if interfaz else "") + f": {detalle}")
    elif res == 'recuperado':
        _log(f"    ✅ RECUPERADO {tipo}" + (f" [{interfaz}]" if interfaz else ""))
    return res


def _procesar_eventos_lan(con, equipo, ifdata):
    """Genera eventos por cada puerto LAN físico: 10 Mbps y down/recuperado."""
    for i in ifdata.get('lan', []):
        nombre = i['nombre']
        est = i.get('estado_lan')
        # 10 Mbps (crítico)
        _ev_equipo(con, equipo, 'lan_10mbps', est == 'critico',
                   f"LAN {nombre} negociada a {i['speed_mbps']} Mbps", interfaz=nombre,
                   valor=i['speed_mbps'])
        # Puerto caído (solo si admin lo tiene arriba)
        caido = (i.get('oper') != 'up' and i.get('admin') == 'up')
        _ev_equipo(con, equipo, 'lan_down', caido,
                   f"Puerto LAN {nombre} DOWN", interfaz=nombre)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', required=True, help='Ruta a netadmin.db')
    ap.add_argument('--ap', type=int, help='Sondear solo el equipo con este id')
    ap.add_argument('--dry', action='store_true', help='No escribir, solo mostrar')
    args = ap.parse_args()

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row

    if args.ap:
        equipos = con.execute("SELECT * FROM torre_equipos WHERE id=?", (args.ap,)).fetchall()
    else:
        equipos = con.execute("SELECT * FROM torre_equipos WHERE es_ap=1 AND estado!='de_baja'").fetchall()

    if not equipos:
        _log("No hay equipos marcados como AP (es_ap=1) en el inventario.")
        con.close(); return

    _log(f"Sondeando {len(equipos)} AP…")
    tot_est = tot_vin = 0
    for e in equipos:
        ne, nv = pollear_ap(con, e, dry=args.dry)
        tot_est += ne; tot_vin += nv
    _log(f"Listo. {tot_est} estaciones, {tot_vin} señales guardadas"
         + (" (DRY: nada escrito)" if args.dry else " con source='snmp'"))
    con.close()


if __name__ == '__main__':
    main()

# ─────────────────────────────────────────────────────────────────────────
# DESPLIEGUE
#
# A) Pucará llega a los APs:
#    Correr por cron en el host de Pucará, cada 5-15 min:
#      */10 * * * * cd /ruta/pucara && python3 snmp_poller.py --db netadmin.db
#
# B) Solo la VM llega a los APs (caso ERLAN):
#    Opción 1 — DB compartida: montar/sincronizar netadmin.db en la VM y correr
#               el poller ahí con --db apuntando a esa copia.
#    Opción 2 — Agente HTTP (RECOMENDADO, ya implementado): correr snmp_agent.py
#               en la VM. Pide la lista de APs a Pucará (/api/snmp/aps), los sondea
#               y postea los resultados (/api/snmp/ingest); Pucará cruza y guarda.
#               Requiere en Pucará: env SNMP_INGEST_TOKEN=<token>
#               En la VM: PUCARA_URL=https://IP SNMP_INGEST_TOKEN=<token> python3 snmp_agent.py
# ─────────────────────────────────────────────────────────────────────────
