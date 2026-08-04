# Fase 0 — Diseño de arquitectura

Documento de diseño previo a la implementación. **No hay código todavía**: se espera
aprobación antes de escribir la primera línea.

Se apoya en los hallazgos de [`00-investigacion.md`](00-investigacion.md). Dos de ellos
condicionan todo lo demás:

1. **SNMP es sólo lectura y sólo parcial.** Todo el aprovisionamiento es CLI.
2. **VSOL y ZTE no comparten modelo conceptual de alta de ONU.** La interfaz común no puede
   ser el calco de un fabricante.

---

## 1. Principio rector

> El núcleo del sistema **nunca** debe saber qué fabricante hay del otro lado.

De ahí se derivan las tres reglas que ordenan el diseño:

- Un comando CLI sólo puede existir dentro de `drivers/<fabricante>/`. Si aparece un string
  con un comando en `core/`, `services/` o `api/`, el diseño se rompió.
- Los servicios hablan con **interfaces**, nunca con implementaciones concretas.
- La web habla con la **API**, nunca con los drivers. (Requisito explícito del pedido.)

---

## 2. Estructura

```
gpon_module/
├── core/
│   ├── interfaces.py       # contratos (Protocol): OLTDriver, Transport, Repository
│   ├── models.py           # entidades tipadas: OLT, PON, ONU, Perfil, Alarma
│   ├── enums.py            # estados, severidades, motivos de caída
│   ├── errors.py           # jerarquía de excepciones propia
│   └── registry.py         # registro fabricante → driver
├── drivers/
│   ├── base.py             # base común + utilidades de parseo
│   ├── transport/
│   │   ├── snmp.py         # lectura masiva
│   │   ├── cli_telnet.py   # sesión CLI
│   │   └── cli_ssh.py
│   ├── vsol/
│   │   ├── driver.py       # implementa OLTDriver
│   │   ├── commands.py     # comandos CLI, aislados y versionados
│   │   ├── oids.py         # OIDs (los verificados en Fase 0)
│   │   └── parsers.py      # salida CLI → modelos
│   └── zte/                # misma estructura
├── database/
│   ├── schema.sql
│   ├── repositories/       # acceso a datos (Repository Pattern)
│   └── migrations/
├── services/               # lógica de negocio (orquesta drivers + repos)
├── api/                    # capa HTTP, único acceso para la web
├── web/                    # Bootstrap 5, consume sólo la API
├── tests/
│   ├── fixtures/           # salidas SNMP y CLI REALES capturadas
│   ├── mocks/              # driver simulado
│   └── ...
└── docs/
```

---

## 3. La interfaz común (`OLTDriver`)

El pedido enumera los métodos. El diseño agrega tres decisiones sobre **cómo** se declaran:

### 3.1 Separar capacidades de métodos

No todos los equipos pueden todo, y **el sistema debe saberlo sin probar y fallar**. Cada
driver declara sus capacidades:

```python
class Capacidad(Enum):
    DESCUBRIR_NO_AUTORIZADAS = auto()
    AUTORIZAR_ONU            = auto()
    TRAFICO_POR_ONU          = auto()
    WIFI_POR_OMCI            = auto()
    TEMPERATURA_CHASIS       = auto()
    ...

driver.capacidades() -> set[Capacidad]
```

Así la interfaz web **oculta** el botón que ese equipo no soporta, en vez de mostrarlo y
tirar error. Con lo verificado en Fase 0, el driver VSOL declarará `TEMPERATURA_CHASIS` y
`TRAFICO_POR_ONU` como **no** soportadas — y la UI dejará de mentir sobre esos datos.

Esta es la respuesta al problema de fondo: `authorize_onu()` no significa lo mismo en VSOL
que en ZTE. En vez de forzar una semántica única, la interfaz expresa la **intención** y
cada driver la resuelve; si no puede, lo declara de antemano.

### 3.2 Toda escritura devuelve un resultado auditable

Nunca `bool`. Una operación de aprovisionamiento debe poder explicarse después:

```python
@dataclass(frozen=True)
class ResultadoOperacion:
    ok: bool
    comandos_enviados: list[str]     # qué se ejecutó exactamente
    salida_cruda: str                # qué contestó el equipo
    error: str | None
    simulado: bool                   # True si fue dry-run
```

### 3.3 Modo simulación obligatorio (mitiga R1)

Todo driver se construye con `dry_run: bool`. En `True` **arma los comandos y no los envía**.
Es la única defensa real contra dejar clientes sin servicio por un comando mal formado, y
permite revisar en pantalla qué se va a ejecutar antes de tocar una OLT en producción.

Propongo que `dry_run=True` sea el **valor por defecto** y que ejecutar de verdad requiera
pedirlo explícitamente.

---

## 4. Transporte CLI: los detalles que hacen que funcione

Concentrados en `drivers/transport/`, porque son los que rompen en producción:

| Problema | Solución de diseño | Riesgo que mitiga |
|---|---|---|
| Paginación (`--More--`) cuelga la sesión | `terminal length 0` al abrir, siempre | R3 |
| La CLI es de sesión única | **Cola serializada por OLT**: nunca dos operaciones simultáneas al mismo equipo | R4 |
| Timeouts intermitentes (visto en `192.141.23.2`) | Reintento con backoff; un timeout **nunca** se interpreta como "no existe" | R5 |
| Un comando inválido pasa desapercibido | Detectar `% Invalid input detected` y **abortar la secuencia** | R2 |
| Secuencia a medias deja la OLT inconsistente | Toda operación multi-comando define su **rollback** | R1 |

---

## 5. Modelo de datos

Base **propia**, sin reutilizar tablas de Pucará (requisito explícito).

