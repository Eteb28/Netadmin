# Módulo GPON

Administración de OLT y ONU multifabricante, con equivalencia funcional a AdminOLT.

Proyecto **independiente**: no importa nada de Pucará ni comparte su base de datos. La
integración futura será por servicios, no por tablas compartidas.

**Estado: fases 1 a 3.** Núcleo, base de datos, driver VSOL de **lectura**, API e interfaz
web. Corre entero contra una OLT simulada, sin necesidad de ningún equipo. La escritura
sobre equipos reales (Fase 5) y el driver ZTE (Fase 6) todavía no están.

---

## Probarlo en un minuto

No requiere base de datos, ni credenciales, ni una OLT:

```bash
python -m gpon_module.cli demo             # recorrido completo por consola
python -m gpon_module.cli web --simulada   # interfaz web en http://127.0.0.1:8070
```

El demo da de alta una OLT simulada, la descubre entera (473 ONU, 8 puertos PON), clasifica
las potencias ópticas, y muestra los comandos exactos que *se habrían enviado* al autorizar
una ONU — sin enviar ninguno.

`web --simulada` levanta la interfaz con ese mismo parque, sin base de datos ni credenciales:
panel, listado de OLT y ONU con filtros, potencias con histograma, eventos y auditoría.

## Instalación

```bash
pip install -e ".[desarrollo,web]"    # núcleo, interfaz web y herramientas de prueba
```

El comando `gpon` queda disponible **dentro del entorno virtual**. Si el entorno no está
activado, `gpon` no existe y la terminal responde *"Orden «gpon» no encontrada"*. Para
evitar ese paso hay un atajo que resuelve el entorno solo:

```bash
./gpon_module/gpon web --simulada     # desde el repositorio
./gpon web --simulada                 # desde el paquete distribuido
```

Sólo hay una dependencia obligatoria: `cryptography`, para no guardar las credenciales de
las OLT en texto plano. El resto es biblioteca estándar. Las dependencias de cada fase
(`equipos`, `web`, `postgres`) se instalan cuando esa fase llega.

## Configuración

Todo se configura por variables de entorno `GPON_*`:

```bash
export GPON_CLAVE_CIFRADO="$(python -m gpon_module.cli generar-clave)"
export GPON_BASE_DATOS="sqlite:///gpon.db"
python -m gpon_module.cli init-db
```

Guardá la clave donde no se pierda (gestor de secretos, o el `.env` del servidor con
permisos `600`). Si se pierde, las credenciales guardadas quedan irrecuperables y hay que
volver a cargarlas.

## Interfaz web

```bash
gpon web                       # usa la base configurada
gpon web --simulada            # OLT simulada, base en memoria, nada que configurar
gpon web --host 0.0.0.0 --puerto 8070
```

| Pantalla | Contenido |
|---|---|
| Panel | Cifras del parque, estado, cortes de luz contra fibra cortada, últimos eventos |
| OLT | Listado, prueba de conexión y descubrimiento |
| Detalle de OLT | Puertos PON, última corrida y **qué puede hacer ese modelo** |
| ONU | Inventario con búsqueda, filtro por PON y estado, y paginación |
| Detalle de ONU | Inventario, óptica en vivo y operaciones hechas sobre ella |
| Potencias | Histograma de RX y las que requieren atención, ordenadas por urgencia |
| Eventos | Histórico de cambios del inventario |
| Auditoría | Toda escritura, con los comandos exactos y si fue real o simulada |
| Drivers | Qué sabe hacer cada fabricante, con lo no soportado tachado |

Bootstrap y Chart.js van **servidos localmente**, no por CDN: un servidor de NOC suele estar
en una VLAN de gestión sin salida a internet, y con CDN la interfaz se vería rota justo
donde tiene que funcionar.

La web nunca habla con un driver: consume la API (`/api/...`), y eso está sostenido por un
test que falla si alguna ruta web importa un servicio.

