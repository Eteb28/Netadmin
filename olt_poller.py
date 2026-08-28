#!/usr/bin/env python3
"""
olt_poller.py — Consulta por SNMP las OLT VSOL y guarda su estado en netadmin.db.
Parte del monitoreo de OLT (Fase 1) de Pucará.

Dos usos:
  1. Por CRON (todas las OLT con snmp_activo=1):
        python3 olt_poller.py
     Ejemplo de cron (cada 3 minutos):
        */3 * * * * cd /ruta/a/pucara && python3 olt_poller.py >> /tmp/olt_poller.log 2>&1

  2. Importado por app.py para pollear UNA OLT bajo demanda (botón "Actualizar").

  3. Diagnóstico de un equipo (no escribe en la base) — útil al dar de alta un
     modelo nuevo o si un dato sale vacío:
        python3 olt_poller.py --diag 192.168.10.247 [community] [version]

Requiere net-snmp:  sudo apt install snmp

OIDs confirmados en las VSOL V1600G1 / V1600G1B (enterprise .37950):
  sysUpTime  1.3.6.1.2.1.1.3.0
  sysDescr   1.3.6.1.2.1.1.1.0            (modelo)
  nombre     .37950.1.1.5.10.12.5.1.0
  firmware   .37950.1.1.5.10.12.5.4.0
  temp chasis .37950.1.1.5.10.12.4.0     (confirmado por snmpwalk, coincide con la web)
  sensores   .37950.1.1.5.10.13.1.1.X.Y  (col .2≈temperatura por PON, .3≈voltaje) [inferido]
  interfaces IF-MIB estándar (ifDescr / ifOperStatus)
"""
import os
import re
import json
import shutil
import sqlite3
import subprocess
import time
from datetime import datetime

DB = os.path.join(os.path.dirname(__file__), 'netadmin.db')

# OIDs estándar (iguales en TODOS los modelos)
OID_UPTIME   = '1.3.6.1.2.1.1.3.0'
OID_DESCR    = '1.3.6.1.2.1.1.1.0'
OID_SYSOBJID = '1.3.6.1.2.1.1.2.0'      # sólo informativo (se muestra en --diag)
OID_IFDESCR  = '1.3.6.1.2.1.2.2.1.2'
OID_IFOPER   = '1.3.6.1.2.1.2.2.1.8'
OID_IFNAME   = '1.3.6.1.2.1.31.1.1.1.1'

# ── Rama del fabricante (VSOL) ───────────────────────────────────────────────
# Verificado con walks reales de V1600G1 y V1600G1B: la rama .5.10.12 es COMÚN
# a los dos modelos (config del sistema), y .5.10.13 son los sensores de los
# SFP. Lo único que cambia entre modelos es .5.10.14.1.0, que trae el nombre
# del modelo como texto ("V1600G1B").
#
# HISTORIA DE UN BUG, para que no se repita: hubo una versión que tomaba
# .5.10.12.4.0 como "temperatura del chasis" porque en una G1 devolvía 39 y
# coincidía con lo que mostraba la web. Era casualidad: en una G1B ese mismo
# OID devuelve 87, y como 87 pasaba el control de "0 < v < 100" se mostraba
# como 87°C y dejaba la OLT en estado CRÍTICO. Ese OID NO es temperatura.
#
# La ÚNICA temperatura real que expone el equipo es la de cada SFP de PON, en
# .5.10.13.1.1.2.<pon> (valores medidos: 39-42°C). No hay sensor de chasis.
VSOL = '1.3.6.1.4.1.37950.1.1.5.10.'
OID_NOMBRE      = VSOL + '12.5.1.0'    # nombre configurado en la OLT
OID_FIRMWARE    = VSOL + '12.5.4.0'    # versión de firmware
OID_MAC         = VSOL + '12.5.7.0'    # MAC del chasis
OID_UPTIME_TXT  = VSOL + '12.5.8.0'    # uptime en texto ("245 Days 11 Hours…")
OID_SERIE       = VSOL + '12.5.11.0'   # número de serie
OID_MODELO_VSOL = VSOL + '14.1.0'      # "V1600G1B"
OID_SENSOR_BASE = VSOL + '13.1.1'      # col .2 = temp por PON, col .3 = voltaje


def _snmp_disponible():
    return shutil.which('snmpget') is not None and shutil.which('snmpbulkwalk') is not None


def snmp_get(ip, community, oid, version='2c', timeout=3):
    """Devuelve el valor de un OID (string), o None si no responde."""
    cmd = ['snmpget', '-v', version, '-c', community, '-t', str(timeout), '-r', '1', ip, oid]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 3)
        linea = p.stdout.strip()
        if not linea or 'No Such' in linea or 'Timeout' in linea or 'No Response' in linea:
            return None
        if '=' not in linea:
            return None
        val = linea.split('=', 1)[1].strip()
        # quitar prefijo de tipo (STRING:, INTEGER:, Timeticks:, Gauge32:, etc.)
        if ':' in val:
            val = val.split(':', 1)[1].strip()
        return val.strip().strip('"')
    except subprocess.TimeoutExpired:
        return None
    except Exception:
        return None


