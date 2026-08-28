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
torre_poller.py — Sondea los equipos de torre (rango 1-50 de cada subred)
═══════════════════════════════════════════════════════════════════════════════════
A diferencia del poller de clientes (que sondea por IP de cliente), este recorre
TODO el rango 1-50 de cada subred cargada en ip_rangos, descubriendo equipos nuevos.

Clasifica cada equipo encontrado:
  - 5 GHz + modo 'ap'  → Master de enlace de torre (irradia)
  - 5 GHz + modo 'sta' → Slave de enlace (recibe de otra torre)
  - 2.4 GHz + modo 'ap' → AP de clientes
  - 2.4 GHz + modo 'sta' → cliente (no debería estar en 1-50)

Guarda en ip_equipos_torre (actualiza nombre/mac/datos) y en chequeos_torre (histórico).

Uso:
    python3 torre_poller.py                  (dry-run: muestra qué encuentra)
    python3 torre_poller.py --apply
    python3 torre_poller.py --subred 80 --apply   (solo una subred)
    python3 torre_poller.py --rapido --apply      (solo las IPs ya descubiertas
                                                   por mikrotik_poller: mucho
                                                   más rápido, no descubre nuevas)
"""
import argparse, sqlite3, sys, time, re
import requests
import urllib3
urllib3.disable_warnings()

DB = 'netadmin.db'
CREDENCIALES = [('ubnt', 'ubnt'), ('admin', 'rucula'), ('ubnt', 'rucula'), ('root', 'rucula')]


def _login(base, timeout=1):
    for user, pwd in CREDENCIALES:
        s = requests.Session()
        s.verify = False
        try:
            s.get(base, timeout=timeout)
            s.post(f"{base}/login.cgi",
                   data={'username': user, 'password': pwd, 'uri': '/'}, timeout=timeout)
            r = s.get(f"{base}/status.cgi", timeout=timeout)
            if r.text.strip().startswith('{'):
                return s
        except Exception:
            continue
    return None


def _norm_mac(m):
    return (m or '').upper().replace('-', ':').strip()


def _banda(freq_txt):
    """De '5745 MHz' o '2387 MHz' devuelve '5GHz' o '2.4GHz'."""
    m = re.search(r'(\d+)', str(freq_txt or ''))
    if not m:
        return '?'
    mhz = int(m.group(1))
    if mhz >= 4000:
        return '5GHz'
    if mhz >= 2000:
        return '2.4GHz'
    return '?'


def _clasificar(banda, modo):
    """Clasifica el equipo según banda y modo."""
    if banda == '5GHz':
        return 'Master enlace' if modo == 'ap' else 'Slave enlace'
    if banda == '2.4GHz':
        return 'AP clientes' if modo == 'ap' else 'Cliente (en rango torre?)'
    return 'Indefinido'


def sondear_ip(ip, timeout=1):
    """Sondea una IP. Devuelve datos parseados o None si no responde."""
    for esquema in ('https', 'http'):
        base = f"{esquema}://{ip}"
        s = _login(base, timeout)
        if s:
            try:
                d = s.get(f"{base}/status.cgi", timeout=timeout).json()
                return _parsear(d, ip)
            except Exception:
                return None
    return None


def _parsear(data, ip):
    host = data.get('host', {})
    wl = data.get('wireless', {})
    ifaces = {i['ifname']: i for i in data.get('interfaces', [])}
    ath0 = ifaces.get('ath0', {})
    eth0 = ifaces.get('eth0', {})

    freq = wl.get('frequency', '')
    banda = _banda(freq)
    modo = wl.get('mode', '')
    up = host.get('uptime', 0)
    ccq_raw = wl.get('ccq', 0)

    return {
        'ip': ip,
        'wlan0_mac': _norm_mac(ath0.get('hwaddr', '')),
        'lan_mac': _norm_mac(eth0.get('hwaddr', '')),
        'device_model': (host.get('devmodel', '') or '').strip(),
        'firmware': host.get('fwversion', ''),
        'hostname': host.get('hostname', ''),
        'uptime_seg': up,
        'uptime_txt': f"{up//86400}d {(up%86400)//3600}h",
        'banda': banda,
        'frecuencia': freq,
        'modo': modo,
        'clasificacion': _clasificar(banda, modo),
        'ssid': wl.get('essid', ''),
        'ap_mac': _norm_mac(wl.get('apmac', '')),   # a quién está enlazado (si es slave/sta)
        'signal': wl.get('signal'),
        'ccq': round(ccq_raw / 10, 1) if ccq_raw else 0,
        'tx_rate': wl.get('txrate', ''),
        'rx_rate': wl.get('rxrate', ''),
        'channel': wl.get('channel'),
    }


def _ensure_tablas(con):
    con.execute("""CREATE TABLE IF NOT EXISTS chequeos_torre(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        subred INTEGER, host INTEGER, ip TEXT,
        fecha TEXT DEFAULT(datetime('now','localtime')),
        wlan0_mac TEXT, device_model TEXT, firmware TEXT, hostname TEXT,
        uptime_txt TEXT, banda TEXT, frecuencia TEXT, modo TEXT,
        clasificacion TEXT, ssid TEXT, ap_mac TEXT,
        signal INTEGER, ccq REAL, tx_rate TEXT, rx_rate TEXT, channel INTEGER)""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_chq_torre ON chequeos_torre(subred, host)")
    # Asegurar columnas extra en ip_equipos_torre para los datos del sondeo
    cols = {r[1] for r in con.execute("PRAGMA table_info(ip_equipos_torre)").fetchall()}
    for col, tipo in [('banda','TEXT'), ('modo','TEXT'), ('clasificacion','TEXT'),
                      ('ssid','TEXT'), ('firmware','TEXT'), ('device_model','TEXT'),
                      ('ultimo_sondeo','TEXT'), ('ap_mac_enlace','TEXT')]:
        if col not in cols:
            con.execute(f"ALTER TABLE ip_equipos_torre ADD COLUMN {col} {tipo}")