Tablas núcleo:

- `olts` — conexión, credenciales **cifradas**, fabricante, modelo, firmware
- `pon_ports` — puertos por OLT
- `onus` — inventario; incluye `serial`, `pon`, `onu_id`, `estado`, `motivo_caida`
- `perfiles_dba`, `perfiles_linea`, `perfiles_servicio`, `service_ports`, `vlans`
- `alarmas` — con `regla_id`, estado y reconocimiento
- `eventos` — bitácora de cambios detectados por sincronización
- `operaciones` — **auditoría de toda escritura**: quién, cuándo, qué comandos, qué respondió

### Históricos: decisión sobre el volumen

El pedido pide históricos de RX/TX/temperatura/CPU/etc. Con **473 ONUs en una sola OLT** y
sondeo cada 5 minutos, una tabla ingenua son ~50 millones de filas al año por OLT.

Propuesta: tabla `metricas` con **retención por escalones** —
detalle fino 7 días → promedios horarios 90 días → promedios diarios 2 años.
Es la diferencia entre un histórico consultable y una base inmanejable a los seis meses.

---

## 6. Sincronización

Ciclo desacoplado del aprovisionamiento, en tres niveles de frecuencia:

| Nivel | Frecuencia | Canal | Qué trae |
|---|---|---|---|
| Rápido | 1–5 min | SNMP | Potencias, estados, motivo de caída |
| Medio | 15–60 min | SNMP + CLI | Inventario de ONU, altas y bajas |
| Lento | diario | CLI | Perfiles, service-ports, VLAN, `running-config` |

Cada corrida **compara contra el estado anterior** y registra los cambios como eventos:
ONU nueva, ONU que desapareció, cambio de potencia, de firmware, de perfil.

**Regla heredada de la experiencia con Pucará:** una lectura incompleta **no** se interpreta
como "todo se cayó". Si el walk viene truncado o la sesión da timeout, se marca la corrida
como parcial y **no** se disparan alarmas de baja masiva. Este error ya ocurrió en producción
y no debe repetirse.

---

## 7. Alarmas

Reglas configurables, con umbral, severidad e histéresis:

```
ONU offline · potencia baja (< −27 dBm) · potencia crítica (< −29 dBm)
potencia SATURADA (> −8 dBm) · OLT caída · puerto saturado · temperatura alta
pérdida óptica · CPU/memoria altas · sincronización fallida
```

Dos decisiones sacadas de hallazgos reales de esta sesión:

- **Saturación incluida desde el día uno.** Se encontró una ONU a −1,57 dBm que el sistema
  anterior contaba como "óptima" porque sólo miraba el extremo bajo. Demasiada luz daña el
  receptor: es alarma, no un valor bueno.
- **La alarma distingue `Power Off` de `Onu Los`.** Un corte de luz en la casa del cliente no
  es lo mismo que una fibra cortada. Sin esa distinción, una zona sin luz genera decenas de
  alarmas que parecen un problema de red y no lo son.

---

## 8. Preparación para integrar con Pucará

Sin dependencias hacia Pucará en ninguna dirección. La integración futura será:

```python
from gpon_module.services import ServicioONU     # Pucará importa el módulo
```

El módulo expone **servicios y modelos propios**; Pucará adapta esos modelos a los suyos en
su propia capa. El módulo nunca importa nada de Pucará: así no hay ciclos y se puede
desarrollar y probar solo.

---

## 9. Plan de fases

| Fase | Contenido | Entregable |
|---|---|---|
| **0** | Investigación y diseño | **Este documento** ← acá estamos |
| 1 | Núcleo: interfaces, modelos, esquema de BD, driver simulado + tests | Módulo que corre entero sin una OLT real |
| 2 | Driver VSOL **sólo lectura**: SNMP + CLI de consulta | Inventario y potencias reales, cero riesgo |
| 3 | Web + API: dashboard, listados, gráficos, alarmas | Sistema usable en modo lectura |
| 4 | Sincronización e históricos | Detección de cambios y retención escalonada |
| 5 | Driver VSOL **escritura**, con dry-run | Aprovisionamiento, previa validación en laboratorio |
| 6 | Driver ZTE | Valida que la abstracción sirvió |
| 7 | WiFi/PPPoE (OMCI o TR-069) | Sólo tras resolver la incógnita de la sección 4.1 |
| 8 | Integración con Pucará | Fuera del alcance actual |

Orden deliberado: **todo lo que lee antes de todo lo que escribe.** Las fases 2–4 dan valor
inmediato sin poder romper nada, y para cuando llegue la fase 5 los parsers ya estarán
probados contra salidas reales.

---

## 10. Qué necesito para arrancar la Fase 1

**Bloqueante:**

1. **Aprobación de este diseño** (o los cambios que quieras).

**Necesario antes de la Fase 2, no antes de la 1:**

2. Acceso CLI de laboratorio a una VSOL (idealmente **no** de producción) para capturar
   salidas reales de: `show running-config`, listado de ONU, perfiles, y el comando de
   autorización — el punto **[POR CONFIRMAR]** más importante.
3. Confirmar si las ONU del parque soportan gestión WiFi por OMCI, o si hace falta TR-069.

**Decisiones tuyas:**

4. ¿Python + Flask, para que la integración futura con Pucará sea directa? Es lo que
   recomiendo por coherencia con el stack actual.
5. ¿Base de datos: SQLite (como Pucará) o PostgreSQL (mejor para series temporales)?
   Recomiendo **PostgreSQL** por el volumen de históricos de la sección 5, aunque implica
   una dependencia nueva.
6. ¿`dry_run=True` por defecto en todos los drivers, como propongo?