## Con base persistente

```bash
gpon alta-olt --nombre "OLT Centro" --host 192.168.1.10 --fabricante simulado
gpon probar 1          # verifica la conexión y toma modelo y firmware
gpon descubrir 1       # inventaría: puertos, ONU, perfiles, VLAN
gpon onus 1 --pon 2    # inventario de un puerto PON
gpon listar-olts
```

La contraseña no se pasa por parámetro: `alta-olt` la pide por teclado, o la toma de
`GPON_OLT_PASSWORD` si está definida. Un parámetro queda en el historial del shell y en la
lista de procesos.

`--fabricante` acepta `vsol` (lectura por SNMP) y `simulado`. `zte` llega con la Fase 6.

### Apuntar a una VSOL real

```bash
gpon alta-olt --nombre "OLT Centro" --host 192.168.1.10 --fabricante vsol --comunidad publica
gpon probar 1        # confirma que responde y toma modelo y firmware
gpon sondear 1       # valores crudos junto a su interpretación
gpon descubrir 1     # inventario completo
```

**Corré `sondear` antes que nada.** El driver deduce por orden de magnitud la escala con la
que la OLT publica potencias, temperatura y voltaje — es el único punto que no pudo
verificarse contra un equipo. `sondear` muestra el valor crudo y el interpretado, uno al
lado del otro, para compararlos con la web de la OLT en un minuto.

Requiere `snmpwalk`/`snmpget` (`sudo apt install snmp`) o `pip install 'gpon-module[equipos]'`.

### Antes de autorizar y configurar ONU: `capturar`

Autorizar una ONU, cambiar su perfil o su VLAN **es CLI**, no SNMP: en VSOL el número de
serie no viaja por SNMP y el aprovisionamiento tampoco. Y la sintaxis exacta de esos
comandos cambia entre versiones de firmware.

```bash
gpon capturar 1                       # Telnet, catálogo completo
gpon capturar 1 --protocolo ssh       # si la OLT tiene SSH (requiere paramiko)
gpon capturar 1 --comando-extra "show onu"   # sólo un comando puntual
```

`capturar` abre una sesión CLI, le pide al equipo su **ayuda en línea** (`?`, que enumera la
sintaxis real sin ejecutar nada) y prueba una lista de comandos de lectura, guardando todo
en un archivo de texto. Lo que el firmware rechaza también queda registrado: saber qué
comando *no* existe vale tanto como saber cuál sí.

**No envía ni un solo comando de escritura.** Hay un filtro que sólo deja pasar `show`,
`display`, `dir` y `get`, y se aplica igual al catálogo propio que a lo que se pida a mano.
Se puede correr contra un equipo en producción a cualquier hora.

Revisá el archivo antes de compartirlo: `show running-config` puede incluir contraseñas del
equipo y de PPPoE de los clientes.

| Variable | Por defecto | Para qué |
|---|---|---|
| `GPON_CLAVE_CIFRADO` | — | Cifra las credenciales de OLT. **Obligatoria** salvo que se pida lo contrario |
| `GPON_PERMITIR_CIFRADO_NULO` | `0` | Desarrollo sin cifrado. Hay que activarlo a propósito |
| `GPON_BASE_DATOS` | `sqlite:///gpon.db` | SQLite ahora; PostgreSQL desde la Fase 4 |
| `GPON_DRY_RUN` | `1` | **Modo simulación.** Ver más abajo |
| `GPON_PORCENTAJE_MINIMO_LECTURA` | `80` | Debajo de esto, una corrida se marca parcial |
| `GPON_RETENCION_FINA / HORARIA / DIARIA` | `7 / 90 / 730` | Días de retención por escalón |

Si falta la clave de cifrado, el módulo **no arranca**. Es deliberado: una base con la
contraseña de administrador de todas las OLT en claro es un problema serio, y no puede ser
el resultado de un descuido.

## Uso desde código

