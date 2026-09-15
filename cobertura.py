"""
cobertura.py — Geometría de cobertura teórica para el mapa inalámbrico de Pucará.

Es geometría PURA (no depende de la base ni de SNMP): dada la ubicación de un AP,
su azimut, apertura horizontal y alcance teórico, produce un polígono sectorial
(GeoJSON) para dibujar en el mapa nuevo de cobertura.

IMPORTANTE (según spec): esto es "cobertura TEÓRICA" — una representación geométrica.
NO es cobertura real (que depende de potencia, frecuencia, terreno, Fresnel, etc.).
La UI debe dejar claro que es teórica.

No inventa datos: si faltan azimut/apertura/alcance, el llamador NO debe dibujar
el sector (se maneja como "No disponible"), en vez de asumir valores.
"""
import math

R_TIERRA_M = 6371000.0  # radio medio terrestre


def normalizar_angulo(a):
    """Normaliza un ángulo a [0, 360)."""
    if a is None:
        return None
    return a % 360.0


def punto_destino(lat, lng, bearing_deg, dist_m):
    """Punto destino (lat, lng) a 'dist_m' metros desde (lat,lng) con rumbo 'bearing_deg'.
    Fórmula de destino geodésico sobre esfera (haversine directa)."""
    ang = math.radians(bearing_deg)
    d_r = dist_m / R_TIERRA_M
    lat1 = math.radians(lat)
    lng1 = math.radians(lng)
    lat2 = math.asin(math.sin(lat1) * math.cos(d_r) +
                     math.cos(lat1) * math.sin(d_r) * math.cos(ang))
    lng2 = lng1 + math.atan2(math.sin(ang) * math.sin(d_r) * math.cos(lat1),
                             math.cos(d_r) - math.sin(lat1) * math.sin(lat2))
    return math.degrees(lat2), math.degrees(lng2)


def bearing(lat1, lng1, lat2, lng2):
    """Rumbo inicial (0-360, 0=norte, 90=este) desde el punto 1 al punto 2."""
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dl = math.radians(lng2 - lng1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return normalizar_angulo(math.degrees(math.atan2(y, x)))


def distancia_m(lat1, lng1, lat2, lng2):
    """Distancia haversine en metros entre dos puntos."""
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R_TIERRA_M * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def sector_geojson(lat, lng, azimut, apertura, alcance_m, pasos=24):
    """Polígono GeoJSON de un sector de cobertura teórica.
      - centro en (lat, lng)
      - orientado a 'azimut' (grados, 0=N)
      - ancho angular = 'apertura' (grados)
      - radio = 'alcance_m' (metros)
    Devuelve None si falta algún dato (no se inventan valores).
    Para apertura >= 360 devuelve un círculo completo (AP omnidireccional).
    El anillo se cierra (primer punto == último), como exige GeoJSON.
    """
    if lat is None or lng is None or azimut is None or apertura is None or not alcance_m:
        return None
    if apertura <= 0 or alcance_m <= 0:
        return None

    if apertura >= 360:
        # Omni: círculo completo
        anillo = [[lng, lat]]  # (no hace falta el centro; es un anillo cerrado)
        anillo = []
        for i in range(pasos * 2 + 1):
            b = (360.0 * i) / (pasos * 2)
            plat, plng = punto_destino(lat, lng, b, alcance_m)
            anillo.append([plng, plat])
        anillo.append(anillo[0])
        return {'type': 'Polygon', 'coordinates': [anillo]}

    inicio = azimut - apertura / 2.0
    fin = azimut + apertura / 2.0
    anillo = [[lng, lat]]  # empieza en el centro (vértice del sector)
    for i in range(pasos + 1):
        b = normalizar_angulo(inicio + (fin - inicio) * i / pasos)
        plat, plng = punto_destino(lat, lng, b, alcance_m)
        anillo.append([plng, plat])  # GeoJSON = [lng, lat]
    anillo.append([lng, lat])       # cierra volviendo al centro
    return {'type': 'Polygon', 'coordinates': [anillo]}


def direccion_promedio(centro_lat, centro_lng, puntos):
    """Dirección (bearing) promedio del centro hacia un conjunto de clientes.
    'puntos' = lista de (lat, lng). Usa media circular (no promedio aritmético,
    que fallaría cerca de 0°/360°). Devuelve None si no hay puntos.
    Sirve para el indicador de orientación: comparar con el azimut configurado."""
    sx = sy = 0.0
    n = 0
    for (plat, plng) in puntos:
        if plat is None or plng is None:
            continue
        b = math.radians(bearing(centro_lat, centro_lng, plat, plng))
        sx += math.cos(b)
        sy += math.sin(b)
        n += 1
    if n == 0:
        return None
    return normalizar_angulo(math.degrees(math.atan2(sy, sx)))


def diferencia_angular(a, b):
    """Menor diferencia entre dos ángulos (0-180)."""
    if a is None or b is None:
        return None
    d = abs(normalizar_angulo(a) - normalizar_angulo(b)) % 360.0
    return min(d, 360.0 - d)


def coherencia_orientacion(azimut, dir_clientes, umbral_adv=45.0):
    """Compara el azimut configurado con la dirección real de los clientes.
    Devuelve dict {diff, estado, mensaje}. Estado: 'coherente' | 'advertencia' | 'sin_datos'.
    NUNCA marca crítico: una discrepancia puede ser reflexión, error de coordenadas,
    apertura real distinta, etc. (spec: no alarma crítica por geometría)."""
    if azimut is None or dir_clientes is None:
        return {'diff': None, 'estado': 'sin_datos',
                'mensaje': 'Sin datos suficientes para evaluar orientación.'}
    diff = diferencia_angular(azimut, dir_clientes)
    if diff <= umbral_adv:
        return {'diff': round(diff, 1), 'estado': 'coherente',
                'mensaje': 'Orientación coherente con la distribución de clientes.'}
    return {'diff': round(diff, 1), 'estado': 'advertencia',
            'mensaje': f'Posible orientación incorrecta o datos físicos desactualizados '
                       f'(azimut {round(azimut)}° vs clientes {round(dir_clientes)}°).'}


def cliente_en_sector(centro_lat, centro_lng, azimut, apertura, alcance_m,
                      cli_lat, cli_lng, margen_grados=0.0, margen_m=0.0):
    """¿El cliente cae dentro del sector teórico? Devuelve dict con detalle.
    Es SOLO informativo (advertencia), no una falla: un cliente fuera del sector
    puede deberse a reflexión, error de coordenadas, apertura real mayor, etc."""
    if None in (centro_lat, centro_lng, azimut, apertura, alcance_m, cli_lat, cli_lng):
        return {'dentro': None, 'motivo': 'datos incompletos'}
    dist = distancia_m(centro_lat, centro_lng, cli_lat, cli_lng)
    b = bearing(centro_lat, centro_lng, cli_lat, cli_lng)
    dif_ang = diferencia_angular(azimut, b)
    dentro_ang = dif_ang <= (apertura / 2.0 + margen_grados)
    dentro_dist = dist <= (alcance_m + margen_m)
    return {
        'dentro': bool(dentro_ang and dentro_dist),
        'distancia_m': round(dist, 1),
        'bearing': round(b, 1),
        'fuera_por': None if (dentro_ang and dentro_dist)
                     else ('angulo' if not dentro_ang else 'distancia'),
    }
