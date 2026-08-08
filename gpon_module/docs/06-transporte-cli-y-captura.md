# Transporte CLI y captura — informe técnico

*Etapa previa a la Fase 5 (escritura). Estado: implementada y probada.*

## Por qué esta etapa existe

La pregunta que la motivó fue: **cómo admitir ONU y configurarlas, y ver toda la
información que falta**.

Hay un límite duro que conviene decir de entrada: **todo eso es CLI**. No es una
preferencia de diseño, es lo que el equipo permite. Verificado contra la V1600G1 de
ERLAN (283 ONU, firmware V2.3.1R), por SNMP:

| Lo que falta | Por qué no se puede por SNMP |
|---|---|
| Número de serie de la ONU | La rama devuelve cero resultados en el equipo real |
| ONU sin autorizar | No hay tabla que las publique |
| Autorizar / borrar / reiniciar ONU | El agente SNMP de VSOL es de sólo lectura |
| Perfiles, DBA, VLAN, service-port | No están en la MIB del fabricante |

Sin serial no se puede autorizar nada, y el serial sólo aparece en la CLI. Así que el
camino a la Fase 5 pasa obligatoriamente por acá.

## Lo que se construyó

### 1. Conversación con la CLI, separada del protocolo

`drivers/transport/interactivo.py` — `TransporteInteractivo`

Hablar con la CLI de una OLT no es "mandar un comando y leer la respuesta": es leer
hasta reconocer un prompt, contestar la paginación, separar el eco del comando de la
salida real y darse cuenta de cuándo el equipo dejó de contestar. Eso es idéntico en
Telnet y en SSH. Vive una sola vez; las subclases sólo aportan `_recibir` y
`_transmitir`.

Incluye:

* login en dos pasos y `enable`, con detección de credenciales rechazadas —volver a
  pedir usuario es cómo estos equipos dicen "no";
* respuesta automática a `--More--` (riesgo R3);
* **sesión exclusiva por OLT** (riesgo R4), tomada al abrir y liberada al cerrar,
  incluso si el login falla;
* aprendizaje del prompt real de la sesión, que permite recortarlo con exactitud en
  vez de adivinar dónde termina la salida.

### 2. Telnet propio

`drivers/transport/telnet.py`

`telnetlib` fue **eliminado en Python 3.13**, así que el protocolo lo implementa el
módulo: negociación IAC —a toda opción se responde que no— y poco más. Son unas 60
líneas y evitan una dependencia externa para el canal que estos equipos traen
habilitado de fábrica.

### 3. SSH

`drivers/transport/ssh.py`

Sobre paramiko, con **canal interactivo** (`invoke_shell`), no `exec_command`: la CLI de
estos equipos es modal, y cada `exec_command` abriría una sesión nueva que pierde el
modo. paramiko es dependencia opcional; si falta, el mensaje dice cómo instalarla en vez
de reventar con un `ImportError` sin contexto.

Conviene usar SSH donde el equipo lo permita: Telnet manda las credenciales en claro por
la red de gestión.

### 4. Captura: preguntarle al equipo en vez de adivinar

`services/captura.py` + `gpon capturar <id>`

Esta es la pieza que desbloquea la Fase 5, y la razón por la que la escritura todavía no
está escrita.

Los manuales de VSOL que circulan son de otras versiones de firmware. Un comando de
lectura mal escrito devuelve un error y no pasa nada. **Un comando de escritura mal
escrito deja clientes sin servicio.** Por eso la lectura se descubre y la escritura se
implementa recién con la salida real en la mano.

`gpon capturar` hace tres cosas:

1. Pide la **ayuda en línea** (`?`). En una CLI estilo Cisco, `?` enumera las opciones
   válidas sin ejecutar nada —no se manda Enter, así que no hay comando que aplicar—.
   Es la forma más segura que existe de averiguar la sintaxis real de un firmware, y es
   lo más valioso de toda la captura.
2. Prueba un catálogo de comandos de lectura (`drivers/vsol/comandos.py`) y guarda la
   salida cruda de cada uno.
3. Registra también los rechazos. Que el firmware no conozca un comando es información,
   no una falla: dice qué sintaxis descartar.

