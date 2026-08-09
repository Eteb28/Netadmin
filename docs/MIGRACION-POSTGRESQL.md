# Corte de motor: SQLite → PostgreSQL

Estado de la migración, qué quedó construido, cómo se verifica y qué falta.

El camino elegido es **corte de motor primero**: que todo Pucará corra sobre PostgreSQL
sin rehacer la arquitectura. La deuda del SQL dentro de las rutas (fase 7 del ROADMAP)
queda para después, ya sin la presión de los bloqueos de escritura.

---

## 1. Por qué esto y no la fase 7 primero

El ADR-0002 propone modelar todo, mover las 728 consultas a Repository y recién ahí
cambiar de motor. Es lo correcto a largo plazo y sigue siendo el destino. Pero tiene un
problema de orden: **la concurrencia no mejora hasta el final**, y el dolor es ahora.

El atajo se apoya en un hecho: las 728 consultas no están escritas contra SQLite *el
motor*, están escritas contra `sqlite3` *la interfaz de Python* — `con.execute(sql, (a,b))`
con marcadores `?`, filas indexables por nombre y por número, `cur.lastrowid`. Si algo
expone esa misma interfaz y por debajo habla con PostgreSQL, las 728 consultas siguen
funcionando sin tocarlas.

Eso es lo que se construyó.

---

## 2. Qué quedó construido

| Archivo | Qué hace |
|---|---|
| `sql/compat_sqlite.sql` | Implementa en PostgreSQL las funciones de SQLite que usa el código: `datetime()`, `sqlite_date()`, `strftime()`, `julianday()`, `group_concat()`, `ifnull()`, y la vista `compat_sqlite_master`. |
| `pucara/compat/dialecto.py` | Traduce lo que no se puede resolver con una función: marcadores `?`, `PRAGMA`, DDL, `LIKE`→`ILIKE`, `IS ?`→`IS NOT DISTINCT FROM`. |
| `pucara/compat/conexion.py` | Conexión con la interfaz de `sqlite3` sobre psycopg2: `execute`, filas por nombre y por índice, `lastrowid`, `executescript`, savepoints por sentencia. |
| `pucara/db.py` → `conexion_sqlite_cruda()` | La apertura de SQLite, que por el ADR-0001 sólo puede vivir acá. |
| `app.py` → `get_db()` | Elige motor según `PUCARA_DB_URL`. Sin la variable, nada cambia. |
| `scripts/generar_esquema_postgres.py` | Genera el DDL PostgreSQL. No se escribe a mano. |
| `scripts/auditar_datos.py` | Audita los **datos** antes del corte: huérfanos, fechas que no son fechas, texto en columnas numéricas. |
| `scripts/comparar_dialectos.py` | Compara cada expresión SQLite contra PostgreSQL y exige el **mismo resultado**. |
| `scripts/verificar_sql.py` | Extrae cada consulta del proyecto y la valida contra un PostgreSQL real con `PREPARE`. |
| `tests/test_compat_dialecto.py` · `tests/test_compat_conexion.py` | 34 pruebas de la capa. |

### La decisión que sostiene todo: las fechas siguen siendo TEXT

Después del corte, **las columnas de fecha siguen siendo `TEXT` en PostgreSQL**. Es
deliberado y es lo que hace viable el atajo:

- El código compara fechas como cadenas (`WHERE fecha >= '2026-01-01'`, `substr(fecha,1,7)`,
  `LIKE '2026-08%'`). Con ISO-8601 eso funciona, porque el orden alfabético coincide con
  el cronológico. Tiparlas como `timestamptz` obligaría a reescribir cientos de
  comparaciones **el mismo día del corte**.
- Saca del camino crítico el riesgo R1 del plan ("fechas guardadas como texto"): los datos
  sucios dejan de bloquear la migración y se limpian después, columna por columna.
- Las funciones de compatibilidad devuelven texto por el mismo motivo.

El tipado correcto se hace en la fase 7, dominio por dominio, con el sistema ya en
PostgreSQL y con pruebas. **Esto es deuda asumida a conciencia, no un descuido.**

### Cómo se conserva el comportamiento

