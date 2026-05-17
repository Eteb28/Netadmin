# NetAdmin v9 — Sprint 3: Sincronización ERP → NetAdmin

## Qué incluye

Vuelta a **NetAdmin estable con SQLite** + módulo independiente que
sincroniza datos del ERP (PG) cada 30 minutos.

```
app.py                  ← revertido a SQLite estable + endpoints del panel sync
sync_pg.py              ← NUEVO: módulo principal del sync
static/js/sync.js       ← NUEVO: frontend del panel
templates/index.html    ← Nueva página "🔄 Sincronización ERP"
static/js/auth.js       ← Visibilidad de "Sync ERP" para admins
static/js/nav.js        ← Activación del panel al entrar
crontab_sync.txt        ← Línea de cron para automatizar
.env.example            ← Plantilla de credenciales PG
requirements.txt        ← Agregado psycopg2-binary
```

## Lo que se removió (vs. sprint 2)

- `db.py` (la capa PG ya no se usa, NetAdmin va directo contra SQLite como antes)
- `migrar_sqlite_a_pg.py` (no se necesita)
- Schema PG `02_schema_netadmin.sql` (no se necesita)

NetAdmin queda **igual de estable** que antes del sprint v9, sin los
problemas de pool/boolean/etc., y con un módulo aparte que le trae
datos del ERP.

## Aplicar

### 1. Backup primero

```bash
cd /home/esteban/Documentos/erlan_v8
cp app.py app.py.PRE_SPRINT3.bak.$(date +%s)
cp -r static static.PRE_SPRINT3.bak
cp -r templates templates.PRE_SPRINT3.bak
```

### 2. Descomprimir el zip nuevo y aplicar

```bash
unzip -o ~/Descargas/erlan_v9_sprint3_sync.zip
cp -r erlan_v9_sprint3_sync/* ./
```

(Esto pisa `app.py`, agrega `sync_pg.py`, el JS del panel, etc.)

### 3. Instalar psycopg2

Las opciones de la última vez:

```bash
# Opción A: paquete del sistema (más simple)
sudo apt install python3-psycopg2

# Opción B: dentro del venv
source venv/bin/activate
pip install psycopg2-binary
```

### 4. Configurar .env

```bash
cp .env.example .env
nano .env
# Editar PG_PASSWORD con la password real de netadmin_user
```

### 5. Probar conexión PG

```bash
source venv/bin/activate
python3 sync_pg.py --test
# Esperado: PG test: {'ok': True}
```

Si tira error, verificar:
- PostgreSQL corriendo: `sudo systemctl status postgresql`
- Usuario `netadmin_user` existe en PG
- DB `erlan_db` existe en PG
- Password en `.env` es correcta

### 6. Probar sync sin escribir (dry-run)

```bash
python3 sync_pg.py --dry-run
```

Vas a ver algo así:

```
═══ SYNC OK ═══
  Inicio: 2026-05-12 23:00:00    Duración: 2.3s
  Iniciado por: cron
  (DRY-RUN — no se escribió nada)
  ✓ clientes     leidos=20037, nuevos=14000, actualizados=6037
  ✓ contratos    leidos=26747, insertados=26747
  ✓ stock        leidos=523, agregados=200, actualizados=323
  ✓ morosidad    leidos=4929, actualizados=4929
  ✓ calculos     leidos=8000, actualizados=8000
```

### 7. Primer sync real

```bash
python3 sync_pg.py
```

**Va a tardar entre 1 y 3 minutos** la primera vez porque trae los
14.000 clientes nuevos. Las syncs siguientes son rápidas (~30s).

### 8. Instalar el cron

```bash
crontab -e
```

Pegar la línea que está en `crontab_sync.txt` (ajustando la ruta si
tu NetAdmin está en otro lado).

### 9. Arrancar NetAdmin

```bash
source venv/bin/activate
python3 app.py
```

Loguearte como admin → en el menú vas a ver **🔄 Sync ERP**.

## El panel "Sincronización ERP"

Vas a ver:

- **Última sincronización**: fecha, duración, estado, errores
- **Acciones**: Sincronizar ahora / Dry-run / Test PG
- **Cambios último ciclo**: qué módulo qué hizo
- **Clientes pendientes de cargar al ERP**: clientes creados en NetAdmin
  con "Crear como venta nueva" que todavía no están en el ERP. Cargalos
  manualmente desde el ERP y marcalos como cargados acá.
- **Historial**: últimas 20 sincronizaciones

## Estrategia de conflictos (resumen)

**Cuando el sync corre, los datos de NetAdmin se conservan en:**
- `lat`, `lng` (coordenadas manuales)
- `observaciones`
- `equipo_serie`, `equipo_modelo`, `equipo_marca`, `mac_address`
- `nap`, `olt_*`, `torre_id`, `ap_nombre`
- `pppoe_*`
- `plan`, `precio` (NetAdmin tiene su propia tarifa)
- Todo el histórico, instalaciones, etc.

**Lo que el ERP pisa:**
- `nombre`, `dni`, `email`, `telefono`, `direccion`, `localidad`
- `estado` (activo / suspendido / baja / rescision)
- `fecha_alta`, `fecha_baja`, `agente`

**Match**: `nro_cliente` (NetAdmin) == `codcliente` (ERP)

## Tablas nuevas creadas en SQLite

El primer sync crea estas tablas automáticamente:

| Tabla | Para qué |
|---|---|
| `sync_log` | Historial de cada sincronización |
| `contratos_erp` | Cache de todos los contratos del ERP |
| `clientes_morosidad` | Cálculo de morosidad por cliente |
| `calculos_enlace` | Datos técnicos de contratos (distancia, altura) |
| `clientes_pte_erp` | Tracking de clientes creados en NetAdmin para cargar al ERP |

## Si algo falla

| Síntoma | Causa probable |
|---|---|
| `psycopg2 no instalado` | falta `pip install psycopg2-binary` |
| `connection refused` | PG no corriendo o puerto distinto |
| `password authentication failed` | password mal en .env |
| `relation "public.clientes" does not exist` | DB del ERP no restaurada o nombre distinto |
| Sync no aparece en el menú | refrescar con Ctrl+F5; debe estar logueado como admin |

Cualquier error en el panel se ve en la sección "Errores" y en
`sync_log` (último item, columna `errores`).

## Pasos futuros (no incluidos en este sprint)

- Fase 2: sync de subida ultra-cauta (solo lat/lng en NAPs y observaciones)
- Sync más fino: detectar cambios uno por uno en vez de "leer todo"
- Trigger en PG que avisa a NetAdmin de cambios en tiempo real
- Mover PG de la máquina local al servidor de producción

## Soporte

Cualquier problema, pegame:
1. Log de la terminal donde corre `app.py`
2. Resumen del sync que aparece en el panel (con errores si hay)
3. Output de `python3 sync_pg.py --dry-run`

Si todavía no funciona, podés hacer rollback en 30s:

```bash
cp app.py.PRE_SPRINT3.bak.* app.py
cp -r static.PRE_SPRINT3.bak/* static/
cp -r templates.PRE_SPRINT3.bak/* templates/
# Reiniciar
```
