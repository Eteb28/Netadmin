#!/bin/bash
# setup_cron.sh — Configura sync automático cada 15 minutos
# Uso: bash setup_cron.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SYNC_SCRIPT="$SCRIPT_DIR/sync_pg.py"
VENV_PYTHON="$SCRIPT_DIR/venv/bin/python3"
LOG_FILE="/tmp/sync_erlan.log"

# Verificar que existe sync_pg.py
if [ ! -f "$SYNC_SCRIPT" ]; then
    echo "❌ No encontré sync_pg.py en $SCRIPT_DIR"
    exit 1
fi

# Verificar si existe venv, sino usar python3 del sistema
if [ -f "$VENV_PYTHON" ]; then
    PYTHON="$VENV_PYTHON"
else
    PYTHON="$(which python3)"
fi

echo "📋 Configurando cron de sync ERP..."
echo "   Script: $SYNC_SCRIPT"
echo "   Python: $PYTHON"
echo "   Log: $LOG_FILE"

# Línea del cron
CRON_LINE="*/15 * * * * cd $SCRIPT_DIR && $PYTHON $SYNC_SCRIPT >> $LOG_FILE 2>&1"

# Verificar si ya existe
if crontab -l 2>/dev/null | grep -qF "sync_pg.py"; then
    echo "⚠️  Ya hay un cron para sync_pg.py. Reemplazando..."
    crontab -l 2>/dev/null | grep -vF "sync_pg.py" | crontab -
fi

# Agregar
(crontab -l 2>/dev/null; echo "$CRON_LINE") | crontab -

echo "✅ Cron configurado. Sync cada 15 minutos."
echo ""
echo "Para verificar: crontab -l"
echo "Para ver log:   tail -f $LOG_FILE"
echo "Para quitar:    crontab -l | grep -v sync_pg | crontab -"
