#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────
# Pucará — Poller SNMP (wrapper para cron)
# Sondea todos los APs del inventario (es_ap=1), guarda la señal de cada
# cliente, marca la torre fehaciente y dispara eventos (SNMP caído, LAN 10 Mbps…).
# ─────────────────────────────────────────────────────────────────────────
set -uo pipefail

# ══ AJUSTAR ESTOS 3 VALORES (ver instrucciones para obtenerlos) ══
BASE="/home/eaguiar/ERLAN/erlan_v6.1.8"     # WorkingDirectory de la app Pucará
DB="$BASE/netadmin.db"                        # la MISMA base que usa la app en vivo
PY="/home/eaguiar/ERLAN/erlan_v6.1.8/venv/bin/python3"                         # o "$BASE/venv/bin/python3" si usás venv
# ═════════════════════════════════════════════════════════════════

LOG="$BASE/logs/poller.log"
mkdir -p "$BASE/logs"
cd "$BASE" || { echo "No existe $BASE"; exit 1; }

{
  echo "===== $(date '+%F %T') ====="
  "$PY" snmp_poller.py --db "$DB"
  echo ""
} >> "$LOG" 2>&1
