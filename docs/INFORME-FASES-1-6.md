# Informe técnico — Fases 1 a 6 (completas)

**Pruebas:** 169 en verde · **Migraciones Alembic:** 3, aplicadas y verificadas reversibles
· **Rutas totales de la app:** 297 (281 heredadas + 16 nuevas bajo `/api/v2`)

---

## Qué se implementó

### Fase 1 — Fundaciones

| Componente | Archivo | Nota |
|---|---|---|
| Configuración de base | `pucara/db.py` | Punto único de conexión. URL por `PUCARA_DB_URL` |
| Tipo `UtcDateTime` | `pucara/db.py` | Ver "hallazgos" |
| Alembic | `migrations/` | Migración inicial + carga de catálogos, reversibles |
| Estructura en capas | `pucara/{models,repositories,services,adaptadores,api,dto}` | ADR-0001 |
| Punto de ensamblado | `pucara/services/factory.py` | La API no conoce repositorios |
| Control de acceso | `pucara/api/seguridad.py` | ADR-0004 |
| **Reglas de arquitectura como prueba** | `tests/test_arquitectura.py` | 9 reglas verificadas en CI |

La última es la más importante a largo plazo: "no dejar SQL fuera del Repository" pasa de ser
una intención a una prueba que falla. Ya sirvió tres veces (ver hallazgos).

### Fases 2 y 3 — Reclamos y analítica

- Modelos: `Reclamo`, `CausaReclamo`, `ResolucionReclamo` (catálogos **administrables**, no
  listas en el código), con las 16 causas y 18 resoluciones del pedido **precargadas** por una
  migración de datos idempotente (`pucara/seeds.py`).
- Repositorios con las agregaciones resueltas en la base.
- `ServicioReclamos`: alta, cierre y estadísticas por cliente (total, por causa, por
  resolución, MTTR, MTBF, últimos).
- `ServicioAnaliticaReclamos`: MTTR global, top de clientes, APs, PON y OLT, y tasa de
  resolución por técnico. Los rankings muestran **nombres**, no ids.
- API bajo `/api/v2/reclamos` (8 rutas).
- **Frontend:** pestaña "📋 Reclamos" en el modal del cliente (alta, cierre, KPIs, gráficos por
  causa y resolución, historial), tarjeta de analítica en la sección Reclamos y ABM de los
  catálogos en Configuración.

### Fase 4 — Motor unificado de incidentes

`MotorIncidentes` implementa la máquina de estados del ADR-0003:

- `ACTIVA → RECUPERADA → CERRADA`, con **cierre automático por estabilidad sostenida**
  (5 minutos configurables) y registro de `Sistema` / `Recuperación automática`.
- **No duplica**: si el incidente ya existe, no crea otro. Si vuelve a caer tras recuperarse,
  **suma un ciclo** en vez de abrir uno nuevo.
- **Eventos masivos**: correlaciona por PON (umbral absoluto o porcentual) y crea **un**
  incidente con N afectados en lugar de N incidentes.
- **Causa probable** inferida de los motivos que reporta la OLT.
- **Lectura parcial**: un sondeo truncado no abre incidentes (sí procesa recuperaciones).

**Conectado al poller real** (`pucara/adaptadores/incidentes_olt.py`): `olt_poller.py` acumula
una lectura por ONU y al final del ciclo se la pasa al motor. Corre **en paralelo** al sistema
de alertas actual durante la transición, para poder comparar qué detecta cada uno sobre los
mismos datos antes de apagar el viejo.

### Extra — Imágenes en las notas de "Mis Tareas"

Las notas admiten capturas de pantalla: pegadas con Ctrl+V, arrastradas con el mouse o elegidas
con el botón 📎. Dominio nuevo completo (`models/adjuntos.py`, `repositories/adjuntos.py`,
`services/adjuntos.py`, `api/adjuntos.py`) más `pucara/almacen.py`, que aísla el disco para que
el servicio no sepa de rutas ni de `open()`.

Decisiones que importan:

- **Los bytes van al disco, no a la base.** Una captura pesa entre 100 KB y 2 MB; en SQLite
  haría que cualquier `SELECT *` sobre las notas arrastre megabytes y que el backup diario
  crezca sin control.
- **El tipo se detecta por los bytes reales**, no por el `Content-Type` ni la extensión, que los
  elige el cliente y no prueban nada. Un ZIP renombrado a `.png` se rechaza.