def _bulk(ip, community, oid, version='2c', cap=28, timeout=10):
    """Bulkwalk acotado. Devuelve {ultimo_indice: valor}."""
    cmd = ['snmpbulkwalk', '-On', '-v', version, '-c', community, '-t', '4', '-r', '1', ip, oid]
    res = {}
    try:
        import time
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        t0 = time.time()
        for linea in proc.stdout:
            linea = linea.strip()
            if linea and 'No Such' not in linea and 'End of MIB' not in linea and '=' in linea:
                oid_part, _, val = linea.partition('=')
                idx = oid_part.strip().split('.')[-1]
                if ':' in val:
                    val = val.split(':', 1)[1].strip()
                res[idx] = val.strip().strip('"')
            if len(res) >= cap or (time.time() - t0) > timeout:
                break
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except Exception:
            proc.kill()
    except Exception:
        pass
    return res


def _num(v):
    """Convierte '42.230' a float, tolerante."""
    if v is None:
        return None
    try:
        return float(str(v).strip())
    except ValueError:
        return None


def _uptime_seg(uptime_raw):
    """De '(958546072) 110 days, 22:37:40.72' saca los segundos (ticks/100)."""
    if not uptime_raw:
        return None
    m = re.search(r'\((\d+)\)', uptime_raw)
    if m:
        return int(m.group(1)) // 100
    return None


def leer_puertos(ip, community, version='2c', temps_pon=None):
    """Lee GE/GPON físicos (no ONU) con su estado up/down.

    Cada puerto incluye 'puerto': el número de PON extraído del nombre
    (ej. 'GPON0/3' → 3). Ese número es la clave con la que se cruza contra
    onu_senal.pon; sin él, el frontend no puede contar clientes por PON.
    'es_pon' distingue los GPON (que llevan ONU) de los GE de uplink.

    'temps_pon' (opcional) es el dict {puerto_str: temp} del sensor SFP de
    cada PON (ver poll_olt): aunque esa temperatura NO es la del chasis, es
    justamente la del módulo óptico de ese PON puntual, así que vale la pena
    mostrarla puerto por puerto (se guarda como 'temp_sfp' en cada puerto)."""
    descrs = _bulk(ip, community, OID_IFDESCR, version, cap=64, timeout=10)
    estados = _bulk(ip, community, OID_IFOPER, version, cap=64, timeout=10)
    puertos = []
    for idx, nombre in descrs.items():
        n = nombre.strip()
        # solo puertos físicos del chasis: GE0/x y GPON0/x, NO las interfaces de ONU
        if ('GE' in n or 'GPON' in n) and 'ONU' not in n:
            st = estados.get(idx, '')
            es_pon = 'GPON' in n.upper()
            # Número de PON: se toma del patrón GPON<slot>/<pon>, NO del "último
            # número del nombre". Los puertos se pueden renombrar desde la OLT
            # (en la G1B hay uno llamado "GPON0/1 Prueba"): con la regla vieja,
            # un puerto llamado "GPON0/3 Torre5" se leía como PON 5 y los
            # clientes se contaban contra el PON equivocado.
            num = None
            mm = re.search(r'GPON\s*\d+\s*/\s*(\d+)', n, re.I)
            if mm:
                num = int(mm.group(1))
            else:
                mm = re.search(r'GE\s*\d+\s*/\s*(\d+)', n, re.I)
                if mm:
                    num = int(mm.group(1))
            temp_sfp = None
            if es_pon and num is not None and temps_pon:
                temp_sfp = _num(temps_pon.get(str(num)))
            puertos.append({'nombre': n, 'up': st == '1',
                            'puerto': num, 'es_pon': es_pon, 'temp_sfp': temp_sfp})
    return puertos


# Nombre de interfaz de una ONU, tal como lo arma la OLT:
#   "GPON01ONU1 GPON0/1:1_030427_CDO1_NAP2"
# Del tramo posterior al espacio salen PON, ONU y —cuando el instalador siguió
# la convención— el nº de cliente, el CDO y la NAP.
_RE_ONU = re.compile(r'GPON\s*(\d+)\s*/\s*(\d+)\s*:\s*(\d+)(?:_(.*))?$', re.I)


def parsear_nombre_onu(nombre):
    """Extrae {pon, onu, nro_cliente, cdo, nap} del nombre de la interfaz ONU.

    Devuelve None si la interfaz no es una ONU. Los campos que no vengan en el
    nombre quedan en None: la convención '<cliente>_CDO<n>_NAP<n>' la escriben
    los técnicos a mano, así que NO se puede dar por garantizada (hay ONUs con
    'Admini' u otro texto en lugar del número de cliente)."""
    if not nombre or 'ONU' not in nombre.upper():
        return None
    m = _RE_ONU.search(nombre.strip())
    if not m:
        return None
    pon, onu, resto = int(m.group(2)), int(m.group(3)), (m.group(4) or '')
    datos = {'pon': pon, 'onu': onu, 'nro_cliente': None, 'cdo': None, 'nap': None}
    for tok in [t for t in resto.split('_') if t]:
        tu = tok.upper()
        if tu.startswith('CDO'):
            datos['cdo'] = tok
        elif tu.startswith('NAP'):
            datos['nap'] = tok
        elif datos['nro_cliente'] is None:
            datos['nro_cliente'] = tok
    return datos


