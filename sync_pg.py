"""
sync_pg.py — Sincronización ERP (PostgreSQL) → NetAdmin (SQLite)
═════════════════════════════════════════════════════════════════
Versión MINIMALISTA: solo trae los campos del cliente que definimos.

Campos del cliente sincronizados desde ERP (lectura pura):
  • nro_cliente (codcliente)
  • nombre (apellidos + nombre)
  • dni (cifnif)
  • email, telefono, telefono2
  • direccion, localidad
  • fecha_alta, fecha_baja, estado (derivado)
  • tipo_servicio (fibra/inalámbrico)
  • agente, plan (codtarifa)

Campos preservados (NetAdmin, NO se pisan nunca):
  • lat, lng
  • nap, olt_nombre, olt_puerto
  • torre_id, ap_nombre
  • equipo_serie, equipo_modelo, equipo_marca, mac_address
  • ip_asignada, pppoe_usuario, pppoe_clave
  • observaciones_tecnicas

Otros datos del ERP en tablas aparte:
  • contratos_erp (todos los contratos)
  • clientes_morosidad (cálculo por cliente)
  • calculos_enlace (datos técnicos del contrato)

NO modifica el ERP. Solo lee.

Uso:
    python3 sync_pg.py                  # sync completo
    python3 sync_pg.py --dry-run        # ver qué haría sin escribir
    python3 sync_pg.py --modulo=clientes
    python3 sync_pg.py --test           # test de conexión PG

Configuración: .env con PG_HOST, PG_PORT, PG_NAME, PG_USER, PG_PASSWORD
"""
import os
import sys
import json
import time
import sqlite3
import threading
import traceback
from pathlib import Path
from datetime import datetime, date

SCRIPT_DIR = Path(__file__).parent
SQLITE_PATH = SCRIPT_DIR / 'netadmin.db'


def _load_dotenv():
    env_file = SCRIPT_DIR / '.env'
    if not env_file.exists(): return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line: continue
        k, v = line.split('=', 1)
        k = k.strip(); v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v
_load_dotenv()

PG_HOST     = os.environ.get('PG_HOST', 'localhost')
PG_PORT     = int(os.environ.get('PG_PORT', '5432'))
PG_NAME     = os.environ.get('PG_NAME', 'erlan_db')
PG_USER     = os.environ.get('PG_USER', 'netadmin_user')
PG_PASSWORD = os.environ.get('PG_PASSWORD', '')

_sync_lock = threading.Lock()


SYNC_SCHEMA = """
CREATE TABLE IF NOT EXISTS sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha_inicio TEXT, fecha_fin TEXT, duracion_seg REAL,
    estado TEXT, iniciado_por TEXT, modulos TEXT, resumen TEXT, errores TEXT
);
CREATE INDEX IF NOT EXISTS ix_sync_log_fecha ON sync_log(fecha_inicio);

CREATE TABLE IF NOT EXISTS contratos_erp (
    codigo TEXT PRIMARY KEY,
    codcliente TEXT NOT NULL,
    nombrecliente TEXT,
    tipocontrato TEXT,
    nombre TEXT,
    descripcion TEXT,
    estado_erp TEXT,
    estado_workflow TEXT,
    medio_transmision TEXT,
    tipo_servicio TEXT,
    fecha_solicitud TEXT,
    fecha_inicio TEXT,
    fecha_activacion TEXT,
    fecha_instalacion TEXT,
    fecha_suspension TEXT,
    fecha_restablecimiento TEXT,
    fecha_rescision TEXT,
    ultimopago TEXT,
    agente TEXT,
    coste REAL,
    totalconiva REAL,
    idcaja_nap INTEGER,
    nap_descripcion TEXT,
    cdo INTEGER,
    nap_numero INTEGER,
    olt_nombre TEXT,
    direccion TEXT,
    localidad TEXT,
    provincia TEXT,
    sincronizado TEXT
);
CREATE INDEX IF NOT EXISTS ix_contratos_erp_cliente ON contratos_erp(codcliente);
CREATE INDEX IF NOT EXISTS ix_contratos_erp_estado  ON contratos_erp(estado_workflow);

CREATE TABLE IF NOT EXISTS clientes_morosidad (
    codcliente TEXT PRIMARY KEY,
    facturas_pendientes INTEGER DEFAULT 0,
    monto_pendiente REAL DEFAULT 0,
    facturas_vencidas INTEGER DEFAULT 0,
    monto_vencido REAL DEFAULT 0,
    ultima_factura_fecha TEXT,
    ultimo_pago_fecha TEXT,
    dias_desde_ultimo_pago INTEGER,
    nivel_riesgo TEXT,
    sincronizado TEXT
);

CREATE TABLE IF NOT EXISTS calculos_enlace (
    codcontrato TEXT PRIMARY KEY,
    codcliente TEXT,
    fecha TEXT,
    distancia_metros REAL,
    altura_ap INTEGER,
    altura_sm INTEGER,
    tieneairmax INTEGER,
    observaciones TEXT,
    sincronizado TEXT
);
CREATE INDEX IF NOT EXISTS ix_calculos_cliente ON calculos_enlace(codcliente);
"""


