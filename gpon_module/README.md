# Módulo GPON

Administración de OLT y ONU multifabricante, con equivalencia funcional a AdminOLT.

Proyecto **independiente**: no importa nada de Pucará ni comparte su base de datos. La
integración futura será por servicios, no por tablas compartidas.

**Estado: Fase 1 completa.** El módulo corre entero contra una OLT simulada, sin necesidad
de ningún equipo real. Los drivers VSOL y ZTE llegan en las fases 2 y 6.

---

## Probarlo en un minuto

No requiere base de datos, ni credenciales, ni una OLT:

```bash
python -m gpon_module.cli demo
```

Da de alta una OLT simulada, la descubre entera (473 ONU, 8 puertos PON), clasifica las
potencias ópticas, y muestra los comandos exactos que *se habrían enviado* al autorizar una
ONU — sin enviar ninguno.

## Instalación

```bash
pip install -e ".[desarrollo]"        # núcleo + herramientas de prueba
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
│   ├── transport/    paginación, exclusión por OLT, reintentos, aborto de secuencia
│   └── mock/         OLT simulada completa, con fallas provocables
├── database/     esquema propio (SQLite y PostgreSQL) + repositorios
├── services/     lógica de negocio; es la fachada del módulo
├── api/          Fase 3
├── web/          Fase 3 (Bootstrap 5)
├── tests/        143 tests, sin red ni disco ni reloj real
└── docs/         investigación, arquitectura, informes de fase
```

La regla que ordena todo: **un comando CLI o un OID sólo puede existir dentro de
`drivers/<fabricante>/`**. Si aparece un comando en `core/`, `services/` o `api/`, el
diseño se rompió.

## Desarrollo

```bash
python -m pytest gpon_module/tests -q     # 143 tests, ~4 s
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