def leer_onus_ifmib(ip, community, version='2c'):
    """Inventario de ONUs leído de la IF-MIB ESTÁNDAR (no de la rama VSOL).

    Por qué importa: la rama del fabricante cambia entre modelos (12 vs 14) y
    puede no estar disponible, pero la IF-MIB está en todos. De acá salen, para
    cada ONU: en qué PON está, su número, si está up/down y —del nombre— el
    cliente, el CDO y la NAP con los que quedó rotulada en la OLT.
    Eso permite cruzar lo que dice la OLT contra lo cargado en Pucará."""
    descrs = _bulk(ip, community, OID_IFDESCR, version, cap=4000, timeout=60)
    estados = _bulk(ip, community, OID_IFOPER, version, cap=4000, timeout=60)
    onus = []
    for idx, nombre in descrs.items():
        d = parsear_nombre_onu(nombre)
        if not d:
            continue
        d['ifindex'] = idx
        d['nombre_if'] = nombre.strip()
        d['online'] = 1 if estados.get(idx, '') == '1' else 0
        onus.append(d)
    return onus


def poll_olt(ip, community='public', version='2c'):
    """Consulta una OLT. Devuelve dict de métricas. online=0 si no responde."""
    m = {'online': 0, 'ip': ip}
    if not ip:
        return m
    uptime = snmp_get(ip, community, OID_UPTIME, version)
    if uptime is None:
        return m  # no responde → offline
    m['online'] = 1
    m['uptime_seg'] = _uptime_seg(uptime)
    m['modelo'] = snmp_get(ip, community, OID_DESCR, version)
    # ── Temperatura ──────────────────────────────────────────────────────────
    # La única temperatura que expone la OLT es la de cada SFP de PON
    # (.5.10.13.1.1.2.<pon>). NO hay sensor de chasis: ver el comentario largo
    # arriba, donde está explicado el OID que parecía serlo y no lo era.
    # Se reporta el SFP más caliente como termómetro del equipo, y además cada
    # PON por separado (leer_puertos), que es lo que sirve para ubicar cuál se
    # está calentando.
    col_temp = {}
    try:
        col_temp, _ = _bulk_optica(ip, community, OID_SENSOR_BASE + '.2', version)
    except Exception:
        pass
    temps_sfp = [_num(x) for x in col_temp.values() if _num(x) is not None]
    if temps_sfp:
        m['temperatura'] = round(max(temps_sfp), 2)   # el SFP más caliente
        m['temp_fuente'] = 'sfp'                      # umbrales de SFP (ver _salud_olt)
    else:
        m['temperatura'] = None
        m['temp_fuente'] = None
    m['temp_sfp_max'] = round(max(temps_sfp), 2) if temps_sfp else None
    m['temp_sfp_prom'] = round(sum(temps_sfp) / len(temps_sfp), 2) if temps_sfp else None
    col_volt = {}
    try:
        col_volt, _ = _bulk_optica(ip, community, OID_SENSOR_BASE + '.3', version)
    except Exception:
        pass
    volts = [_num(x) for x in col_volt.values() if _num(x) is not None]
    m['voltaje'] = round(sum(volts) / len(volts), 3) if volts else None
    m['nombre_olt'] = snmp_get(ip, community, OID_NOMBRE, version)
    m['firmware'] = snmp_get(ip, community, OID_FIRMWARE, version)
    # Datos de inventario que la OLT ya tiene y antes no se leían
    m['modelo_vsol'] = snmp_get(ip, community, OID_MODELO_VSOL, version)
    m['mac'] = snmp_get(ip, community, OID_MAC, version)
    m['serie'] = snmp_get(ip, community, OID_SERIE, version)
    # col_temp trae la temperatura del SFP de cada PON (índice = n° de PON):
    # se la pasamos para que quede guardada puerto por puerto, no solo el
    # máximo/promedio global.
    m['puertos'] = leer_puertos(ip, community, version, temps_pon=col_temp)
    return m


def actualizar_estado(con, olt_id, m):
    """Guarda el resultado del poll en la fila de la OLT."""
    ahora = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    con.execute("""
        UPDATE olts SET
          last_check=?, online=?, uptime_seg=?, firmware_snmp=?,
          temperatura=?, voltaje=?, puertos_json=?,
          temp_fuente=?, temp_sfp_max=?, temp_sfp_prom=?
        WHERE id=?
    """, (
        ahora, m.get('online', 0), m.get('uptime_seg'), m.get('firmware'),
        m.get('temperatura'), m.get('voltaje'),
        json.dumps(m.get('puertos', [])),
        m.get('temp_fuente'), m.get('temp_sfp_max'), m.get('temp_sfp_prom'), olt_id
    ))
    con.commit()


def pollear_una(con, olt_row):
    """Pollea una OLT (dict/Row de la base) y guarda. Devuelve las métricas."""
    ip = olt_row['ip_red'] or olt_row['ip_remota']
    comm = (olt_row['community'] or 'public')
    ver = (olt_row['version_snmp'] or '2c')
    m = poll_olt(ip, comm, ver)
    actualizar_estado(con, olt_row['id'], m)
    return m


