# Fases 2 y 3 — Informe técnico

**Entregado:** driver VSOL de **sólo lectura** por SNMP, API interna e interfaz web
independiente. 232 tests en verde, sin red, sin disco y sin reloj real.

```bash
gpon web --simulada        # interfaz completa, sin configurar nada
python -m pytest gpon_module/tests -q
```

---

## 1. Qué se implementó

### Transporte SNMP (`drivers/transport/snmp.py`)

Dos implementaciones, porque en la práctica una u otra falta según el servidor:

* **net-snmp** (`snmpget`/`snmpwalk`) — la preferida: suele estar instalada en cualquier
  servidor de ISP y su comportamiento es idéntico al que el operador ve cuando prueba a
  mano desde una terminal.
* **pysnmp** — evita lanzar un proceso por consulta.

La fábrica elige la disponible. Si no hay ninguna, el error dice cómo instalar cada una en
vez de fallar con un `ImportError`.

**La regla que gobierna ese archivo:** una rama vacía y una falla de comunicación no son lo
mismo. `walk` devuelve `{}` sólo cuando el equipo contestó y no hay nada; si no hubo
respuesta, levanta `ErrorTiempoAgotado`. Confundirlas es lo que produce una baja masiva
falsa.

### Driver VSOL (`drivers/vsol/`)

| Archivo | Contenido |
|---|---|
| `oids.py` | Los OIDs **verificados** contra los walks reales de ERLAN, y los comprobadamente ausentes |
| `parsers.py` | Valores crudos → modelos, con "ante la duda, `None`" |
| `driver.py` | Identidad, puertos PON, inventario de ONU y potencias |
| `snmp_simulado.py` | Un equipo simulado con la forma exacta de una G1-B, incluidas sus ausencias |

Capacidades declaradas: 9. Fuera quedan, **verificado contra los equipos**,
`SERIAL_POR_SNMP`, `TRAFICO_POR_ONU`, `CPU`, `MEMORIA` y `TEMPERATURA_CHASIS`.

También quedó registrado el OID trampa `.5.10.12.4.0` — devolvía 39 en una G1 y 87 en una
G1-B, y no es temperatura. Está en `oids.py` marcado como no usar, y aparece en el sondeo
para que nadie lo vuelva a tomar por bueno.

### API (`api/`)

23 rutas. Es la **única** puerta de entrada de la interfaz. Cada error del módulo se
traduce al código HTTP que corresponde, y la distinción importa:

| Situación | Código | Por qué |
|---|---|---|
| La OLT no existe en la base | 404 | — |
| Parámetro mal formado | 400 | El pedido está mal |
| El equipo no sabe hacerlo | **501** | El pedido está bien; el equipo no puede |
| No hay comunicación con la OLT | **502** | El problema está entre nosotros y el equipo |

### Interfaz web (`web/`)

Nueve pantallas sobre Bootstrap 5. Tres decisiones que se ven al usarla:

* **Los botones que el equipo no soporta no existen.** Cada pantalla consulta primero las
  capacidades. En el detalle de una OLT, lo no soportado aparece tachado y explicado: no es
  algo pendiente de programar, es algo que ese modelo no expone.
* **Un dato ausente se muestra "—", nunca 0.** Un cero se grafica, se promedia y termina en
  una decisión equivocada.
* **Las potencias que requieren atención se ordenan por urgencia, no por valor.** Una ONU
  saturada va arriba de todo aunque su número sea el más alto: está dañando el receptor
  ahora mismo.

Bootstrap y Chart.js van **servidos localmente**. Un servidor de NOC suele estar en una VLAN
de gestión sin salida a internet; con CDN la interfaz se vería sin estilos y sin gráficos
justo donde tiene que funcionar. Son 500 KB en `web/static/vendor/`, con su procedimiento
de actualización documentado.

---

## 2. Un problema real que encontraron los tests

**La escala de las potencias es ambigua por valor suelto.** El equipo publica un entero:
`-157` puede ser −15,7 dBm o −1,57 dBm, y **las dos son potencias posibles** en una red
real. La primera versión del parser resolvía valor por valor y elegía la primera escala que
cayera en rango físico — con lo cual dos ONU de la misma OLT podían quedar interpretadas
con escalas distintas.

La solución es estadística: **la escala se infiere una vez sobre el lote completo** y se
aplica pareja. Con 473 ONU, la escala correcta es la que ubica a la mayoría en el rango
donde vive un parque sano (−32 a −5 dBm). Un valor suelto no alcanza; el conjunto sí.

