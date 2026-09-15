# Plan de implementación — TR-069 con GenieACS

- **Estado:** propuesto (requiere aprobación)
- **Fecha:** septiembre 2026
- **Resuelve:** configuración de WAN (PPPoE), DHCP y WiFi de las ONU, que hoy el módulo GPON no logra ni por CLI ni por SSH

---

## 1. Por qué no se puede por CLI ni por SSH

No es que falte el comando. **Se está intentando configurar desde la OLT algo que la OLT no administra.**

En GPON hay dos capas y se confunden seguido:

| Capa | Quién la administra | Qué incluye | Cómo se configura |
|---|---|---|---|
| **Transporte GPON** | La OLT | T-CONT, GEM ports, service-port, VLAN, perfiles DBA y de línea | CLI de la OLT, SNMP |
| **Gateway residencial** | La ONU (HGU) | WAN PPPoE, servidor DHCP de LAN, SSID y clave WiFi | **TR-069 / CWMP** |

La OLT llega a la ONU por OMCI (ITU-T G.988), pero el OMCI estándar cubre un conjunto acotado
que **no incluye** la configuración de gateway residencial. Lo que hay más allá son extensiones
propietarias de cada fabricante, no documentadas y distintas entre firmwares.

Por eso el módulo GPON se traba: por ese camino no está el volante.

**TR-069 (CWMP, TR-069 Amendment 6) es el protocolo estándar para exactamente esto.** La ONU
abre una sesión HTTP contra un servidor (el ACS), le informa qué es y qué parámetros tiene, y el
ACS le escribe la configuración. Funciona sin importar el fabricante de la OLT.

### Qué NO resuelve TR-069

Conviene decirlo antes de empezar para que nadie espere de más:

- **El service-port, la VLAN y los perfiles siguen siendo de la OLT.** El módulo GPON no
  desaparece: pasa a cubrir la mitad de transporte, y TR-069 cubre la otra mitad.
- **El alta física de la ONU en la OLT sigue siendo por CLI.** Hasta que la ONU no esté
  autorizada y con service-port, no tiene camino a la red y por lo tanto no llega al ACS.
- **Una ONU en modo bridge no tiene nada que configurar por TR-069.** Esto aplica a las que
  están en modo router (HGU), que son las que dan el problema.

---

## 2. Decisión

**Levantar GenieACS como servidor TR-069, con Pucará como única fuente de verdad de la
configuración, y que el módulo GPON conserve la parte de transporte.**

GenieACS es software libre (licencia AGPL), Node.js + MongoDB, usado por ISP del tamaño de
ERLAN. Tiene API REST, lo que permite integrarlo sin tocar el núcleo de Pucará.

### La decisión que define todo el resto: quién le pregunta a quién

Hay dos formas de conectar Pucará con el ACS, y elegir mal cuesta caro después.

| | **Empuje** — Pucará escribe en GenieACS | **Consulta** — GenieACS le pregunta a Pucará |
|---|---|---|
| Cuándo actúa | Cuando el operador guarda el cliente | Cada vez que la ONU se conecta |
| Si la ONU se resetea de fábrica | **Queda sin configuración** hasta que alguien la reenvíe | Se reconfigura sola |
| Si se cambia una ONU por otra | Hay que acordarse de reenviar | La nueva toma la configuración al arrancar |
| Fuente de verdad | Duplicada en dos sistemas | **Sólo Pucará** |
| Complejidad | Menor | Un script de provisión que llama a una API |

**Se elige consulta.** Un reseteo de fábrica es lo primero que hace un técnico cuando algo
anda mal, y con el modelo de empuje eso deja al cliente sin servicio hasta que alguien se
acuerde de reenviar la configuración. Con consulta, la ONU se reconfigura sola al arrancar.

> El empuje se usa igual, pero sólo para **forzar** un cambio inmediato (el operador toca
> "aplicar ahora"). La configuración correcta siempre sale de Pucará.

---

## 3. Arquitectura