def main():
    if not _snmp_disponible():
        print("✗ Falta net-snmp. Instalá: sudo apt install snmp")
        return
    con = sqlite3.connect(DB, timeout=30)
    con.row_factory = sqlite3.Row
    olts = con.execute("SELECT * FROM olts WHERE snmp_activo=1 AND activa=1").fetchall()
    if not olts:
        print("No hay OLT con SNMP activo. Activá el monitoreo en cada OLT desde la UI.")
        con.close()
        return
    print(f"Polleando {len(olts)} OLT…")
    olts_confiables = set()   # OLTs cuya lectura óptica fue COMPLETA (sólo esas alertan)
    lecturas_incidentes = []  # insumo del motor de incidentes (fase 4)
    lectura_global_completa = True
    for o in olts:
        # Cada OLT va en su propio try: si una falla (timeout, IP caída, SNMP raro),
        # NO debe cortar el ciclo y dejar sin sondear a las que siguen. Ese era el
        # motivo de que unas OLT tuvieran datos de un día y otras de otro.
        try:
            m = pollear_una(con, o)
        except Exception as e:
            print(f"  [ERROR] {o['nombre']} ({o['ip_red'] or o['ip_remota']}): {e}")
            continue
        estado = 'ONLINE' if m.get('online') else 'OFFLINE'
        extra = ''
        if m.get('online'):
            up = m.get('uptime_seg')
            dias = up // 86400 if up else '?'
            extra = f"up {dias}d, temp {m.get('temperatura')}°C, {len(m.get('puertos', []))} puertos"
        print(f"  [{estado}] {o['nombre']} ({o['ip_red'] or o['ip_remota']}) {extra}")
        # Fase 2: señal óptica de las ONU (si la OLT respondió)
        if m.get('online'):
            try:
                n, completa = pollear_optica(con, o, lecturas_incidentes)
                if n:
                    print(f"         ↳ {n} ONU con señal óptica registrada"
                          + ("" if completa else "  [LECTURA PARCIAL]"))
                if completa:
                    olts_confiables.add(o['id'])
                else:
                    # Basta con que UNA OLT venga truncada para no concluir
                    # caídas en este ciclo: el motor sólo procesa recuperaciones.
                    lectura_global_completa = False
            except Exception as e:
                print(f"         ↳ (óptica falló: {e})")
                lectura_global_completa = False
            # Inventario por IF-MIB: va aparte de la óptica a propósito, para
            # que siga funcionando aunque la rama del fabricante falle.
            try:
                n_if = sincronizar_onus_ifmib(con, o)
                if n_if:
                    print(f"         ↳ {n_if} ONU rotuladas leídas por IF-MIB (CDO/NAP)")
            except Exception as e:
                print(f"         ↳ (inventario IF-MIB falló: {e})")
    prune_historico(con, dias=90)
    # Detección de alertas de infraestructura (NAP/PON caídos) + Telegram.
    # SÓLO sobre OLTs cuya lectura óptica fue completa: una lectura truncada
    # marcaba PONs enteros como caídos y disparaba Telegram en masa.
    try:
        n_alertas = detectar_alertas_infra(con, olts_confiables)
        if n_alertas:
            print(f"⚠ {n_alertas} alerta(s) de infraestructura activa(s)")
    except Exception as e:
        print(f"(detección de alertas falló: {e})")

    # Motor unificado de incidentes (fase 4). Corre EN PARALELO al sistema de
    # alertas de arriba durante la transición: así se puede comparar lo que
    # detecta cada uno sobre los mismos datos antes de apagar el viejo.
    # Va en su propio try: si falla, el poller no debe dejar de guardar señales.
    try:
        from pucara.adaptadores.incidentes_olt import procesar_sondeo_olt
        r = procesar_sondeo_olt(lecturas_incidentes, lectura_global_completa)
        if any(r.get(k) for k in ('nuevos', 'masivos', 'recuperados', 'cerrados')):
            print(f"⚡ Incidentes: {r['nuevos']} nuevos, {r['masivos']} masivos, "
                  f"{r['recuperados']} recuperados, {r['cerrados']} cerrados"
                  + ("  [lectura parcial: no se abrieron incidentes]"
                     if r.get('omitido_por_lectura_parcial') else ""))
    except Exception as e:
        print(f"(motor de incidentes no procesó este ciclo: {e})")

    con.close()
    print("Listo.")


# ══ Fase 2: señal óptica de ONU ══════════════════════════════════
# Rama óptica (dump Observium V1600G1B): .37950.1.1.6.1.1.3.1.X
#   .3=temp  .4=voltaje  .6=TX power  .7=RX power  (valores en dBm directo, string)
OID_OPT_RX   = '1.3.6.1.4.1.37950.1.1.6.1.1.3.1.7'
OID_OPT_TX   = '1.3.6.1.4.1.37950.1.1.6.1.1.3.1.6'
OID_OPT_TEMP = '1.3.6.1.4.1.37950.1.1.6.1.1.3.1.3'
OID_OPT_VOLT = '1.3.6.1.4.1.37950.1.1.6.1.1.3.1.4'


def _bulk_optica(ip, community, oid_base, version='2c', cap=4000, timeout=180):
    """Baja una columna óptica. Devuelve (dict {'pon.onu': valor_str}, truncado_bool).

    IMPORTANTE — por qué cap y timeout son altos:
    una OLT con 16 PON x 128 ONU son >2000 filas por columna. Con los valores
    viejos (cap=600, timeout=30) la lectura se cortaba a la mitad y las ONU no
    leídas quedaban marcadas como 'sin señal', disparando alertas masivas falsas.
    'truncado' avisa que la lectura quedó incompleta para NO sacar conclusiones."""
    cmd = ['snmpbulkwalk', '-On', '-v', version, '-c', community, '-t', '5', '-r', '1', ip, oid_base]
    res = {}
    truncado = False
    prefijo = '.' + oid_base + '.'
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        t0 = time.time()
        for linea in proc.stdout:
            linea = linea.strip()
            if linea and '=' in linea and 'No Such' not in linea and 'End of MIB' not in linea:
                oid_part, _, val = linea.partition('=')
                oid_part = oid_part.strip()
                if oid_part.startswith(prefijo):
                    idx = oid_part[len(prefijo):]           # ej "1.5"
                    if ':' in val:
                        val = val.split(':', 1)[1].strip()
                    res[idx] = val.strip().strip('"')
                elif res:
                    break  # salimos de la columna (fin natural, no truncado)
            if len(res) >= cap or (time.time() - t0) > timeout:
                truncado = True          # cortamos nosotros: lectura incompleta
                break
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except Exception:
            proc.kill()
    except Exception:
        truncado = True                  # error a mitad de camino
    return res, truncado


