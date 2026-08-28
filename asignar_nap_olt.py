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
asignar_nap_olt.py — Asigna clientes a NAPs desde datos de OLT
================================================================
Lee la tabla de ONUs de una OLT y actualiza en NetAdmin:
  - nap del cliente (CHARRUA - CDO X - NAP Y)
  - equipo_serie (serial de la ONU)
  - equipo_modelo (modelo de la ONU)
  - equipo_marca (VSOL/GPON)
  - olt_nombre, olt_puerto, red, cdo

Además vincula la infraestructura entre sí:
  - asegura que la RED exista (tabla redes)
  - registra/vincula la OLT con su red (tabla olts)
  - crea/actualiza cada NAP vinculándolo a su OLT y red (tabla naps)

Uso:
    python3 asignar_nap_olt.py --red CHARRUA --olt OLT-CHARRUA --pon 1 --archivo olt_charrua_pon1.txt
    python3 asignar_nap_olt.py --red CHARRUA --olt OLT-CHARRUA --pon 1 --archivo olt_charrua_pon1.txt --apply

Sin --apply solo muestra qué haría (dry-run).
"""
import sqlite3, re, sys, argparse
from pathlib import Path

DB_PATH = Path(__file__).parent / 'netadmin.db'

def parse_olt_line(line):
    """Parsea una línea de la tabla OLT.
    Formato: GPON0/1:N\tOnline\tGPON0/1:N_CLIENTID_CDOX_NAPY\tVxxx\tV2802DAC\tSn\tGPONxxxxxxxx
    """
    parts = line.strip().split('\t')
    if len(parts) < 7:
        return None
    
    puerto = parts[0].strip()         # GPON0/1:1
    estado_onu = parts[1].strip()     # Online / Offline
    descripcion = parts[2].strip()    # GPON0/1:1_030427_CDO1_NAP2
    firmware = parts[3].strip()       # V222 / V422 / unknown
    modelo = parts[4].strip()         # V2802DAC
    # parts[5] = "Sn"
    serial = parts[6].strip()         # GPON002e9f58

    # Extraer cliente y CDO/NAP de la descripción
    # Formato: GPON0/1:N_CLIENTID_CDOX_NAPY
    m = re.search(r'_([A-Za-z0-9]+)_CDO(\d+)_NAP(\d+)', descripcion)
    if not m:
        return None
    
    cliente_ref = m.group(1)  # Puede ser nro_cliente (030427) o nombre (zamero, Admini)
    cdo = m.group(2)
    nap = m.group(3)
    
    # Detectar marca por serial
    marca = 'VSOL' if serial.upper().startswith('VSOL') else 'GPON'
    
    # Extraer índice PON
    pon_match = re.match(r'GPON(\d+)/(\d+):(\d+)', puerto)
    pon_slot = pon_match.group(1) if pon_match else '0'
    pon_port = pon_match.group(2) if pon_match else '0'
    pon_index = pon_match.group(3) if pon_match else '0'
    
    return {
        'puerto': puerto,
        'estado_onu': estado_onu,
        'cliente_ref': cliente_ref,
        'cdo': cdo,
        'nap_num': nap,
        'firmware': firmware,
        'modelo': modelo,
        'serial': serial,
        'marca': marca,
        'pon_slot': pon_slot,
        'pon_port': pon_port,
        'pon_index': pon_index,
    }

def main():
    parser = argparse.ArgumentParser(description='Asignar clientes a NAPs desde datos de OLT')
    parser.add_argument('--red', required=True, help='Nombre de la red (CHARRUA, DIAZ, etc.)')
    parser.add_argument('--olt', required=True, help='Nombre de la OLT (OLT-CHARRUA, OLT-DIAZ, etc.)')
    parser.add_argument('--pon', default='', help='Número de PON (informativo)')
    parser.add_argument('--archivo', required=True, help='Archivo con datos de la OLT')
    parser.add_argument('--apply', action='store_true', help='Aplicar cambios (sin esto, solo muestra)')
    parser.add_argument('--db', default=str(DB_PATH), help='Ruta a la base de datos')
    args = parser.parse_args()

    red = args.red.upper()
    olt_nombre = args.olt

    # Leer archivo
    with open(args.archivo, 'r') as f:
        lines = f.readlines()

    print(f"{'='*70}")
    print(f"  OLT: {olt_nombre} | Red: {red} | PON: {args.pon}")
    print(f"  Archivo: {args.archivo} ({len(lines)} líneas)")
    print(f"  Modo: {'APLICAR' if args.apply else 'DRY-RUN'}")
    print(f"{'='*70}\n")

    # Parsear líneas
    onus = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parsed = parse_olt_line(line)
        if parsed:
            onus.append(parsed)
        else:
            print(f"  ⚠ No se pudo parsear: {line[:60]}...")

    print(f"ONUs parseadas: {len(onus)} ({sum(1 for o in onus if o['estado_onu']=='Online')} online, {sum(1 for o in onus if o['estado_onu']=='Offline')} offline)\n")

    # Conectar a DB
    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row

    # Buscar clientes por nro_cliente
    clientes_db = {}
    for row in con.execute("SELECT id, nombre, nro_cliente, nap, equipo_serie FROM clientes WHERE nro_cliente IS NOT NULL").fetchall():
        clientes_db[row['nro_cliente']] = dict(row)

    actualizados = 0
    no_encontrados = []
    ya_correctos = 0

    for onu in onus:
        ref = onu['cliente_ref']
        nap_nombre = f"{red} - CDO {onu['cdo']} - NAP {onu['nap_num']}"
        olt_puerto = f"PON{onu['pon_port']}:{onu['pon_index']}"

        # Buscar cliente por nro_cliente (las refs numéricas de 6 dígitos son codcliente)
        cliente = None
        if re.match(r'^\d{6}$', ref):
            # Buscar con y sin cero adelante
            cliente = clientes_db.get(ref) or clientes_db.get('0' + ref)
        
        if not cliente:
            # Buscar por nombre parcial (para refs como "zamero", "Admini", "Vago")
            for nro, cli in clientes_db.items():
                if ref.lower() in (cli.get('nombre','') or '').lower():
                    cliente = cli
                    break

        if not cliente:
            no_encontrados.append(f"  ❓ {ref} → {nap_nombre} (S/N: {onu['serial']})")
            continue

        # Verificar si ya está correcto
        if cliente.get('nap') == nap_nombre and cliente.get('equipo_serie') == onu['serial']:
            ya_correctos += 1
            continue

        cambios = []
        if cliente.get('nap') != nap_nombre:
            cambios.append(f"NAP: '{cliente.get('nap','—')}' → '{nap_nombre}'")
        if cliente.get('equipo_serie') != onu['serial']:
            cambios.append(f"Serie: '{cliente.get('equipo_serie','—')}' → '{onu['serial']}'")

        estado_icon = '🟢' if onu['estado_onu'] == 'Online' else '🔴'
        print(f"  {estado_icon} {cliente['nro_cliente']} {cliente['nombre'][:35]:<35} → {', '.join(cambios)}")

        if args.apply:
            con.execute("""UPDATE clientes SET
                nap=?, equipo_serie=?, equipo_modelo=?, equipo_marca=?,
                olt_nombre=?, olt_puerto=?, red=?, cdo=?, tipo_servicio='fibra'
                WHERE id=?""",
                (nap_nombre, onu['serial'], onu['modelo'], onu['marca'],
                 olt_nombre, olt_puerto, red, onu['cdo'], cliente['id']))
            actualizados += 1

    if args.apply:
        con.commit()

    print(f"\n{'='*70}")
    print(f"  RESULTADO:")
    print(f"    Actualizados: {actualizados}")
    print(f"    Ya correctos: {ya_correctos}")
    print(f"    No encontrados: {len(no_encontrados)}")
    if no_encontrados:
        print(f"\n  Clientes no encontrados en NetAdmin:")
        for nf in no_encontrados:
            print(nf)
    
    if not args.apply:
        print(f"\n  [dry-run] Ejecutá con --apply para aplicar los cambios.")

    # ─────────────────────────────────────────────────────────────
    # Vincular infraestructura: red, OLT y NAPs entre sí
    # ─────────────────────────────────────────────────────────────
    if args.apply:
        # 1. Asegurar que la red exista en la tabla redes
        existe_red = con.execute("SELECT id FROM redes WHERE UPPER(nombre)=?", (red,)).fetchone()
        if not existe_red:
            con.execute("INSERT INTO redes(nombre, descripcion, activa, creado) VALUES(?,?,1,datetime('now','localtime'))",
                        (red, f"Red {red} (creada por asignar_nap_olt)"))
            print(f"  ➕ Red '{red}' creada en tabla redes")

        # 2. Asegurar que la OLT exista y tenga su red asignada
        #    (agregar columna 'red' a olts si no existe)
        olt_cols = {r[1] for r in con.execute("PRAGMA table_info(olts)").fetchall()}
        if 'red' not in olt_cols:
            con.execute("ALTER TABLE olts ADD COLUMN red TEXT")
            print("  ➕ Columna 'red' agregada a tabla olts")

        existe_olt = con.execute("SELECT id FROM olts WHERE nombre=?", (olt_nombre,)).fetchone()
        if existe_olt:
            con.execute("UPDATE olts SET red=? WHERE nombre=?", (red, olt_nombre))
            print(f"  🔗 OLT '{olt_nombre}' vinculada a red '{red}'")
        else:
            con.execute("""INSERT INTO olts(nombre, red, puertos_pon, activa, creado)
                           VALUES(?,?,?,1,datetime('now','localtime'))""",
                        (olt_nombre, red, 8))
            print(f"  ➕ OLT '{olt_nombre}' creada y vinculada a red '{red}'")

        # 3. Crear/actualizar cada NAP usado, vinculándolo a su OLT y red
        naps_usados = {}  # nap_nombre -> (cdo, nap_num, olt_puerto)
        for onu in onus:
            nn = f"{red} - CDO {onu['cdo']} - NAP {onu['nap_num']}"
            naps_usados[nn] = (onu['cdo'], onu['nap_num'], f"PON{onu['pon_port']}:{onu['pon_index']}")

        naps_creados = naps_actualizados = 0
        for nap_n, (cdo, nap_num, olt_puerto) in naps_usados.items():
            existe = con.execute("SELECT id FROM naps WHERE nombre=?", (nap_n,)).fetchone()
            if existe:
                con.execute("""UPDATE naps SET olt_nombre=?, red=?, cdo=?, nap_numero=?, olt_puerto=?
                               WHERE nombre=?""",
                            (olt_nombre, red, cdo, nap_num, olt_puerto, nap_n))
                naps_actualizados += 1
            else:
                con.execute("""INSERT INTO naps(nombre, olt_nombre, red, cdo, nap_numero, olt_puerto, estado, creado)
                               VALUES(?,?,?,?,?,?,'activo',datetime('now','localtime'))""",
                            (nap_n, olt_nombre, red, cdo, nap_num, olt_puerto))
                naps_creados += 1

        con.commit()
        print(f"\n  🔗 Infraestructura vinculada:")
        print(f"     NAPs creados: {naps_creados} | actualizados: {naps_actualizados}")
        print(f"     Todos vinculados a OLT '{olt_nombre}' y red '{red}'")

    con.close()

if __name__ == '__main__':
    main()
