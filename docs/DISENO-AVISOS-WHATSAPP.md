# Diseño técnico — Avisos masivos por WhatsApp

**Fase 9 propuesta.** Complementa el [ADR-0005](adr/0005-avisos-masivos-por-whatsapp.md),
que es donde están las decisiones y su justificación. Acá está el cómo.

Nada de esto está implementado todavía: es el documento que se pone a aprobación antes de
escribir código, como pide la regla "analizá → diseñá → documentá → esperá aprobación →
recién ahí implementá".

---

## 1. Qué se reutiliza (y qué no hay que volver a escribir)

| Ya existe | Se usa para |
|---|---|
| `pucara/services/incidentes.py` — motor fase 4 | Detectar la caída masiva y saber quiénes cayeron. **No se toca.** |
| `incidentes` / `incidente_afectados` | Origen del padrón: `cliente_id`, `nro_cliente`, `motivo_caida` |
| `clientes.telefono`, `clientes.telefono2` | Los teléfonos (los llena `sync_pg.py` desde el ERP) |
| `causa_probable` (`CORTE_ELECTRICO` / `CORTE_FIBRA`) | Sugerir la plantilla y precargar el texto de la causa |
| `enviar_telegram()` de `app.py` | Avisarle al NOC que hay un borrador esperando aprobación |
| `proteger(bp, modulo)` de `pucara/api/seguridad.py` | Autenticar el blueprint entero |
| `static/js/v2_widgets.js` | KPIs, tablas y barras del panel — no se reescriben |
| Patrón de poller + cron + `flock` | El worker de despacho sigue el mismo patrón |

**Lo único realmente nuevo** es: el padrón de destinatarios, la máquina de estados de la
campaña, el adaptador de Meta, el worker y el panel.

---

## 2. Modelo de datos

Cuatro tablas nuevas, versionadas por Alembic. **Los nombres están verificados contra las
`CREATE TABLE` de `app.py`: ninguno choca** (existe `notificaciones`, que es el aviso interno
en pantalla y no tiene nada que ver; por eso el prefijo es `aviso_`).

```
avisos_masivos ──┬── aviso_destinatarios   (1:N, cascade)
                 └── aviso_plantillas      (N:1)
aviso_optout     (independiente, por teléfono)
```

### `aviso_plantillas`

Espejo local de las plantillas aprobadas en Meta. Existe para que el panel pueda mostrar la
vista previa y validar las variables sin salir a preguntarle a Meta en cada carga.

| Campo | Tipo | Notas |
|---|---|---|
| `id` | int PK | |
| `nombre` | str(120) | el `name` exacto registrado en Meta |
| `idioma` | str(10) | `es_AR` |
| `categoria` | enum | `UTILITY` / `SERVICE` (nunca `MARKETING` para cortes) |
| `cuerpo` | text | el texto con `{{1}}`, `{{2}}`… tal cual quedó aprobado |
| `variables` | JSON | `[{"n":1,"etiqueta":"Zona","ejemplo":"El Pingo"}, …]` |
| `estado` | enum | `PENDIENTE` / `APROBADA` / `RECHAZADA` / `PAUSADA` |
| `activa` | bool | si aparece en el selector del panel |
| `sincronizada` | UtcDateTime | última vez que se contrastó contra Meta |

Un aviso **sólo puede aprobarse con una plantilla `APROBADA` y `activa`**. Se valida en el
servicio, no en el frontend.

### `avisos_masivos`

La campaña. Un incidente puede tener varios a lo largo de su vida (inicial → actualización →
normalizado), pero **uno solo en vuelo a la vez**.

| Campo | Tipo | Notas |
|---|---|---|
| `id` | int PK | |
| `incidente_id` | int FK nullable | nullable a propósito: también sirve para avisos manuales (corte programado) sin incidente |
| `plantilla_id` | int FK | |
| `variables` | JSON | valores que completan los `{{n}}` |
| `estado` | enum | ver máquina de estados |
| `alcance_descripcion` | str(200) | "El Pingo — PON 5", congelado al armar el padrón |
| `creado_por` / `creado` | str(80) / UtcDateTime | |
| `aprobado_por` / `aprobado_en` | str(80) / UtcDateTime | la firma del que apretó el gatillo |
| `motivo_cancelacion` | str(200) nullable | |
| `total`, `enviados`, `fallidos`, `omitidos` | int | contadores materializados, para no recontar 300 filas en cada refresh del panel |
| `es_prueba` | bool | envío al equipo, no cuenta como aviso real |

