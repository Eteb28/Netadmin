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

* **410 tests**, todos en verde. 165 nuevos entre transporte, captura, diagnóstico,
  exploración de modos, parsers de la VSOL y el alta de ONU.
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

## Fase 5: el alta de una ONU

La secuencia no está inventada ni sacada de un manual: es **la que el propio equipo
escribe** en su `show running-config` para cada una de las 284 ONU ya autorizadas. Se leyó
de ahí, se comparó entre puertos y clientes, y quedó el molde.

```
gpon autorizar 1 --serie GPON002E64F8 --perfil V2802DAC \
     --subida 100M-Dom-UP --bajada 100M-Dom-DOW
```

Sin `--aplicar` **no sale un solo comando**: se muestra la secuencia exacta y nada más.

Antes de escribir, se verifica contra el equipo:

* que la ONU esté realmente esperando en auto-find, y en qué puerto. Si no está, el alta
  ocuparía un índice para una ONU que no llegó;
* qué índices están usados, para reusar el hueco más bajo. En el PON 1 de ERLAN el 29 está
  libre entre el 28 y el 30, y ahí es donde iría la próxima;
* que el serial tenga la forma esperada. Lo tipea un técnico y llega por mensaje: es el
  dato más frágil de todo el flujo.

Si el equipo rechaza un comando del medio, **se aborta ahí**. Seguir es lo que deja una ONU
a medio configurar. El resultado dice cuál falló y cuántos se alcanzaron a aplicar, porque
eso es lo que hay que ir a revisar.

Todo queda auditado con los comandos exactos y con si fue real o simulada.

### Tres errores que costaron una corrida cada uno

La primera versión mandaba `configure terminal` una vez por puerto mientras buscaba el
serial. Desde el segundo puerto ya se estaba en modo configuración, y el equipo lo rechaza.
Lo encontró la réplica, antes de llegar al equipo real.

La segunda salía a EXEC con `end` y volvía a entrar con `configure terminal`, para que la
secuencia se aplicara entera tal como se mostraba. **Contra la OLT real, ese segundo
`configure terminal` fue rechazado** —al parecer `end` devuelve a modo no privilegiado, y
ahí ya no se acepta—. La lección es la misma que la primera vez: la sesión no tiene por qué
salir y volver a entrar, porque las verificaciones ya la dejaron en el puerto correcto.
Ahora se aplica desde donde está, y la navegación que efectivamente se ejecutó cuenta como
aplicada, así lo que se informa sigue siendo lo que salió a la red.

La tercera no fue del código sino de un campo de texto libre. El alta llegó hasta el sexto
comando y ahí el equipo contestó `Error:`:

```
onu 29 gemport 1 traffic-limit upstream 100M-Dom-UP downstream 100M-Dom-DOWN
```

El plan en el equipo se llama `100M-Dom-DOW`, sin la N final. Los 26 planes de esa OLT no
siguen ninguna convención entre sí —`100M-Dom-DOW`, `100M-Pymes-Dowm`, `50M-PYMES-DOW`,
`5M-Dom-Dow`—, así que escribirlos de memoria es cuestión de tiempo. Y `traffic-limit` va
sexto: para cuando el equipo lo rechazó, la ONU ya estaba declarada, con su tcont y su
gemport, y sin servicio.

La corrección tiene tres partes, porque una sola no alcanzaba:

1. Los planes ahora **se guardan** (tabla `perfiles_trafico`), leídos del `show
   running-config` como el resto del inventario. El nombre viaja tal cual: normalizarlo o
   corregirlo sería peor que no tenerlo, porque parecería válido.
2. El alta **valida contra esa lista antes de abrir la sesión**, y cuando no coincide
   ofrece el parecido —que es casi siempre la respuesta—:
   `El plan de tráfico '100M-Dom-DOWN' no existe en esta OLT. ¿Quisiste decir
   '100M-Dom-DOW'?`. Si la base todavía no tiene planes cargados no se bloquea nada: se
   avisa por log y decide el equipo. Un inventario pendiente no puede convertirse en una
   interrupción del servicio.
