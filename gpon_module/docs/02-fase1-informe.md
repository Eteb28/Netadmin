# Fase 1 — Informe técnico

**Entregable comprometido:** núcleo, interfaces, modelos, esquema de base de datos, driver
simulado y tests. *Un módulo que corre entero sin una OLT real.*

**Estado: cumplido.** 143 tests en verde, sin red, sin disco y sin reloj real.

```bash
python -m gpon_module.cli demo        # ciclo completo, cero equipos involucrados
python -m pytest gpon_module/tests -q # 143 passed
```

---

## 1. Qué se implementó

### Núcleo (`core/`) — no conoce ningún fabricante

| Módulo | Contenido |
|---|---|
| `enums.py` | Vocabulario del dominio: estados, motivos de caída, severidades, tipos de métrica, **33 capacidades** |
| `models.py` | 30 entidades inmutables (`frozen=True`), tipadas |
| `interfaces.py` | Contratos (`Protocol`): `OLTDriver`, transportes, 7 repositorios |
| `errors.py` | Jerarquía propia; ninguna excepción de librería cruza la frontera de un driver |
| `registry.py` | Registro fabricante → driver. El único punto donde el núcleo nombra fabricantes |
| `optica.py` | Clasificación de potencias, **saturación incluida** |
| `cifrado.py` | Cifrado en reposo de credenciales (Fernet) |
| `reloj.py` | Tiempo inyectable: tests deterministas |

### Drivers (`drivers/`)

- **`base.py`** — capacidades, modo simulación y resultados auditables, gratis para todo
  driver que herede.
- **`transport/base.py`** — la disciplina de sesión CLI, ya escrita y probada **antes** de
  que exista el driver VSOL: desactivar paginación, serializar por OLT, reintentar
  timeouts con espera creciente, abortar la secuencia ante un rechazo.
- **`mock/`** — OLT simulada completa: 473 ONU con las proporciones reales de ERLAN,
  determinista, con estado que responde a las escrituras y con **fallas provocables**
  (timeout, lectura truncada, rechazo de comandos, autenticación fallida).

### Base de datos (`database/`)

15 tablas, esquema propio, **sin reutilizar ninguna tabla de Pucará**. Escrito para SQLite
y PostgreSQL con los mismos nombres de tabla y columna: los repositorios no cambian al
cambiar de motor.

### Servicios (`services/`)

`ServicioOLT`, `ServicioONU`, `ServicioDescubrimiento` y el contenedor de dependencias que
arma el sistema. Es la fachada del módulo: la futura API y la interfaz web consumen esto,
nunca un driver.

### Interfaz de línea de comandos (`cli.py`)

`demo`, `init-db`, `generar-clave`, `listar-olts`, `descubrir`, `onus`.

---

## 2. Decisiones tomadas

Las tres consultas del cierre de la Fase 0 se resolvieron según lo recomendado, salvo una
precisión sobre la base de datos:

| Consulta | Resolución |
|---|---|
| ¿Python? | **Python 3.11+**, sin framework en el núcleo. Flask entra recién en la Fase 3, y sólo en `web/` |
| ¿SQLite o PostgreSQL? | **Ambos, en este orden.** Ver abajo |
| ¿`dry_run=True` por defecto? | **Sí**, y en tres capas: driver, fábrica y servicio |

**Sobre la base de datos.** Se recomendó PostgreSQL por el volumen del histórico y esa
recomendación se mantiene para producción: el esquema PostgreSQL está escrito y versionado.
Lo implementado y probado ahora es SQLite, por una razón concreta: el entregable de esta
fase es *un módulo que corre entero sin nada externo*, y exigir un servidor PostgreSQL para
correr los tests lo contradice. Los repositorios se escribieron contra una interfaz de
conexión, no contra `sqlite3`; sumar PostgreSQL es agregar una clase, no reescribir la capa
de datos. Queda para la Fase 4, junto con los históricos, que es cuando el volumen empieza
a importar.

**Sobre el idioma del código.** Los nombres de método de `OLTDriver` quedaron en inglés
—`authorize_onu()`, `discover_onus()`, `get_signal()`— tal como fueron especificados; el
resto del módulo está en castellano. Es la única mezcla, y es deliberada: esa interfaz es
el contrato que se compara entre fabricantes.