def _dbm(v):
    """Convierte el string óptico a float dBm. Limpia sufijos tipo '(dBm)'.
    'NULL', 'N/A' o vacío → None (ONU sin señal). Sirve para G1 y G1B."""
    if not v:
        return None
    s = str(v).strip()
    if s.upper() in ('NULL', 'N/A', '--', ''):
        return None
    # Quitar sufijos y unidades: "-30.000(dBm)" → "-30.000"
    import re as _re
    m = _re.search(r'-?\d+\.?\d*', s)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None




def leer_mapeo_onu(ip, community, version='2c'):
    """Mapea el índice (pon,onu) al código de cliente, leyendo los nombres de
    interfaz IF-MIB (ej 'GPON01ONU2 GPON0/1:2_035994_CDO1_NAP1')."""
    descrs = _bulk(ip, community, OID_IFDESCR, version, cap=800, timeout=30)
    mapeo = {}
    for _idx, nombre in descrs.items():
        m = re.search(r'GPON\d+/(\d+):(\d+)_(\d+)', nombre or '')
        if m:
            pon, onu, codigo = m.group(1), m.group(2), m.group(3)
            mapeo[f"{pon}.{onu}"] = {'codigo': codigo, 'interfaz': nombre.strip()}
    return mapeo


OID_ONU_SERIAL = '1.3.6.1.4.1.37950.1.1.6.1.2.1.1.3'  # serial de ONU, índice pon.onu

def leer_seriales(ip, community, version='2c'):
    """Devuelve {idx: serial} (idx='pon.onu'), ej '7.1' -> 'MONU00453581'.
    _bulk_optica ahora devuelve (dict, truncado): acá sólo interesa el dict."""
    seriales, _trunc = _bulk_optica(ip, community, OID_ONU_SERIAL, version)
    return seriales


def leer_optica(ip, community, version='2c'):
    """Devuelve (onus, rx_completa) donde onus = {idx: {rx,tx,temp,volt}}, idx='pon.onu'.

    La clave 'rx' SÓLO existe si la ONU apareció en el walk de RX. Eso permite
    distinguir 'la OLT dice que no tiene señal' (rx presente y None) de
    'no alcanzamos a leerla' (rx ausente) — antes se confundían y las no leídas
    se marcaban como caídas."""
    rx, rx_trunc = _bulk_optica(ip, community, OID_OPT_RX, version)
    tx, _ = _bulk_optica(ip, community, OID_OPT_TX, version)
    tmp, _ = _bulk_optica(ip, community, OID_OPT_TEMP, version)
    vlt, _ = _bulk_optica(ip, community, OID_OPT_VOLT, version)
    onus = {}
    for idx, v in rx.items():
        onus.setdefault(idx, {})['rx'] = _dbm(v)     # la clave existe = sí se leyó
    for idx, v in tx.items():
        onus.setdefault(idx, {})['tx'] = _dbm(v)
    for idx, v in tmp.items():
        onus.setdefault(idx, {})['temp'] = _dbm(v)
    for idx, v in vlt.items():
        onus.setdefault(idx, {})['volt'] = _dbm(v)
    return onus, (not rx_trunc)