3. La web ofrece la lista en un `datalist` y frena antes de pedir la previsualización.

Lo que **no** se valida es el perfil de ONU ni el DBA: salen de listas que el módulo
todavía no lee completas, y rechazar un nombre válido por no tenerlo en la base sería peor
que no validarlo.

## Dar de baja: `gpon baja`

Un alta que se aborta a mitad deja el índice ocupado por una ONU sin servicio, y hay que
sacarla antes de reintentar. `secuencia_baja` ya existía; ahora hay por dónde usarla:

```
gpon baja 1 --pon 1 --indice 29 --serie GPON002E64F8
```

Es la operación más destructiva del módulo —deja al cliente sin servicio en el momento en
que se ejecuta— así que también es simulada por defecto. Antes de borrar lee el puerto y
**muestra qué ONU hay en ese índice**: el índice solo no distingue un alta a medias de la
ONU del vecino. Si se pasa `--serie` y no coincide con lo que reporta el equipo, no sale
ningún comando.

Un índice **vacío** sí se puede borrar: un alta que quedó a medias puede no haber llegado
a aparecer en el inventario, y ése es justamente el caso que hay que poder limpiar. Lo que
frena la baja es encontrar *otra* ONU, no no encontrar ninguna.

## El alta que se completa sola

El operador copiaba a mano cuatro cosas que ya estaban escritas en Pucará. Cada
copia era una oportunidad de equivocarse, y una ya se cobró. Ahora el número de cliente
trae todo:

| Campo del alta | De dónde sale |
|---|---|
| Perfil de ONU | `clientes.equipo_modelo` → `V2802DAC` |
| Planes de tráfico | `clientes.plan` → megabits → perfil de la OLT |
| Descripción | `nro_cliente` + `clientes.nap` → `034716_CDO8_NAP3` |
| PPPoE | `clientes.pppoe_usuario` / `pppoe_clave` |
| VLAN | 1001 por defecto, editable |

**La base comercial se abre en modo `ro`.** No es una promesa del código: es SQLite el
que rechaza la escritura. El alta de una ONU no puede convertirse en un camino lateral
para editar la base de clientes. Y el módulo sigue sin importar una sola línea de código
de Pucará —hay un test que lo vigila—: lee un archivo por una ruta de configuración, nada
más. Sin `GPON_BASE_CLIENTES`, todo se carga a mano igual que antes.

### La traducción del plan

`INTERNET 10 MB` y `10M-Dom-Dow` son dos vocabularios para lo mismo, y nadie los había
conectado salvo la cabeza del operador. La traducción se hace por **megabits, segmento y
sentido**, y el resultado se elige de los perfiles que la OLT declaró — nunca se construye
un nombre. Por eso resuelve sola que el de 10 termina en `Dow`, el de 100 en `DOW` y el de
empresa en `Dowm`: la inconsistencia la desempata el equipo.

Cuando no hay correspondencia, se dice que no la hay. Proponer el más parecido sería el
bug original con otra cara.

## Fase 7: la configuración del CPE (pendiente de sintaxis)

Los requisitos están definidos; falta un dato del equipo para poder escribirlos.

**WAN**, con los datos del cliente:

```
Connect Type: route        IP Version: ipv4       Service Mode: internet
Connect Mode: PPPOE        MTU: 1492              serverName: FTTH1
UserName: <nro_cliente>    pwd: <pppoe_clave>     Nat: enable
VLAN Mode: Tag             VLAN ID: <la misma que la del service-port>
Bind: lan1 lan2 ssid1..ssid8
```

La VLAN de la WAN **no es un campo aparte**: es la misma que se configura en la VLAN List
y en el service-port. Tenerla dos veces sería tener dos formas de que no coincidan.

**WiFi**, con `Country: FCC` y dos redes configurables en nombre y contraseña:

| Red | Autenticación | Cifrado |
|---|---|---|
| WIFI0 / SSID1 (2.4 GHz) | `WPA2PSK` | `AES` |
| WIFI1 / SSID5 (5 GHz) | `WPAPSK/WPA2PSK` | `AES` |

**Dónde vive.** La exploración del 10/08 lo ubicó. En modo configuración, `profile ?`
contesta:

```
profile
  onu      Specify onu profile interface.
  dba      Specify dba profile interface.
  traffic  Specify traffic profile interface.
  line     Specify line profile interface.
  srv      Specify srv profile interface.
  pri      Specify private profile interface.     ← acá
  ...
```

`pri` es *private profile*, y es lo que en el `show running-config` aparece como
`onu N pri ...`. Es un dato de arquitectura, no un detalle: la configuración del CPE en
este firmware **no son comandos sueltos por ONU**, es un perfil. La confirmación indirecta
está en la misma captura: `onu add ?` enumera todo el vocabulario del alta —`desc`,
`tcont`, `gemport`, `service`, `service-port`, `portvlan`, `profile`— y ahí no hay ni WAN
ni WiFi.

**Confirmado el 10/08.** No está en `profile pri` —ése sólo acepta `id` y `name`— sino
en un subcomando **por ONU**. `onu 1 ?` lo mostró:

```
onu 1
  pri               Specify private omci information.     ← acá
  ...
```

Y `onu 1 pri ?` contestó 34 opciones. Las que importan:

| Rama | Para qué |
|---|---|
| `wan_conn` | la conexión WAN: es donde va el PPPoE |
| `wan_adv` | parámetros avanzados de esa WAN |
| `wifi_ssid` | nombre y clave de cada SSID |
| `wifi_switch` | prender y apagar cada radio |
| `save_config` | **guardar en el CPE** — sin esto la configuración se pierde al reiniciar |

`save_config` es el hallazgo que no se buscaba: aplicar la WAN y el WiFi sin guardar dejaría
al cliente andando hasta el primer corte de luz. Va a ser el último comando de la secuencia.

**Lo que falta.** Los argumentos de cada rama. Y ahí apareció un problema de método: pedirlos
requería otra corrida, con el equipo del otro lado y una persona esperando — una por nivel
del árbol.

### La exploración recorre el árbol

`explorar-config` recorre las ramas por su cuenta: pide la ayuda, lee las palabras que
devolvió y vuelve a preguntar por cada una, recursivamente. Qué ramas se profundizan es una
lista explícita y no "todo lo que se pueda": el árbol completo son cientos de preguntas y la
mayoría —VoIP, CATV, tr069— no hacen falta para esto.

Bajar no cambia lo que el servicio *puede* hacer —el `?` sigue sin ejecutar nada y la lista
blanca sigue en pie—: cambia cuántas preguntas hace en el mismo viaje.

**Los rangos numéricos también son camino.** `wifi_ssid <1-8>` no es una rama sino un hueco,
pero justo detrás están los parámetros de cada SSID. Se llena con el extremo bajo, que
existe siempre — y sólo cuando la ayuda no ofrece ninguna palabra: si ofrece las dos cosas,
las palabras son el camino y el número llevaría a preguntar de más. Los otros marcadores
(`<cr>`, `<onu_list>`, `<A.B.C.D>`) se descartan.

**Enumerar nodos de un árbol que no se conoce fue el error.** La lista de prefijos
exactos se quedó corta dos veces: primero no llegaba a `wan_conn add`, después no llegaba a
`wan_conn add route` ni a `wifi_ssid 1 name`. Lo que sí se conoce de antemano es **por dónde
hay que entrar**, así que se declaran subárboles —`wan_conn`, `wan_adv`, `wifi_ssid`,
`wifi_switch`, `username`— y se recorren enteros.