```text
        ┌───────────────────────────────────────────────────────────────┐
        │                          PUCARÁ                               │
        │  Ficha del cliente: PPPoE, VLAN, plan, SSID, rango DHCP       │
        │  ── fuente de verdad ──                                       │
        │                                                               │
        │  GET  /api/v2/tr069/config/<device_id>   ← lo consulta el ACS │
        │  POST /api/v2/tr069/aplicar/<cliente>    → fuerza un cambio   │
        └───────────────┬───────────────────────────────┬───────────────┘
                        │ (1) ¿de quién es              │ (4) forzar
                        │     este equipo?              │     aplicación
                        ▼                               ▼
        ┌───────────────────────────────────────────────────────────────┐
        │                        GENIEACS                               │
        │  cwmp :7547   nbi :7557   fs :7567   ui :3000   MongoDB       │
        │  Provisión «pucara-config» → ext() → consulta a Pucará        │
        └───────────────┬───────────────────────────────────────────────┘
                        │ (2) Inform / (3) SetParameterValues
                        │     CWMP sobre la VLAN de gestión
                        ▼
        ┌───────────────────────────────────────────────────────────────┐
        │              ONU / HGU  (VSOL u otras)                        │
        │  WAN PPPoE · servidor DHCP de LAN · SSID y clave WiFi         │
        └───────────────────────────────────────────────────────────────┘
                        ▲
                        │ service-port · VLAN · T-CONT  (sigue por CLI)
        ┌───────────────┴───────────────────────────────────────────────┐
        │                     OLT VSOL — módulo GPON                    │
        └───────────────────────────────────────────────────────────────┘
```

El flujo normal, de punta a punta:

1. El técnico da de alta la ONU en la OLT (módulo GPON: autorizar, service-port, VLAN).
2. La ONU toma IP de gestión y hace **Inform** al ACS.
3. GenieACS ejecuta la provisión `pucara-config`, que llama a Pucará: *«soy
   `VSOL-V2802-ABC12345`, ¿qué configuración me corresponde?»*.
4. Pucará busca el serial en el padrón, arma la configuración del cliente y la devuelve.
5. GenieACS escribe los parámetros en la ONU.
6. Pucará registra qué se aplicó y cuándo.

---

## 4. Fases

### El parque real de ERLAN (dato de septiembre 2026)

| | Modelo | Firmware |
|---|---|---|
| **OLT** | VSOL V1600G1 | V2.3.1R |
| **OLT** | VSOL V1600G1B | V1.4.14R |
| **ONU** | V2802DAC, V2802GW | V3.2.00 · V1.9.1.2 · **TIGRE-V1.0** · V2.1.06 |

Tres lecturas de esto:

**1. Las dos ONU son HGU.** `V2802GW` es literalmente *gateway*, y la `DAC` es la
variante con WiFi doble banda. Las dos hacen router, WiFi y DHCP: son exactamente el
caso que TR-069 viene a resolver. Bien.

**2. Cuatro firmwares sobre dos modelos es mucha dispersión.** Eleva el riesgo R4: cada
combinación de modelo + firmware es, potencialmente, un árbol de parámetros distinto que
hay que verificar por separado.

**3. `TIGRE-V1.0` trae TR-069 activo de fábrica. Los otros tres, no.** (Confirmado por
ERLAN, septiembre 2026.)

Eso da vuelta el problema respecto de lo que uno supondría. El firmware a medida no es el
riesgo: **es el atajo.** Alguien lo compiló justamente para que las ONU se administren por
ACS, y ahí el cliente CWMP ya está andando.

El trabajo real está en los otros tres — `V3.2.00`, `V1.9.1.2` y `V2.1.06` — y no es
descubrir rutas de parámetros: es **activar TR-069 en una flota ya instalada**, casa por
casa o de forma remota. Ese pasa a ser el riesgo principal del plan.

| | Firmware | TR-069 | Qué hay que hacer |
|---|---|---|---|
| ✅ | `TIGRE-V1.0` | **activo de fábrica** | Nada. Apuntarlo al ACS y anda |
| ⚠️ | `V3.2.00`, `V1.9.1.2`, `V2.1.06` | inactivo | **Activarlo.** Es el problema a resolver |

#### Cómo se activa en los tres que no lo traen

Cuatro caminos, de mejor a peor:

1. **Por OMCI desde la OLT**, si el firmware de la OLT expone la ME correspondiente. Sería lo
   ideal: masivo, remoto y sin tocar al cliente. Hay que verificarlo en las dos OLT por
   separado, que están en líneas bastante distintas (`V2.3.1R` y `V1.4.14R`).
2. **Por plantilla de perfil de ONU en la OLT**, si VSOL permite fijar la URL del ACS en el
   perfil que se aplica al autorizar. Serviría para las altas nuevas, no para lo instalado.
