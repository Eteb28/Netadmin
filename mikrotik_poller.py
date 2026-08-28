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
mikrotik_poller.py — Monitoreo SNMP de los routers MikroTik (RouterOS).

Todos los OIDs de acá están VALIDADOS contra un walk real de un CCR2116-12G-4S+
con RouterOS 7.8 (rama .1.3.6.1.4.1.14988.1.1).

Lee tres cosas, y cada una sirve para algo distinto:

  1. SALUD DEL EQUIPO (.1.1.3.100) — temperaturas, ventiladores y fuentes.
     La tabla es AUTO-DESCRIPTIVA: cada fila trae el nombre del sensor y su
     valor, así que no hay que hardcodear un OID por modelo. Un CCR chico y un
     CCR grande exponen sensores distintos y los dos se leen igual.

  2. SESIONES PPPoE ACTIVAS (.1.1.2.1) — usuario, IP asignada y tráfico.
     Es la respuesta directa a "¿este cliente está conectado ahora?", y se
     cruza con clientes.pppoe_usuario.

  3. VECINOS (.1.1.11.1) — todo lo que el router ve por MNDP/CDP: IP, MAC,
     plataforma, identidad y versión. En la red de prueba devolvió 2152
     equipos (CPEs Ubiquiti y Cambium, APs, otros MikroTik) en UNA sola
     consulta. Es MUCHO más rápido que barrer rangos de IP con torre_poller.

Uso:
    python3 mikrotik_poller.py --diag 192.168.10.1      # ver qué devuelve
    python3 mikrotik_poller.py                          # pollea y guarda

Cron sugerido (cada 5 minutos):
    */5 * * * * cd /ruta/a/pucara && python3 mikrotik_poller.py >> /tmp/mkt_poller.log 2>&1
