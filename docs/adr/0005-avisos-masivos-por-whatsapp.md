# ADR-0005 — Avisos masivos por WhatsApp ante caídas masivas

- **Estado:** propuesto (requiere aprobación)
- **Fecha:** agosto 2026
- **Cubre:** el pedido de "cuando tengamos caídas masivas, mandar un aviso automático por
  WhatsApp, con un panel para configurar el mensaje y dar el OK antes del envío"

---

## Contexto

Cuando se corta un PON entero, hoy pasa esto: el motor de incidentes (fase 4, ADR-0003)
detecta la caída masiva, la agrupa en **un** incidente con sus afectados, e infiere la causa
probable (`Power Off` = corte eléctrico, `Onu Los` = fibra cortada). El NOC se entera por
Telegram. **El cliente no se entera de nada**, y arranca la avalancha de llamadas y de
tickets a Tero preguntando qué pasa.

El sistema **ya sabe** todo lo que hace falta para avisarles:

| Dato | Dónde está hoy |
|---|---|
| Qué se cayó y cuándo | `incidentes` (alcance `PON`, `inicio`, `causa_probable`) |
| Quiénes están afectados | `incidente_afectados` (`cliente_id`, `nro_cliente`) |
| Teléfono de cada uno | `clientes.telefono` y `clientes.telefono2` (vienen del ERP por `sync_pg.py`) |
| Si la lectura fue confiable | `procesar_sondeo(..., lectura_completa)` del motor |

Lo que falta es el canal y —sobre todo— **el control humano sobre el disparo**.

### Por qué el control humano no es opcional

Está documentado en el historial de errores del proyecto: una lectura SNMP truncada marcó
PONs enteros como caídos y disparó una tanda de avisos por Telegram. Ese error, contenido
dentro del NOC, fue una molestia. **El mismo error mandado por WhatsApp a 300 clientes es
irreversible**: no se puede "desmandar", genera más llamadas de las que evita, y castiga la
calidad de la línea de WhatsApp de la empresa.

De ahí la decisión central de este ADR: **Pucará prepara el aviso; una persona lo aprueba.**
El automatismo llega hasta el borrador.

---

## Decisión

### 1. Módulo en Python dentro de Pucará. No n8n.

La pregunta era si convenía n8n o una aplicación en Python. **Python, dentro de Pucará**, por
seis razones concretas:

| | n8n | Módulo en Pucará |
|---|---|---|
| **Los datos** | Están en `netadmin.db`. n8n tendría que leerlos por una API que hay que escribir igual | Los lee directo por el Repository que ya existe |
| **Permisos** | Login propio de n8n. No conoce los roles de Pucará: quien entra a n8n puede disparar el envío | `proteger(bp, "avisos")` + flag `puede_aprobar_avisos` sobre el motor de permisos que ya está |
| **Auditoría** | Queda en la base de n8n → dos verdades sobre el mismo incidente | Queda al lado del incidente, en la misma transacción |
| **El "OK" humano** | Se arma con nodos `Wait` + `Webhook` + un formulario suelto. Frágil y sin identidad del que aprueba | Es una pantalla más del sistema, con el usuario de sesión firmando la aprobación |
| **Pruebas** | Los workflows no se prueban con `pytest`. La regla del proyecto es "ninguna funcionalidad sin pruebas" | Repos, servicio y API con pruebas, como las fases 1 a 6 |
| **Operación** | Otro servicio, otro backup, otra actualización, otro punto de caída en un servidor que ya corre waitress + Caddy + cron | Cero servicios nuevos, cero dependencias de infraestructura |

Y el argumento que cierra la discusión: **n8n se justifica cuando hay que pegar muchos
sistemas heterogéneos sin escribir código.** Acá hay **un** origen (Pucará) y **un** destino
(la API de Meta). No hay orquestación que delegar; sólo se agregaría un intermediario que
puede estar caído justo cuando hay un corte masivo, que es exactamente cuando lo necesitás.

**Esto no cierra la puerta a n8n para otras cosas** (por ejemplo, pegar Tero con el ERP y
con planillas). Para este pedido, no paga lo que cuesta.

### 2. WhatsApp Business Cloud API oficial de Meta. Nada de WhatsApp Web.