3. **Actualización de firmware** a una build con CWMP activo — idealmente la misma `TIGRE`.
   Masivo pero pesado, y hay que validar que no rompa nada.
4. **Web de cada ONU, una por una.** Es el peor caso: no escala a 2.400 equipos y sólo sirve
   como plan de última instancia para un grupo chico.

**El censo decide cuál de estos caminos hace falta y cuánto cuesta**, porque dice qué
proporción de la flota ya está lista y cuánta hay que intervenir.

> Lo que todavía **no** se puede afirmar desde acá: con qué rutas de parámetros responde cada
> firmware. No hay documentación pública confiable de la implementación CWMP de VSOL para
> estas versiones. Sale del equipo o no sale.

### Fase 0 — Descubrimiento · **es la primera y no se puede saltear**

#### Paso 0.a — Censo de la flota por SNMP · *media tarde, sin tocar ninguna ONU*

Antes de pedir una ONU de laboratorio conviene saber **cuántas hay de cada combinación**.
Ese dato hoy no está: `onu_senal` guarda serial y señal, pero no modelo ni firmware.

La OLT sí lo sabe. `olt_poller.py` ya dejó mapeada la rama de ONU de VSOL
(`1.3.6.1.4.1.37950.1.1.6.1.2.1.1.3` = serial, indexado por `<pon>.<onu>`), que es una
**tabla SNMP**: las columnas vecinas traen el resto de los atributos de cada ONU.

```bash
# 1. Descubrir qué trae cada columna
python3 scripts/censo_onu_vsol.py --descubrir 192.168.10.247 <community>

# 2. Con las columnas identificadas, censar
python3 scripts/censo_onu_vsol.py --censo 192.168.10.247 <community> \
        --col-modelo N --col-firmware M --csv censo.csv
```

Es de sólo lectura: `snmpbulkwalk` y nada más.

**Entregable:** cuántas ONU de cada modelo y firmware, y en qué PON.

**El número que decide el proyecto:** qué proporción de la flota corre `TIGRE-V1.0` —o sea,
ya está lista para el ACS— y cuánta hay que intervenir. Si `TIGRE` es mayoría, esto arranca
con valor inmediato sobre buena parte de los clientes. Si es una minoría, el plan depende
enteramente de resolver la activación remota (riesgo R1b).

> Conviene verificar la columna sugerida contra la web de la OLT antes de darla por buena.
> Ya hubo un OID que parecía temperatura de chasis y no lo era: la historia está en el
> encabezado de `olt_poller.py` y terminó marcando una OLT en estado crítico por nada.

#### Paso 0.b — Árbol de parámetros sobre una ONU real

**Nadie puede escribir el script de provisión sin ver primero una ONU real.** Las rutas de
parámetros TR-069 cambian entre fabricante, modelo y firmware. Las dos familias posibles:

| | TR-098 (`InternetGatewayDevice.`) | TR-181 (`Device.`) |
|---|---|---|
| PPPoE usuario | `InternetGatewayDevice.WANDevice.1.WANConnectionDevice.1.WANPPPConnection.1.Username` | `Device.PPP.Interface.1.Username` |
| SSID | `InternetGatewayDevice.LANDevice.1.WLANConfiguration.1.SSID` | `Device.WiFi.SSID.1.SSID` |
| Clave WiFi | `…WLANConfiguration.1.PreSharedKey.1.KeyPassphrase` | `Device.WiFi.AccessPoint.1.Security.KeyPassphrase` |
| DHCP LAN | `InternetGatewayDevice.LANDevice.1.LANHostConfigManagement.*` | `Device.DHCPv4.Server.Pool.1.*` |

La mayoría de los HGU GPON usan TR-098, pero **hay que verificarlo**, no asumirlo.

**Cómo se hace:** una ONU de laboratorio contra GenieACS, y leer el árbol completo que el
equipo publica (`GetParameterNames` sobre la raíz). GenieACS lo muestra en su UI.

**Entregable:** una tabla con la ruta exacta de cada parámetro que hace falta, por modelo de
ONU y versión de firmware.

**Orden de prueba:** primero `TIGRE-V1.0`, que ya trae TR-069 activo. No por ser el difícil
—es el fácil— sino porque **valida la cadena entera de punta a punta** (ONU → ACS → Pucará)
sin pelearse todavía con la activación. Una vez que eso anda, el problema de activar los
otros tres queda aislado y se puede atacar solo.

