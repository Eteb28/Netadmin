# NetAdmin v9 — Sprint 2 FIX 2

## Bugs que arregla

### Bug crítico — `KeyError: 0` en endpoints

```python
total = con.execute("SELECT COUNT(*) FROM ...").fetchone()[0]
                                                          ^^^
KeyError: 0
```

**Causa**: en SQLite cada fila se puede acceder por nombre (`r['col']`) Y
por índice (`r[0]`). El cursor PG con `RealDictCursor` solo permite por
nombre, así que `r[0]` rompe en muchísimas queries del código viejo.

**Fix**: nueva clase `_HybridRow` en `db.py` que soporta los dos accesos
igual que `sqlite3.Row`. Los `fetchone()` y `fetchall()` ahora devuelven
estos objetos híbridos.

### Bug derivado — `pool exhausted`

Cuando un endpoint rompía antes de cerrar la conexión, la conexión quedaba
"colgada" y al cabo de 10 errores se agotaba el pool. Por eso después
del primer error de `KeyError`, **todo** empezaba a fallar.

**Fix**: con el bug anterior arreglado este desaparece. Además, agregué
en `app.py` un `@app.teardown_request` que cierra las conexiones
automáticamente al final de cada request, aunque haya un error.

### Bug menor — `404 autorefresh.js`

Faltaba el archivo en tu carpeta. Lo incluyo en este zip.

---

## Archivos

```
db.py                          ← reemplazar
app.py                         ← reemplazar
static/js/autorefresh.js       ← reemplazar / agregar
```

## Aplicar

```bash
cd /home/esteban/Documentos/erlan_v8
unzip -o ~/Descargas/erlan_v9_sprint2_fix2.zip

cp erlan_v9_sprint2_fix2/db.py ./
cp erlan_v9_sprint2_fix2/app.py ./
cp erlan_v9_sprint2_fix2/static/js/autorefresh.js static/js/

# Reiniciar la app
# Ctrl+C donde corre y volver a:
source venv/bin/activate
python3 app.py
```

## Probar

Una vez levantada, andá a:

1. **/clientes** → debería listar los clientes paginados (los 6.360)
2. **Dashboard** → debería mostrar los KPIs
3. **Mapa** → debería mostrar clientes y NAPs
4. **NAPs** → la lista de NAPs

Los logs no deberían tener `KeyError: 0` ni `pool exhausted`.

Si todavía algo falla, copiame el log y vemos puntualmente.
