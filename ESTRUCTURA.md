# Estructura del proyecto — Pucará v6.1.8

## Raíz (código que corre)
    app.py                  API Flask (pendiente: dividir en routes/, ver abajo)
    run_server.py           Arranque (Waitress) + verificación de rutas
    core: ftth.py · capacidad.py · cobertura.py     motores de evaluación (lógica pura, testeable)
    pollers: olt_poller.py · snmp_poller.py · torre_poller.py · ubiquiti_poller*.py
    integraciones: sync_pg.py (ERP) · tero_sync.py (HelpDesk) · snmp_wireless.py · snmp_agent.py
    utilidades: backup_pucara.py · export_afectados.py · comprobante_vacaciones.py
                asignar_nap_olt.py · liberar_ips_bajas.py · agregar_headers.py (AGPL)
    verificación: verificar_rutas.py · verificar_rutas_huella.py

## templates/
    index.html                      índice: <head>, nav e includes (587 líneas, era 3008)
    partials/pages/<dominio>/*.html    1 archivo por pantalla
    partials/modals/<dominio>/*.html   1 archivo por modal
    Dominios: clientes · red · ftth · operaciones · rrhh · finanzas · sistema · otros

    Para editar una pantalla: templates/partials/pages/<dominio>/<nombre>.html
    El include queda en la posición exacta del bloque original: el orden del DOM
    no cambia (importa para el apilado de modales).

## static/css/
    main.css                índice de @import (NO reordenar: define la cascada)
    main/01-base.css        variables, reset, keyframes
    main/02-layout.css      sidebar, nav, drawer, páginas
    main/03-componentes.css tarjetas, tablas, botones, badges
    main/04-formularios.css inputs, labels, modales
    main/05-mapa.css        Leaflet, barra del mapa, NAPs
    main/06-dominio.css     servicios, OLT/PON, stock, incidencias
    main/07-varios.css      resto
    tema-oscuro.css · pucara-noc.css · mcli-tabs.css · ap-mosaico.css   (overlays, orden importa)

## static/js/
    Un archivo por módulo. Los que carga index.html deben existir: lo valida
    el chequeo de correspondencia (ver "Antes de entregar").

## scripts_historicos/
    Scripts de ejecución única ya cumplidos. No los referencia nadie.

## Antes de entregar / subir a producción
    python3 verificar_rutas.py                  # integridad de app.py
    python3 verificar_rutas_huella.py --comparar # que no desaparecieron rutas
    for f in *.py; do python3 -m py_compile $f; done
    for f in static/js/*.js; do node --check $f; done
    # y que todo lo que index.html carga exista:
    #   comm -23 <(grep -oP "filename='js/\K[^']+" templates/index.html|sort -u) <(ls static/js|sort)

## Pendiente: dividir app.py
    9487 líneas, 280 rutas, 55 helpers. Plan:
      1. core.py      → get_db, decoradores (login_required, admin_required,
                        requiere_permiso), _table_exists, _now
      2. routes/<dominio>.py → un Blueprint por dominio SIN url_prefix
                        (las URLs no deben cambiar)
      3. app.py       → sólo crear la app, registrar blueprints y arrancar
    Regla: `verificar_rutas_huella.py --guardar` ANTES, `--comparar` DESPUÉS.
    Si la huella cambió, el refactor rompió algo: no subir.