Tres traducciones existen para que **nada cambie** de cara al usuario:

- **`LIKE` → `ILIKE`.** En SQLite `LIKE` ignora mayúsculas; en PostgreSQL no. Sin esto, el
  buscador de clientes dejaría de encontrar "perez" escribiendo "PEREZ" el día del corte.
  (Efecto lateral menor: `ILIKE` también iguala mayúsculas de letras acentuadas, cosa que
  SQLite no hacía. Es más permisivo, no menos.)
- **`IS ?` → `IS NOT DISTINCT FROM ?`.** `snmp_wireless.py` lo usa para buscar el evento
  abierto de una interfaz que puede ser NULL. Con `=`, los eventos del equipo entero
  nunca encontrarían su evento previo y se duplicarían en cada corrida del poller.
- **Savepoint por sentencia.** En PostgreSQL una sentencia fallida aborta la transacción
  entera. En SQLite no, y hay código que depende de eso: `_migrate_columns()` intenta
  agregar columnas que quizá ya existan y sigue de largo. Sin savepoints, el primer
  `ALTER` repetido dejaría inservible el resto del arranque.

---

## 3. Qué está verificado, y con qué

Todo lo de abajo se corrió contra un **PostgreSQL 16 real**, no contra una simulación.

| Verificación | Resultado |
|---|---|
| `pytest tests/ -q` | **170 pasan**, incluidas las 9 reglas de arquitectura y las 34 nuevas |
| `comparar_dialectos.py` | **43/43 expresiones** dan el mismo resultado en SQLite y PostgreSQL, incluida la tolerancia a datos sucios |
| `generar_esquema_postgres.py --aplicar` | **87/87 sentencias** de esquema aplicadas (59 tablas, 28 índices) |
| `verificar_sql.py` | **644 consultas** validadas con `PREPARE` contra PostgreSQL |
| `migrar_a_postgres.py` con datos reales | **46.525 filas** migradas; los conteos coinciden en las 24 tablas |

`comparar_dialectos.py` merece una nota: no comprueba que la consulta *compile*, comprueba
que **devuelva lo mismo**. Es la diferencia entre "anda" y "hace lo que hacía".

### Lo que NO está verificado (y hay que mirar)

`verificar_sql.py` deja 46 consultas rechazadas y 75 armadas dinámicamente. Se reparten así:

- **~35 son deriva de esquema.** Columnas que existen en producción y que **ningún DDL del
  proyecto crea**: `usuarios.permisos` (la usan 23 consultas), `naps.nivel_senal`,
  `naps.red`, `naps.cdo`, `pagos.estado_pago`, `stock_items.modelo`, `redes.activa`,
  `olts.red`. Alguien las agregó a mano en la base productiva y nunca volvieron al código.
  **No es un problema de la migración: es un problema que la migración destapó.**
  Se resuelve generando el esquema con `--desde-db` sobre la base de producción.
- **4 son tipado laxo**, el riesgo real: comparaciones tipo `lat = ''` sobre una columna
  `REAL`. SQLite lo acepta; PostgreSQL no. Hay que reescribirlas a mano (son cuatro).
- **1 es un bug preexistente**: `app.py:5274` dice
  `WHERE tipo_servicio='fibra' IS NOT 1 AND tipo_servicio!='fibra'`. `IS NOT 1` es
  sintaxis de SQLite, y la condición además está repetida. Hay que decidir qué quiso decir.
- **3 son la tabla `config`**, que se consulta pero no la crea ningún DDL.
- **75 son fragmentos** que el código concatena en tiempo de ejecución (`sql += " AND …"`).
  No se pueden validar sin ejecutarlas; hay que probarlas con la aplicación andando.

---

## 4. Runbook del corte

### Antes (se puede hacer hoy, sin ventana)

