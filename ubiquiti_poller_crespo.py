#!/usr/bin/env python3
# Pucará — Sistema de gestión para ISP
# Copyright (C) 2026 Esteban Aguiar
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

"""
ubiquiti_poller.py — Sondea equipos Ubiquiti airOS y guarda los datos en Pucara
═══════════════════════════════════════════════════════════════════════════════════
Se conecta a la IP del equipo, hace login, lee /status.cgi y extrae:
  - WLAN0 MAC (ath0), Device Model, Firmware, Uptime, estado LAN (eth0)
  - AP MAC, SSID  → histórico Torre/AP
  - Signal, CCQ, TX/RX → histórico Señal
  - Coteja WLAN0 MAC vs MAC del sistema, y Device Model vs modelo cargado

Uso:
    # Sondear UN cliente puntual (por id de cliente):
    python3 ubiquiti_poller.py --cliente 123

    # Sondeo automático de toda la zona (para el cron):
    python3 ubiquiti_poller.py --zona-auto

    # Probar sin guardar:
    python3 ubiquiti_poller.py --cliente 123 --dry-run
"""
import argparse, json, sqlite3, sys, time
from datetime import datetime
import requests
import urllib3
urllib3.disable_warnings()

DB = 'netadmin.db'

# Localidades a sondear en el modo automático (las inalámbricas de Paraná y alrededores)
ZONAS_AUTO = ['CRESPO', 'ALDEA MARIA LUISA', 'ARANGUREN', 'GENERAL RAMIREZ', 'CAMPS', 'ALDEA SAN JUAN', 'ALDEA SAN RAFAEL', 'SEGUI', 'ISLETAS', 'PUIGGARI', 'LIBERTADOR SAN MARTIN']

# Credenciales a probar en orden (la primera que funcione se usa)
CREDENCIALES = [
    ('ubnt', 'rucula'),
    ('ubnt', 'ubnt'),
    ('admin', 'rucula'),
    ('root', 'rucula'),
]


def _login(base, timeout=8):
    """Login en airOS. Devuelve sesión autenticada o None."""
    for user, pwd in CREDENCIALES:
        s = requests.Session()
        s.verify = False
        try:
            s.get(base, timeout=timeout)
            s.post(f"{base}/login.cgi",
                   data={'username': user, 'password': pwd, 'uri': '/'},
                   timeout=timeout)
            # Verificar que entró: status.cgi debe devolver JSON
            r = s.get(f"{base}/status.cgi", timeout=timeout)
            if r.text.strip().startswith('{'):
                return s, (user, pwd)
        except Exception:
            continue
    return None, None


def _norm_mac(m):
    """Normaliza una MAC a mayúsculas con : para comparar."""
    if not m:
        return ''
    return m.upper().replace('-', ':').strip()


def sondear_equipo(ip, timeout=8):
    """Sondea un equipo y devuelve un dict con los datos parseados, o {'error': ...}."""
    # Probar HTTPS primero, luego HTTP
    for esquema in ('https', 'http'):
        base = f"{esquema}://{ip}"
        s, cred = _login(base, timeout)
        if s:
            try:
                data = s.get(f"{base}/status.cgi", timeout=timeout).json()
                return _parsear(data, ip)
            except Exception as e:
                return {'error': f'login OK pero status.cgi falló: {e}', 'ip': ip}
    return {'error': 'no se pudo conectar/autenticar', 'ip': ip}


def _parsear(data, ip):
    """Extrae los campos de interés del JSON de /status.cgi."""
    host = data.get('host', {})
    wl = data.get('wireless', {})
    ifaces = {i['ifname']: i for i in data.get('interfaces', [])}

    ath0 = ifaces.get('ath0', {})
    eth0 = ifaces.get('eth0', {})

    # Uptime legible
    up = host.get('uptime', 0)
    up_txt = f"{up//86400}d {(up%86400)//3600}h {((up%86400)%3600)//60}m"

    # CCQ viene multiplicado x10 (882 = 88.2%)
    ccq_raw = wl.get('ccq', 0)
    ccq_pct = round(ccq_raw / 10, 1) if ccq_raw else 0

    # Estado LAN (eth0)
    eth_status = eth0.get('status', {})
    lan_plugged = eth_status.get('plugged', 0)
    lan_speed = eth_status.get('speed', 0)
    lan_txt = f"{'conectada' if lan_plugged else 'desconectada'} {lan_speed}Mbps" if lan_plugged else 'desconectada'

    return {
        'ip': ip,
        'ok': True,
        'wlan0_mac': _norm_mac(ath0.get('hwaddr', '')),
        'lan_mac': _norm_mac(eth0.get('hwaddr', '')),
        'device_model': (host.get('devmodel', '') or '').strip(),
        'firmware': host.get('fwversion', ''),
        'fwprefix': host.get('fwprefix', ''),
        'uptime_seg': up,
        'uptime_txt': up_txt,
        'hostname': host.get('hostname', ''),
        'lan_plugged': lan_plugged,
        'lan_speed': lan_speed,
        'lan_estado': lan_txt,
        # Wireless / señal
        'ap_mac': _norm_mac(wl.get('apmac', '')),
        'ssid': wl.get('essid', ''),
        'signal': wl.get('signal'),
        'ccq': ccq_pct,
        'tx_rate': wl.get('txrate', ''),
        'rx_rate': wl.get('rxrate', ''),
        'modo': wl.get('mode', ''),
        'frecuencia': wl.get('frequency', ''),
    }