def pollear_optica(con, olt_row, lecturas=None):
    """Lee la óptica de todas las ONU de una OLT, las cruza con el cliente
    y las guarda en onu_senal. Devuelve cuántas ONU se guardaron.

    Si se pasa `lecturas`, va acumulando ahí un dict por ONU para que el motor
    de incidentes lo procese después (ver pucara/adaptadores/incidentes_olt.py).
    """
    ip = olt_row['ip_red'] or olt_row['ip_remota']
    comm = olt_row['community'] or 'public'
    ver = olt_row['version_snmp'] or '2c'
    if not ip:
        return 0, True   # sin IP: nada que leer, pero no es "incompleto"
    optica, rx_completa = leer_optica(ip, comm, ver)
    if not optica:
        # No se leyó ninguna ONU. Devolver tupla (main hace n, completa = ...).
        # completa=False para NO evaluar alertas sobre una OLT que no dio datos.
        return 0, False
    if not rx_completa:
        print(f"         ⚠ Lectura óptica INCOMPLETA en {olt_row['nombre']}: "
              f"no se actualiza el estado online/offline (evita alertas falsas)")
    mapeo = leer_mapeo_onu(ip, comm, ver)
    seriales = leer_seriales(ip, comm, ver)
    ahora = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    n = 0
    for idx, o in optica.items():
        partes = idx.split('.')
        if len(partes) != 2:
            continue
        pon, onu = partes[0], partes[1]
        info = mapeo.get(idx, {})
        codigo = info.get('codigo')
        interfaz = info.get('interfaz')
        rx = o.get('rx')
        # Sólo se concluye online/offline si la ONU apareció en el walk de RX
        # y la lectura fue completa. Si no, se conserva el estado anterior:
        # "no lo pude leer" NO es lo mismo que "está caído".
        leida = ('rx' in o) and rx_completa
        online = (1 if rx is not None else 0) if leida else None
        serial = (seriales.get(idx) or '').strip() or None
        con.execute("""
            INSERT INTO onu_senal(olt_id,pon,onu,nro_cliente,interfaz,serial_onu,rx_power,tx_power,temperatura,voltaje,online,last_check)
            VALUES(?,?,?,?,?,?,?,?,?,?,COALESCE(?,0),?)
            ON CONFLICT(olt_id,pon,onu) DO UPDATE SET
              nro_cliente=excluded.nro_cliente, interfaz=excluded.interfaz, serial_onu=excluded.serial_onu,
              rx_power=CASE WHEN ? IS NULL THEN onu_senal.rx_power ELSE excluded.rx_power END,
              tx_power=excluded.tx_power,
              temperatura=excluded.temperatura, voltaje=excluded.voltaje,
              online=COALESCE(?, onu_senal.online),
              last_check=excluded.last_check
        """, (olt_row['id'], int(pon), int(onu), codigo, interfaz, serial,
              rx, o.get('tx'), o.get('temp'), o.get('volt'), online, ahora,
              online, online))
        # Insumo del motor de incidentes: sólo las ONU realmente leídas. Una
        # ONU que no apareció en el walk no se reporta como caída (es el mismo
        # criterio que se aplica arriba para no pisar el estado online).
        if lecturas is not None and leida:
            lecturas.append({
                'olt_id': olt_row['id'], 'pon': int(pon), 'onu': int(onu),
                'online': bool(online), 'nro_cliente': codigo,
            })
        # Histórico: registrar la lectura (solo si hay cliente y señal)
        if codigo and rx is not None:
            con.execute("""INSERT INTO onu_senal_hist(nro_cliente,olt_id,pon,onu,rx_power,tx_power,temperatura,fecha)
                           VALUES(?,?,?,?,?,?,?,?)""",
                        (codigo, olt_row['id'], int(pon), int(onu), rx, o.get('tx'), o.get('temp'), ahora))
        n += 1
    # ── Purga: las ONU que ya NO están en la OLT deben desaparecer de la tabla.
    # Sin esto quedan filas fantasma (clientes dados de baja que ya se borraron
    # del equipo siguen figurando en alertas y en la lista de limpieza).
    # Se protege contra lecturas parciales: si trajimos muy poco respecto de lo
    # que había guardado, NO se purga (probable timeout o error de SNMP).
    vistos = set()
    for idx in optica.keys():
        p = idx.split('.')
        if len(p) == 2:
            try:
                vistos.add((int(p[0]), int(p[1])))
            except ValueError:
                pass
    if vistos and rx_completa:   # nunca purgar sobre una lectura truncada
        previas = con.execute("SELECT pon, onu FROM onu_senal WHERE olt_id=?", (olt_row['id'],)).fetchall()
        if not previas or len(vistos) >= len(previas) * 0.6:
            sobrantes = [(p['pon'], p['onu']) for p in previas if (p['pon'], p['onu']) not in vistos]
            for pon_v, onu_v in sobrantes:
                con.execute("DELETE FROM onu_senal WHERE olt_id=? AND pon=? AND onu=?",
                            (olt_row['id'], pon_v, onu_v))
            if sobrantes:
                print(f"         ↳ {len(sobrantes)} ONU dadas de baja en la OLT: eliminadas del registro")
    con.commit()
    return n, rx_completa


def prune_historico(con, dias=90):
    """Borra histórico de señal más viejo que 'dias' (evita que la tabla crezca sin fin)."""
    try:
        con.execute("DELETE FROM onu_senal_hist WHERE fecha < datetime('now', ?)", (f'-{dias} days',))
        con.commit()
    except Exception:
        pass


# ══ Detección de alertas de infraestructura (NAP/PON caídos) ═════
def _cfg(con, clave, default=''):
    """Lee la tabla configuracion."""
    try:
        r = con.execute("SELECT valor FROM configuracion WHERE clave=?", (clave,)).fetchone()
        return (r['valor'] if r else default) or default
    except Exception:
        return default


def _telegram(con, mensaje):
    """Envía por Telegram usando el bot configurado en la base."""
    import urllib.request, urllib.parse
    token = _cfg(con, 'telegram_token', '').strip()
    chat = _cfg(con, 'telegram_chat_id', '').strip()
    if not token or not chat:
        return False
    try:
        data = urllib.parse.urlencode({'chat_id': chat, 'text': mensaje, 'parse_mode': 'HTML'}).encode()
        req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return b'"ok":true' in resp.read()
    except Exception:
        return False


def _crear_incidencia_auto(con, titulo, n, detalle, nap_nombre=None, olt_nombre=None):
    """Crea una incidencia crítica si no hay ya una abierta con ese título."""
    try:
        ya = con.execute("SELECT id FROM incidencias WHERE titulo=? AND estado NOT IN ('cerrada','resuelta')",
                         (titulo,)).fetchone()
        if ya:
            return
        con.execute("""INSERT INTO incidencias(titulo,tipo,descripcion,afectados,estado,prioridad,creado_por,nap_nombre,olt_nombre)
                       VALUES(?,?,?,?, 'abierta', 'critica', 'sistema', ?, ?)""",
                    (titulo, 'infraestructura', detalle, str(n), nap_nombre, olt_nombre))
    except Exception:
        pass


