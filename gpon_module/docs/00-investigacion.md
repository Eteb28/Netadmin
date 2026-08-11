# Fase 0 — Investigación

Proyecto: **módulo GPON independiente** (equivalente o superior a AdminOLT), a integrar
en Pucará más adelante. Este documento reúne lo investigado **antes de escribir código**.

## Cómo leer este documento

Cada afirmación técnica va etiquetada según su nivel de evidencia. Esto es deliberado:
el pedido fue explícito en no asumir nada, y en un proyecto de aprovisionamiento un dato
mal supuesto no genera un bug visual, genera un cliente sin servicio o una ONU borrada.

| Etiqueta | Significado |
|---|---|
| **[VERIFICADO]** | Comprobado contra los walks SNMP reales de las OLT de ERLAN, en esta misma sesión. Evidencia de primera mano. |
| **[DOCUMENTADO]** | Publicado en documentación del fabricante, manual CLI o repositorio público. Confiable, no probado en nuestros equipos. |
| **[POR CONFIRMAR]** | Necesario para el diseño, todavía sin evidencia suficiente. Requiere acceso a un equipo o al manual completo. |

---

## 1. AdminOLT: qué es y cómo funciona

**[DOCUMENTADO]** AdminOLT es un sistema de gestión **en la nube** para OLTs Huawei, ZTE,
ZTE Titan, VSOL y WOLCK. Permite configurar la OLT desde cualquier dispositivo y activar
o administrar ONTs.

### Protocolos que utiliza

Al dar de alta una OLT, AdminOLT pide **tres canales** simultáneos:

| Canal | Datos que pide | Uso deducido |
|---|---|---|
| **SNMP** | puerto, community de **lectura** y community de **lectura/escritura** (mín. 8 caracteres y un número) | Telemetría masiva y, por la exigencia de community RW, alguna escritura |
| **Telnet** | puerto configurable | Ejecución de comandos CLI |
| **SSH** | puerto configurable | Ídem, canal cifrado |

**Lectura arquitectónica:** que exija los tres canales confirma lo que se ve en toda la
categoría de productos — **ningún fabricante GPON expone el aprovisionamiento completo por
SNMP**. SNMP sirve para leer rápido y en volumen; crear un service-port o autorizar una ONU
se hace por CLI. AdminOLT no es la excepción: es un orquestador de CLI con telemetría SNMP.

**[DOCUMENTADO]** Automatiza la creación de **tcont, gemport, service-port y traffic table**
"con un simple clic" — es decir, encapsula una secuencia de comandos CLI detrás de una acción.
Ese es exactamente el patrón que debe replicar nuestro módulo.

**[POR CONFIRMAR]** El detalle interno (parsers, manejo de sesión, reintentos) no es público.
No hay razón para imitarlo a ciegas: nuestro diseño puede ser mejor porque conocemos nuestras
OLT en profundidad (ver sección 2).

---

## 2. VSOL V1600G1 / V1600G1-B — capacidades reales

Esta es la sección de mayor valor del análisis: **está construida sobre walks SNMP reales de
las OLT de ERLAN**, no sobre folletos. Incluye varias limitaciones que no figuran en ninguna
documentación y que condicionan el diseño.

### 2.1 Lo que SÍ se obtiene por SNMP  **[VERIFICADO]**

