# Sprint Refactor — Paso 1: Backup + Sync minimalista + Marcadores

## Qué cambia en este paso

1. **`backup_netadmin.sh`** — Script para hacer backup con timestamp.
   Lo corrés antes de tocar cualquier cosa.

2. **`migrate_refactor.sql`** — Migración SQL que:
   - Agrega columnas marcadoras a `clientes` (`origen`, `*_origen`)
   - Preserva automáticamente lo que cargaste a mano (lat/lng, NAPs, equipos)
   - Crea índices para el listado

3. **`sync_pg.py`** — Reescrito MINIMALISTA:
   - Solo trae los campos del cliente que vos definiste
   - Ya NO toca lat/lng/equipo/nap/torre/pppoe/obs_tecnicas — esos son de NetAdmin
   - Match por `nro_cliente == codcliente`
   - Cada módulo en su propia transacción (no se rompe en cascada)

## Lo que NO cambia en este paso

- La interfaz visual (sigue igual)
- Las páginas (sigue como las tenías)
- Los endpoints de la app (siguen igual)
- El mapa (sigue igual)

**El paso 2 cambia el backend de clientes**.
**El paso 3 cambia el frontend (vista y listado)**.

## Aplicar el paso 1

```bash
cd /home/esteban/Documentos/erlan_v8

# 1) Detener la app si está corriendo
#    (Ctrl+C donde corre, o pkill -f "python.*app.py")

# 2) Copiar los archivos nuevos
unzip -o ~/Descargas/sprint_refactor_paso1.zip
cp sprint_refactor_paso1/backup_netadmin.sh ./
cp sprint_refactor_paso1/migrate_refactor.sql ./
cp sprint_refactor_paso1/sync_pg.py ./
chmod +x backup_netadmin.sh

# 3) Hacer backup
./backup_netadmin.sh
# Te debe crear: backups/netadmin_YYYYMMDD_HHMMSS.db

# 4) Aplicar migración
sqlite3 netadmin.db < migrate_refactor.sql
# Va a mostrar:
#   Total clientes               20037
#   Origen ERP                   20019
#   Origen NetAdmin              18
#   Con coords (preservadas)     511
#   Con equipo manual            N
#   Con NAP asignada             M
#   Con torre/AP                 K
#   Con observaciones técnicas   Z

# 5) Probar el sync nuevo
source venv/bin/activate
python3 sync_pg.py --dry-run

# Si todo OK, sync real
python3 sync_pg.py
```

## Cómo verificar que funcionó

```bash
# Ver clientes con coords preservadas
sqlite3 netadmin.db "SELECT COUNT(*) FROM clientes WHERE coords_origen='netadmin'"
# Te debe dar el mismo número que antes del sync

# Ver clientes pendientes de cargar al ERP
sqlite3 netadmin.db "SELECT id, nombre, dni, nro_cliente FROM clientes WHERE origen='netadmin'"
# Los 17-18 que creaste con "Crear como venta nueva"
```

## Rollback

Si algo no te gusta:

```bash
# Listar backups
ls -lt backups/

# Restaurar el último backup
cp backups/netadmin_YYYYMMDD_HHMMSS.db netadmin.db
```

## Próximo paso

Cuando confirmes que el paso 1 quedó bien, te paso el **paso 2**:
- Backend nuevo para listado y vista individual
- Endpoints adaptados a los campos definidos

Y después el **paso 3**:
- Frontend del listado con las 10 columnas
- Vista individual con bloques colapsables
- Mini-mapa centrado
- Filtros rápidos

---

## Campos definidos (recordatorio)

### Listado (de izq a der)
Nº, Nombre, DNI, Teléfono, Localidad, Tipo, Estado, NAP, OLT, Coords (✓/✗), [⚠ si origen=netadmin]

### Filtros rápidos
Búsqueda, Estado, Tipo, Localidad, Tiene coords

### Vista individual
- **Bloque 1 - Datos básicos** (ERP, lectura): Nº, Nombre, DNI, Email, Tel1, Tel2, Dirección completa
- **Bloque 2 - Servicio** (ERP, lectura): Estado, Tipo servicio, Fechas alta/baja, Agente, Plan, Zona
- **Bloque 3 - Técnicos** (NetAdmin, editables): Lat/Lng, NAP, OLT, Torre/AP, Equipo, IP, PPPoE, Observaciones técnicas
- **Bloque 4 - Histórico** (NetAdmin): Señales, equipos, NAPs/torres, instalaciones
- **Bloque 5 - Cálculos de enlace** (ERP, lectura): Distancia, Altura AP/SM, AirMax, Observaciones
- **Mini-mapa** centrado en el cliente
