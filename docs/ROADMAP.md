# Roadmap de la etapa

Secuencia propuesta para los 9 puntos del pedido. El orden **no** es el del enunciado:
está ordenado por dependencias técnicas y por riesgo.

## Por qué cambia el orden

La migración a PostgreSQL figura como punto 1, pero **no puede ser lo primero**:

- Migrar 729 consultas sin una sola prueba que valide el resultado es la operación más
  riesgosa de todo el pedido, sobre un sistema en producción.
- La capa Repository —que la migración necesita para no dispersar SQL— **todavía no existe**
  (ver [ESTADO-ACTUAL](ESTADO-ACTUAL.md)).
- Las funciones nuevas (reclamos, incidentes) son **dominios nuevos**: se pueden construir ya
  con la arquitectura y el ORM definitivos, sin depender de que se migre lo viejo.

Construir primero un dominio nuevo con SQLAlchemy deja la herramienta probada y la capa
Repository establecida **antes** de tocar lo que está en producción.

## Fases

| # | Fase | Contenido | Punto del pedido | Riesgo |
|---|---|---|---|---|
| **1** | Fundaciones | SQLAlchemy + Alembic, estructura en capas, prueba que hace cumplir las reglas del ADR-0001, CI | 1 (base), 9 | Bajo |
| **2** | Reclamos | Dominio completo en capas: modelos, repos, servicios, API, catálogos administrables, pestaña en el modal, pruebas | 2 | Bajo — tablas nuevas |
| **3** | Analítica de reclamos | MTTR, MTBF, top clientes/AP/PON/OLT, tasa por técnico | 2 (motor) | Bajo |
| **4** | Motor de incidentes | Unificación, cierre automático, eventos masivos ([ADR-0003](adr/0003-motor-de-incidentes.md)) | 3, 4 | **Medio** — toca alarmas en uso |
| **5** | Antigüedad y churn | Permanencia, altas/bajas, churn, cohortes | 5 | Bajo — sólo lectura |
| **6** | Pendientes de rescisión en OLT | Listado ampliado (incluye `pte_rescision`), selección múltiple, exportación | 6 | Bajo — **sólo lectura** por corrección del alcance |
| **7** | Dejar de depender de SQLite | Caracterización ✅, modelar tablas heredadas ✅, mover consultas a Repository ⏳ | 1 | **Alto** |
| **8** | Cambio de motor a PostgreSQL | Copia de datos ✅, secuencias ✅, corte en producción ⏳ | 1 | **Alto** |

**Estado: fases 1 a 6 completas.** Ver [INFORME-FASES-1-6](INFORME-FASES-1-6.md).

**Fase 7 en marcha:** las pruebas de caracterización y el modelado de las tablas
heredadas están hechos, y **toda la suite corre contra PostgreSQL 16 real**
(256 pruebas). Falta mover a Repository las consultas que quedan en `app.py` y
reemplazar los `sqlite3.connect` sueltos.

**Fase 8 ensayada de punta a punta:** la secuencia completa —esquema, copia,
secuencias, verificación de conteos— se ejecutó contra PostgreSQL con datos y
las consultas devuelven exactamente lo mismo que en SQLite. Falta el corte en
producción, que es una decisión operativa.

Detalle y comandos en [PREPARACION-FASES-7-8](PREPARACION-FASES-7-8.md).

Documentación y pruebas **no son una fase**: son parte de la definición de terminado de cada
una (punto 7 y 8 del pedido).

## Definición de "terminado" (para toda fase)

1. Migración Alembic aplicada y **reversible**.
2. Repository con pruebas unitarias.
3. Service con pruebas de la lógica de negocio.
4. API con pruebas de integración.
5. Frontend funcionando contra la API real.
6. Documentación actualizada (ADR si cambió una decisión, modelo de datos, API).
7. Sin SQL fuera de `repositories/` (verificado por prueba automática).

## Dependencias

```
Fase 1 (fundaciones)
   ├── Fase 2 (reclamos) ──► Fase 3 (analítica)
   ├── Fase 4 (incidentes)
   ├── Fase 5 (antigüedad)
   ├── Fase 6 (rescisión en OLT)   [además: driver de OLT ya existente]
   └── Fase 7 (PostgreSQL) ──► Fase 8 (retiro del monolito)
```

La fase 7 puede correr en paralelo a las 2–6 **sólo si** cada dominio nuevo ya nació sobre
SQLAlchemy — que es exactamente lo que asegura la fase 1.

## Sobre el punto 6 (baja de ONU en la OLT)

Es la única fase que **escribe en equipos de producción**. Requisitos propios antes de
implementarla:

- Modo simulación por defecto: mostrar los comandos sin ejecutarlos.
- Confirmación explícita con la lista de lo que se va a borrar.
- Auditoría de cada comando enviado y su respuesta.
- Validación previa: que el cliente siga en estado rescindido/pendiente al momento de
  ejecutar, no sólo cuando se armó la lista.

Vale lo aprendido con el módulo GPON: un comando mal formado no genera un error de pantalla,
deja clientes sin servicio.
