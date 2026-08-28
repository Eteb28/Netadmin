# ADR-0003 — Motor unificado de incidentes (cierre automático y eventos masivos)

- **Estado:** propuesto (requiere aprobación)
- **Fecha:** agosto 2026
- **Cubre:** puntos 3 y 4 del pedido

## Contexto

El pedido dice "mantener la máquina de estados implementada anteriormente". Existe, pero
**no donde hace falta**. Hoy conviven dos mecanismos desconectados:

| | `snmp_wireless.procesar_evento()` | `olt_poller.detectar_alertas_infra()` |
|---|---|---|
| Ámbito | Equipos de torre (wireless) | Infraestructura FTTH (NAP/PON) |
| Tabla | `snmp_eventos` | `alertas_infra` |
| Estados | `inicio → activo → recuperado` | activa / resuelta |
| Histéresis | Sí | Parcial |

El cierre automático y los eventos masivos se piden sobre **FTTH**, que es justamente el lado
con el motor más débil.

## Decisión

Unificar ambos en un **motor de incidentes** único, con una sola máquina de estados y una
sola tabla, del que los dos dominios sean clientes.

### Máquina de estados

```
        detección                 estable N min
INICIO ───────────► ACTIVA ──────────────────► RECUPERADA ──► CERRADA
                      │                                          ▲
                      └──────── cierre manual ───────────────────┘
```

- **ACTIVA → RECUPERADA** no es inmediata: exige que la ONU se mantenga estable un tiempo
  **configurable** (5 minutos por defecto). Sin esa espera, una ONU que oscila abre y cierra
  incidencias en bucle.
- **RECUPERADA → CERRADA** registra: fecha de recuperación, duración de la caída,
  usuario `Sistema`, motivo `Recuperación automática`.
- Reabrir una incidencia recién recuperada **no crea una nueva**: vuelve a ACTIVA y suma un
  ciclo. Así el intermitente se ve como un incidente con muchos ciclos, que es lo que es.

### Eventos masivos: agrupar por causa, no por síntoma

Cuando varias ONU del mismo PON caen dentro de una ventana corta, no son N incidentes: es
**uno solo con N afectados**.

```
Si (caídas en el mismo PON) ≥ umbral  Y  (ventana ≤ T)
    → crear incidencia de PON
    → asociar las ONU como afectadas
    → NO crear incidencias individuales
```

Parámetros configurables: umbral (absoluto y como % del PON), ventana de correlación, y
tiempo de estabilidad para el cierre.

**Aprovechar el motivo de caída que ya reporta la OLT.** Está verificado que la V1600G1-B
expone por ONU el motivo (`Power Off` = dying gasp, corte de luz en la casa; `Onu Los` =
pérdida de señal, problema de fibra). Eso permite **clasificar el incidente masivo por causa
probable** en vez de sólo contarlo:

| Patrón observado | Causa probable |
|---|---|
| Muchas `Power Off` en la misma zona | Corte eléctrico |
| Muchas `Onu Los` en el mismo PON | Corte de fibra / splitter |
| Todo el PON, incluida la óptica del puerto | Problema de la OLT |

Esto responde directamente a lo pedido ("detectar cortes eléctricos, corte de fibra,
problemas de OLT o splitter") con un dato que **ya está disponible y hoy no se usa**.

### Regla heredada de producción (no negociable)

Una lectura incompleta **nunca** se interpreta como caída masiva. Si el sondeo viene truncado
o da timeout, la corrida se marca como parcial y **no** dispara incidencias. Este error ya
ocurrió: una lectura óptica truncada marcó PONs enteros como caídos y disparó una tanda de
avisos por Telegram.

## Consecuencias

**A favor:** un solo motor que mantener; cierre automático en ambos dominios; los incidentes
masivos dejan de tapar el panel; y la causa probable llega junto con la alarma.

**En contra:** hay que migrar los datos de `snmp_eventos` y `alertas_infra` a la tabla
unificada, y ajustar lo que hoy los consulta. Es trabajo real, pero es la condición para que
"mantener la máquina de estados" signifique algo.

## Alternativa descartada

**Agregar el cierre automático sólo del lado FTTH, dejando los dos motores separados.** Más
rápido ahora, pero consolida dos mecanismos divergentes que después hay que mantener en
paralelo — y el pedido pide explícitamente no duplicar lógica.