def _ensure_tablas(con):
    """Crea las tablas/columnas necesarias si no existen."""
    # Tabla de chequeos de equipo (firmware, LAN, uptime, cotejos)
    con.execute("""CREATE TABLE IF NOT EXISTS chequeos_equipo(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cliente_id INTEGER NOT NULL,
        fecha TEXT DEFAULT(datetime('now','localtime')),
        ip TEXT,
        wlan0_mac TEXT, lan_mac TEXT, device_model TEXT,
        firmware TEXT, uptime_seg INTEGER, uptime_txt TEXT,
        lan_estado TEXT, ap_mac TEXT, ssid TEXT,
        signal INTEGER, ccq REAL, tx_rate TEXT, rx_rate TEXT,
        mac_coincide INTEGER, modelo_coincide INTEGER,
        observaciones TEXT, origen TEXT)""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_chequeo_cliente ON chequeos_equipo(cliente_id)")


def guardar_resultado(con, cliente, datos, origen='manual', dry_run=False):
    """Guarda el sondeo en: chequeos_equipo + histórico señal + histórico torre/AP.
    Hace el cotejo de MAC y modelo contra lo cargado en el cliente."""
    cid = cliente['id']

    # ── Cotejo de MAC (WLAN0 vs el N° de Serie del sistema) ──
    # La MAC del equipo se carga en el campo "N° de Serie" (equipo_serie).
    # Fallback al campo mac_address por si algún cliente la tiene ahí.
    serie_sistema = _norm_mac(cliente['equipo_serie'] or '')
    mac_address_sistema = _norm_mac(cliente['mac_address'] or '')
    ref_sistema = serie_sistema or mac_address_sistema  # preferimos la serie
    mac_equipo = datos['wlan0_mac']
    mac_coincide = 1 if (ref_sistema and mac_equipo and ref_sistema == mac_equipo) else 0
    if not ref_sistema:
        mac_estado = 'sin N° de serie en sistema'
    elif mac_coincide:
        mac_estado = '✓ coincide'
    else:
        mac_estado = f'⚠ NO coincide (sistema: {ref_sistema})'

    # ── Cotejo de modelo ──
    modelo_sistema = (cliente['equipo_modelo'] or '').strip().lower()
    modelo_equipo = datos['device_model'].lower()
    # Coincidencia flexible: "nanostation m2" matchea aunque el sistema diga "Nano M2"
    modelo_coincide = 1 if (modelo_sistema and modelo_equipo and
                            (modelo_sistema in modelo_equipo or modelo_equipo in modelo_sistema)) else 0
    modelo_estado = 'sin modelo en sistema' if not modelo_sistema else ('✓ coincide' if modelo_coincide else '⚠ NO coincide')

    obs = f"MAC: {mac_estado} | Modelo: {modelo_estado}"

    if dry_run:
        print(f"\n[DRY-RUN] Cliente {cliente['nombre']} (#{cliente['nro_cliente']}):")
        print(f"  WLAN0 MAC equipo: {mac_equipo} | N° serie sistema: {ref_sistema or '(vacío)'} → {mac_estado}")
        print(f"  Modelo equipo: {datos['device_model']} | sistema: {cliente['equipo_modelo'] or '(vacío)'} → {modelo_estado}")
        print(f"  AP: {datos['ssid']} ({datos['ap_mac']}) | Signal: {datos['signal']}dBm | CCQ: {datos['ccq']}% | TX/RX: {datos['tx_rate']}/{datos['rx_rate']}")
        print(f"  Firmware: {datos['firmware']} | LAN: {datos['lan_estado']} | Uptime: {datos['uptime_txt']}")
        return {'mac_coincide': mac_coincide, 'modelo_coincide': modelo_coincide}

    # ── 1) Guardar chequeo de equipo ──
    con.execute("""INSERT INTO chequeos_equipo
        (cliente_id, ip, wlan0_mac, lan_mac, device_model, firmware, uptime_seg, uptime_txt,
         lan_estado, ap_mac, ssid, signal, ccq, tx_rate, rx_rate,
         mac_coincide, modelo_coincide, observaciones, origen)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (cid, datos['ip'], datos['wlan0_mac'], datos['lan_mac'], datos['device_model'],
         datos['firmware'], datos['uptime_seg'], datos['uptime_txt'], datos['lan_estado'],
         datos['ap_mac'], datos['ssid'], datos['signal'], datos['ccq'],
         datos['tx_rate'], datos['rx_rate'], mac_coincide, modelo_coincide, obs, origen))

    # ── 2) Histórico de señal (signal, ccq, tx/rx) ──
    # Reutiliza la tabla historial_senal_cliente que ya existe
    try:
        con.execute("""INSERT INTO historial_senal_cliente
            (cliente_id, nivel_dbm, tipo, observaciones, usuario)
            VALUES(?,?,?,?,?)""",
            (cid, datos['signal'], 'auto-sondeo',
             f"CCQ {datos['ccq']}% · TX/RX {datos['tx_rate']}/{datos['rx_rate']} · AP {datos['ssid']}",
             origen))
    except Exception as e:
        print(f"  (aviso: no se pudo guardar en histórico señal: {e})")

    # ── 3) Histórico de Torre/AP (AP MAC, SSID) ──
    # El registro queda en chequeos_equipo; el histórico torre/AP se ve desde ahí.

    # Commit con reintentos ante "database is locked" (la app web puede estar escribiendo)
    for intento in range(5):
        try:
            con.commit()
            break
        except sqlite3.OperationalError as e:
            if 'locked' in str(e).lower() and intento < 4:
                time.sleep(1.5)  # esperar y reintentar
                continue
            raise
    return {'mac_coincide': mac_coincide, 'modelo_coincide': modelo_coincide,
            'mac_estado': mac_estado, 'modelo_estado': modelo_estado}