"""
import os
import re
import sqlite3
import subprocess
import time
from datetime import datetime

DB = os.path.join(os.path.dirname(__file__), 'netadmin.db')

MKT = '1.3.6.1.4.1.14988.1.1.'

# ── Identidad y versión (escalares) ──
OID_MKT = {
    'serial':        MKT + '7.3.0',
    'version':       MKT + '7.4.0',
    'fecha_fw':      MKT + '7.6.0',
    'version_actual': MKT + '7.7.0',
    'modelo':        MKT + '7.8.0',
    'board':         MKT + '7.9.0',
    'licencia':      MKT + '4.1.0',
}
# Estándar (sirve en cualquier equipo, no sólo MikroTik)
OID_SYSNAME = '1.3.6.1.2.1.1.5.0'
OID_SYSDESCR = '1.3.6.1.2.1.1.1.0'
OID_UPTIME = '1.3.6.1.2.1.1.3.0'
# CPU y memoria: HOST-RESOURCES-MIB, también estándar
OID_CPU_LOAD = '1.3.6.1.2.1.25.3.3.1.2'      # una fila por núcleo
OID_MEM_TOTAL = '1.3.6.1.2.1.25.2.3.1.5'
OID_MEM_USADA = '1.3.6.1.2.1.25.2.3.1.6'
OID_MEM_DESCR = '1.3.6.1.2.1.25.2.3.1.3'

# ── Tablas ──
OID_HEALTH = MKT + '3.100.1'      # col 2=nombre, 3=valor, 4=unidad
OID_PPP = MKT + '2.1.1'           # col 2=usuario, 3=IP, 8/9=bytes
OID_VECINOS = MKT + '11.1.1'      # col 2=IP, 3=MAC, 4=version, 5=plataforma, 6=identidad

# Unidades de la tabla de salud (col 4). Confirmadas contra el walk:
# 1 = grados Celsius, 2 = RPM, 6 = estado (0/1)
UNIDAD = {1: 'C', 2: 'rpm', 3: 'V', 4: 'A', 5: 'W', 6: 'estado'}


def _snmp_disponible():
    import shutil
    return shutil.which('snmpwalk') is not None


def _walk(ip, community, oid, version='2c', timeout=25, cap=20000):
    """Walk crudo. Devuelve texto (una línea por OID)."""
    cmd = ['snmpwalk', '-On', '-v', version, '-c', community,
           '-t', '5', '-r', '1', ip, oid]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.stdout
    except subprocess.TimeoutExpired:
        return ''
    except Exception:
        return ''


def _get(ip, community, oid, version='2c', timeout=5):
    cmd = ['snmpget', '-Ovq', '-v', version, '-c', community,
           '-t', '3', '-r', '1', ip, oid]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        s = (p.stdout or '').strip().strip('"')
        if not s or 'No Such' in s or 'Timeout' in s:
            return None
        return s
    except Exception:
        return None


def _num(v):
    if v is None:
        return None
    m = re.search(r'-?\d+(?:\.\d+)?', str(v))
    return float(m.group()) if m else None


def parse_tabla(texto, oid_base):
    """Convierte un walk de una tabla en {fila: {columna: valor}}.

    Acepta el OID en notación numérica (-On) o con el prefijo 'iso.', que es
    como lo imprime snmpwalk sin -On: los walks pegados a mano suelen venir
    en ese formato y si no se contempla, el parser devuelve vacío sin avisar."""
    base_num = '.' + oid_base.lstrip('.') + '.'
    base_iso = 'iso.' + oid_base.lstrip('.')[len('1.'):] + '.'
    filas = {}
    for linea in texto.splitlines():
        linea = linea.strip()
        if '=' not in linea:
            continue
        oid, _, val = linea.partition(' = ')
        oid = oid.strip()
        resto = None
        for pref in (base_num, base_iso):
            if oid.startswith(pref):
                resto = oid[len(pref):]
                break
        if resto is None:
            continue
        partes = resto.split('.')
        if len(partes) < 2:
            continue
        col = partes[0]
        idx = '.'.join(partes[1:])
        val = val.strip()
        if ': ' in val:
            val = val.split(': ', 1)[1]
        filas.setdefault(idx, {})[col] = val.strip().strip('"')
    return filas


def leer_salud(ip, community, version='2c'):
    """Sensores del equipo. Devuelve {nombre_sensor: {'valor':x,'unidad':'C'}}.

    Se apoya en que la tabla trae el NOMBRE de cada sensor: así un modelo con
    4 ventiladores y otro sin ninguno se leen con el mismo código."""
    filas = parse_tabla(_walk(ip, community, OID_HEALTH, version), OID_HEALTH)
    out = {}
    for idx, cols in filas.items():
        nombre = cols.get('2')
        if not nombre:
            continue
        out[nombre] = {
            'valor': _num(cols.get('3')),
            'unidad': UNIDAD.get(int(_num(cols.get('4')) or 0), ''),
        }
    return out


def leer_sesiones_ppp(ip, community, version='2c'):
    """Sesiones PPPoE activas: usuario, IP y tráfico acumulado."""
    filas = parse_tabla(_walk(ip, community, OID_PPP, version), OID_PPP)
    ses = []
    for idx, c in filas.items():
        usuario = (c.get('2') or '').strip()
        if not usuario:
            continue
        ses.append({
            'usuario': usuario,
            'ip': c.get('3'),
            'bytes_in': _num(c.get('8')),
            'bytes_out': _num(c.get('9')),
        })
    return ses


def leer_vecinos(ip, community, version='2c'):
    """Equipos que el router ve por descubrimiento (MNDP/CDP).

    Es el atajo rápido al inventario de la red: en vez de barrer rangos de IP
    equipo por equipo, el router ya tiene la lista armada."""
    filas = parse_tabla(_walk(ip, community, OID_VECINOS, version), OID_VECINOS)
    vec = []
    for idx, c in filas.items():
        ipv = c.get('2')
        if not ipv or ipv == '0.0.0.0':
            continue
        vec.append({
            'ip': ipv,
            'mac': _mac(c.get('3')),
            'version': c.get('4'),
            'plataforma': c.get('5'),
            'identidad': (c.get('6') or '').strip(),
            'board': c.get('7'),
        })
    return vec


def _mac(v):
    """'78 9A 18 7E C0 37' (Hex-STRING) → '78:9A:18:7E:C0:37'."""
    if not v:
        return None
    p = v.replace(':', ' ').split()
    if len(p) == 6 and all(len(x) == 2 for x in p):
        return ':'.join(x.upper() for x in p)
    return v.strip() or None


def leer_cpu_mem(ip, community, version='2c'):
    """CPU por núcleo y memoria (HOST-RESOURCES-MIB, estándar)."""
    cpu_txt = _walk(ip, community, OID_CPU_LOAD, version, timeout=15)
    cargas = []
    for linea in cpu_txt.splitlines():
        if '=' in linea:
            v = _num(linea.partition(' = ')[2])
            if v is not None:
                cargas.append(v)
    mem = {'total_kb': None, 'usada_kb': None}
    descr = parse_tabla(_walk(ip, community, OID_MEM_DESCR, version, timeout=15),
                        OID_MEM_DESCR)
    # OID_MEM_* son columnas sueltas: el índice queda como "columna"
    tot = parse_tabla(_walk(ip, community, OID_MEM_TOTAL, version, timeout=15), OID_MEM_TOTAL)
    usa = parse_tabla(_walk(ip, community, OID_MEM_USADA, version, timeout=15), OID_MEM_USADA)
    for idx, c in descr.items():
        nombre = (list(c.values()) or [''])[0]
        if 'main memory' in str(nombre).lower():
            mem['total_kb'] = _num((tot.get(idx) or {}).get(list((tot.get(idx) or {'':''}).keys())[0]))
            mem['usada_kb'] = _num((usa.get(idx) or {}).get(list((usa.get(idx) or {'':''}).keys())[0]))
            break
    return {
        'cpu_nucleos': len(cargas),
        'cpu_prom': round(sum(cargas) / len(cargas), 1) if cargas else None,
        'cpu_max': max(cargas) if cargas else None,
        'cpu_por_nucleo': cargas,
        **mem,
    }


def _uptime_seg(v):
    m = re.search(r'\((\d+)\)', v or '')
    return int(m.group(1)) // 100 if m else None


def poll(ip, community='public', version='2c'):
    """Consulta un MikroTik completo. online=0 si no responde."""
    r = {'ip': ip, 'online': 0}
    up = _get(ip, community, OID_UPTIME, version)
    if up is None:
        return r
    r['online'] = 1
    r['uptime_seg'] = _uptime_seg(up)
    r['identidad'] = _get(ip, community, OID_SYSNAME, version)
    r['descr'] = _get(ip, community, OID_SYSDESCR, version)
    for k, oid in OID_MKT.items():
        r[k] = _get(ip, community, oid, version)
    r.update(leer_cpu_mem(ip, community, version))
    salud = leer_salud(ip, community, version)
    r['sensores'] = salud
    # Atajos para lo que se muestra en la tarjeta
    r['temp_cpu'] = (salud.get('cpu-temperature') or {}).get('valor')
    r['temp_board'] = ((salud.get('temperature') or {}).get('valor')
                       or (salud.get('board-temperature1') or {}).get('valor'))
    r['temp_sfp'] = (salud.get('sfp-temperature') or {}).get('valor')
    r['temp_switch'] = (salud.get('switch-temperature') or {}).get('valor')
    # Ventiladores y fuentes: se listan los que el equipo declare
    r['ventiladores'] = {k: v['valor'] for k, v in salud.items() if 'fan' in k}
    r['fuentes'] = {k: v['valor'] for k, v in salud.items() if 'psu' in k}
    return r


def diagnostico(ip, community='public', version='2c'):
    """Muestra todo lo que se puede leer del equipo, sin escribir en la base."""
    print(f"── Diagnóstico MikroTik {ip} ──")
    d = poll(ip, community, version)
    if not d['online']:
        print("  ✗ No respondió SNMP. Revisá IP, community y versión.")
        return 1
    print(f"  Identidad : {d.get('identidad')}")
    print(f"  Modelo    : {d.get('modelo')}   board: {d.get('board')}")
    print(f"  RouterOS  : {d.get('version')}   serie: {d.get('serial')}")
    up = d.get('uptime_seg') or 0
    print(f"  Uptime    : {up // 86400} días")
    print(f"  CPU       : {d.get('cpu_prom')}% promedio de {d.get('cpu_nucleos')} núcleos "
          f"(máx {d.get('cpu_max')}%)")
    if d.get('total_kb'):
        pct = round((d['usada_kb'] or 0) / d['total_kb'] * 100, 1)
        print(f"  Memoria   : {pct}% usada ({int(d['usada_kb']/1024)} MB de {int(d['total_kb']/1024)} MB)")
    print("  Sensores  :")
    for n, s in sorted(d.get('sensores', {}).items()):
        print(f"      {n:22} {s['valor']} {s['unidad']}")
    ses = leer_sesiones_ppp(ip, community, version)
    print(f"  Sesiones PPPoE activas: {len(ses)}")
    for s in ses[:3]:
        print(f"      {s['usuario'][:38]:38} {s['ip']}")
    vec = leer_vecinos(ip, community, version)
    print(f"  Vecinos descubiertos  : {len(vec)}")
    for v in vec[:3]:
        print(f"      {v['ip']:16} {(v['plataforma'] or '')[:24]:24} {v['identidad'][:28]}")
    return 0


RE_IP_TORRE = re.compile(r'^169\.254\.(\d+)\.(\d+)$')
HOST_MAX_TORRE = 50     # 1-50 = equipos de torre (51-254 son clientes)


def sincronizar_vecinos_torre(con, vecinos):
    """Vuelca los vecinos del MikroTik al inventario de equipos de torre.

    Por qué sirve: torre_poller descubre barriendo los hosts 1-50 de CADA
    subred uno por uno, y la mayoría de esas IPs no existen — se va casi todo
    el tiempo esperando timeouts. El MikroTik ya tiene la lista armada por
    descubrimiento (MNDP/CDP), así que esto la trae en una sola consulta.

    NO reemplaza a torre_poller: el vecino no informa banda ni modo, que es lo
    que hace falta para clasificar un equipo como master/slave/AP. Lo que hace
    es dejar el inventario al día (IP, MAC, nombre, modelo, versión) para que
    el sondeo fino sólo tenga que visitar equipos que se sabe que existen.
    Devuelve (nuevos, actualizados)."""
    cols = {r[1] for r in con.execute("PRAGMA table_info(ip_equipos_torre)").fetchall()}
    # Columnas que puede no haber creado todavía torre_poller
    for col, tipo in (('device_model', 'TEXT'), ('version', 'TEXT'),
                      ('origen', 'TEXT'), ('ultimo_visto', 'TEXT')):
        if col not in cols:
            con.execute(f"ALTER TABLE ip_equipos_torre ADD COLUMN {col} {tipo}")
    ahora = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    nuevos = act = 0
    for v in vecinos:
        m = RE_IP_TORRE.match(v.get('ip') or '')
        if not m:
            continue                      # no es del direccionamiento de torres
        subred, host = int(m.group(1)), int(m.group(2))
        if not (1 <= host <= HOST_MAX_TORRE):
            continue                      # es un cliente, no un equipo de torre
        fila = con.execute("SELECT id, nombre FROM ip_equipos_torre WHERE subred=? AND host=?",
                           (subred, host)).fetchone()
        if fila:
            # El nombre cargado a mano gana sobre la identidad del equipo: si
            # alguien lo renombró en Pucará, no se lo pisa con el valor de MNDP.
            con.execute("""UPDATE ip_equipos_torre
                           SET mac=COALESCE(NULLIF(?,''), mac),
                               nombre=CASE WHEN COALESCE(nombre,'')='' THEN ? ELSE nombre END,
                               device_model=COALESCE(NULLIF(?,''), device_model),
                               version=COALESCE(NULLIF(?,''), version),
                               origen=COALESCE(origen,'mndp'), ultimo_visto=?
                           WHERE id=?""",
                        (v.get('mac') or '', v.get('identidad') or '',
                         v.get('plataforma') or '', v.get('version') or '', ahora, fila['id']))
            act += 1
        else:
            con.execute("""INSERT INTO ip_equipos_torre
                           (subred, host, nombre, mac, device_model, version, origen,
                            ultimo_visto, modificado)
                           VALUES(?,?,?,?,?,?,'mndp',?,?)""",
                        (subred, host, v.get('identidad') or '', v.get('mac') or '',
                         v.get('plataforma') or '', v.get('version') or '', ahora, ahora))
            nuevos += 1
    con.commit()
    return nuevos, act


def _tablas(con):
    con.execute("""CREATE TABLE IF NOT EXISTS mikrotik_estado(
        equipo_id INTEGER PRIMARY KEY,
        ip TEXT, identidad TEXT, modelo TEXT, version TEXT, serial TEXT,
        uptime_seg INTEGER, online INTEGER DEFAULT 0,
        cpu_prom REAL, cpu_max REAL, cpu_nucleos INTEGER,
        mem_total_kb REAL, mem_usada_kb REAL,
        temp_cpu REAL, temp_board REAL, temp_sfp REAL, temp_switch REAL,
        sesiones_ppp INTEGER, vecinos INTEGER,
        sensores_json TEXT, last_check TEXT
    )""")
    con.commit()


def main():
    if not _snmp_disponible():
        print("✗ Falta net-snmp. Instalá: sudo apt install snmp")
        return
    con = sqlite3.connect(DB, timeout=30)
    con.row_factory = sqlite3.Row
    _tablas(con)
    # Los MikroTik se toman del inventario de torres (tipo/fabricante MikroTik)
    try:
        filas = con.execute("""SELECT id, ip, snmp_ip, snmp_community, modelo
                               FROM torre_equipos
                               WHERE estado!='de_baja'
                                 AND (LOWER(COALESCE(fabricante,'')) LIKE '%mikrotik%'
                                   OR LOWER(COALESCE(modelo,'')) LIKE '%ccr%'
                                   OR LOWER(COALESCE(modelo,'')) LIKE '%routerboard%')
                            """).fetchall()
    except sqlite3.OperationalError as e:
        print(f"✗ No se pudo leer el inventario: {e}")
        con.close()
        return
    if not filas:
        print("No hay equipos MikroTik en el inventario de torres.")
        con.close()
        return
    import json
    print(f"Polleando {len(filas)} MikroTik…")
    for f in filas:
        ip = f['snmp_ip'] or f['ip']
        if not ip:
            continue
        comm = f['snmp_community'] or 'public'
        try:
            d = poll(ip, comm)
        except Exception as e:
            print(f"  [ERROR] {ip}: {e}")
            continue
        n_ses = n_vec = 0
        if d['online']:
            try:
                n_ses = len(leer_sesiones_ppp(ip, comm))
            except Exception:
                pass
            try:
                vecinos = leer_vecinos(ip, comm)
                n_vec = len(vecinos)
                nuevos, actualizados = sincronizar_vecinos_torre(con, vecinos)
                if nuevos or actualizados:
                    print(f"      ↳ inventario de torres: {nuevos} nuevos, "
                          f"{actualizados} actualizados (desde vecinos MNDP)")
            except Exception as e:
                print(f"      ↳ (sincronización de vecinos falló: {e})")
        con.execute("""
            INSERT INTO mikrotik_estado(equipo_id, ip, identidad, modelo, version, serial,
                uptime_seg, online, cpu_prom, cpu_max, cpu_nucleos, mem_total_kb, mem_usada_kb,
                temp_cpu, temp_board, temp_sfp, temp_switch, sesiones_ppp, vecinos,
                sensores_json, last_check)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(equipo_id) DO UPDATE SET
                ip=excluded.ip, identidad=excluded.identidad, modelo=excluded.modelo,
                version=excluded.version, serial=excluded.serial, uptime_seg=excluded.uptime_seg,
                online=excluded.online, cpu_prom=excluded.cpu_prom, cpu_max=excluded.cpu_max,
                cpu_nucleos=excluded.cpu_nucleos, mem_total_kb=excluded.mem_total_kb,
                mem_usada_kb=excluded.mem_usada_kb, temp_cpu=excluded.temp_cpu,
                temp_board=excluded.temp_board, temp_sfp=excluded.temp_sfp,
                temp_switch=excluded.temp_switch, sesiones_ppp=excluded.sesiones_ppp,
                vecinos=excluded.vecinos, sensores_json=excluded.sensores_json,
                last_check=excluded.last_check
        """, (f['id'], ip, d.get('identidad'), d.get('modelo'), d.get('version'),
              d.get('serial'), d.get('uptime_seg'), d.get('online'),
              d.get('cpu_prom'), d.get('cpu_max'), d.get('cpu_nucleos'),
              d.get('total_kb'), d.get('usada_kb'), d.get('temp_cpu'),
              d.get('temp_board'), d.get('temp_sfp'), d.get('temp_switch'),
              n_ses, n_vec, json.dumps(d.get('sensores', {})),
              datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        con.commit()
        estado = 'ONLINE' if d['online'] else 'OFFLINE'
        print(f"  [{estado}] {ip} {d.get('identidad') or ''} "
              + (f"CPU {d.get('cpu_prom')}% · {d.get('temp_cpu')}°C · "
                 f"{n_ses} PPPoE · {n_vec} vecinos" if d['online'] else ''))
    con.close()
    print("Listo.")


if __name__ == '__main__':
    import sys
    if '--diag' in sys.argv:
        i = sys.argv.index('--diag')
        if len(sys.argv) <= i + 1:
            print("Uso: python3 mikrotik_poller.py --diag <IP> [community] [version]")
            sys.exit(2)
        sys.exit(diagnostico(sys.argv[i + 1],
                             sys.argv[i + 2] if len(sys.argv) > i + 2 else 'public',
                             sys.argv[i + 3] if len(sys.argv) > i + 3 else '2c'))
    main()