def ensure_sync_schema(con):
    con.executescript(SYNC_SCHEMA)
    con.commit()


def _connect_pg():
    try:
        import psycopg2
    except ImportError:
        raise RuntimeError(
            'psycopg2 no instalado:\n'
            '  source venv/bin/activate && pip install psycopg2-binary'
        )
    return psycopg2.connect(
        host=PG_HOST, port=PG_PORT, dbname=PG_NAME,
        user=PG_USER, password=PG_PASSWORD,
        connect_timeout=10,
    )


def _pg_test():
    try:
        con = _connect_pg()
        cur = con.cursor()
        cur.execute("SELECT 1")
        cur.fetchone()
        cur.close(); con.close()
        return {'ok': True}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


# ═══════════════════════════════════════════════════════════════════
#  SYNC: CLIENTES (minimalista)
# ═══════════════════════════════════════════════════════════════════
def sync_clientes(pg_con, sqlite_con, dry_run=False):
    """ERP → NetAdmin con estrategia minimalista híbrida.
    
    Match: nro_cliente (NetAdmin) == codcliente (ERP).
    
    ERP pisa SIEMPRE: nombre, dni, email, telefono, direccion, localidad,
                      estado, tipo_servicio, fecha_alta, fecha_baja, agente, plan.
    
    NetAdmin conserva (no se tocan acá): lat, lng, nap, olt_*, torre_id, ap_nombre,
                      equipo_*, mac_address, ip_asignada, pppoe_*, observaciones_tecnicas.
    """
    log = {'modulo': 'clientes', 'leidos': 0, 'nuevos': 0,
           'actualizados': 0, 'sin_cambios': 0, 'errores': 0,
           'detalle_errores': []}
    
    pg_cur = pg_con.cursor()
    pg_cur.execute("""
        SELECT
            c.codcliente,
            CASE
                WHEN c.apellidos IS NOT NULL AND TRIM(c.apellidos) <> ''
                    THEN TRIM(c.apellidos) || ', ' || COALESCE(c.nombre, '')
                ELSE COALESCE(c.nombre, '')
            END AS nombre,
            c.cifnif AS dni,
            c.email,
            c.telefono1,
            c.telefono2,
            c.dirclientes_direccion AS direccion,
            c.dirclientes_ciudad AS localidad,
            c.fechaalta,
            c.fechabaja,
            c.debaja,
            c.en_reclamo,
            c.cuentactiva,
            c.codagente AS agente,
            c.codtarifa AS plan,
            c.contratos_medio_transmision AS medio_transmision
        FROM public.clientes c
    """)
    
    # Indexar locales por nro_cliente para match O(1)
    sl_cur = sqlite_con.cursor()
    existing = {}
    for r in sl_cur.execute(
        "SELECT id, nro_cliente FROM clientes WHERE nro_cliente IS NOT NULL AND nro_cliente <> ''"
    ):
        existing[str(r['nro_cliente']).strip()] = r['id']
    
    while True:
        rows = pg_cur.fetchmany(500)
        if not rows: break
        for row in rows:
            log['leidos'] += 1
            try:
                cod = row[0]
                if not cod: continue
                cod = str(cod).strip()
                
                # Derivar estado
                debaja, en_reclamo, cuentactiva, fechabaja = row[10], row[11], row[12], row[9]
                if debaja or fechabaja:
                    estado = 'baja'
                elif en_reclamo:
                    estado = 'rescision'
                elif cuentactiva is False:
                    estado = 'suspendido'
                else:
                    estado = 'activo'
                
                # Tipo de servicio
                medio = (row[15] or '').strip()
                if medio == 'Fibra óptica':
                    tipo_servicio = 'fibra'
                elif medio == 'Inalámbrico':
                    tipo_servicio = 'inalambrico'
                else:
                    tipo_servicio = None
                
                payload = {
                    'nombre': row[1],
                    'dni': row[2] or '',
                    'email': row[3],
                    'telefono': row[4],
                    'direccion': row[6],
                    'localidad': row[7],
                    'estado': estado,
                    'tipo_servicio': tipo_servicio,
                    'fecha_alta': str(row[8]) if row[8] else None,
                    'fecha_baja': str(row[9]) if row[9] else None,
                    'agente': str(row[13]) if row[13] else None,
                    'plan': row[14],
                }
                
                if cod in existing:
                    if dry_run:
                        log['actualizados'] += 1
                        continue
                    local_id = existing[cod]
                    
                    cur_row = sl_cur.execute(
                        "SELECT nombre, dni, email, telefono, direccion, localidad, "
                        "estado, tipo_servicio, agente, plan FROM clientes WHERE id=?",
                        (local_id,)
                    ).fetchone()
                    if cur_row:
                        cambio = (
                            (cur_row['nombre'] or '') != (payload['nombre'] or '') or
                            (cur_row['dni'] or '') != (payload['dni'] or '') or
                            (cur_row['estado'] or '') != payload['estado'] or
                            (cur_row['localidad'] or '') != (payload['localidad'] or '') or
                            (cur_row['telefono'] or '') != (payload['telefono'] or '') or
                            (cur_row['direccion'] or '') != (payload['direccion'] or '') or
                            (cur_row['email'] or '') != (payload['email'] or '') or
                            (cur_row['tipo_servicio'] or '') != (payload['tipo_servicio'] or '')
                        )
                        if not cambio:
                            log['sin_cambios'] += 1
                            continue
                    
                    sl_cur.execute("""
                        UPDATE clientes
                        SET nombre=?, dni=?, email=?, telefono=?,
                            direccion=?, localidad=?,
                            estado=?, tipo_servicio=?,
                            fecha_alta=COALESCE(?, fecha_alta),
                            fecha_baja=?,
                            agente=COALESCE(?, agente),
                            plan=COALESCE(?, plan),
                            origen='erp',
                            modificado=datetime('now','localtime')
                        WHERE id=?
                    """, (payload['nombre'], payload['dni'], payload['email'],
                          payload['telefono'], payload['direccion'], payload['localidad'],
                          payload['estado'], payload['tipo_servicio'],
                          payload['fecha_alta'], payload['fecha_baja'],
                          payload['agente'], payload['plan'], local_id))
                    log['actualizados'] += 1
                else:
                    if dry_run:
                        log['nuevos'] += 1
                        continue
                    sl_cur.execute("""
                        INSERT INTO clientes(
                            nro_cliente, nombre, dni, email, telefono,
                            direccion, localidad, estado, tipo_servicio,
                            fecha_alta, fecha_baja, agente, plan,
                            origen, creado, modificado
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,
                                 'erp', datetime('now','localtime'), datetime('now','localtime'))
                    """, (cod, payload['nombre'], payload['dni'],
                          payload['email'], payload['telefono'],
                          payload['direccion'], payload['localidad'],
                          payload['estado'], payload['tipo_servicio'],
                          payload['fecha_alta'], payload['fecha_baja'],
                          payload['agente'], payload['plan']))
                    existing[cod] = sl_cur.lastrowid
                    log['nuevos'] += 1
            except Exception as e:
                log['errores'] += 1
                if len(log['detalle_errores']) < 5:
                    log['detalle_errores'].append(f"cod={row[0] if row else '?'}: {e}")
    
    pg_cur.close()
    if not dry_run:
        sqlite_con.commit()
    return log


