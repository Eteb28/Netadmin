"""
ERLAN Telecomunicaciones S.A. — NetAdmin ISP v6.1
Sistema Integral de Gestión ISP
Sync ERP (PostgreSQL) → SQLite
"""
from flask import Flask, request, jsonify, render_template, session, redirect, send_file, abort, url_for
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from functools import wraps
import sqlite3, os, threading, time, io, csv, json
from datetime import datetime, date, timedelta

app = Flask(__name__)
# Secret key: variable de entorno, o una clave aleatoria persistida en disco.
# (Antes era un valor fijo en el código: cualquiera que leyera el código podía falsificar sesiones.)
def _load_secret_key():
    sk = os.environ.get('SECRET_KEY')
    if sk:
        return sk
    keyfile = os.path.join(os.path.dirname(__file__), '.secret_key')
    try:
        if os.path.exists(keyfile):
            with open(keyfile) as f:
                k = f.read().strip()
                if k:
                    return k
        import secrets
        k = secrets.token_hex(32)
        with open(keyfile, 'w') as f:
            f.write(k)
        try:
            os.chmod(keyfile, 0o600)
        except OSError:
            pass
        return k
    except OSError:
        # Último recurso: clave de proceso (las sesiones caen al reiniciar)
        import secrets
        return secrets.token_hex(32)
app.secret_key = _load_secret_key()

# Duración de sesión: 30 días, persistente (no se deslogea por inactividad ni al recargar)
from datetime import timedelta
app.permanent_session_lifetime = timedelta(days=30)
app.config['SESSION_REFRESH_EACH_REQUEST'] = True
# Cookie de sesión: configuración explícita para funcionar en HTTP (LAN, sin TLS)
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'   # permite navegación normal
app.config['SESSION_COOKIE_SECURE'] = False     # el sistema corre en HTTP, no exigir HTTPS
app.config['SESSION_COOKIE_HTTPONLY'] = True    # la cookie no es accesible por JS (seguridad)

@app.before_request
def _make_session_permanent():
    # Marcar la sesión como permanente para que use permanent_session_lifetime
    session.permanent = True
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# ─── Cache busting: versiona CSS/JS por fecha de modificación ───
# Así el navegador siempre baja la versión nueva cuando cambia un archivo,
# sin necesidad de agregar ?v=N a mano ni de forzar recarga.
@app.after_request
def _no_cache_html(response):
    """Evita que el navegador cachee las páginas HTML (/, /mobile, /login).
    Los estáticos (CSS/JS) sí se cachean, pero con versionado por mtime."""
    if response.mimetype == 'text/html':
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response

@app.after_request
def _security_headers(response):
    """Cabeceras básicas de hardening (no rompen nada de lo existente):
    - X-Frame-Options / frame-ancestors: evita clickjacking (incrustar la app
      en un iframe ajeno para engañar a un usuario logueado a hacer clic).
    - X-Content-Type-Options: evita que el navegador "adivine" el tipo de
      contenido de un archivo (protección contra ciertos XSS vía uploads)."""
    response.headers.setdefault('X-Frame-Options', 'DENY')
    response.headers.setdefault('Content-Security-Policy', "frame-ancestors 'none'")
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    return response

@app.context_processor
def _override_url_for():
    def versioned_url_for(endpoint, **values):
        if endpoint == 'static':
            filename = values.get('filename')
            if filename:
                fpath = os.path.join(app.static_folder, filename)
                try:
                    values['v'] = int(os.stat(fpath).st_mtime)
                except OSError:
                    pass
        return url_for(endpoint, **values)
    return dict(url_for=versioned_url_for)

DB      = os.path.join(os.path.dirname(__file__), 'netadmin.db')
UPLOADS = os.path.join(os.path.dirname(__file__), 'uploads')
os.makedirs(UPLOADS, exist_ok=True)

NAP_LIMIT = 8
NAP_WARN  = 6

# ─── DB ───────────────────────────────────────────────────────────
def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def get_db():
    con = sqlite3.connect(DB, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=30000")
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA cache_size=-8000")
    return con

def _migrate_columns(con):
    """Agrega columnas nuevas v6.1 si no existen."""
    cols_nuevas = [
        ('nro_cliente', 'TEXT'),
        ('telefono2', 'TEXT'),
        # Datos de red avanzados (pedido operativo): IP pública dedicada o
        # puertos redirigidos, modo del CPE y VLAN (fibra).
        ('tiene_ip_publica', 'INTEGER DEFAULT 0'),
        ('ip_publica', 'TEXT'),
        ('puertos_asignados', 'TEXT'),
        ('modo_equipo', 'TEXT'),
        ('vlan', 'TEXT'),
        ('pppoe_usuario', 'TEXT'),
        ('pppoe_clave', 'TEXT'),
        ('cdo', 'TEXT'),
        ('red', 'TEXT'),
        ('torre_id', 'INTEGER'),
        ('ap_nombre', 'TEXT'),
        ('necesita_nap', 'INTEGER DEFAULT 0'),
    ]
    existentes = {r[1] for r in con.execute("PRAGMA table_info(clientes)").fetchall()}
    for col, tipo in cols_nuevas:
        if col not in existentes:
            con.execute(f"ALTER TABLE clientes ADD COLUMN {col} {tipo}")
            print(f"[migrate] Agregada columna clientes.{col}")
    # Migrar incidencias: agregar columnas faltantes
    inc_cols = {r[1] for r in con.execute("PRAGMA table_info(incidencias)").fetchall()}
    for col, tipo in [('nap_id','INTEGER'),('nap_nombre','TEXT'),('torre_id','INTEGER'),
                      ('objeto_tipo','TEXT'),('red','TEXT'),('olt_nombre','TEXT'),
                      ('cdo','TEXT'),('objeto_ids','TEXT')]:
        if col not in inc_cols:
            con.execute(f"ALTER TABLE incidencias ADD COLUMN {col} {tipo}")
            print(f"[migrate] Agregada columna incidencias.{col}")
    # Tabla historial de señal
    con.execute("""CREATE TABLE IF NOT EXISTS historial_senal(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nap_nombre TEXT,
        cliente_id INTEGER,
        nivel_dbm REAL,
        tipo TEXT DEFAULT 'medicion',
        observaciones TEXT,
        fecha TEXT DEFAULT(datetime('now','localtime')),
        usuario TEXT
    )""")
    # Tabla SEPARADA para señal por cliente (la de arriba es por NAP en producción)
    con.execute("""CREATE TABLE IF NOT EXISTS historial_senal_cliente(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cliente_id INTEGER NOT NULL,
        nivel_dbm REAL,
        tipo TEXT DEFAULT 'medicion',
        observaciones TEXT,
        fecha TEXT DEFAULT(datetime('now','localtime')),
        usuario TEXT
    )""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_hsc_cliente ON historial_senal_cliente(cliente_id)")
    # Instantánea de las estaciones que ve cada AP por SNMP.
    # historial_senal_cliente guarda el HISTÓRICO de señal (una fila por lectura),
    # pero no responde "quién está colgado de este AP ahora mismo": para eso hace
    # falta el estado actual, que es lo que alimenta la Vista de APs. Se pisa en
    # cada sondeo (PK equipo_id+mac), así el que se desconectó desaparece solo.
    con.execute("""CREATE TABLE IF NOT EXISTS snmp_estaciones(
        equipo_id INTEGER NOT NULL,
        mac TEXT NOT NULL,
        cliente_id INTEGER,
        nombre_ap TEXT,           -- nombre que el AP le puso (Cambium lo reporta)
        ip TEXT,
        rssi REAL, snr REAL, ccq REAL,
        distancia_m REAL,
        tx_rate TEXT, rx_rate TEXT,
        uptime_s INTEGER,
        modelo_sm TEXT, firmware_sm TEXT,
        ssid TEXT,
        fecha TEXT,
        PRIMARY KEY(equipo_id, mac)
    )""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_snmpest_cli ON snmp_estaciones(cliente_id)")
    # Origen del dato de señal (v7): distingue de dónde vino cada medición.
    # Los registros viejos quedan como 'poller'; SNMP/API/manual etiquetan los nuevos.
    # Groundwork para migrar el poller a SNMP sin perder el histórico ni duplicar fuentes.
    try:
        hsc_cols = {r[1] for r in con.execute("PRAGMA table_info(historial_senal_cliente)").fetchall()}
        if 'source' not in hsc_cols:
            con.execute("ALTER TABLE historial_senal_cliente ADD COLUMN source TEXT DEFAULT 'poller'")
            print("[migrate] Agregada columna historial_senal_cliente.source")
        onu_cols = {r[1] for r in con.execute("PRAGMA table_info(onu_senal_hist)").fetchall()}
        if 'source' not in onu_cols:
            con.execute("ALTER TABLE onu_senal_hist ADD COLUMN source TEXT DEFAULT 'poller'")
            print("[migrate] Agregada columna onu_senal_hist.source")
    except Exception as e:
        print(f"[migrate] source: {e}")
    # Columnas para monitoreo por ping (v6.2)
    cli_cols2 = {r[1] for r in con.execute("PRAGMA table_info(clientes)").fetchall()}
    for col, tipo in [('ping_estado','TEXT'),('ping_ms','REAL'),('ultimo_ping','TEXT'),
                       ('fecha_cambio_estado','TEXT')]:
        if col not in cli_cols2:
            con.execute(f"ALTER TABLE clientes ADD COLUMN {col} {tipo}")
            print(f"[migrate] Agregada columna clientes.{col}")
    # Columnas para notificación de afectados en incidencias (v6.2)
    try:
        inc_cols = {r[1] for r in con.execute("PRAGMA table_info(incidencias)").fetchall()}
        for col in ['nap_nombre','objeto_ids']:
            if col not in inc_cols:
                con.execute(f"ALTER TABLE incidencias ADD COLUMN {col} TEXT")
                print(f"[migrate] Agregada columna incidencias.{col}")
    except Exception:
        pass
    # Columnas de vacaciones en empleados
    try:
        emp_cols = {r[1] for r in con.execute("PRAGMA table_info(empleados)").fetchall()}
        for col, tipo in [('dias_vacaciones_anuales','INTEGER DEFAULT 0'),
                          ('dias_vacaciones_acumulados','INTEGER DEFAULT 0')]:
            if col not in emp_cols:
                con.execute(f"ALTER TABLE empleados ADD COLUMN {col} {tipo}")
                print(f"[migrate] Agregada columna empleados.{col}")
    except Exception:
        pass
    # Permiso granular: quién puede editar las guardias de sábado
    try:
        usr_cols = {r[1] for r in con.execute("PRAGMA table_info(usuarios)").fetchall()}
        if 'puede_editar_guardias' not in usr_cols:
            con.execute("ALTER TABLE usuarios ADD COLUMN puede_editar_guardias INTEGER DEFAULT 0")
            print("[migrate] Agregada columna usuarios.puede_editar_guardias")
            # Habilitar por defecto a pcabana y eaguiar (los editores actuales)
            con.execute("UPDATE usuarios SET puede_editar_guardias=1 WHERE username IN ('pcabana','eaguiar')")
    except Exception:
        pass
    # Migrar permisos: 'instalaciones' era un nombre que no coincidía con el nav real.
    # El nav usa 'instalacion-pendiente' y 'activacion-pendiente'. Reemplazar en los
    # permisos guardados de cada usuario para que el permiso vuelva a aplicar.
    try:
        import json as _json
        filas = con.execute("SELECT id, permisos FROM usuarios WHERE permisos LIKE '%instalaciones%'").fetchall()
        for f in filas:
            raw = f[1] or ''
            if raw in ('root', '*'):
                continue
            try:
                p = _json.loads(raw)
            except Exception:
                continue
            mods = p.get('modulos')
            if isinstance(mods, list) and 'instalaciones' in mods:
                mods = [m for m in mods if m != 'instalaciones']
                for nuevo in ('instalacion-pendiente', 'activacion-pendiente'):
                    if nuevo not in mods:
                        mods.append(nuevo)
                p['modulos'] = mods
                con.execute("UPDATE usuarios SET permisos=? WHERE id=?",
                            (_json.dumps(p, ensure_ascii=False), f[0]))
        if filas:
            print(f"[migrate] Permisos 'instalaciones' migrados a instalacion/activacion-pendiente ({len(filas)} usuarios)")
    except Exception:
        pass
    # Tabla de redes
    con.execute("""CREATE TABLE IF NOT EXISTS redes(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT UNIQUE NOT NULL,
        descripcion TEXT,
        estado TEXT DEFAULT 'activa',
        creado TEXT DEFAULT(datetime('now','localtime'))
    )""")
    # Insertar redes iniciales si tabla vacía
    cnt_redes = con.execute("SELECT COUNT(*) FROM redes").fetchone()[0]
    if cnt_redes == 0:
        for r in ['Francia','Sanagustin','PuertoSanchez','EscuelaHogar','Charrua',
                   'Diaz','Procrear','Almafuerte','Alcain','Laprida']:
            con.execute("INSERT OR IGNORE INTO redes(nombre) VALUES(?)", (r,))
    # Tabla de log de sync
    con.execute("""CREATE TABLE IF NOT EXISTS sync_log(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fecha TEXT DEFAULT(datetime('now','localtime')),
        clientes_actualizados INTEGER DEFAULT 0,
        clientes_nuevos INTEGER DEFAULT 0,
        errores TEXT,
        duracion_seg REAL,
        iniciado_por TEXT DEFAULT 'manual'
    )""")
    # Migrar sync_log si le falta iniciado_por
    sync_cols = {r[1] for r in con.execute("PRAGMA table_info(sync_log)").fetchall()}
    if 'iniciado_por' not in sync_cols:
        con.execute("ALTER TABLE sync_log ADD COLUMN iniciado_por TEXT DEFAULT 'manual'")
    # Tabla rutas de fibra (FTTH planning)
    con.execute("""CREATE TABLE IF NOT EXISTS rutas_fibra(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL,
        descripcion TEXT,
        coords TEXT,
        distancia_m REAL,
        color TEXT DEFAULT '#1565c0',
        estado TEXT DEFAULT 'planificada',
        creado TEXT DEFAULT(datetime('now','localtime')),
        creado_por TEXT
    )""")
    # Tabla zonas de expansión
    con.execute("""CREATE TABLE IF NOT EXISTS zonas_expansion(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL,
        tipo TEXT DEFAULT 'ftth',
        coords TEXT,
        prioridad TEXT DEFAULT 'media',
        clientes_potenciales INTEGER DEFAULT 0,
        notas TEXT,
        estado TEXT DEFAULT 'pendiente',
        creado TEXT DEFAULT(datetime('now','localtime'))
    )""")
    # Rangos de IP para asignación automática (inalámbricos). Hosts 1-50 reservados torre.
    con.execute("""CREATE TABLE IF NOT EXISTS ip_rangos(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        subred INTEGER NOT NULL,
        host_desde INTEGER DEFAULT 51,
        host_hasta INTEGER DEFAULT 254,
        localidades TEXT DEFAULT '',
        origen TEXT,
        activo INTEGER DEFAULT 1,
        UNIQUE(subred))""")
    # IPs de equipos de torre (host 1-50): radios, APs, routers de energía/servicio.
    # NO son clientes; se administran a mano. subred+host es la clave única.
    con.execute("""CREATE TABLE IF NOT EXISTS ip_equipos_torre(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        subred INTEGER NOT NULL,
        host INTEGER NOT NULL,
        nombre TEXT DEFAULT '',
        mac TEXT DEFAULT '',
        notas TEXT DEFAULT '',
        modificado TEXT,
        UNIQUE(subred, host))""")
    # Credenciales TransDat (GPS vehículos) — editables luego en configuracion
    if _table_exists(con, 'configuracion'):
        for k, v in [('transdat_user','ERLANsoft'), ('transdat_pass','ER98*')]:
            ex = con.execute("SELECT 1 FROM configuracion WHERE clave=?", (k,)).fetchone()
            if not ex:
                con.execute("INSERT INTO configuracion(clave, valor) VALUES(?,?)", (k, v))
    # Columnas nuevas en servicios (para técnico, vendedor, demoras)
    svc_cols = {r[1] for r in con.execute("PRAGMA table_info(servicios)").fetchall()}
    for col, tipo in [
        ('vendedor', 'TEXT'),               # idusuario que solicitó (venta)
        ('tecnico_realizacion', 'TEXT'),    # idusuario_realizacion
        ('fecha_realizacion', 'TEXT'),      # cuándo se realizó (servicio)
        ('fecha_realizacion_instalacion', 'TEXT'),  # cuándo se instaló
        ('tipo_erp', 'TEXT'),               # tiposoporte original del ERP
        ('estado_erp', 'TEXT'),             # estado original del ERP
        ('motivo_cancelacion', 'TEXT'),     # por qué se canceló la instalación
        ('fecha_cancelacion', 'TEXT'),
        ('fecha_en_camino', 'TEXT'),        # cuándo el técnico salió hacia el lugar
        ('fecha_seguimiento', 'TEXT'),      # cuándo quedó marcado como requiere_seguimiento
    ]:
        if col not in svc_cols:
            con.execute(f"ALTER TABLE servicios ADD COLUMN {col} {tipo}")
            print(f"[migrate] Agregada columna servicios.{col}")
    con.execute("CREATE INDEX IF NOT EXISTS idx_servicios_tipo_estado ON servicios(tipo, estado)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_servicios_tecnico ON servicios(tecnico)")
    # Índice para nro_cliente (después de asegurar que la columna existe)
    con.execute("CREATE INDEX IF NOT EXISTS idx_clientes_nro ON clientes(nro_cliente)")
    # Columnas de censo de NAPs (quién censó, cuándo, quién asistió, bocas físicas)
    nap_cols = {r[1] for r in con.execute("PRAGMA table_info(naps)").fetchall()}
    for col, tipo in [
        ('censada', 'INTEGER DEFAULT 0'),
        ('censo_fecha', 'TEXT'),
        ('censo_tecnico', 'TEXT'),
        ('censo_asistente', 'TEXT'),
        ('censo_bocas_fisicas', 'INTEGER'),
        ('censo_notas', 'TEXT'),
        # Nomenclatura normalizada RED - CDO X - NAP Y y señal de instalación.
        # Estas cinco FALTABAN: el código las lee y las escribe (ver
        # /api/naps y actualizar_nap), pero init_db() nunca las creaba. En las
        # bases existentes aparecieron por un ALTER manual; en una base nueva
        # Pucará arrancaba y rompía al listar o editar una NAP. Sin esto, el
        # esquema no es reproducible y no hay recuperación ante desastre.
        ('nivel_senal', 'REAL'),
        ('red', 'TEXT'),
        ('cdo', 'TEXT'),
        ('nap_numero', 'INTEGER'),
        ('sitio', 'TEXT'),
    ]:
        if col not in nap_cols:
            con.execute(f"ALTER TABLE naps ADD COLUMN {col} {tipo}")
    # Columnas SNMP para monitoreo de OLT (Fase 1)
    olt_cols = {r[1] for r in con.execute("PRAGMA table_info(olts)").fetchall()}
    for col, tipo in [
        ('community', "TEXT DEFAULT 'public'"),
        ('version_snmp', "TEXT DEFAULT '2c'"),
        ('snmp_activo', 'INTEGER DEFAULT 0'),
        ('last_check', 'TEXT'),
        ('online', 'INTEGER DEFAULT 0'),
        ('uptime_seg', 'INTEGER'),
        ('firmware_snmp', 'TEXT'),
        ('temperatura', 'REAL'),
        ('voltaje', 'REAL'),
        ('puertos_json', 'TEXT'),
        ('onu_max_pon', 'INTEGER DEFAULT 128'),
        ('temp_fuente', 'TEXT'),        # 'chasis' o 'sfp' (umbrales distintos)
        ('temp_sfp_max', 'REAL'),
        ('temp_sfp_prom', 'REAL'),
    ]:
        if col not in olt_cols:
            con.execute(f"ALTER TABLE olts ADD COLUMN {col} {tipo}")
            print(f"[migrate] Agregada columna olts.{col}")
    # La columna se creó con DEFAULT 64, pero el split real de la planta es 1:128.
    # Se corrige una sola vez (las OLT nunca se configuraron a mano: no había campo
    # en la UI). Marca de control en 'config' para no volver a pisar ajustes manuales.
    try:
        ya = con.execute("SELECT valor FROM config WHERE clave='fix_onu_max_pon_128'").fetchone()
        if not ya:
            n = con.execute("UPDATE olts SET onu_max_pon=128 WHERE COALESCE(onu_max_pon,64)=64").rowcount
            con.execute("INSERT OR REPLACE INTO config(clave,valor) VALUES('fix_onu_max_pon_128','1')")
            if n:
                print(f"[migrate] Capacidad de PON corregida a 128 en {n} OLT (era 64 por defecto)")
    except Exception:
        pass
    # Tabla de señal óptica de ONU (Fase 2)
    con.execute("""CREATE TABLE IF NOT EXISTS onu_senal(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        olt_id INTEGER,
        pon INTEGER,
        onu INTEGER,
        nro_cliente TEXT,
        interfaz TEXT,
        rx_power REAL,
        tx_power REAL,
        temperatura REAL,
        voltaje REAL,
        online INTEGER DEFAULT 1,
        last_check TEXT,
        UNIQUE(olt_id, pon, onu)
    )""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_onu_senal_cli ON onu_senal(nro_cliente)")
    # Serial de ONU (para verificar contra el equipo del cliente)
    _osc = {r[1] for r in con.execute("PRAGMA table_info(onu_senal)").fetchall()}
    if 'serial_onu' not in _osc:
        con.execute("ALTER TABLE onu_senal ADD COLUMN serial_onu TEXT")
    # CDO/NAP tal como los rotula la OLT en el nombre de la interfaz de la ONU
    # (los lee olt_poller.sincronizar_onus_ifmib). Se guardan aparte de los
    # campos del cliente para poder comparar "lo que dice la OLT" contra "lo
    # que está cargado en Pucará" sin que uno pise al otro.
    for _c in ('cdo_olt', 'nap_olt'):
        if _c not in _osc:
            con.execute(f"ALTER TABLE onu_senal ADD COLUMN {_c} TEXT")
    # Histórico de señal de ONU (Fase 2)
    # ── Inventario de equipamiento físico por torre/nodo/backbone (Fase 7) ──
    # Un equipo puede vincularse con el monitoreo SNMP (snmp_ip/snmp_community)
    # y aporta a la valoración económica (costo histórico vs valor actual).
    # Torres/sitios. FALTABA en init_db: en producción ya existe (de versiones previas),
    # pero una instalación limpia arrancaba sin ella. IF NOT EXISTS no toca la existente.
    con.execute("""CREATE TABLE IF NOT EXISTS torres(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL,
        localidad TEXT,
        direccion TEXT,
        lat REAL,
        lng REAL,
        ip_equipos TEXT,
        orientaciones TEXT,
        altura_mts REAL,
        tipo TEXT DEFAULT 'repetidora',
        estado TEXT DEFAULT 'activa',
        torre_padre_id INTEGER,
        observaciones TEXT,
        proveedor TEXT,
        creado TEXT DEFAULT(datetime('now','localtime'))
    )""")
    con.execute("""CREATE TABLE IF NOT EXISTS torre_equipos(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        torre_id INTEGER,
        tipo TEXT,                    -- Router MikroTik, Switch, OLT, ONU, Ubiquiti, Cambium, UPS, Antena, Radio, Fuente, Gabinete, Media Converter, Otro
        fabricante TEXT,
        modelo TEXT,
        nro_serie TEXT,
        mac TEXT,
        ip TEXT,
        firmware TEXT,
        fecha_compra TEXT,
        costo_adquisicion REAL DEFAULT 0,   -- costo histórico (lo que se pagó)
        valor_actual REAL DEFAULT 0,        -- valor actual estimado (depreciado/mercado)
        estado TEXT DEFAULT 'operativo',    -- operativo, en_reparacion, de_baja, repuesto
        ubicacion TEXT,                     -- descripción libre (rack, mástil, gabinete)
        observaciones TEXT,
        -- Vínculo con monitoreo SNMP (Fase 8)
        snmp_ip TEXT,                       -- IP para sondear (si difiere de ip de gestión)
        snmp_community TEXT DEFAULT 'public',
        snmp_fabricante TEXT,               -- ubiquiti / cambium (adaptador a usar)
        snmp_version TEXT DEFAULT '1',      -- 1 / 2c / 3 (preparado para v2c/v3)
        datos_snmp TEXT,                    -- JSON: último snapshot de descubrimiento (radio/OS/etc.)
        es_ap INTEGER DEFAULT 0,            -- 1 = es un AP a sondear por el poller SNMP
        ultimo_snmp TEXT,                   -- fecha del último sondeo exitoso
        snmp_estado TEXT,                   -- online / offline / sin_datos
        creado TEXT DEFAULT(datetime('now','localtime'))
    )""")
    # Migración para bases existentes: columnas SNMP nuevas del inventario
    _te_cols = {r[1] for r in con.execute("PRAGMA table_info(torre_equipos)").fetchall()}
    if 'snmp_version' not in _te_cols:
        con.execute("ALTER TABLE torre_equipos ADD COLUMN snmp_version TEXT DEFAULT '1'")
        print("[migrate] Agregada columna torre_equipos.snmp_version")
    if 'datos_snmp' not in _te_cols:
        con.execute("ALTER TABLE torre_equipos ADD COLUMN datos_snmp TEXT")
        print("[migrate] Agregada columna torre_equipos.datos_snmp")
    con.execute("CREATE INDEX IF NOT EXISTS idx_torre_equipos_torre ON torre_equipos(torre_id)")
    # Eventos de monitoreo SNMP (Fase 10): transiciones con estado activo/recuperado.
    # La lógica de deduplicación vive en snmp_wireless.procesar_evento.
    con.execute("""CREATE TABLE IF NOT EXISTS snmp_eventos(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        equipo_id INTEGER,
        torre_id INTEGER,
        tipo TEXT NOT NULL,          -- snmp_caido, lan_10mbps, lan_down, cambio_firmware, ...
        interfaz TEXT,               -- eth0, ... (si aplica)
        detalle TEXT,
        valor TEXT,                  -- velocidad detectada, versión, etc.
        estado TEXT DEFAULT 'activo',-- activo / recuperado
        inicio TEXT,
        fin TEXT,
        creado TEXT DEFAULT(datetime('now','localtime'))
    )""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_snmp_eventos_equipo ON snmp_eventos(equipo_id, tipo, interfaz, estado)")
    # Enlaces punto a punto entre torres (Fase 7): relación explícita equipo A ↔ equipo B.
    # SNMP no puede adivinar solo qué equipo apunta a cuál; se define acá y se sondean
    # ambos extremos (señal + LAN + alertas de 10 Mbps).
    con.execute("""CREATE TABLE IF NOT EXISTS enlaces(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT,
        equipo_a_id INTEGER,           -- extremo A (torre_equipos.id)
        equipo_b_id INTEGER,           -- extremo B (torre_equipos.id)
        estado TEXT DEFAULT 'activo',  -- activo / inactivo
        observaciones TEXT,
        creado TEXT DEFAULT(datetime('now','localtime'))
    )""")

    # ── Fase capacidad/cobertura (Prioridad 1) ──
    # Perfil técnico POR MODELO (configurable). Se siembra vacío: los valores NULL
    # se muestran como "No disponible". Nada hardcodeado; el operador los completa.
    # 'fuente' = trazabilidad del dato (fabricante/manual/documentacion/snmp).
    con.execute("""CREATE TABLE IF NOT EXISTS perfil_radio(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fabricante TEXT,
        modelo TEXT,
        tipo_equipo TEXT,                 -- AP sectorial / AP omni / PtP / Estación
        apertura_horizontal REAL,         -- grados
        apertura_vertical REAL,           -- grados
        ganancia_dbi REAL,
        frecuencia_min REAL,              -- MHz
        frecuencia_max REAL,              -- MHz
        alcance_teorico_m REAL,           -- metros
        clientes_recomendados INTEGER,
        clientes_max_operativo INTEGER,
        throughput_recomendado_mbps REAL,
        umbral_advertencia REAL,          -- % del recomendado para pasar a 🟡 (ej. 80)
        umbral_critico REAL,              -- % para pasar a 🔴 (ej. 100)
        fuente TEXT DEFAULT 'manual',     -- fabricante / manual / documentacion / snmp
        observaciones TEXT,
        creado TEXT DEFAULT(datetime('now','localtime'))
    )""")
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_perfil_radio_modelo ON perfil_radio(fabricante, modelo)")

    # Datos físicos POR INSTANCIA (1:1 con torre_equipos). Separado a propósito.
    # apertura/alcance override el perfil (COALESCE); azimut/tilt/altura son por equipo.
    # Un equipo sin fila acá simplemente NO dibuja cobertura.
    con.execute("""CREATE TABLE IF NOT EXISTS equipo_radio_fisico(
        equipo_id INTEGER PRIMARY KEY,        -- torre_equipos.id
        perfil_radio_id INTEGER,              -- perfil_radio.id (opcional)
        azimut REAL,                          -- grados 0=N,90=E,180=S,270=O
        apertura_h_override REAL,             -- si NULL usa la del perfil
        apertura_v_override REAL,
        alcance_override_m REAL,              -- si NULL usa el del perfil
        altura_m REAL,
        tilt REAL,                            -- inclinación (grados; negativo = hacia abajo)
        polarizacion TEXT,                    -- vertical / horizontal / dual
        mostrar_cobertura INTEGER DEFAULT 1,  -- 1 = dibujar sector en el mapa de cobertura
        fuente TEXT DEFAULT 'manual',
        actualizado TEXT DEFAULT(datetime('now','localtime'))
    )""")

    con.execute("""CREATE TABLE IF NOT EXISTS onu_senal_hist(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nro_cliente TEXT,
        olt_id INTEGER,
        pon INTEGER,
        onu INTEGER,
        rx_power REAL,
        tx_power REAL,
        temperatura REAL,
        fecha TEXT
    )""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_onu_hist_cli ON onu_senal_hist(nro_cliente, fecha)")
    # Usuarios de Tero (para mostrar nombres reales en vez de usernames)
    con.execute("""CREATE TABLE IF NOT EXISTS tero_usuarios(
        id INTEGER PRIMARY KEY, username TEXT, nombre TEXT, apellido TEXT, nombre_completo TEXT)""")
    # Alertas de infraestructura (NAP/PON con todos los clientes caídos)
    con.execute("""CREATE TABLE IF NOT EXISTS alertas_infra(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tipo TEXT,
        referencia TEXT UNIQUE,
        titulo TEXT,
        severidad TEXT,
        clientes_json TEXT,
        n_afectados INTEGER,
        estado TEXT DEFAULT 'activa',
        notificada INTEGER DEFAULT 0,
        creada TEXT,
        resuelta_at TEXT
    )""")
    # Columnas de fecha para finanzas (si faltan)
    cli_cols = {r[1] for r in con.execute("PRAGMA table_info(clientes)").fetchall()}
    for col in ['fecha_instalacion', 'fecha_activacion', 'fecha_rescision']:
        if col not in cli_cols:
            con.execute(f"ALTER TABLE clientes ADD COLUMN {col} TEXT")
            print(f"[migrate] Agregada columna clientes.{col}")
    # Torre confirmada por SNMP (fehaciente): en qué AP/torre se vio realmente al cliente.
    # NO pisa torre_id (proximidad/manual); el cálculo de producción usa COALESCE.
    if 'torre_id_snmp' not in cli_cols:
        con.execute("ALTER TABLE clientes ADD COLUMN torre_id_snmp INTEGER")
        print("[migrate] Agregada columna clientes.torre_id_snmp")
    if 'ap_snmp_id' not in cli_cols:
        con.execute("ALTER TABLE clientes ADD COLUMN ap_snmp_id INTEGER")
        print("[migrate] Agregada columna clientes.ap_snmp_id")
    if 'torre_snmp_fecha' not in cli_cols:
        con.execute("ALTER TABLE clientes ADD COLUMN torre_snmp_fecha TEXT")
        print("[migrate] Agregada columna clientes.torre_snmp_fecha")
    # Tabla de snapshot mensual de facturación (se llena 1 vez por mes)
    con.execute("""CREATE TABLE IF NOT EXISTS facturacion_mensual(
        mes TEXT PRIMARY KEY,
        clientes_activos INTEGER,
        ingreso_total REAL,
        ingreso_fibra REAL,
        ingreso_inalambrico REAL,
        registrado TEXT
    )""")
    # Stock completo (importado de v6.2): equipos individuales por serie
    con.execute("""CREATE TABLE IF NOT EXISTS stock_items(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        serie TEXT, mac TEXT, modelo TEXT, marca TEXT, tipo TEXT,
        estado TEXT DEFAULT 'deposito',
        cliente_id INTEGER, cliente_nombre TEXT, nro_cliente TEXT,
        ubicacion TEXT DEFAULT 'Depósito central',
        fecha_ingreso TEXT DEFAULT(datetime('now','localtime')),
        fecha_asignacion TEXT, fecha_retiro TEXT, fecha_baja TEXT,
        motivo_baja TEXT, observaciones TEXT, creado_por TEXT
    )""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_stock_items_serie ON stock_items(serie)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_stock_items_estado ON stock_items(estado)")
    # Inventario por cantidad (material a granel: bobinas, conectores, RJ-45, etc.)
    con.execute("""CREATE TABLE IF NOT EXISTS stock_inventario(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL,
        categoria TEXT DEFAULT 'varios',
        cantidad INTEGER DEFAULT 0,
        unidad TEXT DEFAULT 'u',
        origen TEXT DEFAULT 'manual',
        serie_marca TEXT,
        serie_tipo TEXT,
        orden INTEGER DEFAULT 0,
        creado TEXT DEFAULT(datetime('now','localtime'))
    )""")
    con.execute("""CREATE TABLE IF NOT EXISTS stock_movimientos(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_id INTEGER REFERENCES stock_items(id),
        inventario_id INTEGER,
        tipo TEXT NOT NULL, descripcion TEXT,
        cantidad INTEGER, servicio_id INTEGER,
        cliente_id INTEGER, cliente_nombre TEXT, usuario TEXT,
        fecha TEXT DEFAULT(datetime('now','localtime'))
    )""")
    # Migración para bases existentes: agrega columnas si faltan (Fase 5)
    _mov_cols = {r[1] for r in con.execute("PRAGMA table_info(stock_movimientos)").fetchall()}
    for _c in ('servicio_id', 'cantidad', 'inventario_id'):
        if _c not in _mov_cols:
            con.execute(f"ALTER TABLE stock_movimientos ADD COLUMN {_c} INTEGER")
            print(f"[migrate] Agregada columna stock_movimientos.{_c}")
    # Dispositivos de monitoreo (equipos de red: torres, OLTs, antenas, etc.)
    con.execute("""CREATE TABLE IF NOT EXISTS monitoreo_dispositivos(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL,
        tipo TEXT DEFAULT 'otro',
        ip TEXT,
        ping_estado TEXT,
        ping_ms REAL,
        ultimo_ping TEXT,
        creado TEXT DEFAULT(datetime('now','localtime'))
    )""")
    # ── TÉCNICOS INTERIOR (tercerizados) ──
    # Lista fija de técnicos externos
    con.execute("""CREATE TABLE IF NOT EXISTS tecnico_interior_personal(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL,
        telefono TEXT,
        localidad TEXT,
        activo INTEGER DEFAULT 1,
        creado TEXT DEFAULT(datetime('now','localtime'))
    )""")
    # Tarifas por tipo de trabajo
    con.execute("""CREATE TABLE IF NOT EXISTS tecnico_interior_tarifas(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tipo_trabajo TEXT NOT NULL,
        monto REAL DEFAULT 0,
        activo INTEGER DEFAULT 1
    )""")
    # Trabajos realizados por técnicos externos
    con.execute("""CREATE TABLE IF NOT EXISTS tecnico_interior_trabajos(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tecnico TEXT NOT NULL,
        tipo_trabajo TEXT,
        monto REAL DEFAULT 0,
        cliente TEXT,
        localidad TEXT,
        fecha_trabajo TEXT,
        descripcion TEXT,
        pagado INTEGER DEFAULT 0,
        fecha_pago TEXT,
        creado TEXT DEFAULT(datetime('now','localtime')),
        creado_por TEXT
    )""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_ti_tecnico ON tecnico_interior_trabajos(tecnico)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_ti_fecha ON tecnico_interior_trabajos(fecha_trabajo)")
    # Pagos (recibos): cada pago agrupa varios trabajos abonados ese día
    con.execute("""CREATE TABLE IF NOT EXISTS tecnico_interior_pagos(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tecnico TEXT NOT NULL,
        fecha_pago TEXT,
        monto_total REAL DEFAULT 0,
        cantidad_trabajos INTEGER DEFAULT 0,
        periodo_desde TEXT,
        periodo_hasta TEXT,
        observaciones TEXT,
        creado_por TEXT,
        creado TEXT DEFAULT(datetime('now','localtime'))
    )""")
    # Columnas de verificación de trabajo realizado (un área verifica, otra paga)
    _ti_cols = {r[1] for r in con.execute("PRAGMA table_info(tecnico_interior_trabajos)").fetchall()}
    if 'realizado' not in _ti_cols:
        con.execute("ALTER TABLE tecnico_interior_trabajos ADD COLUMN realizado INTEGER DEFAULT 0")
        con.execute("ALTER TABLE tecnico_interior_trabajos ADD COLUMN realizado_por TEXT")
        con.execute("ALTER TABLE tecnico_interior_trabajos ADD COLUMN fecha_realizado TEXT")
        # Los ya pagados se asumen realizados (no romper datos existentes)
        con.execute("UPDATE tecnico_interior_trabajos SET realizado=1 WHERE pagado=1")
    if 'pago_id' not in _ti_cols:
        con.execute("ALTER TABLE tecnico_interior_trabajos ADD COLUMN pago_id INTEGER")
    # Columnas de aprobación en novedades (flujo solicitud → autorización).
    # Guardado: en bases nuevas la tabla aún no existe acá (se crea más abajo con
    # las columnas ya incluidas); esta migración es sólo para bases existentes.
    _nov_tab = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='empleados_novedades'").fetchone()
    if _nov_tab:
        _nov_cols = {r[1] for r in con.execute("PRAGMA table_info(empleados_novedades)").fetchall()}
        if 'estado' not in _nov_cols:
            con.execute("ALTER TABLE empleados_novedades ADD COLUMN estado TEXT DEFAULT 'autorizada'")
            con.execute("ALTER TABLE empleados_novedades ADD COLUMN autorizada_por TEXT")
            con.execute("ALTER TABLE empleados_novedades ADD COLUMN fecha_autorizacion TEXT")
            con.execute("ALTER TABLE empleados_novedades ADD COLUMN solicitada_por TEXT")
            # Las novedades existentes (cargadas por RRHH) quedan como autorizadas
        if 'periodo' not in _nov_cols:
            con.execute("ALTER TABLE empleados_novedades ADD COLUMN periodo INTEGER")
            print("[migrate] Agregada columna empleados_novedades.periodo")
    # Precargar tarifas si está vacío (tipos comunes, montos en 0 para que los cargue el usuario)
    if con.execute("SELECT COUNT(*) FROM tecnico_interior_tarifas").fetchone()[0] == 0:
        for t in ['Instalación FTTH','Instalación inalámbrica','Reparación FTTH',
                  'Reparación inalámbrica','Cambio de domicilio','Retiro de equipo',
                  'Mantenimiento NAP','Otro']:
            con.execute("INSERT INTO tecnico_interior_tarifas(tipo_trabajo, monto) VALUES(?,0)", (t,))
    # Columna por_metro en tarifas (Tendido FO se cobra por metro, no fijo)
    _tar_cols = {r[1] for r in con.execute("PRAGMA table_info(tecnico_interior_tarifas)").fetchall()}
    if 'por_metro' not in _tar_cols:
        con.execute("ALTER TABLE tecnico_interior_tarifas ADD COLUMN por_metro INTEGER DEFAULT 0")
    # Columna metros en trabajos (cantidad de metros para trabajos por metro)
    _tra_cols = {r[1] for r in con.execute("PRAGMA table_info(tecnico_interior_trabajos)").fetchall()}
    if 'metros' not in _tra_cols:
        con.execute("ALTER TABLE tecnico_interior_trabajos ADD COLUMN metros REAL DEFAULT 0")
    if 'cliente_id' not in _tra_cols:
        con.execute("ALTER TABLE tecnico_interior_trabajos ADD COLUMN cliente_id INTEGER")
        con.execute("CREATE INDEX IF NOT EXISTS idx_ti_cliente_id ON tecnico_interior_trabajos(cliente_id)")
    # Historial de cambios de abono/plan del cliente
    con.execute("""CREATE TABLE IF NOT EXISTS historial_abono(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cliente_id INTEGER NOT NULL,
        plan_anterior TEXT, plan_nuevo TEXT,
        precio_anterior REAL, precio_nuevo REAL,
        origen TEXT, usuario TEXT,
        fecha TEXT DEFAULT(datetime('now','localtime')))""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_hist_abono_cliente ON historial_abono(cliente_id)")
    # Precargar "Tendido FO" como tarifa por metro si no existe
    if not con.execute("SELECT 1 FROM tecnico_interior_tarifas WHERE tipo_trabajo='Tendido FO'").fetchone():
        con.execute("INSERT INTO tecnico_interior_tarifas(tipo_trabajo, monto, por_metro) VALUES('Tendido FO',0,1)")
    # Tarifas escalonadas (para la regla de volumen de Zalazar). Se crean con monto 0;
    # el usuario carga el monto real en la config de tarifas. NO se pisan si ya existen.
    for _tesc in ['Instalación FTTH > 6', 'Instalación FTTH > 9',
                  'Reparación FTTH > 4', 'Reparación FTTH > 8']:
        if not con.execute("SELECT 1 FROM tecnico_interior_tarifas WHERE tipo_trabajo=?", (_tesc,)).fetchone():
            con.execute("INSERT INTO tecnico_interior_tarifas(tipo_trabajo, monto) VALUES(?,0)", (_tesc,))
    # Tabla de actividad de usuarios (monitor de conectados)
    con.execute("""CREATE TABLE IF NOT EXISTS sesiones_actividad(
        username TEXT PRIMARY KEY,
        nombre TEXT,
        rol TEXT,
        ultima_actividad TEXT,
        ip TEXT,
        ultima_ruta TEXT
    )""")
    # Tabla de empleados (RRHH) — módulo manual
    con.execute("""CREATE TABLE IF NOT EXISTS empleados(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        legajo TEXT,
        nombre TEXT NOT NULL,
        dni TEXT,
        cuil TEXT,
        fecha_nacimiento TEXT,
        direccion TEXT,
        localidad TEXT,
        telefono TEXT,
        email TEXT,
        contacto_emergencia TEXT,
        tel_emergencia TEXT,
        puesto TEXT,
        area TEXT,
        fecha_ingreso TEXT,
        tipo_contrato TEXT,
        jornada TEXT,
        categoria TEXT,
        obra_social TEXT,
        art TEXT,
        username_sistema TEXT,
        codtecnico TEXT,
        codagente TEXT,
        estado TEXT DEFAULT 'activo',
        dias_vacaciones_anuales INTEGER DEFAULT 0,
        dias_vacaciones_acumulados INTEGER DEFAULT 0,
        observaciones TEXT,
        creado TEXT,
        modificado TEXT
    )""")
    # Novedades de RRHH (licencias, vacaciones, ausencias)
    con.execute("""CREATE TABLE IF NOT EXISTS empleados_novedades(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        empleado_id INTEGER NOT NULL,
        tipo TEXT,
        fecha_desde TEXT,
        fecha_hasta TEXT,
        dias INTEGER,
        motivo TEXT,
        usuario TEXT,
        estado TEXT DEFAULT 'autorizada',
        autorizada_por TEXT,
        fecha_autorizacion TEXT,
        solicitada_por TEXT,
        periodo INTEGER,
        creado TEXT
    )""")
    # Asignación de días de vacaciones POR PERÍODO (lo que RRHH otorga cada año).
    # El saldo disponible por período = dias_asignados - tomados - pendientes de ese período.
    con.execute("""CREATE TABLE IF NOT EXISTS vacaciones_periodo(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        empleado_id INTEGER NOT NULL,
        periodo INTEGER NOT NULL,
        dias_asignados REAL DEFAULT 0,
        observaciones TEXT,
        creado TEXT DEFAULT(datetime('now','localtime')),
        actualizado TEXT
    )""")
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_vac_periodo ON vacaciones_periodo(empleado_id, periodo)")
    # Guardias de sábado (rotación por área). titular + refuerzo opcional.
    # Vinculadas a empleados por id para poder cruzar con vacaciones/novedades.
    con.execute("""CREATE TABLE IF NOT EXISTS guardias(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fecha TEXT NOT NULL,
        area TEXT DEFAULT 'Mesa de Ayuda',
        empleado_id INTEGER,
        refuerzo_empleado_id INTEGER,
        observaciones TEXT,
        creado TEXT DEFAULT(datetime('now','localtime')),
        UNIQUE(fecha, area)
    )""")
    # Registro de uso del sistema: contador agregado por día/usuario/sección.
    # Sirve para saber con datos qué módulos se usan y cuáles están muertos.
    con.execute("""CREATE TABLE IF NOT EXISTS uso_secciones(
        fecha_dia TEXT NOT NULL,
        username TEXT NOT NULL,
        seccion TEXT NOT NULL,
        cantidad INTEGER DEFAULT 1,
        UNIQUE(fecha_dia, username, seccion)
    )""")
    con.execute("""CREATE TABLE IF NOT EXISTS catalogo_servicio(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tipo TEXT NOT NULL,          -- 'diagnostico' | 'solucion'
        nombre TEXT NOT NULL,
        activo INTEGER DEFAULT 1,
        orden INTEGER DEFAULT 0
    )""")
    # Registro de diagnóstico/solución aplicado a cada servicio
    svc_cols2 = {r[1] for r in con.execute("PRAGMA table_info(servicios)").fetchall()}
    for col in ['diagnostico', 'solucion_aplicada']:
        if col not in svc_cols2:
            con.execute(f"ALTER TABLE servicios ADD COLUMN {col} TEXT")

    # Precargar catálogo si está vacío
    if con.execute("SELECT COUNT(*) FROM catalogo_servicio").fetchone()[0] == 0:
        diagnosticos = [
            'Corte fibra árbol-camión','Corte servicio','No llega velocidad',
            'No responde ni de fábrica el equipo','No toma LAN',
            'Feo el enlace / se cae la capacidad','Se corta','Le da 10mbps el cable',
            'Mudanza','Migración','No toma IP el router','Se caen valores',
        ]
        soluciones = [
            'Conector','Fibrado nuevamente','Reemplazo ONU','Reconfiguración','Ficha',
            'Cambio de equipo','Conector en el NAP','Fuente','Atenuada la fibra',
            'Cambio domicilio','Retención y elevación','Reparación NAP-CDO',
            'Retira HH del nap + conector mecánico con capuchón','Conexión incorrecta en router',
            'Estrangulada la fibra','Obstruido','Reorientación',
            'Reinstalación, prisioneros y riendas','Colocación altura-torre','Cambio de cable',
        ]
        for i, d in enumerate(diagnosticos):
            con.execute("INSERT INTO catalogo_servicio(tipo,nombre,orden) VALUES('diagnostico',?,?)", (d, i))
        for i, s in enumerate(soluciones):
            con.execute("INSERT INTO catalogo_servicio(tipo,nombre,orden) VALUES('solucion',?,?)", (s, i))
    con.commit()

def init_db():
    con = get_db()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS usuarios(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        nombre TEXT NOT NULL,
        password TEXT NOT NULL,
        rol TEXT DEFAULT 'operador',
        activo INTEGER DEFAULT 1,
        creado TEXT DEFAULT(datetime('now','localtime'))
    );
    CREATE TABLE IF NOT EXISTS clientes(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL,
        dni TEXT,
        email TEXT,
        telefono TEXT,
        direccion TEXT,
        localidad TEXT,
        lat REAL,
        lng REAL,
        estado TEXT DEFAULT 'activo',
        tipo_servicio TEXT DEFAULT 'inalambrico',
        plan TEXT,
        precio REAL DEFAULT 0,
        nap TEXT,
        equipo_modelo TEXT,
        equipo_marca TEXT,
        equipo_serie TEXT,
        ip_asignada TEXT,
        mac_address TEXT,
        fecha_alta TEXT DEFAULT(date('now','localtime')),
        fecha_suspension TEXT,
        fecha_rescision TEXT,
        fecha_baja TEXT,
        ultimo_pago TEXT,
        agente TEXT,
        observaciones TEXT,
        olt_nombre TEXT,
        olt_puerto TEXT,
        creado TEXT DEFAULT(datetime('now','localtime')),
        modificado TEXT DEFAULT(datetime('now','localtime'))
    );
    CREATE TABLE IF NOT EXISTS naps(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT UNIQUE NOT NULL,
        descripcion TEXT,
        lat REAL,
        lng REAL,
        capacidad INTEGER DEFAULT 8,
        localidad TEXT,
        estado TEXT DEFAULT 'operativo',
        creado TEXT DEFAULT(datetime('now','localtime'))
    );
    CREATE TABLE IF NOT EXISTS abonos(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL,
        tipo TEXT NOT NULL,
        precio REAL NOT NULL,
        velocidad_bajada INTEGER DEFAULT 0,
        velocidad_subida INTEGER DEFAULT 0,
        descripcion TEXT,
        activo INTEGER DEFAULT 1,
        creado TEXT DEFAULT(datetime('now','localtime'))
    );
    CREATE TABLE IF NOT EXISTS egresos(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fecha TEXT NOT NULL,
        categoria TEXT NOT NULL,
        monto REAL NOT NULL,
        descripcion TEXT,
        creado TEXT DEFAULT(datetime('now','localtime')),
        creado_por TEXT
    );
    CREATE TABLE IF NOT EXISTS inflacion_mensual(
        mes TEXT UNIQUE NOT NULL,
        indice_pct REAL NOT NULL,
        creado TEXT DEFAULT(datetime('now','localtime')),
        creado_por TEXT
    );
    -- Reclamos espejados desde Tero HelpDesk (fuente: API GET /tickets)
    CREATE TABLE IF NOT EXISTS reclamos(
        tero_id INTEGER PRIMARY KEY,          -- ticket.id de Tero (clave natural)
        titulo TEXT,
        tero_client_id INTEGER,               -- ticket.client_id (ID interno de Tero)
        nro_cliente TEXT,                     -- cruzado a Pucara (via tero_client_map)
        cliente_nombre TEXT,
        connection_id INTEGER,
        created_by TEXT,                      -- operador que tomó el reclamo
        asign_to TEXT,                        -- operador asignado (puede ser NULL)
        categoria TEXT,
        subcategoria TEXT,
        estado TEXT,                          -- abierto / cerrado
        prioridad TEXT,
        departamento TEXT,
        issue TEXT,
        canal TEXT,                           -- attention_channel
        despacho_tecnico INTEGER DEFAULT 0,
        telefono TEXT,
        email TEXT,
        created_at TEXT,
        closed_at TEXT,
        detalle TEXT,
        solucion TEXT,
        sync_at TEXT DEFAULT(datetime('now','localtime'))
    );
    CREATE INDEX IF NOT EXISTS idx_reclamos_cliente ON reclamos(nro_cliente);
    CREATE INDEX IF NOT EXISTS idx_reclamos_estado ON reclamos(estado);
    CREATE INDEX IF NOT EXISTS idx_reclamos_asign ON reclamos(asign_to);
    -- Mapeo Tero client_id <-> Pucara nro_cliente (armado por DNI/code de conexiones)
    CREATE TABLE IF NOT EXISTS tero_client_map(
        tero_client_id INTEGER PRIMARY KEY,
        nro_cliente TEXT,
        dni TEXT,
        matched_by TEXT,                      -- 'code' | 'dni' | 'telefono' | 'manual'
        creado TEXT DEFAULT(datetime('now','localtime'))
    );
    -- Pizarrón de tareas personales (post-its) por usuario
    CREATE TABLE IF NOT EXISTS tareas_usuario(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        texto TEXT NOT NULL,
        color TEXT DEFAULT 'amarillo',
        completada INTEGER DEFAULT 0,
        orden INTEGER DEFAULT 0,
        creado TEXT DEFAULT(datetime('now','localtime')),
        completado_at TEXT
    );
    CREATE TABLE IF NOT EXISTS servicios(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cliente_id INTEGER REFERENCES clientes(id),
        tipo TEXT NOT NULL,
        subtipo TEXT,
        descripcion TEXT,
        tecnico TEXT,
        estado TEXT DEFAULT 'pendiente',
        prioridad TEXT DEFAULT 'normal',
        costo REAL DEFAULT 0,
        tiene_costo INTEGER DEFAULT 0,
        fecha_creacion TEXT DEFAULT(datetime('now','localtime')),
        fecha_asignacion TEXT,
        fecha_inicio TEXT,
        fecha_cierre TEXT,
        observaciones TEXT,
        creado_por TEXT
    );
    CREATE TABLE IF NOT EXISTS olts(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL,
        ip_remota TEXT,
        ip_red TEXT,
        puertos_pon INTEGER DEFAULT 4,
        lat REAL,
        lng REAL,
        ubicacion TEXT,
        modelo TEXT,
        activa INTEGER DEFAULT 1,
        creado TEXT DEFAULT(datetime('now','localtime'))
    );
    CREATE TABLE IF NOT EXISTS incidencias(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        titulo TEXT NOT NULL,
        tipo TEXT NOT NULL,
        descripcion TEXT,
        afectados TEXT,
        estado TEXT DEFAULT 'abierta',
        prioridad TEXT DEFAULT 'media',
        tecnico TEXT,
        lat REAL,
        lng REAL,
        fecha_inicio TEXT DEFAULT(datetime('now','localtime')),
        fecha_cierre TEXT,
        resolucion TEXT,
        creado_por TEXT
    );
    CREATE TABLE IF NOT EXISTS stock(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        modelo TEXT NOT NULL,
        marca TEXT,
        tipo TEXT,
        cantidad INTEGER DEFAULT 0,
        descripcion TEXT,
        activo INTEGER DEFAULT 1,
        creado TEXT DEFAULT(datetime('now','localtime'))
    );
    CREATE TABLE IF NOT EXISTS pagos(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cliente_id INTEGER REFERENCES clientes(id),
        monto REAL NOT NULL,
        fecha TEXT DEFAULT(date('now','localtime')),
        medio TEXT DEFAULT 'efectivo',
        referencia TEXT,
        observaciones TEXT,
        registrado_por TEXT,
        creado TEXT DEFAULT(datetime('now','localtime'))
    );
    CREATE TABLE IF NOT EXISTS historial(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tipo TEXT,
        modulo TEXT,
        titulo TEXT,
        detalle TEXT,
        diff TEXT,
        usuario TEXT,
        fecha TEXT DEFAULT(datetime('now','localtime'))
    );
    CREATE TABLE IF NOT EXISTS notificaciones(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tipo TEXT,
        titulo TEXT,
        detalle TEXT,
        leida INTEGER DEFAULT 0,
        fecha TEXT DEFAULT(datetime('now','localtime'))
    );
    CREATE TABLE IF NOT EXISTS empresa(
        id INTEGER PRIMARY KEY DEFAULT 1,
        razon_social TEXT DEFAULT 'ERLAN Telecomunicaciones S.A.',
        nombre_fantasia TEXT DEFAULT 'ERLAN',
        cuit TEXT,
        punto_venta INTEGER DEFAULT 1,
        direccion TEXT,
        telefono TEXT,
        email TEXT,
        logo_path TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_clientes_estado ON clientes(estado);
    CREATE INDEX IF NOT EXISTS idx_clientes_nap ON clientes(nap);
    CREATE INDEX IF NOT EXISTS idx_clientes_tipo ON clientes(tipo_servicio);
    CREATE INDEX IF NOT EXISTS idx_servicios_estado ON servicios(estado);
    CREATE INDEX IF NOT EXISTS idx_incidencias_estado ON incidencias(estado);
    CREATE INDEX IF NOT EXISTS idx_pagos_cliente ON pagos(cliente_id);
    """)
    # Migración: agregar columnas nuevas si no existen (v6 → v6.1)
    _migrate_columns(con)
    # Admin por defecto
    if not con.execute("SELECT id FROM usuarios WHERE username='admin'").fetchone():
        con.execute("INSERT INTO usuarios(username,nombre,password,rol) VALUES(?,?,?,?)",
                    ('admin','Administrador',generate_password_hash('admin123'),'admin'))
    # Empresa por defecto
    if not con.execute("SELECT id FROM empresa").fetchone():
        con.execute("INSERT INTO empresa DEFAULT VALUES")
    con.commit()
    con.close()

# ─── AUTH ─────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error':'no_auth'}), 401
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('rol') not in ('admin', 'root'):
            return jsonify({'error':'forbidden'}), 403
        return f(*args, **kwargs)
    return decorated

def _get_permisos_usuario():
    """Devuelve el dict de permisos del usuario logueado.
    admin/root tienen acceso total. Cachea en sesión por request."""
    if session.get('rol') in ('admin', 'root'):
        return {'modulos': '*', 'acciones': '*', 'flags': []}
    uid = session.get('user_id')
    if not uid:
        return {'modulos': [], 'acciones': [], 'flags': []}
    con = get_db()
    row = con.execute("SELECT permisos FROM usuarios WHERE id=?", (uid,)).fetchone()
    con.close()
    raw = (row['permisos'] if row else None) or '{}'
    if raw in ('root', '*'):
        return {'modulos': '*', 'acciones': '*', 'flags': []}
    try:
        p = json.loads(raw)
    except Exception:
        p = {}
    p.setdefault('modulos', [])
    p.setdefault('acciones', [])
    p.setdefault('flags', [])
    return p

def _tiene_modulo(perm, modulo):
    m = perm.get('modulos')
    return m == '*' or (isinstance(m, list) and modulo in m)

def _tiene_flag(perm, flag):
    return flag in (perm.get('flags') or [])

def requiere_permiso(modulo, accion=None):
    """Decorador: exige que el usuario tenga el módulo (y opcionalmente la acción).
    admin/root pasan siempre."""
    def wrapper(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if 'user_id' not in session:
                return jsonify({'error':'no_auth'}), 401
            if session.get('rol') in ('admin', 'root'):
                return f(*args, **kwargs)
            perm = _get_permisos_usuario()
            if not _tiene_modulo(perm, modulo):
                return jsonify({'error':'forbidden', 'detalle':f'Sin permiso para {modulo}'}), 403
            if accion:
                acc = perm.get('acciones')
                if not (acc == '*' or (isinstance(acc, list) and accion in acc)):
                    return jsonify({'error':'forbidden', 'detalle':f'Sin permiso de {accion}'}), 403
            return f(*args, **kwargs)
        return decorated
    return wrapper

def requiere_flag(flag):
    """Decorador: exige un flag especial (ej: puede_sync). admin/root pasan siempre."""
    def wrapper(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if 'user_id' not in session:
                return jsonify({'error':'no_auth'}), 401
            if session.get('rol') in ('admin', 'root'):
                return f(*args, **kwargs)
            if not _tiene_flag(_get_permisos_usuario(), flag):
                return jsonify({'error':'forbidden', 'detalle':f'Sin permiso: {flag}'}), 403
            return f(*args, **kwargs)
        return decorated
    return wrapper

_ACT_CACHE = {}          # username -> (timestamp, ultima_ruta)
_ACT_LOCK = threading.Lock()
ACT_INTERVALO = 45       # segundos entre escrituras reales por usuario

@app.before_request
def _track_actividad():
    """Registra la última actividad de cada usuario logueado (monitor de conectados).

    OJO: esto corre en CADA request. Antes escribía en SQLite siempre, y como
    SQLite admite un solo escritor, durante el sync (que retiene el lock varios
    segundos) TODOS los requests quedaban esperando acá — ni siquiera llegaban a
    su handler. De ahí el "no abre nada" y las acciones repetidas.
    Ahora se escribe como mucho una vez cada ACT_INTERVALO segundos por usuario;
    el resto del tiempo se guarda en memoria."""
    if 'username' not in session:
        return
    path = request.path or ''
    # No registrar pings de fondo ni estáticos para no inflar
    if path.startswith('/static') or path == '/api/usuarios/conectados':
        return
    usuario = session.get('username')
    ahora = time.time()
    with _ACT_LOCK:
        prev = _ACT_CACHE.get(usuario)
        _ACT_CACHE[usuario] = (ahora, path)
        if prev and (ahora - prev[0]) < ACT_INTERVALO:
            return          # ya se registró hace poco: no tocar la base
    try:
        con = get_db()
        con.execute("""
            INSERT INTO sesiones_actividad(username, nombre, rol, ultima_actividad, ip, ultima_ruta)
            VALUES(?,?,?,datetime('now','localtime'),?,?)
            ON CONFLICT(username) DO UPDATE SET
                ultima_actividad=datetime('now','localtime'),
                ip=excluded.ip, ultima_ruta=excluded.ultima_ruta,
                nombre=excluded.nombre, rol=excluded.rol
        """, (usuario, session.get('nombre'), session.get('rol'),
              request.headers.get('X-Forwarded-For', request.remote_addr), path))
        con.commit()
        con.close()
    except Exception:
        pass  # nunca romper un request por el tracking

@app.route('/api/usuarios/conectados')
@login_required
def usuarios_conectados():
    """Usuarios activos. 'en línea' = actividad en los últimos 5 minutos."""
    con = get_db()
    rows = con.execute("""
        SELECT username, nombre, rol, ultima_actividad, ip, ultima_ruta,
               CAST((julianday('now','localtime') - julianday(ultima_actividad)) * 86400 AS INTEGER) AS seg_inactivo
        FROM sesiones_actividad
        ORDER BY ultima_actividad DESC
    """).fetchall()
    con.close()
    out = []
    for r in rows:
        seg = r['seg_inactivo'] or 999999
        if seg < 300:        estado = 'en_linea'      # < 5 min
        elif seg < 1800:     estado = 'inactivo'      # < 30 min
        else:                estado = 'desconectado'  # > 30 min
        out.append({
            'username': r['username'], 'nombre': r['nombre'], 'rol': r['rol'],
            'ultima_actividad': r['ultima_actividad'], 'ip': r['ip'],
            'ultima_ruta': r['ultima_ruta'],
            'segundos_inactivo': seg, 'estado': estado,
        })
    return jsonify({
        'usuarios': out,
        'en_linea': sum(1 for u in out if u['estado'] == 'en_linea'),
    })

# ════════════════════════════════════════════════════════
# RRHH — EMPLEADOS (solo admin)
# ════════════════════════════════════════════════════════
_EMP_CAMPOS = ['legajo','nombre','dni','cuil','fecha_nacimiento','direccion','localidad',
    'telefono','email','contacto_emergencia','tel_emergencia','puesto','area',
    'fecha_ingreso','tipo_contrato','jornada','categoria','obra_social','art',
    'username_sistema','codtecnico','codagente','estado','observaciones',
    'dias_vacaciones_anuales','dias_vacaciones_acumulados']

@app.route('/api/empleados')
@login_required
@admin_required
def get_empleados():
    area = request.args.get('area','')
    estado = request.args.get('estado','')
    q = request.args.get('q','')
    con = get_db()
    sql = "SELECT * FROM empleados WHERE 1=1"
    params = []
    if area:
        sql += " AND area=?"; params.append(area)
    if estado:
        sql += " AND estado=?"; params.append(estado)
    if q:
        sql += " AND (nombre LIKE ? OR dni LIKE ? OR legajo LIKE ?)"
        params += [f'%{q}%']*3
    sql += " ORDER BY nombre"
    rows = con.execute(sql, params).fetchall()
    con.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/empleados/<int:eid>')
@login_required
@admin_required
def get_empleado(eid):
    con = get_db()
    emp = con.execute("SELECT * FROM empleados WHERE id=?", (eid,)).fetchone()
    if not emp:
        con.close(); return jsonify({'error':'no encontrado'}), 404
    novedades = con.execute(
        "SELECT * FROM empleados_novedades WHERE empleado_id=? ORDER BY fecha_desde DESC", (eid,)
    ).fetchall()
    d = dict(emp)
    d['novedades'] = [dict(n) for n in novedades]
    # Saldo de vacaciones: MISMO criterio que el dashboard por período (RRHH).
    # Antes esto usaba un cálculo legacy (anuales+acumulados - tomados_del_año)
    # que ignoraba los períodos y contaba sólo lo tomado en el año calendario,
    # así que mostraba un "disponibles" distinto al que ve RRHH abajo.
    por_periodo, tot_periodo = _vacaciones_por_periodo(con, eid)
    anuales = d.get('dias_vacaciones_anuales') or 0
    acumulados = d.get('dias_vacaciones_acumulados') or 0
    usa_periodos = tot_periodo['periodos_asignados'] > 0
    if usa_periodos:
        disponibles = tot_periodo['disponibles']
        tomados = tot_periodo['tomados']
        pendientes = tot_periodo['pendientes']
    else:
        # Sin asignación por período: total legacy, pero contando TODO lo tomado
        # (no sólo el año actual), que era el otro error.
        tomados = sum((n.get('dias') or 0) for n in d['novedades']
                      if 'vacacion' in (n.get('tipo') or '').lower()
                      and n.get('estado') == 'autorizada')
        pendientes = sum((n.get('dias') or 0) for n in d['novedades']
                         if 'vacacion' in (n.get('tipo') or '').lower()
                         and n.get('estado') == 'pendiente')
        disponibles = anuales + acumulados - tomados - pendientes
    con.close()
    d['vacaciones'] = {
        'anuales': anuales,
        'acumulados': acumulados,
        'tomados': tomados,
        'tomados_este_anio': tomados,   # compat con el front actual
        'pendientes': pendientes,
        'disponibles': disponibles,
        'por_periodo': por_periodo,
        'usa_periodos': usa_periodos,
    }
    return jsonify(d)

@app.route('/api/empleados', methods=['POST'])
@login_required
@admin_required
def crear_empleado():
    data = request.get_json() or {}
    if not data.get('nombre'):
        return jsonify({'error':'nombre requerido'}), 400
    con = get_db()
    cols = [c for c in _EMP_CAMPOS if c in data]
    vals = [data[c] for c in cols]
    cols += ['creado','modificado']
    vals += [_now(), _now()]
    ph = ','.join('?'*len(cols))
    cur = con.execute(f"INSERT INTO empleados({','.join(cols)}) VALUES({ph})", vals)
    con.commit()
    eid = cur.lastrowid
    con.close()
    return jsonify({'ok':True, 'id':eid})

@app.route('/api/empleados/<int:eid>', methods=['PUT'])
@login_required
@admin_required
def actualizar_empleado(eid):
    data = request.get_json() or {}
    con = get_db()
    cols = [c for c in _EMP_CAMPOS if c in data]
    if not cols:
        con.close(); return jsonify({'error':'sin cambios'}), 400
    sets = ','.join(f"{c}=?" for c in cols) + ", modificado=?"
    vals = [data[c] for c in cols] + [_now(), eid]
    con.execute(f"UPDATE empleados SET {sets} WHERE id=?", vals)
    con.commit(); con.close()
    return jsonify({'ok':True})

@app.route('/api/empleados/<int:eid>', methods=['DELETE'])
@login_required
@admin_required
def eliminar_empleado(eid):
    con = get_db()
    con.execute("DELETE FROM empleados WHERE id=?", (eid,))
    con.execute("DELETE FROM empleados_novedades WHERE empleado_id=?", (eid,))
    con.commit(); con.close()
    return jsonify({'ok':True})

@app.route('/api/empleados/<int:eid>/novedades', methods=['POST'])
@login_required
@admin_required
def crear_novedad(eid):
    data = request.get_json() or {}
    con = get_db()
    # Al cargar a mano desde RRHH, la novedad queda autorizada de una (no pasa por
    # el flujo de solicitud). Registramos quién la cargó como autorizador y la fecha,
    # para que el comprobante PDF salga completo.
    ahora = _now()
    quien = session.get('username')
    # Período (solo relevante para vacaciones); por defecto el año de la fecha de inicio
    periodo = data.get('periodo')
    fd = data.get('fecha_desde')
    try:
        periodo = int(periodo) if periodo else (int(fd[:4]) if fd else None)
    except (ValueError, TypeError):
        periodo = None
    con.execute("""INSERT INTO empleados_novedades(empleado_id, tipo, fecha_desde, fecha_hasta,
                     dias, motivo, usuario, creado, estado, autorizada_por, fecha_autorizacion, periodo)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
        (eid, data.get('tipo'), data.get('fecha_desde'), data.get('fecha_hasta'),
         data.get('dias'), data.get('motivo'), quien, ahora,
         'autorizada', quien, ahora, periodo))
    con.commit(); con.close()
    return jsonify({'ok':True})

@app.route('/api/novedades/<int:nid>', methods=['PUT'])
@login_required
@admin_required
def actualizar_novedad(nid):
    data = request.get_json() or {}
    con = get_db()
    con.execute("""UPDATE empleados_novedades
        SET tipo=?, fecha_desde=?, fecha_hasta=?, dias=?, motivo=?,
            periodo=COALESCE(?, periodo) WHERE id=?""",
        (data.get('tipo'), data.get('fecha_desde'), data.get('fecha_hasta'),
         data.get('dias'), data.get('motivo'), data.get('periodo'), nid))
    con.commit(); con.close()
    return jsonify({'ok':True})

@app.route('/api/novedades/<int:nid>', methods=['DELETE'])
@login_required
@admin_required
def eliminar_novedad(nid):
    con = get_db()
    con.execute("DELETE FROM empleados_novedades WHERE id=?", (nid,))
    con.commit(); con.close()
    return jsonify({'ok':True})

@app.route('/api/empleados/resumen')
@login_required
@admin_required
def empleados_resumen():
    con = get_db()
    total = con.execute("SELECT COUNT(*) FROM empleados WHERE estado='activo'").fetchone()[0]
    por_area = con.execute("SELECT area, COUNT(*) c FROM empleados WHERE estado='activo' GROUP BY area").fetchall()
    con.close()
    return jsonify({
        'total_activos': total,
        'por_area': [{'area': r['area'] or 'Sin área', 'cantidad': r['c']} for r in por_area],
    })

@app.route('/api/empleados/ausencias')
@login_required
def empleados_ausencias():
    """Ausencias (novedades) que se solapan con un mes dado, para el calendario.
    Visible para todos los usuarios logueados (transparencia del equipo).
    El motivo detallado solo se muestra a admin/root (privacidad)."""
    mes = request.args.get('mes')
    es_admin = session.get('rol') in ('admin', 'root')
    con = get_db()
    if not mes:
        mes = con.execute("SELECT strftime('%Y-%m', date('now','localtime'))").fetchone()[0]
    ini = mes + '-01'
    fin = mes + '-31'
    # Novedades que se solapan con el mes (empiezan antes del fin Y terminan después del inicio)
    rows = con.execute("""
        SELECT n.id, n.empleado_id, n.tipo, n.fecha_desde, n.fecha_hasta, n.dias, n.motivo,
               n.estado, n.solicitada_por, n.periodo,
               e.nombre AS empleado, e.area, e.puesto
        FROM empleados_novedades n
        JOIN empleados e ON e.id = n.empleado_id
        WHERE n.fecha_desde IS NOT NULL AND n.fecha_desde != ''
          AND n.fecha_desde <= ?
          AND (n.fecha_hasta IS NULL OR n.fecha_hasta = '' OR n.fecha_hasta >= ?)
        ORDER BY n.fecha_desde
    """, (fin, ini)).fetchall()
    con.close()
    ausencias = []
    for r in rows:
        a = dict(r)
        if not es_admin:
            a.pop('motivo', None)  # el motivo solo lo ve admin
        ausencias.append(a)
    return jsonify({'mes': mes, 'ausencias': ausencias})

def _vacaciones_por_periodo(con, emp_id):
    """Desglose de vacaciones por período: asignados (RRHH) vs tomados/pendientes.
    Devuelve (lista_por_periodo, totales). Las novedades sin período (viejas) no
    se atribuyen a ningún período acá; se manejan aparte con el saldo legacy."""
    asign = con.execute("SELECT periodo, dias_asignados FROM vacaciones_periodo WHERE empleado_id=?",
                        (emp_id,)).fetchall()
    novs = con.execute("""SELECT periodo, dias, estado FROM empleados_novedades
        WHERE empleado_id=? AND LOWER(COALESCE(tipo,'')) LIKE '%vacacion%' AND periodo IS NOT NULL""",
        (emp_id,)).fetchall()
    # Días de vacaciones SIN período asignado (novedades viejas, antes de la
    # columna 'periodo'). No pertenecen a ningún período: se informan aparte
    # para que RRHH las regularice, y no ensucian el saldo por período.
    sin_periodo = con.execute("""SELECT COALESCE(SUM(dias),0) AS d FROM empleados_novedades
        WHERE empleado_id=? AND LOWER(COALESCE(tipo,'')) LIKE '%vacacion%'
          AND periodo IS NULL AND estado='autorizada'""", (emp_id,)).fetchone()['d'] or 0

    periodos = {}
    # 1) Períodos que RRHH asignó explícitamente (los únicos con saldo real)
    for a in asign:
        periodos[a['periodo']] = {'periodo': a['periodo'], 'asignados': a['dias_asignados'] or 0.0,
                                  'tomados': 0.0, 'pendientes': 0.0, 'asignado_por_rrhh': True}
    # 2) Períodos que aparecen sólo por consumo (RRHH nunca les cargó días).
    #    Antes esto generaba saldos negativos fantasma (0 - tomados).
    for n in novs:
        p = periodos.setdefault(n['periodo'], {'periodo': n['periodo'], 'asignados': 0.0,
                                               'tomados': 0.0, 'pendientes': 0.0,
                                               'asignado_por_rrhh': False})
        if n['estado'] == 'autorizada':
            p['tomados'] += (n['dias'] or 0)
        elif n['estado'] == 'pendiente':
            p['pendientes'] += (n['dias'] or 0)

    lista = []
    for p in sorted(periodos.values(), key=lambda x: x['periodo'], reverse=True):
        if p['asignado_por_rrhh']:
            # Saldo real. Puede ser negativo si se consumió de más: eso es
            # información válida (exceso), no un error de datos.
            p['disponibles'] = round(p['asignados'] - p['tomados'] - p['pendientes'], 1)
            p['excedido'] = p['disponibles'] < 0
        else:
            # Sin asignación de RRHH no hay saldo que calcular: se muestra el
            # consumo y se marca para regularizar, en vez de inventar un negativo.
            p['disponibles'] = 0.0
            p['excedido'] = False
        p['sin_asignacion'] = not p['asignado_por_rrhh']
        lista.append(p)

    # El total sólo suma los períodos que RRHH asignó (los que tienen saldo real).
    con_saldo = [p for p in lista if p['asignado_por_rrhh']]
    tot = {
        'asignados': round(sum(p['asignados'] for p in con_saldo), 1),
        'tomados': round(sum(p['tomados'] for p in con_saldo), 1),
        'pendientes': round(sum(p['pendientes'] for p in con_saldo), 1),
        'disponibles': round(sum(p['disponibles'] for p in con_saldo), 1),
        # Visibles pero fuera del saldo, para que RRHH los regularice:
        'tomados_sin_asignacion': round(sum(p['tomados'] for p in lista if p['sin_asignacion']), 1),
        'tomados_sin_periodo': round(sin_periodo, 1),
        'periodos_asignados': len(con_saldo),
    }
    return lista, tot

@app.route('/api/mi_empleado')
@login_required
def mi_empleado():
    """Devuelve el empleado vinculado al usuario logueado (por username_sistema)."""
    username = session.get('username','')
    con = get_db()
    emp = con.execute("SELECT * FROM empleados WHERE UPPER(TRIM(username_sistema))=UPPER(?)",
                      (username,)).fetchone()
    if not emp:
        con.close()
        return jsonify({'vinculado': False})
    d = dict(emp)
    # Saldo de vacaciones
    from datetime import date
    anio = str(date.today().year)
    novs = con.execute("""SELECT tipo, fecha_desde, dias, estado FROM empleados_novedades
        WHERE empleado_id=?""", (emp['id'],)).fetchall()
    tomados = sum((n['dias'] or 0) for n in novs
                  if 'vacacion' in (n['tipo'] or '').lower()
                  and (n['fecha_desde'] or '').startswith(anio)
                  and n['estado'] == 'autorizada')
    pendientes = sum((n['dias'] or 0) for n in novs
                     if 'vacacion' in (n['tipo'] or '').lower()
                     and (n['fecha_desde'] or '').startswith(anio)
                     and n['estado'] == 'pendiente')
    anuales = d.get('dias_vacaciones_anuales') or 0
    acum = d.get('dias_vacaciones_acumulados') or 0
    # Últimas solicitudes de vacaciones (RRHH pidió que el empleado las vea al
    # solicitar, para poder reclamar si algo no coincide).
    ultimas = [dict(r) for r in con.execute("""
        SELECT fecha_desde, fecha_hasta, dias, periodo, estado, motivo,
               autorizada_por, fecha_autorizacion
        FROM empleados_novedades
        WHERE empleado_id=? AND LOWER(COALESCE(tipo,'')) LIKE '%vacacion%'
        ORDER BY COALESCE(fecha_desde,'') DESC, id DESC LIMIT 4""",
        (emp['id'],)).fetchall()]
    # Desglose por período (lo que RRHH asignó por año)
    por_periodo, tot_periodo = _vacaciones_por_periodo(con, emp['id'])
    con.close()
    # Si RRHH ya cargó asignaciones por período, el saldo autoritativo sale de ahí.
    # Si no, se usa el total legacy (anuales + acumulados) para no romper nada.
    # OJO: sólo se usa el esquema por período si RRHH ASIGNÓ días de verdad.
    # Antes bastaba con que existiera una vacación etiquetada con período, y
    # como esos períodos tenían 0 asignados, el saldo daba NEGATIVO.
    usa_periodos = tot_periodo['periodos_asignados'] > 0
    disponibles = tot_periodo['disponibles'] if usa_periodos else (anuales + acum - tomados - pendientes)
    return jsonify({
        'vinculado': True,
        'empleado_id': emp['id'],
        'nombre': emp['nombre'],
        'vacaciones': {
            'anuales': anuales, 'acumulados': acum,
            'tomados': tot_periodo['tomados'] if usa_periodos else tomados,
            'pendientes_aprobacion': tot_periodo['pendientes'] if usa_periodos else pendientes,
            'disponibles': disponibles,
            'por_periodo': por_periodo,
            'usa_periodos': usa_periodos,
            'tomados_sin_asignacion': tot_periodo.get('tomados_sin_asignacion', 0),
            'tomados_sin_periodo': tot_periodo.get('tomados_sin_periodo', 0),
        },
        'ultimas_solicitudes': ultimas,
    })

@app.route('/api/empleados/<int:eid>/vacaciones_periodos')
@login_required
@admin_required
def vacaciones_periodos_get(eid):
    """Desglose de vacaciones por período de un empleado (para RRHH)."""
    con = get_db()
    lista, tot = _vacaciones_por_periodo(con, eid)
    con.close()
    return jsonify({'por_periodo': lista, 'totales': tot})

@app.route('/api/empleados/<int:eid>/vacaciones_periodos', methods=['POST'])
@login_required
@admin_required
def vacaciones_periodos_set(eid):
    """RRHH asigna/actualiza los días de un período (upsert por empleado+período)."""
    d = request.get_json() or {}
    try:
        periodo = int(d.get('periodo'))
    except (ValueError, TypeError):
        return jsonify({'error': 'Período inválido'}), 400
    try:
        dias = float(d.get('dias_asignados'))
    except (ValueError, TypeError):
        return jsonify({'error': 'Días inválidos'}), 400
    ahora = _now()
    con = get_db()
    ex = con.execute("SELECT id FROM vacaciones_periodo WHERE empleado_id=? AND periodo=?",
                     (eid, periodo)).fetchone()
    if ex:
        con.execute("UPDATE vacaciones_periodo SET dias_asignados=?, observaciones=?, actualizado=? WHERE id=?",
                    (dias, d.get('observaciones'), ahora, ex['id']))
    else:
        con.execute("""INSERT INTO vacaciones_periodo(empleado_id, periodo, dias_asignados, observaciones, actualizado)
                       VALUES(?,?,?,?,?)""", (eid, periodo, dias, d.get('observaciones'), ahora))
    con.commit(); con.close()
    return jsonify({'ok': True})

@app.route('/api/empleados/<int:eid>/vacaciones_periodos/<int:periodo>', methods=['DELETE'])
@login_required
@admin_required
def vacaciones_periodos_del(eid, periodo):
    con = get_db()
    con.execute("DELETE FROM vacaciones_periodo WHERE empleado_id=? AND periodo=?", (eid, periodo))
    con.commit(); con.close()
    return jsonify({'ok': True})

@app.route('/api/vacaciones/solicitar', methods=['POST'])
@login_required
def solicitar_vacaciones():
    """El empleado logueado solicita vacaciones (queda pendiente de autorización)."""
    d = request.get_json() or {}
    username = session.get('username','')
    con = get_db()
    emp = con.execute("SELECT id, nombre FROM empleados WHERE UPPER(TRIM(username_sistema))=UPPER(?)",
                      (username,)).fetchone()
    if not emp:
        con.close()
        return jsonify({'error':'Tu usuario no está vinculado a un legajo de empleado. Avisá a RRHH.'}), 400
    desde = d.get('fecha_desde'); hasta = d.get('fecha_hasta')
    if not desde:
        con.close(); return jsonify({'error':'Falta la fecha de inicio'}), 400
    medio_dia = bool(d.get('medio_dia'))
    dias = None
    if medio_dia:
        hasta = desde          # medio día = un solo día
        dias = 0.5
    elif desde and hasta:
        from datetime import date
        d1 = date.fromisoformat(desde); d2 = date.fromisoformat(hasta)
        dias = (d2 - d1).days + 1
    # Período al que corresponden estos días (ej. 2025). Por defecto, el año de inicio.
    periodo = d.get('periodo')
    try:
        periodo = int(periodo) if periodo else (int(desde[:4]) if desde else None)
    except (ValueError, TypeError):
        periodo = None
    con.execute("""INSERT INTO empleados_novedades
        (empleado_id, tipo, fecha_desde, fecha_hasta, dias, motivo, usuario, creado,
         estado, solicitada_por, periodo)
        VALUES(?,?,?,?,?,?,?,datetime('now','localtime'),'pendiente',?,?)""",
        (emp['id'], 'vacaciones', desde, hasta, dias, d.get('motivo',''),
         username, username, periodo))
    con.commit(); con.close()
    return jsonify({'ok':True, 'msg':'Solicitud enviada. Queda pendiente de autorización por RRHH.'})

@app.route('/api/novedades/<int:nid>/autorizar', methods=['POST'])
@login_required
@admin_required
def autorizar_novedad(nid):
    """RRHH autoriza o rechaza una solicitud."""
    d = request.get_json() or {}
    accion = d.get('accion')  # 'autorizar' | 'rechazar'
    con = get_db()
    estado = 'autorizada' if accion == 'autorizar' else 'rechazada'
    con.execute("""UPDATE empleados_novedades
        SET estado=?, autorizada_por=?, fecha_autorizacion=datetime('now','localtime')
        WHERE id=?""", (estado, session.get('username'), nid))
    con.commit(); con.close()
    return jsonify({'ok':True, 'estado':estado})

@app.route('/api/rrhh/historial-ausencias')
@login_required
@admin_required
def historial_ausencias():
    """Historial de ausencias/vacaciones con filtros (empleado, tipo, año, estado)."""
    empleado_id = request.args.get('empleado_id')
    tipo = request.args.get('tipo')
    anio = request.args.get('anio')
    estado = request.args.get('estado')
    con = get_db()
    sql = """SELECT n.*, e.nombre AS empleado_nombre, e.legajo AS empleado_legajo,
                    e.area AS empleado_area
             FROM empleados_novedades n
             LEFT JOIN empleados e ON e.id = n.empleado_id
             WHERE 1=1"""
    params = []
    if empleado_id:
        sql += " AND n.empleado_id=?"; params.append(empleado_id)
    if tipo:
        sql += " AND LOWER(n.tipo)=LOWER(?)"; params.append(tipo)
    if estado:
        sql += " AND n.estado=?"; params.append(estado)
    if anio:
        sql += " AND substr(n.fecha_desde,1,4)=?"; params.append(str(anio))
    sql += " ORDER BY n.fecha_desde DESC"
    rows = con.execute(sql, params).fetchall()
    # Traducir username del autorizador a nombre real
    user_cache = {}
    def _nombre_user(u):
        if not u: return None
        if u in user_cache: return user_cache[u]
        r = con.execute("SELECT nombre FROM usuarios WHERE UPPER(TRIM(username))=UPPER(?)", (u.strip(),)).fetchone()
        user_cache[u] = (r['nombre'] if r and r['nombre'] else u)
        return user_cache[u]
    out = []
    total_dias = 0
    for r in rows:
        d = dict(r)
        d['autorizada_por_nombre'] = _nombre_user(d.get('autorizada_por'))
        if d.get('estado') == 'autorizada' and d.get('dias'):
            total_dias += d['dias']
        out.append(d)
    con.close()
    return jsonify({'ausencias': out, 'total': len(out), 'total_dias_autorizados': total_dias})

@app.route('/api/rrhh/anios-ausencias')
@login_required
@admin_required
def anios_ausencias():
    """Años disponibles en el historial, para el filtro."""
    con = get_db()
    rows = con.execute("""SELECT DISTINCT substr(fecha_desde,1,4) AS anio
                          FROM empleados_novedades
                          WHERE fecha_desde IS NOT NULL AND fecha_desde != ''
                          ORDER BY anio DESC""").fetchall()
    con.close()
    return jsonify([r['anio'] for r in rows if r['anio']])

# ── Guardias de sábado ──
def _sabados_entre(desde, hasta):
    """Lista de fechas 'YYYY-MM-DD' de todos los sábados entre desde y hasta (inclusive)."""
    from datetime import datetime, timedelta
    d = datetime.strptime(desde, '%Y-%m-%d')
    h = datetime.strptime(hasta, '%Y-%m-%d')
    # Avanzar hasta el primer sábado (weekday 5)
    while d.weekday() != 5:
        d += timedelta(days=1)
    out = []
    while d <= h:
        out.append(d.strftime('%Y-%m-%d'))
        d += timedelta(days=7)
    return out

def _empleado_ausente(con, empleado_id, fecha):
    """Devuelve el tipo de ausencia si el empleado tiene una novedad autorizada
    que cubre esa fecha (vacaciones, licencia, etc.), o None."""
    if not empleado_id:
        return None
    r = con.execute("""SELECT tipo FROM empleados_novedades
        WHERE empleado_id=? AND estado='autorizada'
          AND fecha_desde <= ? AND fecha_hasta >= ?
        LIMIT 1""", (empleado_id, fecha, fecha)).fetchone()
    return r['tipo'] if r else None

@app.route('/api/guardias')
@login_required
def get_guardias():
    """Lista las guardias de sábado. Admin/RRHH ven todas las áreas (o la que pidan);
    el resto ve solo la de su propia área. Editar requiere el permiso puede_editar_guardias."""
    from datetime import date
    es_admin = session.get('rol') in ('admin', 'root')
    con = get_db()
    # ¿Este usuario puede EDITAR las guardias? (permiso granular, no el rol)
    perm = con.execute("SELECT puede_editar_guardias FROM usuarios WHERE username=?",
                       (session.get('username',''),)).fetchone()
    puede_editar = bool(perm and perm['puede_editar_guardias'])
    # Determinar el área que puede ver este usuario
    mi_area = None
    if not es_admin:
        emp = con.execute("SELECT area FROM empleados WHERE UPPER(TRIM(username_sistema))=UPPER(?)",
                          (session.get('username',''),)).fetchone()
        if not emp or not emp['area']:
            # Usuario sin ficha de empleado o sin área: no ve guardias (con aviso)
            con.close()
            return jsonify({'guardias': [], 'sin_vinculo': True,
                            'area': None,
                            'mensaje': 'Tu usuario no está vinculado a un empleado con área. Pedí a RRHH que lo configure.'})
        mi_area = emp['area']
    # El área a mostrar: admin puede elegir; usuario común solo la suya
    if es_admin:
        area = request.args.get('area', 'Mesa de Ayuda')
    else:
        area = mi_area
    desde = request.args.get('desde') or date.today().strftime('%Y-%m-%d')
    hasta = request.args.get('hasta') or f"{date.today().year}-12-31"
    # Mapa de guardias ya cargadas por fecha
    cargadas = {}
    for g in con.execute("SELECT * FROM guardias WHERE area=? AND fecha BETWEEN ? AND ?",
                         (area, desde, hasta)).fetchall():
        cargadas[g['fecha']] = dict(g)
    emps = {}
    nac = {}
    for e in con.execute("SELECT id, nombre, fecha_nacimiento FROM empleados").fetchall():
        emps[e['id']] = e['nombre']
        if e['fecha_nacimiento'] and len(str(e['fecha_nacimiento'])) >= 10:
            nac[e['id']] = str(e['fecha_nacimiento'])[5:10]  # 'MM-DD'

    def _es_cumple(eid, fecha):
        """True si la fecha (YYYY-MM-DD) coincide en mes-día con el nacimiento."""
        return bool(eid and eid in nac and fecha[5:10] == nac[eid])

    out = []
    for sab in _sabados_entre(desde, hasta):
        g = cargadas.get(sab, {})
        eid = g.get('empleado_id')
        rid = g.get('refuerzo_empleado_id')
        conflicto = _empleado_ausente(con, eid, sab)
        conflicto_ref = _empleado_ausente(con, rid, sab)
        out.append({
            'fecha': sab,
            'empleado_id': eid, 'empleado_nombre': emps.get(eid),
            'refuerzo_empleado_id': rid, 'refuerzo_nombre': emps.get(rid),
            'observaciones': g.get('observaciones'),
            'conflicto': conflicto,
            'conflicto_refuerzo': conflicto_ref,
            'cumple': _es_cumple(eid, sab),
            'cumple_refuerzo': _es_cumple(rid, sab),
            'consecutiva': False,  # se calcula abajo con la pasada completa
        })

    # ── Guardias consecutivas: mismo titular dos sábados seguidos ──
    # Incluye el sábado ANTERIOR al rango (no está en 'out' pero cuenta).
    from datetime import datetime as _dt, timedelta as _td
    if out:
        prev_fecha = (_dt.strptime(out[0]['fecha'], '%Y-%m-%d') - _td(days=7)).strftime('%Y-%m-%d')
        prev = con.execute("SELECT empleado_id FROM guardias WHERE area=? AND fecha=?",
                           (area, prev_fecha)).fetchone()
        prev_eid = prev['empleado_id'] if prev else None
        for i, g in enumerate(out):
            eid = g['empleado_id']
            if not eid:
                prev_eid = None
                continue
            ant = out[i-1]['empleado_id'] if i > 0 else prev_eid
            sig = out[i+1]['empleado_id'] if i+1 < len(out) else None
            if eid == ant or eid == sig:
                g['consecutiva'] = True

    # ── Equidad anual: sábados como titular por empleado en el año en curso ──
    anio = (desde or date.today().strftime('%Y-%m-%d'))[:4]
    equidad = [dict(r) for r in con.execute("""
        SELECT g.empleado_id, e.nombre, COUNT(*) AS sabados
        FROM guardias g LEFT JOIN empleados e ON e.id = g.empleado_id
        WHERE g.area=? AND substr(g.fecha,1,4)=? AND g.empleado_id IS NOT NULL
        GROUP BY g.empleado_id ORDER BY sabados DESC""", (area, anio)).fetchall()]

    # ── Fichas sin fecha de nacimiento entre quienes tienen guardias este año ──
    # (sin este dato, la validación de cumpleaños no puede chequearlos)
    sin_fecha_nac = sorted({emps.get(q['empleado_id'], '?') for q in equidad
                            if q['empleado_id'] not in nac})

    con.close()
    return jsonify({'area': area, 'desde': desde, 'hasta': hasta,
                    'guardias': out, 'es_admin': es_admin, 'editable': puede_editar,
                    'equidad': equidad, 'anio_equidad': anio,
                    'sin_fecha_nac': sin_fecha_nac})

@app.route('/api/guardias', methods=['POST'])
@login_required
def guardar_guardia():
    """Crea o actualiza la guardia de un sábado (upsert por fecha+area).
    Requiere el permiso puede_editar_guardias (no basta con ser admin)."""
    con = get_db()
    perm = con.execute("SELECT puede_editar_guardias FROM usuarios WHERE username=?",
                       (session.get('username',''),)).fetchone()
    if not (perm and perm['puede_editar_guardias']):
        con.close()
        return jsonify({'error': 'No tenés permiso para editar guardias'}), 403
    d = request.get_json() or {}
    fecha = d.get('fecha')
    area = d.get('area', 'Mesa de Ayuda')
    if not fecha:
        con.close()
        return jsonify({'error': 'falta la fecha'}), 400
    con.execute("""INSERT INTO guardias(fecha, area, empleado_id, refuerzo_empleado_id, observaciones)
        VALUES(?,?,?,?,?)
        ON CONFLICT(fecha, area) DO UPDATE SET
            empleado_id=excluded.empleado_id,
            refuerzo_empleado_id=excluded.refuerzo_empleado_id,
            observaciones=excluded.observaciones""",
        (fecha, area, d.get('empleado_id') or None,
         d.get('refuerzo_empleado_id') or None, d.get('observaciones', '')))
    con.commit()
    # Avisos post-guardado: vacaciones, cumpleaños y guardia consecutiva
    eid = d.get('empleado_id')
    conflicto = _empleado_ausente(con, eid, fecha)
    cumple = False
    consecutiva = False
    if eid:
        n = con.execute("SELECT fecha_nacimiento FROM empleados WHERE id=?", (eid,)).fetchone()
        if n and n['fecha_nacimiento'] and len(str(n['fecha_nacimiento'])) >= 10:
            cumple = (str(n['fecha_nacimiento'])[5:10] == fecha[5:10])
        from datetime import datetime as _dt, timedelta as _td
        f = _dt.strptime(fecha, '%Y-%m-%d')
        vecinos = [(f - _td(days=7)).strftime('%Y-%m-%d'), (f + _td(days=7)).strftime('%Y-%m-%d')]
        v = con.execute("""SELECT 1 FROM guardias WHERE area=? AND empleado_id=?
                           AND fecha IN (?,?) LIMIT 1""",
                        (area, eid, vecinos[0], vecinos[1])).fetchone()
        consecutiva = bool(v)
    con.close()
    return jsonify({'ok': True, 'conflicto': conflicto,
                    'cumple': cumple, 'consecutiva': consecutiva})

@app.route('/api/guardias/generar', methods=['POST'])
@login_required
def generar_guardias():
    """Precarga la rotación de titulares sobre un rango de sábados.
    Rota los empleados en orden, uno por sábado. NO pisa guardias ya cargadas
    salvo sobrescribir=True. El refuerzo no se toca (se carga a mano)."""
    con = get_db()
    perm = con.execute("SELECT puede_editar_guardias FROM usuarios WHERE username=?",
                       (session.get('username',''),)).fetchone()
    if not (perm and perm['puede_editar_guardias']):
        con.close()
        return jsonify({'error': 'No tenés permiso para editar guardias'}), 403
    d = request.get_json() or {}
    desde = d.get('desde')
    hasta = d.get('hasta')
    area = d.get('area', 'Mesa de Ayuda')
    rotacion = d.get('rotacion', [])  # lista de empleado_id en orden
    sobrescribir = bool(d.get('sobrescribir'))
    if not desde or not hasta or not rotacion:
        con.close()
        return jsonify({'error': 'Faltan desde, hasta o la rotación de empleados'}), 400
    sabados = _sabados_entre(desde, hasta)
    # Fechas de nacimiento para detectar cumpleaños en la generación
    nac = {}
    for e in con.execute("SELECT id, fecha_nacimiento FROM empleados").fetchall():
        if e['fecha_nacimiento'] and len(str(e['fecha_nacimiento'])) >= 10:
            nac[e['id']] = str(e['fecha_nacimiento'])[5:10]
    # Guardias ya cargadas en el rango (para no pisarlas si no se pide)
    ya = {g['fecha'] for g in con.execute(
        "SELECT fecha FROM guardias WHERE area=? AND fecha BETWEEN ? AND ? AND empleado_id IS NOT NULL",
        (area, desde, hasta)).fetchall()}
    asignadas = 0
    saltadas = 0
    conflictos = []
    for i, sab in enumerate(sabados):
        if sab in ya and not sobrescribir:
            saltadas += 1
            continue
        emp_id = rotacion[i % len(rotacion)]  # rotación cíclica
        con.execute("""INSERT INTO guardias(fecha, area, empleado_id)
            VALUES(?,?,?)
            ON CONFLICT(fecha, area) DO UPDATE SET empleado_id=excluded.empleado_id""",
            (sab, area, emp_id))
        asignadas += 1
        # Avisar si cae en vacaciones ya cargadas o en su cumpleaños
        aus = _empleado_ausente(con, emp_id, sab)
        if aus:
            conflictos.append({'fecha': sab, 'tipo': aus})
        if emp_id in nac and sab[5:10] == nac[emp_id]:
            conflictos.append({'fecha': sab, 'tipo': 'cumpleaños'})
    con.commit()
    con.close()
    aviso = None
    if len(rotacion) == 1:
        aviso = 'La rotación tiene UNA sola persona: todas las guardias serán consecutivas.'
    return jsonify({'ok': True, 'asignadas': asignadas, 'saltadas': saltadas,
                    'total_sabados': len(sabados), 'conflictos': conflictos,
                    'aviso': aviso})

@app.route('/api/guardias/areas')
@login_required
@admin_required
def get_guardias_areas():
    """Áreas distintas que ya tienen guardias cargadas (para el selector)."""
    con = get_db()
    rows = con.execute("SELECT DISTINCT area FROM guardias ORDER BY area").fetchall()
    con.close()
    areas = [r['area'] for r in rows] or ['Mesa de Ayuda']
    return jsonify(areas)

# ── Registro de uso del sistema ──
@app.route('/api/uso/registrar', methods=['POST'])
@login_required
def uso_registrar():
    """Registra la apertura de una sección (agregado diario por usuario).
    Llamado por el frontend en cada cambio de página. Nunca debe fallar ruidosamente."""
    try:
        d = request.get_json() or {}
        seccion = (d.get('seccion') or '').strip()[:50]
        if not seccion:
            return jsonify({'ok': True})  # silencioso: sin sección no registra
        con = get_db()
        con.execute("""INSERT INTO uso_secciones(fecha_dia, username, seccion, cantidad)
            VALUES(date('now','localtime'), ?, ?, 1)
            ON CONFLICT(fecha_dia, username, seccion)
            DO UPDATE SET cantidad = cantidad + 1""",
            (session.get('username', '?'), seccion))
        con.commit(); con.close()
    except Exception:
        pass  # el registro de uso jamás debe romper la navegación
    return jsonify({'ok': True})

@app.route('/api/uso/resumen')
@login_required
@admin_required
def uso_resumen():
    """Resumen de uso: por sección (30 días e histórico, usuarios únicos,
    última vez) y por usuario. Para detectar módulos muertos con datos."""
    con = get_db()
    por_seccion = [dict(r) for r in con.execute("""
        SELECT seccion,
               SUM(CASE WHEN fecha_dia >= date('now','-30 days') THEN cantidad ELSE 0 END) AS total_30d,
               SUM(cantidad) AS total_hist,
               COUNT(DISTINCT CASE WHEN fecha_dia >= date('now','-30 days') THEN username END) AS usuarios_30d,
               MAX(fecha_dia) AS ultima_vez
        FROM uso_secciones
        GROUP BY seccion
        ORDER BY total_30d DESC, total_hist DESC""").fetchall()]
    por_usuario = [dict(r) for r in con.execute("""
        SELECT username,
               SUM(CASE WHEN fecha_dia >= date('now','-30 days') THEN cantidad ELSE 0 END) AS total_30d,
               COUNT(DISTINCT CASE WHEN fecha_dia >= date('now','-30 days') THEN seccion END) AS secciones_30d,
               MAX(fecha_dia) AS ultima_vez
        FROM uso_secciones
        GROUP BY username
        ORDER BY total_30d DESC""").fetchall()]
    con.close()
    return jsonify({'por_seccion': por_seccion, 'por_usuario': por_usuario})

# ═══════════════ CONTABILIDAD (egresos + inflación) ═══════════════
EGRESO_CATEGORIAS = ['Gastos operativos', 'Sueldos y honorarios', 'Compras e inversión',
                     'Tránsito IP mayorista', 'Impuestos y tasas', 'Otros']

@app.route('/api/contabilidad/egresos')
@login_required
@requiere_permiso('contabilidad')
def get_egresos():
    """Lista egresos, opcionalmente filtrados por mes (YYYY-MM)."""
    mes = request.args.get('mes', '')
    con = get_db()
    if mes:
        rows = con.execute("""SELECT * FROM egresos WHERE substr(fecha,1,7)=?
                              ORDER BY fecha DESC""", (mes,)).fetchall()
    else:
        rows = con.execute("SELECT * FROM egresos ORDER BY fecha DESC LIMIT 200").fetchall()
    # Totales por categoría (del mes o global)
    if mes:
        tot = con.execute("""SELECT categoria, SUM(monto) s FROM egresos
                             WHERE substr(fecha,1,7)=? GROUP BY categoria""", (mes,)).fetchall()
    else:
        tot = con.execute("SELECT categoria, SUM(monto) s FROM egresos GROUP BY categoria").fetchall()
    con.close()
    return jsonify({
        'egresos': [dict(r) for r in rows],
        'por_categoria': {r['categoria']: round(r['s'] or 0) for r in tot},
        'categorias': EGRESO_CATEGORIAS,
    })

@app.route('/api/contabilidad/egresos', methods=['POST'])
@login_required
@requiere_permiso('contabilidad', 'crear')
def crear_egreso():
    d = request.get_json()
    fecha = (d.get('fecha') or '').strip()
    categoria = (d.get('categoria') or '').strip()
    monto = d.get('monto')
    if not fecha or not categoria or monto is None:
        return jsonify({'error': 'Faltan fecha, categoría o monto'}), 400
    con = get_db()
    con.execute("""INSERT INTO egresos(fecha, categoria, monto, descripcion, creado_por)
                   VALUES(?,?,?,?,?)""",
                (fecha, categoria, float(monto), d.get('descripcion', ''), session.get('nombre', '')))
    con.commit(); con.close()
    return jsonify({'ok': True})

@app.route('/api/contabilidad/egresos/<int:eid>', methods=['DELETE'])
@login_required
@requiere_permiso('contabilidad', 'eliminar')
def borrar_egreso(eid):
    con = get_db()
    con.execute("DELETE FROM egresos WHERE id=?", (eid,))
    con.commit(); con.close()
    return jsonify({'ok': True})

@app.route('/api/contabilidad/inflacion')
@login_required
@requiere_permiso('contabilidad')
def get_inflacion():
    con = get_db()
    rows = con.execute("SELECT * FROM inflacion_mensual ORDER BY mes DESC").fetchall()
    con.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/contabilidad/inflacion', methods=['POST'])
@login_required
@requiere_permiso('contabilidad', 'crear')
def guardar_inflacion():
    d = request.get_json()
    mes = (d.get('mes') or '').strip()  # YYYY-MM
    indice = d.get('indice_pct')
    if not mes or indice is None:
        return jsonify({'error': 'Faltan mes o índice'}), 400
    con = get_db()
    con.execute("""INSERT INTO inflacion_mensual(mes, indice_pct, creado_por) VALUES(?,?,?)
                   ON CONFLICT(mes) DO UPDATE SET indice_pct=excluded.indice_pct,
                   creado_por=excluded.creado_por""",
                (mes, float(indice), session.get('nombre', '')))
    con.commit(); con.close()
    return jsonify({'ok': True})

@app.route('/api/contabilidad/resumen')
@login_required
@requiere_permiso('contabilidad')
def contabilidad_resumen():
    """Resumen para el panel: ingresos vs egresos de los últimos 12 meses,
    usando egresos reales cargados + facturación real del ERP."""
    con = get_db()
    meses = _meses_atras(12)
    mes_ini = meses[0] + '-01'
    ingresos = {m: 0 for m in meses}
    for r in con.execute("""SELECT substr(fecha,1,7) m, SUM(monto) s FROM pagos
        WHERE origen='erp' AND estado_pago LIKE '%Pagado%' AND fecha >= ?
        GROUP BY m""", (mes_ini,)).fetchall():
        if r['m'] in ingresos:
            ingresos[r['m']] = round(r['s'] or 0)
    egresos = {m: 0 for m in meses}
    for r in con.execute("""SELECT substr(fecha,1,7) m, SUM(monto) s FROM egresos
        WHERE fecha >= ? GROUP BY m""", (mes_ini,)).fetchall():
        if r['m'] in egresos:
            egresos[r['m']] = round(r['s'] or 0)
    infl = {r['mes']: r['indice_pct'] for r in
            con.execute("SELECT mes, indice_pct FROM inflacion_mensual").fetchall()}
    con.close()
    return jsonify({
        'meses': meses,
        'ingresos': [{'mes': m, 'valor': ingresos[m]} for m in meses],
        'egresos': [{'mes': m, 'valor': egresos[m]} for m in meses],
        'ganancia': [{'mes': m, 'valor': ingresos[m] - egresos[m]} for m in meses],
        'inflacion': [{'mes': m, 'valor': infl.get(m)} for m in meses],
        'tiene_egresos': any(egresos.values()),
        'tiene_inflacion': bool(infl),
    })


# ═══════════════ PIZARRÓN DE TAREAS PERSONALES (post-its) ═══════════════
def _tarea_user():
    return session.get('username', '')

@app.route('/api/tareas')
@login_required
def get_tareas():
    """Tareas del usuario logueado (solo las propias)."""
    con = get_db()
    rows = [dict(r) for r in con.execute("""
        SELECT * FROM tareas_usuario WHERE username=?
        ORDER BY completada ASC, orden ASC, id DESC
    """, (_tarea_user(),)).fetchall()]
    con.close()
    return jsonify(rows)

@app.route('/api/tareas', methods=['POST'])
@login_required
def crear_tarea():
    d = request.get_json()
    texto = (d.get('texto') or '').strip()
    if not texto:
        return jsonify({'error': 'La tarea no puede estar vacía'}), 400
    color = d.get('color', 'amarillo')
    con = get_db()
    cur = con.execute("""INSERT INTO tareas_usuario(username, texto, color)
                         VALUES(?,?,?)""", (_tarea_user(), texto[:500], color))
    con.commit()
    tid = cur.lastrowid
    con.close()
    return jsonify({'ok': True, 'id': tid})

@app.route('/api/tareas/<int:tid>', methods=['PUT'])
@login_required
def actualizar_tarea(tid):
    d = request.get_json()
    con = get_db()
    # Solo el dueño puede tocar su tarea
    t = con.execute("SELECT username FROM tareas_usuario WHERE id=?", (tid,)).fetchone()
    if not t or t['username'] != _tarea_user():
        con.close()
        return jsonify({'error': 'No encontrada'}), 404
    campos, valores = [], []
    if 'texto' in d:
        campos.append('texto=?'); valores.append((d['texto'] or '').strip()[:500])
    if 'color' in d:
        campos.append('color=?'); valores.append(d['color'])
    if 'completada' in d:
        campos.append('completada=?'); valores.append(1 if d['completada'] else 0)
        campos.append("completado_at=?")
        valores.append(datetime.now().strftime('%Y-%m-%d %H:%M:%S') if d['completada'] else None)
    if 'orden' in d:
        campos.append('orden=?'); valores.append(int(d['orden']))
    if campos:
        valores.append(tid)
        con.execute(f"UPDATE tareas_usuario SET {', '.join(campos)} WHERE id=?", valores)
        con.commit()
    con.close()
    return jsonify({'ok': True})

@app.route('/api/tareas/<int:tid>', methods=['DELETE'])
@login_required
def borrar_tarea(tid):
    con = get_db()
    t = con.execute("SELECT username FROM tareas_usuario WHERE id=?", (tid,)).fetchone()
    if not t or t['username'] != _tarea_user():
        con.close()
        return jsonify({'error': 'No encontrada'}), 404
    # Las imágenes se borran ANTES que la nota: el servicio verifica la
    # pertenencia leyendo `tareas_usuario`, así que si la nota ya no está no
    # podría hacerlo y quedarían archivos huérfanos en disco.
    try:
        from pucara.db import sesion as _ses
        from pucara.services import factory as _fac
        with _ses() as _s:
            _fac.servicio_adjuntos(_s).borrar_los_de_la_nota(tid, _tarea_user())
    except Exception as _e:   # pragma: no cover
        print(f"[aviso] No se pudieron borrar los adjuntos de la nota {tid}: {_e}")
    con.execute("DELETE FROM tareas_usuario WHERE id=?", (tid,))
    con.commit(); con.close()
    return jsonify({'ok': True})

@app.route('/api/tareas/pendientes')
@login_required
def tareas_pendientes_count():
    """Cantidad de tareas pendientes del usuario (para el badge del dashboard)."""
    con = get_db()
    n = con.execute("SELECT COUNT(*) c FROM tareas_usuario WHERE username=? AND completada=0",
                    (_tarea_user(),)).fetchone()['c']
    con.close()
    return jsonify({'pendientes': n})


@app.route('/api/tero/sync', methods=['POST'])
@login_required
@requiere_permiso('reclamos', 'editar')
def tero_sync_manual():
    """Dispara la sincronización de reclamos desde Tero (manual)."""
    try:
        import tero_sync
        res = tero_sync.sync()
        return jsonify(res)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/reclamos/activos')
@login_required
@requiere_permiso('reclamos')
def reclamos_activos():
    """Reclamos abiertos en Tero, con el cliente vinculado. Para el panel operativo."""
    limite = int(request.args.get('limite', 60))
    con = get_db()
    filas = con.execute("""
        SELECT r.tero_id, r.titulo, r.nro_cliente, r.cliente_nombre, r.categoria,
               r.subcategoria, r.prioridad, r.canal, r.asign_to, r.created_by,
               r.despacho_tecnico, r.created_at, r.issue, r.departamento,
               c.id AS cliente_id, c.telefono, c.direccion, c.localidad, c.tipo_servicio
        FROM reclamos r
        LEFT JOIN clientes c ON c.nro_cliente = r.nro_cliente
        WHERE r.estado IN ('abierto','en_progreso')
        ORDER BY r.created_at DESC
        LIMIT ?""", (limite,)).fetchall()
    resumen = con.execute("""
        SELECT COUNT(*) total,
               SUM(CASE WHEN estado='en_progreso' THEN 1 ELSE 0 END) en_progreso,
               SUM(CASE WHEN asign_to IS NULL OR asign_to='' THEN 1 ELSE 0 END) sin_asignar
        FROM reclamos WHERE estado IN ('abierto','en_progreso')""").fetchone()
    con.close()
    return jsonify({
        'reclamos': [dict(f) for f in filas],
        'total': resumen['total'] or 0,
        'en_progreso': resumen['en_progreso'] or 0,
        'sin_asignar': resumen['sin_asignar'] or 0,
    })

@app.route('/api/reclamos/<int:tero_id>/detalle')
@login_required
@requiere_permiso('reclamos')
def reclamo_detalle(tero_id):
    """Detalle del reclamo traído EN VIVO de Tero: texto completo, conversación
    con el cliente y adjuntos. No se guarda: se consulta al abrirlo."""
    try:
        import tero_sync
        d = tero_sync.traer_detalle(tero_id)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    return jsonify(d)

@app.route('/api/reclamos/operadores')
@login_required
@requiere_permiso('reclamos')
def reclamos_operadores():
    """Padrón de operadores de Tero (username → nombre real)."""
    con = get_db()
    if not _table_exists(con, 'tero_usuarios'):
        con.close(); return jsonify({})
    filas = con.execute("SELECT username, nombre_completo FROM tero_usuarios").fetchall()
    con.close()
    return jsonify({f['username']: f['nombre_completo'] for f in filas})

@app.route('/api/reclamos/stats')
@login_required
@requiere_permiso('reclamos')
def reclamos_stats():
    """Estadísticas de reclamos: ranking de operadores, por categoría, estado,
    tiempos de resolución. Todo sobre la tabla local espejada de Tero."""
    con = get_db()
    dias = int(request.args.get('dias', 90))
    desde = f"-{dias} days"
    operadores = [dict(r) for r in con.execute("""
        SELECT created_by AS operador, COUNT(*) AS total,
               SUM(CASE WHEN estado='cerrado' THEN 1 ELSE 0 END) AS cerrados,
               SUM(CASE WHEN estado!='cerrado' THEN 1 ELSE 0 END) AS abiertos
        FROM reclamos
        WHERE created_by IS NOT NULL AND created_by != '' AND created_at >= date('now', ?)
        GROUP BY created_by ORDER BY total DESC LIMIT 20
    """, (desde,)).fetchall()]
    categorias = [dict(r) for r in con.execute("""
        SELECT categoria, COUNT(*) AS total FROM reclamos
        WHERE created_at >= date('now', ?) GROUP BY categoria ORDER BY total DESC
    """, (desde,)).fetchall()]
    canales = [dict(r) for r in con.execute("""
        SELECT canal, COUNT(*) AS total FROM reclamos
        WHERE created_at >= date('now', ?) GROUP BY canal ORDER BY total DESC
    """, (desde,)).fetchall()]
    kpi = con.execute("""
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN estado='cerrado' THEN 1 ELSE 0 END) AS cerrados,
               SUM(CASE WHEN estado!='cerrado' THEN 1 ELSE 0 END) AS abiertos,
               SUM(CASE WHEN nro_cliente IS NULL THEN 1 ELSE 0 END) AS sin_cruzar
        FROM reclamos WHERE created_at >= date('now', ?)
    """, (desde,)).fetchone()
    tiempo = con.execute("""
        SELECT AVG((julianday(closed_at) - julianday(created_at)) * 24) AS horas
        FROM reclamos WHERE estado='cerrado' AND closed_at IS NOT NULL
          AND created_at >= date('now', ?)
    """, (desde,)).fetchone()
    con.close()
    return jsonify({
        'kpi': dict(kpi),
        'tiempo_prom_horas': round(tiempo['horas'], 1) if tiempo['horas'] else None,
        'operadores': operadores, 'categorias': categorias, 'canales': canales,
    })

@app.route('/api/reclamos/cliente/<nro>')
@login_required
@requiere_permiso('reclamos')
def reclamos_cliente(nro):
    """Historial de reclamos de un cliente (por nro_cliente de Pucará)."""
    con = get_db()
    rows = [dict(r) for r in con.execute("""
        SELECT tero_id, titulo, categoria, subcategoria, estado, prioridad,
               created_by, asign_to, canal, created_at, closed_at, solucion, issue
        FROM reclamos WHERE nro_cliente=? ORDER BY created_at DESC
    """, (nro,)).fetchall()]
    con.close()
    return jsonify({'nro_cliente': nro, 'total': len(rows), 'reclamos': rows})


def _meses_atras(n):
    """Lista de n meses hacia atrás como 'YYYY-MM', del más viejo al más nuevo."""
    from datetime import date
    hoy = date.today()
    out = []
    y, m = hoy.year, hoy.month
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            m = 12; y -= 1
    return list(reversed(out))

@app.route('/api/informes/resumen')
@login_required
@requiere_permiso('informes')
def informes_resumen():
    """Métricas reales calculables hoy: altas/bajas, facturación, cobrabilidad,
    técnico interior. Todo sale de datos que Pucará ya tiene."""
    con = get_db()
    meses = _meses_atras(12)
    mes_ini = meses[0] + '-01'

    # ── KPIs de cabecera ──
    activos = con.execute("SELECT COUNT(*) c FROM clientes WHERE estado='activo'").fetchone()['c']
    # Altas y bajas del período (últimos 30 días)
    altas_30 = con.execute("""SELECT COUNT(*) c FROM clientes
        WHERE fecha_alta >= date('now','-30 days')""").fetchone()['c']
    bajas_30 = con.execute("""SELECT COUNT(*) c FROM clientes
        WHERE estado IN ('baja','rescision')
          AND COALESCE(fecha_baja, fecha_rescision) >= date('now','-30 days')""").fetchone()['c']
    # Altas/bajas de los 30 días previos (para el delta)
    altas_prev = con.execute("""SELECT COUNT(*) c FROM clientes
        WHERE fecha_alta >= date('now','-60 days') AND fecha_alta < date('now','-30 days')""").fetchone()['c']

    # ── Altas y bajas por mes (12 meses) ──
    altas_mes = {m: 0 for m in meses}
    for r in con.execute("""SELECT substr(fecha_alta,1,7) m, COUNT(*) c FROM clientes
        WHERE fecha_alta >= ? GROUP BY m""", (mes_ini,)).fetchall():
        if r['m'] in altas_mes:
            altas_mes[r['m']] = r['c']
    bajas_mes = {m: 0 for m in meses}
    for r in con.execute("""SELECT substr(COALESCE(fecha_baja,fecha_rescision),1,7) m, COUNT(*) c
        FROM clientes WHERE estado IN ('baja','rescision')
          AND COALESCE(fecha_baja,fecha_rescision) >= ? GROUP BY m""", (mes_ini,)).fetchall():
        if r['m'] in bajas_mes:
            bajas_mes[r['m']] = r['c']

    # ── Facturación mensual (pagos del ERP, solo pagados) ──
    fact_mes = {m: 0 for m in meses}
    for r in con.execute("""SELECT substr(fecha,1,7) m, SUM(monto) s FROM pagos
        WHERE origen='erp' AND estado_pago LIKE '%Pagado%' AND fecha >= ?
        GROUP BY m""", (mes_ini,)).fetchall():
        if r['m'] in fact_mes:
            fact_mes[r['m']] = round(r['s'] or 0)
    fact_actual = fact_mes[meses[-1]]
    fact_prev = fact_mes[meses[-2]] if len(meses) > 1 else 0

    # ── Cobrabilidad (pagado vs total de recibos del ERP, últimos 30 días) ──
    cob = con.execute("""SELECT
        SUM(CASE WHEN estado_pago LIKE '%Pagado%' THEN 1 ELSE 0 END) pagados,
        COUNT(*) total FROM pagos
        WHERE origen='erp' AND fecha >= date('now','-30 days')""").fetchone()
    cobrabilidad = round(100.0 * cob['pagados'] / cob['total'], 1) if cob['total'] else 0

    # ── Ranking de vendedores (altas por agente, últimos 90 días) ──
    vendedores = [dict(r) for r in con.execute("""SELECT agente nombre, COUNT(*) altas
        FROM clientes WHERE fecha_alta >= date('now','-90 days')
          AND agente IS NOT NULL AND TRIM(agente) != ''
        GROUP BY agente ORDER BY altas DESC LIMIT 8""").fetchall()]

    # ── Ranking de técnicos interior (trabajos realizados, últimos 90 días) ──
    tecnicos = [dict(r) for r in con.execute("""SELECT tecnico nombre,
        COUNT(*) trabajos, SUM(monto) monto
        FROM tecnico_interior_trabajos
        WHERE fecha_trabajo >= date('now','-90 days')
        GROUP BY tecnico ORDER BY trabajos DESC LIMIT 8""").fetchall()]

    con.close()
    def _serie(dic):
        return [{'mes': m, 'valor': dic[m]} for m in meses]
    return jsonify({
        'kpis': {
            'activos': activos,
            'altas_30': altas_30, 'altas_delta': altas_30 - altas_prev,
            'bajas_30': bajas_30,
            'facturacion': fact_actual,
            'facturacion_delta_pct': round(100.0*(fact_actual-fact_prev)/fact_prev, 1) if fact_prev else 0,
            'cobrabilidad': cobrabilidad,
        },
        'altas_bajas': {'altas': _serie(altas_mes), 'bajas': _serie(bajas_mes)},
        'facturacion': _serie(fact_mes),
        'vendedores': vendedores,
        'tecnicos': tecnicos,
        'meses': meses,
    })

@app.route('/api/novedades/<int:nid>/comprobante')
@login_required
@admin_required
def comprobante_vacaciones_pdf(nid):
    """Genera el PDF de notificación de autorización de vacaciones."""
    con = get_db()
    n = con.execute("""SELECT n.*, e.nombre AS emp_nombre, e.dni AS emp_dni,
                              e.legajo AS emp_legajo, e.puesto AS emp_puesto, e.area AS emp_area
                       FROM empleados_novedades n
                       LEFT JOIN empleados e ON e.id = n.empleado_id
                       WHERE n.id=?""", (nid,)).fetchone()
    if not n:
        con.close()
        return jsonify({'error': 'novedad no encontrada'}), 404
    if n['estado'] != 'autorizada':
        con.close()
        return jsonify({'error': 'la solicitud no está autorizada'}), 400
    # Traducir el username del autorizador a su nombre real (de la tabla usuarios)
    autoriz_nombre = n['autorizada_por']
    if autoriz_nombre:
        u = con.execute("SELECT nombre FROM usuarios WHERE UPPER(TRIM(username))=UPPER(?)",
                        (autoriz_nombre.strip(),)).fetchone()
        if u and u['nombre']:
            autoriz_nombre = u['nombre']
    con.close()
    try:
        from comprobante_vacaciones import generar_comprobante_vacaciones
    except ImportError:
        return jsonify({'error': 'falta el módulo comprobante_vacaciones.py'}), 500
    pdf = generar_comprobante_vacaciones({
        'empleado_nombre': n['emp_nombre'], 'empleado_dni': n['emp_dni'],
        'empleado_legajo': n['emp_legajo'], 'empleado_puesto': n['emp_puesto'],
        'empleado_area': n['emp_area'],
        'fecha_desde': n['fecha_desde'], 'fecha_hasta': n['fecha_hasta'],
        'dias': n['dias'], 'autorizada_por': autoriz_nombre,
        'fecha_autorizacion': n['fecha_autorizacion'], 'motivo': n['motivo'],
    })
    from flask import Response
    nombre_arch = f"vacaciones_{(n['emp_nombre'] or 'empleado').replace(' ','_')}_{n['fecha_desde']}.pdf"
    return Response(pdf, mimetype='application/pdf',
                    headers={'Content-Disposition': f'attachment; filename="{nombre_arch}"'})

@app.route('/api/novedades/pendientes')
@login_required
@admin_required
def novedades_pendientes():
    """Lista las solicitudes pendientes de autorización (para RRHH)."""
    con = get_db()
    rows = con.execute("""
        SELECT n.*, e.nombre AS empleado, e.area, e.puesto
        FROM empleados_novedades n JOIN empleados e ON e.id = n.empleado_id
        WHERE n.estado='pendiente' ORDER BY n.creado DESC
    """).fetchall()
    con.close()
    return jsonify([dict(r) for r in rows])

# ════════════════════════════════════════════════════════
# CATÁLOGO de diagnóstico / solución (editable)
# ════════════════════════════════════════════════════════
# ════════════════════════════════════════════════════════
# (Ping masivo eliminado — causaba locks y no se usaba.
#  El ping individual por dispositivo sigue disponible.)
# ════════════════════════════════════════════════════════

# ════════════════════════════════════════════════════════
# NOTIFICACIÓN DE AFECTADOS POR INCIDENCIA (importado de v6.2)
# ════════════════════════════════════════════════════════
def _calcular_afectados(con, iid):
    """Devuelve (incidencia_dict, lista_clientes) para una incidencia.
    Clientes afectados = por torre (con cascada de torres hijas) + por NAP.
    Reutilizado por el endpoint JSON y el export PDF."""
    inc = con.execute("SELECT * FROM incidencias WHERE id=?", (iid,)).fetchone()
    if not inc:
        return None, []
    inc = dict(inc)
    clientes = []
    campos = "id, nombre, nro_cliente, telefono, email, localidad, direccion, lat, lng, plan, tipo_servicio"
    # Por torre (con cascada de torres hijas)
    if inc.get('torre_id'):
        torres_afectadas = {inc['torre_id']}
        torres_dict = {t['id']: dict(t) for t in con.execute("SELECT id, torre_padre_id FROM torres").fetchall()}
        def _propagar(tid):
            for t2 in torres_dict.values():
                if t2.get('torre_padre_id') == tid and t2['id'] not in torres_afectadas:
                    torres_afectadas.add(t2['id'])
                    _propagar(t2['id'])
        _propagar(inc['torre_id'])
        ph = ','.join('?' * len(torres_afectadas))
        rows = con.execute(f"""SELECT {campos}
            FROM clientes WHERE torre_id IN ({ph}) AND estado='activo' ORDER BY nombre""",
            list(torres_afectadas)).fetchall()
        clientes += [dict(r) for r in rows]
    # Por NAP
    nap_nombres = []
    if inc.get('nap_nombre'):
        nap_nombres = [n.strip() for n in inc['nap_nombre'].split(',')]
    if inc.get('objeto_ids'):
        try:
            for nid in json.loads(inc['objeto_ids']):
                nap = con.execute("SELECT nombre FROM naps WHERE id=?", (nid,)).fetchone()
                if nap and nap['nombre'] not in nap_nombres:
                    nap_nombres.append(nap['nombre'])
        except Exception:
            pass
    for nap_n in nap_nombres:
        rows = con.execute(f"""SELECT {campos}
            FROM clientes WHERE nap=? AND estado='activo' ORDER BY nombre""", (nap_n,)).fetchall()
        for r in rows:
            if not any(c['id'] == r['id'] for c in clientes):
                clientes.append(dict(r))
    return inc, clientes

@app.route('/api/incidencias/<int:iid>/afectados')
@login_required
def incidencia_afectados(iid):
    """Lista clientes afectados por una incidencia (por torre con cascada o NAP)."""
    con = get_db()
    inc, clientes = _calcular_afectados(con, iid)
    con.close()
    if inc is None:
        return jsonify({'error':'Incidencia no encontrada'}), 404
    msg = f"Estimado cliente, le informamos que estamos trabajando en la resolución de: {inc.get('titulo','')}. Disculpe las molestias."
    return jsonify({
        'incidencia': inc,
        'total_afectados': len(clientes),
        'clientes': clientes,
        'mensaje_sugerido': msg,
        'telefonos': [c['telefono'] for c in clientes if c.get('telefono')],
    })

@app.route('/api/incidencias/<int:iid>/afectados/pdf')
@login_required
def incidencia_afectados_pdf(iid):
    """Genera un PDF con los clientes afectados (ubicación, teléfonos, coordenadas)."""
    con = get_db()
    inc, clientes = _calcular_afectados(con, iid)
    con.close()
    if inc is None:
        return jsonify({'error':'Incidencia no encontrada'}), 404
    try:
        from export_afectados import generar_pdf_afectados
    except ImportError:
        return jsonify({'error':'falta el módulo export_afectados.py'}), 500
    pdf = generar_pdf_afectados(inc, clientes)
    from flask import Response
    titulo = (inc.get('titulo') or 'incidencia').replace(' ', '_')[:40]
    nombre = f"afectados_{titulo}_{iid}.pdf"
    return Response(pdf, mimetype='application/pdf',
                    headers={'Content-Disposition': f'attachment; filename="{nombre}"'})

# ════════════════════════════════════════════════════════
# ASIGNAR TORRE POR PROXIMIDAD (importado de v6.2)
# ════════════════════════════════════════════════════════
@app.route('/api/clientes/asignar_torre_proximidad', methods=['POST'])
@login_required
def asignar_torre_proximidad():
    """Asigna torre_id a clientes inalámbricos sin torre según proximidad (máx N km)."""
    import math
    d = request.get_json() or {}
    max_dist = float(d.get('max_km', 5))
    solo_cliente_id = d.get('cliente_id')
    con = get_db()

    def _num(v):
        """Convierte a float seguro; None si no es válido."""
        try:
            f = float(v)
            return f if f != 0 else None
        except (TypeError, ValueError):
            return None

    # Torres con coordenadas válidas
    torres = []
    for t in con.execute("SELECT id, nombre, lat, lng FROM torres WHERE estado='activa'").fetchall():
        la, ln = _num(t['lat']), _num(t['lng'])
        if la is not None and ln is not None:
            torres.append({'id': t['id'], 'lat': la, 'lng': ln})

    if solo_cliente_id:
        rows = con.execute("SELECT id, lat, lng FROM clientes WHERE id=?", (solo_cliente_id,)).fetchall()
    else:
        rows = con.execute("""SELECT id, lat, lng FROM clientes
            WHERE tipo_servicio='inalambrico' AND estado='activo'
            AND (torre_id IS NULL OR torre_id = 0)""").fetchall()

    def _dist_km(lat1, lng1, lat2, lng2):
        R = 6371
        dlat = math.radians(lat2-lat1); dlng = math.radians(lng2-lng1)
        a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlng/2)**2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

    asignados = sin_torre = sin_coords = 0
    for c in rows:
        cla, cln = _num(c['lat']), _num(c['lng'])
        if cla is None or cln is None:
            sin_coords += 1
            continue
        mejor, mejor_dist = None, max_dist + 1
        for t in torres:
            try:
                dk = _dist_km(cla, cln, t['lat'], t['lng'])
            except Exception:
                continue
            if dk < mejor_dist:
                mejor, mejor_dist = t, dk
        if mejor and mejor_dist <= max_dist:
            con.execute("UPDATE clientes SET torre_id=? WHERE id=?", (mejor['id'], c['id']))
            asignados += 1
        else:
            sin_torre += 1
    con.commit(); con.close()
    return jsonify({'ok':True, 'asignados':asignados, 'sin_torre_cercana':sin_torre, 'sin_coordenadas':sin_coords})

# ════════════════════════════════════════════════════════
# TÉCNICOS INTERIOR (tercerizados) — trabajos y pago
# ════════════════════════════════════════════════════════
@app.route('/api/tecnico_interior/personal')
@login_required
def ti_personal():
    con = get_db()
    rows = con.execute("SELECT * FROM tecnico_interior_personal WHERE activo=1 ORDER BY nombre").fetchall()
    con.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/tecnico_interior/personal', methods=['POST'])
@login_required
@requiere_permiso('servicios')
def ti_crear_personal():
    d = request.get_json() or {}
    if not d.get('nombre'):
        return jsonify({'error':'nombre requerido'}), 400
    con = get_db()
    cur = con.execute("INSERT INTO tecnico_interior_personal(nombre, telefono, localidad) VALUES(?,?,?)",
                      (d['nombre'], d.get('telefono',''), d.get('localidad','')))
    con.commit(); con.close()
    return jsonify({'ok':True, 'id':cur.lastrowid})

@app.route('/api/tecnico_interior/personal/<int:pid>', methods=['PUT','DELETE'])
@login_required
@requiere_permiso('servicios')
def ti_editar_personal(pid):
    con = get_db()
    if request.method == 'DELETE':
        con.execute("UPDATE tecnico_interior_personal SET activo=0 WHERE id=?", (pid,))
    else:
        d = request.get_json() or {}
        con.execute("UPDATE tecnico_interior_personal SET nombre=?, telefono=?, localidad=? WHERE id=?",
                    (d.get('nombre'), d.get('telefono',''), d.get('localidad',''), pid))
    con.commit(); con.close()
    return jsonify({'ok':True})

@app.route('/api/tecnico_interior/tarifas')
@login_required
def ti_tarifas():
    con = get_db()
    rows = con.execute("SELECT * FROM tecnico_interior_tarifas WHERE activo=1 ORDER BY tipo_trabajo").fetchall()
    con.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/tecnico_interior/tarifas', methods=['POST'])
@login_required
@requiere_permiso('servicios')
def ti_crear_tarifa():
    d = request.get_json() or {}
    if not d.get('tipo_trabajo'):
        return jsonify({'error':'tipo requerido'}), 400
    con = get_db()
    cur = con.execute("INSERT INTO tecnico_interior_tarifas(tipo_trabajo, monto, por_metro) VALUES(?,?,?)",
                      (d['tipo_trabajo'], d.get('monto', 0), 1 if d.get('por_metro') else 0))
    con.commit(); con.close()
    return jsonify({'ok':True, 'id':cur.lastrowid})

@app.route('/api/tecnico_interior/tarifas/<int:tid>', methods=['PUT','DELETE'])
@login_required
@requiere_permiso('servicios')
def ti_editar_tarifa(tid):
    con = get_db()
    if request.method == 'DELETE':
        con.execute("UPDATE tecnico_interior_tarifas SET activo=0 WHERE id=?", (tid,))
    else:
        d = request.get_json() or {}
        con.execute("UPDATE tecnico_interior_tarifas SET tipo_trabajo=?, monto=?, por_metro=? WHERE id=?",
                    (d.get('tipo_trabajo'), d.get('monto', 0), 1 if d.get('por_metro') else 0, tid))
    con.commit(); con.close()
    return jsonify({'ok':True})

@app.route('/api/tecnico_interior/trabajos')
@login_required
def ti_trabajos():
    """Lista trabajos. Filtros: ?tecnico= &mes=YYYY-MM &pagado=0|1"""
    tecnico = request.args.get('tecnico','')
    mes = request.args.get('mes','')
    pagado = request.args.get('pagado','')
    con = get_db()
    sql = "SELECT * FROM tecnico_interior_trabajos WHERE 1=1"
    params = []
    if tecnico:
        sql += " AND tecnico=?"; params.append(tecnico)
    if mes:
        sql += " AND strftime('%Y-%m', fecha_trabajo)=?"; params.append(mes)
    if pagado != '':
        sql += " AND pagado=?"; params.append(int(pagado))
    sql += " ORDER BY fecha_trabajo DESC, id DESC"
    rows = con.execute(sql, params).fetchall()
    con.close()
    return jsonify([dict(r) for r in rows])

def _norm_tecnico(s):
    """Normaliza el nombre del técnico para comparar: mayúsculas, sin acentos,
    sin espacios de más. Evita que 'Zalazar Mariano ' != 'ZALAZAR MARIANO'."""
    import unicodedata
    s = (s or '').strip().upper()
    s = ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c))
    return ' '.join(s.split())  # colapsa espacios múltiples

# Técnico al que aplica el escalonado por volumen (comparado normalizado)
_ESCALON_TECNICO = _norm_tecnico('Zalazar Mariano')

# Reglas de escalón por grupo. Instalación: 6-8 -> >6, 9+ -> >9.
# Reparación: 4-7 -> >4, 8+ -> >8. Se evalúan de mayor a menor umbral.
_ESCALONES = {
    'instalacion': {
        'tipos': ['Instalación FTTH', 'Instalación FTTH > 6', 'Instalación FTTH > 9'],
        'reglas': [(9, 'Instalación FTTH > 9'), (6, 'Instalación FTTH > 6'), (0, 'Instalación FTTH')],
    },
    'reparacion': {
        'tipos': ['Reparación FTTH', 'Reparación FTTH > 4', 'Reparación FTTH > 8'],
        'reglas': [(8, 'Reparación FTTH > 8'), (4, 'Reparación FTTH > 4'), (0, 'Reparación FTTH')],
    },
}

def _recalcular_escalon_tecnico(con, tecnico, fecha):
    """Recalcula el tipo/monto de TODOS los trabajos FTTH de Zalazar en una fecha,
    según cuántos hizo ese día. Bidireccional: si baja el conteo, revierte al escalón menor.
    Solo aplica al técnico configurado y a los tipos FTTH (instalación/reparación)."""
    if _norm_tecnico(tecnico) != _ESCALON_TECNICO or not fecha:
        return
    for grupo in _ESCALONES.values():
        tipos = grupo['tipos']
        placeholders = ','.join('?' * len(tipos))
        # Traer los trabajos del grupo en la fecha (de cualquier técnico) y filtrar normalizado
        filas = con.execute(f"""SELECT id, tecnico FROM tecnico_interior_trabajos
            WHERE fecha_trabajo=? AND tipo_trabajo IN ({placeholders})""",
            (fecha, *tipos)).fetchall()
        filas = [f for f in filas if _norm_tecnico(f['tecnico']) == _ESCALON_TECNICO]
        total = len(filas)
        if total == 0:
            continue
        # Tipo objetivo según el total (primer umbral que cumple, de mayor a menor)
        tipo_objetivo = grupo['reglas'][-1][1]
        for umbral, tipo in grupo['reglas']:
            if total >= umbral:
                tipo_objetivo = tipo
                break
        tar = con.execute("SELECT monto FROM tecnico_interior_tarifas WHERE tipo_trabajo=? AND activo=1",
                          (tipo_objetivo,)).fetchone()
        monto_objetivo = tar['monto'] if tar else 0
        for f in filas:
            con.execute("UPDATE tecnico_interior_trabajos SET tipo_trabajo=?, monto=? WHERE id=?",
                       (tipo_objetivo, monto_objetivo, f['id']))

@app.route('/api/tecnico_interior/trabajos', methods=['POST'])
@login_required
def ti_crear_trabajo():
    d = request.get_json() or {}
    if not d.get('tecnico') or not d.get('fecha_trabajo'):
        return jsonify({'error':'técnico y fecha son obligatorios'}), 400
    con = get_db()
    metros = float(d.get('metros') or 0)
    # Buscar la tarifa del tipo de trabajo (monto y si es por metro)
    tar = con.execute("SELECT monto, por_metro FROM tecnico_interior_tarifas WHERE tipo_trabajo=? AND activo=1",
                      (d.get('tipo_trabajo'),)).fetchone()
    es_por_metro = bool(tar and tar['por_metro'])
    if es_por_metro:
        # Monto = metros × precio_por_metro (siempre se recalcula, no se acepta monto manual)
        if metros <= 0:
            con.close()
            return jsonify({'error':'Para Tendido FO (o tarifas por metro) tenés que indicar los metros'}), 400
        precio_metro = tar['monto'] if tar else 0
        monto = round(metros * precio_metro, 2)
    else:
        # Monto fijo: el que mandan, o el de la tarifa
        monto = d.get('monto')
        if monto in (None, '', 0):
            monto = tar['monto'] if tar else 0
    cur = con.execute("""INSERT INTO tecnico_interior_trabajos
        (tecnico, tipo_trabajo, monto, metros, cliente, cliente_id, localidad, fecha_trabajo, descripcion, creado_por)
        VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (d['tecnico'], d.get('tipo_trabajo'), monto, metros, d.get('cliente',''),
         d.get('cliente_id'), d.get('localidad',''), d['fecha_trabajo'], d.get('descripcion',''),
         session.get('username')))
    # Registrar en el historial del cliente vinculado
    if d.get('cliente_id'):
        try:
            motivo = d.get('descripcion','') or 'sin detalle'
            con.execute("""INSERT INTO historial(tipo,modulo,titulo,detalle,usuario)
                VALUES('trabajo_tecnico','servicios',?,?,?)""",
                (f"{d.get('tipo_trabajo','Trabajo')} — {d['tecnico']}",
                 f"cliente_id={d['cliente_id']}|Motivo: {motivo}|Fecha: {d['fecha_trabajo']}|Monto: ${monto}",
                 session.get('username')))
        except Exception:
            pass
    # Recalcular escalón por volumen (Zalazar): puede cambiar el tipo/monto de
    # este y de los demás trabajos FTTH del mismo día.
    _recalcular_escalon_tecnico(con, d['tecnico'], d['fecha_trabajo'])
    con.commit()
    # Releer el monto final por si el escalón lo cambió
    fila_final = con.execute("SELECT tipo_trabajo, monto FROM tecnico_interior_trabajos WHERE id=?",
                             (cur.lastrowid,)).fetchone()
    con.close()
    return jsonify({'ok':True, 'id':cur.lastrowid,
                    'monto': fila_final['monto'] if fila_final else monto,
                    'tipo_trabajo': fila_final['tipo_trabajo'] if fila_final else d.get('tipo_trabajo'),
                    'detalle': f'{metros}m × ${tar["monto"]}/m' if es_por_metro else None})

@app.route('/api/tecnico_interior/trabajos/<int:wid>', methods=['PUT','DELETE'])
@login_required
@requiere_permiso('servicios')
def ti_editar_trabajo(wid):
    con = get_db()
    # Guardar técnico/fecha ANTES de modificar, para recalcular ese día también
    prev = con.execute("SELECT tecnico, fecha_trabajo FROM tecnico_interior_trabajos WHERE id=?", (wid,)).fetchone()
    prev_tecnico = prev['tecnico'] if prev else None
    prev_fecha = prev['fecha_trabajo'] if prev else None
    if request.method == 'DELETE':
        con.execute("DELETE FROM tecnico_interior_trabajos WHERE id=?", (wid,))
        # Recalcular el día del trabajo borrado (el conteo bajó)
        _recalcular_escalon_tecnico(con, prev_tecnico, prev_fecha)
    else:
        d = request.get_json() or {}
        metros = float(d.get('metros') or 0)
        # Recalcular si es tarifa por metro
        tar = con.execute("SELECT monto, por_metro FROM tecnico_interior_tarifas WHERE tipo_trabajo=? AND activo=1",
                          (d.get('tipo_trabajo'),)).fetchone()
        if tar and tar['por_metro']:
            monto = round(metros * tar['monto'], 2) if metros > 0 else 0
        else:
            monto = d.get('monto', 0)
        con.execute("""UPDATE tecnico_interior_trabajos
            SET tecnico=?, tipo_trabajo=?, monto=?, metros=?, cliente=?, localidad=?, fecha_trabajo=?, descripcion=?
            WHERE id=?""",
            (d.get('tecnico'), d.get('tipo_trabajo'), monto, metros, d.get('cliente',''),
             d.get('localidad',''), d.get('fecha_trabajo'), d.get('descripcion',''), wid))
        # Recalcular tanto el día viejo como el nuevo (si cambió la fecha o el técnico)
        _recalcular_escalon_tecnico(con, prev_tecnico, prev_fecha)
        _recalcular_escalon_tecnico(con, d.get('tecnico'), d.get('fecha_trabajo'))
    con.commit(); con.close()
    return jsonify({'ok':True})

@app.route('/api/tecnico_interior/trabajos/<int:wid>/toggle_realizado', methods=['POST'])
@login_required
@requiere_permiso('servicios')
def ti_toggle_realizado(wid):
    con = get_db()
    t = con.execute("SELECT realizado, pagado FROM tecnico_interior_trabajos WHERE id=?", (wid,)).fetchone()
    if not t:
        con.close(); return jsonify({'error':'no encontrado'}), 404
    nuevo = 0 if t['realizado'] else 1
    # No se puede desmarcar realizado si ya está pagado
    if not nuevo and t['pagado']:
        con.close()
        return jsonify({'error':'No se puede marcar como no realizado un trabajo ya pagado'}), 400
    if nuevo:
        con.execute("UPDATE tecnico_interior_trabajos SET realizado=1, realizado_por=?, fecha_realizado=datetime('now','localtime') WHERE id=?",
                    (session.get('username'), wid))
    else:
        con.execute("UPDATE tecnico_interior_trabajos SET realizado=0, realizado_por=NULL, fecha_realizado=NULL WHERE id=?", (wid,))
    con.commit(); con.close()
    return jsonify({'ok':True, 'realizado':nuevo})

@app.route('/api/tecnico_interior/trabajos/<int:wid>/toggle_pago', methods=['POST'])
@login_required
@requiere_permiso('servicios')
def ti_toggle_pago(wid):
    con = get_db()
    t = con.execute("SELECT pagado, realizado FROM tecnico_interior_trabajos WHERE id=?", (wid,)).fetchone()
    if not t:
        con.close(); return jsonify({'error':'no encontrado'}), 404
    nuevo = 0 if t['pagado'] else 1
    # REGLA: no se puede pagar un trabajo que no está verificado como realizado
    if nuevo and not t['realizado']:
        con.close()
        return jsonify({'error':'No se puede pagar: el trabajo no está marcado como realizado'}), 400
    if nuevo:
        con.execute("UPDATE tecnico_interior_trabajos SET pagado=1, fecha_pago=datetime('now','localtime') WHERE id=?", (wid,))
    else:
        con.execute("UPDATE tecnico_interior_trabajos SET pagado=0, fecha_pago=NULL WHERE id=?", (wid,))
    con.commit(); con.close()
    return jsonify({'ok':True, 'pagado':nuevo})

@app.route('/api/tecnico_interior/reporte')
@login_required
def ti_reporte():
    """Reporte de pago agrupado por técnico. Filtro: ?mes=YYYY-MM &solo_impagos=1"""
    mes = request.args.get('mes','')
    solo_impagos = request.args.get('solo_impagos','') == '1'
    con = get_db()
    sql = """SELECT tecnico,
                COUNT(*) trabajos,
                COALESCE(SUM(monto),0) total,
                COALESCE(SUM(CASE WHEN pagado=0 THEN monto ELSE 0 END),0) pendiente_pago,
                COALESCE(SUM(CASE WHEN pagado=0 AND realizado=1 THEN monto ELSE 0 END),0) pagable,
                COALESCE(SUM(CASE WHEN pagado=0 AND realizado=0 THEN monto ELSE 0 END),0) sin_verificar
             FROM tecnico_interior_trabajos WHERE 1=1"""
    params = []
    if mes:
        sql += " AND strftime('%Y-%m', fecha_trabajo)=?"; params.append(mes)
    if solo_impagos:
        sql += " AND pagado=0"
    sql += " GROUP BY tecnico ORDER BY pendiente_pago DESC"
    rows = con.execute(sql, params).fetchall()
    con.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/tecnico_interior/pagos/<int:pid>/pdf')
@login_required
def ti_pago_pdf(pid):
    """Genera el comprobante de pago en PDF."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from io import BytesIO

    con = get_db()
    pago = con.execute("SELECT * FROM tecnico_interior_pagos WHERE id=?", (pid,)).fetchone()
    if not pago:
        con.close(); return jsonify({'error':'no encontrado'}), 404
    trabajos = con.execute(
        "SELECT * FROM tecnico_interior_trabajos WHERE pago_id=? ORDER BY fecha_trabajo", (pid,)).fetchall()
    con.close()

    def money(n):
        return '$' + format(n or 0, ',.0f').replace(',', '.')

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=20*mm, bottomMargin=20*mm,
                            leftMargin=18*mm, rightMargin=18*mm)
    styles = getSampleStyleSheet()
    h_title = ParagraphStyle('t', parent=styles['Title'], fontSize=18, textColor=colors.HexColor('#1a3d6b'))
    h_sub = ParagraphStyle('s', parent=styles['Normal'], fontSize=10, textColor=colors.HexColor('#666'))
    story = []

    story.append(Paragraph("ERLAN Telecomunicaciones S.A.", h_title))
    story.append(Paragraph("Comprobante de pago — Técnico interior", h_sub))
    story.append(Spacer(1, 10))

    # Datos del pago
    info = [
        ['Técnico:', pago['tecnico'], 'Fecha de pago:', pago['fecha_pago'] or '—'],
        ['Período:', f"{pago['periodo_desde'] or '—'} a {pago['periodo_hasta'] or '—'}",
         'Comprobante N°:', str(pago['id'])],
    ]
    ti = Table(info, colWidths=[28*mm, 70*mm, 32*mm, 40*mm])
    ti.setStyle(TableStyle([
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica'),
        ('FONTSIZE', (0,0), (-1,-1), 9),
        ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
        ('FONTNAME', (2,0), (2,-1), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
    ]))
    story.append(ti)
    story.append(Spacer(1, 12))

    # Tabla de trabajos
    data = [['Fecha', 'Tipo', 'Cliente', 'Monto']]
    for t in trabajos:
        data.append([
            t['fecha_trabajo'] or '—',
            t['tipo_trabajo'] or '—',
            (t['cliente'] or '—')[:45],
            money(t['monto']),
        ])
    data.append(['', '', 'TOTAL', money(pago['monto_total'])])

    tabla = Table(data, colWidths=[24*mm, 38*mm, 78*mm, 30*mm], repeatRows=1)
    tabla.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1a3d6b')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 9),
        ('ALIGN', (3,0), (3,-1), 'RIGHT'),
        ('ROWBACKGROUNDS', (0,1), (-1,-2), [colors.white, colors.HexColor('#f2f6fb')]),
        ('LINEBELOW', (0,0), (-1,0), 0.5, colors.HexColor('#1a3d6b')),
        ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor('#e8eef6')),
        ('FONTNAME', (0,-1), (-1,-1), 'Helvetica-Bold'),
        ('FONTSIZE', (0,-1), (-1,-1), 11),
        ('TOPPADDING', (0,1), (-1,-1), 4),
        ('BOTTOMPADDING', (0,1), (-1,-1), 4),
    ]))
    story.append(tabla)
    story.append(Spacer(1, 10))
    story.append(Paragraph(f"<b>Total abonado: {money(pago['monto_total'])}</b> — {pago['cantidad_trabajos']} trabajo(s)",
                           ParagraphStyle('tot', parent=styles['Normal'], fontSize=12)))
    if pago['observaciones']:
        story.append(Spacer(1, 8))
        story.append(Paragraph(f"Observaciones: {pago['observaciones']}", h_sub))
    story.append(Spacer(1, 25))
    # Firmas
    firmas = Table([['_______________________', '_______________________'],
                    ['Recibí conforme (técnico)', 'Pagó (ERLAN)']],
                   colWidths=[85*mm, 85*mm])
    firmas.setStyle(TableStyle([
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('FONTSIZE', (0,0), (-1,-1), 8),
        ('TEXTCOLOR', (0,1), (-1,1), colors.HexColor('#666')),
        ('TOPPADDING', (0,1), (-1,1), 2),
    ]))
    story.append(firmas)

    doc.build(story)
    buf.seek(0)
    from flask import send_file
    return send_file(buf, mimetype='application/pdf', as_attachment=True,
                     download_name=f"pago_{pago['tecnico'].replace(' ','_')}_{pago['fecha_pago']}.pdf")

def _ti_pagables(con, tecnico, desde='', hasta=''):
    """Devuelve los trabajos pagables (realizados, no pagados) de un técnico en un rango."""
    sql = """SELECT id, fecha_trabajo, tipo_trabajo, cliente, monto
             FROM tecnico_interior_trabajos
             WHERE tecnico=? AND realizado=1 AND pagado=0"""
    params = [tecnico]
    if desde:
        sql += " AND fecha_trabajo >= ?"; params.append(desde)
    if hasta:
        sql += " AND fecha_trabajo <= ?"; params.append(hasta)
    sql += " ORDER BY fecha_trabajo"
    return con.execute(sql, params).fetchall()

@app.route('/api/tecnico_interior/prepago')
@login_required
@requiere_permiso('servicios')
def ti_prepago():
    """Lista los trabajos a pagar SIN registrar el pago (para conciliación)."""
    tecnico = request.args.get('tecnico','')
    desde = request.args.get('desde','')
    hasta = request.args.get('hasta','')
    if not tecnico:
        return jsonify({'error':'técnico requerido'}), 400
    con = get_db()
    rows = _ti_pagables(con, tecnico, desde, hasta)
    con.close()
    trabajos = [dict(r) for r in rows]
    return jsonify({
        'tecnico': tecnico, 'desde': desde, 'hasta': hasta,
        'trabajos': trabajos,
        'total': sum(t['monto'] or 0 for t in trabajos),
        'cantidad': len(trabajos),
    })

@app.route('/api/tecnico_interior/prepago/pdf')
@login_required
@requiere_permiso('servicios')
def ti_prepago_pdf():
    """Genera el PDF de pre-pago (mismo formato que el comprobante, marcado PRE-PAGO, sin registrar)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from io import BytesIO

    tecnico = request.args.get('tecnico','')
    desde = request.args.get('desde','')
    hasta = request.args.get('hasta','')
    if not tecnico:
        return jsonify({'error':'técnico requerido'}), 400
    con = get_db()
    rows = _ti_pagables(con, tecnico, desde, hasta)
    con.close()
    if not rows:
        return jsonify({'error':'sin trabajos para pre-pago'}), 400

    def money(n):
        return '$' + format(n or 0, ',.0f').replace(',', '.')
    total = sum(r['monto'] or 0 for r in rows)
    fechas = [r['fecha_trabajo'] for r in rows if r['fecha_trabajo']]
    p_desde = desde or (min(fechas) if fechas else '')
    p_hasta = hasta or (max(fechas) if fechas else '')

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=20*mm, bottomMargin=20*mm,
                            leftMargin=18*mm, rightMargin=18*mm)
    styles = getSampleStyleSheet()
    h_title = ParagraphStyle('t', parent=styles['Title'], fontSize=18, textColor=colors.HexColor('#1a3d6b'))
    h_sub = ParagraphStyle('s', parent=styles['Normal'], fontSize=10, textColor=colors.HexColor('#666'))
    story = []
    story.append(Paragraph("ERLAN Telecomunicaciones S.A.", h_title))
    story.append(Paragraph("PRE-PAGO (borrador para conciliación) — Técnico interior", h_sub))
    # Banda de aviso
    aviso = Table([['DOCUMENTO PROVISORIO — NO REGISTRA EL PAGO. Para que el técnico concilie antes de confirmar.']],
                  colWidths=[174*mm])
    aviso.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#fff3cd')),
        ('TEXTCOLOR', (0,0), (-1,-1), colors.HexColor('#856404')),
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 9),
        ('TOPPADDING', (0,0), (-1,-1), 5), ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
    ]))
    story.append(Spacer(1, 8)); story.append(aviso); story.append(Spacer(1, 10))
    info = [['Técnico:', tecnico, 'Período:', f"{p_desde or '—'} a {p_hasta or '—'}"]]
    ti = Table(info, colWidths=[28*mm, 75*mm, 28*mm, 43*mm])
    ti.setStyle(TableStyle([
        ('FONTSIZE', (0,0), (-1,-1), 9),
        ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
        ('FONTNAME', (2,0), (2,-1), 'Helvetica-Bold'),
    ]))
    story.append(ti); story.append(Spacer(1, 12))
    data = [['Fecha', 'Tipo', 'Cliente', 'Monto']]
    for r in rows:
        data.append([r['fecha_trabajo'] or '—', r['tipo_trabajo'] or '—',
                     (r['cliente'] or '—')[:45], money(r['monto'])])
    data.append(['', '', 'TOTAL', money(total)])
    tabla = Table(data, colWidths=[24*mm, 38*mm, 78*mm, 30*mm], repeatRows=1)
    tabla.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#856404')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 9),
        ('ALIGN', (3,0), (3,-1), 'RIGHT'),
        ('ROWBACKGROUNDS', (0,1), (-1,-2), [colors.white, colors.HexColor('#fdf9ef')]),
        ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor('#f5e6c5')),
        ('FONTNAME', (0,-1), (-1,-1), 'Helvetica-Bold'),
        ('FONTSIZE', (0,-1), (-1,-1), 11),
        ('TOPPADDING', (0,1), (-1,-1), 4), ('BOTTOMPADDING', (0,1), (-1,-1), 4),
    ]))
    story.append(tabla); story.append(Spacer(1, 10))
    story.append(Paragraph(f"<b>Total a conciliar: {money(total)}</b> — {len(rows)} trabajo(s)",
                           ParagraphStyle('tot', parent=styles['Normal'], fontSize=12)))
    story.append(Spacer(1, 20))
    firmas = Table([['_______________________', '_______________________'],
                    ['Conformidad del técnico', 'ERLAN']],
                   colWidths=[85*mm, 85*mm])
    firmas.setStyle(TableStyle([
        ('ALIGN', (0,0), (-1,-1), 'CENTER'), ('FONTSIZE', (0,0), (-1,-1), 8),
        ('TEXTCOLOR', (0,1), (-1,1), colors.HexColor('#666')),
    ]))
    story.append(firmas)
    doc.build(story)
    buf.seek(0)
    from flask import send_file
    return send_file(buf, mimetype='application/pdf', as_attachment=True,
                     download_name=f"PREPAGO_{tecnico.replace(' ','_')}_{p_desde}_{p_hasta}.pdf")

@app.route('/api/tecnico_interior/pagar', methods=['POST'])
@login_required
@requiere_permiso('servicios')
def ti_pagar():
    """Crea un pago (recibo) que agrupa trabajos. Recibe:
    - tecnico
    - ids: lista de ids de trabajos a pagar (opcional; si no, todos los pagables del técnico/mes)
    - mes: filtro opcional
    - fecha_pago, observaciones
    Solo paga trabajos verificados como realizados."""
    d = request.get_json() or {}
    tecnico = d.get('tecnico')
    if not tecnico:
        return jsonify({'error':'técnico requerido'}), 400
    ids = d.get('ids')
    mes = d.get('mes','')
    desde = d.get('desde','')
    hasta = d.get('hasta','')
    fecha_pago = d.get('fecha_pago') or _now()[:10]
    obs = d.get('observaciones','')
    con = get_db()
    # Determinar qué trabajos pagar (solo realizados y no pagados)
    if ids:
        ph = ','.join('?'*len(ids))
        sql = f"SELECT id, monto, fecha_trabajo FROM tecnico_interior_trabajos WHERE id IN ({ph}) AND realizado=1 AND pagado=0"
        rows = con.execute(sql, ids).fetchall()
    else:
        sql = "SELECT id, monto, fecha_trabajo FROM tecnico_interior_trabajos WHERE tecnico=? AND realizado=1 AND pagado=0"
        params = [tecnico]
        if mes:
            sql += " AND strftime('%Y-%m', fecha_trabajo)=?"; params.append(mes)
        if desde:
            sql += " AND fecha_trabajo >= ?"; params.append(desde)
        if hasta:
            sql += " AND fecha_trabajo <= ?"; params.append(hasta)
        rows = con.execute(sql, params).fetchall()
    if not rows:
        con.close()
        return jsonify({'error':'No hay trabajos verificados pendientes para pagar'}), 400
    monto_total = sum(r['monto'] or 0 for r in rows)
    fechas = [r['fecha_trabajo'] for r in rows if r['fecha_trabajo']]
    periodo_desde = min(fechas) if fechas else ''
    periodo_hasta = max(fechas) if fechas else ''
    # Crear el recibo de pago
    cur = con.execute("""INSERT INTO tecnico_interior_pagos
        (tecnico, fecha_pago, monto_total, cantidad_trabajos, periodo_desde, periodo_hasta, observaciones, creado_por)
        VALUES(?,?,?,?,?,?,?,?)""",
        (tecnico, fecha_pago, monto_total, len(rows), periodo_desde, periodo_hasta, obs, session.get('username')))
    pago_id = cur.lastrowid
    # Marcar los trabajos como pagados y vincularlos al recibo
    trabajo_ids = [r['id'] for r in rows]
    ph = ','.join('?'*len(trabajo_ids))
    con.execute(f"""UPDATE tecnico_interior_trabajos
        SET pagado=1, fecha_pago=?, pago_id=? WHERE id IN ({ph})""",
        [fecha_pago, pago_id] + trabajo_ids)
    con.commit(); con.close()
    return jsonify({'ok':True, 'pago_id':pago_id, 'monto_total':monto_total, 'cantidad':len(rows)})

@app.route('/api/tecnico_interior/pagos')
@login_required
def ti_pagos():
    """Historial de pagos. Filtros: ?tecnico= &fecha=YYYY-MM-DD &mes=YYYY-MM"""
    tecnico = request.args.get('tecnico','')
    fecha = request.args.get('fecha','')
    mes = request.args.get('mes','')
    con = get_db()
    sql = "SELECT * FROM tecnico_interior_pagos WHERE 1=1"
    params = []
    if tecnico:
        sql += " AND tecnico=?"; params.append(tecnico)
    if fecha:
        sql += " AND fecha_pago=?"; params.append(fecha)
    if mes:
        sql += " AND strftime('%Y-%m', fecha_pago)=?"; params.append(mes)
    sql += " ORDER BY fecha_pago DESC, id DESC"
    rows = con.execute(sql, params).fetchall()
    con.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/tecnico_interior/pagos/<int:pid>')
@login_required
def ti_pago_detalle(pid):
    """Detalle de un pago: el recibo + los trabajos que incluyó."""
    con = get_db()
    pago = con.execute("SELECT * FROM tecnico_interior_pagos WHERE id=?", (pid,)).fetchone()
    if not pago:
        con.close(); return jsonify({'error':'no encontrado'}), 404
    trabajos = con.execute(
        "SELECT * FROM tecnico_interior_trabajos WHERE pago_id=? ORDER BY fecha_trabajo", (pid,)).fetchall()
    con.close()
    d = dict(pago)
    d['trabajos'] = [dict(t) for t in trabajos]
    return jsonify(d)

@app.route('/api/tecnico_interior/marcar_pagado', methods=['POST'])
@login_required
@requiere_permiso('servicios')
def ti_marcar_pagado():
    """(Compat) Redirige al nuevo sistema de pagos como recibo."""
    return ti_pagar()

@app.route('/api/catalogo/<tipo>')
@login_required
def get_catalogo(tipo):
    if tipo not in ('diagnostico','solucion'):
        return jsonify({'error':'tipo inválido'}), 400
    con = get_db()
    rows = con.execute(
        "SELECT * FROM catalogo_servicio WHERE tipo=? AND activo=1 ORDER BY orden, nombre", (tipo,)
    ).fetchall()
    con.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/catalogo', methods=['POST'])
@login_required
@admin_required
def crear_catalogo():
    data = request.get_json() or {}
    tipo, nombre = data.get('tipo'), data.get('nombre','').strip()
    if tipo not in ('diagnostico','solucion') or not nombre:
        return jsonify({'error':'datos inválidos'}), 400
    con = get_db()
    cur = con.execute("INSERT INTO catalogo_servicio(tipo,nombre,orden) VALUES(?,?,999)", (tipo, nombre))
    con.commit(); con.close()
    return jsonify({'ok':True, 'id':cur.lastrowid})

@app.route('/api/catalogo/<int:cid>', methods=['PUT','DELETE'])
@login_required
@admin_required
def editar_catalogo(cid):
    con = get_db()
    if request.method == 'DELETE':
        con.execute("UPDATE catalogo_servicio SET activo=0 WHERE id=?", (cid,))
    else:
        data = request.get_json() or {}
        if 'nombre' in data:
            con.execute("UPDATE catalogo_servicio SET nombre=? WHERE id=?", (data['nombre'].strip(), cid))
    con.commit(); con.close()
    return jsonify({'ok':True})

@app.route('/api/estadisticas/problemas_recurrentes')
@login_required
def estadisticas_problemas_recurrentes():
    """Ranking de diagnósticos y soluciones más frecuentes en servicios técnicos."""
    periodo = request.args.get('periodo','12')
    con = get_db()
    filtro, params = "", []
    if periodo != 'todo':
        filtro = " AND fecha_creacion >= date('now','localtime',?)"
        params.append(f'-{int(periodo)} months')

    diag = con.execute(f"""
        SELECT diagnostico AS nombre, COUNT(*) c FROM servicios
        WHERE tipo='servicio_tecnico' AND diagnostico IS NOT NULL AND diagnostico!='' {filtro}
        GROUP BY diagnostico ORDER BY c DESC
    """, params).fetchall()
    sol = con.execute(f"""
        SELECT solucion_aplicada AS nombre, COUNT(*) c FROM servicios
        WHERE tipo='servicio_tecnico' AND solucion_aplicada IS NOT NULL AND solucion_aplicada!='' {filtro}
        GROUP BY solucion_aplicada ORDER BY c DESC
    """, params).fetchall()
    # Cuántos servicios técnicos están sin clasificar (para saber cobertura)
    sin_diag = con.execute(f"""
        SELECT COUNT(*) FROM servicios
        WHERE tipo='servicio_tecnico' AND (diagnostico IS NULL OR diagnostico='') {filtro}
    """, params).fetchone()[0]
    con.close()
    return jsonify({
        'diagnosticos': [{'nombre':r['nombre'],'cantidad':r['c']} for r in diag],
        'soluciones': [{'nombre':r['nombre'],'cantidad':r['c']} for r in sol],
        'sin_clasificar': sin_diag,
    })

# ─── HELPERS ──────────────────────────────────────────────────────
def log(tipo, titulo, detalle='', modulo=''):
    try:
        usuario = session.get('username', 'sistema')
        con = get_db()
        con.execute("INSERT INTO historial(tipo,modulo,titulo,detalle,usuario) VALUES(?,?,?,?,?)",
                    (tipo, modulo, titulo, detalle, usuario))
        con.commit()
        con.close()
    except: pass


def estado_actual(con, tabla, id_, campos=None):
    """Foto de una fila ANTES de modificarla, para poder auditar el cambio.

    Se llama con la conexión que la ruta ya tiene abierta: abrir otra sobre el
    mismo archivo SQLite da "database is locked".
    """
    try:
        fila = con.execute(f"SELECT * FROM {tabla} WHERE id=?", (id_,)).fetchone()
        if fila is None:
            return {}
        d = dict(fila)
        return {k: d[k] for k in campos if k in d} if campos else d
    except Exception:
        return {}


def auditar_cambio(con, modulo, entidad, id_, antes, despues, campos=None):
    """Registra QUÉ cambió, de QUÉ a QUÉ y QUIÉN lo hizo.

    El plan estratégico (§21) pide valor anterior y valor nuevo; hasta ahora la
    columna `diff` de `historial` existía sin usarse. La lógica de comparación
    vive en pucara/services/auditoria.py y es la misma que usan los módulos
    nuevos — acá sólo cambia quién escribe, porque las rutas heredadas tienen su
    propia conexión sqlite3.

    Devuelve True si hubo algo que registrar. Nunca levanta excepción: la
    auditoría no puede tumbar la operación que la generó.
    """
    try:
        from pucara.services.auditoria import calcular_diff
        dif = calcular_diff(antes or {}, despues or {}, campos)
        if not dif.hubo_cambios:
            return False
        con.execute(
            "INSERT INTO historial(tipo,modulo,titulo,detalle,diff,usuario) VALUES(?,?,?,?,?,?)",
            ('mod', modulo, f'{entidad} #{id_}: {dif.resumen()}',
             '\n'.join(str(c) for c in dif.cambios), dif.a_json(),
             session.get('username', 'sistema')))
        return True
    except Exception as e:
        print(f"[aviso] No se pudo auditar {entidad} #{id_}: {e}")
        return False

def notif(tipo, titulo, detalle=''):
    try:
        con = get_db()
        existe = con.execute("SELECT id FROM notificaciones WHERE titulo=? AND DATE(fecha)=DATE('now','localtime') AND leida=0",
                             (titulo,)).fetchone()
        if not existe:
            con.execute("INSERT INTO notificaciones(tipo,titulo,detalle) VALUES(?,?,?)",
                        (tipo, titulo, detalle))
            con.commit()
        con.close()
    except: pass

# ─── PÁGINAS ──────────────────────────────────────────────────────
@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect('/login')
    return render_template('index.html')

@app.route('/mobile')
def mobile():
    if 'user_id' not in session:
        return redirect('/login')
    return render_template('mobile.html')

# ── Rate limiting del login (anti fuerza bruta) ──
# Simple, en memoria: cuenta intentos fallidos por IP y bloquea temporalmente.
# No reemplaza una VPN, pero frena los bots que martillan el login.
import time as _time
_login_intentos = {}   # ip -> [(timestamp, ...)]
LOGIN_MAX_INTENTOS = 5         # intentos fallidos permitidos
LOGIN_VENTANA = 300           # en esta ventana (segundos) = 5 min
LOGIN_BLOQUEO = 900           # bloqueo tras superar el límite (segundos) = 15 min

_PROXIES_CONFIABLES = {'127.0.0.1', '::1'}  # Caddy corre en el mismo host (ver run_server.py)

def _login_ip():
    # Solo confiamos en X-Forwarded-For si el pedido llegó de un proxy conocido
    # (Caddy, en 127.0.0.1). Si no, cualquiera podría mandar ese header con un
    # valor inventado y esquivar el bloqueo por fuerza bruta.
    # Además, tomamos el ÚLTIMO tramo del header: Caddy AGREGA la IP real del
    # cliente al final de X-Forwarded-For (no reemplaza lo que venga antes), así
    # que el primer valor sigue siendo controlable por quien hace el pedido.
    if request.remote_addr in _PROXIES_CONFIABLES:
        xff = request.headers.get('X-Forwarded-For', '')
        if xff:
            return xff.split(',')[-1].strip()
    return request.remote_addr

def _login_bloqueado(ip):
    ahora = _time.time()
    intentos = _login_intentos.get(ip, [])
    # Limpiar intentos viejos (fuera de la ventana)
    intentos = [t for t in intentos if ahora - t < LOGIN_VENTANA]
    _login_intentos[ip] = intentos
    if len(intentos) >= LOGIN_MAX_INTENTOS:
        # ¿Cuánto falta para desbloquear?
        ultimo = max(intentos)
        if ahora - ultimo < LOGIN_BLOQUEO:
            return int(LOGIN_BLOQUEO - (ahora - ultimo))
    return 0

def _login_fallo(ip):
    _login_intentos.setdefault(ip, []).append(_time.time())

def _login_exito(ip):
    _login_intentos.pop(ip, None)  # limpiar al entrar bien

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        ip = _login_ip()
        espera = _login_bloqueado(ip)
        if espera > 0:
            return jsonify({'error': f'Demasiados intentos fallidos. Esperá {espera//60+1} minuto(s) antes de reintentar.'}), 429
        d = request.get_json() or request.form
        con = get_db()
        u = con.execute("SELECT * FROM usuarios WHERE username=? AND activo=1",
                        (d.get('username',''),)).fetchone()
        con.close()
        if u and check_password_hash(u['password'], d.get('password','')):
            _login_exito(ip)
            session.update({'user_id':u['id'],'username':u['username'],
                            'nombre':u['nombre'],'rol':u['rol']})
            return jsonify({'ok':True,'rol':u['rol'],'nombre':u['nombre']})
        _login_fallo(ip)
        return jsonify({'error':'Credenciales incorrectas'}), 401
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

@app.route('/api/me')
@login_required
def me():
    return jsonify({'id':session.get('user_id'),'username':session['username'],'nombre':session['nombre'],'rol':session['rol']})

# ─── DASHBOARD ────────────────────────────────────────────────────
# ─── ESTADO DE SERVICIOS GRANDES (páginas de estado oficiales) ────
# Lista editable: (nombre, URL del summary.json estilo Statuspage).
# Para agregar/sacar servicios, editá esta lista.
SERVICIOS_STATUS = [
    # (nombre, url, tipo)  — tipo: 'statuspage' | 'aws'
    ('Cloudflare',   'https://www.cloudflarestatus.com/api/v2/summary.json', 'statuspage'),
    ('MercadoPago',  'https://status.mercadopago.com/api/v2/summary.json',   'statuspage'),
    ('AWS',          'https://health.aws.amazon.com/public/currentevents',   'aws'),
    ('Google Cloud', 'https://status.cloud.google.com/incidents.json',       'statuspage'),
    ('Discord',      'https://discordstatus.com/api/v2/summary.json',        'statuspage'),
    ('GitHub',       'https://www.githubstatus.com/api/v2/summary.json',     'statuspage'),
]
_cache_servicios = {'ts': 0, 'data': None}

def _fetch_status(item):
    import urllib.request, ssl
    nombre, url = item[0], item[1]
    tipo = item[2] if len(item) > 2 else 'statuspage'
    try:
        ctx = ssl.create_default_context()
        req = urllib.request.Request(url, headers={'User-Agent': 'Pucara-Monitor/1.0'})
        with urllib.request.urlopen(req, timeout=8, context=ctx) as r:
            raw = r.read()
        # AWS: health.aws.amazon.com/public/currentevents (JSON en UTF-16, lista de eventos)
        if tipo == 'aws':
            try:
                data = json.loads(raw.decode('utf-16'))
            except Exception:
                data = json.loads(raw.decode('utf-8', errors='ignore'))
            # Evento activo = no resuelto (status != '0') y sin end_time
            activos = [e for e in data if str(e.get('status')) not in ('0', '') and not e.get('end_time')]
            if not activos:
                return {'nombre': nombre, 'estado': 'none', 'desc': 'Operativo', 'incidente': None}
            peor = max((int(e.get('status', 1)) for e in activos), default=1)
            est = 'major' if peor >= 2 else 'minor'
            e0 = activos[0]
            inc = f"{e0.get('service_name', '')}: {e0.get('summary', '')}".strip(': ')
            return {'nombre': nombre, 'estado': est, 'desc': 'Con incidentes', 'incidente': inc}
        d = json.loads(raw.decode())
        # Formato Statuspage v2: {status:{indicator,description}, incidents:[...]}
        if isinstance(d, dict) and 'status' in d:
            ind = d.get('status', {}).get('indicator', 'unknown')  # none/minor/major/critical
            desc = d.get('status', {}).get('description', '')
            incs = [i.get('name') for i in d.get('incidents', []) if i.get('name')]
            return {'nombre': nombre, 'estado': ind, 'desc': desc, 'incidente': incs[0] if incs else None}
        # Google Cloud incidents.json: lista de incidentes; vacío = OK
        if isinstance(d, list):
            abiertos = [i for i in d if not i.get('end')]
            if abiertos:
                return {'nombre': nombre, 'estado': 'major', 'desc': 'Con incidentes',
                        'incidente': abiertos[0].get('external_desc') or abiertos[0].get('service_name')}
            return {'nombre': nombre, 'estado': 'none', 'desc': 'Operativo', 'incidente': None}
        return {'nombre': nombre, 'estado': 'sin_datos', 'desc': '', 'incidente': None}
    except Exception:
        return {'nombre': nombre, 'estado': 'sin_datos', 'desc': '', 'incidente': None}

@app.route('/api/servicios-estado')
@login_required
def servicios_estado():
    """Estado de servicios grandes (Cloudflare, MercadoPago, etc.) desde sus
    páginas de estado oficiales. Cacheado 3 min. Fetch en paralelo."""
    import time as _t
    if _cache_servicios['data'] and (_t.time() - _cache_servicios['ts'] < 180):
        return jsonify(_cache_servicios['data'])
    from concurrent.futures import ThreadPoolExecutor
    try:
        with ThreadPoolExecutor(max_workers=8) as ex:
            resultado = list(ex.map(_fetch_status, SERVICIOS_STATUS))
    except Exception:
        resultado = [_fetch_status(s) for s in SERVICIOS_STATUS]
    # Ordenar: primero los que tienen problemas
    orden = {'critical': 0, 'major': 1, 'minor': 2, 'none': 3, 'unknown': 4, 'sin_datos': 5}
    resultado.sort(key=lambda x: orden.get(x['estado'], 9))
    _cache_servicios['data'] = resultado
    _cache_servicios['ts'] = _t.time()
    return jsonify(resultado)

@app.route('/api/dashboard')
@login_required
def dashboard():
    con = get_db()
    stats = {}
    # Conteos generales
    for estado in ['activo','suspendido','rescision','baja']:
        r = con.execute("SELECT COUNT(*) FROM clientes WHERE estado=?", (estado,)).fetchone()
        stats[estado] = r[0]
    stats['total'] = sum(stats.values())

    # Por tipo
    for tipo in ['fibra','inalambrico']:
        r = con.execute("SELECT COUNT(*) FROM clientes WHERE tipo_servicio=? AND estado='activo'", (tipo,)).fetchone()
        stats[f'activos_{tipo}'] = r[0]

    # NAPs con ocupación
    naps_data = []
    naps = con.execute("SELECT * FROM naps WHERE estado='operativo' ORDER BY nombre").fetchall()
    for n in naps:
        cap = n['capacidad'] or NAP_LIMIT
        clientes = con.execute("""
            SELECT estado, COUNT(*) as cnt FROM clientes
            WHERE nap=? AND estado!='baja'
            GROUP BY estado
        """, (n['nombre'],)).fetchall()
        total = sum(c['cnt'] for c in clientes)
        by_estado = {c['estado']: c['cnt'] for c in clientes}
        naps_data.append({
            'nombre': n['nombre'],
            'lat': n['lat'], 'lng': n['lng'],
            'localidad': n['localidad'],
            'capacidad': cap,
            'total': total,
            'activos': by_estado.get('activo', 0),
            'suspendidos': by_estado.get('suspendido', 0),
            'rescision': by_estado.get('rescision', 0),
            'libre': cap - total,
            'pct': round(total / cap * 100) if cap else 0
        })

    # Servicios pendientes
    servicios_pend = con.execute("SELECT COUNT(*) FROM servicios WHERE estado='pendiente'").fetchone()[0]
    servicios_proceso = con.execute("SELECT COUNT(*) FROM servicios WHERE estado='en_proceso'").fetchone()[0]

    # Incidencias activas
    incidencias = con.execute("SELECT * FROM incidencias WHERE estado='abierta' ORDER BY prioridad DESC, fecha_inicio DESC LIMIT 10").fetchall()
    inc_data = [dict(i) for i in incidencias]

    # Bajas pendientes
    bajas_pend = con.execute("SELECT COUNT(*) FROM clientes WHERE estado='rescision'").fetchone()[0]

    # Notificaciones no leídas
    notifs = con.execute("SELECT * FROM notificaciones WHERE leida=0 ORDER BY fecha DESC LIMIT 20").fetchall()

    con.close()
    return jsonify({
        'stats': stats,
        'naps': naps_data,
        'servicios_pendientes': servicios_pend,
        'servicios_en_proceso': servicios_proceso,
        'incidencias': inc_data,
        'bajas_pendientes': bajas_pend,
        'notificaciones': [dict(n) for n in notifs]
    })

@app.route('/api/dashboard/kpis')
@login_required
def dashboard_kpis():
    con = get_db()
    localidad = request.args.get('localidad','')
    tipo = request.args.get('tipo','')
    periodo = request.args.get('periodo','Últimos 30 días')

    # Calcular rango de días según período
    dias_map = {'Últimos 7 días':7, 'Últimos 30 días':30, 'Últimos 90 días':90, 'Último año':365}
    dias = dias_map.get(periodo, 30)

    where = "1=1"
    params = []
    if localidad:
        where += " AND localidad=?"
        params.append(localidad)
    if tipo:
        where += " AND tipo_servicio=?"
        params.append(tipo)

    kpis = {}
    for estado in ['activo','suspendido','pte_rescision','rescision','baja',
                    'pte_instalacion','pte_cambio','pte_calculo','sin_contrato']:
        r = con.execute(f"SELECT COUNT(*) FROM clientes WHERE estado=? AND {where}", [estado]+params).fetchone()
        kpis[estado] = r[0]
    kpis['total'] = sum(kpis.values())

    for t in ['fibra','inalambrico']:
        r = con.execute(f"SELECT COUNT(*) FROM clientes WHERE tipo_servicio=? AND estado='activo' AND {where}", [t]+params).fetchone()
        kpis[f'activos_{t}'] = r[0]

    # Sparklines (últimos N días, conteo diario de activos)
    spark_activos = []
    spark_total = []
    for i in range(min(dias, 30), -1, -1):
        fecha = f"date('now','localtime','-{i} day')"
        r = con.execute(f"SELECT COUNT(*) FROM clientes WHERE estado='activo' AND fecha_alta <= {fecha} AND {where}", params).fetchone()
        spark_activos.append(r[0])
        r2 = con.execute(f"SELECT COUNT(*) FROM clientes WHERE fecha_alta <= {fecha} AND {where}", params).fetchone()
        spark_total.append(r2[0])

    # Altas y bajas en el periodo
    altas = con.execute(f"SELECT COUNT(*) FROM clientes WHERE fecha_alta >= date('now','localtime','-{dias} day') AND {where}", params).fetchone()[0]
    altas_ant = con.execute(f"SELECT COUNT(*) FROM clientes WHERE fecha_alta >= date('now','localtime','-{dias*2} day') AND fecha_alta < date('now','localtime','-{dias} day') AND {where}", params).fetchone()[0]
    bajas = con.execute(f"SELECT COUNT(*) FROM clientes WHERE estado IN ('baja','rescision') AND fecha_baja >= date('now','localtime','-{dias} day') AND {where}", params).fetchone()[0]

    con.close()
    return jsonify({
        'kpis': kpis,
        'sparkline_activos': spark_activos,
        'sparkline_total': spark_total,
        'altas_periodo': altas,
        'altas_periodo_anterior': altas_ant,
        'bajas_periodo': bajas,
        'crecimiento_neto': altas - bajas,
        'periodo_dias': dias,
    })

@app.route('/api/dashboard/riesgos')
@login_required
def dashboard_riesgos():
    con = get_db()
    sus30 = con.execute("SELECT COUNT(*) FROM clientes WHERE estado='suspendido' AND fecha_suspension <= date('now','localtime','-30 day')").fetchone()[0]
    pago15 = con.execute("SELECT COUNT(*) FROM clientes WHERE ultimo_pago IS NOT NULL AND ultimo_pago <= date('now','localtime','-15 day') AND estado='activo'").fetchone()[0]
    deuda = con.execute("SELECT COALESCE(SUM(precio),0) FROM clientes WHERE estado='suspendido'").fetchone()[0]
    resc60 = con.execute("SELECT COUNT(*) FROM clientes WHERE estado='rescision' AND equipo_serie IS NOT NULL AND equipo_serie != ''").fetchone()[0]
    svc48 = con.execute("SELECT COUNT(*) FROM servicios WHERE estado='pendiente' AND fecha_creacion <= datetime('now','localtime','-48 hours') AND (tecnico IS NULL OR tecnico = '')").fetchone()[0]
    revision = con.execute("SELECT COUNT(*) FROM clientes WHERE estado='suspendido' AND fecha_suspension IS NOT NULL AND fecha_suspension <= date('now','localtime','-30 day')").fetchone()[0]
    con.close()
    return jsonify({
        'suspendidos_30dias': sus30,
        'pago_vencido_15dias': pago15,
        'deuda_total': deuda,
        'rescision_60dias_equipo': resc60,
        'servicios_sin_tecnico_48h': svc48,
        'requieren_revision': revision,
    })

@app.route('/api/dashboard/distribucion')
@login_required
def dashboard_distribucion():
    con = get_db()
    estados_raw = {}
    for e in ['activo','suspendido','pte_rescision','rescision','baja',
              'pte_instalacion','pte_calculo','pte_activacion','borrador','sin_contrato']:
        estados_raw[e] = con.execute("SELECT COUNT(*) FROM clientes WHERE estado=?", (e,)).fetchone()[0]
    total = sum(estados_raw.values()) or 1

    # Formato array para drawDonutEstados del frontend
    estados = []
    for e, cnt in estados_raw.items():
        if cnt > 0:
            estados.append({'estado': e, 'cantidad': cnt, 'pct': round(cnt / total * 100, 1)})

    tipos_raw = {}
    for t in ['fibra','inalambrico']:
        tipos_raw[t] = con.execute("SELECT COUNT(*) FROM clientes WHERE tipo_servicio=? AND estado!='baja'", (t,)).fetchone()[0]
    total_tipos = sum(tipos_raw.values()) or 1
    tipos = [{'tipo': t, 'cantidad': c, 'pct': round(c/total_tipos*100,1)} for t, c in tipos_raw.items() if c > 0]

    potencial = con.execute("SELECT COUNT(*) FROM clientes WHERE tipo_servicio='inalambrico' AND estado='activo'").fetchone()[0]

    locs = con.execute("SELECT localidad, COUNT(*) as cnt FROM clientes WHERE estado!='baja' AND localidad IS NOT NULL AND localidad!='' GROUP BY localidad ORDER BY cnt DESC LIMIT 15").fetchall()

    con.close()
    return jsonify({
        'estados': estados,
        'total': total,
        'tipos': tipos,
        'potencial_migracion_ftth': potencial,
        'localidades': [{'localidad': r[0], 'cantidad': r[1]} for r in locs],
    })

@app.route('/api/dashboard/top_naps_crecimiento')
@login_required
def dashboard_top_naps():
    con = get_db()
    naps = con.execute("""
        SELECT nap, COUNT(*) as total,
               SUM(CASE WHEN fecha_alta >= date('now','localtime','-30 day') THEN 1 ELSE 0 END) as nuevos_30d
        FROM clientes WHERE nap IS NOT NULL AND nap != '' AND estado!='baja'
        GROUP BY nap ORDER BY nuevos_30d DESC LIMIT 10
    """).fetchall()
    con.close()
    return jsonify([{'nap': r[0], 'total': r[1], 'nuevos_30d': r[2]} for r in naps])

@app.route('/api/dashboard/calendario')
@login_required
def dashboard_calendario():
    """Heatmap de actividad diaria del último año (estilo GitHub).
    metric: altas | bajas | servicios"""
    metric = request.args.get('metric', 'altas')
    con = get_db()
    # Definir la fuente según la métrica
    if metric == 'altas':
        rows = con.execute("""SELECT date(fecha_instalacion) d, COUNT(*) c FROM clientes
            WHERE fecha_instalacion IS NOT NULL AND fecha_instalacion >= date('now','localtime','-1 year')
            GROUP BY d""").fetchall()
    elif metric == 'bajas':
        rows = con.execute("""SELECT date(fecha_rescision) d, COUNT(*) c FROM clientes
            WHERE fecha_rescision IS NOT NULL AND fecha_rescision >= date('now','localtime','-1 year')
            GROUP BY d""").fetchall()
    else:  # servicios
        rows = con.execute("""SELECT date(fecha_creacion) d, COUNT(*) c FROM servicios
            WHERE fecha_creacion IS NOT NULL AND fecha_creacion >= date('now','localtime','-1 year')
            GROUP BY d""").fetchall()
    con.close()
    por_dia = {r['d']: r['c'] for r in rows if r['d']}
    # Construir los 365 días
    from datetime import date, timedelta
    hoy = date.today()
    data = []
    valores = []
    for i in range(364, -1, -1):
        f = hoy - timedelta(days=i)
        fs = f.isoformat()
        v = por_dia.get(fs, 0)
        valores.append(v)
        data.append({'fecha': fs, 'valor': v})
    # Niveles 0-4 para el color (relativo al máximo)
    mx = max(valores) if valores else 0
    for d in data:
        v = d['valor']
        if v == 0: d['nivel'] = 0
        elif mx <= 1: d['nivel'] = 4 if v else 0
        else:
            ratio = v / mx
            d['nivel'] = 1 if ratio <= .25 else 2 if ratio <= .5 else 3 if ratio <= .75 else 4
    total = sum(valores)
    promedio = round(total / 365, 1)
    return jsonify({'data': data, 'total': total, 'promedio': promedio, 'metric': metric})

@app.route('/api/dashboard/evolucion_mensual')
@login_required
def dashboard_evolucion():
    """Altas vs bajas por mes (12 meses).
    Altas = instalaciones realizadas (tienen fecha confiable).
    Bajas = rescisiones por fecha de rescisión.
    Devuelve formato que espera drawEvolucion: labels[], altas[], bajas[]."""
    con = get_db()
    labels, altas, bajas = [], [], []
    for i in range(11, -1, -1):
        # OJO: date('now','-N month') desde un día 31 DESBORDA al mes siguiente
        # (junio no tiene 31 → 'julio 1'). Eso duplicaba meses y salteaba otros.
        # Anclando al día 1 del mes actual, la resta de meses es exacta.
        mes = con.execute(
            f"SELECT strftime('%Y-%m', date('now','localtime','start of month','-{i} month'))"
        ).fetchone()[0]
        a = con.execute("""
            SELECT COUNT(*) FROM servicios
            WHERE tipo='instalacion' AND fecha_realizacion_instalacion IS NOT NULL
            AND strftime('%Y-%m', fecha_realizacion_instalacion)=?
        """, (mes,)).fetchone()[0]
        b = con.execute("""
            SELECT COUNT(*) FROM clientes
            WHERE fecha_rescision IS NOT NULL AND fecha_rescision != ''
            AND strftime('%Y-%m', fecha_rescision)=?
        """, (mes,)).fetchone()[0]
        # etiqueta mes/año corto
        labels.append(mes.split('-')[1] + '/' + mes.split('-')[0][2:])
        altas.append(a)
        bajas.append(b)
    con.close()
    total_altas = sum(altas)
    total_bajas = sum(bajas)
    return jsonify({
        'labels': labels,
        'altas': altas,
        'bajas': bajas,
        'total_altas': total_altas,
        'total_bajas': total_bajas,
        'crecimiento_neto': total_altas - total_bajas,
    })

@app.route('/api/dashboard/heatmap_horarios')
@login_required
def dashboard_heatmap():
    con = get_db()
    data = con.execute("""
        SELECT strftime('%w', fecha_inicio) as dia, strftime('%H', fecha_inicio) as hora, COUNT(*) as cnt
        FROM incidencias WHERE fecha_inicio IS NOT NULL
        GROUP BY dia, hora
    """).fetchall()
    con.close()
    return jsonify([{'dia': int(r[0]), 'hora': int(r[1]), 'total': r[2]} for r in data])

@app.route('/api/dashboard/naps_agrupadas')
@login_required
def dashboard_naps_agrup():
    con = get_db()
    naps = con.execute("""
        SELECT n.nombre, n.capacidad, n.localidad,
               COUNT(c.id) as ocupacion,
               SUM(CASE WHEN c.estado='activo' THEN 1 ELSE 0 END) as activos,
               SUM(CASE WHEN c.estado='suspendido' THEN 1 ELSE 0 END) as suspendidos
        FROM naps n
        LEFT JOIN clientes c ON c.nap = n.nombre AND c.estado != 'baja'
        WHERE n.estado = 'operativo'
        GROUP BY n.nombre
        ORDER BY n.localidad, n.nombre
    """).fetchall()
    con.close()
    result = {}
    for r in naps:
        loc = r['localidad'] or 'Sin localidad'
        if loc not in result:
            result[loc] = []
        cap = r['capacidad'] or NAP_LIMIT
        result[loc].append({
            'nombre': r['nombre'], 'capacidad': cap,
            'ocupacion': r['ocupacion'], 'activos': r['activos'],
            'suspendidos': r['suspendidos'],
            'pct': round(r['ocupacion'] / cap * 100) if cap else 0,
        })
    return jsonify(result)

@app.route('/api/notificaciones/leer', methods=['POST'])
@login_required
def leer_notifs():
    con = get_db()
    con.execute("UPDATE notificaciones SET leida=1 WHERE leida=0")
    con.commit(); con.close()
    return jsonify({'ok':True})

# ─── CLIENTES ─────────────────────────────────────────────────────
@app.route('/api/clientes')
@login_required
def get_clientes():
    q = request.args.get('q','').strip()
    estado = request.args.get('estado','')
    tipo = request.args.get('tipo','')
    localidad = request.args.get('localidad','')
    nap = request.args.get('nap','')
    impagas = request.args.get('impagas','').strip()  # '1', '2', '3plus'
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 50))

    sql = "SELECT * FROM clientes WHERE 1=1"
    params = []
    if q:
        sql += " AND (nombre LIKE ? OR dni LIKE ? OR telefono LIKE ? OR ip_asignada LIKE ? OR equipo_serie LIKE ? OR nro_cliente LIKE ?)"
        params += [f'%{q}%']*6
    if estado:
        sql += " AND estado=?"
        params.append(estado)
    if tipo:
        sql += " AND tipo_servicio=?"
        params.append(tipo)
    if localidad:
        sql += " AND localidad=?"
        params.append(localidad)
    if nap:
        sql += " AND nap=?"
        params.append(nap)
    # Filtro de facturas impagas: cuenta MESES distintos con algún recibo pendiente
    # (del último año). Un mes con cualquier pendiente cuenta 1, aunque tenga varios recibos.
    # Rangos EXCLUYENTES: '1' = exacto 1 mes, '2' = exacto 2, '3plus' = 3 o más.
    if impagas:
        # HAVING según el rango elegido (no se superponen entre sí)
        having = None
        if impagas == '1':
            having = "= 1"
        elif impagas == '2':
            having = "= 2"
        elif impagas == '3plus':
            having = ">= 3"
        if having:
            sql += f""" AND id IN (
                SELECT cliente_id FROM (
                    SELECT cliente_id, substr(fecha,1,7) AS mes
                    FROM pagos
                    WHERE origen='erp'
                      AND estado_pago LIKE '%Pendiente%'
                      AND fecha >= date('now','-1 year')
                    GROUP BY cliente_id, substr(fecha,1,7)
                )
                GROUP BY cliente_id
                HAVING COUNT(*) {having}
            )"""

    con = get_db()
    total = con.execute(f"SELECT COUNT(*) FROM ({sql})", params).fetchone()[0]
    sql += " ORDER BY nombre LIMIT ? OFFSET ?"
    params += [per_page, (page-1)*per_page]
    rows = con.execute(sql, params).fetchall()
    con.close()
    return jsonify({'total':total,'page':page,'clientes':[dict(r) for r in rows]})

def _filtrar_clientes_export(args):
    """Aplica los mismos filtros que get_clientes y devuelve TODOS los clientes (sin paginar)."""
    q = args.get('q','').strip()
    estado = args.get('estado','')
    tipo = args.get('tipo','')
    localidad = args.get('localidad','')
    nap = args.get('nap','')
    sql = "SELECT * FROM clientes WHERE 1=1"
    params = []
    if q:
        sql += " AND (nombre LIKE ? OR dni LIKE ? OR telefono LIKE ? OR ip_asignada LIKE ? OR equipo_serie LIKE ? OR nro_cliente LIKE ?)"
        params += [f'%{q}%']*6
    if estado:
        sql += " AND estado=?"; params.append(estado)
    if tipo:
        sql += " AND tipo_servicio=?"; params.append(tipo)
    if localidad:
        sql += " AND localidad=?"; params.append(localidad)
    if nap:
        sql += " AND nap=?"; params.append(nap)
    sql += " ORDER BY localidad, nombre"
    con = get_db()
    rows = con.execute(sql, params).fetchall()
    con.close()
    return [dict(r) for r in rows]

@app.route('/api/clientes/exportar')
@login_required
@admin_required
def exportar_clientes():
    """Exporta los clientes filtrados. ?formato=kmz|csv|pdf + mismos filtros que /api/clientes"""
    formato = request.args.get('formato', 'csv').lower()
    clientes = _filtrar_clientes_export(request.args)
    if not clientes:
        return jsonify({'error': 'No hay clientes con esos filtros'}), 404

    from io import BytesIO, StringIO
    from flask import send_file
    import datetime as _dt
    stamp = _dt.datetime.now().strftime('%Y%m%d_%H%M')

    # ════ KMZ (ubicaciones para Google Earth) ════
    if formato == 'kmz':
        import zipfile, html
        # Solo clientes con coordenadas válidas
        con_coord = [c for c in clientes if c.get('lat') and c.get('lng')
                     and str(c['lat']).strip() not in ('','0') and str(c['lng']).strip() not in ('','0')]
        # Color del pin según estado
        def color_estado(e):
            return {'activo':'ff00aa00', 'suspendido':'ff0088ff',
                    'pte_rescision':'ff00ddff', 'rescision':'ff0000ff'}.get(e, 'ffaaaaaa')
        placemarks = []
        for c in con_coord:
            nombre = html.escape(c.get('nombre',''))
            nro = c.get('nro_cliente','') or 's/n'
            abono = html.escape(c.get('plan','') or 'sin abono')
            est = c.get('estado','')
            desc = f"<![CDATA[<b>N° Cliente:</b> {nro}<br><b>Abono:</b> {abono}<br><b>Estado:</b> {est}]]>"
            placemarks.append(f"""    <Placemark>
      <name>{nro} - {nombre}</name>
      <description>{desc}</description>
      <Style><IconStyle><color>{color_estado(est)}</color>
        <Icon><href>http://maps.google.com/mapfiles/kml/paddle/wht-blank.png</href></Icon></IconStyle></Style>
      <Point><coordinates>{c['lng']},{c['lat']},0</coordinates></Point>
    </Placemark>""")
        kml = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Clientes Pucara - {stamp}</name>
{chr(10).join(placemarks)}
  </Document>
</kml>"""
        buf = BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr('doc.kml', kml)
        buf.seek(0)
        return send_file(buf, mimetype='application/vnd.google-earth.kmz',
                         as_attachment=True, download_name=f'clientes_{stamp}.kmz')

    # ════ CSV (todos los datos) ════
    if formato == 'csv':
        import csv
        campos = ['nro_cliente','nombre','dni','email','telefono','direccion','localidad',
                  'estado','tipo_servicio','plan','precio','nap','olt_nombre','olt_puerto',
                  'ip_asignada','equipo_marca','equipo_modelo','equipo_serie','mac_address',
                  'lat','lng','fecha_alta','ultimo_pago','agente']
        sio = StringIO()
        w = csv.writer(sio, delimiter=';')  # ; para que Excel ES lo abra bien
        w.writerow([c.replace('_',' ').title() for c in campos])
        for c in clientes:
            w.writerow([c.get(k,'') if c.get(k) is not None else '' for k in campos])
        buf = BytesIO(sio.getvalue().encode('utf-8-sig'))  # BOM para acentos en Excel
        return send_file(buf, mimetype='text/csv', as_attachment=True,
                         download_name=f'clientes_{stamp}.csv')

    # ════ PDF (todos los datos, formato tabla) ════
    if formato == 'pdf':
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.units import mm
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        buf = BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=landscape(A4), topMargin=12*mm,
                                bottomMargin=12*mm, leftMargin=10*mm, rightMargin=10*mm)
        ss = getSampleStyleSheet()
        AZUL = colors.HexColor('#1a3d6b')
        titulo = ParagraphStyle('t', parent=ss['Title'], fontSize=14, textColor=AZUL)
        sub = ParagraphStyle('s', parent=ss['Normal'], fontSize=8, textColor=colors.HexColor('#666'))
        story = [Paragraph('Pucara — Listado de clientes', titulo)]
        filtros = []
        for k in ['estado','tipo','localidad','nap']:
            if request.args.get(k): filtros.append(f"{k}: {request.args.get(k)}")
        story.append(Paragraph(f"{len(clientes)} clientes · {stamp}" +
                     (f" · Filtros: {', '.join(filtros)}" if filtros else ''), sub))
        story.append(Spacer(1, 8))
        cab = ['N°','Nombre','Localidad','Estado','Tipo','Abono','NAP/OLT','IP','Equipo']
        data = [cab]
        cst = ParagraphStyle('c', parent=ss['Normal'], fontSize=6.5, leading=8)
        for c in clientes:
            nap_olt = c.get('nap','') or c.get('olt_nombre','') or ''
            equipo = f"{c.get('equipo_modelo','') or ''} {c.get('equipo_serie','') or ''}".strip()
            data.append([
                str(c.get('nro_cliente','') or ''),
                Paragraph(c.get('nombre','') or '', cst),
                Paragraph(c.get('localidad','') or '', cst),
                c.get('estado','') or '', c.get('tipo_servicio','') or '',
                Paragraph(c.get('plan','') or '', cst),
                Paragraph(nap_olt, cst),
                c.get('ip_asignada','') or '',
                Paragraph(equipo, cst),
            ])
        t = Table(data, colWidths=[16*mm,52*mm,28*mm,20*mm,20*mm,40*mm,32*mm,26*mm,38*mm], repeatRows=1)
        t.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,0),AZUL), ('TEXTCOLOR',(0,0),(-1,0),colors.white),
            ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'), ('FONTSIZE',(0,0),(-1,0),7),
            ('FONTSIZE',(0,1),(-1,-1),6.5),
            ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white, colors.HexColor('#f2f6fb')]),
            ('GRID',(0,0),(-1,-1),0.3,colors.HexColor('#cccccc')),
            ('VALIGN',(0,0),(-1,-1),'MIDDLE'), ('TOPPADDING',(0,1),(-1,-1),2), ('BOTTOMPADDING',(0,1),(-1,-1),2),
        ]))
        story.append(t)
        doc.build(story)
        buf.seek(0)
        return send_file(buf, mimetype='application/pdf', as_attachment=True,
                         download_name=f'clientes_{stamp}.pdf')

    return jsonify({'error': 'formato inválido (kmz, csv o pdf)'}), 400

@app.route('/api/clientes/mapa')
@login_required
def clientes_mapa():
    estado = request.args.get('estado','')
    tipo = request.args.get('tipo','')
    con_svc_pendiente = request.args.get('con_servicio_pendiente','') == '1'
    con = get_db()
    sql = "SELECT id,nombre,nro_cliente,lat,lng,estado,tipo_servicio,nap,plan,direccion,localidad,equipo_modelo,telefono,necesita_nap,torre_id FROM clientes WHERE lat IS NOT NULL AND lng IS NOT NULL AND lat != '' AND lng != '' AND lat != 0 AND lng != 0"
    params = []
    # estado puede venir como lista separada por comas (checkboxes)
    estados = [e.strip() for e in estado.split(',') if e.strip()]
    if estados:
        ph = ','.join('?' * len(estados))
        sql += f" AND estado IN ({ph})"
        params.extend(estados)
    else:
        sql += " AND estado NOT IN ('baja','rescision')"
    if tipo:
        sql += " AND tipo_servicio=?"
        params.append(tipo)
    # Filtrar solo clientes con servicio técnico pendiente
    if con_svc_pendiente:
        sql += """ AND id IN (
            SELECT cliente_id FROM servicios
            WHERE tipo='servicio_tecnico' AND estado='pendiente' AND cliente_id IS NOT NULL
        )"""
    rows = con.execute(sql, params).fetchall()

    # Calcular torres afectadas por incidencias (cascada)
    torres_afectadas = set()
    torres_dict = {}
    for t in con.execute("SELECT id, torre_padre_id, estado FROM torres").fetchall():
        torres_dict[t['id']] = t
    inc_torres = set()
    for i in con.execute("SELECT torre_id FROM incidencias WHERE estado IN ('abierta','en_proceso') AND torre_id IS NOT NULL").fetchall():
        inc_torres.add(i['torre_id'])
    # Torres inactivas o en mantenimiento afectan a sus clientes (corte temporal).
    # Las dadas de BAJA no: sus clientes fueron migrados o dados de baja.
    for t in torres_dict.values():
        if t['estado'] in ('inactiva', 'mantenimiento'):
            inc_torres.add(t['id'])
    # Cascada: propagar a descendientes
    def _propagar(tid):
        for t2 in torres_dict.values():
            if t2['torre_padre_id'] == tid and t2['id'] not in torres_afectadas:
                torres_afectadas.add(t2['id'])
                _propagar(t2['id'])
    for tid in inc_torres:
        torres_afectadas.add(tid)
        _propagar(tid)

    # NAPs afectados por incidencias
    naps_afectados = set()
    for i in con.execute("SELECT nap_nombre, objeto_ids FROM incidencias WHERE estado IN ('abierta','en_proceso') AND (nap_nombre IS NOT NULL OR objeto_ids IS NOT NULL)").fetchall():
        if i['nap_nombre']:
            for n in i['nap_nombre'].split(','):
                naps_afectados.add(n.strip())
        if i['objeto_ids']:
            try:
                ids = json.loads(i['objeto_ids'])
                for nid in ids:
                    nap = con.execute("SELECT nombre FROM naps WHERE id=?", (nid,)).fetchone()
                    if nap:
                        naps_afectados.add(nap['nombre'])
            except:
                pass

    # Set de clientes con servicio técnico pendiente (antes de cerrar la conexión)
    svc_pendiente_ids = set()
    for s in con.execute("""SELECT DISTINCT cliente_id FROM servicios
        WHERE tipo='servicio_tecnico' AND estado='pendiente' AND cliente_id IS NOT NULL""").fetchall():
        svc_pendiente_ids.add(s['cliente_id'])

    con.close()

    # Enriquecer cada cliente con flag de afectación
    result = []
    for r in rows:
        d = dict(r)
        afectado = False
        motivo = ''
        # Por torre
        if d.get('torre_id') and d['torre_id'] in torres_afectadas:
            afectado = True
            motivo = 'Torre afectada'
        # Por NAP
        if d.get('nap') and d['nap'] in naps_afectados:
            afectado = True
            motivo = 'NAP con incidencia' if not motivo else motivo + ' + NAP con incidencia'
        d['afectado_por_incidencia'] = afectado
        d['motivo_afectacion'] = motivo
        d['tiene_servicio_pendiente'] = d['id'] in svc_pendiente_ids
        result.append(d)
    return jsonify(result)

@app.route('/api/clientes/buscar')
@login_required
def buscar_clientes():
    q = request.args.get('q','').strip()
    if len(q) < 2:
        return jsonify([])
    con = get_db()
    rows = con.execute("""
        SELECT id,nombre,nro_cliente,direccion,localidad,estado,tipo_servicio,lat,lng,telefono
        FROM clientes
        WHERE nombre LIKE ? OR dni LIKE ? OR telefono LIKE ? OR ip_asignada LIKE ? OR nro_cliente LIKE ?
        ORDER BY nombre LIMIT 15
    """, [f'%{q}%']*5).fetchall()
    con.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/clientes/<int:cid>/historial_completo')
@login_required
def cliente_historial_completo(cid):
    """Historial unificado del cliente: instalación, servicios técnicos (técnico,
    problema y solución), trabajos de técnico interior y cambios de abono."""
    con = get_db()
    cli = con.execute("""SELECT nombre, nro_cliente, fecha_instalacion, fecha_alta,
                         plan, precio, tipo_servicio FROM clientes WHERE id=?""", (cid,)).fetchone()
    if not cli:
        con.close()
        return jsonify({'error': 'cliente no encontrado'}), 404
    eventos = []

    # Columnas reales de servicios (defensivo: algunas pueden no existir en bases viejas)
    svc_cols = {r[1] for r in con.execute("PRAGMA table_info(servicios)").fetchall()}
    def col(c, alt=''):
        return c if c in svc_cols else (f"'' AS {c}" if not alt else alt)

    # ── Instalación ──
    inst = con.execute(f"""SELECT fecha_realizacion_instalacion, tecnico_realizacion, tecnico,
                          {col('medio_transmision', "'' AS medio_transmision")}, fecha_creacion
                          FROM servicios
                          WHERE cliente_id=? AND tipo='instalacion'
                          ORDER BY fecha_realizacion_instalacion DESC LIMIT 1""", (cid,)).fetchone()
    if inst and inst['fecha_realizacion_instalacion']:
        eventos.append({'tipo':'instalacion', 'fecha':inst['fecha_realizacion_instalacion'],
            'titulo':'Instalación realizada',
            'tecnico':inst['tecnico_realizacion'] or inst['tecnico'] or '—',
            'detalle':f"Medio: {inst['medio_transmision'] or cli['tipo_servicio'] or '—'}"})
    elif cli['fecha_instalacion']:
        eventos.append({'tipo':'instalacion', 'fecha':cli['fecha_instalacion'],
            'titulo':'Instalación (registrada en ficha)', 'tecnico':'—',
            'detalle':f"Tipo: {cli['tipo_servicio'] or '—'}"})

    # ── Servicios técnicos ──
    servicios = con.execute("""SELECT tipo, fecha_creacion, fecha_realizacion,
                               tecnico, tecnico_realizacion, descripcion, diagnostico,
                               solucion_aplicada, estado
                               FROM servicios
                               WHERE cliente_id=? AND tipo!='instalacion'
                               ORDER BY fecha_creacion DESC""", (cid,)).fetchall()
    for s in servicios:
        partes = []
        if s['diagnostico']: partes.append(f"Problema: {s['diagnostico']}")
        elif s['descripcion']: partes.append(f"Problema: {s['descripcion']}")
        if s['solucion_aplicada']: partes.append(f"Solución: {s['solucion_aplicada']}")
        eventos.append({'tipo':'servicio',
            'fecha':s['fecha_realizacion'] or s['fecha_creacion'],
            'titulo':(s['tipo'] or 'Servicio').replace('_',' ').title(),
            'tecnico':s['tecnico_realizacion'] or s['tecnico'] or '—',
            'detalle':' · '.join(partes) if partes else 'Sin detalle',
            'estado':s['estado']})

    # ── Trabajos de técnico interior ──
    trabajos = con.execute("""SELECT tipo_trabajo, fecha_trabajo, tecnico, descripcion, metros
                              FROM tecnico_interior_trabajos
                              WHERE cliente_id=? ORDER BY fecha_trabajo DESC""", (cid,)).fetchall()
    for t in trabajos:
        det = t['descripcion'] or 'sin detalle'
        if t['metros'] and t['metros'] > 0: det += f" ({t['metros']}m)"
        eventos.append({'tipo':'trabajo_interior', 'fecha':t['fecha_trabajo'],
            'titulo':t['tipo_trabajo'] or 'Trabajo', 'tecnico':t['tecnico'] or '—', 'detalle':det})

    # ── Cambios de abono ──
    abonos = con.execute("""SELECT plan_anterior, plan_nuevo, precio_anterior, precio_nuevo,
                            origen, usuario, fecha FROM historial_abono
                            WHERE cliente_id=? ORDER BY fecha DESC""", (cid,)).fetchall()
    for a in abonos:
        eventos.append({'tipo':'cambio_abono', 'fecha':a['fecha'], 'titulo':'Cambio de abono',
            'tecnico':a['usuario'] or a['origen'] or '—',
            'detalle':f"{a['plan_anterior'] or '—'} → {a['plan_nuevo'] or '—'}" +
                      (f" (${a['precio_anterior'] or 0:.0f} → ${a['precio_nuevo'] or 0:.0f})" if a['precio_nuevo'] else '')})

    con.close()
    eventos.sort(key=lambda e: e['fecha'] or '', reverse=True)
    return jsonify({'cliente':cli['nombre'], 'nro_cliente':cli['nro_cliente'], 'eventos':eventos})

@app.route('/api/clientes/<int:cid>/sondear_equipo', methods=['POST'])
@login_required
def sondear_equipo_cliente(cid):
    """Sondea el equipo Ubiquiti del cliente en vivo y guarda el resultado.
    Botón manual desde la ficha. Devuelve los datos leídos y el cotejo."""
    import os, sys
    # Asegurar que el módulo se encuentre (mismo dir que app.py)
    _dir = os.path.dirname(os.path.abspath(__file__))
    if _dir not in sys.path:
        sys.path.insert(0, _dir)
    try:
        import ubiquiti_poller
    except ImportError as e:
        return jsonify({'error': f'módulo de sondeo no encontrado: {e}. Verificá que ubiquiti_poller.py esté junto a app.py'}), 500
    except Exception as e:
        return jsonify({'error': f'error al cargar el módulo de sondeo: {e}'}), 500
    try:
        con = get_db()
        r = ubiquiti_poller.sondear_cliente(con, cid, origen=session.get('username','manual'))
        con.close()
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'error durante el sondeo: {e}'}), 502
    if r.get('error'):
        return jsonify({'error': r['error']}), 502
    return jsonify(r)

@app.route('/api/clientes/<int:cid>/chequeos')
@login_required
def cliente_chequeos(cid):
    """Historial de chequeos de equipo (firmware, LAN, uptime, cotejos)."""
    con = get_db()
    if not _table_exists(con, 'chequeos_equipo'):
        con.close()
        return jsonify([])
    rows = con.execute("""SELECT fecha, ip, wlan0_mac, device_model, firmware, uptime_txt,
                          lan_estado, ap_mac, ssid, signal, ccq, tx_rate, rx_rate,
                          mac_coincide, modelo_coincide, observaciones, origen
                          FROM chequeos_equipo WHERE cliente_id=?
                          ORDER BY fecha DESC LIMIT 50""", (cid,)).fetchall()
    con.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/clientes/<int:cid>/torre_ap_historico')
@login_required
def cliente_torre_ap_historico(cid):
    """Histórico de AP/SSID al que estuvo enlazado el cliente (de los chequeos).
    Solo muestra cuando cambió el AP, para ver la historia de enlaces."""
    con = get_db()
    if not _table_exists(con, 'chequeos_equipo'):
        con.close()
        return jsonify([])
    rows = con.execute("""SELECT fecha, ap_mac, ssid, signal, origen
                          FROM chequeos_equipo
                          WHERE cliente_id=? AND ap_mac IS NOT NULL AND ap_mac != ''
                          ORDER BY fecha DESC LIMIT 100""", (cid,)).fetchall()
    con.close()
    # Comprimir: solo mostrar entradas donde cambió el AP (historia de enlaces)
    historico = []
    ultimo_ap = None
    for r in rows:
        d = dict(r)
        if d['ap_mac'] != ultimo_ap:
            historico.append(d)
            ultimo_ap = d['ap_mac']
    return jsonify(historico)

@app.route('/api/torres/enlaces')
@login_required
def torres_enlaces():
    """Lista los equipos de torre detectados por el poller, agrupados por
    clasificación (Master enlace, Slave enlace, AP clientes)."""
    con = get_db()
    if not _table_exists(con, 'ip_equipos_torre'):
        con.close()
        return jsonify({'equipos': []})
    cols = {r[1] for r in con.execute("PRAGMA table_info(ip_equipos_torre)").fetchall()}
    if 'clasificacion' not in cols:
        con.close()
        return jsonify({'equipos': [], 'aviso': 'todavía no se corrió el poller de torres'})
    rows = con.execute("""SELECT subred, host, nombre, mac, banda, modo, clasificacion,
                          ssid, firmware, device_model, ap_mac_enlace, ultimo_sondeo
                          FROM ip_equipos_torre
                          WHERE clasificacion IS NOT NULL AND clasificacion != ''
                          ORDER BY clasificacion, subred, host""").fetchall()
    con.close()
    equipos = []
    for r in rows:
        d = dict(r)
        d['ip'] = f"169.254.{r['subred']}.{r['host']}"
        equipos.append(d)
    # Agrupar por clasificación
    grupos = {}
    for e in equipos:
        grupos.setdefault(e['clasificacion'], []).append(e)
    return jsonify({'equipos': equipos, 'grupos': grupos, 'total': len(equipos)})

@app.route('/api/torres/por_mac/<mac>')
@login_required
def torre_equipo_por_mac(mac):
    """Encuentra el equipo de torre cuya WLAN0 MAC coincide con la MAC dada
    (para saltar desde un AP de la Vista de APs a su equipo de torre)."""
    con = get_db()
    if not _table_exists(con, 'ip_equipos_torre'):
        con.close()
        return jsonify({'error': 'sin datos de torre'}), 404
    eq = con.execute("SELECT subred, host FROM ip_equipos_torre WHERE UPPER(mac)=?",
                     (mac.upper(),)).fetchone()
    con.close()
    if not eq:
        return jsonify({'error': 'no hay equipo de torre con esa MAC'}), 404
    return jsonify({'subred': eq['subred'], 'host': eq['host']})

@app.route('/api/torres/equipo/<int:subred>/<int:host>')
@login_required
def torre_equipo_detalle(subred, host):
    """Toda la info de un equipo de torre + los clientes vinculados a él
    (clientes cuyo AP MAC del último sondeo coincide con la MAC de este equipo)."""
    con = get_db()
    if not _table_exists(con, 'ip_equipos_torre'):
        con.close()
        return jsonify({'error': 'sin datos de torre'}), 404
    eq = con.execute("SELECT * FROM ip_equipos_torre WHERE subred=? AND host=?",
                     (subred, host)).fetchone()
    if not eq:
        con.close()
        return jsonify({'error': 'equipo no encontrado'}), 404
    d = dict(eq)
    d['ip'] = f"169.254.{subred}.{host}"

    # Último chequeo de este equipo (histórico de torre), si existe
    if _table_exists(con, 'chequeos_torre'):
        ch = con.execute("""SELECT * FROM chequeos_torre WHERE subred=? AND host=?
                            ORDER BY fecha DESC LIMIT 1""", (subred, host)).fetchone()
        d['ultimo_chequeo'] = dict(ch) if ch else None

    # Clientes vinculados: su AP MAC (del último sondeo) == MAC de este equipo
    clientes = []
    mac_equipo = (eq['mac'] or '').upper().strip()
    if mac_equipo and _table_exists(con, 'chequeos_equipo'):
        rows = con.execute("""
            SELECT ch.cliente_id, ch.signal, ch.ccq, ch.fecha,
                   c.nombre, c.nro_cliente, c.localidad, c.estado, c.ip_asignada
            FROM chequeos_equipo ch
            JOIN clientes c ON c.id = ch.cliente_id
            WHERE ch.id IN (SELECT MAX(id) FROM chequeos_equipo GROUP BY cliente_id)
              AND UPPER(ch.ap_mac) = ?
            ORDER BY ch.signal DESC
        """, (mac_equipo,)).fetchall()
        clientes = [dict(r) for r in rows]
    d['clientes'] = clientes
    d['total_clientes'] = len(clientes)
    con.close()
    return jsonify(d)


# ── Umbrales de calidad de enlace inalámbrico ──
# Ajustables: definen cuándo un enlace se marca para revisión o alerta.
ENLACE_UMBRAL_SENAL = -75    # dBm: señal igual o peor (más negativa) que esto = mala
ENLACE_UMBRAL_CCQ = 50       # %: CCQ por debajo de esto = malo
ENLACE_UMBRAL_TXRX = 10      # Mbps: tx o rx por debajo de esto = malo

def _evaluar_enlace(signal, ccq, tx_rate, rx_rate):
    """Evalúa la calidad de un enlace. Devuelve qué condiciones están mal,
    si necesita bandera de revisión (alguna mala) o alerta (las tres malas)."""
    problemas = []
    senal_mala = signal is not None and signal <= ENLACE_UMBRAL_SENAL
    ccq_malo = ccq is not None and ccq < ENLACE_UMBRAL_CCQ
    # tx/rx vienen como string a veces; convertir
    def _num(v):
        try: return float(str(v).strip())
        except (ValueError, TypeError, AttributeError): return None
    tx, rx = _num(tx_rate), _num(rx_rate)
    txrx_malo = (tx is not None and tx < ENLACE_UMBRAL_TXRX) or \
                (rx is not None and rx < ENLACE_UMBRAL_TXRX)
    if senal_mala: problemas.append('señal')
    if ccq_malo: problemas.append('ccq')
    if txrx_malo: problemas.append('tx/rx')
    n = len(problemas)
    return {
        'problemas': problemas,
        'revisar': n >= 1,            # bandera: al menos una condición mala
        'alerta': n >= 3,            # alerta: las tres condiciones malas
        'senal_mala': senal_mala, 'ccq_malo': ccq_malo, 'txrx_malo': txrx_malo,
    }

@app.route('/api/mikrotik')
@login_required
@requiere_permiso('monitoreo')
def mikrotik_lista():
    """Estado de los routers MikroTik (lo que dejó mikrotik_poller)."""
    con = get_db()
    if not _table_exists(con, 'mikrotik_estado'):
        con.close()
        return jsonify({'routers': [], 'sin_datos': True})
    filas = con.execute("""
        SELECT m.*, e.torre_id, t.nombre AS torre_nombre
        FROM mikrotik_estado m
        LEFT JOIN torre_equipos e ON e.id = m.equipo_id
        LEFT JOIN torres t ON t.id = e.torre_id
        ORDER BY m.online DESC, m.identidad
    """).fetchall()
    con.close()
    out = []
    for f in filas:
        d = dict(f)
        try:
            d['sensores'] = json.loads(d.get('sensores_json') or '{}')
        except Exception:
            d['sensores'] = {}
        d.pop('sensores_json', None)
        if d.get('mem_total_kb'):
            d['mem_pct'] = round((d.get('mem_usada_kb') or 0) / d['mem_total_kb'] * 100, 1)
        else:
            d['mem_pct'] = None
        out.append(d)
    return jsonify({
        'routers': out,
        'resumen': {
            'total': len(out),
            'online': sum(1 for r in out if r.get('online')),
            'sesiones_ppp': sum(r.get('sesiones_ppp') or 0 for r in out),
        },
    })


@app.route('/api/enlaces/concentracion')
@login_required
def enlaces_concentracion():
    """Agrupa los enlaces problemáticos por AP y por localidad, para ver dónde
    se concentran los problemas (¿es un AP saturado o clientes sueltos?)."""
    con = get_db()
    if not _table_exists(con, 'chequeos_equipo'):
        con.close()
        return jsonify({'por_ap': [], 'por_zona': []})
    rows = con.execute("""
        SELECT ch.signal, ch.ccq, ch.tx_rate, ch.rx_rate, ch.ap_mac, ch.ssid,
               c.localidad, c.lat, c.lng, c.nombre, c.id AS cid
        FROM chequeos_equipo ch
        JOIN clientes c ON c.id = ch.cliente_id
        WHERE ch.id IN (SELECT MAX(id) FROM chequeos_equipo GROUP BY cliente_id)
          AND c.estado IN ('activo','suspendido')
    """).fetchall()
    con.close()
    # Contar por AP y por zona: total vs problemáticos
    ap_stats, zona_stats, puntos = {}, {}, []
    for r in rows:
        ev = _evaluar_enlace(r['signal'], r['ccq'], r['tx_rate'], r['rx_rate'])
        # Por AP
        ap = r['ap_mac'] or 'sin AP'
        if ap not in ap_stats:
            ap_stats[ap] = {'ap_mac': r['ap_mac'], 'ssid': r['ssid'], 'total': 0, 'problemas': 0, 'alertas': 0}
        ap_stats[ap]['total'] += 1
        if ev['revisar']: ap_stats[ap]['problemas'] += 1
        if ev['alerta']: ap_stats[ap]['alertas'] += 1
        # Por zona
        z = r['localidad'] or 'sin localidad'
        if z not in zona_stats:
            zona_stats[z] = {'localidad': z, 'total': 0, 'problemas': 0, 'alertas': 0}
        zona_stats[z]['total'] += 1
        if ev['revisar']: zona_stats[z]['problemas'] += 1
        if ev['alerta']: zona_stats[z]['alertas'] += 1
        # Puntos para el mapa de calor (solo los problemáticos con coordenadas)
        if ev['revisar'] and r['lat'] and r['lng']:
            puntos.append({'lat': r['lat'], 'lng': r['lng'], 'nombre': r['nombre'],
                           'cid': r['cid'], 'es_alerta': ev['alerta'],
                           'signal': r['signal'], 'problemas': ev['problemas']})
    # Ordenar por % de problemas (los APs/zonas más afectados primero)
    for d in ap_stats.values():
        d['pct'] = round(100 * d['problemas'] / d['total'], 0) if d['total'] else 0
    for d in zona_stats.values():
        d['pct'] = round(100 * d['problemas'] / d['total'], 0) if d['total'] else 0
    por_ap = sorted([a for a in ap_stats.values() if a['problemas'] > 0],
                    key=lambda x: (-x['alertas'], -x['pct']))
    por_zona = sorted([z for z in zona_stats.values() if z['problemas'] > 0],
                      key=lambda x: (-x['alertas'], -x['pct']))
    return jsonify({'por_ap': por_ap, 'por_zona': por_zona, 'puntos': puntos})

@app.route('/api/enlaces/problematicos')
@login_required
def enlaces_problematicos():
    """Lista los enlaces de clientes con problemas de calidad, según el último
    chequeo. Marca bandera (revisión) o alerta (crítico) según las condiciones."""
    con = get_db()
    if not _table_exists(con, 'chequeos_equipo'):
        con.close()
        return jsonify({'enlaces': [], 'umbrales': {
            'senal': ENLACE_UMBRAL_SENAL, 'ccq': ENLACE_UMBRAL_CCQ, 'txrx': ENLACE_UMBRAL_TXRX}})
    rows = con.execute("""
        SELECT ch.cliente_id, ch.signal, ch.ccq, ch.tx_rate, ch.rx_rate, ch.ssid,
               ch.ap_mac, ch.fecha, c.nombre, c.nro_cliente, c.localidad, c.estado, c.ip_asignada
        FROM chequeos_equipo ch
        JOIN clientes c ON c.id = ch.cliente_id
        WHERE ch.id IN (SELECT MAX(id) FROM chequeos_equipo GROUP BY cliente_id)
          AND c.estado IN ('activo','suspendido')
        ORDER BY ch.signal ASC
    """).fetchall()
    con.close()
    revisar, alertas = [], []
    for r in rows:
        ev = _evaluar_enlace(r['signal'], r['ccq'], r['tx_rate'], r['rx_rate'])
        if not ev['revisar']:
            continue
        item = dict(r)
        item['problemas'] = ev['problemas']
        item['es_alerta'] = ev['alerta']
        if ev['alerta']:
            alertas.append(item)
        else:
            revisar.append(item)
    return jsonify({
        'alertas': alertas,        # las tres condiciones malas (crítico)
        'revisar': revisar,        # alguna condición mala (bandera)
        'total_alertas': len(alertas),
        'total_revisar': len(revisar),
        'umbrales': {'senal': ENLACE_UMBRAL_SENAL, 'ccq': ENLACE_UMBRAL_CCQ, 'txrx': ENLACE_UMBRAL_TXRX},
    })

def _aps_desde_snmp(con):
    """Vista de APs armada con la instantánea SNMP (snmp_estaciones).

    Es la fuente preferida sobre chequeos_equipo porque:
      - la escribe el sondeo SNMP del AP, que corre seguido y ve TODAS sus
        estaciones de una, en vez de depender de que se haya sondeado uno por
        uno a cada cliente por HTTP;
      - incluye estaciones que no cruzan con ningún cliente cargado;
      - trae SNR y distancia cuando el fabricante los reporta (Cambium)."""
    filas = con.execute("""
        SELECT s.*, e.id AS equipo_id, e.modelo AS ap_modelo, e.mac AS ap_mac_inv,
               e.snmp_estado, e.ultimo_snmp, t.nombre AS torre_nombre,
               c.nombre AS cliente_nombre, c.nro_cliente, c.localidad, c.estado AS cliente_estado
        FROM snmp_estaciones s
        LEFT JOIN torre_equipos e ON e.id = s.equipo_id
        LEFT JOIN torres t ON t.id = e.torre_id
        LEFT JOIN clientes c ON c.id = s.cliente_id
        ORDER BY s.ssid, s.rssi DESC
    """).fetchall()
    aps = {}
    for r in filas:
        key = r['equipo_id']
        if key not in aps:
            aps[key] = {
                'equipo_id': r['equipo_id'],
                'ap_mac': r['ap_mac_inv'] or '',
                'ssid': r['ssid'] or r['ap_modelo'] or f"equipo {r['equipo_id']}",
                'ap_modelo': r['ap_modelo'],
                'torre_nombre': r['torre_nombre'],
                'snmp_estado': r['snmp_estado'],
                'ultimo_snmp': r['ultimo_snmp'],
                'fuente': 'snmp',
                'clientes': [],
            }
        aps[key]['clientes'].append({
            'cliente_id': r['cliente_id'],
            # Si no cruzó con un cliente, se muestra el nombre que le puso el AP
            'nombre': r['cliente_nombre'] or r['nombre_ap'] or '(sin identificar)',
            'sin_cruzar': r['cliente_id'] is None,
            'nro_cliente': r['nro_cliente'], 'localidad': r['localidad'],
            'estado': r['cliente_estado'], 'ip': r['ip'],
            'mac': r['mac'], 'signal': r['rssi'], 'ccq': r['ccq'], 'snr': r['snr'],
            'distancia_m': r['distancia_m'], 'tx_rate': r['tx_rate'],
            'modelo_sm': r['modelo_sm'], 'fecha': r['fecha'],
        })
    return list(aps.values())


@app.route('/api/aps')
@login_required
def listar_aps():
    """Lista los AP con sus clientes conectados y nivel de señal.

    Prioriza la instantánea SNMP; si todavía no hay datos SNMP cae al último
    chequeo por cliente del poller HTTP (chequeos_equipo), para que la pantalla
    siga andando en instalaciones donde el sondeo SNMP no está configurado."""
    con = get_db()
    if _table_exists(con, 'snmp_estaciones'):
        lista_snmp = _aps_desde_snmp(con)
        if lista_snmp:
            con.close()
            for a in lista_snmp:
                a['total_clientes'] = len(a['clientes'])
                sigs = [c['signal'] for c in a['clientes'] if c['signal'] is not None]
                a['signal_promedio'] = round(sum(sigs) / len(sigs), 1) if sigs else None
            lista_snmp.sort(key=lambda a: -a['total_clientes'])
            return jsonify({'aps': lista_snmp, 'total_aps': len(lista_snmp), 'fuente': 'snmp'})
    if not _table_exists(con, 'chequeos_equipo'):
        con.close()
        return jsonify({'aps': [], 'fuente': 'ninguna'})
    # Último chequeo de cada cliente (el más reciente por cliente_id)
    rows = con.execute("""
        SELECT ch.cliente_id, ch.ap_mac, ch.ssid, ch.signal, ch.ccq, ch.fecha,
               c.nombre, c.nro_cliente, c.localidad, c.estado, c.ip_asignada
        FROM chequeos_equipo ch
        JOIN clientes c ON c.id = ch.cliente_id
        WHERE ch.id IN (
            SELECT MAX(id) FROM chequeos_equipo GROUP BY cliente_id
        )
        AND ch.ap_mac IS NOT NULL AND ch.ap_mac != ''
        ORDER BY ch.ssid, ch.signal DESC
    """).fetchall()
    con.close()
    # Agrupar por AP MAC
    aps = {}
    for r in rows:
        key = r['ap_mac']
        if key not in aps:
            aps[key] = {'ap_mac': r['ap_mac'], 'ssid': r['ssid'], 'clientes': []}
        aps[key]['clientes'].append({
            'cliente_id': r['cliente_id'], 'nombre': r['nombre'],
            'nro_cliente': r['nro_cliente'], 'localidad': r['localidad'],
            'estado': r['estado'], 'ip': r['ip_asignada'],
            'signal': r['signal'], 'ccq': r['ccq'], 'fecha': r['fecha'],
        })
    # Ordenar APs por cantidad de clientes (descendente)
    lista = sorted(aps.values(), key=lambda a: -len(a['clientes']))
    for a in lista:
        a['total_clientes'] = len(a['clientes'])
        sigs = [c['signal'] for c in a['clientes'] if c['signal'] is not None]
        a['signal_promedio'] = round(sum(sigs)/len(sigs), 1) if sigs else None
    return jsonify({'aps': lista, 'total_aps': len(lista), 'fuente': 'poller_http'})

@app.route('/api/clientes/<int:cid>/trabajos_tecnico')
@login_required
def cliente_trabajos_tecnico(cid):
    """Historial de trabajos de técnico interior realizados a este cliente."""
    con = get_db()
    rows = con.execute("""SELECT id, tecnico, tipo_trabajo, monto, metros, fecha_trabajo,
                          descripcion, realizado, pagado, creado_por
                          FROM tecnico_interior_trabajos
                          WHERE cliente_id=? ORDER BY fecha_trabajo DESC, id DESC""", (cid,)).fetchall()
    con.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/clientes/<int:cid>')
@login_required
def get_cliente(cid):
    con = get_db()
    c = con.execute("SELECT * FROM clientes WHERE id=?", (cid,)).fetchone()
    if not c:
        con.close()
        return jsonify({'error':'not found'}), 404
    # Pagos recientes
    pagos = con.execute("SELECT * FROM pagos WHERE cliente_id=? ORDER BY fecha DESC", (cid,)).fetchall()
    # Servicios
    svcs = con.execute("SELECT * FROM servicios WHERE cliente_id=? ORDER BY fecha_creacion DESC LIMIT 10", (cid,)).fetchall()
    # Construir array de telefonos para el frontend
    telefonos = []
    if c['telefono']:
        telefonos.append({'telefono': c['telefono'], 'tipo': 'movil'})
    if c['telefono2']:
        telefonos.append({'telefono': c['telefono2'], 'tipo': 'movil'})
    if not telefonos:
        telefonos = [{'telefono':'','tipo':'movil'}]
    # Verificar si el cliente está afectado por incidencia
    afectado = False
    motivo = ''
    # Por torre
    if c['torre_id']:
        inc_torre = con.execute("""SELECT COUNT(*) FROM incidencias
            WHERE estado IN ('abierta','en_proceso') AND torre_id=?""", (c['torre_id'],)).fetchone()[0]
        if inc_torre > 0:
            afectado = True
            motivo = 'Torre con incidencia activa'
    # Por NAP
    if c['nap']:
        inc_nap = con.execute("""SELECT COUNT(*) FROM incidencias
            WHERE estado IN ('abierta','en_proceso')
            AND (nap_nombre LIKE ? OR nap_nombre LIKE ?)""",
            (c['nap'], '%'+c['nap']+'%')).fetchone()[0]
        if inc_nap > 0:
            afectado = True
            motivo = ('NAP con incidencia' if not motivo else motivo + ' + NAP con incidencia')

    con.close()
    cd = dict(c)
    cd['afectado_por_incidencia'] = afectado
    cd['motivo_afectacion'] = motivo
    cd['nap_display'] = _armar_nap_display(cd)
    return jsonify({'cliente':cd,'pagos':[dict(p) for p in pagos],'servicios':[dict(s) for s in svcs],'telefonos':telefonos})

@app.route('/api/clientes', methods=['POST'])
@login_required
def crear_cliente():
    d = request.get_json()
    con = get_db()
    cur = con.execute("""
        INSERT INTO clientes(nombre,dni,email,telefono,telefono2,direccion,localidad,lat,lng,
        estado,tipo_servicio,plan,precio,nap,equipo_modelo,equipo_marca,equipo_serie,
        ip_asignada,mac_address,fecha_alta,agente,observaciones,olt_nombre,olt_puerto,
        nro_cliente,pppoe_usuario,pppoe_clave,cdo,red,torre_id,ap_nombre)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (d.get('nombre'),d.get('dni'),d.get('email'),d.get('telefono'),
          d.get('telefono2'),
          d.get('direccion'),d.get('localidad'),d.get('lat'),d.get('lng'),
          d.get('estado','activo'),d.get('tipo_servicio','inalambrico'),
          d.get('plan'),d.get('precio',0),d.get('nap'),
          d.get('equipo_modelo'),d.get('equipo_marca'),d.get('equipo_serie'),
          d.get('ip_asignada'),d.get('mac_address'),
          d.get('fecha_alta', date.today().isoformat()),
          d.get('agente'),d.get('observaciones'),
          d.get('olt_nombre'),d.get('olt_puerto'),
          d.get('nro_cliente'),d.get('pppoe_usuario'),d.get('pppoe_clave'),
          d.get('cdo'),d.get('red'),d.get('torre_id'),d.get('ap_nombre')))
    cid = cur.lastrowid
    con.commit(); con.close()
    log('alta','Alta de cliente','','clientes')
    return jsonify({'ok':True,'id':cid})

# ── Asignación automática de IP y PPPoE (al pasar a Activación Pendiente) ──
def _asignar_ip_libre(con, localidad):
    """Devuelve la primera IP 169.254.X.H libre del rango que corresponda a la
    localidad (o de los rangos genéricos). Hosts 1-50 reservados para torres."""
    rangos = con.execute("SELECT * FROM ip_rangos WHERE activo=1 ORDER BY subred").fetchall()
    if not rangos:
        return None
    loc = (localidad or '').upper()
    especificos = [r for r in rangos if r['localidades'] and
                   any(l.strip() and l.strip() in loc for l in r['localidades'].upper().split(','))]
    candidatos = especificos or [r for r in rangos if not (r['localidades'] or '').strip()]
    if not candidatos:
        return None
    usadas = {(r['ip_asignada'] or '').strip()
              for r in con.execute("SELECT ip_asignada FROM clientes WHERE estado NOT IN ('baja','rescision')").fetchall()}
    for r in candidatos:
        for h in range(max(r['host_desde'], 51), min(r['host_hasta'], 254) + 1):
            ip = f"169.254.{r['subred']}.{h}"
            if ip not in usadas:
                return ip
    return None

def _generar_clave_pppoe():
    """Clave hexadecimal de 4 a 6 dígitos (ej: a54f3)."""
    import secrets, random
    return secrets.token_hex(3)[:random.randint(4, 6)]

# ── Permisos por bloque de campos del cliente (qué EDITA cada rol) ──
# Todos VEN todo; esto controla qué puede modificar cada rol.
BLOQUES_CAMPOS_CLIENTE = {
    'personales': ['nombre','dni','email','telefono','telefono2','direccion','localidad','lat','lng','nro_cliente'],
    'comercial':  ['plan','precio','agente','ultimo_pago','fecha_alta'],
    'tecnico':    ['tipo_servicio','nap','equipo_modelo','equipo_marca','equipo_serie','ip_asignada',
                   'mac_address','olt_nombre','olt_puerto','pppoe_usuario','pppoe_clave','cdo','red',
                   'torre_id','ap_nombre','necesita_nap',
                   'tiene_ip_publica','ip_publica','puertos_asignados','modo_equipo','vlan'],
    'estado':     ['estado','fecha_suspension','fecha_rescision','fecha_baja'],
    'observaciones': ['observaciones'],
}
# Qué bloques puede EDITAR cada rol
ROL_EDITA_BLOQUES = {
    'admin':          ['personales','comercial','tecnico','estado','observaciones'],
    'root':           ['personales','comercial','tecnico','estado','observaciones'],
    'tecnico':        ['personales','tecnico','observaciones'],
    'administrativo': ['personales','comercial','estado','observaciones'],
    'operador':       ['personales','observaciones'],
}

def _bloques_editables(rol):
    return ROL_EDITA_BLOQUES.get(rol, ['personales','observaciones'])

def _campos_editables(rol):
    """Set de campos que el rol puede modificar."""
    bloques = _bloques_editables(rol)
    campos = set()
    for b in bloques:
        campos.update(BLOQUES_CAMPOS_CLIENTE.get(b, []))
    return campos

@app.route('/api/clientes/permisos_campos')
@login_required
def cliente_permisos_campos():
    """Devuelve qué bloques de campos puede editar el usuario actual."""
    rol = session.get('rol', 'operador')
    return jsonify({
        'rol': rol,
        'bloques_editables': _bloques_editables(rol),
        'bloques': BLOQUES_CAMPOS_CLIENTE,
    })

@app.route('/api/clientes/<int:cid>', methods=['PUT'])
@login_required
def actualizar_cliente(cid):
    d = request.get_json()
    campos = ['nombre','dni','email','telefono','telefono2','direccion','localidad','lat','lng',
              'estado','tipo_servicio','plan','precio','nap','equipo_modelo','equipo_marca',
              'equipo_serie','ip_asignada','mac_address','fecha_alta','fecha_suspension',
              'fecha_rescision','fecha_baja','agente','observaciones','olt_nombre','olt_puerto',
              'nro_cliente','pppoe_usuario','pppoe_clave','cdo','red','torre_id','ap_nombre',
              'ultimo_pago','necesita_nap',
              'tiene_ip_publica','ip_publica','puertos_asignados','modo_equipo','vlan']
    # ── Filtro de permisos por campo según rol ──
    # admin/root editan todo; el resto solo sus bloques. Los campos no permitidos
    # se descartan silenciosamente (defensa real en el servidor, no solo en pantalla).
    rol = session.get('rol', 'operador')
    if rol not in ('admin', 'root'):
        permitidos = _campos_editables(rol)
        rechazados = [k for k in d.keys() if k in campos and k not in permitidos]
        for k in rechazados:
            d.pop(k, None)
        if rechazados:
            log('edicion', f'Campos no editados por permisos de rol ({rol}): {", ".join(rechazados)}', '', 'clientes')
    con = get_db()
    # ── Auto-limpiar el marcador "falta NAP" cuando ya tiene NAP asignada ──
    # Si se está asignando una NAP (o ya la tiene en la base), el flag necesita_nap
    # se apaga solo, así no queda resaltado en el mapa tras instalar.
    nap_nueva = d.get('nap')
    if nap_nueva is not None and str(nap_nueva).strip():
        d['necesita_nap'] = 0
    elif 'nap' not in d:
        # No están tocando la NAP en este update: si ya tiene una cargada, limpiar el flag igual
        actual_nap = con.execute("SELECT nap FROM clientes WHERE id=?", (cid,)).fetchone()
        if actual_nap and (actual_nap['nap'] or '').strip():
            d['necesita_nap'] = 0
    # ── Asignación automática al pasar a Activación Pendiente ──
    asignaciones = []
    if d.get('estado') == 'pte_activacion':
        actual = con.execute("""SELECT estado, tipo_servicio, localidad, nro_cliente,
                                pppoe_usuario, pppoe_clave, ip_asignada
                                FROM clientes WHERE id=?""", (cid,)).fetchone()
        if actual and actual['estado'] != 'pte_activacion':
            tipo = d.get('tipo_servicio', actual['tipo_servicio'])
            nro = d.get('nro_cliente', actual['nro_cliente'])
            # PPPoE para TODOS (inalámbrico y FTTH): usuario = nro_cliente, clave hex 4-6
            if nro and not (d.get('pppoe_usuario') or actual['pppoe_usuario']):
                d['pppoe_usuario'] = str(nro)
                asignaciones.append(f"Usuario PPPoE: {nro}")
            if not (d.get('pppoe_clave') or actual['pppoe_clave']):
                d['pppoe_clave'] = _generar_clave_pppoe()
                asignaciones.append(f"Clave PPPoE: {d['pppoe_clave']}")
            # IP solo para INALÁMBRICOS (FTTH no lleva IP de equipo)
            if tipo == 'inalambrico' and not (d.get('ip_asignada') or actual['ip_asignada']):
                ip = _asignar_ip_libre(con, d.get('localidad', actual['localidad']))
                if ip:
                    d['ip_asignada'] = ip
                    asignaciones.append(f"IP asignada: {ip}")
                else:
                    asignaciones.append("⚠ No hay IP libre en los rangos de esta localidad")
    # ── Liberación de IP al pasar a baja/rescisión ──
    if d.get('estado') in ('baja', 'rescision', 'pte_rescision'):
        actual = con.execute("SELECT estado, ip_asignada, nombre FROM clientes WHERE id=?", (cid,)).fetchone()
        if actual and actual['estado'] not in ('baja', 'rescision', 'pte_rescision'):
            ip_previa = (actual['ip_asignada'] or '').strip()
            if ip_previa and 'ip_asignada' not in d:
                d['ip_asignada'] = ''
                asignaciones.append(f"IP {ip_previa} liberada (vuelve al pool del rango)")
                log('edicion', f"IP {ip_previa} liberada por baja de {actual['nombre']}", '', 'clientes')
    sets = ', '.join(f"{c}=?" for c in campos if c in d)
    vals = [d[c] for c in campos if c in d]
    if not sets:
        con.close()
        return jsonify({'error':'no data'}), 400
    # Validación: avisar si IP o serie ya están en OTRO cliente (no bloquea, advierte)
    advertencias = []
    ip = (d.get('ip_asignada') or '').strip()
    if ip and ip not in ('0.0.0.0',) and ip.upper() != 'PPPOE':
        dup = con.execute("""SELECT nombre, nro_cliente FROM clientes
            WHERE TRIM(ip_asignada)=? AND id!=? AND estado NOT IN ('baja','rescision') LIMIT 3""",
            (ip, cid)).fetchall()
        if dup:
            advertencias.append(f"⚠ La IP {ip} ya está asignada a: " +
                ', '.join(f"{r['nombre']} (#{r['nro_cliente'] or 's/n'})" for r in dup))
    serie = (d.get('equipo_serie') or '').strip()
    if serie:
        dup = con.execute("""SELECT nombre, nro_cliente FROM clientes
            WHERE UPPER(TRIM(equipo_serie))=UPPER(?) AND id!=? AND estado NOT IN ('baja','rescision') LIMIT 3""",
            (serie, cid)).fetchall()
        if dup:
            advertencias.append(f"⚠ La serie {serie} ya está asignada a: " +
                ', '.join(f"{r['nombre']} (#{r['nro_cliente'] or 's/n'})" for r in dup))
    # ── Validación de NAP: inexistente (typo) o sin puertos libres ──
    # Solo cuando la NAP CAMBIA (no repite el aviso en cada edición del cliente).
    nap_chk = (d.get('nap') or '').strip()
    if nap_chk:
        prev_nap = con.execute("SELECT nap FROM clientes WHERE id=?", (cid,)).fetchone()
        nap_anterior = (prev_nap['nap'] or '').strip() if prev_nap else ''
        if nap_chk.upper() != nap_anterior.upper():
            nap_row = con.execute("SELECT capacidad FROM naps WHERE UPPER(TRIM(nombre))=UPPER(?)",
                                  (nap_chk,)).fetchone()
            if not nap_row:
                advertencias.append(f"⚠ La NAP '{nap_chk}' NO existe en el sistema — verificá el nombre (posible error de tipeo)")
            else:
                cap = nap_row['capacidad'] or NAP_LIMIT
                ocupados = con.execute("""SELECT COUNT(*) c FROM clientes
                    WHERE UPPER(TRIM(nap))=UPPER(?) AND estado!='baja' AND id!=?""",
                    (nap_chk, cid)).fetchone()['c']
                if ocupados + 1 > cap:
                    advertencias.append(f"🔴 La NAP {nap_chk} está LLENA ({ocupados}/{cap}): asignar este cliente la deja SOBREPASADA. No mandar técnico sin liberar un puerto")
                elif ocupados + 1 == cap:
                    advertencias.append(f"⚠ La NAP {nap_chk} queda COMPLETA con este cliente ({cap}/{cap}): es el último puerto libre")
    # ── Registrar cambio de abono/plan para el historial ──
    if 'plan' in d or 'precio' in d:
        prev = con.execute("SELECT plan, precio FROM clientes WHERE id=?", (cid,)).fetchone()
        if prev:
            cambio_plan = ('plan' in d and (d['plan'] or '') != (prev['plan'] or ''))
            cambio_precio = ('precio' in d and float(d.get('precio') or 0) != float(prev['precio'] or 0))
            if cambio_plan or cambio_precio:
                con.execute("""INSERT INTO historial_abono
                    (cliente_id, plan_anterior, plan_nuevo, precio_anterior, precio_nuevo, origen, usuario)
                    VALUES(?,?,?,?,?,'edición manual',?)""",
                    (cid, prev['plan'], d.get('plan', prev['plan']),
                     prev['precio'], d.get('precio', prev['precio']), session.get('username')))
    # Foto ANTES del UPDATE: es lo que permite registrar "de qué a qué".
    _antes = estado_actual(con, 'clientes', cid, campos)
    con.execute(f"UPDATE clientes SET {sets}, modificado=datetime('now','localtime') WHERE id=?",
                vals + [cid])
    # Auditoría con valor anterior y nuevo (plan estratégico §21). Reemplaza al
    # 'Edición de cliente' genérico, que no permitía saber qué se había tocado.
    # Si no cambió nada no se registra: guardar un formulario sin tocarlo no es
    # un evento auditable, y el ruido es lo que hace que nadie mire el historial.
    # (Ojo: acá NO se puede llamar a log(), que abre otra conexión sqlite3 con el
    #  UPDATE pendiente y da "database is locked".)
    auditar_cambio(con, 'clientes', 'Cliente', cid, _antes, d, campos)
    con.commit(); con.close()
    return jsonify({'ok':True, 'advertencias': advertencias, 'asignaciones': asignaciones})

@app.route('/api/clientes/<int:cid>', methods=['DELETE'])
@login_required
@admin_required
def borrar_cliente(cid):
    con = get_db()
    con.execute("DELETE FROM clientes WHERE id=?", (cid,))
    con.commit(); con.close()
    return jsonify({'ok':True})

# ─── MIGRACIÓN FTTH ───────────────────────────────────────────────
@app.route('/api/clientes/<int:cid>/ftth_potencial')
@login_required
def ftth_potencial(cid):
    """Detecta si cliente inalámbrico puede migrar a FTTH por vecindad"""
    con = get_db()
    c = con.execute("SELECT lat,lng,tipo_servicio FROM clientes WHERE id=?", (cid,)).fetchone()
    if not c or not c['lat']:
        con.close()
        return jsonify({'puede_migrar': False, 'razon': 'Sin coordenadas'})
    if c['tipo_servicio'] == 'fibra':
        con.close()
        return jsonify({'puede_migrar': False, 'razon': 'Ya es cliente de fibra'})
    # Buscar clientes de fibra en radio ~300m (0.003 grados ~= 300m)
    radio = 0.003
    vecinos = con.execute("""
        SELECT id, nombre, direccion, nap, lat, lng
        FROM clientes
        WHERE tipo_servicio='fibra' AND estado='activo'
        AND lat BETWEEN ? AND ?
        AND lng BETWEEN ? AND ?
        AND id != ?
    """, (c['lat']-radio, c['lat']+radio, c['lng']-radio, c['lng']+radio, cid)).fetchall()
    # NAPs cercanos
    naps_cercanos = con.execute("""
        SELECT nombre, lat, lng FROM naps
        WHERE lat BETWEEN ? AND ? AND lng BETWEEN ? AND ?
    """, (c['lat']-radio*2, c['lat']+radio*2, c['lng']-radio*2, c['lng']+radio*2)).fetchall()
    con.close()
    puede = len(vecinos) > 0 or len(naps_cercanos) > 0
    return jsonify({
        'puede_migrar': puede,
        'vecinos_fibra': len(vecinos),
        'naps_cercanos': [dict(n) for n in naps_cercanos],
        'vecinos': [dict(v) for v in vecinos[:5]]
    })

# ─── COBERTURA ────────────────────────────────────────────────────
@app.route('/api/cobertura')
@login_required
def evaluar_cobertura():
    """Evalúa cobertura para un punto (posible cliente)."""
    lat = float(request.args.get('lat', 0))
    lng = float(request.args.get('lng', 0))
    if not lat or not lng:
        return jsonify({'error': 'lat y lng requeridos'}), 400
    con = get_db()
    import math
    def _dist_m(lat1, lng1, lat2, lng2):
        R = 6371000
        dlat = math.radians(lat2 - lat1)
        dlng = math.radians(lng2 - lng1)
        a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng/2)**2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

    # Torres en radio de 5km
    radio_grados = 0.045  # ~5km
    torres = con.execute("""SELECT id,nombre,lat,lng,tipo,estado FROM torres
        WHERE lat BETWEEN ? AND ? AND lng BETWEEN ? AND ? AND estado='activa'""",
        (lat-radio_grados, lat+radio_grados, lng-radio_grados, lng+radio_grados)).fetchall()
    torres_cercanas = []
    for t in torres:
        d = _dist_m(lat, lng, t['lat'], t['lng'])
        if d <= 5000:
            torres_cercanas.append({'nombre':t['nombre'],'tipo':t['tipo'],'distancia_m':int(d)})
    torres_cercanas.sort(key=lambda x: x['distancia_m'])

    # NAPs en radio de 150m
    radio_nap = 0.0010  # ~150m
    naps = con.execute("""SELECT n.nombre, n.lat, n.lng, n.capacidad, n.nivel_senal,
        (SELECT COUNT(*) FROM clientes c WHERE c.nap=n.nombre AND c.estado!='baja') as ocupacion
        FROM naps n
        WHERE n.lat BETWEEN ? AND ? AND n.lng BETWEEN ? AND ? AND n.estado='activo'""",
        (lat-radio_nap, lat+radio_nap, lng-radio_nap, lng+radio_nap)).fetchall()
    naps_cercanos = []
    for n in naps:
        d = _dist_m(lat, lng, n['lat'], n['lng'])
        if d <= 100:
            libre = (n['capacidad'] or 8) - n['ocupacion']
            naps_cercanos.append({
                'nombre': n['nombre'],
                'distancia_m': int(d),
                'capacidad': n['capacidad'],
                'ocupacion': n['ocupacion'],
                'libre': libre,
                'lleno': libre <= 0,
                'senal': n['nivel_senal']
            })
    naps_cercanos.sort(key=lambda x: x['distancia_m'])

    # Determinar tipo sugerido
    tiene_nap = len(naps_cercanos) > 0
    tiene_torre = len(torres_cercanas) > 0
    tipo_sugerido = 'Fibra' if tiene_nap else ('Inalámbrico' if tiene_torre else 'Sin cobertura')

    con.close()
    return jsonify({
        'tiene_cobertura': tiene_nap or tiene_torre,
        'tipo_sugerido': tipo_sugerido,
        'torres_cercanas': torres_cercanas[:5],
        'naps_cercanos': naps_cercanos[:5],
    })

@app.route('/api/clientes/<int:cid>/senales')
@login_required
def get_senales_cliente(cid):
    con = get_db()
    rows = con.execute("SELECT * FROM historial_senal_cliente WHERE cliente_id=? ORDER BY fecha DESC LIMIT 20", (cid,)).fetchall()
    con.close()
    out = []
    for r in rows:
        d = dict(r)
        d['valor_dbm'] = d.get('nivel_dbm')  # el frontend lee 'valor_dbm'
        out.append(d)
    return jsonify(out)

@app.route('/api/clientes/<int:cid>/tendencia_senal')
@login_required
def cliente_tendencia_senal(cid):
    """Evolución de señal, CCQ y TX/RX del cliente a lo largo del tiempo,
    desde los chequeos del equipo (para graficar degradación progresiva)."""
    con = get_db()
    if not _table_exists(con, 'chequeos_equipo'):
        con.close()
        return jsonify({'puntos': []})
    rows = con.execute("""SELECT fecha, signal, ccq, tx_rate, rx_rate, ap_mac, ssid
                          FROM chequeos_equipo WHERE cliente_id=?
                          ORDER BY fecha ASC LIMIT 200""", (cid,)).fetchall()
    con.close()
    puntos = []
    def _num(v):
        try: return float(str(v).strip())
        except (ValueError, TypeError, AttributeError): return None
    for r in rows:
        puntos.append({
            'fecha': r['fecha'], 'signal': r['signal'], 'ccq': r['ccq'],
            'tx_rate': _num(r['tx_rate']), 'rx_rate': _num(r['rx_rate']),
            'ssid': r['ssid'], 'ap_mac': r['ap_mac'],
        })
    # Detectar tendencia de señal (¿está empeorando?)
    tendencia = None
    sigs = [p['signal'] for p in puntos if p['signal'] is not None]
    if len(sigs) >= 4:
        # Comparar promedio de la primera mitad vs la segunda
        mitad = len(sigs) // 2
        prom_ini = sum(sigs[:mitad]) / mitad
        prom_fin = sum(sigs[mitad:]) / (len(sigs) - mitad)
        delta = prom_fin - prom_ini
        if delta <= -5:
            tendencia = {'estado': 'empeorando', 'delta': round(delta, 1)}
        elif delta >= 5:
            tendencia = {'estado': 'mejorando', 'delta': round(delta, 1)}
        else:
            tendencia = {'estado': 'estable', 'delta': round(delta, 1)}
    return jsonify({'puntos': puntos, 'tendencia': tendencia, 'total': len(puntos)})

@app.route('/api/clientes/<int:cid>/senales', methods=['POST'])
@login_required
def crear_senal_cliente(cid):
    d = request.get_json() or {}
    try:
        dbm = float(d.get('valor_dbm'))
    except (TypeError, ValueError):
        return jsonify({'error':'valor_dbm inválido'}), 400
    con = get_db()
    con.execute("""INSERT INTO historial_senal_cliente(cliente_id, nivel_dbm, tipo, observaciones, usuario)
                   VALUES(?,?,?,?,?)""",
                (cid, dbm, d.get('tipo','medicion'),
                 d.get('observaciones',''), session.get('nombre','')))
    con.commit(); con.close()
    return jsonify({'ok':True})

@app.route('/api/clientes/migracion_ftth')
@login_required
def clientes_migracion_ftth():
    """Lista clientes inalámbricos con potencial de migración a FTTH"""
    con = get_db()
    inalambricos = con.execute("""
        SELECT id, nombre, lat, lng, direccion, localidad, plan, precio
        FROM clientes
        WHERE tipo_servicio='fibra' IS NOT 1 AND tipo_servicio!='fibra'
        AND estado='activo' AND lat IS NOT NULL AND lng IS NOT NULL
    """).fetchall()
    result = []
    radio = 0.003
    for c in inalambricos:
        vecinos = con.execute("""
            SELECT COUNT(*) FROM clientes
            WHERE tipo_servicio='fibra' AND estado='activo'
            AND lat BETWEEN ? AND ? AND lng BETWEEN ? AND ?
        """, (c['lat']-radio, c['lat']+radio, c['lng']-radio, c['lng']+radio)).fetchone()[0]
        if vecinos > 0:
            d = dict(c)
            d['vecinos_fibra'] = vecinos
            result.append(d)
    con.close()
    return jsonify(result)

# ─── NAPs ─────────────────────────────────────────────────────────
@app.route('/api/naps/ocupacion')
@login_required
def nap_ocupacion():
    """Ocupación de UNA NAP por nombre (liviano, para el aviso en vivo al asignar).
    Devuelve {existe, capacidad, total, libre}."""
    nombre = (request.args.get('nombre') or '').strip()
    if not nombre:
        return jsonify({'existe': False})
    con = get_db()
    nap = con.execute("SELECT capacidad FROM naps WHERE UPPER(TRIM(nombre))=UPPER(?)",
                      (nombre,)).fetchone()
    if not nap:
        con.close()
        return jsonify({'existe': False})
    cap = nap['capacidad'] or NAP_LIMIT
    total = con.execute("""SELECT COUNT(*) c FROM clientes
        WHERE UPPER(TRIM(nap))=UPPER(?) AND estado!='baja'""", (nombre,)).fetchone()['c']
    con.close()
    return jsonify({'existe': True, 'capacidad': cap, 'total': total, 'libre': cap - total})

@app.route('/api/naps')
@login_required
def get_naps():
    con = get_db()
    naps = con.execute("SELECT * FROM naps ORDER BY nombre").fetchall()
    # Incidencias activas que afectan NAPs
    inc_naps = {}
    try:
        incs = con.execute("""SELECT id, titulo, estado, nap_id, nap_nombre, objeto_ids
            FROM incidencias WHERE estado IN ('abierta','en_proceso')
            AND (nap_id IS NOT NULL OR (nap_nombre IS NOT NULL AND nap_nombre != '')
                 OR (objeto_ids IS NOT NULL AND objeto_ids != ''))""").fetchall()
        for i in incs:
            inc_data = {'titulo': i['titulo'], 'estado': i['estado']}
            # Por objeto_ids (JSON array de IDs de NAPs)
            if i['objeto_ids']:
                try:
                    ids = json.loads(i['objeto_ids'])
                    for nid in ids:
                        if nid not in inc_naps:
                            inc_naps[nid] = []
                        inc_naps[nid].append(inc_data)
                except:
                    pass
            # Por nap_nombre (puede ser "NAP1, NAP2, NAP3")
            if i['nap_nombre']:
                for nombre in i['nap_nombre'].split(','):
                    nombre = nombre.strip()
                    if nombre and nombre not in inc_naps:
                        inc_naps[nombre] = []
                    if nombre:
                        inc_naps[nombre].append(inc_data)
            # Por nap_id directo
            if i['nap_id'] and i['nap_id'] not in inc_naps:
                inc_naps[i['nap_id']] = []
                inc_naps[i['nap_id']].append(inc_data)
    except:
        pass

    result = []
    for n in naps:
        cap = n['capacidad'] or NAP_LIMIT
        clientes = con.execute("""
            SELECT id, nombre, nro_cliente, estado, tipo_servicio
            FROM clientes WHERE nap=? AND estado!='baja'
            ORDER BY nombre
        """, (n['nombre'],)).fetchall()
        total = len(clientes)
        nd = dict(n)
        nd['clientes'] = [dict(c) for c in clientes]
        nd['total'] = total
        nd['libre'] = cap - total
        nd['pct'] = round(total / cap * 100) if cap else 0
        # Validación: NAP sobrecargado (más clientes que el límite)
        nd['sobrecargado'] = total > NAP_LIMIT
        if nd['sobrecargado']:
            nd['exceso'] = total - NAP_LIMIT
            nd['requiere_revision'] = True
            if nd['estado'] not in ('mantenimiento','inactivo'):
                nd['estado'] = 'revision'
        # Incidencias del NAP
        nd['incidencias'] = inc_naps.get(n['id'], []) + inc_naps.get(n['nombre'], [])
        if nd['incidencias'] and nd['estado'] not in ('alerta','mantenimiento','inactivo','revision'):
            nd['estado'] = 'alerta'
        result.append(nd)
    con.close()
    return jsonify(result)

@app.route('/api/naps/<int:nid>/censar', methods=['POST'])
@login_required
def censar_nap(nid):
    """Registra el censo físico de una NAP: técnico, asistente, fecha, bocas físicas."""
    d = request.get_json() or {}
    con = get_db()
    nap = con.execute("SELECT nombre FROM naps WHERE id=?", (nid,)).fetchone()
    if not nap:
        con.close()
        return jsonify({'error': 'NAP no encontrada'}), 404
    fecha = d.get('fecha') or _now()[:10]
    con.execute("""UPDATE naps SET censada=1, censo_fecha=?, censo_tecnico=?,
                   censo_asistente=?, censo_bocas_fisicas=?, censo_notas=? WHERE id=?""",
                (fecha, d.get('tecnico',''), d.get('asistente',''),
                 d.get('bocas_fisicas'), d.get('notas',''), nid))
    con.commit()
    # Comparar bocas físicas vs clientes registrados (detectar discrepancia)
    registrados = con.execute("""SELECT COUNT(*) FROM clientes
        WHERE nap=? AND estado NOT IN ('baja','rescision')""", (nap['nombre'],)).fetchone()[0]
    con.close()
    fisicas = d.get('bocas_fisicas')
    discrepancia = None
    if fisicas is not None and int(fisicas) != registrados:
        discrepancia = {'fisicas': int(fisicas), 'registrados': registrados,
                        'diferencia': int(fisicas) - registrados}
    log('censo', f"NAP {nap['nombre']} censada por {d.get('tecnico','')}", '', 'naps')
    return jsonify({'ok': True, 'discrepancia': discrepancia})

@app.route('/api/naps', methods=['POST'])
@login_required
def crear_nap():
    d = request.get_json()
    con = get_db()
    # Verificar duplicados
    nombre = d.get('nombre','').strip()
    if not d.get('force'):
        dup = con.execute("SELECT id, nombre FROM naps WHERE nombre=?", (nombre,)).fetchone()
        if dup:
            con.close()
            return jsonify({'error':'duplicado','campo':'nombre','valor':nombre,
                           'conflicto_id':dup['id'],'conflicto_nombre':dup['nombre'],'puede_forzar':True})
        red = d.get('red','')
        cdo = d.get('cdo','').strip()
        nap_num = d.get('nap_numero')
        if red and cdo and nap_num:
            dup2 = con.execute("SELECT id, nombre FROM naps WHERE red=? AND cdo=? AND nap_numero=?",
                              (red, cdo, nap_num)).fetchone()
            if dup2:
                con.close()
                return jsonify({'error':'duplicado','campo':'red_cdo_numero',
                               'valor':f'{red}/CDO {cdo}/NAP {nap_num}',
                               'conflicto_id':dup2['id'],'conflicto_nombre':dup2['nombre'],'puede_forzar':True})

    con.execute("""INSERT INTO naps(nombre,descripcion,lat,lng,capacidad,localidad,estado,
                   nivel_senal,red,cdo,nap_numero,sitio)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (nombre,d.get('descripcion',''),d.get('lat'),d.get('lng'),
                 d.get('capacidad',NAP_LIMIT),d.get('localidad',''),d.get('estado','operativo'),
                 d.get('nivel_senal') or d.get('senal_alta'),
                 d.get('red',''),d.get('cdo',''),d.get('nap_numero'),d.get('sitio',d.get('red',''))))
    con.commit(); con.close()
    return jsonify({'ok':True})

@app.route('/api/naps/<int:nid>', methods=['PUT'])
@login_required
def actualizar_nap(nid):
    d = request.get_json()
    con = get_db()
    _campos_nap = ['nombre','descripcion','lat','lng','capacidad','localidad','estado',
                   'nivel_senal','red','cdo','nap_numero','sitio']
    _antes = estado_actual(con, 'naps', nid, _campos_nap)
    con.execute("""UPDATE naps SET nombre=?,descripcion=?,lat=?,lng=?,capacidad=?,localidad=?,estado=?,
                   nivel_senal=?,red=?,cdo=?,nap_numero=?,sitio=? WHERE id=?""",
                (d['nombre'],d.get('descripcion',''),d.get('lat'),d.get('lng'),
                 d.get('capacidad',NAP_LIMIT),d.get('localidad',''),d.get('estado','operativo'),
                 d.get('nivel_senal'),d.get('red',''),d.get('cdo',''),d.get('nap_numero'),
                 d.get('sitio',d.get('red','')),nid))
    auditar_cambio(con, 'naps', 'NAP', nid, _antes, d, _campos_nap)
    con.commit(); con.close()
    return jsonify({'ok':True})

@app.route('/api/naps/<int:nid>', methods=['DELETE'])
@login_required
def borrar_nap(nid):
    con = get_db()
    # Un borrado sin rastro es lo peor que puede pasarle a la trazabilidad:
    # después nadie puede reconstruir qué NAP existía ni qué clientes colgaban.
    _n = con.execute("SELECT nombre, localidad, capacidad FROM naps WHERE id=?", (nid,)).fetchone()
    _clientes = con.execute("SELECT COUNT(*) c FROM clientes WHERE nap=? AND estado!='baja'",
                            (_n['nombre'],)).fetchone()['c'] if _n else 0
    con.execute("DELETE FROM naps WHERE id=?", (nid,))
    if _n:
        con.execute("INSERT INTO historial(tipo,modulo,titulo,detalle,usuario) VALUES(?,?,?,?,?)",
                    ('baja', 'naps', f"NAP eliminada: {_n['nombre']}",
                     f"Localidad: {_n['localidad'] or '—'} · Capacidad: {_n['capacidad']} · "
                     f"Clientes activos que la referenciaban: {_clientes}",
                     session.get('username', 'sistema')))
    con.commit(); con.close()
    return jsonify({'ok':True})

@app.route('/api/naps/<int:nid>/asignar_olt', methods=['PUT'])
@login_required
def asignar_olt_nap(nid):
    d = request.get_json()
    olt = d.get('olt_nombre','')
    pon = d.get('olt_puerto','')
    con = get_db()
    con.execute("UPDATE naps SET olt_nombre=?, olt_puerto=? WHERE id=?", (olt, pon, nid))
    con.commit(); con.close()
    log('mod', f'NAP {nid}: OLT={olt} PON={pon}', '', 'naps')
    return jsonify({'ok':True})

@app.route('/api/naps/<int:nid>/clientes_afectados')
@login_required
def clientes_afectados_nap(nid):
    con = get_db()
    nap = con.execute("SELECT * FROM naps WHERE id=?", (nid,)).fetchone()
    if not nap:
        con.close()
        return jsonify({'error':'NAP no encontrado'}), 404
    clientes = con.execute("""
        SELECT id, nombre, nro_cliente, estado, tipo_servicio, telefono, plan
        FROM clientes WHERE nap=? AND estado!='baja'
        ORDER BY nombre
    """, (nap['nombre'],)).fetchall()
    con.close()
    return jsonify({
        'nap_nombre': nap['nombre'],
        'nap_estado': nap['estado'],
        'total': len(clientes),
        'clientes': [dict(c) for c in clientes]
    })

# ─── ABONOS / PLANES ──────────────────────────────────────────────
@app.route('/api/abonos')
@login_required
def get_abonos():
    con = get_db()
    rows = con.execute("SELECT * FROM abonos WHERE activo=1 ORDER BY tipo, precio").fetchall()
    con.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/abonos', methods=['POST'])
@login_required
def crear_abono():
    d = request.get_json()
    con = get_db()
    con.execute("""INSERT INTO abonos(nombre,tipo,precio,velocidad_bajada,velocidad_subida,descripcion)
                   VALUES(?,?,?,?,?,?)""",
                (d['nombre'],d['tipo'],d['precio'],
                 d.get('velocidad_bajada',0),d.get('velocidad_subida',0),d.get('descripcion','')))
    con.commit(); con.close()
    return jsonify({'ok':True})

@app.route('/api/abonos/<int:aid>', methods=['PUT'])
@login_required
def actualizar_abono(aid):
    d = request.get_json()
    con = get_db()
    con.execute("""UPDATE abonos SET nombre=?,tipo=?,precio=?,velocidad_bajada=?,
                   velocidad_subida=?,descripcion=?,activo=? WHERE id=?""",
                (d['nombre'],d['tipo'],d['precio'],
                 d.get('velocidad_bajada',0),d.get('velocidad_subida',0),
                 d.get('descripcion',''),d.get('activo',1),aid))
    con.commit(); con.close()
    return jsonify({'ok':True})

@app.route('/api/abonos/<int:aid>', methods=['DELETE'])
@login_required
def borrar_abono(aid):
    con = get_db()
    con.execute("UPDATE abonos SET activo=0 WHERE id=?", (aid,))
    con.commit(); con.close()
    return jsonify({'ok':True})

# ─── SERVICIOS / TICKETS ──────────────────────────────────────────
@app.route('/api/servicios')
@login_required
def get_servicios():
    estado = request.args.get('estado','')
    tipo = request.args.get('tipo','')
    tecnico = request.args.get('tecnico','')
    localidad = request.args.get('localidad','')
    prioridad = request.args.get('prioridad','')
    # Por defecto: solo servicios técnicos PENDIENTES reales (los que importan).
    # Para ver el histórico completo, pasar ?todos=1
    todos = request.args.get('todos','') == '1'

    sql = """SELECT s.*, c.nombre as cliente_nombre, c.telefono as cliente_tel,
             c.direccion as cliente_dir, c.localidad as cliente_localidad,
             c.tipo_servicio, c.plan as cliente_plan,
             c.ip_asignada, c.pppoe_usuario, c.pppoe_clave,
             c.nap as cliente_nap, c.olt_nombre, c.olt_puerto
             FROM servicios s LEFT JOIN clientes c ON s.cliente_id=c.id WHERE 1=1"""
    params = []

    if not todos and not estado and not tipo:
        # Vista por defecto: servicios técnicos pendientes
        sql += " AND s.tipo='servicio_tecnico' AND s.estado='pendiente'"
    else:
        if estado:
            sql += " AND s.estado=?"
            params.append(estado)
        if tipo:
            sql += " AND s.tipo=?"
            params.append(tipo)
    if tecnico:
        sql += " AND s.tecnico LIKE ?"
        params.append(f'%{tecnico}%')
    if localidad:
        sql += " AND c.localidad=?"
        params.append(localidad)
    if prioridad:
        sql += " AND s.prioridad=?"
        params.append(prioridad)
    sql += " ORDER BY CASE s.prioridad WHEN 'urgente' THEN 1 WHEN 'alta' THEN 2 WHEN 'normal' THEN 3 ELSE 4 END, s.fecha_programada DESC NULLS LAST, s.fecha_creacion DESC"

    con = get_db()
    rows = con.execute(sql, params).fetchall()
    con.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/servicios/por_tecnico')
@login_required
def servicios_por_tecnico():
    """Productividad por técnico de CAMPO (usa codtecnico).
    Separa técnicos de campo (según lista en configuracion) de usuarios admin.
    Filtros: ?desde=YYYY-MM-DD&hasta=YYYY-MM-DD&tipo=instalacion"""
    desde = request.args.get('desde','')
    hasta = request.args.get('hasta','')
    tipo = request.args.get('tipo','')
    con = get_db()
    # Piso de métricas: desde este mes en adelante por defecto.
    # Los datos históricos anteriores generan ruido (técnicos mal asignados, etc.),
    # así que solo se incluyen si el usuario pide un 'desde' explícito anterior.
    if not desde:
        desde = con.execute("SELECT strftime('%Y-%m-01','now','localtime')").fetchone()[0]

    # Lista de técnicos de campo (editable desde configuracion)
    row = con.execute("SELECT valor FROM configuracion WHERE clave='tecnicos_campo'").fetchone()
    tecnicos_campo = set()
    if row and row['valor']:
        tecnicos_campo = {t.strip().upper() for t in row['valor'].split(',') if t.strip()}

    # Técnico = codtecnico (el de campo asignado)
    sql = """
        SELECT COALESCE(NULLIF(tecnico,''), 'Sin asignar') AS tec,
               tipo,
               COUNT(*) AS cantidad,
               SUM(CASE WHEN estado='completado' THEN 1 ELSE 0 END) AS realizados,
               SUM(CASE WHEN estado='pendiente' THEN 1 ELSE 0 END) AS pendientes
        FROM servicios WHERE 1=1
    """
    params = []
    if desde:
        sql += " AND (fecha_realizacion >= ? OR fecha_creacion >= ?)"; params += [desde, desde]
    if hasta:
        sql += " AND (fecha_realizacion <= ? OR fecha_creacion <= ?)"; params += [hasta, hasta]
    if tipo:
        sql += " AND tipo=?"; params.append(tipo)
    sql += " GROUP BY tec, tipo ORDER BY tec, cantidad DESC"
    rows = con.execute(sql, params).fetchall()

    agg = {}
    for r in rows:
        t = r['tec']
        if t not in agg:
            agg[t] = {'tecnico': t, 'total': 0, 'realizados': 0, 'pendientes': 0, 'por_tipo': {}}
        agg[t]['total'] += r['cantidad']
        agg[t]['realizados'] += r['realizados'] or 0
        agg[t]['pendientes'] += r['pendientes'] or 0
        agg[t]['por_tipo'][r['tipo']] = r['cantidad']
    con.close()

    # Separar en campo vs admin según la lista
    campo, admin = [], []
    for t in sorted(agg.values(), key=lambda x: -x['total']):
        nombre_up = t['tecnico'].upper()
        if not tecnicos_campo:
            # Si no hay lista configurada, todo va junto en "campo"
            campo.append(t)
        elif nombre_up in tecnicos_campo:
            campo.append(t)
        elif t['tecnico'] == 'Sin asignar':
            pass  # los sin asignar no van a ninguna tabla de personas
        else:
            admin.append(t)

    return jsonify({
        'tecnicos_campo': campo,
        'usuarios_admin': admin,
        'lista_configurada': bool(tecnicos_campo),
    })

@app.route('/api/servicios', methods=['POST'])
@login_required
def crear_servicio():
    d = request.get_json()
    estado = d.get('estado','pendiente')
    if estado == 'cerrado':
        estado = 'completado'
    con = get_db()
    cur = con.execute("""INSERT INTO servicios(cliente_id,tipo,subtipo,descripcion,tecnico,
                         estado,prioridad,costo,tiene_costo,diagnostico,solucion_aplicada,creado_por)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (d.get('cliente_id'),d['tipo'],d.get('subtipo',''),
                       d.get('descripcion',''),d.get('tecnico',''),
                       estado,d.get('prioridad','normal'),
                       d.get('costo',0),d.get('tiene_costo',0),
                       d.get('diagnostico',''),d.get('solucion_aplicada',''),
                       session.get('username')))
    con.commit(); con.close()
    # Alerta Telegram automática si el servicio es urgente
    if d.get('prioridad') == 'urgente':
        try:
            cli = ''
            if d.get('cliente_id'):
                con2 = get_db()
                c = con2.execute("SELECT nombre, localidad FROM clientes WHERE id=?", (d['cliente_id'],)).fetchone()
                con2.close()
                if c: cli = f"\n👤 {c['nombre']} ({c['localidad'] or ''})"
            enviar_telegram(f"🚨 <b>Servicio URGENTE creado</b>\n🔧 {d['tipo']}{cli}\n📝 {d.get('descripcion','')[:200]}\n— por {session.get('username')}")
        except Exception:
            pass  # la alerta nunca debe romper la creación
    return jsonify({'ok':True,'id':cur.lastrowid})

@app.route('/api/servicios/<int:sid>', methods=['PUT'])
@login_required
def actualizar_servicio(sid):
    d = request.get_json()
    con = get_db()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    # Normalizar estado: el frontend manda 'cerrado', el sistema usa 'completado'
    estado = d.get('estado')
    if estado == 'cerrado':
        estado = 'completado'
    # Cancelación: el motivo es obligatorio
    if estado == 'cancelado':
        motivo = (d.get('motivo_cancelacion') or '').strip()
        if not motivo:
            con.close()
            return jsonify({'error': 'Para cancelar tenés que indicar el motivo'}), 400
        con.execute("""UPDATE servicios SET estado='cancelado', motivo_cancelacion=?,
                       fecha_cancelacion=?, observaciones=COALESCE(observaciones,'')||? WHERE id=?""",
                    (motivo, now, f"\n[Cancelado {now[:10]}: {motivo}]", sid))
        con.commit(); con.close()
        log('cancelacion', f'Instalación cancelada (servicio #{sid})', motivo, 'servicios')
        return jsonify({'ok': True, 'cancelado': True})
    # Auto-fechas de estado
    fa = d.get('fecha_asignacion')
    fi = d.get('fecha_inicio')
    fc = d.get('fecha_cierre')
    fr = d.get('fecha_realizacion')
    # Estados ampliados del flujo de trabajo del técnico (Fase 4):
    #   pendiente → asignado → en_camino → en_proceso → completado
    #   (requiere_seguimiento: sigue abierto, quedó pendiente de una segunda visita)
    if estado in ('asignado', 'en_camino', 'en_proceso') and not fa:
        fa = now  # al asignar/arrancar queda registrada la asignación
    if estado == 'en_camino':
        d.setdefault('_fecha_en_camino', now)
    if estado == 'en_proceso' and not fi:
        fi = now
    if estado == 'completado':
        if not fc: fc = now
        if not fr: fr = now
    # columnas extra por estado (en_camino / requiere_seguimiento)
    f_encamino = now if estado == 'en_camino' else None
    f_segui = now if estado == 'requiere_seguimiento' else None
    con.execute("""UPDATE servicios SET tipo=?,subtipo=?,descripcion=?,tecnico=?,
                   estado=?,prioridad=?,costo=?,tiene_costo=?,observaciones=?,
                   diagnostico=?,solucion_aplicada=?,
                   fecha_asignacion=COALESCE(?,fecha_asignacion),
                   fecha_inicio=COALESCE(?,fecha_inicio),
                   fecha_cierre=COALESCE(?,fecha_cierre),
                   fecha_en_camino=COALESCE(?,fecha_en_camino),
                   fecha_seguimiento=COALESCE(?,fecha_seguimiento),
                   fecha_realizacion=COALESCE(?,fecha_realizacion) WHERE id=?""",
                (d.get('tipo'),d.get('subtipo'),d.get('descripcion'),d.get('tecnico'),
                 estado,d.get('prioridad','normal'),d.get('costo',0),
                 d.get('tiene_costo',0),d.get('observaciones'),
                 d.get('diagnostico',''),d.get('solucion_aplicada',''),
                 fa, fi, fc, f_encamino, f_segui, fr, sid))
    con.commit(); con.close()
    return jsonify({'ok':True})

@app.route('/api/servicios/<int:sid>', methods=['DELETE'])
@login_required
def borrar_servicio(sid):
    con = get_db()
    con.execute("DELETE FROM servicios WHERE id=?", (sid,))
    con.commit(); con.close()
    return jsonify({'ok':True})

# ══════════ MATERIALES CONSUMIDOS EN UN SERVICIO (Fase 5) ══════════
@app.route('/api/servicios/<int:sid>/materiales')
@login_required
def servicio_materiales(sid):
    """Lista los materiales (a granel) consumidos en una orden de servicio."""
    con = get_db()
    filas = con.execute("""SELECT m.id, m.inventario_id, m.descripcion, m.cantidad, m.fecha, m.usuario,
                                  i.nombre AS material, i.unidad
                           FROM stock_movimientos m
                           LEFT JOIN stock_inventario i ON i.id = m.inventario_id
                           WHERE m.servicio_id=? AND m.tipo='consumo_servicio'
                           ORDER BY m.fecha DESC""", (sid,)).fetchall()
    con.close()
    return jsonify([dict(f) for f in filas])

@app.route('/api/servicios/<int:sid>/materiales', methods=['POST'])
@login_required
def servicio_agregar_materiales(sid):
    """Descuenta material del inventario a granel y lo registra contra el servicio.
    Body: {items:[{inventario_id, cantidad}, ...]}. Valida stock suficiente."""
    d = request.get_json() or {}
    items = d.get('items', [])
    if not items:
        return jsonify({'error': 'Sin materiales'}), 400
    con = get_db()
    srv = con.execute("SELECT id, cliente_id FROM servicios WHERE id=?", (sid,)).fetchone()
    if not srv:
        con.close(); return jsonify({'error': 'Servicio no encontrado'}), 404
    cli = con.execute("SELECT nombre FROM clientes WHERE id=?", (srv['cliente_id'],)).fetchone() if srv['cliente_id'] else None
    cli_nombre = cli['nombre'] if cli else None
    usuario = session.get('nombre') or session.get('username') or 'sistema'
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # Validar stock ANTES de descontar (todo o nada)
    faltantes = []
    for it in items:
        iid = it.get('inventario_id'); cant = int(it.get('cantidad', 0) or 0)
        if not iid or cant <= 0:
            continue
        inv = con.execute("SELECT nombre, cantidad FROM stock_inventario WHERE id=?", (iid,)).fetchone()
        if not inv:
            faltantes.append(f"material #{iid} inexistente")
        elif (inv['cantidad'] or 0) < cant:
            faltantes.append(f"{inv['nombre']} (hay {inv['cantidad']}, pedís {cant})")
    if faltantes:
        con.close()
        return jsonify({'error': 'Stock insuficiente: ' + '; '.join(faltantes)}), 400

    guardados = 0
    for it in items:
        iid = it.get('inventario_id'); cant = int(it.get('cantidad', 0) or 0)
        if not iid or cant <= 0:
            continue
        inv = con.execute("SELECT nombre FROM stock_inventario WHERE id=?", (iid,)).fetchone()
        con.execute("UPDATE stock_inventario SET cantidad = cantidad - ? WHERE id=?", (cant, iid))
        con.execute("""INSERT INTO stock_movimientos(inventario_id, tipo, descripcion, cantidad,
                       cliente_id, cliente_nombre, usuario, servicio_id, fecha)
                       VALUES(?,?,?,?,?,?,?,?,?)""",
                    (iid, 'consumo_servicio', f"Consumo en servicio #{sid}: {inv['nombre']}",
                     cant, srv['cliente_id'], cli_nombre, usuario, sid, now))
        guardados += 1
    con.commit(); con.close()
    return jsonify({'ok': True, 'guardados': guardados})

@app.route('/api/servicios/materiales/<int:mid>', methods=['DELETE'])
@login_required
def servicio_borrar_material(mid):
    """Revierte un consumo: devuelve la cantidad al inventario y borra el movimiento."""
    con = get_db()
    m = con.execute("SELECT inventario_id, cantidad FROM stock_movimientos WHERE id=? AND tipo='consumo_servicio'", (mid,)).fetchone()
    if not m:
        con.close(); return jsonify({'error': 'Movimiento no encontrado'}), 404
    if m['inventario_id'] and m['cantidad']:
        con.execute("UPDATE stock_inventario SET cantidad = cantidad + ? WHERE id=?", (m['cantidad'], m['inventario_id']))
    con.execute("DELETE FROM stock_movimientos WHERE id=?", (mid,))
    con.commit(); con.close()
    return jsonify({'ok': True})

# ─── OLTs ─────────────────────────────────────────────────────────
@app.route('/api/olts')
@login_required
def get_olts():
    con = get_db()
    olts = con.execute("SELECT * FROM olts ORDER BY nombre").fetchall()
    result = []
    for o in olts:
        od = dict(o)
        # Traer todos los clientes de esta OLT una sola vez
        todos = con.execute("""
            SELECT id, nombre, estado, equipo_serie, olt_puerto
            FROM clientes
            WHERE UPPER(TRIM(COALESCE(olt_nombre,''))) = UPPER(TRIM(?)) AND estado!='baja'
        """, (o['nombre'],)).fetchall()

        # Agrupar por número de PON. olt_puerto puede venir como:
        #   "PON1:5" (formato de asignar_nap_olt.py) o "1" (formato viejo)
        import re as _re
        por_pon = {}
        for c in todos:
            pp = (c['olt_puerto'] or '').strip()
            # Formato esperado: "PON1:5". Evitar matchear el PON de "GPON".
            m = _re.search(r'(?<![A-Za-z])PON\s*(\d+)', pp, _re.I)
            if not m:
                # Formato crudo tipo GPON0/1:2 → tomar el segundo número (puerto)
                m2 = _re.search(r'GPON\d+/(\d+)', pp, _re.I)
                if m2:
                    num = int(m2.group(1))
                elif pp.isdigit():
                    num = int(pp)
                else:
                    num = 0
            else:
                num = int(m.group(1))
            por_pon.setdefault(num, []).append(c)

        puertos = []
        for p in range(1, (o['puertos_pon'] or 4) + 1):
            clientes = por_pon.get(p, [])
            by_estado = {}
            for c in clientes:
                by_estado[c['estado']] = by_estado.get(c['estado'], 0) + 1
            puertos.append({
                'puerto': p,
                'total': len(clientes),
                'activos': by_estado.get('activo', 0),
                'suspendidos': by_estado.get('suspendido', 0),
                'rescision': by_estado.get('rescision', 0),
                'clientes': [dict(c) for c in clientes],
            })
        # Clientes sin PON identificable (num=0) van a un grupo aparte
        sin_pon = por_pon.get(0, [])
        od['puertos'] = puertos
        od['sin_pon'] = len(sin_pon)
        od['total_clientes'] = len(todos)
        result.append(od)
    con.close()
    return jsonify(result)

@app.route('/api/olts', methods=['POST'])
@login_required
def crear_olt():
    d = request.get_json()
    con = get_db()
    con.execute("""INSERT INTO olts(nombre,ip_remota,ip_red,puertos_pon,lat,lng,ubicacion,modelo,onu_max_pon)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (d['nombre'],d.get('ip_remota'),d.get('ip_red'),
                 d.get('puertos_pon',4),d.get('lat'),d.get('lng'),
                 d.get('ubicacion'),d.get('modelo'),d.get('onu_max_pon',128)))
    con.commit(); con.close()
    return jsonify({'ok':True})

@app.route('/api/olts/<int:oid>', methods=['PUT'])
@login_required
def actualizar_olt(oid):
    d = request.get_json()
    con = get_db()
    con.execute("""UPDATE olts SET nombre=?,ip_remota=?,ip_red=?,puertos_pon=?,
                   lat=?,lng=?,ubicacion=?,modelo=?,activa=?,
                   onu_max_pon=COALESCE(?,onu_max_pon) WHERE id=?""",
                (d['nombre'],d.get('ip_remota'),d.get('ip_red'),
                 d.get('puertos_pon',4),d.get('lat'),d.get('lng'),
                 d.get('ubicacion'),d.get('modelo'),d.get('activa',1),
                 d.get('onu_max_pon'),oid))
    con.commit(); con.close()
    return jsonify({'ok':True})

@app.route('/api/olts/<int:oid>', methods=['DELETE'])
@login_required
def borrar_olt(oid):
    con = get_db()
    con.execute("DELETE FROM olts WHERE id=?", (oid,))
    con.commit(); con.close()
    return jsonify({'ok':True})

# ─── MONITOREO SNMP DE OLT (Fase 1) ───────────────────────────────
@app.route('/api/ftth/pons')
@requiere_permiso('monitoreo')
def ftth_pons():
    """Topología y capacidad/salud de todos los PONs de todas las OLTs.
    Agrupa las ONU reportadas (onu_senal) por OLT y PON, cruza con la capacidad
    del split (olts.onu_max_pon) y evalúa saturación + salud óptica."""
    import ftth
    con = get_db()
    olts = con.execute("""SELECT id, nombre, ubicacion, puertos_pon,
                          COALESCE(onu_max_pon, 64) AS onu_max_pon, online
                          FROM olts WHERE activa=1 ORDER BY nombre""").fetchall()
    onus = con.execute("""SELECT olt_id, pon, onu, rx_power, online
                          FROM onu_senal ORDER BY olt_id, pon, onu""").fetchall()
    con.close()

    porpon = {}
    for o in onus:
        porpon.setdefault((o['olt_id'], o['pon']), []).append(o)

    resultado = []
    resumen = {'olts': len(olts), 'pons': 0, 'criticos': 0, 'advertencia': 0,
               'normal': 0, 'sin_datos': 0, 'onus_total': 0, 'onus_offline': 0}
    for olt in olts:
        cap = olt['onu_max_pon'] or 64
        pons_olt = []
        pon_ids = sorted({p for (oid, p) in porpon.keys() if oid == olt['id']})
        for pon in pon_ids:
            lista = porpon.get((olt['id'], pon), [])
            total = len(lista)
            online = sum(1 for x in lista if x['online'] == 1)
            rx = [x['rx_power'] for x in lista if x['online'] == 1 and x['rx_power'] is not None]
            ev = ftth.evaluar_pon(total, online, cap, rx)
            pons_olt.append({'pon': pon, **ev})
            resumen['pons'] += 1
            resumen['onus_total'] += total
            resumen['onus_offline'] += ev['onus_offline']
            k = ev['estado'] if ev['estado'] in ('critico', 'advertencia', 'normal') else 'sin_datos'
            resumen['criticos' if k == 'critico' else k] += 1
        resultado.append({
            'olt_id': olt['id'], 'olt': olt['nombre'], 'ubicacion': olt['ubicacion'],
            'online': olt['online'], 'capacidad_pon': cap,
            'puertos_pon': olt['puertos_pon'], 'pons': pons_olt,
        })
    return jsonify({'olts': resultado, 'resumen': resumen})

def _salud_olt(o, espectro):
    """Estado de una OLT + el MOTIVO en texto. Antes la UI decía 'revisar' sin
    explicar por qué. Devuelve (estado, motivo).
    Estados: optimo / alerta / critico / muerto."""
    if not (o['online'] or 0):
        return 'muerto', 'La OLT no responde SNMP'
    t = o['temperatura']
    # La OLT sólo expone la temperatura de los SFP de cada PON (no hay sensor de
    # chasis; ver el comentario en olt_poller.py). Medidas reales en producción:
    # 39-42°C, y el límite típico de un SFP industrial ronda los 70-85°C, así que
    # 60/70 deja margen sin cazar falsos positivos.
    # 'chasis' queda contemplado sólo por compatibilidad con datos ya guardados
    # por versiones viejas del poller.
    fuente = (o['temp_fuente'] if 'temp_fuente' in o.keys() else None) or 'sfp'
    if fuente == 'chasis':
        u_crit, u_alerta, etiqueta = 55, 50, 'chasis'
    else:
        u_crit, u_alerta, etiqueta = 70, 60, 'SFP'
    if t is not None and t >= u_crit:
        return 'critico', f'Temperatura {t}°C ({etiqueta}, crítica ≥{u_crit}°C)'
    e = espectro or {}
    tot = e.get('total') or 0
    if tot:
        crit = e.get('critico') or 0
        sin = e.get('sin_senal') or 0
        alert = e.get('alerta') or 0
        sat = e.get('saturado') or 0
        # Una sola ONU saturada ya se avisa: no es un problema estadístico sino
        # un daño concreto en ese enlace (atenuador de menos o fibra demasiado
        # corta), y con el tiempo quema el receptor de la ONU.
        if sat:
            return 'alerta', (f'{sat} ONU recibiendo DEMASIADA luz (> -8 dBm): '
                              f'falta atenuación, revisar antes de que se dañe el receptor')
        mal = crit + sin
        if mal / tot > 0.15:
            partes = []
            if crit: partes.append(f'{crit} con señal crítica (<-29 dBm)')
            if sin:  partes.append(f'{sin} sin lectura de señal')
            return 'critico', f'{round(mal/tot*100)}% de {tot} ONU con problema: ' + ' y '.join(partes)
        if (alert + mal) / tot > 0.25:
            return 'alerta', f'{round((alert+mal)/tot*100)}% de {tot} ONU con señal degradada (≤-26 dBm)'
    if t is not None and t >= u_alerta:
        return 'alerta', f'Temperatura {t}°C ({etiqueta}, alta ≥{u_alerta}°C)'
    if not tot:
        return 'optimo', 'Sin ONU con lectura reciente'
    return 'optimo', f'{tot} ONU con señal normal'


@app.route('/api/olts/estado')
@requiere_permiso('monitoreo')
def olts_estado():
    """Estado de monitoreo SNMP de las OLT (para la vista de Monitoreo)."""
    con = get_db()
    olts = con.execute("SELECT * FROM olts WHERE activa=1 ORDER BY nombre").fetchall()
    result = []
    for o in olts:
        try:
            puertos = json.loads(o['puertos_json']) if o['puertos_json'] else []
        except Exception:
            puertos = []
        # Normalizar los puertos guardados: el poller viejo sólo guardaba
        # {'nombre','up'} y el frontend busca 'puerto' (el número de PON con el
        # que cruza contra onu_senal). Sin esto, TODOS los PON mostraban 0
        # clientes porque la clave nunca coincidía.
        import re as _re
        for p in puertos:
            if p.get('puerto') is None:
                nums = _re.findall(r'(\d+)', str(p.get('nombre', '')))
                p['puerto'] = int(nums[-1]) if nums else None
            if 'es_pon' not in p:
                p['es_pon'] = 'GPON' in str(p.get('nombre', '')).upper()
        # Conteo REAL de clientes por PON, desde la data SNMP de las ONU.
        # Mismo criterio de frescura que el espectro: las ONU que no se leyeron
        # en las últimas 6 h no se cuentan (si no, un PON mostraba ONU dadas de
        # baja hace meses y el total quedaba inflado).
        pon_data = {}
        for r in con.execute("""SELECT pon, COUNT(*) total,
                                       SUM(CASE WHEN online=1 THEN 1 ELSE 0 END) onl
                                FROM onu_senal
                                WHERE olt_id=?
                                  AND (last_check IS NULL OR
                                       last_check >= datetime('now','localtime','-6 hours'))
                                GROUP BY pon""", (o['id'],)).fetchall():
            onl = r['onl'] or 0
            pon_data[str(r['pon'])] = {'total': r['total'], 'online': onl, 'offline': r['total'] - onl}
        # Espectro óptico: cómo se reparten las señales de esta OLT por franja de dBm.
        # Sólo cuenta ONU con lectura RECIENTE: las filas viejas que quedaron con
        # rx_power NULL (ONU dadas de baja, lecturas truncadas de antes) inflaban
        # 'sin_senal' y dejaban la OLT en "revisar" para siempre.
        # OJO con el extremo de arriba: DEMASIADA luz también es una falla. Un
        # receptor GPON se satura por encima de -8 dBm y se daña con el tiempo;
        # antes esas ONU entraban en 'optimo' (la condición era rx >= -23) y una
        # ONU a -1.5 dBm figuraba como perfecta. Ahora se separan en 'saturado'.
        esp = con.execute("""
            SELECT
              SUM(CASE WHEN rx_power > -8 THEN 1 ELSE 0 END) AS saturado,
              SUM(CASE WHEN rx_power <= -8 AND rx_power >= -23 THEN 1 ELSE 0 END) AS optimo,
              SUM(CASE WHEN rx_power < -23 AND rx_power >= -26 THEN 1 ELSE 0 END) AS normal,
              SUM(CASE WHEN rx_power < -26 AND rx_power >= -29 THEN 1 ELSE 0 END) AS alerta,
              SUM(CASE WHEN rx_power < -29 THEN 1 ELSE 0 END) AS critico,
              SUM(CASE WHEN rx_power IS NULL THEN 1 ELSE 0 END) AS sin_senal,
              AVG(rx_power) AS media,
              COUNT(*) AS total
            FROM onu_senal
            WHERE olt_id=?
              AND (last_check IS NULL OR last_check >= datetime('now','localtime','-6 hours'))
            """, (o['id'],)).fetchone()
        # ONU con datos viejos (no se leyeron en el último ciclo): se informan
        # aparte en vez de contarlas como caídas.
        rancias = con.execute("""SELECT COUNT(*) c FROM onu_senal
            WHERE olt_id=? AND last_check IS NOT NULL
              AND last_check < datetime('now','localtime','-6 hours')""",
            (o['id'],)).fetchone()['c']
        espectro = {
            'optimo': esp['optimo'] or 0, 'normal': esp['normal'] or 0,
            'alerta': esp['alerta'] or 0, 'critico': esp['critico'] or 0,
            'sin_senal': esp['sin_senal'] or 0, 'total': esp['total'] or 0,
            'rancias': rancias,
            'media': round(esp['media'], 2) if esp['media'] is not None else None,
        }
        # Estado de salud + MOTIVO. Antes el frontend decía "revisar" sin decir
        # por qué; ahora el motivo viaja junto al estado.
        salud, motivo = _salud_olt(o, espectro)
        result.append({
            'id': o['id'], 'nombre': o['nombre'],
            'ip': o['ip_red'] or o['ip_remota'],
            'modelo': o['modelo'], 'ubicacion': o['ubicacion'],
            'community': o['community'] or 'public',
            'version_snmp': o['version_snmp'] or '2c',
            'snmp_activo': o['snmp_activo'] or 0,
            'online': o['online'] or 0,
            'last_check': o['last_check'],
            'uptime_seg': o['uptime_seg'],
            'firmware': o['firmware_snmp'],
            'temperatura': o['temperatura'],
            'voltaje': o['voltaje'],
            'puertos': puertos,
            'pon_data': pon_data,
            'salud': salud,
            'motivo': motivo,
            'espectro': espectro,
            'total_clientes': con.execute(
                """SELECT COUNT(*) c FROM (
                       -- Por nombre de OLT (normalizado: mayúsculas/espacios no importan)
                       SELECT id FROM clientes
                        WHERE UPPER(TRIM(COALESCE(olt_nombre,''))) = UPPER(TRIM(?))
                          AND estado!='baja'
                       UNION
                       -- Y por vínculo REAL vía SNMP (olt_id en onu_senal), que no
                       -- depende de cómo esté escrito el nombre en la ficha.
                       -- Se compara tolerando ceros a la izquierda ('035994'=='35994'),
                       -- por si el poller y el ERP guardan el código con distinto padding.
                       SELECT c.id FROM clientes c
                         JOIN onu_senal s
                           ON s.nro_cliente = c.nro_cliente
                           OR CAST(s.nro_cliente AS INTEGER) = CAST(c.nro_cliente AS INTEGER)
                        WHERE s.olt_id = ? AND c.estado!='baja'
                          AND s.nro_cliente IS NOT NULL AND TRIM(s.nro_cliente) != ''
                   )""",
                (o['nombre'], o['id'])).fetchone()['c'],
        })
    con.close()
    return jsonify(result)

@app.route('/api/olts/<int:oid>/snmp', methods=['PUT'])
@requiere_permiso('monitoreo')
def olt_config_snmp(oid):
    """Configura el SNMP de una OLT (community, versión, activar monitoreo)."""
    d = request.get_json()
    con = get_db()
    con.execute("UPDATE olts SET community=?, version_snmp=?, snmp_activo=? WHERE id=?",
                (d.get('community', 'public'), d.get('version_snmp', '2c'),
                 1 if d.get('snmp_activo') else 0, oid))
    con.commit(); con.close()
    return jsonify({'ok': True})

@app.route('/api/olts/<int:oid>/poll', methods=['POST'])
@requiere_permiso('monitoreo')
def olt_poll_ahora(oid):
    """Pollea una OLT bajo demanda (botón Actualizar)."""
    con = get_db()
    o = con.execute("SELECT * FROM olts WHERE id=?", (oid,)).fetchone()
    if not o:
        con.close(); return jsonify({'error': 'OLT no encontrada'}), 404
    try:
        import olt_poller
        m = olt_poller.pollear_una(con, o)
        # Si respondió, leer también la señal de las ONU y recalcular alertas:
        # el botón "Actualizar" debe dejar TODO al día, no solo el estado del equipo.
        n_onus = 0
        if m.get('online'):
            try:
                n_onus, completa = olt_poller.pollear_optica(con, o)
                olt_poller.detectar_alertas_infra(con, {o['id']} if completa else set())
            except Exception:
                pass
    except Exception as e:
        con.close(); return jsonify({'error': f'Error al pollear: {e}'}), 500
    con.close()
    return jsonify({'ok': True, 'onus': n_onus, 'metricas': {
        'online': m.get('online'), 'uptime_seg': m.get('uptime_seg'),
        'temperatura': m.get('temperatura'), 'voltaje': m.get('voltaje'),
        'firmware': m.get('firmware'), 'puertos': m.get('puertos', [])
    }})

@app.route('/api/olts/<int:oid>/clientes_por_pon')
@login_required
def olt_clientes_por_pon(oid):
    """Clientes de un puerto PON, cruzando el registro con la señal real de la ONU."""
    pon = request.args.get('pon', '')
    con = get_db()
    o = con.execute("SELECT nombre FROM olts WHERE id=?", (oid,)).fetchone()
    if not o:
        con.close(); return jsonify({'error': 'OLT no encontrada'}), 404
    # 1) Los que reporta la OLT por SNMP (fuente de verdad del equipo)
    filas = con.execute("""
        SELECT s.pon, s.onu, s.nro_cliente, s.rx_power, s.tx_power, s.online,
               s.serial_onu, s.last_check,
               c.id, c.nombre, c.estado, c.plan, c.telefono, c.direccion,
               c.localidad, c.nap, c.ip_asignada, c.equipo_serie
        FROM onu_senal s
        LEFT JOIN clientes c ON c.nro_cliente = s.nro_cliente
        WHERE s.olt_id=? AND s.pon=?
        ORDER BY s.onu
    """, (oid, pon)).fetchall()
    clientes = []
    vistos = set()
    for f in filas:
        d = dict(f)
        d['origen'] = 'olt'
        d['serial_coincide'] = _serial_match(f['serial_onu'], f['equipo_serie'])
        if f['nro_cliente']:
            vistos.add(f['nro_cliente'])
        clientes.append(d)
    # 2) Los que están asignados a este PON en Pucará pero la OLT no reporta
    #    (útil para detectar registros desactualizados)
    try:
        extra = con.execute("""
            SELECT id, nombre, nro_cliente, estado, plan, telefono, direccion,
                   localidad, nap, ip_asignada
            FROM clientes
            WHERE UPPER(TRIM(COALESCE(olt_nombre,''))) = UPPER(TRIM(?))
              AND CAST(olt_puerto AS TEXT)=? AND estado!='baja'
        """, (o['nombre'], str(pon))).fetchall()
        for e in extra:
            if e['nro_cliente'] and e['nro_cliente'] not in vistos:
                d = dict(e); d['origen'] = 'registro'; d['online'] = None
                clientes.append(d)
    except Exception:
        pass
    con.close()
    con_senal = sum(1 for c in clientes if c.get('online') == 1)
    return jsonify({
        'olt': o['nombre'], 'pon': pon, 'total': len(clientes),
        'con_senal': con_senal, 'sin_senal': len(clientes) - con_senal,
        'clientes': clientes,
    })

@app.route('/api/olts/<int:oid>/onus')
@requiere_permiso('monitoreo')
def olt_onus(oid):
    """ONU de una OLT con su señal óptica, cruzadas con el cliente."""
    con = get_db()
    filas = con.execute("""
        SELECT s.*, c.nombre AS cliente_nombre, c.id AS cliente_id,
               c.equipo_serie AS equipo_serie
        FROM onu_senal s
        LEFT JOIN clientes c ON c.nro_cliente = s.nro_cliente
        WHERE s.olt_id=?
        ORDER BY s.pon, s.onu
    """, (oid,)).fetchall()
    con.close()
    result = []
    for f in filas:
        d = dict(f)
        d['serial_coincide'] = _serial_match(f['serial_onu'], f['equipo_serie'])
        result.append(d)
    return jsonify(result)

def _norm_serial(s):
    """Normaliza un serial para comparar: solo alfanumérico, mayúsculas."""
    if not s:
        return ''
    return ''.join(ch for ch in str(s).upper() if ch.isalnum())

def _serial_match(reportado, registrado):
    """Devuelve 'ok' si coinciden, 'difiere' si ambos existen y no coinciden,
    'sin_registro' si el cliente no tiene serial cargado, None si no hay dato de ONU."""
    r = _norm_serial(reportado)
    g = _norm_serial(registrado)
    if not r:
        return None
    if not g:
        return 'sin_registro'
    if r == g or r in g or g in r:
        return 'ok'
    return 'difiere'

@app.route('/api/olts/<int:oid>/sondear-onus', methods=['POST'])
@requiere_permiso('monitoreo')
def olt_sondear_onus(oid):
    """Lee la señal óptica de las ONU bajo demanda (puede tardar)."""
    con = get_db()
    o = con.execute("SELECT * FROM olts WHERE id=?", (oid,)).fetchone()
    if not o:
        con.close(); return jsonify({'error': 'OLT no encontrada'}), 404
    try:
        import olt_poller
        # pollear_optica ahora devuelve (n, rx_completa). Sólo se evalúan alertas
        # si la lectura fue COMPLETA (evita marcar ONU no leídas como caídas).
        n, completa = olt_poller.pollear_optica(con, o)
        olt_poller.detectar_alertas_infra(con, {oid} if completa else set())
    except Exception as e:
        con.close(); return jsonify({'error': f'Error al sondear ONUs: {e}'}), 500
    con.close()
    return jsonify({'ok': True, 'onus': n})

@app.route('/api/clientes/<int:cid>/senal')
@login_required
def cliente_senal(cid):
    """Última señal óptica registrada de un cliente (para la ficha)."""
    con = get_db()
    cli = con.execute("SELECT nro_cliente, equipo_serie FROM clientes WHERE id=?", (cid,)).fetchone()
    if not cli or not cli['nro_cliente']:
        con.close(); return jsonify(None)
    s = con.execute("""SELECT s.*, o.nombre AS olt_nombre FROM onu_senal s
                       LEFT JOIN olts o ON o.id=s.olt_id
                       WHERE s.nro_cliente=? ORDER BY s.last_check DESC LIMIT 1""",
                    (cli['nro_cliente'],)).fetchone()
    con.close()
    if not s:
        return jsonify(None)
    d = dict(s)
    d['equipo_serie'] = cli['equipo_serie']
    d['serial_coincide'] = _serial_match(s['serial_onu'], cli['equipo_serie'])
    return jsonify(d)

@app.route('/api/onus/problematicas')
@requiere_permiso('monitoreo')
def onus_problematicas():
    """Clientes con señal óptica baja o crítica (para la sección de alertas)."""
    con = get_db()
    filas = con.execute("""
        SELECT s.*, c.nombre AS cliente_nombre, c.id AS cliente_id,
               c.telefono AS telefono, c.direccion AS direccion, c.localidad AS localidad,
               o.nombre AS olt_nombre
        FROM onu_senal s
        LEFT JOIN clientes c ON c.nro_cliente = s.nro_cliente
        LEFT JOIN olts o ON o.id = s.olt_id
        WHERE s.online=1 AND s.rx_power IS NOT NULL
          AND (s.rx_power < -26 OR s.rx_power > -8)
        ORDER BY s.rx_power ASC
    """).fetchall()
    criticas, bajas, saturadas = [], [], []
    for f in filas:
        d = dict(f)
        if f['rx_power'] > -8:
            saturadas.append(d)          # exceso de luz: también hay que ir
        elif f['rx_power'] < -29:
            criticas.append(d)
        else:
            bajas.append(d)
    con.close()
    return jsonify({
        'criticas': criticas, 'bajas': bajas, 'saturadas': saturadas,
        'total_criticas': len(criticas), 'total_bajas': len(bajas),
        'total_saturadas': len(saturadas),
        'umbrales': {'saturada': -8, 'buena': -23, 'aceptable': -26, 'baja': -29}
    })

@app.route('/api/onus/alertas-count')
@login_required
def onus_alertas_count():
    """Cantidad de ONU con señal crítica (para el banner del dashboard)."""
    con = get_db()
    row = con.execute("""SELECT COUNT(*) c FROM onu_senal
                         WHERE online=1 AND rx_power IS NOT NULL AND rx_power < -29""").fetchone()
    con.close()
    return jsonify({'criticas': row['c']})

@app.route('/api/alertas/nap-pon')
@requiere_permiso('monitoreo')
def alertas_nap_pon():
    """Alertas de infraestructura: NAPs/PONs con todos los clientes caídos."""
    con = get_db()
    if not _table_exists(con, 'alertas_infra'):
        con.close(); return jsonify({'criticas': [], 'bajas': []})
    filas = con.execute("SELECT * FROM alertas_infra WHERE estado='activa' ORDER BY n_afectados DESC, creada DESC").fetchall()
    criticas, bajas = [], []
    for f in filas:
        d = dict(f)
        try:
            d['clientes'] = json.loads(f['clientes_json']) if f['clientes_json'] else []
        except Exception:
            d['clientes'] = []
        (criticas if f['severidad'] == 'sin_senal' else bajas).append(d)
    con.close()
    return jsonify({'criticas': criticas, 'bajas': bajas})

# /api/onus/limpieza se retiró: lo reemplaza /api/v2/pendientes-rescision, que
# además incluye los clientes en 'pte_rescision' y calcula la antigüedad del
# cambio de estado. Mantener las dos habría dejado dos versiones de la misma
# consulta divergiendo con el tiempo. Ver pucara/services/rescisiones.py.

@app.route('/api/clientes/<int:cid>/senal_hist')
@login_required
def cliente_senal_hist(cid):
    """Histórico de señal de un cliente. Sin parámetros: últimas 50 lecturas
    (compat). Con ?horas=N: lecturas de las últimas N horas, envueltas en
    {puntos:[...]} para la pestaña de monitoreo."""
    horas = request.args.get('horas', type=int)
    con = get_db()
    cli = con.execute("SELECT nro_cliente FROM clientes WHERE id=?", (cid,)).fetchone()
    if not cli or not cli['nro_cliente']:
        con.close()
        return jsonify({'puntos': []} if horas else [])
    if horas:
        filas = con.execute("""SELECT rx_power, tx_power, temperatura, fecha FROM onu_senal_hist
                               WHERE nro_cliente=? AND fecha >= datetime('now','localtime',?)
                               ORDER BY fecha ASC""",
                            (cli['nro_cliente'], f'-{int(horas)} hours')).fetchall()
        con.close()
        return jsonify({'puntos': [dict(f) for f in filas]})
    filas = con.execute("""SELECT rx_power, tx_power, temperatura, fecha FROM onu_senal_hist
                           WHERE nro_cliente=? ORDER BY fecha DESC LIMIT 50""",
                        (cli['nro_cliente'],)).fetchall()
    con.close()
    return jsonify([dict(f) for f in reversed(filas)])

# ─── INCIDENCIAS ──────────────────────────────────────────────────
@app.route('/api/incidencias')
@login_required
def get_incidencias():
    estado = request.args.get('estado','')
    tipo = request.args.get('tipo','')
    con = get_db()
    sql = "SELECT * FROM incidencias WHERE 1=1"
    params = []
    if estado:
        sql += " AND estado=?"
        params.append(estado)
    if tipo:
        sql += " AND tipo=?"
        params.append(tipo)
    sql += " ORDER BY CASE estado WHEN 'abierta' THEN 0 ELSE 1 END, CASE prioridad WHEN 'critica' THEN 0 WHEN 'alta' THEN 1 WHEN 'media' THEN 2 ELSE 3 END, fecha_inicio DESC"
    rows = con.execute(sql, params).fetchall()
    con.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/incidencias', methods=['POST'])
@login_required
def crear_incidencia():
    d = request.get_json()
    con = get_db()
    # Para NAPs: guardar IDs y nombres
    nap_id = d.get('nap_id')
    nap_nombre = d.get('nap_nombre','')
    objeto_ids = d.get('objeto_ids')
    if objeto_ids and isinstance(objeto_ids, list):
        # Múltiples NAPs afectados → guardar como JSON y resolver nombres
        nap_nombres = []
        for nid in objeto_ids:
            n = con.execute("SELECT nombre FROM naps WHERE id=?", (nid,)).fetchone()
            if n:
                nap_nombres.append(n['nombre'])
        nap_nombre = ', '.join(nap_nombres)
        nap_id = objeto_ids[0] if objeto_ids else None
        objeto_ids_json = json.dumps(objeto_ids)
    else:
        objeto_ids_json = None

    cur = con.execute("""INSERT INTO incidencias(titulo,tipo,descripcion,afectados,
                         estado,prioridad,tecnico,lat,lng,creado_por,
                         torre_id,nap_id,nap_nombre,objeto_tipo,red,olt_nombre,cdo,objeto_ids)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (d['titulo'],d['tipo'],d.get('descripcion',''),
                       d.get('afectados',''),d.get('estado','abierta'),
                       d.get('prioridad','media'),d.get('tecnico',''),
                       d.get('lat'),d.get('lng'),session.get('username'),
                       d.get('torre_id'),nap_id,nap_nombre,
                       d.get('objeto_tipo'),d.get('red'),d.get('olt_nombre'),
                       d.get('cdo'),objeto_ids_json))
    con.commit(); con.close()
    notif('incidencia', f"Nueva incidencia: {d['titulo']}", d.get('descripcion',''))
    # Alerta Telegram automática por incidencia nueva
    try:
        pr = d.get('prioridad','media')
        icono = '🔴' if pr in ('alta','urgente','critica') else '🟡'
        afect = f"\n👥 Afecta: {d.get('afectados')}" if d.get('afectados') else ''
        enviar_telegram(f"{icono} <b>Nueva incidencia</b>\n📌 {d['titulo']} ({pr})\n{d.get('descripcion','')[:200]}{afect}\n— por {session.get('username')}")
    except Exception:
        pass
    return jsonify({'ok':True,'id':cur.lastrowid})

@app.route('/api/incidencias/<int:iid>', methods=['PUT'])
@login_required
def actualizar_incidencia(iid):
    d = request.get_json()
    fc = d.get('fecha_cierre')
    if d.get('estado') == 'cerrada' and not fc:
        fc = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    con = get_db()
    # Para NAPs: resolver nombres
    objeto_ids = d.get('objeto_ids')
    nap_id = d.get('nap_id')
    nap_nombre = d.get('nap_nombre','')
    if objeto_ids and isinstance(objeto_ids, list):
        nap_nombres = []
        for nid in objeto_ids:
            n = con.execute("SELECT nombre FROM naps WHERE id=?", (nid,)).fetchone()
            if n:
                nap_nombres.append(n['nombre'])
        nap_nombre = ', '.join(nap_nombres)
        nap_id = objeto_ids[0] if objeto_ids else None
        objeto_ids_json = json.dumps(objeto_ids)
    else:
        objeto_ids_json = d.get('objeto_ids')

    con.execute("""UPDATE incidencias SET titulo=?,tipo=?,descripcion=?,afectados=?,
                   estado=?,prioridad=?,tecnico=?,lat=?,lng=?,fecha_cierre=?,resolucion=?,
                   torre_id=?,nap_id=?,nap_nombre=?,objeto_tipo=?,red=?,olt_nombre=?,cdo=?,objeto_ids=? WHERE id=?""",
                (d['titulo'],d['tipo'],d.get('descripcion',''),d.get('afectados',''),
                 d.get('estado','abierta'),d.get('prioridad','media'),d.get('tecnico',''),
                 d.get('lat'),d.get('lng'),fc,d.get('resolucion',''),
                 d.get('torre_id'),nap_id,nap_nombre,
                 d.get('objeto_tipo'),d.get('red'),d.get('olt_nombre'),
                 d.get('cdo'),objeto_ids_json,iid))
    con.commit(); con.close()
    return jsonify({'ok':True})

@app.route('/api/incidencias/<int:iid>', methods=['DELETE'])
@login_required
def borrar_incidencia(iid):
    con = get_db()
    con.execute("DELETE FROM incidencias WHERE id=?", (iid,))
    con.commit(); con.close()
    return jsonify({'ok':True})

# ─── STOCK ────────────────────────────────────────────────────────
# ═══ STOCK COMPLETO (importado de v6.2) ═══

# ── Inventario por cantidad (panel simple combinado) ──
@app.route('/api/stock/inventario')
@login_required
def stock_inventario_panel():
    """Panel de inventario: ítems manuales (cantidad cargada a mano) +
    ítems automáticos (conteo del stock por serie en depósito).
    Agrupado por categoría: inalambrico, fibra, varios."""
    con = get_db()
    rows = con.execute("SELECT * FROM stock_inventario ORDER BY categoria, orden, nombre").fetchall()
    result = []
    for r in rows:
        d = dict(r)
        if d['origen'] == 'auto':
            # Contar del stock por serie en depósito
            sql = "SELECT COUNT(*) FROM stock_items WHERE estado='deposito'"
            params = []
            if d.get('serie_marca'):
                sql += " AND UPPER(TRIM(marca))=UPPER(?)"; params.append(d['serie_marca'])
            if d.get('serie_tipo'):
                sql += " AND UPPER(TRIM(tipo))=UPPER(?)"; params.append(d['serie_tipo'])
            d['cantidad'] = con.execute(sql, params).fetchone()[0]
        result.append(d)
    con.close()
    # Agrupar por categoría
    cats = {'inalambrico': [], 'fibra': [], 'varios': []}
    for d in result:
        cat = d.get('categoria','varios')
        if cat not in cats: cats[cat] = []
        cats[cat].append(d)
    return jsonify(cats)

@app.route('/api/stock/inventario', methods=['POST'])
@login_required
@admin_required
def stock_inventario_crear():
    d = request.get_json() or {}
    if not d.get('nombre'):
        return jsonify({'error':'nombre requerido'}), 400
    con = get_db()
    cur = con.execute("""INSERT INTO stock_inventario
        (nombre, categoria, cantidad, unidad, origen, serie_marca, serie_tipo, orden)
        VALUES(?,?,?,?,?,?,?,?)""",
        (d['nombre'], d.get('categoria','varios'), d.get('cantidad',0), d.get('unidad','u'),
         d.get('origen','manual'), d.get('serie_marca'), d.get('serie_tipo'), d.get('orden',0)))
    con.commit(); con.close()
    return jsonify({'ok':True, 'id':cur.lastrowid})

@app.route('/api/stock/inventario/<int:iid>', methods=['PUT','DELETE'])
@login_required
@admin_required
def stock_inventario_editar(iid):
    con = get_db()
    if request.method == 'DELETE':
        con.execute("DELETE FROM stock_inventario WHERE id=?", (iid,))
    else:
        d = request.get_json() or {}
        # Edición rápida: solo cantidad, o ítem completo
        if set(d.keys()) <= {'cantidad'}:
            con.execute("UPDATE stock_inventario SET cantidad=? WHERE id=?", (d.get('cantidad',0), iid))
        else:
            con.execute("""UPDATE stock_inventario
                SET nombre=?, categoria=?, cantidad=?, unidad=?, origen=?, serie_marca=?, serie_tipo=?, orden=?
                WHERE id=?""",
                (d.get('nombre'), d.get('categoria','varios'), d.get('cantidad',0), d.get('unidad','u'),
                 d.get('origen','manual'), d.get('serie_marca'), d.get('serie_tipo'), d.get('orden',0), iid))
    con.commit(); con.close()
    return jsonify({'ok':True})

@app.route('/api/stock/resumen')
@login_required
def stock_resumen():
    """Dashboard de stock: conteos por estado, marca, tipo."""
    con = get_db()
    # Equipos en stock_items
    items_estado = con.execute("SELECT estado, COUNT(*) as c FROM stock_items GROUP BY estado ORDER BY c DESC").fetchall()
    items_por_marca = con.execute("SELECT marca, COUNT(*) as c FROM stock_items WHERE estado='deposito' GROUP BY marca ORDER BY c DESC").fetchall()
    items_por_tipo = con.execute("SELECT tipo, COUNT(*) as c FROM stock_items WHERE estado='deposito' GROUP BY tipo ORDER BY c DESC").fetchall()
    # Derivado de clientes (equipos instalados sin trackear en stock_items)
    instalados_total = con.execute("SELECT COUNT(*) FROM clientes WHERE estado NOT IN ('baja','rescision') AND equipo_serie IS NOT NULL AND equipo_serie != ''").fetchone()[0]
    instalados_trackeados = con.execute("SELECT COUNT(*) FROM stock_items WHERE estado='instalado'").fetchone()[0]
    # Pendientes de retiro (rescindidos/pte_rescision con equipo)
    pend_retiro = con.execute("""SELECT COUNT(*) FROM clientes
        WHERE estado IN ('rescision','pte_rescision')
        AND equipo_serie IS NOT NULL AND equipo_serie != ''""").fetchone()[0]
    # Alertas: modelos con stock bajo (menos de 3 en depósito)
    stock_bajo = con.execute("""SELECT modelo, marca, COUNT(*) as en_deposito
        FROM stock_items WHERE estado='deposito'
        GROUP BY modelo, marca HAVING en_deposito < 3
        ORDER BY en_deposito ASC""").fetchall()
    con.close()
    return jsonify({
        'por_estado': {r['estado']:r['c'] for r in items_estado},
        'por_marca': [{'marca':r['marca'],'cantidad':r['c']} for r in items_por_marca],
        'por_tipo': [{'tipo':r['tipo'],'cantidad':r['c']} for r in items_por_tipo],
        'instalados_total': instalados_total,
        'instalados_trackeados': instalados_trackeados,
        'pendientes_retiro': pend_retiro,
        'stock_bajo': [dict(r) for r in stock_bajo],
    })

@app.route('/api/stock/items')
@login_required
def get_stock_items():
    """Lista de equipos individuales con filtros."""
    estado = request.args.get('estado','')
    marca = request.args.get('marca','')
    tipo = request.args.get('tipo','')
    q = request.args.get('q','')
    con = get_db()
    sql = "SELECT * FROM stock_items WHERE 1=1"
    params = []
    if estado:
        sql += " AND estado=?"
        params.append(estado)
    if marca:
        sql += " AND marca=?"
        params.append(marca)
    if tipo:
        sql += " AND tipo=?"
        params.append(tipo)
    if q:
        sql += " AND (serie LIKE ? OR mac LIKE ? OR modelo LIKE ? OR cliente_nombre LIKE ?)"
        params += [f'%{q}%']*4
    sql += " ORDER BY CASE estado WHEN 'deposito' THEN 0 WHEN 'instalado' THEN 1 WHEN 'pend_retiro' THEN 2 ELSE 3 END, fecha_ingreso DESC"
    sql += " LIMIT 200"
    rows = con.execute(sql, params).fetchall()
    con.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/stock/items', methods=['POST'])
@login_required
def crear_stock_item():
    """Ingresar equipo(s) al depósito."""
    d = request.get_json()
    con = get_db()
    serie = (d.get('serie','') or '').strip()
    # Verificar duplicado por serie
    if serie:
        dup = con.execute("SELECT id, estado, cliente_nombre FROM stock_items WHERE serie=?", (serie,)).fetchone()
        if dup:
            con.close()
            return jsonify({'error': f'Serie {serie} ya existe (estado: {dup["estado"]}, cliente: {dup["cliente_nombre"] or "—"})'}), 400
    cur = con.execute("""INSERT INTO stock_items(serie,mac,modelo,marca,tipo,estado,ubicacion,observaciones,creado_por)
                         VALUES(?,?,?,?,?,'deposito',?,?,?)""",
                (serie, d.get('mac',''), d.get('modelo',''), d.get('marca',''),
                 d.get('tipo',''), d.get('ubicacion','Depósito central'),
                 d.get('observaciones',''), session.get('username')))
    item_id = cur.lastrowid
    # Registrar movimiento
    con.execute("INSERT INTO stock_movimientos(item_id,tipo,descripcion,usuario) VALUES(?,'ingreso',?,?)",
                (item_id, f"Ingreso: {d.get('marca','')} {d.get('modelo','')} S/N:{serie}", session.get('username')))
    con.commit(); con.close()
    log('alta', f'Stock ingreso: {d.get("marca","")} {d.get("modelo","")} S/N:{serie}', '', 'stock')
    return jsonify({'ok':True, 'id':item_id})

@app.route('/api/stock/items/lote', methods=['POST'])
@login_required
def crear_stock_lote():
    """Ingresar múltiples equipos al depósito."""
    d = request.get_json()
    items = d.get('items', [])
    con = get_db()
    creados = 0
    errores = []
    for item in items:
        serie = (item.get('serie','') or '').strip()
        if serie:
            dup = con.execute("SELECT id FROM stock_items WHERE serie=?", (serie,)).fetchone()
            if dup:
                errores.append(f"Serie {serie} duplicada")
                continue
        cur = con.execute("""INSERT INTO stock_items(serie,mac,modelo,marca,tipo,estado,ubicacion,creado_por)
                             VALUES(?,?,?,?,?,'deposito',?,?)""",
                    (serie, item.get('mac',''), item.get('modelo',d.get('modelo','')),
                     item.get('marca',d.get('marca','')), item.get('tipo',d.get('tipo','')),
                     d.get('ubicacion','Depósito central'), session.get('username')))
        con.execute("INSERT INTO stock_movimientos(item_id,tipo,descripcion,usuario) VALUES(?,'ingreso',?,?)",
                    (cur.lastrowid, f"Ingreso lote: S/N:{serie}", session.get('username')))
        creados += 1
    con.commit(); con.close()
    return jsonify({'ok':True, 'creados':creados, 'errores':errores})

@app.route('/api/stock/items/<int:iid>/asignar', methods=['POST'])
@login_required
def asignar_stock_item(iid):
    """Asignar equipo a un cliente."""
    d = request.get_json()
    cliente_id = d.get('cliente_id')
    con = get_db()
    item = con.execute("SELECT * FROM stock_items WHERE id=?", (iid,)).fetchone()
    if not item:
        con.close(); return jsonify({'error':'Item no encontrado'}), 404
    if item['estado'] != 'deposito':
        con.close(); return jsonify({'error':f'Item no está en depósito (estado: {item["estado"]})'}), 400
    # Buscar cliente
    cli = con.execute("SELECT id, nombre, nro_cliente FROM clientes WHERE id=?", (cliente_id,)).fetchone()
    if not cli:
        con.close(); return jsonify({'error':'Cliente no encontrado'}), 404
    # Asignar
    con.execute("""UPDATE stock_items SET estado='instalado', cliente_id=?, cliente_nombre=?,
                   nro_cliente=?, fecha_asignacion=datetime('now','localtime') WHERE id=?""",
                (cli['id'], cli['nombre'], cli['nro_cliente'], iid))
    # Actualizar equipo en cliente
    if item['serie']:
        con.execute("UPDATE clientes SET equipo_serie=?, equipo_marca=?, equipo_modelo=?, mac_address=? WHERE id=?",
                    (item['serie'], item['marca'], item['modelo'], item['mac'], cli['id']))
    # Movimiento
    con.execute("INSERT INTO stock_movimientos(item_id,tipo,descripcion,cliente_id,cliente_nombre,usuario) VALUES(?,'asignacion',?,?,?,?)",
                (iid, f"Asignado a {cli['nombre']} ({cli['nro_cliente']})", cli['id'], cli['nombre'], session.get('username')))
    con.commit(); con.close()
    log('mod', f'Stock asignado: S/N:{item["serie"]} → {cli["nombre"]}', '', 'stock')
    return jsonify({'ok':True})

@app.route('/api/stock/items/<int:iid>/retirar', methods=['POST'])
@login_required
def retirar_stock_item(iid):
    """Retirar equipo de un cliente (vuelta a depósito)."""
    d = request.get_json() or {}
    con = get_db()
    item = con.execute("SELECT * FROM stock_items WHERE id=?", (iid,)).fetchone()
    if not item:
        con.close(); return jsonify({'error':'Item no encontrado'}), 404
    cli_nombre = item['cliente_nombre'] or ''
    # Limpiar equipo del cliente
    if item['cliente_id']:
        con.execute("UPDATE clientes SET equipo_serie=NULL, equipo_marca=NULL, equipo_modelo=NULL, mac_address=NULL WHERE id=?",
                    (item['cliente_id'],))
    # Volver a depósito
    con.execute("""UPDATE stock_items SET estado='deposito', cliente_id=NULL, cliente_nombre=NULL,
                   nro_cliente=NULL, fecha_retiro=datetime('now','localtime'),
                   ubicacion=? WHERE id=?""",
                (d.get('ubicacion','Depósito central'), iid))
    con.execute("INSERT INTO stock_movimientos(item_id,tipo,descripcion,cliente_id,cliente_nombre,usuario) VALUES(?,'retiro',?,?,?,?)",
                (iid, f"Retirado de {cli_nombre}: {d.get('motivo','')}", item['cliente_id'], cli_nombre, session.get('username')))
    con.commit(); con.close()
    log('mod', f'Stock retirado: S/N:{item["serie"]} de {cli_nombre}', '', 'stock')
    return jsonify({'ok':True})

@app.route('/api/stock/items/<int:iid>/baja', methods=['POST'])
@login_required
def baja_stock_item(iid):
    """Dar de baja un equipo (descarte, robo, daño)."""
    d = request.get_json() or {}
    con = get_db()
    item = con.execute("SELECT * FROM stock_items WHERE id=?", (iid,)).fetchone()
    if not item:
        con.close(); return jsonify({'error':'Item no encontrado'}), 404
    con.execute("""UPDATE stock_items SET estado='baja', fecha_baja=datetime('now','localtime'),
                   motivo_baja=? WHERE id=?""", (d.get('motivo',''), iid))
    con.execute("INSERT INTO stock_movimientos(item_id,tipo,descripcion,usuario) VALUES(?,'baja',?,?)",
                (iid, f"Baja: {d.get('motivo','Sin motivo')}", session.get('username')))
    con.commit(); con.close()
    log('baja', f'Stock baja: S/N:{item["serie"]} - {d.get("motivo","")}', '', 'stock')
    return jsonify({'ok':True})

@app.route('/api/stock/items/<int:iid>', methods=['PUT'])
@login_required
def editar_stock_item(iid):
    """Editar datos de un equipo."""
    d = request.get_json()
    con = get_db()
    con.execute("""UPDATE stock_items SET serie=?,mac=?,modelo=?,marca=?,tipo=?,
                   ubicacion=?,observaciones=? WHERE id=?""",
                (d.get('serie',''), d.get('mac',''), d.get('modelo',''), d.get('marca',''),
                 d.get('tipo',''), d.get('ubicacion',''), d.get('observaciones',''), iid))
    con.commit(); con.close()
    return jsonify({'ok':True})

@app.route('/api/stock/movimientos')
@login_required
def get_stock_movimientos():
    """Historial de movimientos de stock."""
    item_id = request.args.get('item_id','')
    limit = int(request.args.get('limit', 50))
    con = get_db()
    if item_id:
        rows = con.execute("""SELECT m.*, i.serie, i.modelo, i.marca
            FROM stock_movimientos m LEFT JOIN stock_items i ON i.id = m.item_id
            WHERE m.item_id=? ORDER BY m.fecha DESC LIMIT ?""", (int(item_id), limit)).fetchall()
    else:
        rows = con.execute("""SELECT m.*, i.serie, i.modelo, i.marca
            FROM stock_movimientos m LEFT JOIN stock_items i ON i.id = m.item_id
            ORDER BY m.fecha DESC LIMIT ?""", (limit,)).fetchall()
    con.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/stock/pendientes_retiro')
@login_required
def stock_pendientes_retiro():
    """Equipos en clientes rescindidos, pendientes de retirar."""
    con = get_db()
    rows = con.execute("""SELECT id, nombre, nro_cliente, telefono, direccion, localidad,
        equipo_modelo, equipo_marca, equipo_serie, mac_address, estado,
        lat, lng, tipo_servicio
        FROM clientes
        WHERE estado IN ('rescision','pte_rescision')
        AND equipo_serie IS NOT NULL AND equipo_serie != ''
        ORDER BY estado, localidad, nombre""").fetchall()
    con.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/stock/importar_desde_clientes', methods=['POST'])
@login_required
@admin_required
def stock_importar_clientes():
    """Importa equipos instalados desde clientes a stock_items (una sola vez)."""
    con = get_db()
    clientes = con.execute("""SELECT id, nombre, nro_cliente, equipo_modelo, equipo_marca,
        equipo_serie, mac_address, tipo_servicio
        FROM clientes
        WHERE equipo_serie IS NOT NULL AND equipo_serie != ''
        AND estado NOT IN ('baja')""").fetchall()
    importados = 0
    saltados = 0
    for c in clientes:
        # Verificar si ya existe
        existe = con.execute("SELECT id FROM stock_items WHERE serie=?", (c['equipo_serie'],)).fetchone()
        if existe:
            saltados += 1
            continue
        estado_item = 'instalado' if c['nro_cliente'] else 'deposito'
        if not c['nro_cliente']:
            estado_item = 'deposito'
        con.execute("""INSERT INTO stock_items(serie,mac,modelo,marca,tipo,estado,cliente_id,
                       cliente_nombre,nro_cliente,fecha_ingreso,creado_por)
                       VALUES(?,?,?,?,?,?,?,?,?,datetime('now','localtime'),'importacion')""",
                    (c['equipo_serie'], c['mac_address'], c['equipo_modelo'], c['equipo_marca'],
                     c['tipo_servicio'], estado_item, c['id'], c['nombre'], c['nro_cliente']))
        importados += 1
    con.commit(); con.close()
    log('alta', f'Stock importado desde clientes: {importados} equipos', '', 'stock')
    return jsonify({'ok':True, 'importados':importados, 'saltados':saltados})


@app.route('/api/stock')
@login_required
def get_stock():
    con = get_db()
    # Stock manual
    stock_manual = con.execute("SELECT * FROM stock WHERE activo=1 ORDER BY tipo, marca, modelo").fetchall()
    # Stock derivado de clientes instalados
    stock_instalado = con.execute("""
        SELECT
            COALESCE(equipo_modelo,'Sin modelo') as modelo,
            COALESCE(equipo_marca,'Sin marca') as marca,
            tipo_servicio as tipo,
            COUNT(*) as cantidad,
            GROUP_CONCAT(DISTINCT localidad) as localidades
        FROM clientes
        WHERE estado!='baja' AND equipo_modelo IS NOT NULL AND equipo_modelo!=''
        GROUP BY equipo_modelo, equipo_marca, tipo_servicio
        ORDER BY tipo_servicio, equipo_marca, equipo_modelo
    """).fetchall()
    con.close()
    return jsonify({
        'manual': [dict(s) for s in stock_manual],
        'instalado': [dict(s) for s in stock_instalado]
    })

@app.route('/api/stock', methods=['POST'])
@login_required
def crear_stock():
    d = request.get_json()
    con = get_db()
    con.execute("INSERT INTO stock(modelo,marca,tipo,cantidad,descripcion) VALUES(?,?,?,?,?)",
                (d['modelo'],d.get('marca',''),d.get('tipo',''),d.get('cantidad',0),d.get('descripcion','')))
    con.commit(); con.close()
    return jsonify({'ok':True})

@app.route('/api/stock/<int:sid>', methods=['PUT'])
@login_required
def actualizar_stock(sid):
    d = request.get_json()
    con = get_db()
    con.execute("UPDATE stock SET modelo=?,marca=?,tipo=?,cantidad=?,descripcion=? WHERE id=?",
                (d['modelo'],d.get('marca',''),d.get('tipo',''),d.get('cantidad',0),d.get('descripcion',''),sid))
    con.commit(); con.close()
    return jsonify({'ok':True})

# ─── BAJAS ────────────────────────────────────────────────────────
@app.route('/api/bajas')
@login_required
def get_bajas():
    localidad = request.args.get('localidad','')
    tipo = request.args.get('tipo','')
    orden = request.args.get('orden','fecha')  # fecha, localidad, nombre

    sql = """SELECT id,nombre,dni,telefono,email,direccion,localidad,tipo_servicio,
             plan,equipo_modelo,equipo_marca,equipo_serie,nap,
             fecha_rescision,fecha_baja,estado,observaciones
             FROM clientes WHERE estado IN ('rescision','baja')"""
    params = []
    if localidad:
        sql += " AND localidad=?"
        params.append(localidad)
    if tipo:
        sql += " AND tipo_servicio=?"
        params.append(tipo)

    orden_map = {'fecha':'fecha_rescision DESC','localidad':'localidad,nombre','nombre':'nombre'}
    sql += f" ORDER BY {orden_map.get(orden,'fecha_rescision DESC')}"

    con = get_db()
    rows = con.execute(sql, params).fetchall()
    today = date.today().isoformat()
    result = []
    for r in rows:
        d = dict(r)
        if d.get('fecha_rescision'):
            try:
                dias = (date.today() - date.fromisoformat(d['fecha_rescision'])).days
                d['dias_pendiente'] = dias
            except: d['dias_pendiente'] = 0
        else:
            d['dias_pendiente'] = 0
        result.append(d)
    con.close()
    return jsonify(result)

@app.route('/api/bajas/export')
@login_required
@admin_required
def export_bajas():
    # Exportación masiva de PII (DNI, email, teléfono, dirección) de clientes
    # dados de baja: mismo criterio que /api/clientes/exportar (solo admin/root).
    localidad = request.args.get('localidad','')
    tipo = request.args.get('tipo','')
    sql = """SELECT nombre,dni,telefono,email,direccion,localidad,tipo_servicio,
             plan,equipo_modelo,equipo_marca,equipo_serie,nap,
             fecha_rescision,fecha_baja,estado,observaciones
             FROM clientes WHERE estado IN ('rescision','baja')"""
    params = []
    if localidad:
        sql += " AND localidad=?"
        params.append(localidad)
    if tipo:
        sql += " AND tipo_servicio=?"
        params.append(tipo)
    sql += " ORDER BY fecha_rescision DESC"

    con = get_db()
    rows = con.execute(sql, params).fetchall()
    con.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Nombre','DNI','Teléfono','Email','Dirección','Localidad','Tipo',
                     'Plan','Equipo Modelo','Marca','Serie','NAP','F.Rescisión','Estado','Observaciones'])
    for r in rows:
        writer.writerow([r['nombre'],r['dni'],r['telefono'],r['email'],
                         r['direccion'],r['localidad'],r['tipo_servicio'],
                         r['plan'],r['equipo_modelo'],r['equipo_marca'],r['equipo_serie'],
                         r['nap'],r['fecha_rescision'],r['estado'],r['observaciones']])

    output.seek(0)
    return send_file(io.BytesIO(output.getvalue().encode('utf-8-sig')),
                     mimetype='text/csv',
                     as_attachment=True,
                     download_name=f'bajas_{date.today().isoformat()}.csv')

# ─── PAGOS ────────────────────────────────────────────────────────
@app.route('/api/pagos', methods=['POST'])
@login_required
def registrar_pago():
    d = request.get_json()
    con = get_db()
    con.execute("INSERT INTO pagos(cliente_id,monto,fecha,medio,referencia,observaciones,registrado_por) VALUES(?,?,?,?,?,?,?)",
                (d['cliente_id'],d['monto'],d.get('fecha',date.today().isoformat()),
                 d.get('medio','efectivo'),d.get('referencia',''),d.get('observaciones',''),
                 session.get('username')))
    con.execute("UPDATE clientes SET ultimo_pago=? WHERE id=?",
                (d.get('fecha',date.today().isoformat()), d['cliente_id']))
    con.commit(); con.close()
    return jsonify({'ok':True})

# ─── HISTORIAL ────────────────────────────────────────────────────
@app.route('/api/historial')
@login_required
def get_historial():
    page = int(request.args.get('page',1))
    rows = get_db().execute("SELECT * FROM historial ORDER BY fecha DESC LIMIT 100 OFFSET ?",
                            ((page-1)*100,)).fetchall()
    return jsonify([dict(r) for r in rows])

# ─── USUARIOS ─────────────────────────────────────────────────────
@app.route('/api/usuarios')
@login_required
@admin_required
def get_usuarios():
    rows = get_db().execute("SELECT id,username,nombre,rol,activo,creado,permisos,puede_editar_guardias FROM usuarios ORDER BY nombre").fetchall()
    result = []
    for r in rows:
        d = dict(r)
        # Parsear permisos JSON
        perm_raw = d.pop('permisos', None) or '{}'
        if perm_raw == 'root' or perm_raw == '*':
            d['permisos'] = 'root'
            d['permisos_obj'] = {'modulos': '*', 'acciones': '*'}
        else:
            try:
                d['permisos_obj'] = json.loads(perm_raw)
            except:
                d['permisos_obj'] = {}
            d['permisos'] = perm_raw
        result.append(d)
    return jsonify(result)

@app.route('/api/usuarios', methods=['POST'])
@login_required
@admin_required
def crear_usuario():
    d = request.get_json()
    con = get_db()
    con.execute("INSERT INTO usuarios(username,nombre,password,rol,puede_editar_guardias) VALUES(?,?,?,?,?)",
                (d['username'],d['nombre'],generate_password_hash(d['password']),d.get('rol','operador'),
                 int(d.get('puede_editar_guardias',0))))
    con.commit(); con.close()
    return jsonify({'ok':True})

@app.route('/api/usuarios/<int:uid>', methods=['PUT'])
@login_required
@admin_required
def actualizar_usuario(uid):
    d = request.get_json()
    con = get_db()
    peg = int(d.get('puede_editar_guardias',0))
    if d.get('password'):
        con.execute("UPDATE usuarios SET nombre=?,rol=?,activo=?,puede_editar_guardias=?,password=? WHERE id=?",
                    (d['nombre'],d['rol'],d.get('activo',1),peg,generate_password_hash(d['password']),uid))
    else:
        con.execute("UPDATE usuarios SET nombre=?,rol=?,activo=?,puede_editar_guardias=? WHERE id=?",
                    (d['nombre'],d['rol'],d.get('activo',1),peg,uid))
    con.commit(); con.close()
    return jsonify({'ok':True})

@app.route('/api/usuarios/<int:uid>/permisos')
@login_required
@admin_required
def get_usuario_permisos(uid):
    con = get_db()
    row = con.execute("SELECT id, username, nombre, rol, activo, permisos FROM usuarios WHERE id=?", (uid,)).fetchone()
    con.close()
    if not row:
        return jsonify({'error': 'Usuario no encontrado'}), 404
    perm_raw = row['permisos'] or '{}'
    if perm_raw in ('root', '*'):
        permisos = {'modulos': '*', 'acciones': '*'}
    else:
        try:
            permisos = json.loads(perm_raw)
        except:
            permisos = {}
    return jsonify({
        'id': row['id'], 'username': row['username'],
        'nombre': row['nombre'], 'rol': row['rol'],
        'activo': row['activo'], 'permisos': permisos
    })

@app.route('/api/usuarios/<int:uid>/permisos', methods=['PUT'])
@login_required
@admin_required
def set_usuario_permisos(uid):
    d = request.get_json()
    permisos = d.get('permisos', {})
    perm_json = json.dumps(permisos, ensure_ascii=False)
    con = get_db()
    con.execute("UPDATE usuarios SET permisos=? WHERE id=?", (perm_json, uid))
    con.commit(); con.close()
    log('mod', f'Permisos actualizados para usuario #{uid}', perm_json[:200], 'usuarios')
    return jsonify({'ok': True})

# ─── EMPRESA ──────────────────────────────────────────────────────
@app.route('/api/empresa')
@login_required
def get_empresa():
    con = get_db()
    e = con.execute("SELECT * FROM empresa WHERE id=1").fetchone()
    con.close()
    return jsonify(dict(e) if e else {})

@app.route('/api/empresa', methods=['PUT'])
@login_required
@admin_required
def update_empresa():
    d = request.get_json()
    con = get_db()
    con.execute("""UPDATE empresa SET razon_social=?,nombre_fantasia=?,cuit=?,
                   punto_venta=?,direccion=?,telefono=?,email=? WHERE id=1""",
                (d.get('razon_social'),d.get('nombre_fantasia'),d.get('cuit'),
                 d.get('punto_venta',1),d.get('direccion'),d.get('telefono'),d.get('email')))
    con.commit(); con.close()
    return jsonify({'ok':True})

# ─── LOCALIDADES (para filtros) ────────────────────────────────────
@app.route('/api/localidades')
@login_required
def get_localidades():
    con = get_db()
    rows = con.execute("SELECT DISTINCT localidad FROM clientes WHERE localidad IS NOT NULL AND localidad!='' ORDER BY localidad").fetchall()
    con.close()
    return jsonify([r[0] for r in rows])

@app.route('/api/tecnicos')
@login_required
def get_tecnicos():
    con = get_db()
    rows = con.execute("SELECT DISTINCT tecnico FROM servicios WHERE tecnico IS NOT NULL AND tecnico!='' ORDER BY tecnico").fetchall()
    con.close()
    return jsonify([r[0] for r in rows])

# ─── ENDPOINTS ADICIONALES (requeridos por el frontend) ──────────
@app.route('/api/usuarios/agentes')
@login_required
def usuarios_agentes():
    con = get_db()
    rows = con.execute("SELECT id, nombre, username FROM usuarios WHERE rol IN ('admin','tecnico','agente') ORDER BY nombre").fetchall()
    con.close()
    return jsonify([{'id':r['id'],'nombre':r['nombre'],'usuario':r['username']} for r in rows])

@app.route('/api/me/permisos')
@login_required
def me_permisos():
    con = get_db()
    row = con.execute("SELECT permisos, rol FROM usuarios WHERE id=?", (session.get('user_id'),)).fetchone()
    con.close()
    if not row:
        return jsonify({'all': False, 'permisos': {}})
    perm_raw = row['permisos'] or '{}'
    if row['rol'] in ('admin', 'root') or perm_raw in ('root', '*'):
        return jsonify({'all': True, 'permisos': {'modulos': '*', 'acciones': '*', 'flags': []}})
    try:
        permisos = json.loads(perm_raw)
    except Exception:
        permisos = {}
    permisos.setdefault('modulos', [])
    permisos.setdefault('acciones', [])
    permisos.setdefault('flags', [])
    return jsonify({'all': False, 'permisos': permisos})

@app.route('/api/redes')
@login_required
def get_redes():
    con = get_db()
    rows = con.execute("SELECT * FROM redes ORDER BY nombre").fetchall()
    con.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/redes', methods=['POST'])
@login_required
def crear_red():
    d = request.get_json()
    con = get_db()
    try:
        con.execute("INSERT INTO redes(nombre,descripcion) VALUES(?,?)",
                    (d['nombre'].strip(), d.get('descripcion','')))
        con.commit()
    except Exception as e:
        con.close()
        return jsonify({'error': str(e)}), 400
    con.close()
    return jsonify({'ok':True})

@app.route('/api/redes/<int:rid>', methods=['PUT'])
@login_required
def editar_red(rid):
    d = request.get_json()
    con = get_db()
    con.execute("UPDATE redes SET nombre=?,descripcion=?,estado=? WHERE id=?",
                (d['nombre'].strip(), d.get('descripcion',''), d.get('estado','activa'), rid))
    con.commit(); con.close()
    return jsonify({'ok':True})

@app.route('/api/redes/<int:rid>', methods=['DELETE'])
@login_required
@admin_required
def borrar_red(rid):
    con = get_db()
    con.execute("DELETE FROM redes WHERE id=?", (rid,))
    con.commit(); con.close()
    return jsonify({'ok':True})

@app.route('/api/torres/mapa_red')
@login_required
def torres_mapa_red():
    con = get_db()
    torres = con.execute("SELECT * FROM torres WHERE lat IS NOT NULL AND lng IS NOT NULL").fetchall()
    torres_dict = {t['id']: dict(t) for t in torres}

    # Monitoreo: estado de ping por IP
    mon_status = {}
    try:
        for m in con.execute("SELECT nombre, ip, estado FROM monitoreo WHERE activo=1").fetchall():
            mon_status[m['ip']] = m['estado']
    except:
        pass

    # Contar hijos por torre
    hijos_count = {}
    for t in torres_dict.values():
        pid = t.get('torre_padre_id')
        if pid:
            hijos_count[pid] = hijos_count.get(pid, 0) + 1

    # Incidencias activas por torre
    inc_por_torre = {}
    try:
        incs = con.execute("SELECT * FROM incidencias WHERE estado IN ('abierta','en_proceso') AND torre_id IS NOT NULL").fetchall()
        for i in incs:
            tid = i['torre_id']
            if tid not in inc_por_torre:
                inc_por_torre[tid] = []
            inc_por_torre[tid].append({'titulo': i['titulo'], 'estado': i['estado']})
    except:
        pass

    # Cascada: si una torre tiene incidencia, TODOS sus descendientes están afectados
    # Construir set de torres afectadas (incidencia propia o en cualquier ancestro)
    torres_afectadas = set()
    def _marcar_descendientes(tid):
        for t2 in torres_dict.values():
            if t2.get('torre_padre_id') == tid and t2['id'] not in torres_afectadas:
                torres_afectadas.add(t2['id'])
                _marcar_descendientes(t2['id'])
    for tid in inc_por_torre:
        torres_afectadas.add(tid)
        _marcar_descendientes(tid)
    # También marcar si la torre está inactiva o en mantenimiento (no si está dada de baja)
    for t in torres_dict.values():
        if t.get('estado') in ('inactiva', 'mantenimiento'):
            torres_afectadas.add(t['id'])
            _marcar_descendientes(t['id'])

    # Construir resultado enriquecido
    result = []
    for t in torres_dict.values():
        d = dict(t)
        d['hijos'] = hijos_count.get(t['id'], 0)
        # Mon estado
        ip = (t.get('ip_equipos') or '').split(',')[0].strip()
        d['mon_estado'] = mon_status.get(ip, 'desconocido')
        # Coords del padre
        pid = t.get('torre_padre_id')
        if pid and pid in torres_dict:
            d['padre_lat'] = torres_dict[pid]['lat']
            d['padre_lng'] = torres_dict[pid]['lng']
        else:
            d['padre_lat'] = None
            d['padre_lng'] = None
        # Incidencias
        d['incidencias'] = inc_por_torre.get(t['id'], [])
        d['incidencia_activa'] = len(d['incidencias']) > 0
        d['afectada_por_incidencia'] = t['id'] in torres_afectadas and not d['incidencia_activa']
        d['requiere_revision'] = t['id'] in torres_afectadas
        result.append(d)

    con.close()
    return jsonify(result)

# ════════════════════════════════════════════════════════
# AUDITORÍA DE DATOS — validaciones de integridad del sistema
# ════════════════════════════════════════════════════════
def _correr_auditoria(con):
    """Corre todas las validaciones. Devuelve (total, checks).
    Cada check: {clave, titulo, severidad, cantidad, items:[{texto, clientes:[{id,nombre}]}]}"""
    checks = []

    def add(clave, titulo, severidad, items):
        if items:
            checks.append({'clave': clave, 'titulo': titulo,
                           'severidad': severidad, 'cantidad': len(items),
                           'items': items[:80]})

    def it(texto, clientes=None):
        return {'texto': texto, 'clientes': clientes or []}

    # ── 1. IPs duplicadas ──
    rows = con.execute("""
        SELECT TRIM(ip_asignada) ip FROM clientes
        WHERE ip_asignada IS NOT NULL AND TRIM(ip_asignada) NOT IN ('', '0.0.0.0')
          AND UPPER(TRIM(ip_asignada)) != 'PPPOE' AND estado NOT IN ('baja','rescision')
        GROUP BY TRIM(ip_asignada) HAVING COUNT(*) > 1
        ORDER BY COUNT(*) DESC""").fetchall()
    items = []
    for r in rows:
        quienes = con.execute("""SELECT id, nombre, nro_cliente FROM clientes
            WHERE TRIM(ip_asignada)=? AND estado NOT IN ('baja','rescision')""", (r['ip'],)).fetchall()
        items.append(it(f"IP {r['ip']} → {len(quienes)} clientes",
                        [{'id': q['id'], 'nombre': f"{q['nombre']} (#{q['nro_cliente'] or 's/n'})"} for q in quienes]))
    add('ip_dup', 'IPs asignadas a más de un cliente', 'alta', items)

    # ── 2. Series duplicadas ──
    rows = con.execute("""
        SELECT TRIM(equipo_serie) s FROM clientes
        WHERE equipo_serie IS NOT NULL AND TRIM(equipo_serie) != ''
          AND estado NOT IN ('baja','rescision')
        GROUP BY UPPER(TRIM(equipo_serie)) HAVING COUNT(*) > 1
        ORDER BY COUNT(*) DESC""").fetchall()
    items = []
    for r in rows:
        quienes = con.execute("""SELECT id, nombre, nro_cliente FROM clientes
            WHERE UPPER(TRIM(equipo_serie))=UPPER(?) AND estado NOT IN ('baja','rescision')""", (r['s'],)).fetchall()
        items.append(it(f"Serie {r['s']} → {len(quienes)} clientes",
                        [{'id': q['id'], 'nombre': f"{q['nombre']} (#{q['nro_cliente'] or 's/n'})"} for q in quienes]))
    add('serie_dup', 'Equipos (serie) asignados a más de un cliente', 'alta', items)

    # ── 3. MACs duplicadas ──
    rows = con.execute("""
        SELECT TRIM(mac_address) m FROM clientes
        WHERE mac_address IS NOT NULL AND TRIM(mac_address) != ''
          AND estado NOT IN ('baja','rescision')
        GROUP BY UPPER(REPLACE(REPLACE(TRIM(mac_address),':',''),'-','')) HAVING COUNT(*) > 1""").fetchall()
    items = []
    for r in rows:
        quienes = con.execute("""SELECT id, nombre, nro_cliente FROM clientes
            WHERE UPPER(REPLACE(REPLACE(TRIM(mac_address),':',''),'-',''))=UPPER(REPLACE(REPLACE(TRIM(?),':',''),'-',''))
              AND estado NOT IN ('baja','rescision')""", (r['m'],)).fetchall()
        items.append(it(f"MAC {r['m']} → {len(quienes)} clientes",
                        [{'id': q['id'], 'nombre': f"{q['nombre']} (#{q['nro_cliente'] or 's/n'})"} for q in quienes]))
    add('mac_dup', 'MACs asignadas a más de un cliente', 'media', items)

    # ── 4. NAPs sobrepasados ──
    rows = con.execute(f"""
        SELECT TRIM(nap) nap, COUNT(*) c FROM clientes
        WHERE nap IS NOT NULL AND TRIM(nap) != '' AND estado NOT IN ('baja','rescision')
        GROUP BY TRIM(nap) HAVING COUNT(*) > {NAP_LIMIT} ORDER BY c DESC""").fetchall()
    add('nap_sobre', f'NAPs con más de {NAP_LIMIT} clientes (sobrecarga)', 'alta',
        [it(f"{r['nap']} → {r['c']} clientes (+{r['c']-NAP_LIMIT} de exceso)") for r in rows])

    # ── 5. Abono/equipo inconsistente ──
    rows = con.execute("""SELECT id, nombre, nro_cliente FROM clientes
        WHERE tipo_servicio='fibra' AND estado='activo'
          AND (nap IS NULL OR TRIM(nap)='') ORDER BY nombre LIMIT 200""").fetchall()
    add('fibra_sin_nap', 'Clientes FIBRA activos sin NAP asignada', 'media',
        [it(f"{r['nombre']} (#{r['nro_cliente'] or 's/n'})",
            [{'id': r['id'], 'nombre': r['nombre']}]) for r in rows])

    rows = con.execute("""SELECT id, nombre, nro_cliente FROM clientes
        WHERE tipo_servicio='fibra' AND estado='activo'
          AND (equipo_serie IS NULL OR TRIM(equipo_serie)='') ORDER BY nombre LIMIT 200""").fetchall()
    add('fibra_sin_equipo', 'Clientes FIBRA activos sin equipo (ONU) cargado', 'media',
        [it(f"{r['nombre']} (#{r['nro_cliente'] or 's/n'})",
            [{'id': r['id'], 'nombre': r['nombre']}]) for r in rows])

    rows = con.execute("""SELECT id, nombre, nro_cliente, nap, olt_nombre FROM clientes
        WHERE tipo_servicio='inalambrico' AND estado NOT IN ('baja','rescision')
          AND ((nap IS NOT NULL AND TRIM(nap)!='') OR (olt_nombre IS NOT NULL AND TRIM(olt_nombre)!=''))
        ORDER BY nombre LIMIT 200""").fetchall()
    add('inal_con_nap', 'Clientes INALÁMBRICOS con NAP/OLT asignada (¿migrados sin actualizar tipo?)', 'media',
        [it(f"{r['nombre']} (#{r['nro_cliente'] or 's/n'}) — NAP: {r['nap'] or '—'} OLT: {r['olt_nombre'] or '—'}",
            [{'id': r['id'], 'nombre': r['nombre']}]) for r in rows])

    rows = con.execute("""SELECT id, nombre, nro_cliente, plan, tipo_servicio FROM clientes
        WHERE estado='activo' AND plan IS NOT NULL AND TRIM(plan)!=''
          AND ((tipo_servicio='inalambrico' AND (UPPER(plan) LIKE '%FIBRA%' OR UPPER(plan) LIKE '%FTTH%' OR UPPER(plan) LIKE '%FO %'))
            OR (tipo_servicio='fibra' AND (UPPER(plan) LIKE '%INALAMBRIC%' OR UPPER(plan) LIKE '%WIRELESS%' OR UPPER(plan) LIKE '%AIRE%')))
        ORDER BY nombre LIMIT 200""").fetchall()
    add('plan_vs_tipo', 'Abono/plan que NO condice con el tipo de servicio', 'alta',
        [it(f"{r['nombre']} (#{r['nro_cliente'] or 's/n'}) — tipo: {r['tipo_servicio']}, plan: {r['plan']}",
            [{'id': r['id'], 'nombre': r['nombre']}]) for r in rows])

    r = con.execute("""SELECT COUNT(*) c FROM clientes
        WHERE estado='activo' AND (plan IS NULL OR TRIM(plan)='')""").fetchone()
    if r['c']:
        add('sin_plan', 'Clientes activos sin plan/abono cargado', 'baja',
            [it(f"{r['c']} clientes activos no tienen plan cargado (afecta facturación estimada)")])

    # ── 6. Activos sin coordenadas ──
    r = con.execute("""SELECT COUNT(*) c FROM clientes
        WHERE estado='activo' AND (lat IS NULL OR TRIM(COALESCE(lat,''))='' OR CAST(lat AS REAL)=0)""").fetchone()
    if r['c']:
        add('sin_coords', 'Clientes activos sin coordenadas (no aparecen en mapa/rutas)', 'baja',
            [it(f"{r['c']} clientes activos sin lat/lng")])

    # ── 7. Servicios estancados ──
    rows = con.execute("""
        SELECT s.id sid, s.tipo, c.id cid, c.nombre, c.nro_cliente,
               CAST(julianday('now') - julianday(s.fecha_creacion) AS INT) dias
        FROM servicios s LEFT JOIN clientes c ON c.id=s.cliente_id
        WHERE s.estado='pendiente' AND s.fecha_creacion IS NOT NULL AND s.fecha_creacion != ''
          AND julianday('now') - julianday(s.fecha_creacion) > 30
        ORDER BY dias DESC LIMIT 100""").fetchall()
    add('svc_viejos', 'Servicios pendientes hace más de 30 días', 'media',
        [it(f"#{r['sid']} {r['tipo'] or ''} — {r['nombre'] or 's/cliente'} ({r['dias']} días)",
            [{'id': r['cid'], 'nombre': r['nombre']}] if r['cid'] else []) for r in rows])

    # ── 8. NAP: lo que dice la OLT vs lo cargado en Pucará ──
    # nap_olt lo escribe olt_poller leyendo el nombre de la interfaz de la ONU
    # (rótulo que ponen los técnicos en la OLT). Si no coincide con la NAP del
    # cliente, uno de los dos está mal: normalmente se movió el cliente de NAP
    # y sólo se actualizó de un lado. Se compara sólo el número (NAP2 ↔ 2).
    if _col_existe(con, 'onu_senal', 'nap_olt'):
        rows = con.execute("""
            SELECT c.id, c.nombre, c.nro_cliente, c.nap AS nap_pucara, o.nap_olt,
                   o.pon, o.onu
            FROM onu_senal o
            JOIN clientes c ON TRIM(c.nro_cliente) = TRIM(o.nro_cliente)
            WHERE o.nap_olt IS NOT NULL AND TRIM(o.nap_olt) != ''
              AND c.estado NOT IN ('baja','rescision')
              AND TRIM(COALESCE(c.nap,'')) != ''
              AND REPLACE(UPPER(TRIM(o.nap_olt)),'NAP','') !=
                  REPLACE(UPPER(TRIM(c.nap)),'NAP','')
            ORDER BY c.nombre LIMIT 200""").fetchall()
        add('nap_olt_discrepa', 'NAP distinta entre la OLT y Pucará', 'media',
            [it(f"{r['nombre']} (#{r['nro_cliente'] or 's/n'}) — Pucará: {r['nap_pucara']} · "
                f"OLT: {r['nap_olt']} (PON{r['pon']}/{r['onu']})",
                [{'id': r['id'], 'nombre': r['nombre']}]) for r in rows])

    # ── 9. Seguridad: admin default ──
    adm = con.execute("SELECT password FROM usuarios WHERE username='admin' AND activo=1").fetchone()
    if adm and check_password_hash(adm['password'], 'admin123'):
        add('admin_default', 'SEGURIDAD: el usuario admin tiene la contraseña por defecto', 'alta',
            [it("Cambiá la contraseña del usuario 'admin' desde Configuración → Usuarios.")])

    orden = {'alta': 0, 'media': 1, 'baja': 2}
    checks.sort(key=lambda x: orden.get(x['severidad'], 9))
    total = sum(c['cantidad'] for c in checks)
    return total, checks

@app.route('/api/auditoria/datos')
@login_required
@admin_required
def auditoria_datos():
    con = get_db()
    total, checks = _correr_auditoria(con)
    con.close()
    return jsonify({'total_problemas': total, 'checks': checks})

@app.route('/api/auditoria/cron', methods=['POST'])
def auditoria_cron():
    """Auditoría programada (para cron). Protegida por token de archivo .cron_token.
    Compara con la corrida anterior y avisa por Telegram SOLO si hay problemas nuevos."""
    tokenfile = os.path.join(os.path.dirname(__file__), '.cron_token')
    if not os.path.exists(tokenfile):
        # Generar el token la primera vez
        import secrets as _sec
        with open(tokenfile, 'w') as f:
            f.write(_sec.token_hex(16))
        try: os.chmod(tokenfile, 0o600)
        except OSError: pass
    token_ok = open(tokenfile).read().strip()
    token_req = request.headers.get('X-Cron-Token', '') or (request.get_json(silent=True) or {}).get('token','')
    if token_req != token_ok:
        return jsonify({'error':'token inválido'}), 403

    con = get_db()
    con.execute("""CREATE TABLE IF NOT EXISTS auditoria_snapshot(
        clave TEXT PRIMARY KEY, cantidad INTEGER, actualizado TEXT)""")
    total, checks = _correr_auditoria(con)
    # Comparar con snapshot anterior
    previo = {r['clave']: r['cantidad'] for r in con.execute("SELECT clave, cantidad FROM auditoria_snapshot").fetchall()}
    nuevos = []
    for c in checks:
        antes = previo.get(c['clave'], 0)
        if c['cantidad'] > antes:
            nuevos.append(f"• {c['titulo']}: {antes} → {c['cantidad']} (+{c['cantidad']-antes})")
    # Guardar snapshot actual
    con.execute("DELETE FROM auditoria_snapshot")
    for c in checks:
        con.execute("INSERT INTO auditoria_snapshot(clave,cantidad,actualizado) VALUES(?,?,datetime('now','localtime'))",
                    (c['clave'], c['cantidad']))
    con.commit(); con.close()

    enviado = False
    if nuevos:
        msg = "🔍 <b>Auditoría Pucara — problemas nuevos</b>\n\n" + "\n".join(nuevos)
        ok, det = enviar_telegram(msg)
        enviado = ok
    return jsonify({'ok': True, 'total': total, 'nuevos': len(nuevos), 'telegram_enviado': enviado})

# ── Gestión de rangos IP ──
@app.route('/api/ip_rangos')
@login_required
def get_ip_rangos():
    con = get_db()
    rows = con.execute("SELECT * FROM ip_rangos ORDER BY subred").fetchall()
    # Conteo de uso por subred
    out = []
    for r in rows:
        d = dict(r)
        d['en_uso'] = con.execute(
            "SELECT COUNT(*) FROM clientes WHERE ip_asignada LIKE ? AND estado NOT IN ('baja','rescision')",
            (f"169.254.{r['subred']}.%",)).fetchone()[0]
        d['capacidad'] = r['host_hasta'] - max(r['host_desde'], 51) + 1
        out.append(d)
    con.close()
    return jsonify(out)

@app.route('/api/ip_rangos', methods=['POST'])
@login_required
@admin_required
def crear_ip_rango():
    d = request.get_json() or {}
    if not d.get('subred'):
        return jsonify({'error':'subred requerida'}), 400
    con = get_db()
    con.execute("""INSERT INTO ip_rangos(subred,host_desde,host_hasta,localidades,origen)
        VALUES(?,?,?,?,?) ON CONFLICT(subred) DO UPDATE SET
        host_desde=excluded.host_desde, host_hasta=excluded.host_hasta,
        localidades=excluded.localidades""",
        (int(d['subred']), int(d.get('host_desde',51)), int(d.get('host_hasta',254)),
         d.get('localidades',''), d.get('origen','manual')))
    con.commit(); con.close()
    return jsonify({'ok':True})

@app.route('/api/ip_rangos/<int:rid>', methods=['DELETE'])
@login_required
@admin_required
def borrar_ip_rango(rid):
    con = get_db()
    con.execute("DELETE FROM ip_rangos WHERE id=?", (rid,))
    con.commit(); con.close()
    return jsonify({'ok':True})

# ════════════════════════════════════════════════════════
# GRILLA DE IPs — equipos de torre (1-50) y clientes (51-254)
# ════════════════════════════════════════════════════════
@app.route('/api/ip_grilla')
@login_required
def ip_grilla():
    """Grilla completa de una subred: cada host con su estado y a quién pertenece.
    ?subred=80&bloque=torre  → hosts 1-50 (equipos de torre)
    ?subred=80&bloque=clientes → hosts 51-254 (clientes)"""
    subred = request.args.get('subred', type=int)
    bloque = request.args.get('bloque', 'clientes')
    if subred is None:
        return jsonify({'error': 'subred requerida'}), 400
    h_ini, h_fin = (1, 50) if bloque == 'torre' else (51, 254)
    con = get_db()
    # Equipos de torre en esta subred
    torre = {r['host']: dict(r) for r in con.execute(
        "SELECT * FROM ip_equipos_torre WHERE subred=?", (subred,)).fetchall()}
    # Clientes con IP en esta subred
    prefijo = f"169.254.{subred}."
    cli_rows = con.execute("""SELECT id, nombre, nro_cliente, ip_asignada, estado, localidad, tipo_servicio
        FROM clientes WHERE ip_asignada LIKE ? AND estado NOT IN ('baja','rescision')""",
        (prefijo + '%',)).fetchall()
    clientes = {}
    for r in cli_rows:
        try:
            h = int(r['ip_asignada'].strip().split('.')[-1])
            clientes[h] = dict(r)
        except (ValueError, IndexError):
            continue
    con.close()
    grilla = []
    for h in range(h_ini, h_fin + 1):
        ip = f"169.254.{subred}.{h}"
        if bloque == 'torre':
            eq = torre.get(h)
            grilla.append({'host': h, 'ip': ip,
                           'ocupada': bool(eq and (eq['nombre'] or eq['mac'])),
                           'nombre': eq['nombre'] if eq else '',
                           'mac': eq['mac'] if eq else '',
                           'notas': eq['notas'] if eq else ''})
        else:
            cli = clientes.get(h)
            grilla.append({'host': h, 'ip': ip,
                           'ocupada': bool(cli),
                           'cliente_id': cli['id'] if cli else None,
                           'nombre': cli['nombre'] if cli else '',
                           'nro_cliente': cli['nro_cliente'] if cli else '',
                           'localidad': cli['localidad'] if cli else '',
                           'tipo_servicio': cli['tipo_servicio'] if cli else ''})
    libres = sum(1 for g in grilla if not g['ocupada'])
    return jsonify({'subred': subred, 'bloque': bloque, 'grilla': grilla,
                    'total': len(grilla), 'ocupadas': len(grilla) - libres, 'libres': libres})

@app.route('/api/ip_equipos_torre', methods=['POST'])
@login_required
@admin_required
def set_equipo_torre():
    """Crear/editar/borrar un equipo de torre. Body: {subred, host, nombre, mac, notas}.
    Si nombre y mac vienen vacíos, libera (borra) esa IP."""
    d = request.get_json() or {}
    subred = d.get('subred'); host = d.get('host')
    if subred is None or host is None:
        return jsonify({'error': 'subred y host requeridos'}), 400
    if not (1 <= int(host) <= 50):
        return jsonify({'error': 'el bloque de torre es host 1-50'}), 400
    con = get_db()
    nombre = (d.get('nombre') or '').strip()
    mac = (d.get('mac') or '').strip()
    notas = (d.get('notas') or '').strip()
    if not nombre and not mac:
        con.execute("DELETE FROM ip_equipos_torre WHERE subred=? AND host=?", (subred, host))
    else:
        con.execute("""INSERT INTO ip_equipos_torre(subred,host,nombre,mac,notas,modificado)
            VALUES(?,?,?,?,?,datetime('now','localtime'))
            ON CONFLICT(subred,host) DO UPDATE SET
            nombre=excluded.nombre, mac=excluded.mac, notas=excluded.notas,
            modificado=excluded.modificado""", (subred, host, nombre, mac, notas))
    con.commit(); con.close()
    return jsonify({'ok': True})

@app.route('/api/ip_asignar_manual', methods=['POST'])
@login_required
@admin_required
def ip_asignar_manual():
    """Asigna manualmente una IP a un cliente (ej: fibra→inalámbrico por mudanza).
    Body: {cliente_id, ip}. Valida que la IP no esté ocupada por otro."""
    d = request.get_json() or {}
    cliente_id = d.get('cliente_id'); ip = (d.get('ip') or '').strip()
    if not cliente_id or not ip:
        return jsonify({'error': 'cliente_id e ip requeridos'}), 400
    import re as _re
    if not _re.match(r'^169\.254\.\d{1,3}\.\d{1,3}$', ip):
        return jsonify({'error': 'formato de IP inválido'}), 400
    host = int(ip.split('.')[-1])
    if host <= 50:
        return jsonify({'error': 'los host 1-50 son para equipos de torre, no clientes'}), 400
    con = get_db()
    # ¿Ya la tiene otro cliente?
    otro = con.execute("""SELECT id, nombre FROM clientes
        WHERE TRIM(ip_asignada)=? AND id!=? AND estado NOT IN ('baja','rescision')""",
        (ip, cliente_id)).fetchone()
    if otro:
        con.close()
        return jsonify({'error': f"IP ya asignada a {otro['nombre']} (id {otro['id']})"}), 409
    con.execute("UPDATE clientes SET ip_asignada=?, modificado=datetime('now','localtime') WHERE id=?",
                (ip, cliente_id))
    con.commit(); con.close()
    log('edicion', f'IP {ip} asignada manualmente', '', 'clientes')
    return jsonify({'ok': True, 'ip': ip})

# ── TransDat: geolocalización de vehículos ──
_transdat_cache = {'token': None, 'expira': 0}
_transdat_pos_cache = {'data': None, 'expira': 0}  # cachea posiciones ~25s (evita saturar)

def _transdat_token():
    """Obtiene (y cachea ~23h) el token de TransDat."""
    import time, urllib.request, json as _json
    if _transdat_cache['token'] and time.time() < _transdat_cache['expira']:
        return _transdat_cache['token'], None
    user = _get_config('transdat_user', '')
    pwd = _get_config('transdat_pass', '')
    if not user or not pwd:
        return None, 'Faltan credenciales TransDat en configuración'
    try:
        req = urllib.request.Request(
            'https://clientes.transdat.com.ar/authex',
            data=_json.dumps({'user': user, 'pass': pwd}).encode(),
            headers={'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = _json.loads(resp.read().decode())
        token = data.get('token')
        if not token:
            return None, f"TransDat no devolvió token: {data}"
        _transdat_cache['token'] = token
        _transdat_cache['expira'] = time.time() + 23 * 3600
        return token, None
    except Exception as e:
        return None, f"Error autenticando con TransDat: {e}"

@app.route('/api/vehiculos/posiciones')
@login_required
def vehiculos_posiciones():
    """Última posición de los vehículos (TransDat TD-GPS).
    Cachea el resultado ~25s para que muchos usuarios NO golpeen a TransDat
    cada uno por su cuenta (evita saturar el servidor con llamadas externas lentas)."""
    import urllib.request, json as _json
    # Servir de caché si es reciente (evita llamadas externas repetidas)
    ahora = time.time()
    if _transdat_pos_cache['data'] is not None and ahora < _transdat_pos_cache['expira']:
        return jsonify(_transdat_pos_cache['data'])
    token, err = _transdat_token()
    if err:
        return jsonify({'error': err}), 502
    try:
        req = urllib.request.Request(
            'https://clientes.transdat.com.ar/ex/objects/request',
            headers={'Authorization': f'Bearer {token}'})
        # Timeout CORTO: si TransDat tarda, no bloqueamos un hilo del servidor 15s
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = _json.loads(resp.read().decode())
    except Exception as e:
        # Token pudo vencer antes: invalidar cache para reintento próximo
        _transdat_cache['token'] = None
        # Si tenemos posiciones viejas en caché, las servimos en vez de fallar
        if _transdat_pos_cache['data'] is not None:
            return jsonify(_transdat_pos_cache['data'])
        return jsonify({'error': f'Error consultando posiciones: {e}'}), 502
    unidades = data if isinstance(data, list) else data.get('objects', data.get('data', []))
    out = []
    for u in (unidades or []):
        try:
            out.append({
                'patente': u.get('Patente',''),
                'descripcion': u.get('Descripcion',''),
                'lat': float(u.get('Latitud')),
                'lng': float(u.get('Longitud')),
                'velocidad': u.get('Velocidad', 0),
                'sentido': u.get('Sentido', 0),
                'fecha': u.get('Re_Fecha',''),
            })
        except (TypeError, ValueError):
            continue
    # Guardar en caché ~25s para no golpear a TransDat en cada request
    _transdat_pos_cache['data'] = out
    _transdat_pos_cache['expira'] = time.time() + 25
    return jsonify(out)

@app.route('/api/configuracion')
@login_required
def get_configuracion():
    con = get_db()
    if _table_exists(con, 'configuracion'):
        rows = con.execute("SELECT clave, valor FROM configuracion").fetchall()
        con.close()
        return jsonify({r['clave']:r['valor'] for r in rows})
    con.close()
    return jsonify({})

@app.route('/api/configuracion', methods=['PUT'])
@login_required
@admin_required
def set_configuracion():
    d = request.get_json()
    con = get_db()
    if not _table_exists(con, 'configuracion'):
        con.execute("CREATE TABLE configuracion(clave TEXT PRIMARY KEY, valor TEXT)")
    for k, v in d.items():
        con.execute("INSERT OR REPLACE INTO configuracion(clave,valor) VALUES(?,?)", (k, str(v)))
    con.commit(); con.close()
    return jsonify({'ok':True})

def _get_config(clave, default=None):
    """Lee un valor de la tabla configuracion."""
    con = get_db()
    if not _table_exists(con, 'configuracion'):
        con.close(); return default
    r = con.execute("SELECT valor FROM configuracion WHERE clave=?", (clave,)).fetchone()
    con.close()
    return r['valor'] if r else default

def enviar_telegram(mensaje, chat_id=None):
    """Envía un mensaje por Telegram usando el bot configurado.
    Devuelve (ok, detalle). Reutilizable para alertas automáticas."""
    import urllib.request, urllib.parse, json as _json
    token = _get_config('telegram_token', '').strip()
    chat = (chat_id or _get_config('telegram_chat_id', '')).strip()
    if not token or not chat:
        return False, 'Falta token o chat_id'
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        'chat_id': chat,
        'text': mensaje,
        'parse_mode': 'HTML',
    }).encode()
    try:
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=10) as resp:
            res = _json.loads(resp.read().decode())
            if res.get('ok'):
                return True, 'enviado'
            return False, res.get('description', 'error desconocido')
    except Exception as e:
        return False, str(e)

@app.route('/api/configuracion/test_telegram', methods=['POST'])
@login_required
@admin_required
def test_telegram():
    # Usa lo que llegue en el body, o lo guardado en config
    d = request.get_json() or {}
    token = (d.get('telegram_token') or _get_config('telegram_token','')).strip()
    chat = (d.get('telegram_chat_id') or _get_config('telegram_chat_id','')).strip()
    if not token or not chat:
        return jsonify({'ok':False,'error':'Falta token o Chat ID'}), 400
    # Guardar primero, después probar
    con = get_db()
    if not _table_exists(con, 'configuracion'):
        con.execute("CREATE TABLE configuracion(clave TEXT PRIMARY KEY, valor TEXT)")
    con.execute("INSERT OR REPLACE INTO configuracion(clave,valor) VALUES('telegram_token',?)", (token,))
    con.execute("INSERT OR REPLACE INTO configuracion(clave,valor) VALUES('telegram_chat_id',?)", (chat,))
    con.commit(); con.close()
    # Enviar mensaje de prueba
    ok, detalle = enviar_telegram(
        "✅ <b>NetAdmin ERLAN</b>\nConexión de Telegram configurada correctamente. A partir de ahora recibirás alertas del sistema aquí.",
        chat_id=chat)
    if ok:
        return jsonify({'ok':True,'msg':'Mensaje de prueba enviado. Revisá tu Telegram.'})
    return jsonify({'ok':False,'error':detalle}), 400

@app.route('/api/monitoreo')
@login_required
def get_monitoreo():
    con = get_db()
    rows = con.execute("SELECT * FROM monitoreo_dispositivos ORDER BY nombre").fetchall()
    con.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/monitoreo', methods=['POST'])
@login_required
def crear_monitoreo():
    d = request.get_json() or {}
    if not d.get('nombre'):
        return jsonify({'error':'nombre requerido'}), 400
    con = get_db()
    cur = con.execute("""INSERT INTO monitoreo_dispositivos(nombre, tipo, ip)
                         VALUES(?,?,?)""",
                      (d.get('nombre'), d.get('tipo','otro'), d.get('ip','')))
    con.commit(); con.close()
    return jsonify({'ok':True, 'id':cur.lastrowid})

@app.route('/api/monitoreo/<int:mid>', methods=['PUT'])
@login_required
def actualizar_monitoreo(mid):
    d = request.get_json() or {}
    con = get_db()
    con.execute("UPDATE monitoreo_dispositivos SET nombre=?, tipo=?, ip=? WHERE id=?",
                (d.get('nombre'), d.get('tipo','otro'), d.get('ip',''), mid))
    con.commit(); con.close()
    return jsonify({'ok':True})

@app.route('/api/monitoreo/<int:mid>', methods=['DELETE'])
@login_required
def eliminar_monitoreo(mid):
    con = get_db()
    con.execute("DELETE FROM monitoreo_dispositivos WHERE id=?", (mid,))
    con.commit(); con.close()
    return jsonify({'ok':True})

@app.route('/api/monitoreo/ping/<int:mid>', methods=['POST'])
@login_required
def ping_dispositivo(mid):
    """Hace ping a un dispositivo de monitoreo puntual."""
    import subprocess
    con = get_db()
    disp = con.execute("SELECT ip FROM monitoreo_dispositivos WHERE id=?", (mid,)).fetchone()
    if not disp:
        con.close(); return jsonify({'error':'no encontrado'}), 404
    ip = (disp['ip'] or '').strip()
    estado, ms = 'offline', None
    if ip and ip != '0.0.0.0':
        try:
            result = subprocess.run(['ping','-c','1','-W','2',ip], capture_output=True, timeout=5)
            if result.returncode == 0:
                m = re.search(r'time[=<](\d+\.?\d*)', result.stdout.decode())
                ms = float(m.group(1)) if m else 0
                estado = 'warning' if ms > 100 else 'online'
        except Exception:
            pass
    con.execute("UPDATE monitoreo_dispositivos SET ping_estado=?, ping_ms=?, ultimo_ping=datetime('now','localtime') WHERE id=?",
                (estado, ms, mid))
    con.commit(); con.close()
    return jsonify({'ok':True, 'ping_estado':estado, 'ping_ms':ms})

@app.route('/api/monitoreo/resumen')
@login_required
def monitoreo_resumen():
    con = get_db()
    base = "SELECT COUNT(*) FROM clientes WHERE estado='activo'"
    online = con.execute(base + " AND ping_estado='online'").fetchone()[0]
    offline = con.execute(base + " AND ping_estado='offline'").fetchone()[0]
    warning = con.execute(base + " AND ping_estado='warning'").fetchone()[0]
    sin_ip = con.execute(base + " AND (ip_asignada IS NULL OR ip_asignada='' OR ip_asignada='PPPoE')").fetchone()[0]
    total = con.execute(base).fetchone()[0]
    con.close()
    return jsonify({'total':total,'online':online,'offline':offline,'warning':warning,'sin_ip':sin_ip})

@app.route('/api/instalaciones')
@login_required
def get_instalaciones():
    """Instalaciones pendientes reales: soportes tipo instalacion en estado pendiente."""
    estado = request.args.get('estado','')
    con = get_db()
    sql = """SELECT s.*, c.nombre as cliente_nombre, c.telefono as cliente_tel,
             c.direccion as cliente_dir, c.localidad as cliente_localidad,
             c.tipo_servicio as cliente_tipo, c.plan as cliente_plan,
             c.ip_asignada, c.pppoe_usuario, c.pppoe_clave,
             c.nap as cliente_nap, c.olt_nombre, c.olt_puerto,
             c.cdo as cliente_cdo, c.red as cliente_red,
             c.equipo_marca, c.equipo_modelo, c.equipo_serie
             FROM servicios s LEFT JOIN clientes c ON c.id=s.cliente_id
             WHERE s.tipo='instalacion'"""
    params = []
    if estado:
        sql += " AND s.estado=?"
        params.append(estado)
    else:
        sql += " AND s.estado='pendiente'"
    sql += " ORDER BY s.fecha_programada DESC NULLS LAST, s.fecha_creacion DESC LIMIT 100"
    rows = con.execute(sql, params).fetchall()
    con.close()
    out = []
    for r in rows:
        d = dict(r)
        # Armar el display de NAP con lo que haya (nap, o red/cdo)
        d['cliente_nap_display'] = _armar_nap_display({
            'nap': d.get('cliente_nap'), 'cdo': d.get('cliente_cdo'), 'red': d.get('cliente_red')})
        out.append(d)
    return jsonify(out)

@app.route('/api/pendientes/resumen')
@login_required
def pendientes_resumen():
    """Resumen del pipeline de pendientes para tarjetas del dashboard.
    Servicios técnicos desde la tabla servicios; activación/cálculo/instalación
    desde el estado del cliente (flujo: borrador→calculo→activacion→instalacion)."""
    con = get_db()
    def cli(estado):
        return con.execute("SELECT COUNT(*) FROM clientes WHERE estado=?", (estado,)).fetchone()[0]
    def svc(tipo, estado='pendiente'):
        return con.execute("SELECT COUNT(*) FROM servicios WHERE tipo=? AND estado=?", (tipo, estado)).fetchone()[0]
    out = {
        'servicios_tecnicos_pendientes': svc('servicio_tecnico'),
        'instalaciones_pendientes': svc('instalacion'),
        'borrador': cli('borrador'),
        'pte_calculo': cli('pte_calculo'),
        'pte_activacion': cli('pte_activacion'),
        'pte_instalacion': cli('pte_instalacion'),
    }
    con.close()
    return jsonify(out)

def _armar_nap_display(d):
    """Devuelve la mejor representación de la NAP con los datos disponibles.
    Si hay descripción completa, la usa. Si no, arma algo con red/cdo/número.
    Devuelve None solo si NO hay absolutamente ningún dato de red."""
    nap = (d.get('nap') or '').strip()
    if nap:
        return nap
    # No hay descripción: armar con lo que haya
    partes = []
    red = (d.get('red') or '').strip()
    cdo = (d.get('cdo') or '').strip()
    if red:
        partes.append(red)
    if cdo:
        partes.append(f"CDO {cdo}")
    if partes:
        return ' - '.join(partes)
    return None  # no hay ningún dato de red

@app.route('/api/pendientes/<tipo>')
@login_required
def pendientes_listado(tipo):
    """Listado de clientes en un estado del pipeline.
    tipo ∈ borrador, pte_calculo, pte_activacion, pte_instalacion"""
    mapa = {'borrador':'borrador','pte_calculo':'pte_calculo',
            'pte_activacion':'pte_activacion','pte_instalacion':'pte_instalacion'}
    estado = mapa.get(tipo)
    if not estado:
        return jsonify({'error':'tipo inválido'}), 400
    con = get_db()
    rows = con.execute("""
        SELECT id, nombre, nro_cliente, telefono, direccion, localidad,
               tipo_servicio, plan, nap, lat, lng, creado,
               ip_asignada, pppoe_usuario, pppoe_clave, olt_nombre, olt_puerto,
               red, cdo
        FROM clientes WHERE estado=? ORDER BY creado DESC
    """, (estado,)).fetchall()
    con.close()
    out = []
    for r in rows:
        d = dict(r)
        d['nap_display'] = _armar_nap_display(d)
        out.append(d)
    return jsonify(out)

# ════════════════════════════════════════════════════════
# MÓDULOS DEL SISTEMA — activables por instalación (comercialización modular)
# ════════════════════════════════════════════════════════
_MODULOS_SISTEMA = [
    'dashboard','clientes','mapa','ftth','naps','torres','servicios','incidencias',
    'monitoreo','instalaciones','agenda','historial','rrhh','finanzas','stock',
    'usuarios','permisos','config','sync'
]

@app.route('/api/sistema/modulos')
@login_required
def sistema_modulos():
    """Qué módulos están habilitados en esta instalación. El nav usa esto para ocultar."""
    con = get_db()
    con.execute("""CREATE TABLE IF NOT EXISTS sistema_modulos(
        clave TEXT PRIMARY KEY, habilitado INTEGER DEFAULT 1)""")
    estado = {r['clave']: r['habilitado'] for r in con.execute("SELECT * FROM sistema_modulos").fetchall()}
    con.close()
    # Módulos no registrados = habilitados por defecto
    return jsonify({m: estado.get(m, 1) for m in _MODULOS_SISTEMA})

@app.route('/api/sistema/modulos', methods=['PUT'])
@login_required
@admin_required
def sistema_modulos_set():
    """Habilita/deshabilita módulos. Body: {clave: 0/1, ...}"""
    d = request.get_json() or {}
    con = get_db()
    con.execute("""CREATE TABLE IF NOT EXISTS sistema_modulos(
        clave TEXT PRIMARY KEY, habilitado INTEGER DEFAULT 1)""")
    for clave, hab in d.items():
        if clave in _MODULOS_SISTEMA:
            con.execute("""INSERT INTO sistema_modulos(clave, habilitado) VALUES(?,?)
                ON CONFLICT(clave) DO UPDATE SET habilitado=excluded.habilitado""",
                (clave, 1 if hab else 0))
    con.commit(); con.close()
    return jsonify({'ok': True})

@app.route('/api/permisos/catalogo')
@login_required
def permisos_catalogo():
    # IMPORTANTE: cada 'key' debe coincidir EXACTAMENTE con el nombre usado en
    # navGo('...') del frontend, sino el permiso se guarda pero no aplica al menú.
    return jsonify({
        'modulos': [
            # Directos
            {'key': 'dashboard', 'label': '📊 Dashboard', 'grupo': 'Principal'},
            {'key': 'clientes', 'label': '👥 Clientes', 'grupo': 'Principal'},
            {'key': 'mapa', 'label': '🗺️ Mapa', 'grupo': 'Principal'},
            # FTTH / Red
            {'key': 'ftth', 'label': '🔵 FTTH / Red', 'grupo': 'FTTH / Red'},
            {'key': 'naps', 'label': '📦 NAPs', 'grupo': 'FTTH / Red'},
            {'key': 'gestion-ips', 'label': '🌐 Gestión IPs', 'grupo': 'FTTH / Red'},
            {'key': 'aps', 'label': '📶 Vista de APs', 'grupo': 'FTTH / Red'},
            {'key': 'enlaces-alertas', 'label': '⚠️ Alertas de Enlaces', 'grupo': 'FTTH / Red'},
            {'key': 'torres-enlaces', 'label': '🔗 Enlaces de Torres', 'grupo': 'FTTH / Red'},
            {'key': 'incidencias', 'label': '🚨 Incidencias', 'grupo': 'FTTH / Red'},
            # Servicios
            {'key': 'servicios', 'label': '🔧 Servicios', 'grupo': 'Servicios'},
            {'key': 'activacion-pendiente', 'label': '🟢 Activaciones pendientes', 'grupo': 'Servicios'},
            {'key': 'instalacion-pendiente', 'label': '🛠️ Instalaciones pendientes', 'grupo': 'Servicios'},
            {'key': 'agenda', 'label': '📅 Agenda', 'grupo': 'Servicios'},
            {'key': 'stats-service', 'label': '📈 Estadísticas de servicio', 'grupo': 'Servicios'},
            # Infraestructura
            {'key': 'torres', 'label': '🗼 Torres', 'grupo': 'Infraestructura'},
            {'key': 'monitoreo', 'label': '📡 Monitoreo', 'grupo': 'Infraestructura'},
            # Administración
            {'key': 'bajas', 'label': '📉 Bajas', 'grupo': 'Administración'},
            {'key': 'antiguedad', 'label': '📅 Antigüedad y churn', 'grupo': 'Administración'},
            {'key': 'abonos', 'label': '💵 Abonos', 'grupo': 'Administración'},
            {'key': 'stock', 'label': '📦 Stock', 'grupo': 'Administración'},
            {'key': 'historial', 'label': '📜 Historial', 'grupo': 'Administración'},
            # Gestión / negocio
            {'key': 'guardias', 'label': '🗓️ Guardias', 'grupo': 'Gestión'},
            {'key': 'informes', 'label': '📊 Informes', 'grupo': 'Gestión'},
            {'key': 'finanzas', 'label': '💰 Finanzas', 'grupo': 'Gestión'},
            {'key': 'contabilidad', 'label': '🧮 Contabilidad', 'grupo': 'Gestión'},
            {'key': 'reclamos', 'label': '📨 Reclamos (Tero)', 'grupo': 'Gestión'},
            {'key': 'ftth_plan', 'label': '📐 FTTH Plan', 'grupo': 'Gestión'},
            # Solo administradores
            {'key': 'usuarios', 'label': '👤 Usuarios', 'grupo': 'Sistema', 'admin_only': True},
            {'key': 'rrhh', 'label': '🧑‍💼 RRHH', 'grupo': 'Sistema', 'admin_only': True},
            {'key': 'config', 'label': '⚙️ Configuración', 'grupo': 'Sistema', 'admin_only': True},
            {'key': 'sync', 'label': '🔄 Sync ERP', 'grupo': 'Sistema', 'admin_only': True},
        ],
        'acciones': [
            {'key': 'ver', 'label': 'Ver'},
            {'key': 'crear', 'label': 'Crear'},
            {'key': 'editar', 'label': 'Editar'},
            {'key': 'eliminar', 'label': 'Eliminar'},
        ],
        'flags_especiales': [
            {'key': 'ocultar_precios', 'label': 'Ocultar precios/montos'},
            {'key': 'ocultar_pppoe', 'label': 'Ocultar credenciales PPPoE'},
            {'key': 'solo_lectura_clientes', 'label': 'Clientes: solo lectura'},
            {'key': 'puede_exportar', 'label': 'Puede exportar datos (CSV)'},
            {'key': 'puede_sync', 'label': 'Puede ejecutar sync ERP'},
            {'key': 'puede_editar_guardias', 'label': 'Puede editar guardias'},
        ],
        'roles_template': {
            'admin': {
                'modulos': '*', 'acciones': '*'
            },
            'tecnico': {
                'modulos': ['dashboard','clientes','mapa','naps','torres','ftth','servicios',
                            'incidencias','monitoreo','instalacion-pendiente','activacion-pendiente','agenda'],
                'acciones': ['ver','crear','editar'],
                'flags': ['ocultar_precios']
            },
            'operador': {
                'modulos': ['dashboard','clientes','mapa','naps','servicios','incidencias','agenda'],
                'acciones': ['ver','crear'],
            },
            'administrativo': {
                'modulos': ['dashboard','clientes','mapa','historial','abonos','bajas','finanzas'],
                'acciones': ['ver','crear','editar'],
            },
            'lectura': {
                'modulos': ['dashboard','clientes','mapa','historial'],
                'acciones': ['ver'],
            },
        }
    })

@app.route('/api/historial_senal')
@login_required
def historial_senal():
    nap = request.args.get('nap','')
    cliente_id = request.args.get('cliente_id','')
    limit = int(request.args.get('limit', 20))
    con = get_db()
    if nap:
        rows = con.execute("SELECT * FROM historial_senal WHERE nap_nombre=? ORDER BY fecha DESC LIMIT ?",
                          (nap, limit)).fetchall()
    elif cliente_id:
        rows = con.execute("SELECT * FROM historial_senal_cliente WHERE cliente_id=? ORDER BY fecha DESC LIMIT ?",
                          (int(cliente_id), limit)).fetchall()
    else:
        rows = con.execute("SELECT * FROM historial_senal ORDER BY fecha DESC LIMIT ?", (limit,)).fetchall()
    con.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/historial_senal', methods=['POST'])
@login_required
def crear_historial_senal():
    d = request.get_json()
    nap = d.get('nap_nombre','')
    dbm = d.get('nivel_dbm')
    if not nap or dbm is None:
        return jsonify({'error':'nap_nombre y nivel_dbm requeridos'}), 400
    con = get_db()
    con.execute("""INSERT INTO historial_senal(nap_nombre, nivel_dbm, observaciones, usuario)
                   VALUES(?,?,?,?)""",
                (nap, float(dbm), d.get('observaciones',''), session.get('nombre','')))
    # Actualizar nivel_senal en la NAP
    con.execute("UPDATE naps SET nivel_senal=? WHERE nombre=?", (f"{dbm} dBm", nap))
    con.commit(); con.close()
    return jsonify({'ok':True})

@app.route('/api/incidencias/scope_options')
@login_required
def incidencias_scope():
    con = get_db()
    torres = con.execute("SELECT id, nombre FROM torres ORDER BY nombre").fetchall()
    naps_data = con.execute("SELECT id, nombre, red, olt_nombre, cdo FROM naps ORDER BY nombre").fetchall()
    redes = con.execute("SELECT nombre FROM redes ORDER BY nombre").fetchall()
    olts = con.execute("SELECT id, nombre FROM olts ORDER BY nombre").fetchall()
    # CDOs únicos desde NAPs
    cdos = con.execute("""SELECT DISTINCT cdo, red, olt_nombre FROM naps
        WHERE cdo IS NOT NULL AND cdo != '' ORDER BY red, cdo""").fetchall()
    con.close()
    return jsonify({
        'torres': [dict(t) for t in torres],
        'naps': [dict(n) for n in naps_data],
        'redes': [{'nombre': r['nombre']} for r in redes],
        'olts': [o['nombre'] for o in olts],
        'cdos': [dict(c) for c in cdos],
    })

def _table_exists(con, table):
    r = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return r is not None


def _col_existe(con, tabla, columna):
    """True si la tabla tiene esa columna. Se usa para que una auditoría o una
    consulta nueva no explote en una base todavía sin migrar."""
    if not _table_exists(con, tabla):
        return False
    return columna in {r[1] for r in con.execute(f"PRAGMA table_info({tabla})").fetchall()}

# ─── TORRES ───────────────────────────────────────────────────────
@app.route('/api/torres')
@login_required
def get_torres():
    con = get_db()
    rows = con.execute("SELECT * FROM torres ORDER BY nombre").fetchall()
    con.close()
    return jsonify([dict(r) for r in rows])

# ══════════ INVENTARIO DE EQUIPOS (Fase 7) ══════════
TIPOS_EQUIPO = ['Router MikroTik','Switch','Media Converter','OLT','ONU','Ubiquiti',
                'Cambium','UPS','Antena','Radio','Fuente','Gabinete','Otro']

@app.route('/api/inventario/tipos')
@login_required
def inventario_tipos():
    return jsonify(TIPOS_EQUIPO)

@app.route('/api/torres/<int:tid>/equipos')
@login_required
def torre_equipos_list(tid):
    """Equipos de una torre/nodo."""
    con = get_db()
    filas = con.execute("SELECT * FROM torre_equipos WHERE torre_id=? ORDER BY tipo, modelo", (tid,)).fetchall()
    con.close()
    return jsonify([dict(f) for f in filas])

@app.route('/api/inventario/equipos')
@login_required
def inventario_equipos():
    """Todos los equipos (con nombre de la torre). Filtros: ?tipo= &torre_id= &es_ap=1"""
    tipo = request.args.get('tipo',''); torre_id = request.args.get('torre_id','')
    es_ap = request.args.get('es_ap','')
    con = get_db()
    sql = """SELECT e.*, t.nombre AS torre_nombre FROM torre_equipos e
             LEFT JOIN torres t ON t.id=e.torre_id WHERE 1=1"""
    p = []
    if tipo: sql += " AND e.tipo=?"; p.append(tipo)
    if torre_id: sql += " AND e.torre_id=?"; p.append(torre_id)
    if es_ap == '1': sql += " AND e.es_ap=1"
    sql += " ORDER BY t.nombre, e.tipo"
    filas = con.execute(sql, p).fetchall()
    con.close()
    return jsonify([dict(f) for f in filas])

@app.route('/api/inventario/equipos', methods=['POST'])
@login_required
def inventario_crear():
    d = request.get_json() or {}
    if not d.get('tipo'):
        return jsonify({'error': 'El tipo es obligatorio'}), 400
    con = get_db()
    cur = con.execute("""INSERT INTO torre_equipos(torre_id,tipo,fabricante,modelo,nro_serie,mac,ip,
        firmware,fecha_compra,costo_adquisicion,valor_actual,estado,ubicacion,observaciones,
        snmp_ip,snmp_community,snmp_fabricante,snmp_version,datos_snmp,es_ap)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (d.get('torre_id'),d.get('tipo'),d.get('fabricante'),d.get('modelo'),d.get('nro_serie'),
         d.get('mac'),d.get('ip'),d.get('firmware'),d.get('fecha_compra'),
         d.get('costo_adquisicion',0) or 0,d.get('valor_actual',0) or 0,
         d.get('estado','operativo'),d.get('ubicacion'),d.get('observaciones'),
         d.get('snmp_ip'),d.get('snmp_community','public'),d.get('snmp_fabricante'),
         d.get('snmp_version','1'),
         json.dumps(d.get('datos_snmp')) if d.get('datos_snmp') else None,
         1 if d.get('es_ap') else 0))
    con.commit(); eid = cur.lastrowid; con.close()
    return jsonify({'ok': True, 'id': eid})

@app.route('/api/inventario/equipos/<int:eid>', methods=['PUT'])
@login_required
def inventario_editar(eid):
    d = request.get_json() or {}
    con = get_db()
    con.execute("""UPDATE torre_equipos SET torre_id=?,tipo=?,fabricante=?,modelo=?,nro_serie=?,
        mac=?,ip=?,firmware=?,fecha_compra=?,costo_adquisicion=?,valor_actual=?,estado=?,
        ubicacion=?,observaciones=?,snmp_ip=?,snmp_community=?,snmp_fabricante=?,snmp_version=?,
        datos_snmp=COALESCE(?,datos_snmp),es_ap=? WHERE id=?""",
        (d.get('torre_id'),d.get('tipo'),d.get('fabricante'),d.get('modelo'),d.get('nro_serie'),
         d.get('mac'),d.get('ip'),d.get('firmware'),d.get('fecha_compra'),
         d.get('costo_adquisicion',0) or 0,d.get('valor_actual',0) or 0,
         d.get('estado','operativo'),d.get('ubicacion'),d.get('observaciones'),
         d.get('snmp_ip'),d.get('snmp_community','public'),d.get('snmp_fabricante'),
         d.get('snmp_version','1'),
         json.dumps(d.get('datos_snmp')) if d.get('datos_snmp') else None,
         1 if d.get('es_ap') else 0, eid))
    con.commit(); con.close()
    return jsonify({'ok': True})

@app.route('/api/inventario/equipos/<int:eid>', methods=['DELETE'])
@login_required
def inventario_borrar(eid):
    con = get_db()
    con.execute("DELETE FROM torre_equipos WHERE id=?", (eid,))
    con.commit(); con.close()
    return jsonify({'ok': True})

# ══════════ TRANSPORTE SNMP: agente en la VM ↔ Pucará (Fase 3.1) ══════════
# Cuando Pucará NO llega a los APs pero la VM sí, la VM corre snmp_agent.py:
#   1) GET  /api/snmp/aps      → lista de APs a sondear (con IP/community/adaptador)
#   2) sondea cada AP con snmp_wireless (en la VM)
#   3) POST /api/snmp/ingest   → resultados normalizados; Pucará cruza y guarda
# Autenticación por token compartido (env SNMP_INGEST_TOKEN). Sin token seteado,
# los endpoints rechazan: no se exponen datos ni escrituras sin credencial.
import hmac as _hmac

def _snmp_token_ok():
    esperado = os.environ.get('SNMP_INGEST_TOKEN')
    if not esperado:
        return False  # sin token configurado, no se habilita el transporte
    dado = request.args.get('token') or request.headers.get('X-SNMP-Token') or ''
    return _hmac.compare_digest(str(dado), str(esperado))

@app.route('/api/snmp/aps')
def snmp_aps_para_agente():
    """Lista de APs a sondear por el agente de la VM."""
    if not _snmp_token_ok():
        return jsonify({'error': 'token invalido o SNMP_INGEST_TOKEN no configurado'}), 403
    con = get_db()
    filas = con.execute("""SELECT id, modelo, snmp_ip, ip, snmp_community, snmp_fabricante, fabricante
                           FROM torre_equipos WHERE es_ap=1 AND estado!='de_baja'""").fetchall()
    con.close()
    out = []
    for a in filas:
        ip = a['snmp_ip'] or a['ip']
        if not ip:
            continue
        out.append({
            'equipo_id': a['id'],
            'ip': ip,
            'community': a['snmp_community'] or 'public',
            'fabricante': (a['snmp_fabricante'] or a['fabricante'] or 'ubiquiti').lower(),
            'modelo': a['modelo'],
        })
    return jsonify(out)

def _guardar_estacion_snmp(con, equipo_id, est, cliente_id, ssid, fecha):
    """Delegado en snmp_wireless: la implementación es una sola y la comparten
    este endpoint y el poller directo."""
    import snmp_wireless
    snmp_wireless.guardar_estacion(con, equipo_id, est, cliente_id, ssid, fecha)


def _purgar_estaciones_snmp(con, equipo_id, macs_vistas):
    import snmp_wireless
    snmp_wireless.purgar_estaciones(con, equipo_id, macs_vistas)


@app.route('/api/snmp/ingest', methods=['POST'])
def snmp_ingest_desde_agente():
    """Recibe los resultados del agente (ya sondeados en la VM), cruza cada
    estación con su cliente y escribe la señal al histórico con source='snmp'.
    El cruce se hace ACÁ (donde vive la data de clientes), no en la VM."""
    if not _snmp_token_ok():
        return jsonify({'error': 'token invalido o SNMP_INGEST_TOKEN no configurado'}), 403
    payload = request.get_json(silent=True) or {}
    resultados = payload.get('results', [])
    try:
        import snmp_wireless
    except Exception as e:
        return jsonify({'error': f'snmp_wireless no disponible: {e}'}), 500

    con = get_db()
    ahora = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    tot_est = tot_vin = 0
    detalle = []
    for res in resultados:
        eid = res.get('equipo_id')
        estaciones = res.get('estaciones', []) or []
        if res.get('error') or not res.get('device'):
            if eid:
                con.execute("UPDATE torre_equipos SET snmp_estado='offline', ultimo_snmp=? WHERE id=?", (ahora, eid))
            detalle.append({'equipo_id': eid, 'estado': 'offline', 'error': res.get('error')})
            continue
        vin = 0
        # Torre del AP (para asignar la torre fehaciente a los clientes que ve)
        torre_ap = None
        if eid:
            _r = con.execute("SELECT torre_id FROM torre_equipos WHERE id=?", (eid,)).fetchone()
            torre_ap = _r['torre_id'] if _r else None
        ssid_ap = (res.get('device') or {}).get('essid')
        macs_vistas = []
        for est in estaciones:
            cid, criterio = snmp_wireless.match_cliente(est, con)
            # Instantánea: se guarda TODA estación que el AP reporte, cruce o no
            # con un cliente. Las que no cruzan son justamente las interesantes
            # (equipo sin cargar en Pucará, o MAC cambiada tras un recambio).
            if est.get('mac') and eid:
                macs_vistas.append(est['mac'])
                _guardar_estacion_snmp(con, eid, est, cid, ssid_ap, ahora)
            if est.get('rssi') is None or not cid:
                continue
            vin += 1
            obs = snmp_wireless.obs_metricas(est)
            if criterio != 'mac':
                obs = (obs + f" · [match:{criterio}]").strip(' ·')
            con.execute("""INSERT INTO historial_senal_cliente
                           (cliente_id, nivel_dbm, tipo, observaciones, fecha, usuario, source)
                           VALUES(?,?,?,?,?,?,?)""",
                        (cid, est['rssi'], 'snmp', obs, ahora, 'snmp_agent', 'snmp'))
            snmp_wireless.marcar_torre_cliente(con, cid, eid, torre_ap, ahora)
        if eid:
            # Las estaciones que ya no aparecen se borran: si no, un cliente que
            # se pasó a otro AP quedaría colgando de los dos.
            _purgar_estaciones_snmp(con, eid, macs_vistas)
            con.execute("UPDATE torre_equipos SET snmp_estado='online', ultimo_snmp=? WHERE id=?", (ahora, eid))
        tot_est += len(estaciones); tot_vin += vin
        detalle.append({'equipo_id': eid, 'estado': 'online', 'estaciones': len(estaciones), 'vinculadas': vin})
    con.commit(); con.close()
    return jsonify({'ok': True, 'estaciones': tot_est, 'vinculadas': tot_vin, 'detalle': detalle})

# ══════════ VALORACIÓN ECONÓMICA (Fase 9) ══════════
def _valorar(con, torre_id=None):
    """Valoración de una torre (torre_id) o de toda la red (None).
    Diferencia costo histórico de adquisición vs valor actual estimado."""
    # Equipos
    if torre_id:
        eq = con.execute("""SELECT COUNT(*) n, COALESCE(SUM(costo_adquisicion),0) costo,
                            COALESCE(SUM(valor_actual),0) actual FROM torre_equipos
                            WHERE torre_id=? AND estado!='de_baja'""", (torre_id,)).fetchone()
        # Producción fehaciente: la torre confirmada por SNMP gana sobre la de proximidad
        cli = con.execute("""SELECT COUNT(*) n, COALESCE(SUM(precio),0) abono,
                            COALESCE(SUM(CASE WHEN torre_id_snmp IS NOT NULL THEN 1 ELSE 0 END),0) snmp_conf
                            FROM clientes
                            WHERE COALESCE(torre_id_snmp, torre_id)=? AND estado='activo'""", (torre_id,)).fetchone()
    else:
        eq = con.execute("""SELECT COUNT(*) n, COALESCE(SUM(costo_adquisicion),0) costo,
                            COALESCE(SUM(valor_actual),0) actual FROM torre_equipos
                            WHERE estado!='de_baja'""").fetchone()
        cli = con.execute("""SELECT COUNT(*) n, COALESCE(SUM(precio),0) abono,
                            COALESCE(SUM(CASE WHEN torre_id_snmp IS NOT NULL THEN 1 ELSE 0 END),0) snmp_conf
                            FROM clientes WHERE estado='activo'""").fetchone()
    abono_mensual = cli['abono'] or 0
    # "Valor económico de clientes": ingreso anualizado como proxy simple (12 meses)
    valor_clientes = abono_mensual * 12
    valor_equipos_actual = eq['actual'] or 0
    return {
        'equipos_cantidad': eq['n'],
        'equipos_costo_historico': round(eq['costo'] or 0, 2),
        'equipos_valor_actual': round(valor_equipos_actual, 2),
        'clientes_cantidad': cli['n'],
        'clientes_confirmados_snmp': cli['snmp_conf'] if 'snmp_conf' in cli.keys() else 0,
        'ingresos_mensuales': round(abono_mensual, 2),
        'valor_clientes_anual': round(valor_clientes, 2),
        'valor_total_estimado': round(valor_equipos_actual + valor_clientes, 2),
    }

@app.route('/api/torres/<int:tid>/valoracion')
@login_required
def torre_valoracion(tid):
    con = get_db()
    t = con.execute("SELECT nombre FROM torres WHERE id=?", (tid,)).fetchone()
    v = _valorar(con, tid)
    con.close()
    v['torre'] = t['nombre'] if t else None
    return jsonify(v)

@app.route('/api/inventario/valoracion_red')
@login_required
def valoracion_red():
    """Valoración de toda la red + desglose por torre."""
    con = get_db()
    total = _valorar(con, None)
    torres = con.execute("SELECT id, nombre FROM torres ORDER BY nombre").fetchall()
    por_torre = []
    for t in torres:
        v = _valorar(con, t['id'])
        v['torre_id'] = t['id']; v['torre'] = t['nombre']
        # solo incluir torres con algo de valor
        if v['equipos_cantidad'] or v['clientes_cantidad']:
            por_torre.append(v)
    con.close()
    por_torre.sort(key=lambda x: -x['valor_total_estimado'])
    return jsonify({'total': total, 'por_torre': por_torre})

@app.route('/api/snmp/eventos')
@login_required
def snmp_eventos_listar():
    """Lista eventos de monitoreo SNMP. ?estado=activo para solo los abiertos."""
    con = get_db()
    estado = request.args.get('estado')
    limite = int(request.args.get('limite', 100))
    q = """SELECT e.*, t.nombre AS torre_nombre,
                  COALESCE(NULLIF(eq.modelo,''), eq.tipo) AS equipo_nombre
           FROM snmp_eventos e
           LEFT JOIN torres t ON t.id = e.torre_id
           LEFT JOIN torre_equipos eq ON eq.id = e.equipo_id"""
    params = []
    if estado:
        q += " WHERE e.estado=?"; params.append(estado)
    q += " ORDER BY e.id DESC LIMIT ?"; params.append(limite)
    filas = con.execute(q, params).fetchall()
    con.close()
    return jsonify([dict(f) for f in filas])

# ══════════ ENLACES PUNTO A PUNTO (Fase 7) ══════════
def _equipo_resumen(con, eid):
    """Datos de un extremo de enlace desde el inventario (sin sondear)."""
    if not eid:
        return None
    e = con.execute("""SELECT eq.id, eq.modelo, eq.fabricante, eq.mac, eq.ip, eq.snmp_ip,
                              eq.snmp_estado, eq.ultimo_snmp, eq.torre_id, t.nombre AS torre_nombre,
                              t.localidad
                       FROM torre_equipos eq LEFT JOIN torres t ON t.id = eq.torre_id
                       WHERE eq.id=?""", (eid,)).fetchone()
    return dict(e) if e else None

# ══════════ PERFILES TÉCNICOS DE RADIO (por modelo, configurables) ══════════
@app.route('/api/perfiles_radio')
@login_required
def perfiles_radio_listar():
    con = get_db()
    filas = con.execute("SELECT * FROM perfil_radio ORDER BY fabricante, modelo").fetchall()
    con.close()
    return jsonify([dict(f) for f in filas])

@app.route('/api/perfiles_radio', methods=['POST'])
@login_required
def perfiles_radio_crear():
    d = request.get_json() or {}
    if not (d.get('fabricante') and d.get('modelo')):
        return jsonify({'error': 'Fabricante y modelo son obligatorios'}), 400
    con = get_db()
    dup = con.execute("SELECT id FROM perfil_radio WHERE fabricante=? AND modelo=?",
                      (d['fabricante'], d['modelo'])).fetchone()
    if dup:
        con.close(); return jsonify({'error': 'Ya existe un perfil para ese fabricante/modelo'}), 400
    campos = ['fabricante','modelo','tipo_equipo','apertura_horizontal','apertura_vertical',
              'ganancia_dbi','frecuencia_min','frecuencia_max','alcance_teorico_m',
              'clientes_recomendados','clientes_max_operativo','throughput_recomendado_mbps',
              'umbral_advertencia','umbral_critico','fuente','observaciones']
    vals = [d.get(c) for c in campos]
    ph = ','.join('?' * len(campos))
    cur = con.execute(f"INSERT INTO perfil_radio({','.join(campos)}) VALUES({ph})", vals)
    con.commit(); pid = cur.lastrowid; con.close()
    return jsonify({'ok': True, 'id': pid})

@app.route('/api/perfiles_radio/<int:pid>', methods=['PUT'])
@login_required
def perfiles_radio_editar(pid):
    d = request.get_json() or {}
    campos = ['fabricante','modelo','tipo_equipo','apertura_horizontal','apertura_vertical',
              'ganancia_dbi','frecuencia_min','frecuencia_max','alcance_teorico_m',
              'clientes_recomendados','clientes_max_operativo','throughput_recomendado_mbps',
              'umbral_advertencia','umbral_critico','fuente','observaciones']
    sets = ','.join(f"{c}=?" for c in campos)
    vals = [d.get(c) for c in campos] + [pid]
    con = get_db()
    con.execute(f"UPDATE perfil_radio SET {sets} WHERE id=?", vals)
    con.commit(); con.close()
    return jsonify({'ok': True})

@app.route('/api/perfiles_radio/<int:pid>', methods=['DELETE'])
@login_required
def perfiles_radio_borrar(pid):
    con = get_db()
    # No borrar si hay equipos usándolo (integridad)
    usos = con.execute("SELECT COUNT(*) FROM equipo_radio_fisico WHERE perfil_radio_id=?", (pid,)).fetchone()[0]
    if usos:
        con.close(); return jsonify({'error': f'{usos} equipo(s) usan este perfil. Reasignalos primero.'}), 400
    con.execute("DELETE FROM perfil_radio WHERE id=?", (pid,))
    con.commit(); con.close()
    return jsonify({'ok': True})

# ══════════ DATOS FÍSICOS DE UN EQUIPO (azimut, apertura, alcance…) ══════════
def _cobertura_efectiva(fisico, perfil):
    """Resuelve apertura/alcance efectivos: override del equipo o, si NULL, el del perfil.
    Devuelve (apertura_h, alcance_m) o None donde no haya dato (no se inventa)."""
    ap = None; al = None
    if fisico:
        ap = fisico.get('apertura_h_override')
        al = fisico.get('alcance_override_m')
    if ap is None and perfil:
        ap = perfil.get('apertura_horizontal')
    if al is None and perfil:
        al = perfil.get('alcance_teorico_m')
    return ap, al

@app.route('/api/inventario/equipos/<int:eid>/fisico')
@login_required
def equipo_fisico_get(eid):
    """Datos físicos + perfil resuelto de un equipo, con apertura/alcance efectivos."""
    con = get_db()
    fis = con.execute("SELECT * FROM equipo_radio_fisico WHERE equipo_id=?", (eid,)).fetchone()
    fis = dict(fis) if fis else None
    perfil = None
    if fis and fis.get('perfil_radio_id'):
        p = con.execute("SELECT * FROM perfil_radio WHERE id=?", (fis['perfil_radio_id'],)).fetchone()
        perfil = dict(p) if p else None
    con.close()
    ap, al = _cobertura_efectiva(fis, perfil)
    return jsonify({'fisico': fis, 'perfil': perfil,
                    'apertura_efectiva': ap, 'alcance_efectivo_m': al})

@app.route('/api/inventario/equipos/<int:eid>/fisico', methods=['PUT'])
@login_required
def equipo_fisico_set(eid):
    """Crea o actualiza los datos físicos de un equipo (upsert)."""
    d = request.get_json() or {}
    con = get_db()
    if not con.execute("SELECT 1 FROM torre_equipos WHERE id=?", (eid,)).fetchone():
        con.close(); return jsonify({'error': 'Equipo no encontrado'}), 404
    campos = ['perfil_radio_id','azimut','apertura_h_override','apertura_v_override',
              'alcance_override_m','altura_m','tilt','polarizacion','mostrar_cobertura','fuente']
    existe = con.execute("SELECT 1 FROM equipo_radio_fisico WHERE equipo_id=?", (eid,)).fetchone()
    if existe:
        sets = ','.join(f"{c}=?" for c in campos)
        vals = [d.get(c) for c in campos] + [eid]
        con.execute(f"UPDATE equipo_radio_fisico SET {sets}, actualizado=datetime('now','localtime') WHERE equipo_id=?", vals)
    else:
        cols = ['equipo_id'] + campos
        vals = [eid] + [d.get(c) for c in campos]
        ph = ','.join('?' * len(cols))
        con.execute(f"INSERT INTO equipo_radio_fisico({','.join(cols)}) VALUES({ph})", vals)
    con.commit(); con.close()
    return jsonify({'ok': True})

# ══════════ CAPACIDAD / SATURACIÓN DE APs (Prioridad 2) ══════════
def _metricas_ap(con, equipo_id, rssi_pobre=-75, rssi_buena=-65):
    """Métricas actuales de un AP a partir de datos ya persistidos:
    clientes ligados por SNMP + su RSSI más reciente. No parsea texto.
    Devuelve (clientes, rssi_promedio, pct_pobre, distribucion)."""
    filas = con.execute("""
        SELECT c.id,
               (SELECT h.nivel_dbm FROM historial_senal_cliente h
                WHERE h.cliente_id=c.id AND h.source='snmp'
                ORDER BY h.fecha DESC, h.id DESC LIMIT 1) AS rssi
        FROM clientes c
        WHERE c.ap_snmp_id=? AND c.estado='activo'""", (equipo_id,)).fetchall()
    clientes = len(filas)
    rssis = [f['rssi'] for f in filas if f['rssi'] is not None]
    rssi_prom = round(sum(rssis) / len(rssis), 1) if rssis else None
    pct_pobre = round(sum(1 for r in rssis if r < rssi_pobre) / len(rssis) * 100, 1) if rssis else None
    # Desglose para el mosaico: cuántos clientes en cada franja de señal
    dist = {
        'buena': sum(1 for r in rssis if r >= rssi_buena),
        'media': sum(1 for r in rssis if rssi_pobre <= r < rssi_buena),
        'pobre': sum(1 for r in rssis if r < rssi_pobre),
        'sin_dato': clientes - len(rssis),
    }
    return clientes, rssi_prom, pct_pobre, dist


@app.route('/api/capacidad/aps')
@login_required
def capacidad_aps():
    """Matriz de capacidad/saturación de todos los APs, para el dashboard wireless.
    Combina clientes por AP + señal + perfil técnico. APs sin perfil muestran la
    saturación como 'No disponible' (no se inventa)."""
    import capacidad
    con = get_db()
    aps = con.execute("""
        SELECT eq.id, eq.modelo, eq.tipo, eq.snmp_estado, eq.ultimo_snmp, eq.torre_id,
               t.nombre AS torre_nombre,
               f.perfil_radio_id
        FROM torre_equipos eq
        LEFT JOIN torres t ON t.id = eq.torre_id
        LEFT JOIN equipo_radio_fisico f ON f.equipo_id = eq.id
        WHERE eq.es_ap=1 AND eq.estado!='de_baja'
        ORDER BY t.nombre, eq.modelo""").fetchall()
    # Perfiles cacheados
    perfiles = {p['id']: dict(p) for p in con.execute("SELECT * FROM perfil_radio").fetchall()}
    resultado = []
    para_dist = []
    for ap in aps:
        clientes, rssi_prom, pct_pobre, dist = _metricas_ap(con, ap['id'])
        perfil = perfiles.get(ap['perfil_radio_id'])
        # 'sin_snmp' = el equipo responde ping pero su agente SNMP no contesta.
        # No es lo mismo que caído: se muestra distinto en el mosaico.
        snmp_ok = (ap['snmp_estado'] == 'online')
        ev = capacidad.evaluar_ap(clientes, perfil, rssi_prom, pct_pobre, snmp_ok)
        fila = {
            'equipo_id': ap['id'], 'modelo': ap['modelo'] or ap['tipo'],
            'torre_id': ap['torre_id'], 'torre_nombre': ap['torre_nombre'],
            'tiene_perfil': perfil is not None,
            'ultimo_snmp': ap['ultimo_snmp'],
            'snmp_estado': ap['snmp_estado'],
            'distribucion': dist,
            'rssi_promedio': rssi_prom,
            'recomendados': (perfil or {}).get('clientes_recomendados'),
            'maximo': (perfil or {}).get('clientes_max_operativo'),
            'umbral_advertencia': (perfil or {}).get('umbral_advertencia') or 80,
            **ev,
        }
        resultado.append(fila)
        para_dist.append({'equipo_id': ap['id'], 'torre_id': ap['torre_id'], 'clientes': clientes})
    con.close()
    # Marcar APs con distribución desbalanceada dentro de su torre
    desbal = capacidad.distribucion_desbalanceada(para_dist)
    for f in resultado:
        f['desbalanceado'] = f['equipo_id'] in desbal
    # Resumen para tarjetas
    resumen = {
        'total': len(resultado),
        'criticos': sum(1 for f in resultado if f['estado'] == 'critico'),
        'advertencia': sum(1 for f in resultado if f['estado'] == 'advertencia'),
        'normal': sum(1 for f in resultado if f['estado'] == 'normal'),
        'sin_datos': sum(1 for f in resultado if f['estado'] == 'sin_datos'),
        'desbalanceados': len(desbal),
    }
    return jsonify({'aps': resultado, 'resumen': resumen})

@app.route('/api/cobertura/sectores')
@login_required
def cobertura_sectores():
    """Datos para el MAPA de cobertura teórica (Prioridad 5):
    por cada AP con 'mostrar_cobertura', su sector geométrico + estado de capacidad.
    El centro es la ubicación de la torre. Sin lat/lng o sin datos físicos → se omite."""
    import cobertura, capacidad
    con = get_db()
    perfiles = {p['id']: dict(p) for p in con.execute("SELECT * FROM perfil_radio").fetchall()}
    filas = con.execute("""
        SELECT eq.id, eq.modelo, eq.tipo, eq.snmp_estado, eq.torre_id,
               t.nombre AS torre_nombre, t.lat, t.lng,
               f.azimut, f.apertura_h_override, f.alcance_override_m, f.perfil_radio_id,
               f.mostrar_cobertura
        FROM torre_equipos eq
        JOIN equipo_radio_fisico f ON f.equipo_id = eq.id
        LEFT JOIN torres t ON t.id = eq.torre_id
        WHERE eq.es_ap=1 AND eq.estado!='de_baja' AND COALESCE(f.mostrar_cobertura,0)=1""").fetchall()
    sectores = []
    omitidos = []
    for r in filas:
        perfil = perfiles.get(r['perfil_radio_id'])
        # apertura/alcance efectivos (override del equipo o del perfil)
        apertura = r['apertura_h_override'] if r['apertura_h_override'] is not None else (perfil or {}).get('apertura_horizontal')
        alcance = r['alcance_override_m'] if r['alcance_override_m'] is not None else (perfil or {}).get('alcance_teorico_m')
        if r['lat'] is None or r['lng'] is None:
            omitidos.append({'equipo_id': r['id'], 'motivo': 'La torre no tiene coordenadas'})
            continue
        if r['azimut'] is None or not apertura or not alcance:
            omitidos.append({'equipo_id': r['id'], 'motivo': 'Faltan azimut, apertura o alcance'})
            continue
        geo = cobertura.sector_geojson(r['lat'], r['lng'], r['azimut'], apertura, alcance)
        # estado de capacidad para colorear el sector
        clientes, rssi_prom, pct_pobre, _dist = _metricas_ap(con, r['id'])
        ev = capacidad.evaluar_ap(clientes, perfil, rssi_prom, pct_pobre, r['snmp_estado'] == 'online')
        sectores.append({
            'equipo_id': r['id'], 'modelo': r['modelo'] or r['tipo'],
            'torre_nombre': r['torre_nombre'], 'lat': r['lat'], 'lng': r['lng'],
            'azimut': r['azimut'], 'apertura': apertura, 'alcance_m': alcance,
            'geojson': geo, 'clientes': clientes,
            'estado': ev['estado'], 'color': ev['color'], 'motivo': ev['motivo'],
        })
    # Clientes SNMP-vinculados con coordenadas (capa de puntos del mapa)
    clientes_map = []
    cli_rows = con.execute("""
        SELECT c.id, c.nombre, c.lat, c.lng, c.ap_snmp_id,
               (SELECT h.nivel_dbm FROM historial_senal_cliente h
                WHERE h.cliente_id=c.id AND h.source='snmp'
                ORDER BY h.fecha DESC, h.id DESC LIMIT 1) AS rssi
        FROM clientes c
        WHERE c.estado='activo' AND c.ap_snmp_id IS NOT NULL
          AND c.lat IS NOT NULL AND c.lng IS NOT NULL AND c.lat != 0 AND c.lng != 0""").fetchall()
    for c in cli_rows:
        rssi = c['rssi']
        if rssi is None:
            senal = 'sin_datos'
        elif rssi >= -65:
            senal = 'buena'
        elif rssi >= -75:
            senal = 'media'
        else:
            senal = 'pobre'
        clientes_map.append({'id': c['id'], 'nombre': c['nombre'], 'lat': c['lat'], 'lng': c['lng'],
                             'ap_snmp_id': c['ap_snmp_id'], 'rssi': rssi, 'senal': senal})
    con.close()
    return jsonify({'sectores': sectores, 'omitidos': omitidos, 'clientes': clientes_map})

@app.route('/api/inventario/equipos_con_torre')
@login_required
def inventario_equipos_con_torre():
    """Lista plana de equipos con su torre, para elegir extremos de enlaces."""
    con = get_db()
    filas = con.execute("""SELECT eq.id, eq.tipo, eq.modelo, eq.ip, eq.mac, eq.torre_id,
                                  t.nombre AS torre_nombre
                           FROM torre_equipos eq LEFT JOIN torres t ON t.id = eq.torre_id
                           WHERE eq.estado!='de_baja'
                           ORDER BY t.nombre, eq.modelo""").fetchall()
    con.close()
    return jsonify([dict(f) for f in filas])

@app.route('/api/enlaces')
@login_required
def enlaces_listar():
    con = get_db()
    filas = con.execute("SELECT * FROM enlaces ORDER BY id DESC").fetchall()
    out = []
    for f in filas:
        d = dict(f)
        d['extremo_a'] = _equipo_resumen(con, f['equipo_a_id'])
        d['extremo_b'] = _equipo_resumen(con, f['equipo_b_id'])
        out.append(d)
    con.close()
    return jsonify(out)

@app.route('/api/enlaces', methods=['POST'])
@login_required
def enlaces_crear():
    d = request.get_json() or {}
    if not d.get('equipo_a_id') or not d.get('equipo_b_id'):
        return jsonify({'error': 'Elegí los dos extremos del enlace'}), 400
    if d.get('equipo_a_id') == d.get('equipo_b_id'):
        return jsonify({'error': 'Los dos extremos no pueden ser el mismo equipo'}), 400
    con = get_db()
    cur = con.execute("""INSERT INTO enlaces(nombre, equipo_a_id, equipo_b_id, estado, observaciones)
                         VALUES(?,?,?,?,?)""",
                      (d.get('nombre'), d['equipo_a_id'], d['equipo_b_id'],
                       d.get('estado', 'activo'), d.get('observaciones')))
    con.commit(); eid = cur.lastrowid; con.close()
    return jsonify({'ok': True, 'id': eid})

@app.route('/api/enlaces/<int:lid>', methods=['PUT'])
@login_required
def enlaces_editar(lid):
    d = request.get_json() or {}
    con = get_db()
    con.execute("""UPDATE enlaces SET nombre=?, equipo_a_id=?, equipo_b_id=?, estado=?, observaciones=?
                   WHERE id=?""",
                (d.get('nombre'), d.get('equipo_a_id'), d.get('equipo_b_id'),
                 d.get('estado', 'activo'), d.get('observaciones'), lid))
    con.commit(); con.close()
    return jsonify({'ok': True})

@app.route('/api/enlaces/<int:lid>', methods=['DELETE'])
@login_required
def enlaces_borrar(lid):
    con = get_db()
    con.execute("DELETE FROM enlaces WHERE id=?", (lid,))
    con.commit(); con.close()
    return jsonify({'ok': True})

def _sondear_extremo(con, eid):
    """Sondea un extremo de enlace: señal de radio + interfaces LAN. Corre en el host."""
    e = con.execute("SELECT * FROM torre_equipos WHERE id=?", (eid,)).fetchone()
    if not e:
        return {'error': 'equipo no encontrado'}
    ip = e['snmp_ip'] or e['ip']
    if not ip:
        return {'error': 'sin IP'}
    fab = (e['snmp_fabricante'] or e['fabricante'] or 'ubiquiti').lower()
    comm = e['snmp_community'] or 'public'
    ver = e['snmp_version'] or '1'
    import snmp_wireless
    out = {'equipo_id': eid, 'ip': ip}
    try:
        radio = snmp_wireless.poll(ip, fab, comm, ver)
        dev = radio.get('device', {})
        out['device'] = dev
        out['snmp_ok'] = bool(dev.get('mac') or radio.get('estaciones'))
    except Exception as ex:
        out['device'] = {}; out['snmp_ok'] = False; out['error_radio'] = str(ex)[:120]
    try:
        ifdata = snmp_wireless.walk_ifmib(ip, comm, ver)
        out['lan'] = ifdata.get('lan', [])
        out['lan_alerta'] = ifdata.get('lan_alerta')
    except Exception as ex:
        out['lan'] = []; out['lan_alerta'] = None; out['error_lan'] = str(ex)[:120]
    return out

@app.route('/api/enlaces/<int:lid>/estado')
@login_required
def enlaces_estado(lid):
    """Sondea ambos extremos del enlace EN VIVO y devuelve señal + LAN de cada uno,
    marcando qué extremo tiene el problema de 10 Mbps si lo hubiera."""
    con = get_db()
    l = con.execute("SELECT * FROM enlaces WHERE id=?", (lid,)).fetchone()
    if not l:
        con.close(); return jsonify({'error': 'Enlace no encontrado'}), 404
    a = _sondear_extremo(con, l['equipo_a_id'])
    b = _sondear_extremo(con, l['equipo_b_id'])
    con.close()
    # ¿Qué extremo tiene la alerta de LAN a 10 Mbps?
    extremos_con_alerta = []
    if a.get('lan_alerta'):
        extremos_con_alerta.append('A')
    if b.get('lan_alerta'):
        extremos_con_alerta.append('B')
    return jsonify({
        'enlace_id': lid, 'nombre': l['nombre'],
        'extremo_a': a, 'extremo_b': b,
        'alerta_lan_en': extremos_con_alerta,
    })

@app.route('/api/inventario/detectar', methods=['POST'])
@login_required
def inventario_detectar_snmp():
    """Descubrimiento SNMP para autocompletar el alta de un equipo, ANTES de guardarlo.
    Body: {ip, community, version, fabricante?}. Corre en el host de Pucará
    (sirve si Pucará llega al equipo por la VPN). Devuelve datos detectados;
    el frontend decide qué campos completar sin pisar lo cargado a mano."""
    d = request.get_json() or {}
    ip = (d.get('ip') or '').strip()
    if not ip:
        return jsonify({'ok': False, 'error': 'Falta la IP'}), 400
    community = (d.get('community') or 'public').strip()
    version = str(d.get('version') or '1').strip()
    fabricante = (d.get('fabricante') or '').strip() or None
    try:
        import snmp_wireless
        res = snmp_wireless.discover(ip, community, version, fabricante)
    except Exception as ex:
        return jsonify({'ok': False, 'error': str(ex)[:200]}), 500
    return jsonify(res)

@app.route('/api/inventario/equipos/<int:eid>/interfaces')
@login_required
def inventario_interfaces_lan(eid):
    """Consulta EN VIVO las interfaces LAN (IF-MIB) de un equipo guardado.
    Detecta el estado de cada puerto ethernet y la condición de 10 Mbps."""
    con = get_db()
    e = con.execute("SELECT * FROM torre_equipos WHERE id=?", (eid,)).fetchone()
    con.close()
    if not e:
        return jsonify({'error': 'Equipo no encontrado'}), 404
    ip = e['snmp_ip'] or e['ip']
    if not ip:
        return jsonify({'error': 'El equipo no tiene IP para sondear'}), 400
    comm = e['snmp_community'] or 'public'
    ver = e['snmp_version'] or '1'
    try:
        import snmp_wireless
        data = snmp_wireless.walk_ifmib(ip, comm, ver)
    except Exception as ex:
        return jsonify({'error': str(ex)[:200]}), 500
    return jsonify(data)

@app.route('/api/inventario/equipos/<int:eid>/snmp_test')
@login_required
def inventario_snmp_test(eid):
    """Sondeo SNMP EN VIVO de un equipo (para el botón de la UI). Corre en el
    host de Pucará: sirve si Pucará llega al equipo; si no, usar el poller en la VM."""
    con = get_db()
    e = con.execute("SELECT * FROM torre_equipos WHERE id=?", (eid,)).fetchone()
    con.close()
    if not e:
        return jsonify({'error': 'Equipo no encontrado'}), 404
    ip = e['snmp_ip'] or e['ip']
    if not ip:
        return jsonify({'error': 'El equipo no tiene IP para sondear'}), 400
    fab = (e['snmp_fabricante'] or e['fabricante'] or 'ubiquiti').lower()
    comm = e['snmp_community'] or 'public'
    try:
        import snmp_wireless
        data = snmp_wireless.poll(ip, fab, comm)
    except Exception as ex:
        return jsonify({'error': str(ex)}), 500
    # anexar cuántas estaciones cruzarían con clientes
    if data.get('estaciones'):
        con = get_db()
        for est in data['estaciones']:
            cid, crit = snmp_wireless.match_cliente(est, con)
            est['cliente_id'] = cid; est['match'] = crit
        con.close()
    return jsonify(data)

@app.route('/api/torres', methods=['POST'])
@login_required
def crear_torre():
    d = request.get_json()
    con = get_db()
    cur = con.execute("""
        INSERT INTO torres(nombre,localidad,direccion,lat,lng,ip_equipos,orientaciones,
        altura_mts,tipo,estado,torre_padre_id,observaciones,proveedor)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (d.get('nombre'),d.get('localidad'),d.get('direccion'),d.get('lat'),d.get('lng'),
          d.get('ip_equipos'),d.get('orientaciones'),d.get('altura_mts'),
          d.get('tipo','repetidora'),d.get('estado','activa'),
          d.get('torre_padre_id'),d.get('observaciones'),d.get('proveedor')))
    con.commit(); con.close()
    log('alta','Torre creada: '+d.get('nombre',''),'','torres')
    return jsonify({'ok':True,'id':cur.lastrowid})

@app.route('/api/torres/<int:tid>', methods=['PUT'])
@login_required
def editar_torre(tid):
    d = request.get_json()
    con = get_db()
    campos = ['nombre','localidad','direccion','lat','lng','ip_equipos','orientaciones',
              'altura_mts','tipo','estado','torre_padre_id','observaciones',
              'requiere_revision','motivos_revision','proveedor']
    sets = []
    vals = []
    for c in campos:
        if c in d:
            sets.append(f"{c}=?")
            vals.append(d[c])
    if not sets:
        con.close()
        return jsonify({'error':'nada que actualizar'}), 400
    vals.append(tid)
    con.execute(f"UPDATE torres SET {','.join(sets)} WHERE id=?", vals)
    con.commit(); con.close()
    log('mod','Torre editada','','torres')
    return jsonify({'ok':True})

@app.route('/api/torres/<int:tid>', methods=['DELETE'])
@login_required
@admin_required
def borrar_torre(tid):
    con = get_db()
    con.execute("DELETE FROM torres WHERE id=?", (tid,))
    con.commit(); con.close()
    log('baja','Torre eliminada','','torres')
    return jsonify({'ok':True})

# ─── SYNC ERP ─────────────────────────────────────────────────────
@app.route('/api/sync/status')
@login_required
def sync_status():
    """Estado de sync para el panel."""
    con = get_db()
    # Último sync
    row = con.execute("SELECT * FROM sync_log ORDER BY id DESC LIMIT 1").fetchone()
    # Historial últimos 20
    history = con.execute("SELECT * FROM sync_log ORDER BY id DESC LIMIT 20").fetchall()
    con.close()

    def _fmt_row(r):
        if not r: return None
        d = dict(r)
        estado = 'ok' if not d.get('errores') else ('parcial' if d.get('clientes_actualizados',0) > 0 else 'error')
        resumen = json.dumps({'clientes': {
            'actualizados': d.get('clientes_actualizados', 0),
            'nuevos': d.get('clientes_nuevos', 0),
            'duracion_seg': d.get('duracion_seg', 0),
        }})
        return {
            'fecha_inicio': d.get('fecha'),
            'estado': estado,
            'duracion_seg': d.get('duracion_seg'),
            'errores': d.get('errores'),
            'iniciado_por': d.get('iniciado_por', 'manual'),
            'resumen': resumen,
        }

    return jsonify({
        'last': _fmt_row(row),
        'history': [_fmt_row(r) for r in history],
    })

@app.route('/api/sync/run', methods=['POST'])
@login_required
@requiere_flag('puede_sync')
def run_sync():
    """Ejecuta sync ERP → SQLite."""
    try:
        import subprocess, sys
        script = os.path.join(os.path.dirname(__file__), 'sync_pg.py')
        if not os.path.exists(script):
            return jsonify({'error':'sync_pg.py no encontrado'}), 404

        d = request.get_json(silent=True) or {}
        cmd = [sys.executable, script]
        if d.get('dry_run'):
            cmd.append('--dry-run')

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        output = result.stdout + result.stderr
        ok = result.returncode == 0

        # Parsear resultado del último sync_log
        con = get_db()
        row = con.execute("SELECT * FROM sync_log ORDER BY id DESC LIMIT 1").fetchone()
        con.close()

        if row:
            r = dict(row)
            estado = 'ok' if ok and not r.get('errores') else 'error'
            return jsonify({
                'estado': estado,
                'duracion_seg': r.get('duracion_seg', 0),
                'errores': [r['errores']] if r.get('errores') else [],
                'modulos': {'clientes': {
                    'actualizados': r.get('clientes_actualizados', 0),
                    'nuevos': r.get('clientes_nuevos', 0),
                }}
            })
        else:
            return jsonify({'estado': 'ok' if ok else 'error', 'output': output[-2000:]})

    except subprocess.TimeoutExpired:
        return jsonify({'error':'Timeout — sync tardó más de 180 segundos'}), 504
    except Exception as e:
        return jsonify({'error':str(e)}), 500

@app.route('/api/sync/test_pg')
@login_required
def test_pg():
    """Test de conexión a PostgreSQL."""
    try:
        import subprocess, sys
        script = os.path.join(os.path.dirname(__file__), 'sync_pg.py')
        result = subprocess.run(
            [sys.executable, script, '--test'],
            capture_output=True, text=True, timeout=15
        )
        ok = result.returncode == 0
        return jsonify({'ok': ok, 'output': result.stdout + result.stderr})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})

@app.route('/api/sync/clientes_pte_erp')
@login_required
def clientes_pte_erp():
    """Clientes creados en NetAdmin pero sin nro_cliente (no están en el ERP)."""
    con = get_db()
    rows = con.execute("""
        SELECT id, nombre, dni, fecha_alta, estado
        FROM clientes
        WHERE (nro_cliente IS NULL OR nro_cliente = '')
        ORDER BY fecha_alta DESC
        LIMIT 50
    """).fetchall()
    con.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/sync/clientes_pte_erp/<int:cid>/marcar_cargado', methods=['POST'])
@login_required
def marcar_cargado_erp(cid):
    """Marcar un cliente local como ya cargado al ERP (poner nro_cliente manual)."""
    d = request.get_json(silent=True) or {}
    nro = d.get('nro_cliente', '')
    con = get_db()
    if nro:
        con.execute("UPDATE clientes SET nro_cliente=? WHERE id=?", (nro, cid))
    else:
        # Si no mandan nro, marcar con un placeholder para sacarlo de pendientes
        con.execute("UPDATE clientes SET nro_cliente=? WHERE id=?", (f'LOCAL-{cid}', cid))
    con.commit()
    con.close()
    return jsonify({'ok': True})

# ─── MÓDULO FINANCIERO ─────────────────────────────────────────────
@app.route('/api/finanzas/resumen')
@login_required
def finanzas_resumen():
    con = get_db()
    ingreso = con.execute("SELECT COALESCE(SUM(precio),0) FROM clientes WHERE estado='activo' AND precio > 0").fetchone()[0]
    activos_con_precio = con.execute("SELECT COUNT(*) FROM clientes WHERE estado='activo' AND precio > 0").fetchone()[0]
    ticket_prom = round(ingreso / activos_con_precio, 2) if activos_con_precio else 0
    ingreso_fibra = con.execute("SELECT COALESCE(SUM(precio),0) FROM clientes WHERE estado='activo' AND tipo_servicio='fibra' AND precio > 0").fetchone()[0]
    ingreso_inal = con.execute("SELECT COALESCE(SUM(precio),0) FROM clientes WHERE estado='activo' AND tipo_servicio='inalambrico' AND precio > 0").fetchone()[0]
    deuda = con.execute("SELECT COALESCE(SUM(precio),0) FROM clientes WHERE estado='suspendido' AND precio > 0").fetchone()[0]
    suspendidos = con.execute("SELECT COUNT(*) FROM clientes WHERE estado='suspendido'").fetchone()[0]
    morosos = con.execute("SELECT COUNT(*) FROM clientes WHERE estado='activo' AND ultimo_pago IS NOT NULL AND ultimo_pago < date('now','localtime','-35 day')").fetchone()[0]
    morosos_monto = con.execute("SELECT COALESCE(SUM(precio),0) FROM clientes WHERE estado='activo' AND ultimo_pago IS NOT NULL AND ultimo_pago < date('now','localtime','-35 day')").fetchone()[0]
    perdido = con.execute("SELECT COALESCE(SUM(precio),0) FROM clientes WHERE estado IN ('rescision','pte_rescision') AND precio > 0").fetchone()[0]
    con.close()
    return jsonify({
        'ingreso_mensual': round(ingreso, 2), 'ingreso_fibra': round(ingreso_fibra, 2),
        'ingreso_inalambrico': round(ingreso_inal, 2), 'ticket_promedio': ticket_prom,
        'activos_con_precio': activos_con_precio, 'deuda_suspendidos': round(deuda, 2),
        'suspendidos': suspendidos, 'morosos': morosos,
        'morosos_monto': round(morosos_monto, 2), 'ingreso_perdido_rescision': round(perdido, 2),
    })

@app.route('/api/finanzas/morosidad')
@login_required
def finanzas_morosidad():
    con = get_db()
    campo = request.args.get('agrupar', 'localidad')
    if campo not in ('localidad','plan','tipo_servicio'): campo = 'localidad'
    rows = con.execute(f"""
        SELECT {campo} as grupo, COUNT(*) as total,
            SUM(CASE WHEN ultimo_pago IS NOT NULL AND ultimo_pago < date('now','localtime','-35 day') THEN 1 ELSE 0 END) as morosos,
            SUM(CASE WHEN ultimo_pago IS NOT NULL AND ultimo_pago < date('now','localtime','-35 day') THEN precio ELSE 0 END) as monto_moroso,
            COALESCE(SUM(precio),0) as ingreso_total
        FROM clientes WHERE estado='activo' AND precio > 0
        AND {campo} IS NOT NULL AND {campo} != '' GROUP BY {campo} ORDER BY morosos DESC
    """).fetchall()
    con.close()
    return jsonify([{'grupo':r['grupo'],'total':r['total'],'morosos':r['morosos'] or 0,
        'tasa':round((r['morosos'] or 0)/(r['total'] or 1)*100,1),
        'monto_moroso':round(r['monto_moroso'] or 0,2),
        'ingreso_total':round(r['ingreso_total'],2)} for r in rows])

@app.route('/api/finanzas/evolucion')
@login_required
def finanzas_evolucion():
    """Ingresos (mes anterior / actual / proyección) y bajas con pérdida de ingreso.
    - Meses pasados: estimación = clientes activos en ese mes × su abono.
    - De ahora en más: usa el snapshot real de facturacion_mensual si existe.
    - Proyección mes siguiente: promedio de los últimos 3 meses.
    """
    con = get_db()
    _registrar_snapshot_si_falta(con)

    def mes_offset(n):
        return con.execute(f"SELECT strftime('%Y-%m', date('now','localtime','start of month','{n:+d} month'))").fetchone()[0]

    mes_actual = mes_offset(0)
    mes_anterior = mes_offset(-1)
    mes_siguiente = mes_offset(1)

    def ingreso_estimado_mes(mes):
        """Ingreso del mes: dato real de facturacion_mensual si existe,
        sino estimación basada en la base activa actual (más estable)."""
        snap = con.execute("SELECT ingreso_total, cobrado FROM facturacion_mensual WHERE mes=?", (mes,)).fetchone()
        if snap and snap[0]:
            return round(snap[0], 2), 'real'
        # Estimación de respaldo: ingreso de la base activa actual.
        # No filtramos por fecha_instalacion porque muchos clientes no la tienen
        # cargada, lo que distorsionaba el cálculo. Usamos la foto actual.
        total = con.execute(
            "SELECT COALESCE(SUM(precio),0) FROM clientes WHERE estado='activo' AND precio > 0"
        ).fetchone()[0]
        return round(total, 2), 'estimado'

    ing_actual, tipo_actual = ingreso_estimado_mes(mes_actual)
    ing_anterior, tipo_anterior = ingreso_estimado_mes(mes_anterior)

    # Proyección = promedio de últimos 3 meses
    ult3 = [ingreso_estimado_mes(mes_offset(-k))[0] for k in (1, 2, 3)]
    proyeccion = round(sum(ult3) / 3, 2) if ult3 else 0

    # Bajas: mes anterior (completo) y mes actual (hasta hoy) + pérdida de ingreso
    def bajas_mes(mes, hasta_hoy=False):
        sql = """SELECT COUNT(*) c, COALESCE(SUM(precio),0) perdida FROM clientes
                 WHERE fecha_rescision IS NOT NULL AND fecha_rescision != ''
                 AND strftime('%Y-%m', fecha_rescision)=?"""
        params = [mes]
        if hasta_hoy:
            sql += " AND fecha_rescision <= date('now','localtime')"
        r = con.execute(sql, params).fetchone()
        return {'cantidad': r['c'], 'perdida_ingreso': round(r['perdida'], 2)}

    bajas_anterior = bajas_mes(mes_anterior)
    bajas_actual = bajas_mes(mes_actual, hasta_hoy=True)

    # Serie de 12 meses (altas vs bajas) para el gráfico
    meses = []
    for i in range(11, -1, -1):
        mes = mes_offset(-i)
        altas = con.execute("""SELECT COUNT(*) FROM clientes
            WHERE fecha_instalacion IS NOT NULL AND strftime('%Y-%m', fecha_instalacion)=?""", (mes,)).fetchone()[0]
        bajas = con.execute("""SELECT COUNT(*) FROM clientes
            WHERE fecha_rescision IS NOT NULL AND strftime('%Y-%m', fecha_rescision)=?""", (mes,)).fetchone()[0]
        meses.append({'mes': mes, 'altas': altas, 'bajas': bajas, 'neto': altas - bajas})

    # Serie de facturación real (de facturacion_mensual) últimos 12 meses
    facturacion = []
    for i in range(11, -1, -1):
        mes = mes_offset(-i)
        r = con.execute("SELECT ingreso_total, cobrado FROM facturacion_mensual WHERE mes=?", (mes,)).fetchone()
        if r and r['ingreso_total']:
            facturacion.append({'mes': mes, 'facturado': round(r['ingreso_total'],2),
                                'cobrado': round(r['cobrado'],2) if r['cobrado'] else None})

    con.close()
    return jsonify({
        'ingresos': {
            'mes_anterior': {'mes': mes_anterior, 'monto': ing_anterior, 'tipo': tipo_anterior},
            'mes_actual': {'mes': mes_actual, 'monto': ing_actual, 'tipo': tipo_actual},
            'proyeccion_siguiente': {'mes': mes_siguiente, 'monto': proyeccion, 'metodo': 'promedio 3 meses'},
        },
        'bajas': {
            'mes_anterior': {'mes': mes_anterior, **bajas_anterior},
            'mes_actual': {'mes': mes_actual, **bajas_actual},
        },
        'facturacion_real': facturacion,
        'meses': meses,
    })

def _registrar_snapshot_si_falta(con):
    """Guarda el snapshot de facturación del mes actual si todavía no existe.
    Así de ahora en más queda el histórico real de cada mes."""
    mes = con.execute("SELECT strftime('%Y-%m', date('now','localtime'))").fetchone()[0]
    existe = con.execute("SELECT 1 FROM facturacion_mensual WHERE mes=?", (mes,)).fetchone()
    if existe:
        return
    tot = con.execute("SELECT COUNT(*), COALESCE(SUM(precio),0) FROM clientes WHERE estado='activo' AND precio>0").fetchone()
    fib = con.execute("SELECT COALESCE(SUM(precio),0) FROM clientes WHERE estado='activo' AND tipo_servicio='fibra' AND precio>0").fetchone()[0]
    ina = con.execute("SELECT COALESCE(SUM(precio),0) FROM clientes WHERE estado='activo' AND tipo_servicio='inalambrico' AND precio>0").fetchone()[0]
    con.execute("""INSERT INTO facturacion_mensual(mes, clientes_activos, ingreso_total, ingreso_fibra, ingreso_inalambrico, registrado)
                   VALUES(?,?,?,?,?,datetime('now','localtime'))""",
                (mes, tot[0], round(tot[1], 2), round(fib, 2), round(ina, 2)))
    con.commit()

@app.route('/api/finanzas/top_planes')
@login_required
def finanzas_top_planes():
    con = get_db()
    rows = con.execute("SELECT plan, COUNT(*) as clientes, COALESCE(SUM(precio),0) as ingreso, AVG(precio) as precio_prom FROM clientes WHERE estado='activo' AND plan IS NOT NULL AND plan != '' GROUP BY plan ORDER BY ingreso DESC LIMIT 20").fetchall()
    con.close()
    return jsonify([{'plan':r['plan'],'clientes':r['clientes'],'ingreso':round(r['ingreso'],2),'precio_prom':round(r['precio_prom'],2)} for r in rows])

@app.route('/api/finanzas/detalle_morosos')
@login_required
def finanzas_detalle_morosos():
    con = get_db()
    rows = con.execute("""SELECT id, nombre, nro_cliente, telefono, localidad, plan, precio,
        ultimo_pago, tipo_servicio, CAST(julianday('now','localtime') - julianday(ultimo_pago) AS INTEGER) as dias_mora
        FROM clientes WHERE estado='activo' AND ultimo_pago IS NOT NULL AND ultimo_pago < date('now','localtime','-35 day')
        ORDER BY ultimo_pago ASC LIMIT 100""").fetchall()
    con.close()
    return jsonify([dict(r) for r in rows])

# ─── MÉTRICAS AVANZADAS ────────────────────────────────────────────
@app.route('/api/finanzas/churn')
@login_required
def finanzas_churn():
    """Churn rate mensual: clientes que dejaron de ser activos cada mes."""
    con = get_db()
    meses = []
    for i in range(11, -1, -1):
        mes = con.execute(f"SELECT strftime('%Y-%m', date('now','localtime','start of month','-{i} month'))").fetchone()[0]
        mes_ini = mes + '-01'
        # Activos al inicio del mes (fecha_alta antes del mes, no rescindidos/baja antes)
        activos_inicio = con.execute("""
            SELECT COUNT(*) FROM clientes
            WHERE fecha_alta < ? AND (estado='activo'
                OR (estado IN ('suspendido','pte_rescision','rescision') AND fecha_alta < ?))
        """, (mes_ini, mes_ini)).fetchone()[0] or 1
        # Bajas/rescisiones del mes
        bajas_mes = con.execute("""
            SELECT COUNT(*) FROM clientes
            WHERE estado IN ('rescision','pte_rescision','baja')
            AND strftime('%Y-%m', COALESCE(fecha_baja, fecha_alta)) = ?
        """, (mes,)).fetchone()[0]
        # Nuevos suspendidos del mes
        susp_mes = con.execute("""
            SELECT COUNT(*) FROM clientes
            WHERE estado = 'suspendido'
            AND strftime('%Y-%m', COALESCE(fecha_suspension, fecha_alta)) = ?
        """, (mes,)).fetchone()[0]
        # Altas del mes
        altas = con.execute("SELECT COUNT(*) FROM clientes WHERE strftime('%Y-%m', fecha_alta) = ?", (mes,)).fetchone()[0]
        churn = round((bajas_mes + susp_mes) / activos_inicio * 100, 2)
        crecimiento = altas - bajas_mes
        meses.append({
            'mes': mes, 'activos_inicio': activos_inicio,
            'altas': altas, 'bajas': bajas_mes, 'suspensiones': susp_mes,
            'churn_pct': churn, 'crecimiento_neto': crecimiento
        })
    con.close()
    return jsonify(meses)

@app.route('/api/finanzas/ingreso_por_torre')
@login_required
def finanzas_ingreso_torre():
    """Ingreso mensual por torre (clientes inalámbricos)."""
    con = get_db()
    rows = con.execute("""
        SELECT t.id, t.nombre, t.localidad,
            COUNT(c.id) as clientes,
            COALESCE(SUM(c.precio), 0) as ingreso,
            SUM(CASE WHEN c.estado='activo' THEN 1 ELSE 0 END) as activos,
            SUM(CASE WHEN c.estado='suspendido' THEN 1 ELSE 0 END) as suspendidos
        FROM torres t
        LEFT JOIN clientes c ON COALESCE(c.torre_id_snmp, c.torre_id) = t.id AND c.estado != 'baja' AND c.precio > 0
        GROUP BY t.id
        ORDER BY ingreso DESC
    """).fetchall()
    con.close()
    return jsonify([{
        'torre_id': r['id'], 'nombre': r['nombre'], 'localidad': r['localidad'],
        'clientes': r['clientes'], 'activos': r['activos'], 'suspendidos': r['suspendidos'],
        'ingreso': round(r['ingreso'], 2),
        'ingreso_por_cliente': round(r['ingreso'] / r['clientes'], 2) if r['clientes'] else 0
    } for r in rows])

@app.route('/api/finanzas/ingreso_por_olt')
@login_required
def finanzas_ingreso_olt():
    """Ingreso mensual por OLT (clientes de fibra agrupados por olt_nombre)."""
    con = get_db()
    rows = con.execute("""
        SELECT
            COALESCE(NULLIF(c.olt_nombre,''), 'Sin OLT asignada') as olt,
            COUNT(c.id) as clientes,
            COALESCE(SUM(c.precio), 0) as ingreso,
            SUM(CASE WHEN c.estado='activo' THEN 1 ELSE 0 END) as activos,
            SUM(CASE WHEN c.estado='suspendido' THEN 1 ELSE 0 END) as suspendidos
        FROM clientes c
        WHERE c.estado != 'baja' AND c.precio > 0
          AND (c.tipo_servicio='fibra' OR c.olt_nombre IS NOT NULL AND c.olt_nombre != '')
        GROUP BY olt
        ORDER BY ingreso DESC
    """).fetchall()
    con.close()
    return jsonify([{
        'olt': r['olt'],
        'clientes': r['clientes'], 'activos': r['activos'], 'suspendidos': r['suspendidos'],
        'ingreso': round(r['ingreso'], 2),
        'ingreso_por_cliente': round(r['ingreso'] / r['clientes'], 2) if r['clientes'] else 0
    } for r in rows])

@app.route('/api/finanzas/ingreso_por_nap')
@login_required
def finanzas_ingreso_nap():
    """Ingreso y ocupación por NAP."""
    con = get_db()
    rows = con.execute("""
        SELECT n.nombre, n.capacidad, n.localidad, n.red,
            COUNT(c.id) as ocupacion,
            SUM(CASE WHEN c.estado='activo' THEN 1 ELSE 0 END) as activos,
            SUM(CASE WHEN c.estado='suspendido' THEN 1 ELSE 0 END) as suspendidos,
            COALESCE(SUM(CASE WHEN c.estado='activo' THEN c.precio ELSE 0 END), 0) as ingreso
        FROM naps n
        LEFT JOIN clientes c ON c.nap = n.nombre AND c.estado != 'baja'
        GROUP BY n.nombre
        ORDER BY ingreso DESC
    """).fetchall()
    con.close()
    return jsonify([{
        'nombre': r['nombre'], 'capacidad': r['capacidad'] or NAP_LIMIT,
        'localidad': r['localidad'], 'red': r['red'],
        'ocupacion': r['ocupacion'], 'activos': r['activos'], 'suspendidos': r['suspendidos'],
        'libre': (r['capacidad'] or NAP_LIMIT) - r['ocupacion'],
        'ingreso': round(r['ingreso'], 2),
        'ingreso_por_puerto': round(r['ingreso'] / r['ocupacion'], 2) if r['ocupacion'] else 0,
        'pct_ocupacion': round(r['ocupacion'] / (r['capacidad'] or NAP_LIMIT) * 100, 1)
    } for r in rows])

@app.route('/api/finanzas/funnel_instalacion')
@login_required
def finanzas_funnel():
    """Funnel: Pte.Instalación → Activo, tiempos y conversión."""
    con = get_db()
    pte_inst = con.execute("SELECT COUNT(*) FROM clientes WHERE estado='pte_instalacion'").fetchone()[0]
    pte_calc = con.execute("SELECT COUNT(*) FROM clientes WHERE estado='pte_calculo'").fetchone()[0]
    borrador = con.execute("SELECT COUNT(*) FROM clientes WHERE estado='borrador'").fetchone()[0]
    pte_cambio = con.execute("SELECT COUNT(*) FROM clientes WHERE estado='pte_cambio'").fetchone()[0]
    # Conversiones últimos 90 días (clientes que pasaron a activo recientemente)
    conv_90d = con.execute("""
        SELECT COUNT(*) FROM clientes
        WHERE estado='activo' AND fecha_alta >= date('now','localtime','-90 day')
    """).fetchone()[0]
    # Tiempo promedio de alta (fecha_alta de los últimos activos)
    # No tenemos fecha de solicitud vs fecha_alta, usamos lo que hay
    activos_recientes = con.execute("""
        SELECT fecha_alta FROM clientes
        WHERE estado='activo' AND fecha_alta >= date('now','localtime','-90 day')
        AND fecha_alta IS NOT NULL
    """).fetchall()
    # Equipos pendientes de retiro (rescindidos con equipo)
    equipos_pend = con.execute("""
        SELECT COUNT(*) FROM clientes
        WHERE estado IN ('rescision','pte_rescision')
        AND equipo_serie IS NOT NULL AND equipo_serie != ''
    """).fetchone()[0]
    equipos_valor = con.execute("""
        SELECT COUNT(*) FROM clientes
        WHERE estado IN ('rescision','pte_rescision')
        AND equipo_serie IS NOT NULL AND equipo_serie != ''
        AND fecha_alta IS NOT NULL
    """).fetchone()[0]
    con.close()
    return jsonify({
        'funnel': {
            'borrador': borrador, 'pte_calculo': pte_calc,
            'pte_instalacion': pte_inst, 'pte_cambio': pte_cambio,
            'convertidos_90d': conv_90d,
        },
        'equipos_pendientes_retiro': equipos_pend,
        'total_pipeline': borrador + pte_calc + pte_inst + pte_cambio,
    })

@app.route('/api/finanzas/instalaciones_metricas')
@login_required
def finanzas_instalaciones_metricas():
    """Instalaciones realizadas: demora promedio (Fibra vs Inalámbrico),
    cantidad por mes, y ranking de vendedores."""
    con = get_db()

    # Instalaciones realizadas = tipo instalacion con fecha de realización
    base = """FROM servicios
              WHERE tipo='instalacion'
              AND fecha_realizacion_instalacion IS NOT NULL
              AND fecha_realizacion_instalacion != ''
              AND fecha_creacion IS NOT NULL AND fecha_creacion != ''"""

    # Demora promedio en días por medio de transmisión
    demora_rows = con.execute(f"""
        SELECT medio_transmision AS medio,
               COUNT(*) AS cantidad,
               AVG(julianday(fecha_realizacion_instalacion) - julianday(fecha_creacion)) AS demora_prom,
               MIN(julianday(fecha_realizacion_instalacion) - julianday(fecha_creacion)) AS demora_min,
               MAX(julianday(fecha_realizacion_instalacion) - julianday(fecha_creacion)) AS demora_max
        {base}
        GROUP BY medio_transmision
    """).fetchall()
    demoras = []
    for r in demora_rows:
        demoras.append({
            'medio': r['medio'] or 'Sin especificar',
            'cantidad': r['cantidad'],
            'demora_promedio_dias': round(r['demora_prom'], 1) if r['demora_prom'] is not None else None,
            'demora_min_dias': int(r['demora_min']) if r['demora_min'] is not None else None,
            'demora_max_dias': int(r['demora_max']) if r['demora_max'] is not None else None,
        })

    # Instalaciones por mes (últimos 12 meses) según fecha de realización
    por_mes = []
    for i in range(11, -1, -1):
        mes = con.execute(f"SELECT strftime('%Y-%m', date('now','localtime','start of month','-{i} month'))").fetchone()[0]
        n = con.execute(f"""
            SELECT COUNT(*) {base}
            AND strftime('%Y-%m', fecha_realizacion_instalacion)=?
        """, (mes,)).fetchone()[0]
        nf = con.execute(f"""
            SELECT COUNT(*) {base}
            AND strftime('%Y-%m', fecha_realizacion_instalacion)=?
            AND medio_transmision='Fibra óptica'
        """, (mes,)).fetchone()[0]
        ni = con.execute(f"""
            SELECT COUNT(*) {base}
            AND strftime('%Y-%m', fecha_realizacion_instalacion)=?
            AND medio_transmision='Inalámbrico'
        """, (mes,)).fetchone()[0]
        por_mes.append({'mes': mes, 'total': n, 'fibra': nf, 'inalambrico': ni})

    # Ranking de vendedores (quién solicitó/vendió) — desde este mes en adelante.
    # Los datos históricos de vendedores generan ruido hasta tener forma de validarlos.
    mes_actual = con.execute("SELECT strftime('%Y-%m','now','localtime')").fetchone()[0]
    vendedores = con.execute(f"""
        SELECT COALESCE(NULLIF(vendedor,''),'Sin asignar') AS vendedor,
               COUNT(*) AS instalaciones
        {base}
        AND strftime('%Y-%m', fecha_realizacion_instalacion) >= ?
        GROUP BY vendedor ORDER BY instalaciones DESC LIMIT 20
    """, (mes_actual,)).fetchall()

    # Totales
    total_realizadas = con.execute(f"SELECT COUNT(*) {base}").fetchone()[0]
    pendientes = con.execute("SELECT COUNT(*) FROM servicios WHERE tipo='instalacion' AND estado='pendiente'").fetchone()[0]

    con.close()
    return jsonify({
        'total_realizadas': total_realizadas,
        'pendientes': pendientes,
        'demora_por_medio': demoras,
        'por_mes': por_mes,
        'ranking_vendedores': [{'vendedor':r['vendedor'],'instalaciones':r['instalaciones']} for r in vendedores],
    })

@app.route('/api/estadisticas/reclamos_por_medio')
@login_required
def estadisticas_reclamos_por_medio():
    """Compara FTTH vs Inalámbrico en cantidad de servicios técnicos (reclamos
    que requieren visita) y la TASA por cliente activo, para comparar justo."""
    periodo = request.args.get('periodo', '12')  # meses hacia atrás, o 'todo'
    con = get_db()

    # Base de clientes activos por medio (para la tasa)
    base = {}
    for medio_db, label in [('fibra', 'Fibra óptica'), ('inalambrico', 'Inalámbrico')]:
        base[label] = con.execute(
            "SELECT COUNT(*) FROM clientes WHERE estado='activo' AND tipo_servicio=?",
            (medio_db,)
        ).fetchone()[0]

    # Filtro temporal
    filtro_fecha = ""
    params = []
    if periodo != 'todo':
        filtro_fecha = " AND fecha_creacion >= date('now','localtime',?) "
        params.append(f'-{int(periodo)} months')

    # Servicios técnicos por medio (solo los que implican visita: servicio_tecnico)
    resultado = []
    for label in ['Fibra óptica', 'Inalámbrico']:
        n = con.execute(f"""
            SELECT COUNT(*) FROM servicios
            WHERE tipo='servicio_tecnico' AND medio_transmision=? {filtro_fecha}
        """, [label] + params).fetchone()[0]
        clientes = base.get(label, 0) or 1
        resultado.append({
            'medio': label,
            'servicios_tecnicos': n,
            'clientes_activos': base.get(label, 0),
            'tasa_por_100_clientes': round(n / clientes * 100, 1),
        })

    # Evolución mensual por medio (12 meses)
    evolucion = []
    for i in range(11, -1, -1):
        mes = con.execute(f"SELECT strftime('%Y-%m', date('now','localtime','start of month','-{i} month'))").fetchone()[0]
        f = con.execute("""SELECT COUNT(*) FROM servicios WHERE tipo='servicio_tecnico'
            AND medio_transmision='Fibra óptica' AND strftime('%Y-%m',fecha_creacion)=?""", (mes,)).fetchone()[0]
        inal = con.execute("""SELECT COUNT(*) FROM servicios WHERE tipo='servicio_tecnico'
            AND medio_transmision='Inalámbrico' AND strftime('%Y-%m',fecha_creacion)=?""", (mes,)).fetchone()[0]
        evolucion.append({'mes': mes, 'fibra': f, 'inalambrico': inal})

    con.close()
    return jsonify({
        'periodo_meses': periodo,
        'comparativa': resultado,
        'evolucion': evolucion,
    })

@app.route('/api/finanzas/salud_base')
@login_required
def finanzas_salud():
    """Indicadores de salud de la base de clientes."""
    con = get_db()
    total = con.execute("SELECT COUNT(*) FROM clientes WHERE estado NOT IN ('baja')").fetchone()[0] or 1
    activos = con.execute("SELECT COUNT(*) FROM clientes WHERE estado='activo'").fetchone()[0]
    suspendidos = con.execute("SELECT COUNT(*) FROM clientes WHERE estado='suspendido'").fetchone()[0]
    pte_resc = con.execute("SELECT COUNT(*) FROM clientes WHERE estado='pte_rescision'").fetchone()[0]
    rescindidos = con.execute("SELECT COUNT(*) FROM clientes WHERE estado='rescision'").fetchone()[0]
    # Ratio activos/total (salud)
    salud_pct = round(activos / total * 100, 1)
    # Clientes sin coordenadas (no aparecen en mapa)
    sin_coords = con.execute("SELECT COUNT(*) FROM clientes WHERE estado='activo' AND (lat IS NULL OR lat = 0 OR lat = '')").fetchone()[0]
    # Clientes sin email (no se pueden contactar digital)
    sin_email = con.execute("SELECT COUNT(*) FROM clientes WHERE estado='activo' AND (email IS NULL OR email = '')").fetchone()[0]
    # Clientes sin teléfono
    sin_tel = con.execute("SELECT COUNT(*) FROM clientes WHERE estado='activo' AND (telefono IS NULL OR telefono = '')").fetchone()[0]
    # Fibra vs inalámbrico
    fibra = con.execute("SELECT COUNT(*) FROM clientes WHERE estado='activo' AND tipo_servicio='fibra'").fetchone()[0]
    inal = con.execute("SELECT COUNT(*) FROM clientes WHERE estado='activo' AND tipo_servicio='inalambrico'").fetchone()[0]
    # ARPU por tipo
    arpu_fibra = con.execute("SELECT AVG(precio) FROM clientes WHERE estado='activo' AND tipo_servicio='fibra' AND precio > 0").fetchone()[0] or 0
    arpu_inal = con.execute("SELECT AVG(precio) FROM clientes WHERE estado='activo' AND tipo_servicio='inalambrico' AND precio > 0").fetchone()[0] or 0
    # Top 5 localidades
    locs = con.execute("""
        SELECT localidad, COUNT(*) as total,
            SUM(CASE WHEN estado='activo' THEN 1 ELSE 0 END) as activos,
            SUM(CASE WHEN estado='suspendido' THEN 1 ELSE 0 END) as suspendidos,
            SUM(CASE WHEN estado IN ('rescision','pte_rescision') THEN 1 ELSE 0 END) as perdidos,
            COALESCE(SUM(CASE WHEN estado='activo' THEN precio ELSE 0 END),0) as ingreso
        FROM clientes WHERE localidad IS NOT NULL AND localidad != ''
        AND estado != 'baja'
        GROUP BY localidad ORDER BY activos DESC LIMIT 10
    """).fetchall()
    con.close()
    return jsonify({
        'salud_pct': salud_pct,
        'total': total, 'activos': activos, 'suspendidos': suspendidos,
        'pte_rescision': pte_resc, 'rescindidos': rescindidos,
        'sin_coords': sin_coords, 'sin_email': sin_email, 'sin_telefono': sin_tel,
        'fibra': fibra, 'inalambrico': inal,
        'arpu_fibra': round(arpu_fibra, 2), 'arpu_inalambrico': round(arpu_inal, 2),
        'ratio_fibra': round(fibra / (fibra + inal) * 100, 1) if (fibra + inal) else 0,
        'localidades': [dict(r) for r in locs],
    })

# ─── FTTH PLANNING ────────────────────────────────────────────────
@app.route('/api/ftth/rutas')
@login_required
def get_rutas_fibra():
    con = get_db()
    rows = con.execute("SELECT * FROM rutas_fibra ORDER BY creado DESC").fetchall()
    con.close()
    result = []
    for r in rows:
        d = dict(r)
        try: d['coords'] = json.loads(d['coords']) if d['coords'] else []
        except: d['coords'] = []
        result.append(d)
    return jsonify(result)

@app.route('/api/ftth/rutas', methods=['POST'])
@login_required
def crear_ruta_fibra():
    d = request.get_json()
    coords = d.get('coords', [])
    import math
    dist = 0
    for i in range(1, len(coords)):
        lat1, lng1 = coords[i-1]; lat2, lng2 = coords[i]
        R = 6371000; dlat = math.radians(lat2-lat1); dlng = math.radians(lng2-lng1)
        a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlng/2)**2
        dist += R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    con = get_db()
    con.execute("INSERT INTO rutas_fibra(nombre,descripcion,coords,distancia_m,color,estado,creado_por) VALUES(?,?,?,?,?,?,?)",
                (d['nombre'], d.get('descripcion',''), json.dumps(coords), round(dist,1), d.get('color','#1565c0'), d.get('estado','planificada'), session.get('username')))
    con.commit(); con.close()
    return jsonify({'ok': True, 'distancia_m': round(dist, 1)})

@app.route('/api/ftth/rutas/<int:rid>', methods=['PUT'])
@login_required
def editar_ruta_fibra(rid):
    d = request.get_json()
    coords = d.get('coords', [])
    import math
    dist = 0
    for i in range(1, len(coords)):
        lat1, lng1 = coords[i-1]; lat2, lng2 = coords[i]
        R = 6371000; dlat = math.radians(lat2-lat1); dlng = math.radians(lng2-lng1)
        a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlng/2)**2
        dist += R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    con = get_db()
    con.execute("UPDATE rutas_fibra SET nombre=?,descripcion=?,coords=?,distancia_m=?,color=?,estado=? WHERE id=?",
                (d['nombre'], d.get('descripcion',''), json.dumps(coords), round(dist,1), d.get('color','#1565c0'), d.get('estado','planificada'), rid))
    con.commit(); con.close()
    return jsonify({'ok': True, 'distancia_m': round(dist, 1)})

@app.route('/api/ftth/rutas/<int:rid>', methods=['DELETE'])
@login_required
def borrar_ruta_fibra(rid):
    con = get_db()
    con.execute("DELETE FROM rutas_fibra WHERE id=?", (rid,)); con.commit(); con.close()
    return jsonify({'ok': True})

@app.route('/api/ftth/densidad')
@login_required
def ftth_densidad():
    con = get_db()
    rows = con.execute("SELECT lat, lng, nombre, nro_cliente, plan, localidad FROM clientes WHERE tipo_servicio='inalambrico' AND estado='activo' AND lat IS NOT NULL AND lat != 0 AND lng IS NOT NULL AND lng != 0").fetchall()
    con.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/ftth/zonas', methods=['GET'])
@login_required
def get_zonas_expansion():
    con = get_db()
    rows = con.execute("SELECT * FROM zonas_expansion ORDER BY prioridad DESC, creado DESC").fetchall()
    con.close()
    result = []
    for r in rows:
        d = dict(r)
        try: d['coords'] = json.loads(d['coords']) if d['coords'] else []
        except: d['coords'] = []
        result.append(d)
    return jsonify(result)

@app.route('/api/ftth/zonas', methods=['POST'])
@login_required
def crear_zona_expansion():
    d = request.get_json()
    coords = d.get('coords', [])
    con = get_db()
    clientes_pot = 0
    if coords:
        lats = [c[0] for c in coords]; lngs = [c[1] for c in coords]
        clientes_pot = con.execute("SELECT COUNT(*) FROM clientes WHERE tipo_servicio='inalambrico' AND estado='activo' AND lat BETWEEN ? AND ? AND lng BETWEEN ? AND ?",
            (min(lats), max(lats), min(lngs), max(lngs))).fetchone()[0]
    con.execute("INSERT INTO zonas_expansion(nombre,tipo,coords,prioridad,clientes_potenciales,notas,estado) VALUES(?,?,?,?,?,?,?)",
                (d['nombre'], d.get('tipo','ftth'), json.dumps(coords), d.get('prioridad','media'), clientes_pot, d.get('notas',''), d.get('estado','pendiente')))
    con.commit(); con.close()
    return jsonify({'ok': True, 'clientes_potenciales': clientes_pot})

@app.route('/api/ftth/zonas/<int:zid>', methods=['DELETE'])
@login_required
def borrar_zona_expansion(zid):
    con = get_db()
    con.execute("DELETE FROM zonas_expansion WHERE id=?", (zid,)); con.commit(); con.close()
    return jsonify({'ok': True})

# ─── MOBILE TÉCNICO ───────────────────────────────────────────────
@app.route('/api/tecnico/mis-tareas')
@login_required
def tecnico_mis_tareas():
    username = (session.get('username','') or '').strip()
    nombre = (session.get('nombre','') or '').strip()
    con = get_db()
    tareas = con.execute("""
        SELECT s.*, c.nombre as cliente_nombre, c.nro_cliente, c.telefono, c.direccion,
               c.localidad, c.lat, c.lng, c.tipo_servicio, c.nap, c.equipo_modelo,
               c.plan as cliente_plan, c.ip_asignada, c.pppoe_usuario, c.pppoe_clave,
               c.olt_nombre, c.olt_puerto, c.cdo, c.red
        FROM servicios s LEFT JOIN clientes c ON c.id = s.cliente_id
        WHERE (UPPER(TRIM(s.tecnico))=UPPER(?) OR UPPER(TRIM(s.tecnico))=UPPER(?)
               OR UPPER(TRIM(s.tecnico_realizacion))=UPPER(?))
              AND s.estado IN ('pendiente','en_proceso','programado')
        ORDER BY CASE s.prioridad WHEN 'urgente' THEN 0 WHEN 'alta' THEN 1 WHEN 'media' THEN 2 ELSE 3 END,
                 s.fecha_programada ASC, s.fecha_creacion ASC
    """, (username, nombre, username)).fetchall()
    incidencias = con.execute("""
        SELECT i.*, t.nombre as torre_nombre, t.lat as torre_lat, t.lng as torre_lng
        FROM incidencias i LEFT JOIN torres t ON t.id = i.torre_id
        WHERE (UPPER(TRIM(i.tecnico))=UPPER(?) OR UPPER(TRIM(i.tecnico))=UPPER(?))
              AND i.estado IN ('abierta','en_proceso')
        ORDER BY i.prioridad DESC, i.fecha_inicio ASC
    """, (username, nombre)).fetchall()
    con.close()
    tareas_out = []
    for t in tareas:
        d = dict(t)
        d['nap_display'] = _armar_nap_display(d)
        tareas_out.append(d)
    return jsonify({'tareas': tareas_out, 'incidencias': [dict(i) for i in incidencias],
                    'fecha': date.today().isoformat(), 'tecnico': nombre})

@app.route('/api/tecnico/completar/<int:sid>', methods=['POST'])
@login_required
def tecnico_completar_tarea(sid):
    d = request.get_json() or {}
    con = get_db()
    con.execute("UPDATE servicios SET estado='completado', fecha_cierre=datetime('now','localtime'), observaciones=COALESCE(observaciones,'') || ? WHERE id=?",
                ('\n[Completado] ' + d.get('notas',''), sid))
    con.commit(); con.close()
    return jsonify({'ok': True})

@app.route('/api/tecnico/iniciar/<int:sid>', methods=['POST'])
@login_required
def tecnico_iniciar_tarea(sid):
    con = get_db()
    con.execute("UPDATE servicios SET estado='en_proceso', fecha_inicio=datetime('now','localtime') WHERE id=?", (sid,))
    con.commit(); con.close()
    return jsonify({'ok': True})

@app.route('/api/tecnico/ruta')
@login_required
def tecnico_ruta():
    username = (session.get('username','') or '').strip()
    nombre = (session.get('nombre','') or '').strip()
    con = get_db()
    tareas = con.execute("""
        SELECT s.id, c.nombre as cliente, c.direccion, c.localidad, c.lat, c.lng,
               s.tipo, s.prioridad, s.descripcion
        FROM servicios s LEFT JOIN clientes c ON c.id = s.cliente_id
        WHERE (UPPER(TRIM(s.tecnico))=UPPER(?) OR UPPER(TRIM(s.tecnico))=UPPER(?)
               OR UPPER(TRIM(s.tecnico_realizacion))=UPPER(?))
              AND s.estado IN ('pendiente','en_proceso','programado')
              AND c.lat IS NOT NULL AND c.lat != '' AND CAST(c.lat AS REAL) != 0
              AND c.lng IS NOT NULL AND c.lng != '' AND CAST(c.lng AS REAL) != 0
        ORDER BY s.prioridad DESC
    """, (username, nombre, username)).fetchall()
    con.close()
    import math
    puntos = []
    for t in tareas:
        d = dict(t)
        try:
            d['lat'] = float(d['lat'])
            d['lng'] = float(d['lng'])
            puntos.append(d)
        except (TypeError, ValueError):
            continue  # saltear coordenadas inválidas
    if len(puntos) < 2: return jsonify(puntos)
    ruta = [puntos.pop(0)]
    while puntos:
        u = ruta[-1]
        mejor = min(puntos, key=lambda p: math.sqrt((p['lat']-u['lat'])**2 + (p['lng']-u['lng'])**2))
        ruta.append(mejor); puntos.remove(mejor)
    return jsonify(ruta)

# ─── BACKGROUND ───────────────────────────────────────────────────
def generar_notificaciones():
    try:
        con = get_db()
        hoy = date.today()
        # NAPs casi llenas
        naps = con.execute("SELECT nombre, capacidad FROM naps WHERE estado='operativo'").fetchall()
        for n in naps:
            cap = n['capacidad'] or NAP_LIMIT
            total = con.execute("SELECT COUNT(*) FROM clientes WHERE nap=? AND estado!='baja'", (n['nombre'],)).fetchone()[0]
            if total >= cap:
                notif('nap_lleno', f"NAP {n['nombre']} LLENO ({total}/{cap})", f"Capacidad máxima alcanzada")
            elif total >= NAP_WARN:
                notif('nap_casi_lleno', f"NAP {n['nombre']} casi lleno ({total}/{cap})")
        con.close()
    except Exception as e:
        print(f"[bg] Error notificaciones: {e}")

def background_worker():
    while True:
        try: generar_notificaciones()
        except: pass
        time.sleep(1800)

# ─── MAIN ─────────────────────────────────────────────────────────
# ─── Módulos en arquitectura nueva (ADR-0001) ──────────────────────────
# Los dominios migrados se registran como blueprints bajo /api/v2. Conviven con
# las rutas heredadas mientras dura la transición (patrón strangler fig): app.py
# deja de crecer y se va vaciando a medida que cada dominio se muda.
try:
    from pucara.api.seguridad import registrar_autorizador

    def _autorizador_v2(uid, rol, modulo, accion):
        """Puente al motor de permisos existente.

        Los blueprints nuevos no pueden importar app.py (invertiría la
        dependencia), así que app.py les inyecta su verificador. Con esto
        /api/v2 respeta exactamente los mismos permisos por módulo que el
        resto del sistema, sin duplicar la lógica.
        """
        perm = _get_permisos_usuario()
        if not _tiene_modulo(perm, modulo):
            return False
        if accion:
            acc = perm.get('acciones')
            return acc == '*' or (isinstance(acc, list) and accion in acc)
        return True

    registrar_autorizador(_autorizador_v2)

    # La auditoría de los módulos nuevos NO se inyecta como callback a `log()`:
    # abre una segunda conexión sqlite3 y choca con la sesión de SQLAlchemy
    # ("database is locked"). Escriben en `historial` por su propia sesión.
    # Ver pucara/repositories/auditoria.py.

    from pucara.api.adjuntos import bp as _bp_adjuntos
    from pucara.api.analitica import bp as _bp_antiguedad
    from pucara.api.analitica import bp_rescisiones as _bp_rescisiones
    from pucara.api.naps import bp as _bp_naps
    from pucara.api.optica import bp as _bp_optica
    from pucara.api.reclamos import bp as _bp_reclamos
    for _bp in (_bp_reclamos, _bp_antiguedad, _bp_rescisiones, _bp_adjuntos,
                _bp_naps, _bp_optica):
        app.register_blueprint(_bp)
except Exception as _e:  # pragma: no cover
    # No debe impedir que arranque el sistema en producción si falta una
    # dependencia nueva (SQLAlchemy) en un despliegue todavía sin actualizar.
    print(f"[aviso] Módulos v2 no cargados: {_e}")


if __name__ == '__main__':
    init_db()
    try: generar_notificaciones()
    except: pass
    t = threading.Thread(target=background_worker, daemon=True)
    t.start()

    # HTTPS: si existen los certificados, levanta en HTTPS; si no, HTTP (con aviso).
    import os as _os
    CERT = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), 'cert.pem')
    KEY = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), 'key.pem')
    usar_https = _os.path.exists(CERT) and _os.path.exists(KEY)

    print("="*60)
    print("  ERLAN Telecomunicaciones S.A. — NetAdmin ISP v6")
    print(f"  DB: {DB}")
    if usar_https:
        print("  URL: https://192.168.10.9:5000  (HTTPS activo)")
    else:
        print("  URL: http://192.168.10.9:5000  (HTTP - sin cifrar)")
        print("  ⚠ Para HTTPS: colocá cert.pem y key.pem junto a app.py")
    print("="*60)

    if usar_https:
        app.run(host='0.0.0.0', port=5000, debug=False, threaded=True,
                ssl_context=(CERT, KEY))
    else:
        app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
