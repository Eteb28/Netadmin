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
liberar_ips_bajas.py — Libera las IPs de clientes dados de baja / rescindidos
═════════════════════════════════════════════════════════════════════════════
Limpia el campo ip_asignada de todos los clientes en estado baja, rescision
o pte_rescision, devolviendo esas IPs al pool para reasignación automática.

Guarda el detalle de lo liberado en backups/ips_liberadas_FECHA.txt
(por si alguna vez hay que rastrear qué IP tenía un cliente).

Uso:
    python3 liberar_ips_bajas.py            (dry-run: muestra qué liberaría)
    python3 liberar_ips_bajas.py --apply    (libera)
"""
import argparse
import os
import sqlite3
from datetime import datetime

ESTADOS_BAJA = ('baja', 'rescision', 'pte_rescision')

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default='netadmin.db')
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args()

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row

    ph = ','.join('?' * len(ESTADOS_BAJA))
    rows = con.execute(f"""
        SELECT id, nombre, nro_cliente, localidad, estado, ip_asignada
        FROM clientes
        WHERE estado IN ({ph})
          AND ip_asignada IS NOT NULL AND TRIM(ip_asignada) != ''
        ORDER BY ip_asignada""", ESTADOS_BAJA).fetchall()

    if not rows:
        print("No hay IPs cargadas en clientes de baja. Nada para liberar.")
        con.close()
        return

    # Resumen por subred (para ver cuánto se recupera por rango)
    por_subred = {}
    for r in rows:
        ip = r['ip_asignada'].strip()
        partes = ip.split('.')
        sub = '.'.join(partes[:3]) + '.x' if len(partes) == 4 else 'otras'
        por_subred[sub] = por_subred.get(sub, 0) + 1

    print(f"IPs a liberar: {len(rows)} (de clientes en {', '.join(ESTADOS_BAJA)})\n")
    print("Por subred:")
    for sub, c in sorted(por_subred.items(), key=lambda x: -x[1]):
        print(f"  {sub:20} {c} IPs")

    print("\nDetalle (primeros 20):")
    for r in rows[:20]:
        print(f"  {r['ip_asignada']:18} {r['nombre'][:40]:40} ({r['estado']})")
    if len(rows) > 20:
        print(f"  ... y {len(rows)-20} más")

    if args.apply:
        # Guardar detalle para trazabilidad
        os.makedirs('backups', exist_ok=True)
        detalle = os.path.join('backups', f"ips_liberadas_{datetime.now():%Y%m%d_%H%M%S}.txt")
        with open(detalle, 'w', encoding='utf-8') as f:
            f.write(f"IPs liberadas el {datetime.now():%Y-%m-%d %H:%M}\n")
            f.write(f"{'IP':18} {'Cliente':45} {'Nro':10} {'Estado'}\n")
            for r in rows:
                f.write(f"{r['ip_asignada']:18} {(r['nombre'] or '')[:45]:45} "
                        f"{str(r['nro_cliente'] or ''):10} {r['estado']}\n")
        ids = [r['id'] for r in rows]
        ph2 = ','.join('?' * len(ids))
        con.execute(f"""UPDATE clientes
            SET ip_asignada='', modificado=datetime('now','localtime')
            WHERE id IN ({ph2})""", ids)
        con.commit()
        print(f"\n✓ {len(rows)} IPs liberadas. Detalle guardado en {detalle}")
    else:
        print("\nModo: DRY-RUN (usá --apply para liberar)")
    con.close()

if __name__ == '__main__':
    main()
