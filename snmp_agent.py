#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
snmp_agent.py — Agente SNMP para la VM (relay) de ERLAN.

Se usa cuando Pucará NO tiene alcance de red a los APs pero la VM SÍ.
Corre en la VM, donde hay:
  - alcance de red a los equipos (las VPNs),
  - net-snmp instalado (snmpwalk),
  - snmp_wireless.py (este mismo repo),
  - la librería requests.

Flujo:
  1) GET  {PUCARA_URL}/api/snmp/aps      → lista de APs a sondear
  2) sondea cada AP con el adaptador del fabricante (snmp_wireless)
  3) POST {PUCARA_URL}/api/snmp/ingest   → resultados; Pucará cruza y guarda

El cruce estación↔cliente y la escritura al histórico ocurren en Pucará
(donde vive la data de clientes), no acá. La VM sólo aporta el alcance SNMP.

Configuración (variables de entorno o argumentos):
  PUCARA_URL          ej. https://pucara.miempresa.com   (o IP con https)
  SNMP_INGEST_TOKEN   el mismo token configurado en Pucará

Uso:
  PUCARA_URL=https://IP SNMP_INGEST_TOKEN=xxx python3 snmp_agent.py
  python3 snmp_agent.py --url https://IP --token xxx [--insecure] [--dry]

Cron sugerido en la VM (cada 10 min):
  */10 * * * * cd /ruta/agente && PUCARA_URL=https://IP SNMP_INGEST_TOKEN=xxx python3 snmp_agent.py >> /var/log/snmp_agent.log 2>&1
"""

import os
import sys
import json
import argparse
from datetime import datetime

try:
    import requests
except ImportError:
    print("Falta 'requests'. Instalá: pip install requests")
    sys.exit(1)

import snmp_wireless as sw


def _log(msg):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', default=os.environ.get('PUCARA_URL', ''),
                    help='URL base de Pucará (o env PUCARA_URL)')
    ap.add_argument('--token', default=os.environ.get('SNMP_INGEST_TOKEN', ''),
                    help='Token de ingesta (o env SNMP_INGEST_TOKEN)')
    ap.add_argument('--insecure', action='store_true',
                    help='No verificar el certificado TLS (self-signed)')
    ap.add_argument('--dry', action='store_true',
                    help='Sondea y muestra, pero NO postea a Pucará')
    ap.add_argument('--timeout', type=int, default=20, help='Timeout HTTP (s)')
    args = ap.parse_args()

    if not args.url or not args.token:
        _log("Faltan --url/--token (o PUCARA_URL/SNMP_INGEST_TOKEN). Abortando.")
        sys.exit(2)

    base = args.url.rstrip('/')
    verify = not args.insecure
    if not verify:
        try:
            import urllib3
            urllib3.disable_warnings()
        except Exception:
            pass

    # 1) Pedir la lista de APs a Pucará
    try:
        r = requests.get(f"{base}/api/snmp/aps", params={'token': args.token},
                         verify=verify, timeout=args.timeout)
    except Exception as e:
        _log(f"No pude pedir la lista de APs: {e}")
        sys.exit(3)
    if r.status_code != 200:
        _log(f"Pucará rechazó /api/snmp/aps: {r.status_code} {r.text[:200]}")
        sys.exit(3)
    aps = r.json()
    if not aps:
        _log("No hay APs marcados para SNMP en el inventario. Nada que hacer.")
        return

    _log(f"Sondeando {len(aps)} AP…")
    resultados = []
    for a in aps:
        ip = a.get('ip'); fab = (a.get('fabricante') or 'ubiquiti').lower()
        comm = a.get('community') or 'public'
        nombre = a.get('modelo') or f"equipo #{a.get('equipo_id')}"
        try:
            data = sw.poll(ip, fab, comm)
        except Exception as e:
            data = {'device': {}, 'estaciones': [], 'error': str(e)}
        n_est = len(data.get('estaciones', []))
        err = data.get('error')
        _log(f"  {'✗' if err else '✓'} {nombre} ({ip}) [{fab}]: "
             + (f"error: {err}" if err else f"{n_est} estaciones"))
        resultados.append({'equipo_id': a.get('equipo_id'), **data})

    if args.dry:
        _log("DRY: no se postea. Resumen JSON:")
        print(json.dumps(resultados, indent=2, ensure_ascii=False)[:4000])
        return

    # 3) Postear resultados a Pucará (cruce + guardado ocurren allá)
    try:
        r = requests.post(f"{base}/api/snmp/ingest", params={'token': args.token},
                          json={'results': resultados}, verify=verify, timeout=args.timeout)
    except Exception as e:
        _log(f"No pude postear resultados: {e}")
        sys.exit(4)
    if r.status_code != 200:
        _log(f"Pucará rechazó /api/snmp/ingest: {r.status_code} {r.text[:200]}")
        sys.exit(4)
    resp = r.json()
    _log(f"Ingesta OK: {resp.get('estaciones')} estaciones, "
         f"{resp.get('vinculadas')} señales guardadas con source='snmp'.")


if __name__ == '__main__':
    main()