**Y "entero" tampoco alcanzaba.** `wan_adv index 1 bind` acepta una **lista repetida** de
interfaces: `bind lan1 ?` ofrece `lan2 … ssid10`, `bind lan1 lan2 ?` ofrece el resto, y así.
Eso no es un árbol, es una combinatoria. El recorrido en profundidad se hundió ahí y gastó
las 150 preguntas del presupuesto **sin llegar nunca a `wan_conn` ni a `wifi_ssid`**, que
era justo lo que se estaba buscando. Otra corrida perdida.

Dos cambios, y los dos sobre el mismo principio:

* **Se recorre a lo ancho, no en profundidad.** El orden en que se piden las cosas es el
  orden en que se pierden si algo se corta, y lo poco profundo es lo que casi siempre
  importa. En profundidad, la primera rama que se abre se lleva todo.
* **Tope de tres niveles** bajo la raíz de cada subárbol. Alcanza para `wan_conn add route`
  y `wifi_ssid 1 name`, y corta la combinatoria en el primer escalón: a `bind` se le
  pregunta una vez —devuelve la lista completa de interfaces, que es lo que sirve— y no se
  sigue por cada combinación.

Contra el árbol real esto pasa de 159 preguntas que no servían a 35 que traen todo.

**Y los huecos de texto también son camino.** `wifi_ssid 1 name ?` contesta sólo
`<string>`, pero el modo de autenticación, el cifrado y la clave están **después** del
nombre. Sin rellenar ese hueco el recorrido se corta justo antes de lo único que faltaba,
así que se rellena con un valor de prueba —el `?` no ejecuta nada, es texto que después se
borra con Ctrl-U—. `<cr>` no se rellena, porque ahí el comando termina de verdad, y
`<A.B.C.D>` tampoco: una IP inventada no lleva a ningún lado.

La profundidad pasó a declararse **por subárbol**, porque las formas son distintas:
`wan_conn` se agota en tres niveles y esconde la combinatoria del `bind`, mientras que el
WiFi es una cadena larga de pares clave-valor que hay que recorrer entera.

## Fase 7: dónde está cada cosa del CPE

Después de cuatro exploraciones, el mapa completo:

| Qué | Dónde |
|---|---|
| WAN con PPPoE | `onu <id> pri wan_conn add route [qos enable]` + `... index <n> route <modo> ...` + `commit` |
| Modo de la WAN | `internet`, `voip`, `tr069`, `multicast` y las combinaciones |
| Interfaces ligadas | `bind_lan` / `bind_ssid`, **como mascara de bits** |
| Nombre del SSID | `onu <id> pri wifi_ssid <1-8> name <texto>` |
| Radio y **pais** | `onu <id> pri wifi_switch <1-2> enable <pais> [canal]` |
| Guardar en el CPE | `onu <id> pri save_config` |

El `Country: FCC` no estaba donde se lo buscó —no es del SSID sino de la radio— y aparece
como una de quince opciones de `wifi_switch <n> enable`, seguida del canal (`auto`,
`chl_36`, ...) y del estándar (`80211acanacax` y compañía). `wifi_switch 1` es 2.4 GHz y
`wifi_switch 2` es 5 GHz, que se corresponden con SSID1 y SSID5.

### La clave del WiFi no existe en esta CLI

Hay que decirlo de frente porque era un requisito. Se recorrió el árbol entero de
`onu <id> pri` —37 ramas hasta las hojas, y después una búsqueda de texto sobre la captura
completa— y **no hay `wpa`, ni `psk`, ni `encrypt`, ni `key`, ni `password`** en ninguna
parte del subárbol del CPE. La cadena del SSID termina acá:

```
onu <id> pri wifi_ssid <1-8> name <texto> hide <enable|disable>
```

Nombre y visibilidad. Nada más. De la radio se puede tocar el encendido, el país, el canal
y el estándar; del SSID, cómo se llama y si se anuncia.

Eso deja el requisito de ERLAN —SSID1 en WPA2PSK+AES y SSID5 en WPAPSK/WPA2PSK+AES, ambas
con contraseña configurable— **fuera del alcance de esta vía**. Fingir lo contrario sería
peor que la limitación: quedaría un formulario con un campo de contraseña que no hace nada,
y alguien lo descubriría con un cliente sin WiFi del otro lado.