#### La garantía de seguridad

La captura **no puede** enviar un comando de escritura:

* lista blanca de verbos: `show`, `display`, `dir`, `get`;
* se rechaza cualquier comando con `|`, `>`, `;`, `&` o salto de línea —una redirección
  o dos comandos en uno podrían escribir;
* el filtro se aplica **al catálogo propio con el mismo rigor** que a lo que venga de
  afuera: un error de tipeo en el catálogo no puede convertirse en un comando de
  configuración;
* la validación corre **antes** de abrir la sesión, no después.

Está sostenido por tests, incluido uno que recorre el catálogo entero. Se puede correr
contra un equipo en producción a cualquier hora.

### 5. Diagnóstico cuando la CLI no abre

`gpon probar-cli <id>` (y el mismo diagnóstico, automático, cuando `capturar` falla al
conectarse).

El primer caso real contra la OLT de ERLAN fue justamente ése: el puerto 23 no contestó.
Un error de socket no alcanza para saber qué pasó, y las dos causas posibles se arreglan
en lugares distintos:

* **rechazado** (RST inmediato): se llega al equipo, el servicio está apagado. Se arregla
  en la OLT.
* **sin respuesta** (timeout): un firewall o la lista de gestión del equipo descarta el
  paquete en silencio. Se arregla en el camino.

El comando sondea 23, 22, 443 y 80, no manda credenciales —abre y cierra una conexión
TCP— y cierra diciendo qué hacer con lo que encontró. Si la web del equipo responde pero
la CLI no, lo dice: llegar se llega, el problema es el servicio.

## Cómo se probó

* **372 tests**, todos en verde. 128 nuevos entre transporte, captura, diagnóstico,
  exploración de modos y parsers de la VSOL.
* El Telnet se prueba contra un socket falso con guion: negociación IAC, login en dos
  pasos, contraseña rechazada, paginación, eco del comando, corte de sesión.
* De punta a punta contra una **OLT VSOL simulada sobre un socket TCP real**, con
  `gpon capturar` completo: login, ayuda en línea, 30 comandos, archivo generado.

Dos defectos reales aparecieron en esa prueba de punta a punta y quedaron corregidos:

1. **La ayuda perdía su última línea.** Varios equipos redibujan el prompt pegado al
   último renglón, sin salto de línea previo. Descartar esa línea entera se comía la
   última opción, que suele ser justo la que interesa. Se corrigió recortando el prompt
   exacto aprendido en el login.
2. **Los tests dependían del recolector de basura** para liberar la sesión exclusiva.
   Funcionaba por casualidad. Ahora se cierra explícitamente en el *fixture*.

### Lo que enseñó la primera sesión contra la OLT de ERLAN

Las trazas de las sesiones fallidas —`--traza`— resolvieron en dos lecturas cuatro cosas
que ninguna cantidad de suposiciones habría resuelto:

**1. El fin de línea.** El equipo anuncia en su banner que entra en *character mode*:
procesa cada byte según llega. Un `\r\n` son **dos Enter**. En el login eso mandaba el
usuario y, acto seguido, una contraseña vacía; el equipo contestaba *"Bad UserName or Bad
Password"* con credenciales perfectamente válidas. Ahora se manda **CR solo**, que es lo
que manda una terminal real.

**2. El rechazo tardaba 20 s en detectarse.** Tras el fallo, el equipo vuelve a mostrar
`Login:`, que no era ninguno de los patrones esperados, así que la sesión esperaba hasta
el timeout — y reintentaba tres veces, gastando tres intentos de login contra un equipo
que puede bloquear la cuenta. Ahora se corta en el acto, al leer el texto del rechazo.

**3. La OLT empuja avisos a la sesión.** Sin que nadie los pida::

    2026/08/06 12:15:28   ONU Offline   PON 0/7 ONU 22 sn GPON00B8FF21

Llegan en cualquier momento, también en medio de la salida de un comando. Se filtran de la
salida antes de que la vea un parser: una línea así en medio de una tabla sería una fila
inventada.

**4. El prompt lleva un acento.** Con el fin de línea arreglado, el login pasó y el equipo
contestó::

    Zona_Bº_Belgrano>