---

## 3. Tres reglas que quedaron grabadas en tests

No son comentarios en un documento: si alguien las rompe, el test falla.

**Una lectura incompleta no es una baja masiva.**
`TestLecturaIncompleta`, 5 casos. Un walk truncado, un timeout y una sesión caída se
comportan distinto entre sí, y ninguno borra el inventario ni baja el contador de ONU.
La corrida queda marcada `PARCIAL` (leí a medias) o `FALLIDA` (no pude leer nada), que son
cosas distintas y llevan a decisiones distintas.

**Demasiada luz es alarma, no un valor bueno.**
`test_exceso_de_luz_es_saturacion_y_no_optima`. Una ONU a −1,57 dBm —el caso real que
apareció en el parque— se clasifica `SATURADA`, no `OPTIMA`.

**Las claves no se guardan en la auditoría.**
`test_las_claves_nunca_quedan_en_la_auditoria`. Los comandos con contraseñas WiFi o PPPoE
se registran enmascarados, y el cambio se aplica igual. La tabla de auditoría no puede
convertirse en un depósito de contraseñas.

---

## 4. Dos errores que encontraron los tests

Vale registrarlos porque son exactamente el tipo de falla que en producción se descubre
tarde:

1. **Un timeout leyendo el modelo abortaba el descubrimiento entero.** La lectura de
   identidad no estaba protegida, así que una consulta secundaria fallida tiraba abajo la
   corrida completa — incluido el inventario, que podía leerse perfectamente bien. Ahora
   cada paso degrada por separado.

2. **Una limitación conocida contaba como lectura incompleta.** Que una VSOL no exponga las
   ONU sin autorizar por SNMP es una característica del equipo, no una falla de red. Como
   estaba, *toda* corrida de una VSOL habría quedado marcada como parcial, y la marca habría
   dejado de significar algo. Ahora se distinguen las advertencias (limitación conocida) de
   las fallas (problema real de lectura).

---

## 5. Qué falta

| Fase | Contenido | Depende de |
|---|---|---|
| 2 | Driver VSOL **sólo lectura**: SNMP + CLI de consulta | Acceso a un equipo para capturar salidas reales |
| 3 | API + interfaz web (Bootstrap 5) | Fase 2 |
| 4 | Sincronización periódica, históricos, alarmas, PostgreSQL | Fase 2 |
| 5 | Driver VSOL **escritura** | Laboratorio + el comando de autorización confirmado |
| 6 | Driver ZTE | Fase 5 |
| 7 | WiFi/PPPoE (OMCI o TR-069) | Resolver la incógnita de la sección 4.1 de la investigación |
| 8 | Integración con Pucará | Fuera del alcance actual |

Dentro de esta fase quedó implementado el descubrimiento, no la sincronización periódica:
detectar bajas y cambios de estado a lo largo del tiempo es el trabajo de la Fase 4, y
depende de tener lecturas reales con las que calibrar.

---

## 6. Riesgos

### Mitigados en esta fase

| # | Riesgo | Cómo quedó cubierto |
|---|---|---|
| R1 | Comando mal formado en producción | `dry_run=True` por defecto en tres capas + auditoría de todo |
| R2 | Comando rechazado que pasa desapercibido | Detección de rechazo y **aborto de secuencia**, probado |
| R3 | Paginación que cuelga la sesión | `terminal length 0` al abrir, siempre |
| R4 | Dos operaciones simultáneas sobre una OLT | Exclusión por OLT, probada con hilos reales |
| R5 | Timeout interpretado como ausencia | Reintento con espera creciente; el timeout nunca produce lista vacía |
| R8 | Credenciales en base de datos | Cifrado obligatorio; sin clave el módulo no arranca |

### Vigentes

| # | Riesgo | Estado |
|---|---|---|
| R2 | La CLI cambia entre versiones de firmware | Estructural. Se mitiga con fixtures de salidas reales, que exigen acceso a los equipos |
| R6 | Sin serial por SNMP en VSOL | Aceptado y modelado: la capacidad se declara ausente |
| R7 | Alcance de TR-069 indefinido | Sin cambios. Sigue siendo la mayor incógnita del alcance |
| **R9** | **El simulador puede diferir del equipo real** | **Nuevo.** El driver simulado es fiel a lo *verificado*, pero no reemplaza una prueba contra hardware. Los parsers reales llegan en la Fase 2 |