- **SVG queda afuera** aunque sea una imagen: es XML y puede contener `<script>`.
- **El nombre en disco lo genera el servidor** (UUID). Si viniera del navegador,
  `../../../app.py` pisaría código.
- **Cada operación verifica la pertenencia, incluida la descarga.** Conocer el id de un adjunto
  no alcanza para verlo. Responde 404 y no 403: un 403 confirmaría que existe y es de otro.
- Al borrar una nota se borran sus imágenes del disco, y se hace **antes** de borrar la nota,
  porque la verificación de pertenencia necesita que la nota todavía exista.

38 pruebas, incluidas las de un ZIP disfrazado de PNG, el intento de escapar del directorio y
el aislamiento entre usuarios.

### Extra — Corrección de coordenadas de NAPs

Varias NAPs quedaron mal georreferenciadas. Ahora se corrigen desde el mapa por tres caminos:
botón **📍 Editar ubicación / datos** en el globo, chip **📍 Reubicar NAPs** que vuelve los
marcadores arrastrables, y botón **📍 Elegir en el mapa** dentro del modal de la NAP.

Detrás hay un endpoint acotado, `PUT /api/v2/naps/<id>/ubicacion`, que toca **sólo** `lat` y
`lng`. No se reutilizó el `PUT /api/naps/<id>` heredado porque reescribe la fila entera y exige
el payload completo: mandarle sólo las coordenadas habría borrado descripción, localidad, red y
CDO. Además el heredado sólo pide `@login_required` —sin permiso de edición— y no deja rastro;
el nuevo exige `naps/editar` y **audita el antes, el después y los metros movidos**.

Valida el rango de la coordenada y **avisa** (sin bloquear) cuando cae fuera de la zona de
cobertura: el error más común al cargar coordenadas a mano es invertir latitud y longitud, y
`(-31.7, -60.5)` al revés da un punto en el Atlántico Sur.

### Fase 5 — Antigüedad y churn

`ServicioAntiguedad`: permanencia media (activos y bajas por separado), distribución por los
tramos pedidos, altas/bajas por mes, churn mensual y anual. Pantalla propia
(**Clientes → Antigüedad y churn**) con KPIs, distribución, serie de churn y comparativa
altas/bajas mes a mes.

### Fase 6 — Pendientes de rescisión (**solo lectura**, según la corrección)

`ServicioRescisiones` lista las ONU todavía registradas en la OLT cuyo cliente está en
`rescision`, `pte_rescision` o `baja`, con cliente, estado comercial, OLT, PON, ONU, serial,
fecha, días desde el cambio y si sigue activa. Ordena por antigüedad y marca las que llevan
más de 90 días.

**Reemplaza** al listado anterior (`/api/onus/limpieza`), que sólo veía `baja` y `rescision`.
La ruta vieja se retiró para no dejar dos versiones de la misma consulta divergiendo.

La pantalla permite **seleccionar varios** y copiarlos o exportarlos a CSV para llevarlos a la
sesión de la OLT, con la advertencia visible de que **Pucará no ejecuta ninguna baja**. Que sea
sólo lectura está verificado por dos pruebas de arquitectura y una de integración
(cualquier verbo de escritura devuelve 405).

---

## Hallazgos durante la implementación

**1. Las rutas nuevas estaban sin autenticar.** Los blueprints de `/api/v2` no usaban los
decoradores de `app.py` —no pueden, sin invertir la dependencia— y quedaron accesibles **sin
sesión**: padrón completo, seriales de ONU y estadísticas comerciales. Se detectó antes de
desplegar. Solución en el ADR-0004: `proteger()` a nivel de blueprint, con el motor de
permisos de `app.py` inyectado. Hay una prueba que falla si un blueprint nuevo no lo llama.

**2. Colisión de nombre de tabla con el espejo de Tero.** El modelo `Reclamo` se llamaba
`reclamos`, que es la tabla donde se replican los tickets de Tero HelpDesk. En una base nueva
Alembic la creaba primero y después `init_db()` la daba por existente
(`CREATE TABLE IF NOT EXISTS`), dejando la sincronización de Tero rota; en la base actual, al
revés, la migración fallaba. Se renombró a `reclamos_tecnicos` y hay una prueba
(`test_convivencia_legado.py`) que compara los modelos contra **todas** las tablas que crea
`app.py`.

**3. Las pruebas encontraron un bug real de portabilidad.** Con `DateTime(timezone=True)`,
SQLite devuelve fechas **sin** zona horaria y cualquier resta contra un `datetime` con zona
falla. Rompía MTTR y MTBF. Se resolvió con el tipo `UtcDateTime`, que de paso deja el cálculo
de duraciones **idéntico antes y después de migrar a PostgreSQL**.

