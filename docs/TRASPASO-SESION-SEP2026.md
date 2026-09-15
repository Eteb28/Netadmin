# Traspaso — estado de Pucará, septiembre 2026

Documento para arrancar una conversación nueva sin perder contexto. Todo lo de acá está
verificado contra el código, no es de memoria.

**Repositorio:** `Eteb28/Netadmin` · **Rama:** `claude/project-review-ik4e2e` · **PR #2**
**Último commit:** `d0e3f73`

---

## 1. Qué es Pucará

Sistema de gestión integral del ISP **ERLAN Telecomunicaciones** (Paraná, Crespo y El Pingo,
Entre Ríos). No es un NOC: es el ERP operativo. Clientes, facturación, órdenes de trabajo,
stock, RRHH, mapa de NAP y torres, y monitoreo de red.

- **Stack:** Python 3.11 / Flask + JavaScript sin framework. SQLite (migración a PostgreSQL
  ensayada, ver §3).
- **Tamaño:** `app.py` 9.978 líneas con 280 rutas · 21.600 líneas de Python · 13.000 de JS ·
  53 tablas.
- **Arquitectura:** monolito heredado + paquete en capas nuevo (`pucara/`), patrón
  *strangler fig*. Lo nuevo nace en capas; lo viejo se migra de a poco.
- **Licencia:** AGPL-3.0, de ERLAN.
- **Despliegue:** `~/ERLAN/erlan_v6.1.8`, systemd (`pucara.service`), Caddy con certificado
  propio sobre IP. **Usa `./venv/bin/python3`** — no el Python del sistema (PEP 668).

### Escala del negocio
3.782 clientes vigentes · 2.341 fibra · 1.441 inalámbrico · 214 suspendidos.
OLT VSOL, APs Cambium y Ubiquiti.

---

## 2. Reglas del usuario — no negociables

Esteban las repitió a lo largo de varias sesiones. Respetarlas:

1. **Hablar y escribir siempre en castellano rioplatense.**
2. **Nada de SQL fuera de `repositories/`.** Hay una prueba automática que lo hace cumplir.
3. **Ninguna funcionalidad sin pruebas.**
4. **Nada de soluciones rápidas ni parches.**
5. **No inventar.** Si un dato no se puede verificar, decirlo.

---

## 3. Dónde está cada cosa

### Fases 1 a 6 — completas
Reclamos técnicos, analítica (MTTR/MTBF, rankings), motor unificado de incidentes,
antigüedad y churn, pendientes de rescisión (**sólo lectura**, por corrección explícita del
alcance).

### Fase 7 — en marcha
- `pucara/models/legado.py` describe **11 tablas heredadas** (`clientes`, `olts`, `naps`,
  `onu_senal`, `onu_senal_hist`, `historial`, `tareas_usuario`, `torres`, `torre_equipos`,
  `snmp_estaciones`, `stock_items`). **Ya no queda SQL en texto en ningún repositorio.**
- **La suite corre en los dos motores.** `PUCARA_TEST_PG_URL=postgresql+psycopg2://...`
  y la misma suite va contra PostgreSQL.
- Falta: mover a Repository las consultas que quedan en `app.py` y reemplazar los 15
  `sqlite3.connect` sueltos.

### Fase 8 — ensayada de punta a punta
Contra un PostgreSQL 16 real: Alembic ida y vuelta, 53 tablas heredadas creadas con
`scripts/esquema_heredado_a_postgres.py`, copia de datos, secuencias resincronizadas,
conteos coincidentes, idempotencia. **Las consultas devuelven exactamente lo mismo en los
dos motores.** Falta el corte en producción, que es decisión operativa.

### Estado verificado hoy
**326 pruebas en SQLite** (~7 s) · **336 en PostgreSQL** · 19 rutas en `/api/v2` ·
3 migraciones Alembic reversibles en los dos motores.

---