def _upsert_alerta(con, tipo, ref, titulo, sev, clientes, ahora, activas, nap=None, olt=None):
    activas.add(ref)
    cj = json.dumps([{'cod': c['cod'], 'nombre': c['nombre']} for c in clientes])
    n = len(clientes)
    prev = con.execute("SELECT estado FROM alertas_infra WHERE referencia=?", (ref,)).fetchone()
    if prev and prev['estado'] == 'activa':
        con.execute("UPDATE alertas_infra SET titulo=?, severidad=?, clientes_json=?, n_afectados=? WHERE referencia=?",
                    (titulo, sev, cj, n, ref))
        return
    # Nueva o reactivada
    con.execute("""INSERT INTO alertas_infra(tipo,referencia,titulo,severidad,clientes_json,n_afectados,estado,notificada,creada)
                   VALUES(?,?,?,?,?,?,'activa',0,?)
                   ON CONFLICT(referencia) DO UPDATE SET estado='activa', titulo=excluded.titulo,
                     severidad=excluded.severidad, clientes_json=excluded.clientes_json,
                     n_afectados=excluded.n_afectados, notificada=0, creada=excluded.creada, resuelta_at=NULL""",
                (tipo, ref, titulo, sev, cj, n, ahora))
    # Notificar SOLO las críticas (sin señal): Telegram + incidencia
    if sev == 'sin_senal':
        lista = ', '.join(f"{c['nombre']} (#{c['cod']})" for c in clientes[:12])
        if n > 12:
            lista += f" y {n-12} más"
        _telegram(con, f"🔴 <b>{titulo}</b>\n{n} cliente(s) sin señal — posible corte de fibra\n👥 {lista}")
        _crear_incidencia_auto(con, titulo, n, f"Detección automática: {titulo}. {n} clientes sin señal.", nap, olt)
        con.execute("UPDATE alertas_infra SET notificada=1 WHERE referencia=?", (ref,))


def detectar_alertas_infra(con, olts_confiables=None):
    """Detecta NAPs/PONs donde TODOS los clientes activos están sin señal (crítico)
    o en señal baja/crítica (aviso). Dispara Telegram+incidencia para los sin señal,
    con dedup, y resuelve las alertas que ya no aplican.

    olts_confiables: set de olt_id cuya lectura óptica fue COMPLETA en este ciclo.
    Si se pasa, sólo se evalúan esas OLT. Una lectura truncada dejaba ONU sin leer
    que figuraban 'sin señal' y disparaban alertas masivas falsas.
    Además se exige que el dato sea FRESCO (last_check reciente): una ONU que no
    se pudo leer hace horas no es evidencia de que el PON esté caído."""
    ahora = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    activas = set()
    # Ventana de frescura: sólo datos actualizados en las últimas 2 horas
    FRESCO = "s.last_check >= datetime('now','localtime','-2 hours')"
    if olts_confiables is not None:
        if not olts_confiables:
            print("   (sin OLT con lectura completa: no se evalúan alertas este ciclo)")
            return 0
        ids = ','.join(str(int(i)) for i in olts_confiables)
        FILTRO_OLT = f" AND s.olt_id IN ({ids})"
    else:
        FILTRO_OLT = ""

    # --- NAPs: agrupar clientes ACTIVOS con señal por NAP ---
    naps = {}
    for r in con.execute(f"""
        SELECT c.nap AS nap, c.nombre AS nombre, c.nro_cliente AS cod,
               s.rx_power AS rx, s.online AS online
        FROM onu_senal s JOIN clientes c ON c.nro_cliente = s.nro_cliente
        WHERE c.estado='activo' AND c.nap IS NOT NULL AND TRIM(c.nap) != ''
          AND {FRESCO}{FILTRO_OLT}
    """).fetchall():
        naps.setdefault(r['nap'], []).append(r)
    for nap, cls in naps.items():
        if len(cls) < 2:
            continue  # con 1 cliente no se puede concluir corte de NAP
        todos_sin = all(c['online'] == 0 for c in cls)
        todos_bajos = (not todos_sin) and all(
            (c['online'] == 0) or (c['rx'] is not None and c['rx'] < -26) for c in cls)
        if todos_sin:
            _upsert_alerta(con, 'nap', f'nap:{nap}', f'NAP {nap} sin señal', 'sin_senal', cls, ahora, activas, nap=nap)
        elif todos_bajos:
            _upsert_alerta(con, 'nap', f'nap:{nap}', f'NAP {nap} con señal baja/crítica', 'baja', cls, ahora, activas, nap=nap)

    # --- PONs: agrupar clientes ACTIVOS por (OLT, PON) ---
    pons = {}
    for r in con.execute(f"""
        SELECT s.olt_id AS olt_id, s.pon AS pon, o.nombre AS olt_nombre,
               c.nombre AS nombre, c.nro_cliente AS cod, s.online AS online
        FROM onu_senal s JOIN clientes c ON c.nro_cliente = s.nro_cliente
        LEFT JOIN olts o ON o.id = s.olt_id
        WHERE c.estado='activo' AND {FRESCO}{FILTRO_OLT}
    """).fetchall():
        pons.setdefault((r['olt_id'], r['pon'], r['olt_nombre']), []).append(r)
    for (olt_id, pon, olt_nombre), cls in pons.items():
        if len(cls) < 2:
            continue
        if all(c['online'] == 0 for c in cls):
            _upsert_alerta(con, 'pon', f'pon:{olt_id}:{pon}',
                           f'{olt_nombre or "OLT"} · PON{pon} sin señal', 'sin_senal', cls, ahora, activas, olt=olt_nombre)

    # Resolver alertas que ya no están activas
    for row in con.execute("SELECT referencia FROM alertas_infra WHERE estado='activa'").fetchall():
        if row['referencia'] not in activas:
            con.execute("UPDATE alertas_infra SET estado='resuelta', resuelta_at=? WHERE referencia=?",
                        (ahora, row['referencia']))
    con.commit()
    return len(activas)