def guardar(con, subred, host, datos):
    """Guarda en chequeos_torre (histórico) y actualiza ip_equipos_torre (inventario)."""
    # Histórico
    con.execute("""INSERT INTO chequeos_torre
        (subred,host,ip,wlan0_mac,device_model,firmware,hostname,uptime_txt,
         banda,frecuencia,modo,clasificacion,ssid,ap_mac,signal,ccq,tx_rate,rx_rate,channel)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (subred, host, datos['ip'], datos['wlan0_mac'], datos['device_model'],
         datos['firmware'], datos['hostname'], datos['uptime_txt'], datos['banda'],
         datos['frecuencia'], datos['modo'], datos['clasificacion'], datos['ssid'],
         datos['ap_mac'], datos['signal'], datos['ccq'], datos['tx_rate'],
         datos['rx_rate'], datos['channel']))
    # Inventario: crear o actualizar el equipo de torre
    existe = con.execute("SELECT id, nombre FROM ip_equipos_torre WHERE subred=? AND host=?",
                         (subred, host)).fetchone()
    # Nombre: si ya tiene uno cargado a mano, respetarlo; si no, usar el hostname del equipo
    nombre = datos['hostname'] or f"Equipo {datos['ip']}"
    if existe and existe['nombre']:
        nombre = existe['nombre']  # no pisar el nombre cargado a mano
    if existe:
        con.execute("""UPDATE ip_equipos_torre SET mac=?, banda=?, modo=?, clasificacion=?,
            ssid=?, firmware=?, device_model=?, ap_mac_enlace=?,
            ultimo_sondeo=datetime('now','localtime') WHERE subred=? AND host=?""",
            (datos['wlan0_mac'], datos['banda'], datos['modo'], datos['clasificacion'],
             datos['ssid'], datos['firmware'], datos['device_model'], datos['ap_mac'],
             subred, host))
    else:
        con.execute("""INSERT INTO ip_equipos_torre
            (subred,host,nombre,mac,banda,modo,clasificacion,ssid,firmware,device_model,
             ap_mac_enlace,ultimo_sondeo)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,datetime('now','localtime'))""",
            (subred, host, nombre, datos['wlan0_mac'], datos['banda'], datos['modo'],
             datos['clasificacion'], datos['ssid'], datos['firmware'],
             datos['device_model'], datos['ap_mac']))


def _objetivos_descubiertos(con, subredes):
    """(subred, host) de los equipos que ya sabemos que existen.

    Los llena mikrotik_poller con la tabla de vecinos del router (MNDP/CDP), y
    sirven para sondear SÓLO lo que está vivo en vez de barrer 1-50 a ciegas.
    Se pide ultimo_visto para no arrastrar equipos que ya no están en la red."""
    cols = {r[1] for r in con.execute("PRAGMA table_info(ip_equipos_torre)").fetchall()}
    if 'ultimo_visto' not in cols:
        return []      # todavía no corrió mikrotik_poller: no hay descubrimiento
    ph = ','.join('?' * len(subredes))
    filas = con.execute(f"""
        SELECT subred, host FROM ip_equipos_torre
        WHERE subred IN ({ph}) AND host BETWEEN 1 AND 50
          AND ultimo_visto IS NOT NULL
          AND ultimo_visto >= datetime('now','localtime','-7 day')
        ORDER BY subred, host""", subredes).fetchall()
    return [(r['subred'], r['host']) for r in filas]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default=DB)
    ap.add_argument('--subred', type=int, help='Sondear solo esta subred (ej: 80)')
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--timeout', type=int, default=6)
    ap.add_argument('--rapido', action='store_true',
                    help='Sondear sólo las IPs ya descubiertas por el MikroTik '
                         '(mikrotik_poller) en vez de barrer 1-50 de cada subred. '
                         'Mucho más rápido, pero NO encuentra equipos nuevos que '
                         'todavía no aparecieron como vecinos: para eso, correr '
                         'el barrido completo de vez en cuando.')
    args = ap.parse_args()

    con = sqlite3.connect(args.db, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=30000")
    _ensure_tablas(con)

    # Subredes a recorrer
    if args.subred is not None:
        subredes = [args.subred]
    else:
        subredes = [r['subred'] for r in
                    con.execute("SELECT subred FROM ip_rangos WHERE activo=1 ORDER BY subred").fetchall()]
    if not subredes:
        print("No hay rangos cargados en ip_rangos. Cargá los rangos primero.")
        con.close()
        return

    # Qué IPs sondear: el barrido completo (1-50 por subred) o sólo las que el
    # MikroTik ya vio como vecinos. Barrer a ciegas gasta casi todo el tiempo
    # esperando el timeout de IPs que no existen.
    objetivos = None
    if args.rapido:
        objetivos = _objetivos_descubiertos(con, subredes)
        if not objetivos:
            print("[torre-poller] --rapido pedido pero no hay equipos descubiertos todavía.\n"
                  "               Corré primero: python3 mikrotik_poller.py\n"
                  "               Por ahora se hace el barrido completo.\n")
            objetivos = None
    if objetivos is None:
        objetivos = [(sub, host) for sub in subredes for host in range(1, 51)]
        print(f"[torre-poller] Barrido COMPLETO: {len(subredes)} subred(es) × hosts 1-50 "
              f"= {len(objetivos)} sondeos\n")
    else:
        completo = len(subredes) * 50
        print(f"[torre-poller] Modo RÁPIDO: {len(objetivos)} equipos ya descubiertos "
              f"(en vez de {completo} sondeos a ciegas)\n")

    encontrados = []
    sub_actual = None
    for sub, host in objetivos:
        if sub != sub_actual:
            print(f"── Subred 169.254.{sub}.x ──")
            if args.apply and sub_actual is not None:
                con.commit()
            sub_actual = sub
        ip = f"169.254.{sub}.{host}"
        datos = sondear_ip(ip, args.timeout)
        if datos:
            tag = {'Master enlace':'🗼','Slave enlace':'📡','AP clientes':'📶'}.get(datos['clasificacion'],'❓')
            print(f"  {tag} .{host:<3} {datos['banda']:6} {datos['modo']:4} | {datos['device_model'][:22]:22} | {datos['clasificacion']} | {datos['ssid'] or datos['hostname'] or ''}")
            encontrados.append((sub, host, datos))
            if args.apply:
                guardar(con, sub, host, datos)
        time.sleep(0.3)
    if args.apply:
        con.commit()

    print(f"\n[torre-poller] {len(encontrados)} equipos encontrados")
    # Resumen por clasificación
    clases = {}
    for _, _, d in encontrados:
        clases[d['clasificacion']] = clases.get(d['clasificacion'], 0) + 1
    for c, n in sorted(clases.items(), key=lambda x: -x[1]):
        print(f"   {c}: {n}")
    if not args.apply:
        print("\nModo: DRY-RUN (usá --apply para guardar)")
    con.close()


if __name__ == '__main__':
    main()
