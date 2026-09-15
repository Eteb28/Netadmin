"""
ftth.py — Motor de evaluación FTTH (Prioridad 3): salud óptica de ONUs y
capacidad/salud de PONs. Lógica PURA (no toca la base), testeable aparte.

Umbrales ópticos para GPON (potencia RX en la ONU, en dBm). Son configurables;
los valores por defecto siguen el presupuesto óptico típico clase B+ (sensibilidad
de recepción ~ -27/-28 dBm). NADA se inventa: sin lectura → 'sin_datos'.
"""

_SEV = {'sin_datos': 0, 'buena': 1, 'normal': 1, 'advertencia': 2, 'critico': 3}
_COLOR = {'buena': '#2e7d32', 'normal': '#2e7d32', 'advertencia': '#e8a13b',
          'critico': '#c62828', 'sin_datos': '#9e9e9e'}
_ICONO = {'buena': '🟢', 'normal': '🟢', 'advertencia': '🟡', 'critico': '🔴', 'sin_datos': '⚫'}

# Ventana óptica sana (dBm). Fuera de esto, la ONU está en riesgo.
RX_MIN_OK = -24.0        # por debajo (más negativo) = señal débil → advertencia
RX_CRITICO = -27.0       # por debajo = al límite del presupuesto → crítico
RX_MAX_OK = -8.0         # por encima = demasiada potencia → advertencia
RX_MAX_CRITICO = -5.0    # por encima = sobrecarga del receptor → crítico

# Umbrales de capacidad del PON (% del split ocupado)
PON_ADV = 80.0           # % de ONUs sobre el máximo para 🟡
PON_CRIT = 95.0          # % para 🔴
# % de ONUs con óptica mala en el PON para escalar su estado
PON_OPTICA_ADV = 15.0
PON_OPTICA_CRIT = 30.0


def _peor(*estados):
    val = [e for e in estados if e]
    return max(val, key=lambda e: _SEV.get(e, 0)) if val else 'sin_datos'


def evaluar_optica_onu(rx_power):
    """Clasifica la potencia óptica RX de una ONU. None → 'sin_datos'."""
    if rx_power is None:
        return 'sin_datos'
    if rx_power < RX_CRITICO or rx_power > RX_MAX_CRITICO:
        return 'critico'
    if rx_power < RX_MIN_OK or rx_power > RX_MAX_OK:
        return 'advertencia'
    return 'buena'


def evaluar_pon(onus_total, onus_online, capacidad, rx_powers=None):
    """Evalúa un PON: saturación (ONUs vs split) + salud óptica.
    - onus_total: ONUs provisionadas en el PON.
    - onus_online: ONUs que reportan señal.
    - capacidad: máximo de ONUs del split (ej. 64).
    - rx_powers: lista de rx_power de las ONUs online (para % óptica mala).
    Devuelve dict con estado, color, ícono, motivo e indicadores."""
    rx_powers = [r for r in (rx_powers or []) if r is not None]

    # Saturación
    if capacidad and capacidad > 0:
        pct = round(onus_total / capacidad * 100, 1)
        if pct >= PON_CRIT:
            sat = 'critico'
        elif pct >= PON_ADV:
            sat = 'advertencia'
        else:
            sat = 'normal'
        sat_det = f'{onus_total} de {capacidad} ONUs ({pct}%)'
    else:
        pct = None
        sat = 'sin_datos'
        sat_det = 'Sin capacidad de split configurada'

    # Óptica: % de ONUs online con señal mala
    if rx_powers:
        malas = sum(1 for r in rx_powers if evaluar_optica_onu(r) in ('advertencia', 'critico'))
        pct_mala = round(malas / len(rx_powers) * 100, 1)
        criticas = sum(1 for r in rx_powers if evaluar_optica_onu(r) == 'critico')
        if criticas > 0 or pct_mala >= PON_OPTICA_CRIT:
            opt = 'critico'
        elif pct_mala >= PON_OPTICA_ADV:
            opt = 'advertencia'
        else:
            opt = 'normal'
        opt_det = f'{pct_mala}% con señal óptica fuera de rango' + (f' · {criticas} crítica(s)' if criticas else '')
    else:
        pct_mala = None
        opt = 'sin_datos'
        opt_det = 'Sin lecturas ópticas'

    estado = _peor(sat, opt)
    indicadores = [
        {'nombre': 'Ocupación', 'estado': sat, 'detalle': sat_det, 'valor': pct},
        {'nombre': 'Óptica', 'estado': opt, 'detalle': opt_det, 'valor': pct_mala},
    ]
    motivo = 'Todo normal'
    if estado in ('critico', 'advertencia'):
        cand = [i for i in indicadores if i['estado'] == estado]
        if cand:
            motivo = f"{cand[0]['nombre']}: {cand[0]['detalle']}"
    elif estado == 'sin_datos':
        motivo = 'Sin datos (PON sin ONUs reportando o sin capacidad configurada)'

    return {
        'estado': estado, 'color': _COLOR[estado], 'icono': _ICONO[estado],
        'motivo': motivo, 'pct_ocupacion': pct, 'pct_optica_mala': pct_mala,
        'onus_total': onus_total, 'onus_online': onus_online,
        'onus_offline': onus_total - onus_online, 'capacidad': capacidad,
        'indicadores': indicadores,
    }