Esa `º` viaja como `\xc2\xba`, y `\w` en un patrón de **bytes** es sólo ASCII: el módulo
no reconocía un prompt que tenía delante, se iba a timeout y reintentaba el login tres
veces. Ahora el nombre del equipo se acepta con cualquier byte imprimible.

Ese mismo prompt terminó en `>` y no en `#`: la sesión queda en modo **no privilegiado**.
El `enable` se intenta igual, pero si el firmware no lo conoce o pide una contraseña que no
tenemos, se avisa y se sigue — perder la lectura entera por no haber podido elevar
privilegios sería el peor de los desenlaces.

Las cuatro correcciones están fijadas por tests contra una réplica del equipo, reconstruida
a partir de esas trazas: mismo banner, mismo *character mode*, mismo prompt con acento,
mismos avisos.

### La exploración de modos: dónde estaba todo

`show ?` en el modo EXEC no tiene un solo comando de GPON — es la CLI del switch. Entrar a
`configure terminal` → `interface gpon 0/1` y pedir la ayuda ahí resolvió el resto:

| Encontrado | Para qué |
|---|---|
| `show onu auto-find` | ONU detectadas y **sin autorizar** — la pantalla "AutoFind" de la web |
| `show onu info` | Inventario con modelo, perfil y **número de serie** |
| `show onu state` | `working` / `OffLine` / `DyingGasp` / `LOS` |
| `onu confirm` | Autorizar una ONU auto-detectada |
| `onu add`, `onu delete`, `onu reboot` | Alta, baja y reinicio |

Dos hallazgos que cambian cosas ya escritas:

**El `Phase State` es el motivo de caída que SNMP no da.** `DyingGasp` es un corte de luz
en el domicilio —la ONU alcanzó a avisar que se quedaba sin energía— y `LOS` es pérdida de
señal óptica, o sea fibra. Son dos cuadrillas distintas, y en el PON 1 de ERLAN aparecen
las dos. Es exactamente la distinción que el panel mostraba como "no disponible".

**Las tablas se alinean con secuencias ANSI, no con espacios.** Una fila llega así::

    GPON0/1:1\x1b[25CGPON002E64F8\x1b[50Cunknow

El número es la columna absoluta donde arranca el campo, y coincide exacto con la posición
del encabezado. Sin traducirlo no hay parser que pueda separar las columnas. El transporte
ahora lo convierte a espacios antes de que nadie vea el texto.

## Qué sigue, y qué hace falta para poder hacerlo

El próximo paso es la **Fase 5: escritura** — autorizar, borrar, reiniciar y configurar
ONU. Para escribirla hace falta una sola cosa:

```bash
gpon capturar 1 --salida captura-belgrano.txt
```

y el archivo resultante. Con eso a la vista quedan determinados:

* la sintaxis exacta de autorización en ese firmware;
* el formato de la tabla de ONU sin autorizar, para poder listarlas en la web;
* el formato del inventario con serial, que es lo que hoy falta en la interfaz;
* los perfiles, DBA y VLAN disponibles, para ofrecerlos en el alta.

Antes de mandarlo conviene revisarlo: `show running-config` puede incluir contraseñas
del equipo y de PPPoE de los clientes.

Sobre esa salida se escriben los parsers y las secuencias de aprovisionamiento, con
`dry_run=True` por defecto —para que un comando llegue de verdad al equipo hay que
pedirlo explícitamente— y auditoría completa de cada operación.

## Riesgos

| # | Riesgo | Estado |
|---|---|---|
| R3 | Paginación cuelga la sesión | Cubierto: se contesta sola |
| R4 | Dos operaciones simultáneas entrelazan la configuración | Cubierto: sesión exclusiva por OLT |
| R2 | Comando rechazado tomado por datos | Cubierto: se detecta y aborta la secuencia |
| R12 | El prompt de un firmware distinto no coincide con el patrón | Abierto. La captura lo detectaría de inmediato: no habría login |
| R13 | La CLI bloquea la cuenta tras varios intentos fallidos | Mitigado: el protocolo se elige explícitamente, nunca se prueba uno y se cae al otro |
