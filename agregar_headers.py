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
agregar_headers.py — Agrega el encabezado de licencia AGPLv3 a cada archivo
fuente (.py y .js) del proyecto. Es idempotente: si un archivo ya tiene el
encabezado, lo saltea. Respeta la línea shebang (#!/usr/bin/env python3).

Uso:
    cd ~/Pucara-git            # la raíz del repo
    python3 agregar_headers.py            # aplica a todo el repo
    python3 agregar_headers.py --dry-run  # solo muestra qué haría, sin tocar nada

Ajustá AUTOR y ANIO abajo si hace falta.
"""
import os
import sys

AUTOR = "Esteban Aguiar"
ANIO = "2026"
PROYECTO = "Pucará — Sistema de gestión para ISP"

# Directorios a ignorar
IGNORAR_DIRS = {'.git', 'venv', '.venv', 'env', 'node_modules', '__pycache__',
                'backups', 'uploads', 'dist', 'build'}

# Texto base del encabezado (sin comentar)
LINEAS = [
    f"{PROYECTO}",
    f"Copyright (C) {ANIO} {AUTOR}",
    "",
    "This program is free software: you can redistribute it and/or modify",
    "it under the terms of the GNU Affero General Public License as published by",
    "the Free Software Foundation, either version 3 of the License, or",
    "(at your option) any later version.",
    "",
    "This program is distributed in the hope that it will be useful,",
    "but WITHOUT ANY WARRANTY; without even the implied warranty of",
    "MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the",
    "GNU Affero General Public License for more details.",
    "",
    "You should have received a copy of the GNU Affero General Public License",
    "along with this program. If not, see <https://www.gnu.org/licenses/>.",
]

def header_py():
    return "\n".join("# " + l if l else "#" for l in LINEAS) + "\n"

def header_js():
    cuerpo = "\n".join(" * " + l if l else " *" for l in LINEAS)
    return "/*\n" + cuerpo + "\n */\n"

def ya_tiene(contenido):
    # Chequea las primeras ~30 líneas
    cabeza = "\n".join(contenido.splitlines()[:30])
    return "GNU Affero General Public License" in cabeza

def procesar(path, dry):
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        contenido = f.read()
    if ya_tiene(contenido):
        return 'ya'
    ext = os.path.splitext(path)[1]
    header = header_py() if ext == '.py' else header_js()
    lineas = contenido.split('\n', 1)
    # Preservar shebang si existe
    if contenido.startswith('#!'):
        shebang = lineas[0] + '\n'
        resto = lineas[1] if len(lineas) > 1 else ''
        nuevo = shebang + header + '\n' + resto
    else:
        nuevo = header + '\n' + contenido
    if not dry:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(nuevo)
    return 'agregado'

def main():
    dry = '--dry-run' in sys.argv
    raiz = '.'
    agregados = saltados = 0
    for dirpath, dirnames, filenames in os.walk(raiz):
        dirnames[:] = [d for d in dirnames if d not in IGNORAR_DIRS]
        for fn in filenames:
            if not (fn.endswith('.py') or fn.endswith('.js')):
                continue
            if fn.endswith('.min.js'):
                continue
            # No agregarse a sí mismo el header no es necesario, pero es inofensivo
            path = os.path.join(dirpath, fn)
            r = procesar(path, dry)
            if r == 'agregado':
                print(f"  {'[dry] ' if dry else ''}+ header → {path}")
                agregados += 1
            else:
                saltados += 1
    print()
    print(f"{'(simulacro) ' if dry else ''}Headers agregados: {agregados} · ya tenían: {saltados}")
    if dry:
        print("Corré sin --dry-run para aplicarlo de verdad.")

if __name__ == '__main__':
    main()