| Dato | OID | Observación |
|---|---|---|
| Modelo | `.1.3.6.1.4.1.37950.1.1.5.10.14.1.0` | `"V1600G1B"` |
| Nombre / firmware / MAC / serie | `.5.10.12.5.{1,4,7,11}.0` | Iguales en G1 y G1-B |
| Uptime | `1.3.6.1.2.1.1.3.0` | Estándar |
| **Temperatura por PON** | `.5.10.13.1.1.2.<pon>` | 39–42 °C medidos. Ver 2.3 |
| Voltaje por PON | `.5.10.13.1.1.3.<pon>` | ~3,3 V |
| Puertos GE/GPON | IF-MIB estándar | `GE0/1..8`, `GPON0/1..8` |
| **Inventario de ONU** | IF-MIB (`ifDescr`) | 473 ONUs, nombre con nº cliente, CDO y NAP |
| Estado por ONU | `.6.1.1.1.1.5.<pon>.<onu>` | 3 = en línea (386), 4, 6 |
| **Motivo de caída** | `.6.1.1.1.1.10.<pon>.<onu>` | `Power Off` (225), `Onu Los` (174), `N/A` (74) |
| Última subida / bajada | `.6.1.1.1.1.{8,9}.<pon>.<onu>` | Timestamps |
| Tiempo en estado | `.6.1.1.1.1.11.<pon>.<onu>` | `"6 05:49:51"` |
| **Potencia óptica RX/TX** | `.6.1.1.3.1.{7,6}.<pon>.<onu>` | 386 con lectura, −32,22 a −1,57 dBm |
| Temp./voltaje de ONU | `.6.1.1.3.1.{3,4}.<pon>.<onu>` | Por ONU |

**Hallazgo aprovechable:** el **motivo de caída** distingue `Power Off` (dying gasp: se cortó
la luz en la casa del cliente) de `Onu Los` (pérdida de señal: problema de fibra nuestro).
Es la diferencia entre "no hay nada que hacer" y "mandar una cuadrilla", y hoy Pucará no lo usa.

### 2.2 Lo que NO se obtiene por SNMP  **[VERIFICADO]**

Estas ausencias son las que definen la arquitectura:

1. **El número de serie de la ONU no está.** La rama `.6.1.2` (que el `olt_poller` actual de
   Pucará consulta como `OID_ONU_SERIAL`) **no existe** en la V1600G1-B: 0 resultados en el
   walk. Coincide con un reporte independiente de la comunidad LibreNMS para la V1600G.
   → **Consecuencia:** descubrir ONUs *no autorizadas* (que se identifican justamente por su
   serial) **es imposible por SNMP**. Debe hacerse por CLI, sin alternativa.

2. **No hay sensor de temperatura de chasis.** Sólo existe la de cada SFP de PON.

3. **No hay contadores de tráfico por ONU.** Los `ifHCInOctets` de las interfaces ONU
   devuelven 0.
   → **Consecuencia:** el histórico de tráfico por cliente no puede salir de esta OLT por
   SNMP. Hay que evaluar CLI, o tomar el dato del router de borde (donde ya tenemos las 684
   sesiones PPPoE del MikroTik).

4. **No hay CPU ni memoria de la OLT** en la rama del fabricante.

5. **Ninguna operación de escritura.** No hay OIDs de aprovisionamiento.

> **Corolario de diseño:** en VSOL, SNMP es un canal de **sólo lectura y sólo parcial**.
> Todo lo que el pedido enumera como administración (autorizar, borrar, perfiles, VLAN,
> WiFi, PPPoE, reboot) **es CLI obligatoriamente**.

### 2.3 Advertencia sobre un OID engañoso  **[VERIFICADO]**

`.5.10.12.4.0` devolvía `39` en una G1 y parecía la temperatura del chasis (coincidía con la
web). En la G1-B devuelve `87`. **No es temperatura.** Un módulo que lo tome como tal reporta
87 °C y marca la OLT en crítico. Queda documentado para que no se repita: es el tipo de dato
que sólo se descubre comparando dos equipos reales.

### 2.4 Acceso CLI  **[DOCUMENTADO]**

La CLI de VSOL es de estilo Cisco (confirmado por el modelo de Oxidized, herramienta de
backup de configuración en producción):

- Login por `Login:` / `Password:`, prompt `NOMBRE>` / `NOMBRE#`
- `enable` para modo privilegiado
- `terminal length 0` para desactivar la paginación — **imprescindible** antes de cualquier
  lectura larga, si no la sesión se cuelga esperando `--More--`