Las alternativas reales son otras —OMCI directo (`onu omci` existe en modo configuración),
TR-069 (`tr069_mng` está en el CPE), o la web del propio CPE— y cuál corresponde depende de
cómo se configure hoy a mano. Es una pregunta para ERLAN, no algo que se resuelva leyendo
más ayuda.

### Lo que sí se puede escribir, y está escrito

La WAN sale **verbatim del equipo**, así que el constructor tiene un test que compara su
salida contra la línea que imprime el firmware para la ONU 1. Si esa comparación se rompe,
el comando dejó de ser el que el equipo acepta — no es un test contra una expectativa
escrita a mano.

```
onu <id> pri wan_conn add route qos enable
onu <id> pri wan_conn index <n> route internet bind_lan 3 bind_ssid 255 qos enable
    nat enable mtu 1492 pppoe proxy disable user <cliente> pwd <clave> server FTTH mode auto
onu <id> pri wan_conn commit
onu <id> pri wifi_switch 1 enable fcc auto
onu <id> pri wifi_switch 2 enable fcc auto
onu <id> pri wifi_ssid 1 name <red> hide disable
onu <id> pri wifi_ssid 5 name <red-5G> hide disable
onu <id> pri save_config
```

Son **tres pasos** para la WAN y el orden importa: crear, configurar y confirmar. El
`commit` no es decorativo — sin él el equipo se queda con la conexión a medio armar, que es
la misma clase de problema que ya dejó una ONU sin servicio.

Queda un punto por verificar: la VLAN. El eco del equipo no la incluye en la línea, pero
`wan_conn index <n> vlan enable` existe y el `show` reporta `wanVlanId: 1001`. No se emite
un comando de VLAN sin haberlo visto: es exactamente la clase de suposición que costó cara.

**Para lo puntual, `--ayuda-de`.** Cuando falta un pedazo concreto no tiene sentido pagar
el recorrido entero: `gpon explorar-config 1 --ayuda-de 'onu 1 pri wifi_ssid 1 name '`
pregunta eso y nada más. Preguntar por dos prefijos toma segundos; una exploración completa
toma minutos con alguien esperando.

### Un `show` que no empieza con `show`

`onu 1 pri wan_conn show` lee la WAN de una ONU ya configurada —los nombres reales de cada
parámetro, que es justo lo que hay que saber escribir—. Pero en esta CLI el verbo va al
final, así que el filtro de sólo lectura, que mira la primera palabra, lo rechazaba.

La excepción es un patrón exacto: `onu <n> pri <cosa> show`, sin nada después. Aflojar la
regla general a "contiene show" habría dejado pasar `onu 1 pri factory_reset` de un tipeo,
y ese comando le borra la configuración al CPE de un cliente.

Adivinar la sintaxis es exactamente lo que dejó la ONU 1:29 a medio configurar. Preguntar
sale barato; suponer salió caro.

## Dos cosas que enseñó la exploración del 10/08

### `show onu auto-find` contesta `Error:` cuando no hay nada esperando

No devuelve una tabla vacía: devuelve un `Error:` pelado. Y `Error:` está en la lista de
marcadores de rechazo, así que el listado de pendientes daba **siete puertos fallados**
todos los días sin altas — que son la mayoría de los días. Peor que un falso negativo: un
falso "no se pudo mirar" enseña a ignorar el aviso.

Ahora ese caso se lee como "puerto sin ONU esperando". La excepción es angosta a propósito
—sólo el `Error:` sin más texto—: un rechazo de sintaxis o un puerto inexistente siguen
siendo fallas. Y si la suposición fuera errónea el costo es acotado y se nota solo, porque
el operador está buscando un serial concreto que el técnico acaba de instalar.

### `show onu state` sí publica el motivo de caída