Índice único **parcial** —la lección del ADR-0003 aplicada de nuevo—:

```sql
CREATE UNIQUE INDEX uq_aviso_en_vuelo ON avisos_masivos (incidente_id)
WHERE estado IN ('PENDIENTE_APROBACION','APROBADO','ENVIANDO') AND es_prueba = 0;
```

Parcial y no total: el mismo incidente **tiene que** poder tener el aviso inicial ya enviado
y después el de normalización. Lo que no puede haber es dos sin terminar al mismo tiempo.

### `aviso_destinatarios`

Una fila por persona. Es el diario del envío y lo que hace al worker retomable.

| Campo | Tipo | Notas |
|---|---|---|
| `id` | int PK | |
| `aviso_id` | int FK cascade | |
| `cliente_id`, `nro_cliente`, `nombre` | | congelados al armar el padrón, para que el historial no cambie si después se edita el cliente |
| `telefono_e164` | str(20) | ya normalizado; el original queda en `telefono_origen` |
| `telefono_origen` | str(40) | lo que había en la base, para poder auditar la normalización |
| `estado` | enum | `PENDIENTE` → `ENVIADO` → `ENTREGADO` → `LEIDO`, o `FALLIDO` / `OMITIDO` |
| `motivo_omision` | str(40) nullable | `telefono_invalido` / `sin_telefono` / `opt_out` / `duplicado` |
| `wa_message_id` | str(80) nullable | el id que devuelve Meta; con eso se casan los webhooks |
| `error_codigo`, `error_detalle` | | tal cual los devuelve Meta, sin interpretar |
| `intentos` | int | |
| `enviado_en`, `actualizado_en` | UtcDateTime | |

Único `(aviso_id, telefono_e164)`: **dos clientes del mismo hogar con el mismo teléfono
reciben un solo mensaje**. El segundo queda `OMITIDO / duplicado`, visible.

### `aviso_optout`

`telefono_e164` (PK), `origen` (`respuesta_baja` / `manual`), `fecha`, `usuario`.

No es un lujo: si la gente bloquea o reporta, Meta baja la calificación del número y termina
limitando el envío. Respetar la baja es lo que mantiene el canal vivo. Se alimenta del
webhook (cuando alguien responde "BAJA") y a mano desde el panel.

### Máquina de estados de la campaña

```
                     ┌──────────── cancelar ────────────┐
                     ▼                                  │
BORRADOR ──► PENDIENTE_APROBACION ──► APROBADO ──► ENVIANDO ──► ENVIADO
   │                                     ▲                          │
   └──── (armado del padrón) ────────────┘                    (parcial si hubo fallidos)
```

- `BORRADOR`: lo crea el sistema al detectar la caída masiva, o el operador a mano. Todavía
  no tiene plantilla ni variables.
- `PENDIENTE_APROBACION`: tiene plantilla, variables y padrón congelado. Es lo que se ve en
  la vista previa.
- `APROBADO`: alguien firmó. **Acá se aplican todas las validaciones duras** (ver §4).
- `ENVIANDO`: el worker lo tomó.
- `ENVIADO`: no quedan destinatarios `PENDIENTE`. Si hubo fallidos, queda con el contador y
  el panel ofrece reintentar sólo esos.
- `CANCELADO`: sólo desde `BORRADOR` o `PENDIENTE_APROBACION`. **Una vez que empezó a salir,
  no se cancela**: se puede frenar el resto (`ENVIADO` parcial), pero lo que salió, salió.
  El panel tiene que decirlo con esas palabras.

### Migración