Importante: el rango típico se usa **sólo para inferir la escala**, nunca para descartar una
lectura. Una ONU saturada a −1,57 dBm queda fuera de ese rango y es justamente la que hay
que ver; hay un test que lo verifica.

Sigue siendo una inferencia, no un hecho verificado. Por eso existe `gpon sondear`: muestra
el valor crudo y el interpretado uno al lado del otro, para compararlos con la web de la OLT
en un minuto.

---

## 3. Qué falta

| Fase | Contenido | Depende de |
|---|---|---|
| 2b | ONU sin autorizar y perfiles en VSOL | Transporte CLI: el serial no viaja por SNMP |
| 4 | Sincronización periódica, históricos, alarmas, PostgreSQL | Nada — se puede empezar |
| 5 | Escritura VSOL (autorizar, borrar, reiniciar) | Laboratorio + comando de autorización confirmado |
| 6 | Driver ZTE | Fase 5 |
| 7 | WiFi/PPPoE (OMCI o TR-069) | Resolver la incógnita de la sección 4.1 de la investigación |
| 8 | Integración con Pucará | Fuera del alcance actual |

En la web falta lo que depende de fases posteriores: gráficos históricos (Fase 4), pantalla
de alarmas con reglas configurables (Fase 4) y las acciones de aprovisionamiento (Fase 5).
El único botón de escritura que existe hoy —reiniciar— está para probar el circuito completo
de capacidad, ejecución y auditoría.

---

## 4. Riesgos

### Mitigados en estas fases

| # | Riesgo | Cómo quedó cubierto |
|---|---|---|
| R5 | Timeout interpretado como ausencia | El transporte distingue rama vacía de sin respuesta, con tests |
| R2 | Cambios de firmware | Tests de parseo con valores reales; un código desconocido se registra, no se adivina |
| R6 | Sin serial por SNMP | Capacidad declarada ausente; el repositorio no pisa un serial ya conocido |

### Vigentes

| # | Riesgo | Estado |
|---|---|---|
| **R10** | **Escala de potencias sin confirmar** | **Nuevo y principal.** Inferida del lote, no verificada. Se resuelve con `gpon sondear` contra un equipo |
| **R11** | **Índices PON base 0 o base 1** | **Nuevo.** El driver toma los índices tal como vienen. Si la G1-B numera desde 0, los nombres de puerto quedarían corridos. `sondear` lo muestra |
| R2 | La MIB puede diferir entre G1 y G1-B | Los OIDs se verificaron en ambas, pero el firmware puede cambiar |
| R7 | Alcance de TR-069 indefinido | Sin cambios |
| R9 | El simulado puede diferir del equipo real | Vigente hasta la primera lectura contra hardware |

**Sobre la web:** hoy no tiene autenticación. Es deliberado —los usuarios son de la Fase 3
del plan original y la tabla ya existe— pero significa que **no debe exponerse fuera de la
red de gestión**. Por eso `gpon web` escucha en `127.0.0.1` salvo que se pida otra cosa.

---

## 5. Compatibilidad

### VSOL V1600G1 y V1600G1-B

Lectura implementada y probada contra un simulado que reproduce la forma real del equipo:
identidad, puertos PON con temperatura y voltaje, inventario completo de ONU con estado y
motivo de caída, y potencias ópticas.

Pendiente de confirmar contra hardware: la escala de las magnitudes analógicas (R10) y la
numeración de los índices PON (R11). Las dos se resuelven con una corrida de `gpon sondear`.

Lo que **no** va a poder hacerse por SNMP en estos equipos, y no es una limitación del
módulo: descubrir ONU sin autorizar, leer perfiles y cualquier escritura. Todo eso es CLI.

### ZTE

Sin cambios respecto del informe de Fase 1. El diseño sigue preparado: `SolicitudAutorizacion`
expresa intención y no comandos, y `RefONU` es neutra frente a los dos direccionamientos.

La Fase 6 sigue siendo la prueba de la abstracción: agregar ZTE no debería requerir ningún
cambio en `core/`, `services/`, `database/`, `api/` ni `web/`.

---

## 6. Para seguir

**Lo que desbloquea todo lo demás:** una corrida de `gpon sondear` contra una V1600G1-B
real. Son dos minutos y confirma o corrige los dos riesgos nuevos.

Sin eso, la Fase 4 (sincronización, históricos y alarmas) se puede empezar igual: no depende
de hardware, y trabaja sobre los mismos servicios que ya funcionan contra el simulado.