**Criterio de éxito:** cambiar el SSID de una ONU de laboratorio desde la UI de GenieACS y
verlo aplicado en el equipo.

> **Si esta fase falla, el plan se cancela acá y se perdió una semana, no un trimestre.**
> Es posible que un modelo de ONU no traiga TR-069 habilitado de fábrica, o que no exponga
> los parámetros de WiFi. Mejor saberlo ahora.

### Fase 1 — GenieACS en pie, aislado de Pucará

- Servidor propio (VM o contenedor): Node.js 20+, MongoDB 6+, GenieACS 1.2.x.
- Los cuatro servicios: `genieacs-cwmp` (7547), `genieacs-nbi` (7557), `genieacs-fs` (7567),
  `genieacs-ui` (3000).
- **Alcanzabilidad:** la ONU tiene que llegar al puerto 7547 por la VLAN de gestión, y el ACS
  tiene que poder llegar a la ONU para el *Connection Request* (el mecanismo con el que el ACS
  le dice "conectate ahora" en vez de esperar al chequeo periódico). Esto es ruteo, y es la
  parte que más suele demorar.
- TLS con certificado propio y usuario/clave CWMP por equipo.
- Configuración manual desde la UI, sin Pucará todavía.

**Criterio de éxito:** tres ONU de prueba, en tres casas distintas, configuradas desde la UI
de GenieACS y funcionando.

### Fase 2 — El puente de identidad

Es el corazón de la integración y es poco código.

**En Pucará** — endpoint de sólo lectura, siguiendo la arquitectura en capas:

```
GET /api/v2/tr069/config/<device_id>
→ { cliente_id, nro_cliente, pppoe: {usuario, clave}, vlan,
    wifi: {ssid, clave}, dhcp: {habilitado, desde, hasta, lease} }
```

El `device_id` de TR-069 es `OUI-ProductClass-SerialNumber`. Pucará resuelve el serial contra
`clientes.equipo_serie` — **usando la normalización que ya existe** en
`pucara/services/inventario.py` (`normalizar_serie`, que resuelve que el mismo serial esté
cargado como `VSOL-1234 5678`, `vsol12345678` o `VSOL:12345678`).

Un serial que no resuelve a ningún cliente **no devuelve una configuración por defecto**:
devuelve 404 y queda registrado. Configurar a ciegas un equipo que no sabemos de quién es, es
peor que no configurarlo.

**En GenieACS** — una provisión que llama a ese endpoint:

```javascript
// provisión: pucara-config
const id = declare("DeviceID.SerialNumber", {value: 1}).value[0];
const oui = declare("DeviceID.OUI", {value: 1}).value[0];
const clase = declare("DeviceID.ProductClass", {value: 1}).value[0];

const cfg = ext("pucara", "config", `${oui}-${clase}-${id}`);
if (!cfg || !cfg.pppoe) return;   // sin cliente asociado: no se toca nada

declare(RUTA_PPPOE_USUARIO, null, {value: cfg.pppoe.usuario});
declare(RUTA_PPPOE_CLAVE,   null, {value: cfg.pppoe.clave});
declare(RUTA_SSID,          null, {value: cfg.wifi.ssid});
// … las rutas exactas salen de la fase 0
```

Y un *preset* que la dispara en los eventos `0 BOOTSTRAP`, `1 BOOT` y `2 PERIODIC`.

**Criterio de éxito:** resetear de fábrica una ONU de prueba y que vuelva sola, sin que nadie
toque nada, con el PPPoE y el WiFi del cliente correcto.

### Fase 3 — Operación desde Pucará

Recién acá el operador deja de entrar a GenieACS.

- En la ficha del cliente: ver la configuración vigente de la ONU, la última vez que reportó
  y el firmware.
- Botón **aplicar ahora**: Pucará encola una tarea, llama al NBI de GenieACS con
  *connection request*, y muestra el resultado.
- Cambiar SSID y clave WiFi desde la ficha, sin entrar al equipo.
- **Toda escritura queda auditada** con el mecanismo que ya existe
  (`pucara/repositories/auditoria.py`): quién, cuándo, de qué a qué. La clave PPPoE y la del
  WiFi ya están en `CAMPOS_SECRETOS`, así que se registra que cambiaron sin escribir el valor.