Una sola revisión de Alembic encadenada a `d0813c9d86cb`, con `downgrade()` que borra las
cuatro tablas. Se verifica reversible (`upgrade` → `downgrade` → `upgrade`) como pide la
definición de terminado. Fechas con `UtcDateTime`, enums con `native_enum=False` — igual que
`incidentes`, para que la fase 8 no encuentre sorpresas al pasar a PostgreSQL.

---

## 3. Estructura del código

Respeta el ADR-0001 sin excepciones ni permisos especiales:

```
pucara/
├── models/avisos.py                 ~180 líneas   las 4 tablas
├── repositories/avisos.py           ~200 líneas   avisos, destinatarios, plantillas, opt-out
├── repositories/contactos.py        ~120 líneas   teléfonos de los afectados (SQL crudo sobre
│                                                  `clientes`, permitido dentro del Repository)
├── services/telefonos.py            ~120 líneas   normalización E.164 argentina — función pura
├── services/avisos.py               ~280 líneas   padrón, máquina de estados, validaciones
├── services/despacho.py             ~150 líneas   el bucle de envío contra el Protocol
├── adaptadores/whatsapp_cloud.py    ~180 líneas   HTTP contra Meta. Único lugar con `requests`
├── api/avisos.py                    ~200 líneas   blueprint /api/v2, `proteger(bp, "avisos")`
└── dto/avisos.py                    ~80 líneas    lo que ve el panel
avisos_worker.py                     ~90 líneas    entrada por cron, con flock
```

Ninguno supera las 500 líneas (regla 7). El servicio no importa Flask (regla 1) ni arma
consultas (regla 2). La API no importa repositorios (regla 3).

### El punto fino: el servicio no puede hablar HTTP

El envío es I/O contra un tercero, pero la regla dice que los servicios no conocen HTTP. Se
resuelve con un `Protocol` declarado **en la capa de servicio** e implementado **en
adaptadores**:

```python
# pucara/services/despacho.py
class ProveedorWhatsApp(Protocol):
    def enviar_plantilla(
        self, telefono_e164: str, plantilla: str, idioma: str, variables: list[str]
    ) -> ResultadoEnvio: ...
```

`ResultadoEnvio` es un dataclass con `ok`, `wa_message_id`, `codigo`, `detalle` y
`reintentable`. El servicio decide qué hacer con cada resultado; el adaptador decide cómo
hablar con Meta. En las pruebas se inyecta un `ProveedorFalso` y **no se toca la red**, que
es lo que permite probar reintentos, 429 y errores permanentes de forma determinista.

Distinguir **reintentable** de **permanente** es lo que evita dos desastres opuestos: quemar
el cupo reintentando un número que no existe, y dar por fallido a alguien porque Meta tuvo un
hipo de 500.

---

## 4. Reglas de negocio que hace cumplir el servicio

Todas se validan en `ServicioAvisos.aprobar()`, del lado del servidor. El frontend las
muestra deshabilitadas, pero **no es el frontend el que las hace cumplir**.

| Regla | Por qué |
|---|---|
| La plantilla tiene que estar `APROBADA` y `activa` | Meta rechaza el envío igual; mejor fallar antes y con un mensaje claro |
| Todas las variables `{{n}}` completas y sin saltos de línea ni tabs | Meta rechaza los parámetros con saltos de línea |
| El incidente **no** puede venir de un sondeo con lectura parcial | La regla de oro del proyecto, llevada al canal más caro de equivocarse |
| El incidente tiene que tener ≥ `minutos_minimos` de vida (10 por defecto) | No avisar por un parpadeo |
| Ningún otro aviso del mismo incidente en vuelo | El índice único parcial lo garantiza; el servicio devuelve 409 con un mensaje entendible |
| Ventana horaria 07:00–23:00 salvo `forzar=true` de un admin | Un WhatsApp a las 3 AM molesta más de lo que ayuda |
| ≤ `tope_destinatarios` (500 por defecto) o rol admin | Techo de daño ante un falso positivo |
| El usuario tiene el flag `puede_aprobar_avisos` | Redactar y disparar son dos permisos distintos |
| La plantilla se probó al menos una vez (envío de prueba) | La primera vez que se usa una plantilla es cuando se descubre que quedó mal redactada |

