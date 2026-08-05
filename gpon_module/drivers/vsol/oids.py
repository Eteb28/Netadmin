"""OIDs de las OLT VSOL V1600G1 / V1600G1-B.

**Todos los OIDs de este archivo están verificados** contra walks reales de las
OLT de ERLAN (ver docs/00-investigacion.md, sección 2.1). No hay ninguno tomado
de documentación sin comprobar.

Igual de importante es lo que **no** está acá, porque no existe en estos
equipos: número de serie de la ONU, tráfico por ONU, CPU, memoria y temperatura
de chasis. El driver las declara como capacidades ausentes en vez de devolver
ceros.
"""

from __future__ import annotations

#: Rama privada de VSOL.
BASE = "1.3.6.1.4.1.37950.1.1"

# --- Identidad del equipo  [VERIFICADO] -----------------------------------

MODELO = f"{BASE}.5.10.14.1.0"
NOMBRE_EQUIPO = f"{BASE}.5.10.12.5.1.0"
FIRMWARE = f"{BASE}.5.10.12.5.4.0"
MAC = f"{BASE}.5.10.12.5.7.0"
NUMERO_SERIE = f"{BASE}.5.10.12.5.11.0"

#: Estándar, no del fabricante: centésimas de segundo desde el arranque.
UPTIME = "1.3.6.1.2.1.1.3.0"
DESCRIPCION_SISTEMA = "1.3.6.1.2.1.1.1.0"
NOMBRE_SISTEMA = "1.3.6.1.2.1.1.5.0"

#: **Trampa documentada.** Devolvía 39 en una G1 (coincidía con la web y
#: parecía la temperatura del chasis) y 87 en una G1-B. **No es temperatura.**
#: Queda listado para que nadie lo vuelva a tomar por bueno; el driver no lo usa.
OID_ENGANOSO_NO_USAR = f"{BASE}.5.10.12.4.0"

# --- Puertos PON  [VERIFICADO] --------------------------------------------

PON_TEMPERATURA = f"{BASE}.5.10.13.1.1.2"
PON_VOLTAJE = f"{BASE}.5.10.13.1.1.3"

# --- Tabla de estado de ONU  [VERIFICADO] ---------------------------------
# Índice: <pon>.<onu>

ONU_ESTADO = f"{BASE}.6.1.1.1.1.5"
ONU_ULTIMA_SUBIDA = f"{BASE}.6.1.1.1.1.8"
ONU_ULTIMA_BAJADA = f"{BASE}.6.1.1.1.1.9"
#: Motivo de caída. Distingue el corte de luz del corte de fibra: es la
#: diferencia entre "no hay nada que hacer" y "mandar una cuadrilla".
ONU_MOTIVO_CAIDA = f"{BASE}.6.1.1.1.1.10"
ONU_TIEMPO_EN_ESTADO = f"{BASE}.6.1.1.1.1.11"

# --- Tabla óptica de ONU  [VERIFICADO] ------------------------------------
# Índice: <pon>.<onu>

ONU_TEMPERATURA = f"{BASE}.6.1.1.3.1.3"
ONU_VOLTAJE = f"{BASE}.6.1.1.3.1.4"
ONU_POTENCIA_TX = f"{BASE}.6.1.1.3.1.6"
ONU_POTENCIA_RX = f"{BASE}.6.1.1.3.1.7"

# --- IF-MIB estándar ------------------------------------------------------

IF_DESCR = "1.3.6.1.2.1.2.2.1.2"
IF_OPER_STATUS = "1.3.6.1.2.1.2.2.1.8"
IF_ALIAS = "1.3.6.1.2.1.31.1.1.1.18"

# --- Ramas comprobadamente ausentes ---------------------------------------

#: El `olt_poller` de Pucará consulta esta rama como número de serie de ONU.
#: **No existe en la V1600G1-B**: el walk devuelve 0 resultados, y la
#: verificación "el serial coincide con el equipo registrado" queda
#: silenciosamente inactiva. Coincide con un reporte independiente de LibreNMS.
#: Se deja acá documentado para que no se vuelva a intentar.
ONU_SERIE_INEXISTENTE = f"{BASE}.6.1.2.1.1.3"