Existe la tentación —y es la receta que circula en los tutoriales de n8n— de usar una
librería que maneja WhatsApp Web (`whatsapp-web.js`, Baileys, venom-bot). **Queda descartada
de entrada:** viola los términos de servicio, y la forma más rápida de que Meta banee un
número es mandar 300 mensajes casi idénticos en dos minutos. El número que se banea es el
número comercial que está impreso en la factura. El riesgo no es teórico y no es asumible.

Se usa la **Cloud API hosteada por Meta**, directo, sin intermediario. Un BSP (Twilio,
360dialog, Gupshup, Wati) revende exactamente lo mismo con un margen encima, y lo que agrega
—colas, reintentos, gestión de plantillas— es justamente lo que este módulo hace. Para no
quedar casados con la decisión, el envío entra por una **interfaz `ProveedorWhatsApp`**: si
mañana conviene un BSP, se escribe otro adaptador y no se toca ni el servicio ni el panel.

### 3. El panel configura las **variables** del mensaje, no el mensaje entero.

Esta es la restricción que hay que entender antes de prometer nada, porque cambia lo que el
panel puede ofrecer.

Meta **no permite** mandarle texto libre a alguien que no te escribió en las últimas 24
horas. Fuera de esa ventana sólo se puede enviar una **plantilla previamente aprobada** por
Meta (categoría *utility* para avisos de servicio). Las plantillas tienen texto fijo y
huecos `{{1}}`, `{{2}}`… que sí se completan al momento del envío.

Entonces el panel es:

```
[ Plantilla ▾ ]  Corte de servicio — aviso inicial
   Zona          [ El Pingo — PON 5 ............ ]
   Desde         [ 14:20 ....................... ]
   Causa         [ corte de energía en la zona . ]

┌ Vista previa (lo que le llega al cliente) ────────────┐
│ ERLAN Telecomunicaciones                              │
│ Estamos con una interrupción del servicio en El Pingo │
│ — PON 5 desde las 14:20, por corte de energía en la   │
│ zona. Ya estamos trabajando. Te avisamos cuando se    │
│ normalice.                                            │
└───────────────────────────────────────────────────────┘

  312 afectados · 287 con teléfono válido · 3 con baja voluntaria
  [ Enviar prueba al equipo ]   [ Enviar a los 287 ]
```

El texto fijo se edita en Meta (y vuelve a pasar por aprobación, que tarda de minutos a
horas). Lo variable se edita en el panel y sale al instante. Es importante que el dueño del
producto lo sepa desde el día uno: **no es "escribo lo que quiero y le doy enviar"**.

### 4. Automatismo hasta el borrador; el envío lo aprueba una persona.

```
Motor de incidentes            Pucará                       Operador
──────────────────             ──────                       ────────
caída masiva en PON  ─────►  crea BORRADOR de aviso
                             avisa al NOC (Telegram)  ─────►  abre el panel
                                                              elige plantilla y variables
                                                              ve la vista previa
                                                              manda una prueba al equipo
                                                       ◄─────  APRUEBA (queda firmado)
                             worker despacha con ritmo
                             webhook actualiza estados ─────►  progreso en vivo
incidente CERRADO    ─────►  ofrece aviso "normalizado" ────►  un clic
```

Salvaguardas que el sistema hace cumplir, no que el operador tiene que recordar:

1. **No se puede aprobar un aviso si el sondeo que originó el incidente fue una lectura
   parcial.** Es la regla de oro de producción, llevada al canal más caro de equivocarse.
2. **No se puede aprobar un aviso de un incidente con menos de N minutos de vida**
   (10 por defecto, configurable): evita avisar por un parpadeo.
3. **Un solo aviso en vuelo por incidente**, garantizado por índice único parcial en la base
   —no por código— para que dos operadores en simultáneo no manden lo mismo dos veces.
4. **Tope de destinatarios por aviso**; superarlo exige rol admin.
5. **Bloqueo horario** (23:00–07:00) salvo forzado explícito.
6. **Opt-out siempre respetado**, y quien se dio de baja no vuelve a entrar en un padrón.
7. **Confirmación tipeando la cantidad** antes de disparar: no alcanza con un clic.

### 5. El despacho lo hace un worker por cron, no el request HTTP.