```
1/1/1:7     enable    disable    DyingGasp    1(GPON)
1/1/1:18    enable    disable    LOS          1(GPON)
1/1/1:19    enable    disable    OffLine      1(GPON)
```

Eso cierra un hueco que estaba abierto desde la Fase 2: SNMP en estos equipos dice que la
ONU no está, pero no por qué. **DyingGasp es un corte de luz en el domicilio y LOS es
fibra cortada**; confundirlas cuesta un viaje de cuadrilla. `OffLine` se informa como
desconocido en vez de elegir una de las dos.

```
gpon estados 1
```

Es de sólo lectura y actualiza el inventario, así que el panel puede separar "cortes de
luz" de "fibra cortada" —las tarjetas ya estaban, les faltaba quién las llenara—. Ojo con
el formato del índice: acá es `1/1/1:7` y no el `GPON0/1:7` de las otras tablas.

Una fase que el módulo no conozca **no pisa** lo que ya sabe: un firmware con una fase
nueva no debe convertir un inventario bueno en uno de ONU en estado desconocido.

### El equipo dicta su propia sintaxis

`onu 1 pri wan_conn show` no sólo lista los valores: **termina imprimiendo los comandos que
recrean esa configuración**.

```
wanIndex            : 1
bindingLan          : lan1
bindingSsid         : ssid1 ssid2 ssid3 ssid4
wanVlanId           : 1001
pppoeUserName       : esc_mitre_88
...
onu 1 pri wan_conn add routeQOS enable
onu 1 pri wan_conn index 1 route internet bind_lan 1 bind_ssid 15 qos enable
    nat enable mtu 1492 pppoe proxy disable user esc_mitre_88 pwd a1b1 server FTTH mode auto
```

Es la sintaxis contada por el propio firmware, sobre un cliente que anda. Se guarda cruda,
sin retocar: modificarla al leerla sería perder la única fuente confiable que hay.

De ahí sale también cómo se escriben las interfaces ligadas. El equipo **muestra nombres y
recibe una máscara de bits**: `bindingLan: lan1` se escribe `bind_lan 1`, y
`bindingSsid: ssid1 ssid2 ssid3 ssid4` se escribe `bind_ssid 15` (1+2+4+8). Las dos formas
aparecen en el mismo volcado, así que la interpretación queda comprobada contra sí misma —
no hace falta creerle a nadie.

Ojo: esta salida trae **la contraseña PPPoE del cliente en texto plano**. El modelo la
oculta al imprimirse, y esto no debería loguearse entero nunca.

## Riesgos

| # | Riesgo | Estado |
|---|---|---|
| R3 | Paginación cuelga la sesión | Cubierto: se contesta sola |
| R4 | Dos operaciones simultáneas entrelazan la configuración | Cubierto: sesión exclusiva por OLT |
| R2 | Comando rechazado tomado por datos | Cubierto: se detecta y aborta la secuencia |
| R12 | El prompt de un firmware distinto no coincide con el patrón | Abierto. La captura lo detectaría de inmediato: no habría login |
| R13 | La CLI bloquea la cuenta tras varios intentos fallidos | Mitigado: el protocolo se elige explícitamente, nunca se prueba uno y se cae al otro |
| R14 | Un nombre de plan mal tipeado corta el alta a mitad | Cubierto: se valida contra los planes guardados antes de abrir la sesión |
| R15 | Una baja sobre el índice equivocado deja sin servicio a otro cliente | Mitigado: se muestra el serial del índice y `--serie` lo verifica |
| R16 | El alta escribe en la base comercial | Cubierto: se abre con `mode=ro`, lo impide SQLite |
| R17 | Un dato desactualizado en Pucará se aplica sin que nadie lo note | Mitigado: la propuesta viaja con motivo y advertencias, y avisa si el serial no coincide |
| R18 | Una respuesta normal del equipo se lee como falla y enseña a ignorar los avisos | Cubierto para `auto-find`; la excepción es angosta y está documentada |
