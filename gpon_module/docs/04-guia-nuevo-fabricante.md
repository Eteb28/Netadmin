# Cómo agregar un fabricante

Esta guía es también la prueba de que la arquitectura sirve. **Agregar un fabricante no
debe requerir ningún cambio en `core/`, `services/`, `database/`, `api/` ni `web/`.** Si
hace falta tocar alguno de esos paquetes, el problema no es el driver nuevo: es que la
abstracción se quedó corta, y ahí hay que corregirla.

## Antes de escribir código: capturar salidas reales

El paso que no se puede saltear. Un parser escrito contra la documentación del fabricante
funciona hasta que se enfrenta a un equipo de verdad.

Con acceso a un equipo, capturar y guardar en `tests/fixtures/<fabricante>/`:

```
show version               → identidad, modelo, firmware
show running-config        → configuración completa
<listado de ONU>           → inventario, con y sin ONU caídas
<listado de perfiles>      → DBA, línea, servicio
<potencias ópticas>        → una ONU en línea y una caída
<ONU sin autorizar>        → con al menos una pendiente
<un comando inválido>      → para conocer el texto exacto del rechazo
```

Ese último es tan importante como los demás: es lo que le enseña al transporte a distinguir
un error de un dato.

## 1. Estructura

```
drivers/<fabricante>/
├── __init__.py
├── driver.py      implementa OLTDriver
├── commands.py    plantillas de comandos CLI, aisladas
├── oids.py        OIDs SNMP
└── parsers.py     salida cruda → modelos del dominio
```

Separar `commands.py` y `parsers.py` del driver no es ceremonia: cuando cambie una versión
de firmware, el cambio queda en un archivo de plantillas y no desparramado en la lógica.

## 2. Declarar las capacidades **verificadas**

Es la parte que más influye en el resultado, y la que más tienta a hacer mal.

```python
CAPACIDADES = frozenset({
    Capacidad.DESCUBRIR_ONUS,
    Capacidad.POTENCIA_OPTICA,
    ...
})
```

Se declara lo que el equipo **hace**, comprobado contra el equipo — no lo que promete el
folleto. Declarar de más es peor que declarar de menos: la interfaz muestra un botón que
falla en producción, delante de un cliente esperando su servicio.

Referencia concreta: en VSOL, `TRAFICO_POR_ONU`, `CPU`, `MEMORIA`, `TEMPERATURA_CHASIS` y
`SERIAL_POR_SNMP` van **fuera**. Está verificado contra los equipos reales, no supuesto.

## 3. Escribir el driver

```python
from ...core.enums import Capacidad, Fabricante
from ...core.registry import registrar_driver
from ..base import DriverBase


@registrar_driver(
    Fabricante.ZTE,
    nombre="ZTE C320/C300",
    modelos=("C320", "C300"),
    protocolos=("snmp", "telnet", "ssh"),
)
class DriverZTE(DriverBase):
    FABRICANTE = Fabricante.ZTE
    CAPACIDADES = CAPACIDADES
    MODELOS = ("C320", "C300")

    def discover_onus(self) -> list[ONU]:
        self._exigir(Capacidad.DESCUBRIR_ONUS)
        salida = self._cli.ejecutar(comandos.LISTAR_ONU)
        return parsers.parsear_onus(salida, olt_id=self.olt_id)

    def reboot_onu(self, ref: RefONU) -> ResultadoOperacion:
        self._exigir(Capacidad.REINICIAR_ONU)
        return self._operacion(
            TipoOperacion.REINICIAR_ONU,
            comandos.reiniciar(ref),
            self._ejecutar_cli,
            ref=ref,
        )
```

Heredando de `DriverBase` se obtiene sin escribir nada: el modo simulación respetado en
toda escritura, `CapacidadNoSoportada` antes de tocar el equipo, y un `ResultadoOperacion`
completo con comandos, salida y duración.

## 4. Cinco reglas que no se negocian

**Un dato ausente es `None`, nunca `0`.** Un cero se grafica, se promedia y se convierte en
una mentira que se propaga hasta una decisión operativa.

**Un timeout no es una lista vacía.** Devolver `[]` ante una falla de comunicación es
exactamente lo que produce una baja masiva falsa. Si la lectura salió truncada, hay que
levantar `ErrorLecturaParcial` con la cuenta de lo obtenido.

**Ningún comando fuera del driver.** Si un string de comando aparece en `core/`,
`services/` o `api/`, el diseño se rompió.

**Toda escritura devuelve `ResultadoOperacion`, nunca `bool`.** Una operación de
aprovisionamiento tiene que poder explicarse después.

**Las contraseñas se enmascaran en los comandos que se devuelven.** El cambio se aplica
igual; lo que no queda es la clave en la tabla de auditoría.

## 5. Traducir, no calcar

La tentación es copiar la semántica del fabricante hacia arriba. No se hace: el núcleo
tiene su propio vocabulario y cada driver traduce.

```python
_ESTADOS = {
    "working": EstadoONU.EN_LINEA,
    "los": EstadoONU.FUERA_DE_LINEA,
    "dying-gasp": EstadoONU.FUERA_DE_LINEA,
}

_MOTIVOS = {
    "dying-gasp": MotivoCaida.APAGADO,        # corte de luz en el domicilio
    "los": MotivoCaida.PERDIDA_SENAL,         # problema de fibra: hay que ir
}
```

Un valor desconocido se mapea a `DESCONOCIDO` y se registra en el log. Nunca se adivina.

El mismo criterio vale para las diferencias de fondo. `authorize_onu()` recibe una
*intención*: en ZTE se resuelve como un alta explícita por serial, en VSOL como confirmar y
configurar la ONU que el `auto-learn` ya incorporó. Dos implementaciones, una sola llamada
desde arriba.

## 6. Probar

La batería de `tests/unit/test_driver_simulado.py` está escrita para valer contra
**cualquier** driver. Al agregar uno nuevo:

1. Verificar que cumple `OLTDriver` y expone los 21 métodos del contrato.
2. Probar los parsers contra las salidas reales capturadas en el paso 0.
3. Probar que en modo simulación **no se envía ni un comando**.
4. Probar la lectura truncada y el timeout.
5. Probar que las capacidades declaradas coinciden con lo que el equipo hace.

## 7. Registrarlo

Una línea en `drivers/__init__.py`:

```python
from . import mock, vsol, zte  # noqa: F401
```

Con eso, `Fabricante.ZTE` aparece en el alta de OLT, la fábrica sabe construirlo y la
interfaz web muestra sólo lo que ese equipo puede hacer. No hay ningún otro lugar donde
tocar.

## Lista de verificación

- [ ] Salidas reales capturadas en `tests/fixtures/<fabricante>/`
- [ ] Capacidades declaradas **verificadas contra el equipo**, no supuestas
- [ ] Comandos y OIDs sólo dentro de `drivers/<fabricante>/`
- [ ] Datos ausentes como `None`, nunca `0`
- [ ] `ErrorLecturaParcial` ante lecturas truncadas
- [ ] Contraseñas enmascaradas en los comandos devueltos
- [ ] Toda escritura devuelve `ResultadoOperacion`
- [ ] Secuencias multicomando con su rollback definido
- [ ] Tests de parseo contra salidas reales
- [ ] `core/`, `services/`, `database/`, `api/` y `web/` **sin un solo cambio**