### Armado del padrón (`ServicioAvisos.armar_padron`)

1. Trae los afectados del incidente (`incidente_afectados`).
2. Para cada `cliente_id`, trae `nombre`, `telefono`, `telefono2` (Repository de contactos).
3. Normaliza cada teléfono a E.164. Se prefiere `telefono`; si no valida, se intenta
   `telefono2`.
4. Marca `OMITIDO` con motivo: `sin_telefono`, `telefono_invalido`, `opt_out`, `duplicado`.
5. Congela nombre y número en la fila: el historial no puede cambiar retroactivamente porque
   alguien editó la ficha del cliente tres meses después.

El panel muestra los cuatro motivos de omisión con su lista. **Los `telefono_invalido` son
una tarea para Atención al Cliente**, y esa lista sola ya vale lo que cuesta el módulo.

### Normalización a E.164 argentino

Es el punto que más se rompe y necesita su propia batería de pruebas. Lo que hay en la base
(real): `343-1234567`, `0343 15 4123456`, `+54 9 343 4123456`, `154123456`, `3434123456`,
`(0343) 4123456`, `343 412 3456 / 343 412 3457`.

Reglas:

1. Dejar sólo dígitos (si hay dos números separados por `/` o `-`, se toma **el primero** y se
   deja registrado el original).
2. Sacar `00` o `+` inicial; sacar `54` inicial si está.
3. Sacar el `0` de la característica y el `15` del celular (en ese orden: `0343 15 4123456`).
4. Anteponer `549`.
5. Validar: 13 dígitos, característica argentina conocida, y que no quede un fijo disfrazado.
6. **Lo que no valida no se manda.** No se completa, no se adivina, no se "arregla". Mandarle
   un aviso de corte a un tercero por un número mal armado es peor que no mandar nada.

---

## 5. API (`/api/v2`, blueprint protegido con `proteger(bp, "avisos")`)

| Método y ruta | Qué hace |
|---|---|
| `GET /avisos` | Listado con filtros (estado, incidente, fechas) |
| `GET /avisos/<id>` | Detalle + contadores + destinatarios paginados |
| `POST /avisos` | Crea el borrador (desde un incidente o manual) |
| `PUT /avisos/<id>` | Plantilla y variables. Recalcula el padrón |
| `GET /avisos/<id>/vista-previa` | El texto final renderizado + resumen del padrón |
| `POST /avisos/<id>/prueba` | Envía a los números del equipo (de configuración) |
| `POST /avisos/<id>/aprobar` | **El OK.** Body con `confirmacion` = cantidad tipeada. Aplica §4 |
| `POST /avisos/<id>/cancelar` | Sólo desde `BORRADOR` / `PENDIENTE_APROBACION` |
| `POST /avisos/<id>/reintentar-fallidos` | Nueva pasada sólo sobre los `FALLIDO` reintentables |
| `GET /avisos/<id>/destinatarios.csv` | La lista, para llamar a los que no tienen WhatsApp |
| `GET /avisos/plantillas` | Catálogo local |
| `POST /avisos/plantillas/sincronizar` | Contrasta contra Meta y actualiza estados |
| `GET|POST|DELETE /avisos/opt-out` | Gestión de bajas |
| `POST /webhook/whatsapp` | **Fuera del blueprint protegido** (lo llama Meta, no un usuario). Verifica la firma `X-Hub-Signature-256` con el app secret. Sin firma válida → 403 |

Códigos: `409` si ya hay un aviso en vuelo, `422` si falla una validación de negocio (con el
motivo en castellano, para mostrarlo tal cual), `403` sin el flag de aprobación.

---

## 6. Panel

`templates/partials/pages/ftth/avisos.html` + `static/js/avisos.js`, alcanzable con
`navGo('avisos')`, al lado de Incidencias. Usa `v2Kpi`, `v2Tabla` y `v2Fecha` de
`v2_widgets.js`; escapa todo con `escHtml()` / `escJs()` como manda la convención.

