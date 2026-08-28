# ADR-0001 — Arquitectura en capas y estrategia de adopción

- **Estado:** propuesto (requiere aprobación)
- **Fecha:** agosto 2026
- **Contexto previo:** [`../ESTADO-ACTUAL.md`](../ESTADO-ACTUAL.md)

## Contexto

Pucará es hoy un monolito de una capa: 281 rutas Flask y 729 sentencias SQL conviviendo en
un `app.py` de 9.858 líneas, más 18 archivos que abren la base por su cuenta. No hay capa de
servicios, repositorios, DTO ni pruebas.

Se pide una arquitectura `Controller → Service → Repository → Database`, sin SQL disperso y
con la lógica de negocio en Services.

## Decisión

Adoptar la arquitectura en capas **de forma incremental por dominio**, no con una reescritura
completa.

```
api/          (Controller)  HTTP: valida entrada, traduce a DTO, devuelve JSON. Sin SQL.
services/     (Service)     Lógica de negocio. No sabe de HTTP ni de SQL.
repositories/ (Repository)  Único lugar con acceso a datos. Devuelve modelos, no filas.
models/                     Entidades SQLAlchemy + DTO.
```

Reglas verificables (se harán cumplir con una prueba automática, no con buena voluntad):

1. `api/` no puede importar `repositories/` ni contener SQL.
2. `services/` no puede importar `flask`.
3. Fuera de `repositories/` no puede haber `sqlite3.connect`, `.execute(` ni SQL crudo.

## Estrategia de adopción: patrón *Strangler Fig*

La alternativa —reescribir las 281 rutas antes de entregar nada— dejaría el proyecto meses
sin avanzar y con un riesgo enorme en un sistema que está en producción. En su lugar:

- **Todo dominio nuevo nace en la arquitectura nueva.** Reclamos (punto 2 del pedido) es el
  primero y sirve de referencia.
- **Los dominios existentes migran cuando hay que tocarlos**, no antes y no "todos juntos".
- `app.py` va adelgazando a medida que los dominios se mudan; deja de crecer desde ya.

El monolito y las capas nuevas conviven durante la transición. Es deliberado.

## Consecuencias

**A favor**
- Se entrega valor desde la primera semana sin congelar el proyecto.
- Cada dominio migrado queda con pruebas: la cobertura crece con el trabajo real.
- Si el enfoque resulta equivocado, se descubre con un dominio, no con 281 rutas.

**En contra**
- Convivencia temporal de dos estilos. Se acepta a cambio de no frenar producción.
- Requiere disciplina: la regla "lo nuevo va en capas" hay que sostenerla. Por eso se
  automatiza como prueba.

## Alternativa descartada

**Reescritura completa antes de nuevas funciones.** Descartada: meses sin entregas, riesgo
alto sobre un sistema en producción y sin red de pruebas que respalde el cambio.