```bash
# 1. Auditar los DATOS de producción. Limpiar lo que reporte, ANTES del corte.
python3 scripts/auditar_datos.py --db netadmin.db
python3 scripts/auditar_datos.py --db netadmin.db --sql-limpieza > limpiar.sql   # revisar

# 2. Levantar PostgreSQL y crear la base
createdb pucara
psql -d pucara -c "ALTER DATABASE pucara SET pucara.zona = 'America/Argentina/Buenos_Aires';"
psql -d pucara -f sql/compat_sqlite.sql

# 3. Generar el esquema DESDE LA BASE DE PRODUCCIÓN (no desde el código: ver §3)
python3 scripts/generar_esquema_postgres.py --desde-db netadmin.db \
        --salida sql/esquema_postgres.sql --aplicar "dbname=pucara"

# 4. Verificar TODO el SQL del proyecto contra ese esquema
python3 scripts/verificar_sql.py --pg "dbname=pucara" --detalle
#    Repetir hasta que sólo queden los fragmentos dinámicos.

# 5. Ensayo de copia (el sistema sigue andando)
python3 scripts/migrar_a_postgres.py --origen netadmin.db \
        --destino "postgresql:///pucara" --dry-run
```

### El corte (ventana corta)

```bash
sudo systemctl stop pucara
crontab -l > /tmp/cron.bak && crontab -r          # frenar los pollers

sqlite3 netadmin.db ".backup 'netadmin_precorte.db'"   # NO cp: WAL
python3 scripts/migrar_a_postgres.py --origen netadmin.db --destino "postgresql:///pucara"

# La variable es el interruptor
echo 'PUCARA_DB_URL=postgresql://pucara@localhost/pucara' >> /etc/default/pucara
sudo systemctl start pucara
crontab /tmp/cron.bak
```

### Vuelta atrás

Sacar `PUCARA_DB_URL` y reiniciar. **El archivo SQLite no se toca durante el corte**, así
que sigue siendo válido. Ésa es toda la vuelta atrás, y es la razón por la que el camino
de SQLite en el traductor es la identidad: el mismo código corre en los dos motores.

### Después

- `backup_pucara.py` hay que rehacerlo con `pg_dump` — la API de respaldo de SQLite ya no
  aplica.
- Los pollers del cron tienen que arrancar con `venv/bin/python3` **y** con
  `PUCARA_DB_URL` en el entorno. Si no, siguen escribiendo en el SQLite viejo y los datos
  se parten en dos. Es el riesgo operativo más grande del corte, y se suma al problema de
  higiene de crontab que ya está anotado en la deuda técnica.
- Dejar el SQLite en sólo lectura una semana como red de seguridad.

---

## 5. Qué falta para dar el corte por terminado

1. **Correr `auditar_datos.py` y `verificar_sql.py` contra la base de producción real.**
   Todo lo verificado acá se hizo contra el esquema reconstruido desde el código y contra
   un respaldo viejo (`netadmin.db.PRE_SPRINT3.bak`, 24 tablas, 46.525 filas). Los ~35
   rechazos por deriva de esquema deberían desaparecer solos al usar `--desde-db`; hay que
   confirmarlo.
2. **Arreglar las 4 comparaciones de tipado laxo** (`lat = ''` y parientes).
3. **Decidir qué hace `app.py:5274`** y reescribirlo.
4. **Migrar los 11 pollers**: hoy siguen llamando a `sqlite3.connect` por su cuenta. Con
   `PUCARA_DB_URL` puesta tienen que pasar por `pucara.compat.conexion.abrir()`. Es
   mecánico —una línea por archivo— pero es lo que evita que los datos se partan en dos.
5. **Probar las 75 consultas dinámicas** con la aplicación andando sobre PostgreSQL.
6. **Rehacer `backup_pucara.py`** con `pg_dump`.

Recién con 1–6 hechos el corte está listo para producción. Lo construido hasta acá es la
infraestructura y la verificación; lo que falta es correrla contra los datos de verdad.

---

## 6. Después del corte: la fase 7 sigue en pie

Nada de esto reemplaza el ADR-0002. La capa de compatibilidad es **andamio**: cada dominio
que pase a Repository deja de usarla. `verificar_sql.py` sirve de medidor — cuando reporte
cero consultas traducidas, `sql/compat_sqlite.sql` y `pucara/compat/` se borran y queda lo
que el ADR-0001 pedía desde el principio.

La diferencia es que para entonces el sistema ya va a estar corriendo con concurrencia
real, y ese trabajo se podrá hacer sin apuro.