Mandar 300 mensajes dentro de un request de Flask bloquea un hilo de waitress durante
minutos y pierde todo si el servicio reinicia. El envío lo hace `avisos_worker.py`, invocado
por cron cada minuto con `flock`, igual que los pollers que ya están. El estado vive en la
tabla de destinatarios, así que el worker es **idempotente y retomable**: si se corta la luz
a mitad de camino, en la corrida siguiente sigue por donde iba. Sin Celery, sin Redis, sin
dependencias nuevas.

---

## Consecuencias

**A favor**

- El cliente se entera antes de llamar. Es el objetivo del pedido y baja llamadas y tickets.
- Todo el aviso queda auditado al lado del incidente: quién lo aprobó, a quiénes, con qué
  texto, y qué contestó Meta por cada destinatario.
- La primera fase (padrón de destinatarios + vista previa + simulación) **es útil sin Meta**:
  ya te dice a quiénes avisarías y saca la lista para llamarlos.
- El adaptador aísla al proveedor: cambiar a un BSP es escribir una clase.

**En contra / lo que hay que asumir**

- **Hay trámite con Meta antes de mandar el primer mensaje real**: Business Manager
  verificado, un número dedicado, plantillas cargadas y aprobadas. No lo puede resolver el
  código.
- **El número no puede ser uno que hoy esté en uso en la app WhatsApp Business** sin migrarlo
  (y al migrarlo se pierde el uso desde el celular).
- **Cuesta plata por mensaje.** Las plantillas *utility* se cobran por mensaje entregado
  fuera de la ventana de 24 h. Orden de magnitud para Argentina según fuentes públicas: entre
  centavos de dólar y ~USD 0,06 por mensaje según proveedor y volumen — **hay que confirmarlo
  contra la tabla oficial vigente antes de aprobar el gasto**, y desde abril de 2026 Meta
  factura en pesos en Argentina.
- **Hay un tope diario de usuarios únicos** (1.000 en el escalón inicial). Alcanza para un
  corte, no para tres el mismo día. Se sube con la verificación de negocio.
- **Los teléfonos de la base están sucios.** Normalizar a E.164 argentino es trabajo real y
  con riesgo: un número mal armado le manda el aviso a un tercero. La decisión es
  **no adivinar**: lo que no valida no se manda y queda listado para que Atención lo corrija.
- La lógica de "qué decimos" queda partida en dos lugares (texto fijo en Meta, variables en
  Pucará). Es una consecuencia de la plataforma, no del diseño.

---

## Alternativas descartadas

| Alternativa | Por qué no |
|---|---|
| **n8n orquestando** | Sin ganancia real: un origen y un destino. Suma un servicio, un login sin los roles de Pucará, una segunda base con la auditoría, y workflows que no se prueban con `pytest`. |
| **WhatsApp Web no oficial** (`whatsapp-web.js`, Baileys) | Viola los ToS y el envío masivo es el gatillo típico del baneo. Se pierde el número comercial. |
| **Envío 100 % automático, sin OK** | El sistema ya se equivocó una vez concluyendo caídas por una lectura truncada. Ese error por WhatsApp es irreversible. |
| **SMS en vez de WhatsApp** | Más caro por unidad, sin estados de entrega útiles, y la gente no los lee. Puede convivir después como reserva para quien no tiene WhatsApp. |
| **Sólo un aviso en la app / mail** | El cliente que se quedó sin internet no ve ni la app ni el mail. WhatsApp le llega por datos móviles. |
| **Meter todo en `app.py`** | Rompe el ADR-0001 y suma a un archivo de 9.892 líneas. El módulo va en `pucara/`, en capas. |

---

## Qué hace falta decidir antes de implementar

1. **Número de teléfono** que va a ser el emisor (y si hoy está en uso en la app de WhatsApp
   Business).
2. **Cloud API directo o BSP.** La recomendación es directo; un BSP se justifica sólo si se
   quiere evitar el trámite con Meta y se acepta el margen.
3. **Texto exacto de las 4 plantillas** (aviso inicial, actualización, normalizado,
   corte programado). Cuanto antes se manden a aprobar, antes se puede probar de punta a punta.

El detalle técnico —modelo de datos, migración, capas, API, panel, worker, pruebas y plan por
fases— está en [`docs/DISENO-AVISOS-WHATSAPP.md`](../DISENO-AVISOS-WHATSAPP.md).