**4. La prueba de arquitectura detectó dos violaciones propias.** La API importando
repositorios directamente (obligó a crear `services/factory.py`) y, después, la vista de
rescisiones alcanzando un atributo privado del servicio. La segunda generó una regla nueva.

**5. El ranking de PON sumaba puertos distintos.** Agrupaba sólo por número de PON: el PON 1 de
la OLT de Crespo se sumaba con el PON 1 de la de El Pingo. Se agrupa por el par `(olt, pon)`.

**6. La auditoría de los módulos nuevos no se escribía, y nadie se enteraba.** El primer diseño
inyectaba la función `log()` de `app.py` como callback, igual que el autorizador del ADR-0004.
No funciona: `log()` abre su **propia** conexión sqlite3, y llamarla desde adentro de un
`with sesion()` con una escritura pendiente da `database is locked`. El `except: pass` que tiene
`log()` se comía el error, así que la operación devolvía 200 y el registro no existía. Se detectó
con una prueba de humo contra la aplicación real, no con las unitarias. Ahora la auditoría se
escribe **por la misma sesión** (`repositories/auditoria.py`), lo que además la mete en la misma
transacción: si el cambio se revierte, la constancia también. Hay una prueba que lo verifica.

**7. Corregí un índice mal diseñado antes de que llegara a producción.** El índice único de
incidentes abiertos era total sobre `(alcance, referencia)`, lo que habría impedido que un
mismo PON tuviera dos incidentes a lo largo del tiempo. Debía ser **parcial**.

---

## Qué falta

- **Motivo de caída por SNMP.** El motor distingue corte eléctrico de corte de fibra a partir
  del motivo que reporta la OLT (`Power Off` / `Onu Los`), pero ese OID **todavía no se lee**:
  hace falta confirmarlo contra un walk del equipo. Sin él la causa queda en `DESCONOCIDA` y
  todo lo demás funciona igual. No se adivinó el OID a propósito: adivinar uno fue exactamente
  lo que causó la regresión de temperatura en las V1600G1-B.
- **Migrar el historial de `snmp_eventos` y `alertas_infra`** a la tabla unificada. Se hará al
  apagar el sistema de alertas viejo, no antes: mientras los dos corran en paralelo, cada uno
  usa su tabla.

**Deuda consciente:** `repositories/clientes.py` e `incidentes.py` usan SQL explícito sobre las
tablas heredadas (`clientes`, `onu_senal`, `olts`), que todavía no tienen modelo. Está
**dentro** del Repository, que es donde el ADR-0001 lo permite, y se elimina en la fase 7.

---

## Riesgos

| # | Riesgo | Estado |
|---|---|---|
| R1 | Que el motor de incidentes se comporte distinto al actual | Mitigado: 24 pruebas y **corre en paralelo** al sistema viejo, sin reemplazarlo todavía |
| R2 | Que la migración de `snmp_eventos`/`alertas_infra` pierda historial | **Abierto** — se resuelve al apagar el sistema viejo |
| R3 | Fechas heredadas guardadas como texto | Contenido: `_a_fecha()` tolera formatos inválidos. Es el riesgo principal de la fase 8 |
| R4 | Que el módulo nuevo impida arrancar el sistema | Mitigado: el registro de los blueprints está en `try/except` |
| R5 | Que alguien agregue una ruta `/api/v2` sin protegerla | Mitigado: prueba automática |

---

## Compatibilidad

- **Convive con el sistema actual.** Verificado: `app.py` arranca con 291 rutas — las 281
  heredadas intactas más 10 nuevas bajo `/api/v2`.
- **Preparado para PostgreSQL.** Todo el código nuevo usa SQLAlchemy; el cambio de motor es la
  variable `PUCARA_DB_URL`. Ver [PREPARACION-FASES-7-8](PREPARACION-FASES-7-8.md).
- **Las migraciones no tocan las tablas heredadas**: `env.py` las excluye explícitamente.

---

## Cómo probarlo

```bash
pip install -r requirements.txt
python3 -m pytest tests/ -q              # 169 pruebas
python3 -m alembic upgrade head          # tablas nuevas + catálogos precargados
python3 -m alembic downgrade base        # y las revierte

python3 scripts/auditoria_portabilidad.py --db netadmin.db   # inventario de la fase 8
```