## 4. Lo hecho en esta etapa (5 commits)

| Commit | Qué |
|---|---|
| `0eb0b20` | Fase 7: tablas heredadas modeladas, suite verificada en PostgreSQL |
| `ab2c645` | Lector de códigos: prueba de campo para el inventario |
| `aed1f0c` | Conciliación de inventario contra lo que la red ya reporta |
| `f561550` | Plan TR-069 con GenieACS |
| `d0e3f73` | Censo de ONU por SNMP (fase 0.a del plan TR-069) |

### 4.1 Conciliación de inventario · `aed1f0c`

Contesta *«qué equipos existen de verdad, cuáles figuran en el papel y ya no están, y cuáles
funcionan sin figurar»* — años de registros malos.

**La idea de fondo: la red es un inventario que se toma todos los días y nadie lee.** La OLT
reporta el serial de cada ONU (`onu_senal.serial_onu`), los AP reportan MAC y modelo de cada
CPE (`snmp_estaciones`), el poller sabe qué equipo de torre contestó y cuándo.

`GET /api/v2/inventario/conciliacion` cruza eso contra el padrón y el depósito:

| Categoría | Qué significa |
|---|---|
| `fantasma` | Figura en depósito **pero está funcionando en la red** |
| `no_visto` | El registro dice que está, la red no lo ve |
| `difiere` | El cliente tiene otro equipo del que dice su ficha |
| `sin_registro` | Funciona en la red, no está cargado |
| `huerfano` | La red lo ve, no se puede atribuir a nadie |

Más **cobertura**: el % de lo que la red ve que está bien registrado. Se calcula siempre
sobre el total, nunca sobre lo filtrado, para que sea comparable entre semanas.

> **Regla que no se negocia:** que la red no lo vea **no** significa que no exista. Clientes
> sin servicio no generan faltante; un equipo de torre necesita 7 días sin contestar para
> aparecer y 60 para escalar. **Hay nueve pruebas dedicadas sólo a que no invente faltantes.**

**PENDIENTE: correrlo contra producción.** Nadie lo hizo todavía. Ese número dice cuán mal
está el registro y es insumo de casi todo lo demás.

### 4.2 Lector de códigos · `ab2c645`

`static/herramientas/lector.html` — se abre desde el teléfono en
`https://192.168.10.9:5000/static/herramientas/lector.html`.

Prueba de campo, no el módulo: **¿la cámara lee las etiquetas reales, gastadas y dentro del
rack?** Usa `BarcodeDetector` nativo (Android; Safari no lo trae y el diagnóstico lo dice con
todas las letras). Linterna, carga manual, exportación a CSV. Archivo suelto en `static/`:
no toca `app.py` ni la base.

**PENDIENTE: probarlo con equipos reales** y pasar el CSV. Lo que no se lea define el tamaño
de la campaña de reetiquetado.

### 4.3 Plan TR-069 + GenieACS · `f561550`, `d0e3f73`

Ver `docs/PLAN-TR069-GENIEACS.md` (completo) y §6 de este documento.

### 4.4 Muestra de tablero rediseñado

Artefacto: https://claude.ai/code/artifact/3889d71b-e2c5-4d48-92ad-da4ce2a033c3
Sólo maqueta, **no implementado**. Tres KPI (vigentes, suspendidos, bajas del mes), fibra vs
inalámbrico, altas contra bajas día por día, comparación trimestral estilo telco, y un chat
interno de la empresa. Se sacaron localidades, señal crítica, distribución, servicios
pendientes y planes vigentes.

### 4.5 Evaluación de FTTH-Copilot

Repo de terceros (`Rene-Kuhm/FTTH-Copilot`) que Esteban pidió evaluar.
**Conclusión: no integrar.** Tres razones independientes:

1. **Licencia propietaria**, todos los derechos reservados. Prohíbe copiar, modificar, crear
   obras derivadas y usar el software con cualquier fin. El acceso público es sólo para
   evaluación.