- `show running-config` para respaldo de configuración
- Errores: `% Invalid input detected at`
- Telnet puede venir bloqueado; se habilita con
  `no login-access-list deny telnet 0.0.0.0 0.0.0.0`
- Valores de fábrica: AUX `192.168.8.200`, usuario `admin`, contraseña `Xpon@Olt9417#`

Comandos de aprovisionamiento (fragmentos confirmados en guías de configuración):

```
tcont 1 name 1 dba dbagpon
gemport 1 tcont 1 gemport_name 1
service srv_1 gemport 1 vlan 2001
service-port 1 gemport 1 uservlan 2001 vlan 2026
```

**[POR CONFIRMAR]** La secuencia exacta de **autorización de ONU** en V1600G1/G1-B. Se sabe
que existe `onu auto-learn` (auto-descubrimiento **activado de fábrica**, la ONU se agrega
sola con el perfil por defecto), lo que implica un modelo de trabajo distinto al de ZTE.
Falta el comando explícito de alta por serial y el de baja.

---

## 3. ZTE (C320 / C300) — soporte previsto  **[DOCUMENTADO]**

Sintaxis confirmada en manuales y repositorios públicos:

```
show gpon onu uncfg                          ← ONUs no autorizadas (con serial)
configure terminal
 interface gpon-olt_1/2/2
  onu 17 type F670L sn ZTEGC11F4854          ← autorizar por serial
 interface gpon-onu_1/2/2:17
  tcont 1 name PPPoE profile dba_inet
  gemport 1 name INTERNET tcont 1
  service-port 1 vport 1 user-vlan 1542 vlan 2542
pon-onu-mng gpon-onu_1/2/2:17                ← modo de gestión de la ONU
  reboot
show pon power attenuation gpon-onu_1/2/2:17 ← potencia y atenuación
show gpon onu state gpon-olt_1/1/1           ← estado
```

### Diferencia conceptual clave con VSOL

| | VSOL | ZTE |
|---|---|---|
| Modelo de alta | `auto-learn` **activo de fábrica**: la ONU entra sola | Autorización **explícita** por serial |
| Descubrir no autorizadas | Sin comando equivalente conocido **[POR CONFIRMAR]** | `show gpon onu uncfg` |
| Gestión de la ONU | **[POR CONFIRMAR]** | Modo dedicado `pon-onu-mng` |
| Direccionamiento | `GPON0/<pon>:<onu>` | `gpon-onu_<rack>/<shelf>/<slot>:<onu>` |

Esto **no es un detalle**: es la prueba de que la interfaz común no puede ser un calco de un
fabricante. `authorize_onu()` significa "dar de alta explícitamente" en ZTE y "confirmar y
configurar la que ya entró sola" en VSOL. La interfaz debe expresar la *intención* del
operador, y cada driver resolverla como pueda en su equipo.

---

## 4. Protocolos: qué sirve para qué

| Protocolo | Uso real | Veredicto para el módulo |
|---|---|---|
| **SNMP** | Telemetría masiva: potencias, estados, inventario | **Sí.** Canal principal de lectura. Barato y rápido |
| **Telnet/SSH (CLI)** | Todo el aprovisionamiento + lo que SNMP no expone (seriales) | **Sí.** Canal obligatorio de escritura |
| **TR-069 (CWMP)** | Config del CPE: WiFi, SSID, clave, PPPoE | **Evaluar.** Requiere un ACS. Ver 4.1 |
| **OMCI** | Protocolo OLT↔ONU interno | **No directo.** Se accede a través de la CLI de la OLT |
| **API del fabricante** | No existe en VSOL/ZTE de esta gama | No |

### 4.1 Sobre WiFi, SSID y PPPoE **[POR CONFIRMAR]**

El pedido incluye cambiar SSID, clave WiFi y PPPoE. Hay dos caminos posibles y **todavía no
está determinado cuál soportan las ONU del parque de ERLAN**:

- **Vía OLT/OMCI:** ZTE lo permite dentro de `pon-onu-mng`. En VSOL falta confirmar.
- **Vía TR-069:** requiere levantar un ACS (servidor de gestión) — es un subsistema propio,
  no una función suelta.

Es la mayor incógnita del alcance y **debe resolverse antes de comprometer esas funciones**.
Propongo tratarla como una fase separada con su propia investigación.

---

## 5. Hallazgo colateral sobre Pucará

`olt_poller.leer_seriales()` consulta `.6.1.2.1.1.3`, rama que **no existe en la V1600G1-B**.
La función devuelve vacío sin error, y la verificación "el serial de la ONU coincide con el
equipo registrado" queda silenciosamente inactiva en ese modelo.

**No lo toqué**: se pidió no modificar Pucará en esta etapa. Queda anotado para la
integración, o como corrección puntual aparte si preferís.

---

## 6. Riesgos identificados

| # | Riesgo | Impacto | Mitigación propuesta |
|---|---|---|---|
| R1 | Comando CLI mal formado en una OLT en producción | **Alto** — puede dejar clientes sin servicio | Driver con modo simulación obligatorio, *dry-run* por defecto, y allowlist de comandos |
| R2 | La CLI no es una API: cambia entre versiones de firmware | Alto | Parsers tolerantes + tests con salidas reales capturadas |
| R3 | Sesión CLI colgada por paginación | Medio | `terminal length 0` siempre, y timeout duro por comando |
| R4 | Concurrencia: dos operaciones a la vez sobre la misma OLT | **Alto** — la CLI es sesión única | Cola serializada **por OLT** |
| R5 | Timeouts intermitentes (ya observado en `192.141.23.2`) | Medio | Reintentos con backoff; nunca concluir "no existe" desde un timeout |
| R6 | Sin serial por SNMP en VSOL | Medio | Aceptado: descubrimiento por CLI |
| R7 | Alcance de TR-069 indefinido | Medio | Fase separada, no comprometer antes de investigar |
| R8 | Credenciales de OLT en base de datos | **Alto** | Cifrado en reposo + registro de auditoría de toda operación de escritura |

---

## 7. Fuentes

- [AdminOLT — sitio oficial](https://adminolt.com/en/)
- [AdminOLT — alta de OLT VSOL GPON](https://adminolt.com/en/documentacion/articulo/agregar-olt-vsol-gpon-86/)
- [AdminOLT — autorizar ONU VSOL](https://adminolt.com/en/documentacion/articulo/autorizar-onu-vsol-93/)
- [VSOL — GPON OLT Basics and Configuration](https://www.vsolcn.com/blog/vsol-gpon-olt-basics-and-configuration.html)
- [Modelo Oxidized para OLT VSOL (login, prompts, paginación)](https://gist.github.com/mdpuma/0df4bc4fe6dd8d0aad6d0445902a9f63)
- [LibreNMS — soporte VSOL V1600D](https://github.com/librenms/librenms/pull/14853)
- [LibreNMS — serial de ONU no disponible por SNMP en V1600G](https://community.librenms.org/t/vsol-v1600g-gpon-olt-onu-serial-number-not-available-via-snmp-shows-000000-00/29172)
- [ZTE C320 — configuración básica (repositorio público)](https://github.com/randifilan/zte-c320/blob/main/01.%20Basic%20Config%20OLT%20ZTE.md)
- [ZTE C300 — comandos básicos](https://github.com/denniseptian/ZTE-C300/blob/master/00.%20Perintah%20Dasar%20OLT)
- [ZTE C320 — manual de configuración CLI](https://ecolan.com.ua/components/com_jshopping/files/demo_products/CLI_MANUAL_OLT_ZTE_C320__V1.2.5_.pdf)
- [V1600D Series OLT CLI User Manual](http://kabeli.eu/upload/vsol/V1600D%20Series%20OLT%20CLI%20User%20Manual_v1.2.pdf)
- Walks SNMP de las OLT de ERLAN (V1600G1 y V1600G1-B) — evidencia primaria de esta sesión
