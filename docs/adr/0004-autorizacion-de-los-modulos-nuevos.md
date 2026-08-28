# ADR-0004 — Autorización de los módulos en arquitectura nueva

- **Estado:** aceptado
- **Fecha:** agosto 2026
- **Depende de:** [ADR-0001](0001-arquitectura-en-capas.md)

## Contexto

Las rutas heredadas se protegen con los decoradores `@login_required`,
`@admin_required` y `@requiere_permiso(modulo, accion)`, definidos **dentro de
`app.py`**.

Los blueprints nuevos viven en el paquete `pucara`, que por el ADR-0001 no puede
depender de `app.py`: eso invertiría la dependencia (el módulo limpio pasaría a
depender del monolito) y haría imposible probar el paquete por separado.

El primer intento de resolverlo fue no protegerlas. El resultado fue un agujero
real: `/api/v2/reclamos/*`, `/api/v2/antiguedad` y `/api/v2/pendientes-rescision`
quedaron accesibles **sin sesión iniciada**, exponiendo el padrón completo con
nombres, seriales de ONU y estadísticas comerciales. Se detectó antes de
desplegar, pero la causa de fondo —"no hay forma limpia de autorizar desde
`pucara`"— seguía ahí.

## Decisión

Un **punto de extensión** en `pucara/api/seguridad.py`:

- `proteger(bp, modulo, accion=None)` instala un `before_request` en **todo el
  blueprint**. La política mínima —hace falta `user_id` en sesión— la define el
  paquete y no depende de nadie.
- `registrar_autorizador(fn)` permite que `app.py` inyecte su motor de permisos.
  Lo hace al registrar los blueprints.

```
app.py                         pucara/api/seguridad.py
  registrar_autorizador(fn) ──────► _autorizador
                                        ▲
pucara/api/reclamos.py                  │
  proteger(bp, "reclamos") ─────────────┘
```

### Por qué a nivel de blueprint y no de ruta

Decorar ruta por ruta hace que **agregar una ruta nueva la deje abierta por
olvido**, que es exactamente el error que originó este ADR. Con
`before_request`, la ruta nueva nace protegida y hay que hacer algo explícito
para abrirla.

### Por qué sin autorizador la regla sigue siendo restrictiva

Si nadie registró un autorizador (por ejemplo en las pruebas, o si el arranque
falló a mitad), la respuesta es **401 sin sesión**, no "pasa todo". Un fallo de
configuración no puede traducirse en apertura.

### Módulo de permiso por blueprint

| Blueprint | Módulo | Motivo |
|---|---|---|
| `reclamos_api` | `reclamos` | Es la información de reclamos |
| `antiguedad_api` | `antiguedad` | Información comercial de la cartera |
| `rescisiones_api` | `monitoreo` | Se consume desde el panel de alertas de ONU |

Antigüedad y rescisiones son **dos blueprints y no uno** justamente porque los
mira gente distinta: unirlos habría obligado a darle el módulo comercial a quien
sólo necesita limpiar OLTs.

## Consecuencias

**A favor**

- `pucara` no importa `app.py`: la dependencia sigue apuntando en la dirección
  correcta y el paquete se prueba solo.
- No se duplica el motor de permisos: hay uno, y es el que ya existía.
- La regla está verificada: `tests/test_seguridad_api.py` comprueba el 401 sin
  sesión, el 403 sin módulo, el paso de admin, **y que todo archivo de
  `pucara/api/` que declare un `Blueprint` llame a `proteger()`**.

**En contra**

- Estado global de módulo (`_autorizador`). Es un *composition root* más, como
  `services/factory.py`; las pruebas lo sustituyen con `monkeypatch`.
- La protección es por módulo completo, no por ruta. Cuando haga falta granularidad
  distinta dentro de un mismo blueprint, se parte el blueprint (como ya se hizo con
  antigüedad y rescisiones).

## Alternativas descartadas

- **Importar los decoradores de `app.py`.** Invierte la dependencia. Descartada por
  el ADR-0001.
- **Reimplementar el chequeo de permisos en `pucara`.** Dos motores de permisos
  divergiendo es peor que no tener ninguno.
- **Un `before_request` global en `app.py` que mire el prefijo `/api/v2`.** Funciona,
  pero deja la política de cada módulo lejos del módulo, y `app.py` es justamente
  el archivo que se quiere dejar de tocar.