def sync_contratos(pg_con, sqlite_con, dry_run=False):
    """Cache completo de contratos del ERP."""
    log = {'modulo': 'contratos', 'leidos': 0, 'insertados': 0, 'errores': 0}
    
    pg_cur = pg_con.cursor()
    pg_cur.execute("""
        SELECT
            co.codigo, co.codcliente, co.nombrecliente,
            co.tipocontrato, co.nombre, co.descripcion,
            co.estado,
            CASE
                WHEN co.fecharescision IS NOT NULL                THEN 'baja'
                WHEN co.fechasuspension IS NOT NULL
                     AND co.fecharestablecimiento IS NULL         THEN 'suspendido'
                WHEN co.fechainstalacion IS NOT NULL              THEN 'activo'
                WHEN co.fechaactivacion IS NOT NULL               THEN 'instalacion_pendiente'
                WHEN co.fechasolicitud IS NOT NULL                THEN 'venta'
                ELSE LOWER(COALESCE(co.estado, 'desconocido'))
            END AS estado_workflow,
            co.medio_transmision,
            CASE
                WHEN co.medio_transmision = 'Fibra óptica' THEN 'fibra'
                WHEN co.medio_transmision = 'Inalámbrico'  THEN 'inalambrico'
                ELSE NULL
            END AS tipo_servicio,
            co.fechasolicitud, co.fechainicio, co.fechaactivacion,
            co.fechainstalacion, co.fechasuspension,
            co.fecharestablecimiento, co.fecharescision,
            co.ultimopago, co.codagente,
            co.coste, co.totalconiva,
            co.idcaja_nap, co.caja_nap_descripcion,
            cn.cdo, cn.nap, cn.nombre_fo_olt,
            co.dirclientes_direccion, co.dirclientes_ciudad, co.dirclientes_provincia
        FROM public.contratos co
        LEFT JOIN public.sat_cajas_nap cn ON cn.id = co.idcaja_nap
    """)
    
    sl_cur = sqlite_con.cursor()
    if not dry_run:
        sl_cur.execute("DELETE FROM contratos_erp")
    
    while True:
        rows = pg_cur.fetchmany(1000)
        if not rows: break
        log['leidos'] += len(rows)
        if dry_run:
            log['insertados'] += len(rows)
            continue
        for r in rows:
            try:
                sl_cur.execute("""
                    INSERT INTO contratos_erp(
                        codigo, codcliente, nombrecliente, tipocontrato, nombre, descripcion,
                        estado_erp, estado_workflow, medio_transmision, tipo_servicio,
                        fecha_solicitud, fecha_inicio, fecha_activacion, fecha_instalacion,
                        fecha_suspension, fecha_restablecimiento, fecha_rescision, ultimopago,
                        agente, coste, totalconiva,
                        idcaja_nap, nap_descripcion, cdo, nap_numero, olt_nombre,
                        direccion, localidad, provincia, sincronizado
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,
                            datetime('now','localtime'))
                """, [_dt2s(v) for v in r])
                log['insertados'] += 1
            except Exception as e:
                log['errores'] += 1
                if log['errores'] <= 3:
                    print(f"[sync_contratos] {r[0]}: {e}")
    
    pg_cur.close()
    if not dry_run:
        sqlite_con.commit()
    return log