def sincronizar_onus_ifmib(con, olt_row):
    """Completa onu_senal con lo que la OLT rotula en cada interfaz de ONU.

    Complementa (no reemplaza) la lectura óptica: la óptica vive en la rama del
    fabricante y puede no estar disponible según el modelo, mientras que esto
    sale de la IF-MIB estándar y anda siempre. Aporta dos cosas que la óptica
    no da: el CDO y la NAP con los que la ONU está rotulada EN LA OLT, que es
    contra lo que después se puede auditar la carga de Pucará.

    No pisa el estado online que calcula la óptica salvo que la ONU no exista
    todavía en la tabla: 'la interfaz está down' y 'la ONU no tiene señal' son
    cosas distintas y la óptica es la fuente más precisa para eso."""
    ip = olt_row['ip_red'] or olt_row['ip_remota']
    comm = olt_row['community'] or 'public'
    ver = olt_row['version_snmp'] or '2c'
    if not ip:
        return 0
    onus = leer_onus_ifmib(ip, comm, ver)
    if not onus:
        return 0
    ahora = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    for o in onus:
        con.execute("""
            INSERT INTO onu_senal(olt_id,pon,onu,nro_cliente,interfaz,cdo_olt,nap_olt,online,last_check)
            VALUES(?,?,?,?,?,?,?,?,?)
            ON CONFLICT(olt_id,pon,onu) DO UPDATE SET
              interfaz=excluded.interfaz,
              cdo_olt=excluded.cdo_olt,
              nap_olt=excluded.nap_olt,
              nro_cliente=COALESCE(onu_senal.nro_cliente, excluded.nro_cliente),
              last_check=excluded.last_check
        """, (olt_row['id'], o['pon'], o['onu'], o['nro_cliente'], o['nombre_if'],
              o['cdo'], o['nap'], o['online'], ahora))
    con.commit()
    return len(onus)


def diagnostico(ip, community='public', version='2c'):
    """Imprime QUÉ ve el poller en una OLT concreta, sin escribir en la base.

    Sirve para dar de alta un modelo nuevo (o entender por qué un dato sale
    vacío) sin tener que adivinar: muestra el valor crudo de cada OID que usa
    el poller, para poder contrastarlo contra lo que muestra la web del equipo.

        python3 olt_poller.py --diag 192.168.10.247
    """
    print(f"── Diagnóstico SNMP de {ip} ──")
    descr = snmp_get(ip, community, OID_DESCR, version)
    print(f"  sysDescr      : {descr}")
    print(f"  sysObjectID   : {snmp_get(ip, community, OID_SYSOBJID, version)}")
    if descr is None:
        print("  ✗ La OLT no respondió SNMP. Revisá IP, community y versión.")
        return 1
    for etiqueta, oid in (('Modelo (VSOL)', OID_MODELO_VSOL), ('Nombre', OID_NOMBRE),
                          ('Firmware', OID_FIRMWARE), ('MAC', OID_MAC),
                          ('N° de serie', OID_SERIE), ('Uptime (texto)', OID_UPTIME_TXT)):
        print(f"  {etiqueta:14}: {snmp_get(ip, community, oid, version)!r}   [{oid}]")
    try:
        col, _ = _bulk_optica(ip, community, OID_SENSOR_BASE + '.2', version)
        if col:
            print(f"  Temperatura por PON ({OID_SENSOR_BASE}.2):")
            for pon in sorted(col, key=lambda x: (len(x), x)):
                print(f"      PON {pon}: {col[pon]} °C")
            nums = [_num(v) for v in col.values() if _num(v) is not None]
            if nums:
                print(f"      → se reporta el más caliente: {max(nums)} °C")
        else:
            print(f"  Temperatura por PON: (vacío) — la OLT no expone {OID_SENSOR_BASE}.2")
    except Exception as e:
        print(f"  Temperatura por PON: error {e}")
    puertos = leer_puertos(ip, community, version)
    print(f"  Puertos físicos: {len(puertos)}  "
          f"(PON: {sum(1 for p in puertos if p['es_pon'])})")
    onus = leer_onus_ifmib(ip, community, version)
    con_cli = sum(1 for o in onus if o['nro_cliente'])
    con_nap = sum(1 for o in onus if o['nap'])
    print(f"  ONUs por IF-MIB: {len(onus)}  "
          f"(con nº de cliente en el nombre: {con_cli} · con NAP: {con_nap})")
    for o in onus[:3]:
        print(f"    PON{o['pon']}/{o['onu']} online={o['online']} "
              f"cliente={o['nro_cliente']} cdo={o['cdo']} nap={o['nap']}")
    return 0


if __name__ == '__main__':
    import sys as _sys
    if '--diag' in _sys.argv:
        i = _sys.argv.index('--diag')
        _ip = _sys.argv[i + 1] if len(_sys.argv) > i + 1 else None
        if not _ip:
            print("Uso: python3 olt_poller.py --diag <IP> [community] [version]")
            _sys.exit(2)
        _comm = _sys.argv[i + 2] if len(_sys.argv) > i + 2 else 'public'
        _ver = _sys.argv[i + 3] if len(_sys.argv) > i + 3 else '2c'
        _sys.exit(diagnostico(_ip, _comm, _ver))
    main()