### Fase 4 — Lo que se cosecha de yapa

Una vez que las ONU hablan con el ACS, sale gratis:

- **Inventario real de ONU**: serial, modelo y firmware de cada equipo que se conecta. Entra
  directo en la conciliación de inventario construida la semana pasada, como una quinta fuente
  junto a `onu_senal`, `snmp_estaciones`, `torre_equipos` y `stock_items`.
- **Auditoría de firmware**: qué equipos corren versiones viejas.
- **Diagnóstico remoto**: potencia óptica y estado de WiFi reportados por la propia ONU.
- **Actualización de firmware masiva** por grupos.

---

## 5. Modelo de datos

Tres tablas nuevas en el paquete en capas, con migración Alembic reversible:

| Tabla | Para qué |
|---|---|
| `tr069_dispositivos` | `device_id`, `cliente_id`, serial, OUI, modelo, firmware, `ultimo_inform`, `ip_gestion` |
| `tr069_tareas` | Cola de cambios pedidos: qué parámetro, qué valor, estado, intentos, resultado |
| `tr069_eventos` | Bitácora: cada Inform y cada aplicación, con qué se escribió y qué contestó el equipo |

`tr069_dispositivos` es el puente entre el device ID de TR-069 y el `cliente_id` de Pucará.
No duplica el padrón: lo referencia.

---

## 6. Seguridad — hay que arreglar algo antes de empezar

### La clave PPPoE está en texto plano y sale al navegador

Hoy `clientes.pppoe_clave` se guarda sin cifrar y se envía al frontend
(`static/js/clientes.js:136`). Funciona, pero **este plan la hace circular por un sistema
más** y por la red hacia cada ONU. Eso convierte un problema latente en uno activo.

**No es opcional y va antes de la fase 2:**

1. Cifrar `pppoe_clave` en reposo con una clave maestra fuera de la base.
2. Que la API **no** devuelva la clave al listar clientes; sólo bajo pedido explícito, con
   permiso, y quedando auditado quién la miró.
3. Que el endpoint `/api/v2/tr069/config/` sea el único que la entrega en claro, sólo al ACS,
   autenticado y sobre TLS.

### El resto de los controles

| Riesgo | Control |
|---|---|
| CWMP expuesto a internet | El puerto 7547 **sólo** en la VLAN de gestión. Nunca con IP pública |
| Cualquiera se hace pasar por una ONU | Usuario y clave CWMP **por equipo**, no compartidos |
| El NBI de GenieACS es una API sin autenticación por defecto | Escucha sólo en localhost o detrás de un proxy con autenticación. **Quien llega al NBI reconfigura toda la red** |
| Credenciales viajando en claro | TLS en CWMP y en el NBI |
| Pucará expone la configuración de cualquiera | El endpoint `/api/v2/tr069/config/` autenticado con un token propio del ACS, no con sesión de usuario |

---

## 7. Riesgos

| # | Riesgo | Probabilidad | Mitigación |
|---|---|---|---|
| R1 | Un modelo de ONU no expone los parámetros de WiFi o DHCP por TR-069 | Media | Fase 0. Se sabe con una semana de trabajo, no con un trimestre |
| **R1b** | **No hay forma masiva de activar TR-069 en `V3.2.00`, `V1.9.1.2` y `V2.1.06`** | **Alta** | **Es el riesgo principal del plan.** Si ni OMCI ni el perfil de la OLT sirven, queda actualizar firmware a toda la flota o visitar casa por casa. El censo dice cuántos equipos son; eso decide si el plan sigue, se acota a las altas nuevas, o se frena |
| R2 | El ACS no puede alcanzar la ONU para el *connection request* | **Media** | Sin esto, los cambios se aplican recién en el chequeo periódico (horas). Verificar el ruteo en la fase 1 |
| R3 | Una provisión mal escrita se aplica a toda la red | **Baja, impacto altísimo** | Presets por etiqueta. Grupo de prueba de 10 clientes durante dos semanas antes de ampliar |
| R4 | Heterogeneidad de firmware entre ONU del mismo modelo | Alta | El script resuelve rutas por modelo y firmware, no una sola ruta fija |
| R5 | La ONU pierde la configuración al actualizar firmware | Media | El evento `0 BOOTSTRAP` la vuelve a aplicar sola. Es un beneficio del modelo de consulta |
| R6 | MongoDB es una pieza de operación nueva | Baja | Respaldo diario y monitoreo. Es la única dependencia nueva de infraestructura |