def sync_calculos(pg_con, sqlite_con, dry_run=False):
    """Cálculos de enlace: distancia, altura AP/SM, airmax, observaciones."""
    log = {'modulo': 'calculos', 'leidos': 0, 'actualizados': 0, 'errores': 0}
    
    pg_cur = pg_con.cursor()
    pg_cur.execute("""
        SELECT co.codigo, co.codcliente, co.fechasolicitud,
               co.distancia_sitio_metros, co.altura_ap, co.altura_sm,
               CASE WHEN co.tieneairmax THEN 1 ELSE 0 END,
               co.observaciones_calculo
        FROM public.contratos co
        WHERE co.distancia_sitio_metros IS NOT NULL
           OR co.altura_ap IS NOT NULL
           OR co.altura_sm IS NOT NULL
           OR co.observaciones_calculo IS NOT NULL
    """)
    
    sl_cur = sqlite_con.cursor()
    if not dry_run:
        sl_cur.execute("DELETE FROM calculos_enlace")
    
    rows = pg_cur.fetchall()
    log['leidos'] = len(rows)
    
    for r in rows:
        try:
            if dry_run:
                log['actualizados'] += 1
                continue
            sl_cur.execute("""
                INSERT OR REPLACE INTO calculos_enlace(
                    codcontrato, codcliente, fecha,
                    distancia_metros, altura_ap, altura_sm,
                    tieneairmax, observaciones, sincronizado
                ) VALUES(?,?,?,?,?,?,?,?, datetime('now','localtime'))
            """, (r[0], r[1], str(r[2]) if r[2] else None,
                  float(r[3]) if r[3] else None,
                  r[4], r[5], r[6], r[7]))
            log['actualizados'] += 1
        except Exception as e:
            log['errores'] += 1
            if log['errores'] <= 3:
                print(f"[sync_calculos] {r[0]}: {e}")
    
    pg_cur.close()
    if not dry_run:
        sqlite_con.commit()
    return log


