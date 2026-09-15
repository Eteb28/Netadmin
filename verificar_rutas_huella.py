#!/usr/bin/env python3
"""verificar_rutas_huella.py — Red de seguridad para refactors de app.py.

Genera/compara la 'huella' de la aplicación: todas las rutas con su URL,
métodos HTTP y función asociada. Si un refactor no cambió NADA funcional,
la huella debe ser idéntica.

Uso:
    python3 verificar_rutas_huella.py --guardar   # antes de refactorizar
    python3 verificar_rutas_huella.py --comparar  # después
"""
import sys, json, os

HUELLA = '.huella_rutas.json'

def huella():
    os.environ.setdefault('NETADMIN_DB', '/tmp/_huella_check.db')
    import app
    rutas = {}
    for r in app.app.url_map.iter_rules():
        rutas[str(r)] = {
            'metodos': sorted(m for m in r.methods if m not in ('HEAD', 'OPTIONS')),
            'funcion': r.endpoint,
        }
    return rutas

def main():
    modo = sys.argv[1] if len(sys.argv) > 1 else '--comparar'
    if modo == '--orden':
        return verificar_orden_main()
    actual = huella()
    if modo == '--guardar':
        json.dump(actual, open(HUELLA, 'w'), indent=1, sort_keys=True)
        print(f"✓ Huella guardada: {len(actual)} rutas → {HUELLA}")
        return 0
    if not os.path.exists(HUELLA):
        print(f"✗ No existe {HUELLA}. Corré primero: python3 {sys.argv[0]} --guardar")
        return 1
    previo = json.load(open(HUELLA))
    faltan = sorted(set(previo) - set(actual))
    nuevas = sorted(set(actual) - set(previo))
    cambian = sorted(u for u in set(previo) & set(actual) if previo[u] != actual[u])
    if not (faltan or cambian):
        extra = f" (+{len(nuevas)} nuevas)" if nuevas else ""
        print(f"✓ Huella intacta: las {len(previo)} rutas siguen igual{extra}.")
        return 0
    print(f"✗ La huella CAMBIÓ — no subas a producción:")
    for u in faltan:  print(f"   FALTA:   {u}  [{','.join(previo[u]['metodos'])}]")
    for u in cambian: print(f"   CAMBIÓ:  {u}  {previo[u]} → {actual[u]}")
    return 1

def verificar_orden_main():
    """Detecta el bug de 'if __name__' antes de las funciones que usa.
    Un script con def después de la llamada a main() falla en runtime con
    NameError aunque compile bien. Corré: python3 verificar_rutas_huella.py --orden"""
    import glob, sys
    problemas = []
    for f in glob.glob('*.py'):
        lines = open(f).read().split('\n')
        mains = [i for i,l in enumerate(lines,1) if l.startswith("if __name__")]
        if not mains:
            continue
        mc = mains[0]
        despues = [l.split('(')[0][4:] for i,l in enumerate(lines,1)
                   if l.startswith('def ') and i > mc]
        if despues:
            problemas.append((f, mc, despues))
    if problemas:
        print("✗ Archivos con funciones definidas DESPUÉS de la llamada a main():")
        for f, mc, d in problemas:
            print(f"   {f}: if __name__ en línea {mc}, {len(d)} def después → {d[:4]}")
        return 1
    print("✓ Orden correcto: en todos los scripts el bloque main va al final.")
    return 0


if __name__ == '__main__':
    sys.exit(main())