def sondear_cliente(con, cid, origen='manual', dry_run=False):
    """Sondea el equipo de un cliente por su id."""
    cli = con.execute("""SELECT id, nombre, nro_cliente, ip_asignada, mac_address,
                         equipo_serie, equipo_modelo, tipo_servicio, localidad
                         FROM clientes WHERE id=?""", (cid,)).fetchone()
    if not cli:
        return {'error': 'cliente no encontrado'}
    if not cli['ip_asignada']:
        return {'error': 'el cliente no tiene IP asignada'}

    datos = sondear_equipo(cli['ip_asignada'])
    if datos.get('error'):
        return {'error': datos['error'], 'ip': cli['ip_asignada']}

    res = guardar_resultado(con, cli, datos, origen, dry_run)
    return {'ok': True, 'datos': datos, 'cotejo': res, 'cliente': cli['nombre']}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cliente', type=int, help='ID del cliente a sondear')
    ap.add_argument('--zona-auto', action='store_true', help='Sondear toda la zona (cron)')
    ap.add_argument('--db', default=DB)
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    con = sqlite3.connect(args.db, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=30000")
    _ensure_tablas(con)

    if args.cliente:
        r = sondear_cliente(con, args.cliente, 'manual', args.dry_run)
        if r.get('error'):
            print(f"❌ {r['error']}")
            sys.exit(1)
        print(f"✅ {r['cliente']}: sondeo OK")
        if not args.dry_run:
            c = r['cotejo']
            print(f"   {c.get('mac_estado','')} | {c.get('modelo_estado','')}")

    elif args.zona_auto:
        # Clientes inalámbricos de las zonas, con IP.
        # Solo Vigentes (activo) y Suspendidos: no gastamos tiempo en pte_rescision
        # ni rescision/baja (esos equipos probablemente ya no están conectados).
        ph = ','.join('?' * len(ZONAS_AUTO))
        clientes = con.execute(f"""SELECT id, nombre, localidad, estado FROM clientes
            WHERE tipo_servicio='inalambrico'
              AND estado IN ('activo','suspendido')
              AND ip_asignada IS NOT NULL AND ip_asignada != ''
              AND UPPER(localidad) IN ({ph})
            ORDER BY localidad, nombre""", ZONAS_AUTO).fetchall()
        print(f"[poller] {len(clientes)} equipos a sondear (vigentes + suspendidos)\n")
        ok = fail = 0
        for c in clientes:
            r = sondear_cliente(con, c['id'], 'auto', args.dry_run)
            estado_lbl = '🟢' if c['estado']=='activo' else '🟡'
            if r.get('error'):
                fail += 1
                print(f"  ✗ {estado_lbl} {c['nombre']} ({c['localidad']}): {r['error']}")
            else:
                ok += 1
                print(f"  ✓ {estado_lbl} {c['nombre']} ({c['localidad']})")
            time.sleep(1)  # no saturar la red
        print(f"\n[poller] Terminado: {ok} OK, {fail} con error")
    else:
        ap.print_help()
    con.close()


if __name__ == '__main__':
    main()