def sync_morosidad(pg_con, sqlite_con, dry_run=False):
    """Calcula morosidad por cliente."""
    log = {'modulo': 'morosidad', 'leidos': 0, 'actualizados': 0, 'errores': 0}
    
    pg_cur = pg_con.cursor()
    pg_cur.execute("""
        SELECT
            f.codcliente,
            COUNT(*) FILTER (WHERE r.idrecibo IS NULL) AS pendientes,
            COALESCE(SUM(f.total) FILTER (WHERE r.idrecibo IS NULL), 0) AS monto_pte,
            COUNT(*) FILTER (
                WHERE r.idrecibo IS NULL
                  AND f.fecha < CURRENT_DATE - INTERVAL '30 days'
            ) AS vencidas,
            COALESCE(SUM(f.total) FILTER (
                WHERE r.idrecibo IS NULL
                  AND f.fecha < CURRENT_DATE - INTERVAL '30 days'
            ), 0) AS monto_vencido,
            MAX(f.fecha) AS ultima_factura
        FROM public.facturascli f
        LEFT JOIN public.reciboscli r ON r.idfactura = f.idfactura
        WHERE f.codcliente IS NOT NULL
          AND (f.anulada IS NOT TRUE)
        GROUP BY f.codcliente
    """)
    facts = {r[0]: r for r in pg_cur.fetchall()}
    
    pg_cur.execute("""
        SELECT codcliente, MAX(fecha) FROM public.reciboscli
        WHERE codcliente IS NOT NULL GROUP BY codcliente
    """)
    pagos = {r[0]: r[1] for r in pg_cur.fetchall()}
    
    sl_cur = sqlite_con.cursor()
    if not dry_run:
        sl_cur.execute("DELETE FROM clientes_morosidad")
    
    hoy = date.today()
    todos_cli = set(facts.keys()) | set(pagos.keys())
    log['leidos'] = len(todos_cli)
    
    for cod in todos_cli:
        try:
            f = facts.get(cod, (cod, 0, 0, 0, 0, None))
            ultimo_pago = pagos.get(cod)
            dias = (hoy - ultimo_pago).days if ultimo_pago else None
            vencidas = f[3] or 0
            monto_vencido = float(f[4] or 0)
            if vencidas >= 3 or monto_vencido > 50000:
                riesgo = 'critico'
            elif vencidas >= 2:
                riesgo = 'alto'
            elif vencidas >= 1:
                riesgo = 'medio'
            else:
                riesgo = 'bajo'
            
            if dry_run:
                log['actualizados'] += 1
                continue
            
            sl_cur.execute("""
                INSERT INTO clientes_morosidad(
                    codcliente, facturas_pendientes, monto_pendiente,
                    facturas_vencidas, monto_vencido,
                    ultima_factura_fecha, ultimo_pago_fecha,
                    dias_desde_ultimo_pago, nivel_riesgo, sincronizado
                ) VALUES(?,?,?,?,?,?,?,?,?, datetime('now','localtime'))
            """, (cod, f[1] or 0, float(f[2] or 0), vencidas, monto_vencido,
                  str(f[5]) if f[5] else None,
                  str(ultimo_pago) if ultimo_pago else None,
                  dias, riesgo))
            log['actualizados'] += 1
        except Exception as e:
            log['errores'] += 1
    
    pg_cur.close()
    if not dry_run:
        sqlite_con.commit()
    return log


MODULOS = {
    'clientes':  sync_clientes,
    'contratos': sync_contratos,
    'calculos':  sync_calculos,
    'morosidad': sync_morosidad,
}


