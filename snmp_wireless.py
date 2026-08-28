#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
snmp_wireless.py — Monitoreo SNMP de equipos inalámbricos para Pucará.

Arquitectura por adaptadores. Cada fabricante traduce sus OIDs a un modelo
NORMALIZADO común, de modo que el resto de Pucará NO dependa de OIDs concretos:

    SNMP (fabricante)  →  Adaptador  →  Modelo normalizado  →  Pucará

Modelo normalizado (dicts simples, sin dependencias):
    device   = {mac, essid, noise_floor, tx_rate, rx_rate, ancho_mhz,
                estaciones_n, fabricante, modelo, firmware, modo}
    estacion = {mac, nombre, ip, rssi, noise_floor, distancia_m, ccq,
                airmax_quality, airmax_capacity, tx_rate, rx_rate,
                tx_bytes, rx_bytes, uptime_s}

Estado actual:
  - UbiquitiAirOS: OIDs VALIDADOS contra un WALK real de un Rocket airMAX 5GHz
    (rama .1.3.6.1.4.1.41112.1.4). Ver OID_UBNT abajo.
  - Cambium ePMP: OIDs VALIDADOS contra un WALK real de un AP ePMP con 11 SMs
    asociados (rama .1.3.6.1.4.1.17713.21). Se verificó columna por columna de
    la tabla de estaciones: MAC, RSSI, SNR, IP, nombre del cliente, calidad de
    enlace, uptime, tasa, distancia, y modelo/firmware del CPE.