---

## 7. Mejoras posibles

- **Fixtures de salidas reales** (`tests/fixtures/`): la carpeta está creada y vacía a
  propósito. Con capturas de `show running-config` y del listado de ONU de una V1600G1-B se
  pueden escribir tests de parseo antes de tener el driver, y detectar cambios de firmware
  como fallas de test en vez de como incidentes.
- **Índice único sobre `numero_serie`**: hoy no lo es, a propósito, para permitir el
  histórico de una ONU que migra de OLT. Conviene revisarlo cuando exista la Fase 4.
- **Particionado de `metricas`** por rango de fecha en PostgreSQL: el esquema ya está
  preparado (la granularidad es una columna, no una tabla).
- **`mypy --strict`** está configurado pero no se corre en cada cambio; conviene sumarlo a
  integración continua junto con `ruff`.

---

## 8. Compatibilidad

### VSOL V1600G1 y V1600G1-B

El diseño está construido sobre lo **verificado** en los walks reales de estos dos equipos:

| Aspecto | Cómo quedó resuelto |
|---|---|
| Serial de ONU ausente por SNMP | `Capacidad.SERIAL_POR_SNMP` se declarará **no** soportada. El repositorio ya protege el caso: una lectura sin serial no borra el serial ya conocido |
| Sin tráfico por ONU | `Capacidad.TRAFICO_POR_ONU` no soportada. La interfaz oculta el dato en vez de mostrar ceros |
| Sin CPU, memoria ni temperatura de chasis | Se devuelve `None`, nunca `0` |
| `Power Off` vs `Onu Los` | `MotivoCaida.APAGADO` y `MotivoCaida.PERDIDA_SENAL`, modelados desde el primer día |
| Temperatura y voltaje por PON | En el modelo `PuertoPON` |
| CLI estilo Cisco | El transporte base ya contempla `enable`, `terminal length 0` y `% Invalid input detected` |
| Direccionamiento `GPON0/<pon>:<onu>` | Encapsulado en `RefONU`; el núcleo nunca ve esa cadena |
| OID engañoso `.5.10.12.4.0` | Documentado en la investigación; no se usa |

El perfil `PERFIL_VSOL` del simulador reproduce estas limitaciones, así que el
comportamiento del sistema ante un equipo limitado **ya está probado hoy**, antes de que
exista el driver real.

**Sigue pendiente** el comando exacto de autorización de ONU en V1600G1/G1-B — el
`[POR CONFIRMAR]` más importante de la Fase 0. Bloquea la Fase 5, no las anteriores.

### ZTE (C320 / C300)

Prevista, no implementada. Lo que el diseño ya resolvió para que encaje sin cambios en el
núcleo:

- **Autorización explícita vs `auto-learn`.** `SolicitudAutorizacion` expresa la *intención*
  del operador, no una secuencia de comandos. En ZTE será un alta por serial; en VSOL,
  confirmar la que ya entró sola. La misma llamada, dos implementaciones.
- **Direccionamiento distinto** (`gpon-onu_1/2/2:17` contra `GPON0/2:17`): `RefONU` es
  neutra y cada driver la traduce.
- **`show gpon onu uncfg`**: ZTE **sí** podrá declarar `DESCUBRIR_NO_AUTORIZADAS`, y el
  sistema mostrará esa función sólo donde existe.
- **Modo `pon-onu-mng`**: es un detalle interno del driver; nada del núcleo lo conoce.

La Fase 6 es la que va a validar si la abstracción sirvió. La prueba concreta: agregar ZTE
no debería requerir **ningún** cambio en `core/`, `services/` ni `database/`.

---

## 9. Para arrancar la Fase 2

**Bloqueante:** acceso SNMP y CLI a una VSOL —idealmente no de producción— para capturar
salidas reales: `show running-config`, listado de ONU, listado de perfiles y el comando de
autorización.

Con eso, la Fase 2 (driver VSOL de sólo lectura) es directa: la interfaz está definida, el
transporte está escrito y probado, y los tests de comportamiento ya existen. Lo que falta
son los parsers, y los parsers se escriben contra salidas reales o no se escriben.
