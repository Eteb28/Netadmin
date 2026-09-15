# ERLAN NetAdmin v6.1 — Sync ERP

## Qué cambió respecto a v6

- **Sync ERP**: nuevo `sync_pg.py` que lee clientes de PostgreSQL y los vuelca a SQLite
- **Nuevos campos**: nro_cliente, telefono2, pppoe_usuario, pppoe_clave, cdo, red, torre_id, ap_nombre
- **Búsqueda mejorada**: se puede buscar por nombre Y por N° de cliente en clientes y mapa
- **Estado correcto**: el estado se calcula desde `contratos` (fechasuspension/fecharescision), no desde `clientes.cuentactiva`

## Instalación

```bash
# 1. Backup de todo
cp -r /home/eaguiar/ERLAN/erlan_actual /home/eaguiar/ERLAN/erlan_actual.bak

# 2. Descomprimir el zip
cd /home/eaguiar/ERLAN
unzip ~/Descargas/erlan_v6.1.zip

# 3. Copiar la DB existente (NO viene en el zip)
cp erlan_actual/netadmin.db erlan_v6.1/

# 4. Crear archivo .env con la password de PostgreSQL
cp erlan_v6.1/.env.example erlan_v6.1/.env
nano erlan_v6.1/.env   # poner la password real

# 5. Instalar dependencias
cd erlan_v6.1
pip install -r requirements.txt
```

## Primer sync

```bash
cd /home/eaguiar/ERLAN/erlan_v6.1

# Test de conexión a PostgreSQL
python3 sync_pg.py --test

# Ver qué haría sin escribir
python3 sync_pg.py --dry-run

# Sync real
python3 sync_pg.py
```

## Levantar la app

```bash
python3 app.py
```

## Sync automático (opcional)

Agregar al crontab para sync cada 15 minutos:

```bash
crontab -e
# Agregar:
*/15 * * * * cd /home/eaguiar/ERLAN/erlan_v6.1 && python3 sync_pg.py >> /tmp/sync_erlan.log 2>&1
```

## Sync manual desde la interfaz

Como admin, hacer POST a `/api/sync/run` (se puede agregar un botón después).

## Qué se sincroniza y qué NO

**Se actualiza desde el ERP:**
nombre, dni, email, teléfonos, dirección, localidad, coords, estado, tipo servicio, plan, precio, último pago, fecha alta, equipo, MAC, IP, PPPoE, CDO, red, NAP, OLT

**NO se pisa (datos locales de NetAdmin):**
torres, AP, observaciones, olt_puerto, fechas manuales (suspensión/rescisión/baja), agente

## Rollback

```bash
cp erlan_actual.bak/* erlan_actual/
```