```python
from gpon_module import crear_contenedor
from gpon_module.core import CredencialesOLT, Fabricante

with crear_contenedor() as sistema:
    olt = sistema.servicio_olt.registrar(
        nombre="OLT Centro",
        host="192.168.1.10",
        fabricante=Fabricante.VSOL,
        credenciales=CredencialesOLT(usuario="admin", password="…"),
    )
    resultado = sistema.servicio_descubrimiento.descubrir(olt.id)
    print(resultado.onus_leidas, "ONU", "completo" if resultado.completo else "PARCIAL")
```

## Dos decisiones que conviene conocer antes de usarlo

**1. Todo sale simulado.** Cualquier operación de escritura arma los comandos y **no los
envía**. Para que lleguen al equipo hay que pedirlo explícitamente:

```python
sistema.servicio_onu.eliminar(olt.id, ref)                  # simulado: no toca nada
sistema.servicio_onu.eliminar(olt.id, ref, dry_run=False)   # ejecuta de verdad
```

Ambas quedan auditadas, con los comandos y la respuesta del equipo. Es la única defensa
real contra dejar clientes sin servicio por un comando mal formado.

**2. Una lectura incompleta nunca es una baja masiva.** Si un walk viene truncado o la
sesión se corta, se guarda lo leído, la corrida queda marcada como parcial y no se concluye
nada sobre lo que no se alcanzó a ver. Este error ya ocurrió en producción con Pucará; acá
está cubierto por tests explícitos.

## Estructura

```
gpon_module/
├── core/         contratos, entidades y reglas de dominio — no conoce fabricantes
├── drivers/      un subpaquete por fabricante + transporte (SNMP, Telnet, SSH)
│   ├── base.py       capacidades, modo simulación, resultados auditables
│   ├── transport/    SNMP (net-snmp o pysnmp) + disciplina de sesión CLI
│   ├── vsol/         V1600G1 / G1-B, sólo lectura, con OIDs verificados
│   └── mock/         OLT simulada completa, con fallas provocables
├── database/     esquema propio (SQLite y PostgreSQL) + repositorios
├── services/     lógica de negocio; es la fachada del módulo
├── api/          API interna: única puerta de entrada de la interfaz
├── web/          interfaz Bootstrap 5, servida sin CDN
├── tests/        232 tests, sin red ni disco ni reloj real
└── docs/         investigación, arquitectura, informes de fase
```

La regla que ordena todo: **un comando CLI o un OID sólo puede existir dentro de
`drivers/<fabricante>/`**. Si aparece un comando en `core/`, `services/` o `api/`, el
diseño se rompió.

## Desarrollo

```bash
python -m pytest gpon_module/tests -q     # 232 tests, ~5 s
ruff check gpon_module
```

Los tests no tocan la red, el disco ni el reloj del sistema: base en memoria, reloj fijo y
driver simulado. Fallan siempre que deben fallar, y nunca por casualidad.

## Documentación

| Documento | Contenido |
|---|---|
| [`docs/00-investigacion.md`](docs/00-investigacion.md) | Qué hace AdminOLT, qué expone realmente cada equipo, evidencia verificada contra las OLT de ERLAN |
| [`docs/01-arquitectura.md`](docs/01-arquitectura.md) | Diseño, decisiones y plan de fases |
| [`docs/02-fase1-informe.md`](docs/02-fase1-informe.md) | Qué se implementó, qué falta, riesgos y compatibilidad |
| [`docs/03-modelo-de-datos.md`](docs/03-modelo-de-datos.md) | Tablas, relaciones y retención del histórico |
| [`docs/04-guia-nuevo-fabricante.md`](docs/04-guia-nuevo-fabricante.md) | Cómo agregar un fabricante nuevo |
| [`docs/05-fases-2-3-informe.md`](docs/05-fases-2-3-informe.md) | Driver VSOL, API y web: qué se implementó y qué falta |