def sync_full(iniciado_por='manual', dry_run=False, solo_modulos=None):
    if not _sync_lock.acquire(blocking=False):
        return {'estado': 'error', 'msg': 'Ya hay un sync corriendo'}
    
    inicio = datetime.now()
    inicio_str = inicio.strftime('%Y-%m-%d %H:%M:%S')
    modulos_a_correr = solo_modulos or list(MODULOS.keys())
    resumen = {'estado': 'corriendo', 'modulos': {}, 'iniciado_por': iniciado_por,
               'inicio': inicio_str, 'dry_run': dry_run}
    errores_globales = []
    log_id = None
    sqlite_con = None
    pg_con = None
    
    try:
        sqlite_con = sqlite3.connect(str(SQLITE_PATH))
        sqlite_con.row_factory = sqlite3.Row
        ensure_sync_schema(sqlite_con)
        
        if not dry_run:
            cur = sqlite_con.execute("""
                INSERT INTO sync_log(fecha_inicio, estado, iniciado_por, modulos)
                VALUES(?, 'corriendo', ?, ?)
            """, (inicio_str, iniciado_por, json.dumps(modulos_a_correr)))
            log_id = cur.lastrowid
            sqlite_con.commit()
        
        try:
            pg_con = _connect_pg()
        except Exception as e:
            errores_globales.append(f"No pude conectar a PG: {e}")
            raise
        
        for nombre in modulos_a_correr:
            fn = MODULOS.get(nombre)
            if not fn:
                errores_globales.append(f"Módulo desconocido: {nombre}")
                continue
            try:
                t0 = time.time()
                modlog = fn(pg_con, sqlite_con, dry_run=dry_run)
                try: pg_con.commit()
                except Exception: pass
                modlog['duracion_seg'] = round(time.time() - t0, 2)
                resumen['modulos'][nombre] = modlog
            except Exception as e:
                try: pg_con.rollback()
                except Exception: pass
                try: sqlite_con.rollback()
                except Exception: pass
                errores_globales.append(f"{nombre}: {e}")
                resumen['modulos'][nombre] = {'modulo': nombre, 'error': str(e),
                                              'traceback': traceback.format_exc()[:500]}
        
        modulos_ok = sum(1 for m in resumen['modulos'].values() if 'error' not in m)
        if errores_globales:
            resumen['estado'] = 'parcial' if modulos_ok > 0 else 'error'
        else:
            resumen['estado'] = 'ok'
    
    except Exception as e:
        resumen['estado'] = 'error'
        errores_globales.append(str(e))
    finally:
        _sync_lock.release()
        fin = datetime.now()
        resumen['fin'] = fin.strftime('%Y-%m-%d %H:%M:%S')
        resumen['duracion_seg'] = round((fin - inicio).total_seconds(), 2)
        resumen['errores'] = errores_globales
        
        if log_id and not dry_run and sqlite_con:
            try:
                sqlite_con.execute("""
                    UPDATE sync_log
                    SET fecha_fin=?, duracion_seg=?, estado=?, resumen=?, errores=?
                    WHERE id=?
                """, (resumen['fin'], resumen['duracion_seg'], resumen['estado'],
                      json.dumps(resumen['modulos'], default=str),
                      '\n'.join(errores_globales)[:5000] if errores_globales else None,
                      log_id))
                sqlite_con.commit()
            except Exception:
                pass
        if pg_con:
            try: pg_con.close()
            except Exception: pass
        if sqlite_con:
            try: sqlite_con.close()
            except Exception: pass
    
    return resumen


def _dt2s(v):
    if v is None: return None
    if isinstance(v, (datetime, date)):
        return v.isoformat(sep=' ', timespec='seconds') if isinstance(v, datetime) else str(v)
    return v


def _print_resumen(r):
    print(f"\n═══ SYNC {r.get('estado','?').upper()} ═══")
    print(f"  Inicio: {r.get('inicio')}    Duración: {r.get('duracion_seg')}s")
    print(f"  Iniciado por: {r.get('iniciado_por')}")
    if r.get('dry_run'): print(f"  (DRY-RUN — no se escribió nada)")
    for nombre, m in (r.get('modulos') or {}).items():
        if 'error' in m:
            print(f"  ✗ {nombre:12} ERROR: {m['error']}")
        else:
            detalle = ", ".join(
                f"{k}={v}" for k, v in m.items()
                if k not in ('modulo','detalle_errores') and not isinstance(v, list)
            )
            print(f"  ✓ {nombre:12} {detalle}")
    if r.get('errores'):
        print(f"\n  Errores:")
        for e in r['errores']: print(f"    • {e}")


def main():
    args = {a.split('=',1)[0]: (a.split('=',1)[1] if '=' in a else True) for a in sys.argv[1:]}
    
    if '--help' in args or '-h' in args:
        print(__doc__); return
    
    if '--test' in args:
        r = _pg_test()
        print(f"PG test: {r}"); return
    
    dry = '--dry-run' in args
    modulos_str = args.get('--modulo')
    solo = [m.strip() for m in modulos_str.split(',')] if modulos_str else None
    iniciado = args.get('--iniciado-por', 'cron')
    
    resultado = sync_full(iniciado_por=iniciado, dry_run=dry, solo_modulos=solo)
    _print_resumen(resultado)
    sys.exit(0 if resultado.get('estado') == 'ok' else 1)


if __name__ == '__main__':
    main()
