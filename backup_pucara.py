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
backup_pucara.py — Backup automático de la base de datos
═══════════════════════════════════════════════════════
Crea una copia segura de netadmin.db (usando la API de backup de SQLite,
que es segura aunque la app esté escribiendo), la comprime con gzip,
y borra los backups con más de 30 días.

Uso manual:
    python3 backup_pucara.py

Cron (diario a las 03:00):
    crontab -e
    0 3 * * * cd /ruta/al/proyecto && python3 backup_pucara.py >> backups/backup.log 2>&1
"""
import sqlite3
import gzip
import os
import shutil
import sys
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, 'netadmin.db')
BACKUP_DIR = os.path.join(BASE, 'backups')
DIAS_RETENCION = 30

def main():
    if not os.path.exists(DB_PATH):
        print(f"[{datetime.now():%Y-%m-%d %H:%M}] ERROR: no existe {DB_PATH}")
        sys.exit(1)
    os.makedirs(BACKUP_DIR, exist_ok=True)

    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    tmp_copy = os.path.join(BACKUP_DIR, f'_tmp_{stamp}.db')
    final = os.path.join(BACKUP_DIR, f'pucara_{stamp}.db.gz')

    # 1. Copia consistente con la API de backup de SQLite (segura con la app corriendo)
    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(tmp_copy)
    with dst:
        src.backup(dst)
    dst.close()
    src.close()

    # 2. Comprimir
    with open(tmp_copy, 'rb') as f_in, gzip.open(final, 'wb', compresslevel=6) as f_out:
        shutil.copyfileobj(f_in, f_out)
    os.remove(tmp_copy)

    size_mb = os.path.getsize(final) / (1024 * 1024)
    print(f"[{datetime.now():%Y-%m-%d %H:%M}] Backup OK: {os.path.basename(final)} ({size_mb:.1f} MB)")

    # 3. Rotación: borrar backups de más de DIAS_RETENCION días
    limite = datetime.now() - timedelta(days=DIAS_RETENCION)
    borrados = 0
    for f in os.listdir(BACKUP_DIR):
        if f.startswith('pucara_') and f.endswith('.db.gz'):
            path = os.path.join(BACKUP_DIR, f)
            if datetime.fromtimestamp(os.path.getmtime(path)) < limite:
                os.remove(path)
                borrados += 1
    if borrados:
        print(f"  Rotación: {borrados} backup(s) viejos eliminados (> {DIAS_RETENCION} días)")

if __name__ == '__main__':
    main()