2. **Cambium no aparece en una sola línea del repo** → 1.441 clientes sin cubrir.
3. Duplicaría el sistema de alertas justo después de que Pucará unificó los suyos.

Es un buen proyecto (38.400 líneas TS, 510 pruebas verificadas) pero es **NOC/SOC de sólo
lectura**: no tiene clientes, facturación, stock ni mapa, y **no configura nada** — lo tiene
prohibido por regla explícita del proyecto.

Lo que sí conviene traer como **idea** (las ideas no se licencian): recibir trampas SNMP en
vez de sólo sondear, separar evidencia de diagnóstico, ventanas de mantenimiento, auditoría
de firmware, predecir tiempo hasta el corte, exportador Prometheus.

---

## 5. Trampas conocidas — no repetirlas

Cada una costó tiempo. Están documentadas en el código.

1. **`database is locked` silencioso.** Nunca abrir una segunda conexión `sqlite3` mientras
   una sesión SQLAlchemy tiene una escritura pendiente. El `except: pass` de `log()` se come
   el error: la petición devuelve 200 y el registro no existe. La auditoría escribe por la
   **misma** sesión.
2. **En PostgreSQL una sentencia fallida aborta la transacción entera.** Todo `try/except`
   alrededor de SQL necesita un `SAVEPOINT` (`begin_nested()`). Ya pasó en
   `IncidenteRepository.total_onus_en_pon()`.
3. **Los modelos heredados van en `BaseLegado`, NO en `pucara.db.Base`.** Si entran ahí,
   `alembic autogenerate` propone ALTERs sobre las tablas de producción a imagen de
   declaraciones que son parciales a propósito. Hay una prueba que falla si alguien los mueve.
4. **`escJs()` y no `escHtml()`** para JS dentro de atributos: el navegador decodifica las
   entidades antes de ejecutar.
5. **Todo blueprint nuevo de `/api/v2` debe llamar a `proteger()`.** Hay una prueba que falla
   si se omite.
6. **Fechas fijas en pruebas con ventana temporal.** `test_degradacion` tenía datos anclados
   a agosto; pasó el mes y dos pruebas se pusieron rojas solas. Todo se ancla a
   `date.today()`.
7. **Un OID que parece temperatura y no lo es.** `.37950.1.1.5.10.12.4.0` devolvía 39 en una
   G1 (coincidía con la web) y 87 en una G1B: dejaba la OLT en crítico por nada. La historia
   está en el encabezado de `olt_poller.py`.

---

## 6. TR-069 — el frente abierto

**El problema:** el módulo GPON no logra configurar WAN (PPPoE), DHCP ni WiFi de las ONU,
ni por CLI ni por SSH.

**El diagnóstico:** no falta el comando. Se intenta configurar desde la OLT algo que la OLT
no administra. La OLT maneja el transporte (T-CONT, GEM, service-port, VLAN); el gateway
residencial vive adentro de la ONU. La OLT llega por OMCI, pero el OMCI estándar no cubre
esa parte. **TR-069 (CWMP) es el protocolo estándar para eso.**

### El parque real

| | Modelo | Firmware | TR-069 |
|---|---|---|---|
| OLT | VSOL V1600G1 | `V2.3.1R` | — |
| OLT | VSOL V1600G1B | `V1.4.14R` | — |
| ONU | V2802DAC, V2802GW | `TIGRE-V1.0` | ✅ **activo de fábrica** |
| ONU | V2802DAC, V2802GW | `V3.2.00`, `V1.9.1.2`, `V2.1.06` | ❌ inactivo |

**El riesgo principal (R1b) es activar TR-069 en los tres firmwares que no lo traen**, sobre
una flota ya instalada. Caminos, de mejor a peor: por OMCI desde la OLT · por plantilla de
perfil de ONU · actualización de firmware · web de cada ONU una por una.

