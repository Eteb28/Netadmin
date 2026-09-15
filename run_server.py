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
run_server.py — Lanza Pucara con un servidor WSGI de producción (waitress)
en lugar del servidor de desarrollo de Flask (app.run), que no aguanta HTTPS
bajo carga y se satura.

Maneja HTTPS envolviendo el socket con SSL. Si no hay certificados, cae a HTTP.

Uso:
    python3 run_server.py

Requiere: pip install waitress
"""
import os
import ssl
import threading
import sys

# Importar la app y sus inicializaciones desde app.py
import app as pucara_app

BASE = os.path.dirname(os.path.abspath(__file__))
CERT = os.path.join(BASE, 'cert.pem')
KEY = os.path.join(BASE, 'key.pem')
HOST = '0.0.0.0'
# Puerto configurable: variable de entorno PUCARA_PORT, o argumento, o 5000 por defecto
PORT = int(os.environ.get('PUCARA_PORT', sys.argv[1] if len(sys.argv) > 1 else 5000))
THREADS = 12   # cantidad de hilos para atender pedidos concurrentes


def main():
    # Verificación de integridad de rutas al arrancar (avisa, no bloquea).
    # Detecta endpoints huérfanos / rutas duplicadas antes de que un usuario
    # se tope con un 404 en producción.
    try:
        import verificar_rutas
        app_py = os.path.join(BASE, 'app.py')
        if verificar_rutas.verificar(app_py) != 0:
            print("\n⚠⚠⚠ ATENCIÓN: problemas de rutas en app.py (ver arriba).")
            print("    El servidor arranca igual, pero revisá eso cuanto antes.\n")
    except Exception as _e:
        print(f"(no se pudo verificar rutas: {_e})")

    # Inicializaciones que hacía app.py en el __main__
    pucara_app.init_db()
    try:
        pucara_app.generar_notificaciones()
    except Exception:
        pass
    t = threading.Thread(target=pucara_app.background_worker, daemon=True)
    t.start()

    flask_app = pucara_app.app
    # Detrás de un proxy (Caddy) queremos HTTP puro: PUCARA_FORCE_HTTP=1
    forzar_http = os.environ.get('PUCARA_FORCE_HTTP') == '1'
    usar_https = (not forzar_http) and os.path.exists(CERT) and os.path.exists(KEY)

    # SEGURIDAD: si estamos detrás de Caddy (forzar_http), atarse SOLO a localhost.
    # Así el puerto interno no queda expuesto sin cifrar a toda la red — la única
    # entrada es Caddy (que hace el HTTPS). En modo directo, escucha en todas las interfaces.
    bind_host = '127.0.0.1' if forzar_http else HOST

    print("=" * 60)
    print("  ERLAN Telecomunicaciones — Pucara (waitress)")
    print(f"  DB: {pucara_app.DB}")
    print(f"  Hilos: {THREADS}")

    if usar_https:
        print(f"  URL: https://192.168.10.9:{PORT}  (HTTPS + waitress)")
        print("=" * 60)
        # waitress no hace TLS nativo; envolvemos con un adaptador SSL.
        # Usamos el módulo 'waitress' con un socket TLS mediante un pequeño wrapper.
        _serve_https(flask_app)
    else:
        destino = 'localhost' if bind_host == '127.0.0.1' else '192.168.10.9'
        print(f"  URL interna: http://{destino}:{PORT}  (HTTP + waitress)")
        if bind_host == '127.0.0.1':
            print("  (solo localhost — el acceso externo entra por Caddy/HTTPS)")
        print("=" * 60)
        from waitress import serve
        serve(flask_app, host=bind_host, port=PORT, threads=THREADS)


def _serve_https(flask_app):
    """Sirve la app con waitress detrás de un socket TLS.
    Como waitress no hace TLS nativo, usamos el servidor WSGI de la stdlib
    con ThreadingMixIn envuelto en SSL — estable y sin las limitaciones del
    servidor de desarrollo de Flask."""
    from wsgiref.simple_server import make_server, WSGIServer
    from wsgiref.handlers import SimpleHandler
    from socketserver import ThreadingMixIn

    class ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
        daemon_threads = True

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(CERT, KEY)

    httpd = make_server(HOST, PORT, flask_app, server_class=ThreadingWSGIServer)
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nDetenido.")


if __name__ == '__main__':
    main()