> **Sobre R3.** Vale la misma regla que quedó escrita para el módulo GPON: *un comando mal
> formado no genera un error de pantalla, deja clientes sin servicio.* Con TR-069 el alcance
> es mayor, porque un preset mal filtrado toca cientos de equipos en minutos. Por eso el grupo
> de prueba no es opcional.

---

## 8. Qué se necesita de ERLAN para arrancar

Los modelos y firmwares ya están (ver arriba). Queda pendiente:

1. ~~Modelo y firmware de las OLT~~ · **resuelto:** V1600G1 `V2.3.1R` y V1600G1B `V1.4.14R`.
2. ~~Modelos de ONU~~ · **resuelto:** V2802DAC y V2802GW, ambos HGU. Falta saber **cuántas
   están en modo bridge**, porque esas no participan de TR-069. El censo lo aclara en parte;
   el resto sale de `clientes.modo_equipo`.
3. ~~Si las ONU traen TR-069 habilitado~~ · **resuelto:** sólo `TIGRE-V1.0`. En su lugar
   queda la pregunta que importa: **¿se puede activar TR-069 por OMCI o por perfil desde las
   OLT?** Hay que probarlo en las dos por separado (`V2.3.1R` y `V1.4.14R`). De la respuesta
   depende que esto sea un proyecto de un mes o una campaña de actualización de firmware a
   toda la planta.
4. **Plan de direccionamiento de la VLAN de gestión**: qué rango usan las ONU y si el servidor
   del ACS puede rutear hacia ahí. Es lo que decide si un cambio se aplica al momento o recién
   en el chequeo periódico.

Más una decisión de negocio: **una ONU de laboratorio** que se pueda resetear y romper sin
afectar a un cliente. **Dos, en realidad:** una con `TIGRE-V1.0` para validar la cadena
entera rápido, y otra con cualquiera de los tres restantes para atacar la activación.

---

## 9. Orden y esfuerzo

| Fase | Trabajo | Depende de |
|---|---|---|
| 0.a · Censo de la flota por SNMP | **media tarde** | Nada — se puede correr hoy |
| 0.b · Árbol de parámetros | ~1 semana | Una ONU de laboratorio por firmware |
| 1 · GenieACS en pie | ~1 semana | Servidor y VLAN de gestión ruteada |
| — · Cifrar la clave PPPoE | ~2 días | — (se puede hacer en paralelo) |
| 2 · Puente de identidad | ~1 semana | Fases 0 y 1 |
| 3 · Operación desde Pucará | ~2 semanas | Fase 2 |
| 4 · Cosecha | ~1 semana | Fase 3 |

Las estimaciones de las fases 2 a 4 **dependen del resultado de la fase 0** y hay que
revisarlas cuando esté. Si el modelo de datos de las ONU resulta ser uniforme, las fases 2 y 3
se acortan; si hay tres modelos con árboles distintos, se alargan.

**Puertas de decisión:** al terminar la fase 0 y al terminar la fase 2. En cada una se decide
seguir o parar, con evidencia y no con expectativa.

---

## 10. Cómo encaja con lo que ya hay

- **El módulo GPON no se tira ni se frena.** Conserva su alcance —autorización de ONU,
  service-port, VLAN, perfiles— que es la mitad que TR-069 no toca. Lo que cambia es que deja
  de intentar configurar WAN, DHCP y WiFi, que no le corresponde.
- **Pucará no cambia de arquitectura.** El módulo TR-069 nace en el paquete en capas
  (`models` → `repositories` → `services` → `api`), con las reglas que ya hace cumplir
  `tests/test_arquitectura.py`: nada de SQL fuera de Repository, blueprint protegido con
  `proteger()`, ningún archivo de más de 500 líneas.
- **Se reutiliza lo construido:** `normalizar_serie()` de inventario para resolver el equipo,
  `AuditoriaRepository` para el registro de cambios, `CAMPOS_SECRETOS` para no filtrar claves
  en la bitácora.
- **Nada sin pruebas**, como siempre: el resolvedor de identidad y el armado de configuración
  se prueban sin GenieACS ni ONU, con fixtures.

Si este plan se aprueba, la decisión se registra como **ADR-0005** siguiendo la convención de
`docs/adr/`.
