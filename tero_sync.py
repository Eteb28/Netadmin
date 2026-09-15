#!/usr/bin/env python3
"""
tero_sync.py — Sincroniza los reclamos (tickets) de Tero HelpDesk a Pucará.

API v2 (confirmada):
  Login:  POST {BASE_URL}/api/v2/accounts/login  {username,password} → {token}
  Auth:   header  Authorization: Token <token>
  Tickets: GET /api/v2/tickets  (paginado: count/next/previous/results)
  Clients: GET /api/v2/clients  (gatewayId = codcli sin ceros a la izquierda)

Cruce cliente confirmado al 100%:  nro_cliente = str(gatewayId).zfill(6)

Credenciales por variables de entorno o .env:
  NETADMIN_TERO_URL   (default https://nuevat1erlan.815d.net:815)
  NETADMIN_TERO_USER  (default erlanpucara)
  NETADMIN_TERO_PASS

Uso:
  from tero_sync import sync;  sync()                 # desde app.py (endpoint)
  python3 tero_sync.py                                # manual, últimos 30 días
  python3 tero_sync.py --dias 90 --rebuild-map        # más histórico + rearmar mapa
"""
import os
import ssl
import json
import sqlite3
import urllib.request
import urllib.error
from datetime import datetime, timedelta

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'netadmin.db')

_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


def _cfg(clave, default=''):
    """Lee de variable de entorno o del .env."""
    v = os.environ.get(clave)
    if v:
        return v
    envfile = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    if os.path.exists(envfile):
        for line in open(envfile):
            line = line.strip()
            if line.startswith(clave + '='):
                return line.split('=', 1)[1].strip().strip('"').strip("'")
    return default


BASE = _cfg('NETADMIN_TERO_URL', 'https://nuevat1erlan.815d.net:815').rstrip('/')
USER = _cfg('NETADMIN_TERO_USER', 'erlanpucara')
PASS = _cfg('NETADMIN_TERO_PASS', '')


def _req(method, path, token=None, body=None, timeout=30):
    h = {'Content-Type': 'application/json'}
    if token:
        h['Authorization'] = f'Token {token}'
    data = json.dumps(body).encode() if body else None
    url = path if path.startswith('http') else BASE + path
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        try:
            return e.code, e.read().decode()
        except Exception:
            return e.code, ''
    except Exception as e:
        return None, str(e)


def _login():
    st, body = _req('POST', '/api/v2/accounts/login', body={'username': USER, 'password': PASS})
    if st != 200:
        raise RuntimeError(f'Login Tero falló (HTTP {st}): {body[:200]}')
    return json.loads(body).get('token')


def _map_vacio(con):
    try:
        return con.execute("SELECT COUNT(*) c FROM tero_client_map").fetchone()[0] == 0
    except Exception:
        return True


def construir_mapa(con, token):
    """Arma tero_client_map (tero_client_id → nro_cliente) desde /api/v2/clients.
    gatewayId es el codcli sin ceros → nro_cliente = zfill(6)."""
    total = 0
    page = 1
    while True:
        st, body = _req('GET', f'/api/v2/clients?page={page}&page_size=200', token)
        if st != 200:
            # reintento sin page_size por si no lo soporta
            st, body = _req('GET', f'/api/v2/clients?page={page}', token)
            if st != 200:
                break
        j = json.loads(body)
        for c in j.get('results', []):
            gw = c.get('gatewayId')
            if gw is None:
                continue
            cod = str(gw).zfill(6)
            con.execute("""INSERT OR REPLACE INTO tero_client_map(tero_client_id, nro_cliente, matched_by, creado)
                           VALUES(?,?, 'code', datetime('now','localtime'))""", (c['id'], cod))
            total += 1
        if not j.get('next'):
            break
        page += 1
    con.commit()
    return total


def sincronizar_usuarios(con, token):
    """Trae el padrón de operadores de Tero (id, username, nombre y apellido)."""
    st, body = _req('GET', '/api/v2/users?page_size=200', token)
    if st != 200:
        st, body = _req('GET', '/api/v2/users', token)
        if st != 200:
            return 0
    j = json.loads(body)
    items = j.get('results', j if isinstance(j, list) else [])
    n = 0
    for u in items:
        nom = (u.get('first_name') or '').strip()
        ape = (u.get('last_name') or '').strip()
        completo = (nom + ' ' + ape).strip() or u.get('username')
        con.execute("""INSERT OR REPLACE INTO tero_usuarios(id,username,nombre,apellido,nombre_completo)
                       VALUES(?,?,?,?,?)""", (u.get('id'), u.get('username'), nom, ape, completo))
        n += 1
    con.commit()
    return n


