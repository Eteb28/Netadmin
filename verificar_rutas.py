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
verificar_rutas.py — Detecta bugs de integridad en app.py antes de subir a producción.

Nació de un problema real: al editar app.py (6000+ líneas) con reemplazos de texto,
un @app.route puede perderse silenciosamente, dejando un endpoint "huérfano"
(función definida pero sin URL). El servidor arranca sin quejarse y el endpoint
da 404 recién cuando un usuario lo toca semanas después.

Este script detecta TRES clases de problema:
  1. HUÉRFANOS: función con @login_required/@admin_required pero sin @app.route.
  2. RUTAS DUPLICADAS: misma URL + método declarada dos veces (una pisa la otra).
  3. NOMBRES DE FUNCIÓN DUPLICADOS: dos def con el mismo nombre (el 2º pisa al 1º).

Uso:
    python3 verificar_rutas.py            # revisa ./app.py
    python3 verificar_rutas.py otro.py    # revisa otro archivo

Devuelve código de salida 0 si todo OK, 1 si hay problemas (sirve para scripts/CI).
"""
import ast
import sys
import re
from collections import Counter


DECORADORES_AUTH = {'login_required', 'admin_required'}


def _nombre_decorador(dec):
    """Extrae el nombre de un decorador, sea @x, @x(...) o @a.b."""
    if isinstance(dec, ast.Name):
        return dec.id
    if isinstance(dec, ast.Call):
        return _nombre_decorador(dec.func)
    if isinstance(dec, ast.Attribute):
        return dec.attr
    return None


def _es_app_route(dec):
    """True si el decorador es @app.route(...) o @app.get/@app.post etc."""
    if isinstance(dec, ast.Call):
        f = dec.func
        if isinstance(f, ast.Attribute) and f.attr in ('route', 'get', 'post', 'put', 'delete', 'patch'):
            return True
    return False


def _ruta_y_metodos(dec):
    """De un @app.route('/x', methods=['POST']) devuelve ('/x', ('POST',))."""
    ruta = None
    metodos = ('GET',)
    if dec.args:
        a = dec.args[0]
        if isinstance(a, ast.Constant):
            ruta = a.value
    for kw in dec.keywords:
        if kw.arg == 'methods' and isinstance(kw.value, (ast.List, ast.Tuple)):
            metodos = tuple(sorted(
                e.value for e in kw.value.elts if isinstance(e, ast.Constant)))
    return ruta, metodos


def verificar(path):
    src = open(path, encoding='utf-8').read()
    try:
        arbol = ast.parse(src)
    except SyntaxError as e:
        print(f"✗ ERROR DE SINTAXIS en {path}:{e.lineno}: {e.msg}")
        return 1

    huerfanos = []
    rutas = []            # (ruta, metodos, nombre_funcion, linea)
    nombres_funcion = []  # (nombre, linea)

    for nodo in ast.walk(arbol):
        if not isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        decos = nodo.decorator_list
        nombres_deco = {_nombre_decorador(d) for d in decos}
        tiene_route = any(_es_app_route(d) for d in decos)
        tiene_auth = bool(nombres_deco & DECORADORES_AUTH)

        # 1. Huérfano: tiene auth pero NO tiene @app.route
        if tiene_auth and not tiene_route:
            huerfanos.append((nodo.name, nodo.lineno))

        # 2. Recolectar rutas para detectar duplicados
        if tiene_route:
            nombres_funcion.append((nodo.name, nodo.lineno))
            for d in decos:
                if _es_app_route(d):
                    ruta, metodos = _ruta_y_metodos(d)
                    rutas.append((ruta, metodos, nodo.name, nodo.lineno))

    problemas = 0

    # Reporte 1: huérfanos
    if huerfanos:
        problemas += len(huerfanos)
        print(f"\n⚠ {len(huerfanos)} ENDPOINT(S) HUÉRFANO(S) — función con auth pero SIN @app.route:")
        for nombre, linea in huerfanos:
            print(f"    línea {linea}: def {nombre}()  → le falta el @app.route")

    # Reporte 2: rutas duplicadas (misma ruta + mismo método)
    clave = Counter((r, m) for r, m, _, _ in rutas if r)
    dups_ruta = [k for k, c in clave.items() if c > 1]
    if dups_ruta:
        problemas += len(dups_ruta)
        print(f"\n⚠ {len(dups_ruta)} RUTA(S) DUPLICADA(S) — misma URL+método declarada 2+ veces:")
        for (ruta, metodos) in dups_ruta:
            quienes = [f"{n} (línea {l})" for r, m, n, l in rutas if r == ruta and m == metodos]
            print(f"    {ruta} {list(metodos)}: {', '.join(quienes)}")

    # Reporte 3: nombres de función duplicados (Flask se queja, pero avisamos antes)
    cnt_nombres = Counter(n for n, _ in nombres_funcion)
    dups_nombre = [n for n, c in cnt_nombres.items() if c > 1]
    if dups_nombre:
        problemas += len(dups_nombre)
        print(f"\n⚠ {len(dups_nombre)} NOMBRE(S) DE FUNCIÓN DUPLICADO(S) — el 2º pisa al 1º:")
        for nombre in dups_nombre:
            lineas = [str(l) for n, l in nombres_funcion if n == nombre]
            print(f"    def {nombre}()  en líneas {', '.join(lineas)}")

    # Resumen
    print()
    if problemas == 0:
        print(f"✓ {path}: {len(rutas)} rutas registradas, sin problemas de integridad.")
        return 0
    print(f"✗ {path}: {problemas} problema(s) detectado(s). NO subir a producción hasta corregir.")
    return 1


if __name__ == '__main__':
    path = sys.argv[1] if len(sys.argv) > 1 else 'app.py'
    sys.exit(verificar(path))
