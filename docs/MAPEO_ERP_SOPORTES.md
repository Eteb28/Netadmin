# Mapeo ERP `sat_soportescontrato` ↔ Pucará `servicios`

Basado en el .mtd que envió Silix y en sus respuestas del punto 3.
La tabla tiene **90 campos**, 9 obligatorios, 32 con relación a otras tablas.

## 1. Campos obligatorios (lo mínimo para poder insertar)

| Campo | Tipo | Relación | Notas |
|---|---|---|---|
| `idsoporte` | serial | sat_registrossoporte.idsoporte (1M) | PK autoincremental (serial). Lo genera el ERP. |
| `codigo` | string(18) | — | Código del documento. default=0 → **lo asigna la numeración del ERP**. |
| `codcontrato` | string(5) | contratos.codigo (M1) | Contrato del cliente. Pucará hoy NO lo guarda: hay que traerlo. |
| `codcliente` | string(6) | clientes.codcliente (M1) | **Clave de vínculo**: es `nro_cliente` en Pucará. |
| `codejercicio` | string(4) | ejercicios.codejercicio (M1) | Ejercicio contable (año). Hay que leer el vigente de `ejercicios`. |
| `codserie` | string(4) | series.codserie (M1) | Serie del documento. Hay que leer la que usan de `series`. |
| `numero` | string(12) | — | Número del documento. default=0 → **idem**. |
| `fecha` | date | — | Fecha del soporte. |
| `hora` | time | — | Hora del soporte. |

## 2. Mapeo directo con Pucará

| Pucará `servicios` | ERP | Observación |
|---|---|---|
| `nro_cliente` | `codcliente` | Clave de vínculo, ya validada en el sync de clientes |
| `tipo` | `tiposoporte` | Hay que mapear los valores (ver punto 4) |
| `estado` | `estado` | Ciclos distintos (ver punto 4) |
| `descripcion` | `descripcion` | string(100): truncar |
| `observaciones` | `observaciones` | stringlist |
| `fecha_programada` | `fechaprogramada` | |
| `fecha_completado` | `fecha_cierre` | El ERP además tiene `fecha_realizacion` |
| `tecnico_id` | `codtecnico` | Pucará usa id propio; el ERP `tecnicos.codtecnico`. Los empleados ya tienen `codtecnico` |
| `nap` / `cdo` | `fo_nap` / `fo_cdo` + `idcaja_nap` | El ERP también tiene `caja_nap_descripcion` |

## 3. Campos del ERP que Pucará NO tiene (a considerar)

| ERP | Para qué |
|---|---|
| `ipequipo`, `idipequipo`, `tipoipservicio` | IP del equipo del cliente y su tipo. `idipequipo` apunta a `sat_pooldeip` |
| `puertosredireccionados` (bool) | **Coincide con el pedido nuevo de IP pública/puertos** |
| `motivo`, `solucion` | Motivo del reclamo y solución aplicada. Muy útil para el historial técnico |
| `equipo_sugerido`, `reemplazar_referencia` | Equipo a instalar / a reemplazar (→ `articulos`) |
| `fecha_realizacion`, `fecha_realizacion_instalacion`, `fecha_cancelacion` | Marcas de tiempo del ciclo |

## 4. Diferencias de vocabulario a resolver antes de escribir

**Tipos** — el ERP usa: Activación, Cálculo enlace, Cambio contrato, Cambio domicilio,
Cambio titular, Instalación, Mantenimiento, Rescisión, Restablecimiento, Servicio técnico.
Pucará tiene su propio conjunto: hace falta una tabla de equivalencias.

**Estados** — el ERP: `Pendiente → Realizado → Cerrado`
(*Realizado* = hubo reemplazo o reconfiguración y queda pendiente el cierre).
Pucará: `pendiente → asignado → en_camino → en_proceso → completado`.
Los intermedios de Pucará no existen en el ERP: hay que decidir si se colapsan al escribir.

## 5. Riesgo real de escribir (lo que hay que resolver primero)

Silix confirmó (3.4) que el soporte **no toca facturación ni el libro diario**. El .mtd lo
respalda: no hay campos de asiento, importe ni IVA… **salvo el bloque `cambio_*`**
(`cambio_totalconiva`, `cambio_codpago`, `cambio_codcuenta`, `cambio_codtarjeta`…), que
pertenece al *cambio de contrato*. Y Silix advirtió que cambiar el estado de un contrato
**sí** hace que se generen o no facturas.

> **Límite propuesto:** escribir soportes operativos (Instalación, Servicio técnico,
> Mantenimiento) sin tocar `cambio_*` ni el estado del contrato. Todo lo que sea
> Cambio contrato / Rescisión / Suspensión sigue haciéndose en Eneboo.

**El obstáculo técnico no es contable, es la numeración.** `codigo` y `numero` tienen
`default=0`, y `codejercicio`/`codserie` referencian `ejercicios` y `series`. En Eneboo
esos valores los asigna el sistema de numeración de documentos. Insertar con números
inventados puede generar duplicados o huecos en la serie.

## 6. Camino propuesto

1. **Fase lectura (sin riesgo):** traer `sat_soportescontrato` al sync y mostrar en la ficha
   del cliente el historial de soportes del ERP. Se gana visibilidad sin escribir nada.
2. **Preguntas a Silix antes de escribir:**
   - ¿Cómo se asignan `codigo` y `numero`? ¿Hay secuencia/contador consultable, o lo
     resuelve la capa de aplicación de Eneboo?
   - ¿Qué `codserie` usan para soportes y cómo se obtiene el `codejercicio` vigente?
   - `sat_registrossoporte` (relación 1→M con `idsoporte`): ¿hay que crear un registro
     inicial junto con el soporte, o lo genera el ERP?
   - ¿Un soporte creado por fuera de Eneboo aparece bien en su interfaz?
3. **Prueba controlada:** snapshot de PostgreSQL antes/después de crear UN soporte desde
   Eneboo, para ver exactamente qué tablas toca. Recién ahí, escribir.
