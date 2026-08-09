# ADR-0006 — PostgreSQL y no MariaDB

- **Estado:** propuesto (requiere aprobación)
- **Fecha:** agosto 2026
- **Reabre y confirma:** [ADR-0002](0002-migracion-postgresql.md)

## Contexto

Se pidió evaluar de nuevo el motor destino: "PostgreSQL u otra base como MariaDB que
maneje mejor la concurrencia de peticiones, escrituras simultáneas y escalabilidad".

Lo primero, para sacarlo del medio: **la concurrencia no desempata**. SQLite serializa
las escrituras y ése es el problema real —12 procesos escriben hoy: `app.py` y once
pollers—. Pero tanto PostgreSQL como MariaDB con InnoDB tienen MVCC y bloqueo por fila,
y los dos resuelven ese problema de sobra para el tamaño de Pucará. Elegir por
"concurrencia" es elegir a cara o cruz.

Lo que sí desempata son cinco cosas concretas de **este** código.

## Decisión

**PostgreSQL.**

### 1. Los índices únicos parciales, que MariaDB no tiene

`pucara/models/incidentes.py` declara:

```python
Index("uq_incidente_abierto", "alcance", "referencia", unique=True,
      postgresql_where=text("estado != 'CERRADA'"))
```

Ese índice es la garantía de que **no haya dos incidentes abiertos para el mismo PON**,
y es parcial a propósito: uno total impediría que un PON tuviera dos incidentes a lo
largo del tiempo, que es lo normal. Está documentado en el ADR-0003 y figura en la lista
de errores que no hay que repetir.

**MariaDB no soporta índices parciales ni filtrados.** No hay equivalente. La única
salida sería volver a garantizar la unicidad desde el código de aplicación — con dos
corridas del poller solapadas, que es precisamente el escenario que el índice existe
para cubrir. Sería devolver al código una garantía que hoy da el motor.

Y no es un caso aislado: el diseño de avisos por WhatsApp del [ADR-0005](0005-avisos-masivos-por-whatsapp.md)
necesita otro índice parcial igual (`uq_aviso_en_vuelo`), por el mismo motivo — que dos
operadores no disparen el mismo aviso masivo a la vez.

### 2. El ERP del que se sincroniza YA es PostgreSQL

`sync_pg.py` lee el ERP por `psycopg2`, que ya está en `requirements.txt`. Con MariaDB
habría **dos motores y dos drivers** en el mismo proceso para siempre. Con PostgreSQL de
los dos lados queda además abierta la puerta a `postgres_fdw` para el sync, en vez de
traer todo a Python y volver a escribirlo.

### 3. `ON CONFLICT` ya está en el código, 20 veces

El código usa `ON CONFLICT (...) DO UPDATE` en 20 lugares, y en esta etapa se
reescribieron 8 `INSERT OR REPLACE/IGNORE` a esa misma forma. Es sintaxis **común a
SQLite y PostgreSQL**, y por eso el mismo código corre en los dos motores — que es lo
que hace reversible el corte. MariaDB usa `ON DUPLICATE KEY UPDATE`: habría que
reescribir las 28 y perder la compatibilidad con SQLite, o sea perder la vuelta atrás.

### 4. `timestamptz` de verdad

`UtcDateTime` (en `pucara/db.py`) existe porque SQLite no guarda el desplazamiento
horario. PostgreSQL sí, con `timestamptz`, y ahí el tipo se vuelve casi innecesario.
MariaDB tampoco guarda el offset: el parche tendría que quedarse para siempre.

### 5. La capa de compatibilidad se apoya en cosas que MariaDB no tiene

Lo construido en esta etapa (`sql/compat_sqlite.sql`) reimplementa `datetime()`,
`date()`, `strftime()` y `julianday()` con **funciones variádicas** y PL/pgSQL, y
`group_concat` como agregado propio. MariaDB no tiene funciones variádicas ni permite
definir agregados en SQL puro. La misma estrategia allá sería bastante más fea, o
directamente habría que reescribir las 728 consultas a mano.

## Lo que se pierde eligiendo PostgreSQL

Vale decirlo: MariaDB es más común en hosting compartido y más gente lo ha tocado alguna
vez. No aplica acá — el servidor es propio y el equipo ya opera un PostgreSQL, el del
ERP. No hay una habilidad nueva que aprender.

## Alternativas descartadas

| Alternativa | Por qué no |
|---|---|
| **MariaDB / MySQL** | Sin índices parciales se pierde una garantía que hoy hace cumplir el motor. Además: segundo driver, `ON DUPLICATE KEY` en vez de `ON CONFLICT` (se pierde la vuelta atrás a SQLite), sin `timestamptz`. |
| **Seguir con SQLite en WAL** | WAL da muchos lectores y **un** escritor. Acá hay doce escritores. Es el problema, no la solución. |
| **SQLite + una cola de escritura** | Serializa a mano lo que un motor real hace solo, y suma una pieza que se puede caer. |
| **CockroachDB / Yugabyte** | Compatibles con PostgreSQL pero pensados para escala distribuida. Un ISP regional con ~6.000 clientes no la necesita, y suma operación. |

## Consecuencias

- Se confirma el ADR-0002; no hay que rehacer nada de lo ya decidido.
- Hay que operar PostgreSQL: respaldos con `pg_dump` en vez de la API de respaldo de
  SQLite (`backup_pucara.py` se reescribe).
- El corte es reversible mientras `PUCARA_DB_URL` sea una variable de entorno y el
  archivo SQLite no se toque. Ver `docs/MIGRACION-POSTGRESQL.md`.