**Pantalla 1 — bandeja.** Los borradores pendientes arriba, con el reloj corriendo desde el
inicio del incidente. KPIs: avisos hoy, mensajes enviados, tasa de entrega, teléfonos
inválidos por corregir.

**Pantalla 2 — armado.** Selector de plantilla (sugerida según `causa_probable`), campos de
variables con ejemplo, **vista previa renderizada en formato burbuja de WhatsApp** —tiene que
verse igual a lo que le llega al cliente, no un formulario—, y el resumen del padrón con las
cuatro listas de omitidos desplegables.

**Pantalla 3 — confirmación.** Modal que repite el texto final, la cantidad exacta, y pide
**tipear la cantidad** para habilitar el botón. Debajo, en rojo: *"Esto le manda un WhatsApp
a 287 personas. No se puede deshacer."*

**Pantalla 4 — seguimiento.** Barra de progreso, contadores en vivo (poll cada 5 s mientras
esté `ENVIANDO`), tabla de destinatarios filtrable por estado, botón de reintentar fallidos.

---

## 7. Worker de despacho

`avisos_worker.py`, por cron cada minuto:

```
* * * * * /home/eaguiar/ERLAN/erlan_v6.1.8/venv/bin/python3 \
    /home/eaguiar/ERLAN/erlan_v6.1.8/avisos_worker.py >> /var/log/pucara/avisos.log 2>&1
```

Con `flock` para que dos corridas no se pisen, y **con el Python del venv** — es exactamente
el error que hoy tiene `olt_poller.py` en el crontab y que hace que el motor de incidentes no
corra (deuda técnica 7). No repetirlo acá.

Cada corrida: toma los avisos `APROBADO` / `ENVIANDO`, procesa hasta N destinatarios
`PENDIENTE` (200 por corrida, ~20 msg/s con pausa), marca resultado por fila, actualiza
contadores, y si no queda ninguno pendiente pasa el aviso a `ENVIADO`.

- **Ritmo:** la Cloud API tolera del orden de 80 mensajes por segundo, pero el límite que
  importa es el de **usuarios únicos por 24 h** (1.000 en el escalón inicial, 10.000 con la
  verificación de negocio hecha). Alcanza para un corte grande, no para tres el mismo día:
  conviene tramitar la verificación antes de necesitarla.
- **Backoff** exponencial ante `429` y `5xx`, respetando `Retry-After` si viene.
- **Errores permanentes** (número inexistente, sin WhatsApp) no se reintentan: `FALLIDO` con
  el código de Meta sin interpretar, para poder mirarlo después.
- Si el aviso quedó a medias y pasan más de 30 minutos, avisa por Telegram al NOC.

---

## 8. Permisos

Se agrega `avisos` a `_MODULOS_SISTEMA` y al catálogo de `permisos_catalogo()` en el grupo
"FTTH / Red", con la clave **idéntica** al `navGo('avisos')` (nota que ya está en el código:
si no coinciden, el permiso se guarda pero no aplica al menú).

Acciones `ver` / `crear` / `editar` como el resto. **La aprobación va como flag especial
`puede_aprobar_avisos`**, junto a los que ya existen: redactar un aviso y disparárselo a 300
clientes no son la misma responsabilidad, y el rol `tecnico` debería poder hacer lo primero y
no lo segundo.

---

## 9. Pruebas

Ninguna funcionalidad sin pruebas. Estimado: ~45 casos.

| Archivo | Cubre |
|---|---|
| `tests/test_telefonos.py` | Normalización E.164 con la tabla de casos feos reales, incluidos los que **deben** rechazarse |
| `tests/test_avisos_padron.py` | Armado del padrón, dedup por teléfono, opt-out, congelado de nombre y número |
| `tests/test_avisos_estados.py` | Máquina de estados: no se envía sin aprobar, no se aprueba dos veces, no se cancela lo que ya salió |
| `tests/test_avisos_reglas.py` | Las nueve validaciones de §4, una por una — sobre todo lectura parcial y ventana horaria |
| `tests/test_despacho.py` | Con `ProveedorFalso`: reintentos, `429` con backoff, error permanente, corrida interrumpida y retomada |
| `tests/test_api_avisos.py` | 401 sin sesión, 403 sin el flag, 409 con aviso en vuelo, 422 con validación fallida |
| `tests/test_webhook_whatsapp.py` | Firma inválida → 403; estados `sent`/`delivered`/`read`/`failed`; evento duplicado no rompe |
| `tests/test_convivencia_legado.py` | (existente) confirma que las 4 tablas nuevas no pisan nada del legado |
| `tests/test_arquitectura.py` | (existente) las 9 reglas siguen en verde con el módulo nuevo |