def traer_detalle(tero_id):
    """Detalle completo de un ticket EN VIVO desde Tero: el texto del reclamo
    (campo `detail`, que no viene en el listado), la conversación y los adjuntos."""
    if not PASS:
        return {'error': 'Sin credenciales de Tero'}
    try:
        token = _login()
    except Exception as e:
        return {'error': str(e)}
    res = {'tero_id': tero_id}
    st, body = _req('GET', '/api/v2/tickets/%s' % tero_id, token)
    if st == 200:
        try:
            t = json.loads(body)
            res['detail'] = t.get('detail')
            res['titulo'] = t.get('title')
            res['estado'] = t.get('status')
            res['categoria'] = t.get('category')
            res['cliente'] = t.get('client')
            res['creado'] = t.get('createdAt')
            res['cerrado'] = t.get('closedAt')
            res['asignado'] = t.get('assignee')
            cid = t.get('conversationId')
        except Exception:
            cid = None
    else:
        cid = None
    # adjuntos
    st, body = _req('GET', '/api/v2/tickets/%s/attachments' % tero_id, token)
    if st == 200:
        try:
            a = json.loads(body)
            res['adjuntos'] = a.get('results', a if isinstance(a, list) else [])
        except Exception:
            res['adjuntos'] = []
    # conversación
    if cid:
        st, body = _req('GET', '/api/v2/conversations/%s/messages' % cid, token)
        if st == 200:
            try:
                m = json.loads(body)
                res['mensajes'] = m.get('results', m if isinstance(m, list) else [])
            except Exception:
                res['mensajes'] = []
    return res


def _estado(ticket):
    """Tero usa 3 grupos: unstarted (Abierto), started (En Progreso), completed (Cerrado)."""
    g = ticket.get('statusGroup')
    if g == 'completed' or ticket.get('closedAt'):
        return 'cerrado'
    if g == 'started':
        return 'en_progreso'
    return 'abierto'


def _parse_fecha(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace('Z', '+00:00'))
    except Exception:
        return None


def sync_tickets(con, token, dias=30, max_paginas=60):
    """Trae tickets (más nuevos primero), los cruza con el cliente y los guarda.
    Corta al llegar a tickets más viejos que 'dias' o al tope de páginas."""
    mapa = {r[0]: r[1] for r in con.execute("SELECT tero_client_id, nro_cliente FROM tero_client_map").fetchall()}
    corte = datetime.now().astimezone() - timedelta(days=dias)
    total, vinculados = 0, 0
    page = 1
    parar = False
    while page <= max_paginas and not parar:
        st, body = _req('GET', f'/api/v2/tickets?page={page}&page_size=100', token)
        if st != 200:
            st, body = _req('GET', f'/api/v2/tickets?page={page}', token)
            if st != 200:
                break
        j = json.loads(body)
        items = j.get('results', [])
        if not items:
            break
        for t in items:
            fc = _parse_fecha(t.get('createdAt'))
            if fc and fc.astimezone() < corte:
                parar = True
                break
            nro = mapa.get(t.get('clientId'))
            if nro:
                vinculados += 1
            con.execute("""
                INSERT OR REPLACE INTO reclamos(
                    tero_id, titulo, tero_client_id, nro_cliente, cliente_nombre,
                    connection_id, created_by, asign_to, categoria, subcategoria,
                    estado, prioridad, departamento, issue, canal, despacho_tecnico,
                    created_at, closed_at, sync_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, datetime('now','localtime'))
            """, (
                t.get('id'), t.get('title'), t.get('clientId'), nro, t.get('client'),
                t.get('connectionId'), t.get('createdBy') or t.get('createdByFullName'),
                t.get('assignee'), t.get('category'), t.get('subcategory'),
                _estado(t), t.get('priority'), t.get('department'), t.get('issue'),
                t.get('attentionChannel'), 1 if t.get('dispatchTechnician') else 0,
                t.get('createdAt'), t.get('closedAt'),
            ))
            total += 1
        con.commit()
        if not j.get('next'):
            break
        page += 1
    return total, vinculados


def sync(dias=30, rebuild_map=False, max_paginas=60):
    """Punto de entrada. Llamado por el endpoint /api/tero/sync o desde CLI."""
    if not PASS:
        return {'error': 'Falta NETADMIN_TERO_PASS (env o .env)'}
    con = sqlite3.connect(DB, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        token = _login()
        n_map = 0
        n_usuarios = sincronizar_usuarios(con, token)
        if rebuild_map or _map_vacio(con):
            n_map = construir_mapa(con, token)
        n_tickets, n_link = sync_tickets(con, token, dias=dias, max_paginas=max_paginas)
    except Exception as e:
        con.close()
        return {'error': str(e)}
    con.close()
    return {
        'ok': True,
        'operadores': n_usuarios,
        'clientes_mapeados': n_map,
        'tickets_sincronizados': n_tickets,
        'tickets_vinculados_a_cliente': n_link,
    }


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--dias', type=int, default=30)
    ap.add_argument('--rebuild-map', action='store_true')
    ap.add_argument('--max-paginas', type=int, default=60)
    a = ap.parse_args()
    print(f"Sincronizando reclamos de Tero (últimos {a.dias} días)…")
    res = sync(dias=a.dias, rebuild_map=a.rebuild_map, max_paginas=a.max_paginas)
    print(json.dumps(res, indent=2, ensure_ascii=False))
