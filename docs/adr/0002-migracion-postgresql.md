# ADR-0002 — Migración a PostgreSQL con SQLAlchemy y Alembic

- **Estado:** propuesto (requiere aprobación)
- **Fecha:** agosto 2026
- **Depende de:** [ADR-0001](0001-arquitectura-en-capas.md)

## Contexto

SQLite serializa las escrituras: con varios operadores y los pollers (OLT, MikroTik,
wireless, sync ERP) escribiendo a la vez, aparecen bloqueos. El objetivo declarado es
soportar miles de clientes y múltiples usuarios simultáneos.

Medición del punto de partida: **729 sentencias SQL**, de las cuales **247 usan
construcciones propias de SQLite** que PostgreSQL no acepta, repartidas en **19 archivos**.

## Decisión

Migrar a **PostgreSQL**, con **SQLAlchemy** como capa de acceso y **Alembic** para versionar
el esquema. La migración se ejecuta **por dominio, detrás de la capa Repository** del
ADR-0001 — nunca como un "cambiar la conexión y rezar".

### Por qué SQLAlchemy y no seguir con SQL crudo

Se pidió expresamente, y además resuelve el problema de fondo: las 247 construcciones
específicas de SQLite existen porque el SQL se escribió contra un motor concreto. Con el ORM,
`datetime('now')` y `NOW()` dejan de ser una decisión de cada consulta.

Se mantiene SQL crudo (vía `text()`) **sólo** para los reportes analíticos pesados, y siempre
dentro de un Repository.

### Orden de ejecución

| Paso | Contenido | Por qué en este orden |
|---|---|---|
| 1 | Alembic + modelos SQLAlchemy del esquema actual | Sin esquema versionado no hay migración reproducible |
| 2 | **Pruebas de caracterización** sobre las consultas críticas | Congela el comportamiento actual **antes** de tocar nada |
| 3 | Script de migración de datos SQLite → PostgreSQL, idempotente | Debe poder correrse muchas veces mientras se ajusta |
| 4 | Migrar dominio por dominio detrás del Repository | Cada uno con sus pruebas en verde |
| 5 | Revisión de índices, claves foráneas y restricciones | Recién con el esquema real en Postgres |
| 6 | Corte definitivo | Cuando todos los dominios estén migrados |

**El paso 2 no es negociable.** Sin pruebas que fijen el comportamiento actual, no hay forma
de saber si una consulta migrada devuelve lo mismo. Es lo que convierte la migración en una
tarea verificable en vez de una apuesta.

### Riesgos específicos detectados

1. **Tipado laxo → estricto.** SQLite acepta `'1'`, `1` y `True` en la misma columna;
   PostgreSQL no. Es el riesgo silencioso: aparece recién al insertar datos reales.
   *Mitigación:* el script de migración valida y normaliza tipos, y reporta cada fila que no
   puede convertir en lugar de descartarla.

2. **Fechas guardadas como texto.** Hoy se usa `datetime('now','localtime')` y las fechas se
   comparan como cadenas. En PostgreSQL pasan a ser `timestamptz`.
   *Mitigación:* definir explícitamente la zona horaria y convertir en la migración.

3. **Los pollers escriben directo a la base.** Los 18 archivos fuera de `app.py` también
   tienen que migrar, o quedan escribiendo en una base que ya no es la fuente de verdad.
   *Mitigación:* migran junto con su dominio, no después.

4. **Ventana de corte.** Los datos siguen entrando mientras se migra.
   *Mitigación:* migración idempotente + una ventana corta de sólo lectura para el corte
   final.

## Consecuencias

**A favor:** concurrencia real, esquema versionado y reversible, tipos y restricciones que
el motor hace cumplir, y base apta para los históricos y analíticas pedidas.

**En contra:** PostgreSQL es una pieza más que operar (respaldos, actualizaciones), y hay que
levantarlo en desarrollo. El backup actual (`backup_pucara.py`, que usa la API de respaldo de
SQLite) debe rehacerse con `pg_dump`.

## Alternativa descartada

**Seguir con SQLite en modo WAL.** Ya está en uso y no alcanza: WAL permite varios lectores
con un escritor, pero acá hay varios escritores concurrentes (pollers + operadores).

## Anexo — lo que se aprendió al ejecutarlo (agosto 2026)

La secuencia completa se ensayó contra un PostgreSQL 16 real. Tres cosas que
esta decisión no había previsto y que ahora son reglas del proyecto:

1. **En PostgreSQL una sentencia fallida aborta la transacción entera.** Todo
   `try/except` alrededor de una consulta necesita un `SAVEPOINT`
   (`Session.begin_nested()`), o una tolerancia inofensiva en SQLite se
   convierte en la pérdida del lote completo. Ya pasó en
   `IncidenteRepository.total_onus_en_pon()`.
2. **Una sesión abierta bloquea cualquier DDL.** En SQLite no pasa nada; en
   PostgreSQL el `ALTER`/`DROP` espera indefinidamente. Afecta a cualquier
   cambio de esquema en caliente.
3. **Los `DEFAULT` traducidos hay que mirarlos entrecomillado por
   entrecomillado.** `DEFAULT 'CURRENT_TIMESTAMP'` se aplica sin error y guarda
   el texto literal en cada fila.

Ninguna de las tres se detecta leyendo el código: aparecieron al ejecutarlo. Por
eso la suite ahora corre contra los dos motores (`PUCARA_TEST_PG_URL`) y no sólo
contra SQLite.