---

## 10. Plan por fases

**Fase 9-A — Todo lo que no depende de Meta.** Se puede empezar hoy mismo, sin trámite y sin
gastar un peso. Modelo, migración, repositorios, normalización de teléfonos, armado del
padrón, panel con vista previa y **proveedor simulado** que no manda nada. Entregable
utilizable solo: *"si hubiera que avisar, le avisaríamos a estas 287 personas, con este
texto, y estas 25 tienen el teléfono mal"* — más el CSV para llamarlos. Esa lista sola ya
mejora la operación de hoy.

**Fase 9-B — Alta en Meta.** En paralelo, y es la que tiene tiempos de tercero: Business
Manager verificado, número dedicado, WABA, las 4 plantillas cargadas y aprobadas, adaptador
Cloud API real, envío de prueba al equipo.

**Fase 9-C — Envío real.** Worker por cron, webhook de estados, opt-out, seguimiento en vivo,
reintento de fallidos.

**Fase 9-D — Cierre del círculo.** Aviso de normalización sugerido al cerrarse el incidente,
métricas (tasa de entrega y lectura, y sobre todo: cuántos tickets de Tero se evitaron
comparando cortes con aviso contra cortes sin aviso).

---

## 11. Lo que hace falta del lado del cliente antes de la fase 9-B

No lo puede resolver el código:

1. **Número de teléfono dedicado.** Si hoy está en uso en la app WhatsApp Business, migrarlo
   implica perder el uso desde el celular. Conviene un número nuevo.
2. **Meta Business Manager verificado** (documentación de la empresa). Es también lo que
   habilita subir el tope diario de 1.000 a 10.000 usuarios únicos.
3. **Texto de las 4 plantillas**, redactado y mandado a aprobar:
   - `corte_masivo_aviso` — `{{1}}` zona, `{{2}}` hora de inicio, `{{3}}` causa
   - `corte_masivo_actualizacion` — `{{1}}` zona, `{{2}}` estado / estimación
   - `corte_masivo_resuelto` — `{{1}}` zona, `{{2}}` hora de normalización
   - `corte_programado` — `{{1}}` zona, `{{2}}` fecha y hora, `{{3}}` duración estimada
4. **Confirmar el costo real** contra la tabla oficial vigente de plantillas *utility* para
   Argentina antes de aprobar el gasto (Meta actualiza precios trimestralmente y desde abril
   de 2026 factura en pesos acá).

---

## 12. Riesgos y cómo se contienen

| Riesgo | Contención |
|---|---|
| Falso positivo avisado a 300 clientes | OK humano obligatorio + bloqueo por lectura parcial + antigüedad mínima del incidente + tope de destinatarios |
| Doble envío por dos operadores | Índice único parcial en la base, no una verificación en código |
| Número mal normalizado → aviso a un tercero | No se adivina: lo que no valida queda `OMITIDO` y listado |
| Baneo o degradación de la calidad del número | Sólo plantillas *utility* aprobadas, opt-out respetado, sin marketing, ventana horaria |
| Costo desbordado | Contador por aviso, tope de destinatarios, y las plantillas dentro de la ventana de 24 h no se cobran |
| El worker queda a medias | Estado por destinatario en la base: la corrida siguiente retoma. Aviso al NOC si se estanca |
| Se cae Meta justo en el corte | El CSV de destinatarios sigue disponible para llamar. El aviso queda pendiente, no perdido |
| Fase 8 (PostgreSQL) | Tablas nuevas con `UtcDateTime`, enums no nativos y SQL sólo en repositorios: nace portable |