Dónde corre: igual que el poller HTTP actual, este módulo debe ejecutarse
DONDE haya alcance de red a los equipos (la VM con las VPNs), no necesariamente
en el mismo host que Pucará.
"""

import subprocess
import re
import json
import sys
from datetime import datetime

# ───────────────────────── Ubiquiti airOS (UBNT-MIB / AirMAX) ─────────────────────────
# Rama empresarial Ubiquiti: .1.3.6.1.4.1.41112
# Subárbol airOS de radio y estaciones: .1.4
UBNT_BASE = '1.3.6.1.4.1.41112.1.4'

# Tabla de RADIO (una fila, instancia .1). Columnas confirmadas por el WALK real:
OID_UBNT_RADIO = {
    'essid':        UBNT_BASE + '.5.1.2.1',    # STRING  'Dorado'
    'modo':         UBNT_BASE + '.5.1.3.1',    # INTEGER 2=AP  (confirmar 1=Station)
    'mac':          UBNT_BASE + '.5.1.4.1',    # Hex     BSSID del AP
    'noise_floor':  UBNT_BASE + '.5.1.8.1',    # INTEGER -91
    'tx_rate':      UBNT_BASE + '.5.1.9.1',    # INTEGER bps
    'rx_rate':      UBNT_BASE + '.5.1.10.1',   # INTEGER bps
    'ancho_mhz':    UBNT_BASE + '.5.1.14.1',   # INTEGER 20
    'estaciones_n': UBNT_BASE + '.5.1.15.1',   # Gauge32 8
    'antena':       UBNT_BASE + '.1.1.9.1',    # STRING  'Built in - 11 dBi'
}

# Tabla de ESTACIONES asociadas: .1.4.7.1.<columna>.1.<MAC en decimal (6 octetos)>
# Se DESCUBRE por WALK: el índice de cada estación es su propia MAC, no fijo.
UBNT_STA_TABLE = UBNT_BASE + '.7.1'
UBNT_STA_COLS = {
    1:  'mac',              # Hex-STRING
    2:  'nombre',           # STRING (suele traer el nombre del cliente)
    3:  'rssi',             # INTEGER dBm (señal que el AP recibe de la estación)
    4:  'noise_floor',      # INTEGER dBm
    5:  'distancia_m',      # INTEGER metros
    6:  'ccq',              # INTEGER %
    8:  'airmax_quality',   # INTEGER %
    9:  'airmax_capacity',  # INTEGER %
    10: 'ip',               # IpAddress
    11: 'tx_rate',          # INTEGER bps
    12: 'rx_rate',          # INTEGER bps
    13: 'tx_bytes',         # Counter64
    14: 'rx_bytes',         # Counter64
    15: 'uptime_s',         # Timeticks (centésimas de segundo)
}

# sysDescr/sysName genéricos (MIB-2) para identidad básica
OID_SYS = {
    'sysDescr': '1.3.6.1.2.1.1.1.0',
    'sysName':  '1.3.6.1.2.1.1.5.0',
    'uptime':   '1.3.6.1.2.1.1.3.0',
}


# ───────────────────────── Utilidades de parsing ─────────────────────────
_LINE_RE = re.compile(
    r'^(?:iso|\.1|\.iso)?[\d.]*?(?P<oid>[\d.]+)\s*=\s*(?P<type>[\w\-]+):?\s*(?P<val>.*)$'
)


def _mac_from_octetos(octetos):
    """['0','21','109','158','226','5'] → '00:15:6D:9E:E2:05'"""
    try:
        return ':'.join('%02X' % int(o) for o in octetos)
    except (ValueError, TypeError):
        return None


def _mac_from_hex(val):
    """'68 72 51 44 AC 04' → '68:72:51:44:AC:04'"""
    partes = val.strip().split()
    if all(re.fullmatch(r'[0-9A-Fa-f]{2}', p) for p in partes) and partes:
        return ':'.join(p.upper() for p in partes)
    return val.strip()


def _num(val):
    m = re.search(r'-?\d+', val)
    return int(m.group(0)) if m else None


def _timeticks_seg(val):
    """'(94536200) 10 days, 22:36:02.00' → segundos (94536200 centésimas /100)."""
    m = re.search(r'\((\d+)\)', val)
    return int(m.group(1)) // 100 if m else None


def _normalizar_oid(linea):
    """Toma una línea de snmpwalk (con prefijo iso. o .1.3...) y devuelve
    (oid_numerico_desde_41112_o_absoluto, tipo, valor) o None."""
    linea = linea.strip()
    if not linea or '=' not in linea:
        return None
    izq, der = linea.split('=', 1)
    # normalizar el OID: 'iso.3.6.1.4.1.41112...' → '1.3.6.1.4.1.41112...'
    oid = izq.strip()
    oid = oid.replace('iso.', '1.').lstrip('.')
    der = der.strip()
    if ':' in der:
        tipo, val = der.split(':', 1)
        tipo, val = tipo.strip(), val.strip()
    else:
        tipo, val = '', der
    # quitar comillas de STRING
    if val.startswith('"') and val.endswith('"'):
        val = val[1:-1]
    return oid, tipo, val


# ───────────────────────── Adaptador Ubiquiti airOS ─────────────────────────
class UbiquitiAirOS:
    fabricante = 'Ubiquiti'

    @staticmethod
    def parse_walk(texto):
        """Parsea la salida de `snmpwalk` (texto) del subárbol .41112.1.4 a
        modelo normalizado {device, estaciones}. Testeable sin red."""
        radio = {}
        # columnas de estación indexadas por MAC-decimal (string del índice)
        estaciones = {}
        pref_sta = UBNT_STA_TABLE + '.'   # 1.3.6.1.4.1.41112.1.4.7.1.

        # invertir OID_UBNT_RADIO para lookup rápido
        radio_por_oid = {v: k for k, v in OID_UBNT_RADIO.items()}

        for linea in texto.splitlines():
            r = _normalizar_oid(linea)
            if not r:
                continue
            oid, tipo, val = r

            # ¿es una columna de radio?
            if oid in radio_por_oid:
                campo = radio_por_oid[oid]
                if campo == 'mac':
                    radio['mac'] = _mac_from_hex(val)
                elif campo in ('essid', 'antena'):
                    radio[campo] = val
                else:
                    radio[campo] = _num(val)
                continue

            # ¿es una fila de la tabla de estaciones?
            if oid.startswith(pref_sta):
                resto = oid[len(pref_sta):].split('.')
                # resto = [columna, '1', <6 octetos de MAC>]
                if len(resto) < 8:
                    continue
                col = int(resto[0])
                mac_oct = resto[2:8]
                idx = '.'.join(mac_oct)   # clave de la estación
                est = estaciones.setdefault(idx, {'mac': _mac_from_octetos(mac_oct)})
                nombre_col = UBNT_STA_COLS.get(col)
                if not nombre_col:
                    continue
                if nombre_col == 'mac':
                    est['mac'] = _mac_from_hex(val)
                elif nombre_col == 'nombre':
                    est['nombre'] = val
                elif nombre_col == 'ip':
                    est['ip'] = val.strip()
                elif nombre_col == 'uptime_s':
                    est['uptime_s'] = _timeticks_seg(val)
                else:
                    est[nombre_col] = _num(val)

        device = {
            'fabricante': 'Ubiquiti',
            'mac': radio.get('mac'),
            'essid': radio.get('essid'),
            'modo': 'AP' if radio.get('modo') == 2 else ('Station' if radio.get('modo') == 1 else None),
            'noise_floor': radio.get('noise_floor'),
            'tx_rate': radio.get('tx_rate'),
            'rx_rate': radio.get('rx_rate'),
            'ancho_mhz': radio.get('ancho_mhz'),
            'estaciones_n': radio.get('estaciones_n'),
            'antena': radio.get('antena'),
        }
        # completar campos faltantes en cada estación con None (modelo estable)
        campos_est = ['mac', 'nombre', 'ip', 'rssi', 'noise_floor', 'distancia_m',
                      'ccq', 'airmax_quality', 'airmax_capacity', 'tx_rate',
                      'rx_rate', 'tx_bytes', 'rx_bytes', 'uptime_s']
        lista = []
        for est in estaciones.values():
            for c in campos_est:
                est.setdefault(c, None)
            lista.append(est)
        lista.sort(key=lambda e: (e.get('rssi') is None, e.get('rssi') or 0))
        return {'device': device, 'estaciones': lista}

    @staticmethod
    def walk_device(ip, community='public', timeout=8, version='1'):
        """Ejecuta snmpwalk real sobre el subárbol airOS y devuelve el modelo
        normalizado. Requiere net-snmp instalado en el host que corre esto."""
        cmd = ['snmpwalk', f'-v{version}', '-c', community, '-t', str(timeout),
               '-r', '1', ip, UBNT_BASE]
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5)
        except FileNotFoundError:
            raise RuntimeError('Falta net-snmp. Instalá: sudo apt install snmp')
        except subprocess.TimeoutExpired:
            return {'device': {}, 'estaciones': [], 'error': 'timeout'}
        if out.returncode != 0 and not out.stdout:
            return {'device': {}, 'estaciones': [], 'error': (out.stderr or '').strip()[:200]}
        return UbiquitiAirOS.parse_walk(out.stdout)


# ───────────────────────── Cambium ePMP ─────────────────────────
# Rama Cambium: .1.3.6.1.4.1.17713.21
# Estructura MUY distinta a Ubiquiti:
#   - Identidad: escalares en .21.1.1.<x>.0
#   - Radio/estado: escalares en .21.1.2.<x>.0 (RSSI/SNR solo en SM)
#   - Estaciones (lado AP): tabla .21.1.2.30.1.<columna>.<n>, con n SECUENCIAL (1..N),
#     NO la MAC. La MAC es la columna 1/15. Validado contra un AP ePMP2000 con 38 SMs.
CAMBIUM_BASE = '1.3.6.1.4.1.17713.21'

OID_CAMBIUM_DEV = {
    'mac':        CAMBIUM_BASE + '.1.1.5.0',
    'essid':      CAMBIUM_BASE + '.1.1.11.0',   # SSID del sector (ej. "Cardenal")
    'hostname':   CAMBIUM_BASE + '.1.1.13.0',
    'firmware':   CAMBIUM_BASE + '.1.1.17.0',
    'lat':        CAMBIUM_BASE + '.1.1.18.0',
    'lng':        CAMBIUM_BASE + '.1.1.19.0',
    'serial':     CAMBIUM_BASE + '.1.1.31.0',
    'frecuencia': CAMBIUM_BASE + '.1.2.1.0',
    'sm_rssi':    CAMBIUM_BASE + '.1.2.3.0',    # RSSI del SM hacia su AP (solo SM)
    'sm_ssid':    CAMBIUM_BASE + '.1.2.8.0',    # AP al que está asociado (SM)
    'sm_snr':     CAMBIUM_BASE + '.1.2.18.0',   # SNR del SM (solo SM)
    'sm_ap_mac':  CAMBIUM_BASE + '.1.2.19.0',   # MAC del AP asociado (SM)
}

# Tabla de estaciones vista por el AP: .21.1.2.30.1.<col>.<n>
CAMBIUM_STA_TABLE = CAMBIUM_BASE + '.1.2.30.1'
CAMBIUM_STA_COLS = {
    1:  'mac',            # MAC (minúsculas)
    4:  'rssi',           # RSSI (dBm)
    6:  'snr',            # SNR (dB)
    10: 'ip',             # IP
    11: 'estado',         # 'NORMAL'
    18: 'nombre',         # nombre del cliente
    20: 'link_quality',   # % calidad de enlace
    27: 'uptime_str',     # 'DDDD:HH:MM:SS'
    28: 'data_rate',      # '300M'
    29: 'distancia_m',    # metros
    38: 'modelo_sm',      # '5 GHz Force 130 Radio'
    43: 'firmware_sm',    # '4.6.1'
}


def _cambium_uptime_seg(s):
    """'0035:10:44:01' → segundos (35d 10h 44m 01s)."""
    m = re.match(r'\s*(\d+):(\d+):(\d+):(\d+)', s or '')
    if not m:
        return None
    d, h, mi, se = map(int, m.groups())
    return ((d * 24 + h) * 60 + mi) * 60 + se


class CambiumEPMP:
    fabricante = 'Cambium'

    @staticmethod
    def parse_walk(texto):
        """Parsea un WALK ePMP (AP o SM) al modelo normalizado {device, estaciones}."""
        dev_por_oid = {v: k for k, v in OID_CAMBIUM_DEV.items()}
        dev_raw = {}
        estaciones = {}   # n → dict de columnas
        pref_sta = CAMBIUM_STA_TABLE + '.'

        for linea in texto.splitlines():
            r = _normalizar_oid(linea)
            if not r:
                continue
            oid, tipo, val = r
            if oid in dev_por_oid:
                dev_raw[dev_por_oid[oid]] = val
                continue
            if oid.startswith(pref_sta):
                resto = oid[len(pref_sta):].split('.')
                if len(resto) < 2:
                    continue
                col = int(resto[0]); n = resto[1]
                nombre_col = CAMBIUM_STA_COLS.get(col)
                if not nombre_col:
                    continue
                est = estaciones.setdefault(n, {})
                if nombre_col in ('mac', 'nombre', 'ip', 'estado', 'data_rate', 'modelo_sm', 'firmware_sm'):
                    est[nombre_col] = val.strip().upper() if nombre_col == 'mac' else val.strip()
                elif nombre_col == 'uptime_str':
                    est['uptime_s'] = _cambium_uptime_seg(val)
                else:
                    est[nombre_col] = _num(val)

        es_ap = len(estaciones) > 0
        device = {
            'fabricante': 'Cambium',
            'mac': (dev_raw.get('mac') or '').upper() or None,
            'hostname': dev_raw.get('hostname'),
            'modelo': dev_raw.get('hostname'),   # el hostname suele traer el modelo
            'firmware': dev_raw.get('firmware'),
            'serial': dev_raw.get('serial'),
            'frecuencia': _num(dev_raw.get('frecuencia', '')),
            'lat': dev_raw.get('lat'), 'lng': dev_raw.get('lng'),
            'modo': 'AP' if es_ap else 'Station',
            # En un AP el SSID propio está en .1.1.11.0; en un SM ese campo no
            # aplica y lo que interesa es a qué AP se asoció (.1.2.8.0).
            'essid': (dev_raw.get('essid') if es_ap else dev_raw.get('sm_ssid')),
            'estaciones_n': len(estaciones),
        }
        # Para un SM: su propia señal hacia el AP (una sola "estación" = él mismo)
        if not es_ap and dev_raw.get('sm_rssi'):
            device['sm_rssi'] = _num(dev_raw['sm_rssi'])
            device['sm_snr'] = _num(dev_raw.get('sm_snr', ''))
            device['sm_ap_mac'] = dev_raw.get('sm_ap_mac')

        campos = ['mac', 'nombre', 'ip', 'rssi', 'snr', 'noise_floor', 'distancia_m',
                  'ccq', 'airmax_quality', 'airmax_capacity', 'link_quality',
                  'data_rate', 'estado', 'tx_rate', 'rx_rate', 'tx_bytes', 'rx_bytes', 'uptime_s']
        lista = []
        for est in estaciones.values():
            for c in campos:
                est.setdefault(c, None)
            lista.append(est)
        lista.sort(key=lambda e: (e.get('rssi') is None, e.get('rssi') or 0))
        return {'device': device, 'estaciones': lista}

    @staticmethod
    def walk_device(ip, community='public', timeout=10, version='2c'):
        cmd = ['snmpwalk', f'-v{version}', '-c', community, '-t', str(timeout),
               '-r', '1', ip, CAMBIUM_BASE]
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 8)
        except FileNotFoundError:
            raise RuntimeError('Falta net-snmp. Instalá: sudo apt install snmp')
        except subprocess.TimeoutExpired:
            return {'device': {}, 'estaciones': [], 'error': 'timeout'}
        # Cambium suele terminar el WALK con un error de paquete pero ya trajo los datos
        if not out.stdout:
            return {'device': {}, 'estaciones': [], 'error': (out.stderr or '').strip()[:200]}
        return CambiumEPMP.parse_walk(out.stdout)


# ───────────────────────── Registro de adaptadores ─────────────────────────
ADAPTADORES = {
    'ubiquiti': UbiquitiAirOS,
    'cambium': CambiumEPMP,
}


def poll(ip, fabricante='ubiquiti', community='public', version=None):
    """Punto de entrada normalizado: elige adaptador y devuelve modelo común.
    version: '1' | '2c' | '3'. Si es None, usa el default del adaptador."""
    adap = ADAPTADORES.get(fabricante.lower())
    if not adap:
        raise ValueError(f'Sin adaptador para "{fabricante}". Disponibles: {list(ADAPTADORES)}')
    if version:
        return adap.walk_device(ip, community, version=version)
    return adap.walk_device(ip, community)


# ───────────────────────── IF-MIB estándar (interfaces LAN) ─────────────────────────
# Rama IF-MIB (RFC 2863): 1.3.6.1.2.1.2.2.1  — universal, NO es de fabricante.
# Validado contra un WALK real de un AP Ubiquiti airMAX (eth0/eth1/wifi0/ath0/br0).
# OJO: en airOS las interfaces wireless (ath0/wifi0) también reportan ifType=6
# (ethernetCsmacd), así que NO se puede distinguir LAN por tipo → se filtra por
# nombre 'eth*'. ifHighSpeed (31.1.1) puede no existir; ifSpeed (32-bit) alcanza
# para 10/100/1000 Mbps.
IF_BASE = '1.3.6.1.2.1.2.2.1'
IF_COLS = {
    1:  'index',
    2:  'nombre',       # ifDescr  ('eth0', 'ath0', ...)
    3:  'tipo_num',     # ifType   (6=ethernet, 24=loopback)
    4:  'mtu',
    5:  'speed_bps',    # ifSpeed  (bits/s)
    6:  'mac',          # ifPhysAddress (hex)
    7:  'admin_num',    # ifAdminStatus (1=up,2=down)
    8:  'oper_num',     # ifOperStatus  (1=up,2=down,...)
    10: 'in_octets',
    11: 'in_ucast',
    13: 'in_discards',  # ifInDiscards
    14: 'in_errors',    # ifInErrors
    16: 'out_octets',
    17: 'out_ucast',
    18: 'out_discards', # ifOutDiscards
    19: 'out_errors',   # ifOutErrors
}
IF_STATUS = {1: 'up', 2: 'down', 3: 'testing', 4: 'unknown',
             5: 'dormant', 6: 'notPresent', 7: 'lowerLayerDown'}
IF_TIPO = {6: 'ethernet', 24: 'loopback', 1: 'other', 53: 'propVirtual', 131: 'tunnel'}


def _es_lan_fisica(nombre):
    """True si el nombre de interfaz es un puerto ethernet físico (eth0, eth1, ...).
    Excluye wireless (ath*, wifi*), bridges (br*), loopback (lo) y virtuales."""
    return bool(re.match(r'^eth\d+$', (nombre or '').strip(), re.I))


def clasificar_velocidad_lan(mbps, oper):
    """Estado de un puerto LAN según velocidad negociada y estado operativo.
    Devuelve uno de: 'critico' (10 Mbps up), 'normal' (100/1000 up),
    'advertencia' (velocidad rara up), 'down', 'sin_datos'."""
    if oper != 'up':
        return 'down'
    if mbps is None or mbps == 0:
        return 'sin_datos'
    if mbps <= 10:
        return 'critico'          # ⚠️ LAN a 10 Mbps → revisar
    if mbps in (100, 1000, 2500, 10000):
        return 'normal'
    return 'advertencia'


def parse_ifmib(texto):
    """Parsea un WALK de IF-MIB al modelo normalizado.
    Devuelve {'interfaces':[...todas...], 'lan':[...solo eth*...], 'lan_alerta': {...}|None}."""
    pref = IF_BASE + '.'
    filas = {}   # index → {col: valor}
    for linea in texto.splitlines():
        r = _normalizar_oid(linea)
        if not r:
            continue
        oid, tipo, val = r
        if not oid.startswith(pref):
            continue
        resto = oid[len(pref):].split('.')
        if len(resto) < 2:
            continue
        col = int(resto[0]); idx = resto[1]
        nombre_col = IF_COLS.get(col)
        if not nombre_col:
            continue
        f = filas.setdefault(idx, {})
        if nombre_col == 'nombre':
            f['nombre'] = val.strip()
        elif nombre_col == 'mac':
            f['mac'] = _mac_from_hex(val) if val.strip() else None
        else:
            f[nombre_col] = _num(val)

    interfaces = []
    for idx, f in sorted(filas.items(), key=lambda kv: f_idx(kv[0])):
        speed_bps = f.get('speed_bps')
        mbps = int(speed_bps // 1_000_000) if speed_bps else 0
        oper = IF_STATUS.get(f.get('oper_num'), 'unknown')
        admin = IF_STATUS.get(f.get('admin_num'), 'unknown')
        nombre = f.get('nombre') or f"if{idx}"
        interfaces.append({
            'index': f.get('index'),
            'nombre': nombre,
            'tipo': IF_TIPO.get(f.get('tipo_num'), f.get('tipo_num')),
            'es_lan': _es_lan_fisica(nombre),
            'mtu': f.get('mtu'),
            'mac': f.get('mac'),
            'speed_bps': speed_bps,
            'speed_mbps': mbps,
            'admin': admin,
            'oper': oper,
            'in_octets': f.get('in_octets'),
            'out_octets': f.get('out_octets'),
            'in_ucast': f.get('in_ucast'),
            'out_ucast': f.get('out_ucast'),
            'in_errors': f.get('in_errors'),
            'out_errors': f.get('out_errors'),
            'in_discards': f.get('in_discards'),
            'out_discards': f.get('out_discards'),
            'estado_lan': clasificar_velocidad_lan(mbps, oper) if _es_lan_fisica(nombre) else None,
        })

    lan = [i for i in interfaces if i['es_lan']]
    # Alerta de 10 Mbps: primer puerto LAN up negociado a ≤10 Mbps
    alerta = None
    for i in lan:
        if i['estado_lan'] == 'critico':
            alerta = {
                'interfaz': i['nombre'],
                'velocidad_mbps': i['speed_mbps'],
                'mensaje': f"LAN {i['nombre']} negociada a {i['speed_mbps']} Mbps",
            }
            break
    return {'interfaces': interfaces, 'lan': lan, 'lan_alerta': alerta}


def f_idx(s):
    """Orden numérico del índice de interfaz (para sortear)."""
    try:
        return int(s)
    except (ValueError, TypeError):
        return 9999


def walk_ifmib(ip, community='public', version='1', timeout=8):
    """Consulta la IF-MIB de un equipo y devuelve el modelo normalizado de interfaces."""
    cmd = ['snmpwalk', f'-v{version}', '-c', community, '-t', str(timeout), '-r', '1', ip, IF_BASE]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 8)
    except FileNotFoundError:
        raise RuntimeError('Falta net-snmp. Instalá: sudo apt install snmp')
    except subprocess.TimeoutExpired:
        return {'interfaces': [], 'lan': [], 'lan_alerta': None, 'error': 'timeout'}
    if not out.stdout:
        return {'interfaces': [], 'lan': [], 'lan_alerta': None,
                'error': (out.stderr or '').strip()[:200] or 'sin respuesta'}
    return parse_ifmib(out.stdout)


# ───────────────────────── Descubrimiento / autocompletado ─────────────────────────
# System MIB estándar (RFC 1213) — universal, NO es MIB de fabricante. Segura de usar.
OID_SYS = {
    'descr':    '1.3.6.1.2.1.1.1.0',   # sysDescr:   suele traer OS/versión/modelo
    'objectid': '1.3.6.1.2.1.1.2.0',   # sysObjectID: identifica al fabricante
    'uptime':   '1.3.6.1.2.1.1.3.0',   # sysUpTime:  Timeticks (1/100 s)
    'name':     '1.3.6.1.2.1.1.5.0',   # sysName:    hostname
    'location': '1.3.6.1.2.1.1.6.0',   # sysLocation
}


def _snmp_get(ip, oids, community='public', version='1', timeout=8):
    """snmpget de varios OID escalares. Devuelve {oid: valor_str}."""
    cmd = ['snmpget', f'-v{version}', '-c', community, '-t', str(timeout), '-r', '1', ip] + list(oids)
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 6)
    except FileNotFoundError:
        raise RuntimeError('Falta net-snmp. Instalá: sudo apt install snmp')
    except subprocess.TimeoutExpired:
        return {}
    res = {}
    for linea in out.stdout.splitlines():
        r = _normalizar_oid(linea)
        if r:
            oid, tipo, val = r
            res[oid] = val
    return res


def _uptime_desde_timeticks(v):
    """'Timeticks: (62281583) 7 days, 5:00:15' o '(62281583) ...' → texto legible."""
    if not v:
        return None
    m = re.search(r'\((\d+)\)', str(v))
    if m:
        ticks = int(m.group(1))
        seg = ticks // 100
        d, resto = divmod(seg, 86400)
        h, resto = divmod(resto, 3600)
        mi, s = divmod(resto, 60)
        if d:
            return f"{d}d {h}h {mi}m"
        if h:
            return f"{h}h {mi}m"
        return f"{mi}m {s}s"
    return str(v).strip()


def _os_desde_descr(descr):
    """Extrae SO/plataforma del sysDescr (best-effort, sin inventar)."""
    if not descr:
        return None
    d = descr.strip()
    if d.lower().startswith('linux'):
        return 'Linux'
    return d[:60]


def _fw_desde_descr(descr):
    """Intenta extraer la versión de firmware del sysDescr (best-effort).
    airOS suele terminar en '.vX.Y.Z' (ej. 'XM.ar7240.v6.3.11'); preferimos esa
    sobre la versión del kernel Linux que aparece al principio."""
    if not descr:
        return None
    # 1) preferir una versión precedida por 'v' (típica de airOS)
    m = re.search(r'\bv(\d+\.\d+\.\d+(?:[.\-]\w+)?)', descr)
    if m:
        return m.group(1)
    # 2) si no, la última versión tipo x.y.z del texto
    todas = re.findall(r'\b(\d+\.\d+\.\d+(?:[.\-]\w+)?)', descr)
    return todas[-1] if todas else None


def discover(ip, community='public', version='1', fabricante=None, timeout=8):
    """Descubrimiento SNMP para autocompletar el alta de un equipo.
    Combina la system MIB estándar (hostname/OS/firmware/uptime) con el
    adaptador del fabricante (radio: modo/SSID/ancho/antena/estaciones).
    Devuelve sólo lo que realmente obtuvo; lo demás queda en None ('No disponible').
    NO inventa OIDs: para datos sin OID validado (canal, potencia TX) devuelve None.
    """
    # 1) System MIB (universal)
    try:
        sysvals = _snmp_get(ip, OID_SYS.values(), community, version, timeout)
    except RuntimeError as e:
        return {'ok': False, 'error': str(e)}
    sys = {}
    for k, oid in OID_SYS.items():
        sys[k] = sysvals.get(oid) or sysvals.get(oid.lstrip('.'))
    if not any(sys.values()):
        return {'ok': False, 'error': 'Sin respuesta SNMP. Verificá IP, community, versión y que SNMP esté habilitado en el equipo.'}

    # 2) Detectar fabricante (por sysObjectID o el indicado)
    fab = (fabricante or '').lower().strip()
    objid = sys.get('objectid') or ''
    if not fab:
        if '41112' in objid:
            fab = 'ubiquiti'
        elif '17713' in objid:
            fab = 'cambium'

    # 3) Radio del fabricante (best-effort; si falla, seguimos con la system MIB)
    radio = {'device': {}, 'estaciones': []}
    fabs_a_probar = [fab] if fab in ADAPTADORES else list(ADAPTADORES.keys())
    for f in fabs_a_probar:
        try:
            r = ADAPTADORES[f].walk_device(ip, community, version=version)
        except Exception:
            continue
        if r.get('device', {}).get('mac') or r.get('estaciones'):
            fab = f
            radio = r
            break
        if not radio['device']:
            radio = r  # guardamos algo aunque esté vacío

    dev = radio.get('device', {})
    descr = sys.get('descr') or ''
    estaciones = radio.get('estaciones', [])

    # 4) Interfaces LAN (IF-MIB estándar) — best-effort
    interfaces = []
    lan = []
    lan_alerta = None
    try:
        ifdata = walk_ifmib(ip, community, version, timeout)
        interfaces = ifdata.get('interfaces', [])
        lan = ifdata.get('lan', [])
        lan_alerta = ifdata.get('lan_alerta')
    except Exception:
        pass

    device = {
        'fabricante':        dev.get('fabricante') or (fab.capitalize() if fab else None),
        'hostname':          sys.get('name') or dev.get('hostname'),
        'sistema_operativo': _os_desde_descr(descr),
        'firmware':          dev.get('firmware') or _fw_desde_descr(descr),
        'modelo':            dev.get('modelo'),           # sin OID validado en Ubiquiti → None
        'mac':               dev.get('mac'),              # BSSID del radio
        'uptime':            _uptime_desde_timeticks(sys.get('uptime')),
        'modo':              dev.get('modo'),             # AP / Station
        'essid':             dev.get('essid'),            # SSID
        'frecuencia':        dev.get('frecuencia'),       # Cambium sí; Ubiquiti None (sin OID validado)
        'canal':             None,                        # sin OID validado → No disponible
        'ancho_mhz':         dev.get('ancho_mhz'),        # ancho de canal (Ubiquiti validado)
        'potencia_tx':       None,                        # sin OID validado → No disponible
        'antena':            dev.get('antena'),           # ganancia de antena (Ubiquiti validado)
        'estaciones_n':      dev.get('estaciones_n') if dev.get('estaciones_n') is not None else (len(estaciones) or None),
        'noise_floor':       dev.get('noise_floor'),
        'sys_descr':         descr,
        'sys_location':      sys.get('location'),
    }
    return {
        'ok': True,
        'fabricante_detectado': fab or None,
        'device': device,
        'estaciones': estaciones,
        'interfaces': interfaces,
        'lan': lan,
        'lan_alerta': lan_alerta,
    }


# ───────────────────────── Cruce con clientes de Pucará ─────────────────────────
def _norm_mac(m):
    return re.sub(r'[^0-9A-Fa-f]', '', m or '').upper()


def obs_metricas(est):
    """Texto de observaciones con las métricas extra de una estación normalizada.
    Cubre Ubiquiti (CCQ/airMAX) y Cambium (SNR/data_rate/LQ)."""
    partes = []
    if est.get('snr') is not None:                      # Cambium
        partes.append(f"SNR {est['snr']}dB")
    if est.get('ccq') is not None:                      # Ubiquiti
        partes.append(f"CCQ {est['ccq']}%")
    if est.get('airmax_quality') is not None or est.get('airmax_capacity') is not None:
        q = est.get('airmax_quality'); c = est.get('airmax_capacity')
        partes.append(f"airMAX Q{q if q is not None else '?'}/C{c if c is not None else '?'}")
    if est.get('link_quality') is not None:             # Cambium
        partes.append(f"LQ {est['link_quality']}%")
    if est.get('data_rate'):                            # Cambium ('300M')
        partes.append(str(est['data_rate']).strip())
    tx = est.get('tx_rate'); rx = est.get('rx_rate')    # Ubiquiti (bps)
    if tx or rx:
        partes.append(f"{(tx or 0)//1000000}/{(rx or 0)//1000000} Mbps")
    if est.get('distancia_m') is not None:
        partes.append(f"{est['distancia_m']} m")
    return ' · '.join(partes)


def guardar_estacion(con, equipo_id, est, cliente_id, ssid, fecha):
    """Guarda/actualiza una estación en la instantánea del AP (snmp_estaciones).

    Vive acá y no en app.py porque la usan los dos caminos de ingreso: el
    poller directo (snmp_poller) y el endpoint que recibe al agente remoto.
    Los campos salen del modelo normalizado, así que sirve igual para Ubiquiti
    (CCQ/airMAX) que para Cambium (SNR/distancia); lo que el fabricante no
    reporte queda NULL en vez de inventarse."""
    con.execute("""
        INSERT INTO snmp_estaciones(equipo_id, mac, cliente_id, nombre_ap, ip, rssi, snr,
                                    ccq, distancia_m, tx_rate, rx_rate, uptime_s,
                                    modelo_sm, firmware_sm, ssid, fecha)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(equipo_id, mac) DO UPDATE SET
            cliente_id=excluded.cliente_id, nombre_ap=excluded.nombre_ap, ip=excluded.ip,
            rssi=excluded.rssi, snr=excluded.snr, ccq=excluded.ccq,
            distancia_m=excluded.distancia_m, tx_rate=excluded.tx_rate,
            rx_rate=excluded.rx_rate, uptime_s=excluded.uptime_s,
            modelo_sm=excluded.modelo_sm, firmware_sm=excluded.firmware_sm,
            ssid=excluded.ssid, fecha=excluded.fecha
    """, (equipo_id, (est.get('mac') or '').upper(), cliente_id, est.get('nombre'),
          est.get('ip'), est.get('rssi'), est.get('snr'),
          est.get('ccq') if est.get('ccq') is not None else est.get('link_quality'),
          est.get('distancia_m'), est.get('tx_rate'), est.get('rx_rate'),
          est.get('uptime_s'), est.get('modelo_sm'), est.get('firmware_sm'),
          ssid, fecha))


def purgar_estaciones(con, equipo_id, macs_vistas):
    """Saca de la instantánea las estaciones que este AP dejó de reportar.
    Sin esto, un cliente que se pasó a otro AP queda colgando de los dos."""
    if macs_vistas:
        ph = ','.join('?' * len(macs_vistas))
        con.execute(f"DELETE FROM snmp_estaciones WHERE equipo_id=? AND UPPER(mac) NOT IN ({ph})",
                    [equipo_id] + [m.upper() for m in macs_vistas])
    else:
        con.execute("DELETE FROM snmp_estaciones WHERE equipo_id=?", (equipo_id,))


def marcar_torre_cliente(con, cliente_id, ap_id, torre_id, fecha):
    """Registra la torre FEHACIENTE de un cliente: la del AP donde SNMP lo vio.
    No pisa clientes.torre_id (proximidad/manual); escribe columnas separadas
    que el cálculo de producción usa vía COALESCE(torre_id_snmp, torre_id).
    Silencioso si las columnas no existen (base sin migrar)."""
    if not cliente_id or not torre_id:
        return
    try:
        con.execute("""UPDATE clientes SET torre_id_snmp=?, ap_snmp_id=?, torre_snmp_fecha=?
                       WHERE id=?""", (torre_id, ap_id, fecha, cliente_id))
    except Exception:
        pass


def procesar_evento(con, equipo_id, torre_id, tipo, activo, detalle='', interfaz=None, valor=None, fecha=None):
    """Motor de eventos con estados inicio/activo/recuperación (Fase 10).
    Evita crear una alerta nueva en cada ciclo mientras el problema continúe.
      - activo=True  → si NO hay un evento activo (mismo equipo/tipo/interfaz), lo crea.
                       Si ya hay uno activo, no hace nada (el problema sigue).
      - activo=False → si hay un evento activo, lo cierra (estado='recuperado', fin=fecha).
    Devuelve: 'inicio' | 'recuperado' | None (sin cambio).
    Silencioso si la tabla no existe (base sin migrar)."""
    fecha = fecha or datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    try:
        abierto = con.execute(
            """SELECT id FROM snmp_eventos
               WHERE equipo_id=? AND tipo=? AND estado='activo'
               AND (interfaz IS ? OR interfaz=?)
               ORDER BY id DESC LIMIT 1""",
            (equipo_id, tipo, interfaz, interfaz)).fetchone()
    except Exception:
        return None  # tabla no migrada

    if activo:
        if abierto:
            return None  # el problema continúa: no duplicar
        con.execute(
            """INSERT INTO snmp_eventos(equipo_id, torre_id, tipo, interfaz, detalle, valor,
               estado, inicio, creado) VALUES(?,?,?,?,?,?,?,?,?)""",
            (equipo_id, torre_id, tipo, interfaz, detalle, str(valor) if valor is not None else None,
             'activo', fecha, fecha))
        return 'inicio'
    else:
        if abierto:
            con.execute("UPDATE snmp_eventos SET estado='recuperado', fin=? WHERE id=?",
                        (fecha, abierto['id']))
            return 'recuperado'
        return None


def match_cliente(estacion, con):
    """Intenta vincular una estación SNMP con un cliente de Pucará.
    Orden de coincidencia: MAC → IP → nombre. Devuelve (cliente_id, criterio) o (None, None)."""
    mac = _norm_mac(estacion.get('mac'))
    ip = (estacion.get('ip') or '').strip()
    nombre = (estacion.get('nombre') or '').strip()

    if mac:
        # comparar sin separadores contra mac_address
        row = con.execute(
            "SELECT id FROM clientes WHERE REPLACE(REPLACE(UPPER(mac_address),':',''),'-','')=?",
            (mac,)).fetchone()
        if row:
            return row['id'], 'mac'
    if ip:
        row = con.execute("SELECT id FROM clientes WHERE ip_asignada=?", (ip,)).fetchone()
        if row:
            return row['id'], 'ip'
    if nombre:
        # coincidencia laxa por nombre (útil porque el AP suele traer el nombre del cliente)
        row = con.execute("SELECT id FROM clientes WHERE UPPER(nombre)=UPPER(?)",
                          (nombre,)).fetchone()
        if row:
            return row['id'], 'nombre'
    return None, None


# ───────────────────────── CLI de prueba ─────────────────────────
if __name__ == '__main__':
    if len(sys.argv) >= 2 and sys.argv[1] == '--parse' and len(sys.argv) >= 3:
        # Modo test: parsear un archivo de WALK ya capturado
        fab = sys.argv[3].lower() if len(sys.argv) > 3 else 'ubiquiti'
        adap = ADAPTADORES.get(fab, UbiquitiAirOS)
        with open(sys.argv[2], encoding='utf-8') as f:
            data = adap.parse_walk(f.read())
        print(json.dumps(data, indent=2, ensure_ascii=False))
    elif len(sys.argv) >= 2:
        ip = sys.argv[1]
        comm = sys.argv[2] if len(sys.argv) > 2 else 'public'
        fab = sys.argv[3].lower() if len(sys.argv) > 3 else 'ubiquiti'
        data = poll(ip, fab, comm)
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print('Uso:')
        print('  python3 snmp_wireless.py <ip> [community] [ubiquiti|cambium]   # WALK real')
        print('  python3 snmp_wireless.py --parse <archivo> [ubiquiti|cambium]  # parsear un WALK')