### Decisión de arquitectura ya tomada

**Consulta, no empuje.** GenieACS le pregunta a Pucará en cada arranque de la ONU, en vez de
que Pucará escriba en GenieACS al guardar el cliente. Razón: resetear de fábrica es lo
primero que hace un técnico cuando algo anda mal, y con empuje eso deja al cliente sin
servicio. Con consulta la ONU se reconfigura sola y la fuente de verdad queda sólo en Pucará.

### Próximo paso inmediato

```bash
python3 scripts/censo_onu_vsol.py --descubrir <IP-OLT> <community>
python3 scripts/censo_onu_vsol.py --censo <IP-OLT> <community> \
        --col-modelo N --col-firmware M --csv censo.csv
```

Sólo lectura, media tarde, no toca ninguna ONU. **El número que decide el proyecto:** qué
proporción de la flota corre `TIGRE-V1.0` y ya está lista, y cuánta hay que intervenir.

---

## 7. Hay que arreglar esto antes de TR-069

**`clientes.pppoe_clave` se guarda en texto plano y se envía al navegador**
(`static/js/clientes.js:136`). Hoy es un problema latente; TR-069 la hace circular por un
sistema más y por la red hacia cada ONU. Cifrado en reposo, que la API deje de devolverla al
listar, y que el endpoint del ACS sea el único que la entrega en claro.

**Además, pendiente de sesiones anteriores:** la contraseña real de PostgreSQL está en claro
en `sync_pg.py`, que **ya está en el repositorio**. Hay que rotarla. (No se versionó en los
commits nuevos, pero eso no borra el historial.)

---

## 8. Pendientes, por prioridad

1. **Correr la conciliación de inventario contra producción.** Insumo de casi todo lo demás.
2. **Censo de ONU por SNMP** (§6). Media tarde.
3. **Alerta de evento masivo global** (≥10 equipos caídos en 60 s a nivel red). El motor hoy
   correlaciona sólo por PON: los 58 eventos de backbone del diagnóstico —hasta 97 equipos—
   pasan sin detectar. **La mayor relación impacto/costo del plan.**
4. **Cifrar `pppoe_clave`** y rotar la de PostgreSQL.
5. **Campaña de carga de torre y NAP.** 58,5 % y 61,6 % de los clientes sin ese dato. Es
   carga de datos, pero desbloquea el motor de incidentes para la red inalámbrica.
6. **Diagnóstico obligatorio al cerrar una orden** (adopción actual 0,4 %).
7. Extender la auditoría de cambios a las ~97 rutas de escritura restantes.
8. Unicidad de serie y MAC con historial de equipos. MFA para administradores.
9. Terminar fase 7 y ejecutar el corte a PostgreSQL.
10. Confirmar el OID de «motivo de caída» de las ONU VSOL (`Power Off` / `Onu Los`).
    **Deliberadamente no adivinado.**

---

## 9. Cómo trabajar acá

```bash
python3 -m pytest -q                                    # 326, ~7 s
PUCARA_TEST_PG_URL="postgresql+psycopg2://u@h:5432/db" python3 -m pytest -q   # 336
python3 scripts/auditoria_portabilidad.py --db netadmin.db   # 562 usos por reescribir
```

**Reglas que hace cumplir `tests/test_arquitectura.py`:** nada de SQL fuera de
`repositories/` · los servicios no importan Flask · la API no toca repositorios ni atributos
privados · nadie abre la base por su cuenta · ningún archivo de más de 500 líneas · el
módulo de fase 6 no puede escribir.

**Documentos de referencia:** `docs/ROADMAP.md` · `docs/ESTADO-ACTUAL.md` ·
`docs/PREPARACION-FASES-7-8.md` · `docs/PLAN-TR069-GENIEACS.md` · `docs/adr/` (0001 capas,
0002 PostgreSQL, 0003 incidentes, 0004 autorización).
