"""
capacidad.py — Motor de evaluación de capacidad/saturación de un AP (Prioridad 2).

Es lógica PURA (no toca la base): recibe métricas ya calculadas de un AP y su
perfil técnico, y devuelve un estado semafórico con el MOTIVO principal.

Combina varios indicadores (no solo cantidad de clientes):
  - saturación:  clientes actuales vs recomendados del perfil
  - señal:       % de clientes con señal pobre (RSSI bajo)
(otros como CCQ/airMAX/airtime quedan como "No disponible" hasta persistirlos
estructuradamente; NO se inventan).

Principio: si falta el dato para un indicador, ese indicador queda 'sin_datos'
y no se inventa. El estado global es el PEOR de los indicadores evaluables.
"""

# Estados y su severidad (para elegir el peor)
_SEV = {'sin_datos': 0, 'normal': 1, 'advertencia': 2, 'critico': 3}
_COLOR = {'normal': '#2e7d32', 'advertencia': '#e8a13b', 'critico': '#c62828', 'sin_datos': '#9e9e9e'}
_ICONO = {'normal': '🟢', 'advertencia': '🟡', 'critico': '🔴', 'sin_datos': '⚫'}

# Umbrales por defecto (se pueden pisar desde el perfil)
RSSI_POBRE_DBM = -75          # por debajo de esto, la señal del cliente es "pobre"
PCT_SENAL_ADV = 20.0          # % de clientes con señal pobre para 🟡
PCT_SENAL_CRIT = 40.0         # % para 🔴


def _peor(*estados):
    """Devuelve el estado más severo entre los pasados (ignora None)."""
    val = [e for e in estados if e]
    if not val:
        return 'sin_datos'
    return max(val, key=lambda e: _SEV.get(e, 0))


def evaluar_saturacion(clientes, recomendados, maximo=None, umbral_adv=None, umbral_crit=None):
    """Evalúa saturación por cantidad de clientes vs recomendados del perfil.
    Devuelve dict {estado, pct, detalle} o 'sin_datos' si no hay recomendados."""
    if not recomendados:
        return {'estado': 'sin_datos', 'pct': None,
                'detalle': 'El perfil no tiene "clientes recomendados" cargados.'}
    pct = round(clientes / recomendados * 100, 1)
    adv = umbral_adv if umbral_adv is not None else 80.0
    crit = umbral_crit if umbral_crit is not None else 100.0
    if pct >= crit:
        estado = 'critico'
    elif pct >= adv:
        estado = 'advertencia'
    else:
        estado = 'normal'
    # Si supera el máximo operativo declarado, es crítico sí o sí
    if maximo and clientes >= maximo:
        estado = 'critico'
    return {'estado': estado, 'pct': pct,
            'detalle': f'{clientes} de {recomendados} recomendados ({pct}%)'
                       + (f' · máx {maximo}' if maximo else '')}


def evaluar_senal(pct_pobre, adv=PCT_SENAL_ADV, crit=PCT_SENAL_CRIT):
    """Evalúa calidad por % de clientes con señal pobre. 'sin_datos' si es None."""
    if pct_pobre is None:
        return {'estado': 'sin_datos', 'pct': None,
                'detalle': 'Sin mediciones de señal recientes.'}
    if pct_pobre >= crit:
        estado = 'critico'
    elif pct_pobre >= adv:
        estado = 'advertencia'
    else:
        estado = 'normal'
    return {'estado': estado, 'pct': round(pct_pobre, 1),
            'detalle': f'{round(pct_pobre,1)}% de clientes con señal pobre'}


def evaluar_ap(clientes, perfil=None, rssi_promedio=None, pct_senal_pobre=None,
               snmp_ok=True):
    """Evaluación integral de un AP.
    - clientes: cantidad de clientes actuales del AP (por SNMP).
    - perfil: dict de perfil_radio (o None si el equipo no tiene perfil).
    - pct_senal_pobre: % de clientes con RSSI < umbral (o None).
    - snmp_ok: si el AP respondió SNMP en el último ciclo.
    Devuelve dict con estado global, color/ícono, motivo principal e indicadores.
    """
    if not snmp_ok:
        return {
            'estado': 'sin_datos', 'color': _COLOR['sin_datos'], 'icono': _ICONO['sin_datos'],
            'motivo': 'Sin respuesta SNMP', 'clientes': clientes,
            'pct_capacidad': None, 'indicadores': [],
        }

    perfil = perfil or {}
    rec = perfil.get('clientes_recomendados')
    maxop = perfil.get('clientes_max_operativo')
    u_adv = perfil.get('umbral_advertencia')
    u_crit = perfil.get('umbral_critico')

    sat = evaluar_saturacion(clientes, rec, maxop, u_adv, u_crit)
    sig = evaluar_senal(pct_senal_pobre)

    indicadores = [
        {'nombre': 'Saturación', 'estado': sat['estado'], 'detalle': sat['detalle'], 'valor': sat['pct']},
        {'nombre': 'Señal', 'estado': sig['estado'], 'detalle': sig['detalle'], 'valor': sig['pct']},
    ]
    if rssi_promedio is not None:
        indicadores.append({'nombre': 'RSSI promedio', 'estado': 'normal',
                            'detalle': f'{round(rssi_promedio,1)} dBm', 'valor': round(rssi_promedio, 1)})

    estado = _peor(sat['estado'], sig['estado'])
    # Motivo principal = el indicador que "manda" el estado global
    motivo = 'Todo normal'
    if estado == 'sin_datos':
        motivo = 'Sin datos de capacidad (falta perfil o mediciones)'
    else:
        candidatos = [i for i in indicadores if i['estado'] == estado and i['nombre'] != 'RSSI promedio']
        if candidatos:
            motivo = f"{candidatos[0]['nombre']}: {candidatos[0]['detalle']}"

    return {
        'estado': estado, 'color': _COLOR[estado], 'icono': _ICONO[estado],
        'motivo': motivo, 'clientes': clientes,
        'pct_capacidad': sat['pct'], 'indicadores': indicadores,
    }


def distribucion_desbalanceada(aps_estados, factor=2.5):
    """Detecta APs con mala distribución de clientes en una misma torre.
    aps_estados: lista de dicts {equipo_id, torre_id, clientes}.
    Marca como desbalanceados los APs de una torre cuya carga se aleja mucho
    del promedio de esa torre (factor). Devuelve set de equipo_id desbalanceados.
    Solo informativo (no es una falla dura)."""
    por_torre = {}
    for a in aps_estados:
        if a.get('torre_id') is None:
            continue
        por_torre.setdefault(a['torre_id'], []).append(a)
    desbal = set()
    for torre_id, aps in por_torre.items():
        if len(aps) < 2:
            continue
        cargas = [a.get('clientes', 0) for a in aps]
        prom = sum(cargas) / len(cargas)
        if prom <= 0:
            continue
        for a in aps:
            c = a.get('clientes', 0)
            if c > prom * factor or (prom > 0 and c < prom / factor):
                desbal.add(a['equipo_id'])
    return desbal
