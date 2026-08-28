# Estado real de la arquitectura de Pucará

**Fecha:** agosto 2026 · **Autor:** relevamiento previo a la etapa de migración

Este documento existe porque se pidió "revisar toda la documentación del proyecto (ADR,
Arquitectura, Roadmap, Estándares)" antes de implementar. **Esa documentación no existía.**
Antes de escribirla hacía falta medir el punto de partida real, porque varias premisas de
la planificación no se sostienen contra el código.

Todos los números son verificables con los comandos indicados.

---

## 1. Lo que se asumía vs. lo que hay

| Premisa de la planificación | Estado real | Evidencia |
|---|---|---|
| Existen ADR, Arquitectura, Roadmap, Estándares | **No existen** | `docs/` sólo tiene `MAPEO_ERP_SOPORTES.md` y un `.mtd` del ERP |
| "Toda consulta deberá **seguir** pasando por Repository" | **No hay capa Repository** | `grep -rn "class .*Repository" --include=*.py` → 0 resultados |
| "Toda lógica de negocio deberá permanecer en Services" | **No hay capa Service** | `grep -rn "class .*Service" --include=*.py` → 0 resultados |
| Se usan DTO | **No hay DTO ni dataclasses** | `grep -rn "@dataclass" --include=*.py` → 0 resultados |
| Separación Controller → Service → Repository → DB | **No existe**: el SQL vive dentro de las rutas Flask | 729 `.execute()` en `app.py`, junto a 281 `@app.route` |
| "No quiero SQL distribuido por el proyecto" | **El SQL ya está distribuido** | 19 archivos abren la base con `sqlite3.connect` |
| "Mantener la máquina de estados implementada anteriormente" | **Existe, pero no donde se cree** | Ver sección 3 |
| Migración con SQLAlchemy + Alembic "si aún no está implementado" | **Correcto: no está** | `requirements.txt` = flask, werkzeug, reportlab, psycopg2-binary |
| Hay pruebas | **No hay ninguna** | 0 archivos `test_*.py` |

### Cómo verificarlo

```bash
grep -c "@app.route" app.py          # 281 rutas
grep -c "\.execute(" app.py          # 729 sentencias SQL
wc -l app.py                         # 9.858 líneas
grep -rln "sqlite3.connect" --include=*.py .   # 19 archivos
find . -iname "test_*.py" | wc -l    # 0
```

**Conclusión:** Pucará hoy es un monolito de una sola capa donde el SQL está embebido en los
manejadores HTTP. Funciona y está en producción, pero no tiene la arquitectura que la
planificación da por existente. **Esto no es una crítica al proyecto** — es el punto de
partida que hay que reconocer para no construir sobre una base imaginaria.

---

## 2. Por qué esto cambia el plan (y no sólo el cronograma)

Tres consecuencias concretas:

**a) "Que la capa Repository siga funcionando sin modificar la lógica de negocio" no es
posible tal como está planteado.** No hay Repository que preservar ni lógica de negocio
separada que dejar intacta: hoy la lógica de negocio *es* el SQL dentro de la ruta. Crear la
capa **es** el trabajo, no un efecto colateral de la migración.

**b) La migración a PostgreSQL no es un cambio de conexión.** Hay **247 construcciones SQL
propias de SQLite** que PostgreSQL no acepta o interpreta distinto:

| Construcción | Ocurrencias | Qué pasa en PostgreSQL |
|---|---|---|
| `datetime('now','localtime')` | 63 | No existe → `NOW()` / `CURRENT_TIMESTAMP` |
| `date('now',...)` | 50 | No existe |
| `strftime(...)` | 42 | No existe → `TO_CHAR()` |
| `AUTOINCREMENT` | 43 | No existe → `SERIAL` / `IDENTITY` |
| `PRAGMA ...` | 28 | No existe |
| `julianday(...)` | 16 | No existe → aritmética de `date` |
| `INSERT OR REPLACE` / `OR IGNORE` | 5 | → `ON CONFLICT ... DO UPDATE / DO NOTHING` |

Además, SQLite es de tipado laxo y PostgreSQL es estricto: columnas que hoy guardan `'1'`,
`1` y `True` indistintamente van a fallar al insertar. Ese es el riesgo silencioso de la
migración, y sólo se detecta con datos reales.

**c) Migrar 729 consultas a mano, sin pruebas, sobre un sistema en producción, es la forma
más segura de romper algo.** Hoy no hay una sola prueba que avise si una consulta migrada
devuelve otra cosa. **Las pruebas no van al final: son lo que hace posible la migración.**

---

## 3. La máquina de estados que sí existe

`snmp_wireless.procesar_evento()` implementa un ciclo `inicio → activo → recuperado` y evita
duplicar alertas mientras el problema persiste. **Pero es para eventos de equipos
inalámbricos de torre** (`snmp_eventos`: LAN a 10 Mbps, puerto caído, AP sin responder).

**No cubre incidencias FTTH/ONU**, que es donde se pidió el cierre automático y la detección
de eventos masivos. Ahí el flujo actual es distinto: `detectar_alertas_infra()` en
`olt_poller.py` trabaja sobre `alertas_infra` con otra lógica.

O sea: hay **dos mecanismos de eventos distintos y desconectados**. El pedido de "mantener la
máquina de estados implementada anteriormente" sólo tiene sentido si primero se unifican.
Ese es el contenido del ADR-0003.

---

## 4. Lo que sí está sólido y conviene conservar

El relevamiento no es sólo deuda. Estas decisiones ya tomadas están bien y el rediseño debe
respetarlas:

- **Permisos por rol validados en el servidor** (no sólo ocultando botones en pantalla).
- **Motor de eventos con histéresis** en el lado wireless: el concepto es correcto y es la
  base sobre la que unificar.
- **Lecturas parciales que no concluyen "todo se cayó"**: aprendido en producción, ya
  implementado en el poller de OLT. Es una regla de oro que debe sobrevivir a la migración.
- **Separación por dominio en el frontend** (`static/js/*.js` por módulo) y en las
  plantillas (`templates/partials/pages/`). El backend debería imitar esa organización.
