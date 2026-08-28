"""Trazabilidad de cambios: qué cambió, quién lo cambió y de qué a qué.

El plan estratégico (§21) pide que toda operación relevante registre usuario,
fecha, objeto, **valor anterior**, **valor nuevo** y resultado. Hoy la tabla
`historial` tiene una columna `diff` que nunca se usó: los registros guardan una
frase suelta y el 88 % de las rutas de escritura no registran nada.

Este módulo tiene la lógica —pura, sin base de datos— para comparar el estado
anterior con el nuevo. La usan los dos mundos:

  * el paquete nuevo, por `AuditoriaRepository` (misma sesión SQLAlchemy);
  * `app.py`, por su propio helper con su conexión sqlite3.

Se comparte la **lógica**, no la escritura: mezclar conexiones sobre el mismo
archivo SQLite da "database is locked".
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

# Campos cuyo valor NUNCA se escribe en el historial. El historial lo lee
# cualquiera con permiso del módulo; una clave PPPoE ahí es una filtración.
# Se registra QUE cambiaron, no A QUÉ.
CAMPOS_SECRETOS = frozenset({
    "password", "clave", "pppoe_clave", "pppoe_pass", "secret", "token",
    "community", "api_key", "telegram_token", "uisp_token", "pg_password",
})

# Etiquetas legibles para la pantalla. Lo que no esté acá se muestra tal cual.
ETIQUETAS: dict[str, str] = {
    "nro_cliente": "N° de cliente", "tipo_servicio": "Tipo de servicio",
    "plan": "Plan", "precio": "Precio", "estado": "Estado",
    "nap": "NAP", "olt_nombre": "OLT", "olt_puerto": "Puerto PON",
    "ip_asignada": "IP asignada", "mac_address": "MAC",
    "equipo_serie": "N° de serie", "equipo_modelo": "Modelo de equipo",
    "equipo_marca": "Marca de equipo", "torre_id": "Torre", "ap_nombre": "AP",
    "pppoe_usuario": "Usuario PPPoE", "pppoe_clave": "Clave PPPoE",
    "lat": "Latitud", "lng": "Longitud", "localidad": "Localidad",
    "direccion": "Dirección", "telefono": "Teléfono", "email": "Email",
    "fecha_alta": "Fecha de alta", "fecha_baja": "Fecha de baja",
    "fecha_rescision": "Fecha de rescisión", "vlan": "VLAN",
}

# Cambios que la gerencia quiere poder encontrar sin filtrar a mano.
CAMPOS_CRITICOS = frozenset({"plan", "precio", "estado", "nap", "olt_puerto",
                             "equipo_serie", "mac_address", "ip_asignada"})


@dataclass(frozen=True)
class CampoCambiado:
    campo: str
    etiqueta: str
    antes: Any
    despues: Any
    critico: bool

    def __str__(self) -> str:
        return f"{self.etiqueta}: {_mostrar(self.antes)} → {_mostrar(self.despues)}"


@dataclass(frozen=True)
class Diferencia:
    """Resultado de comparar dos estados de una entidad."""

    cambios: list[CampoCambiado] = field(default_factory=list)

    @property
    def hubo_cambios(self) -> bool:
        return bool(self.cambios)

    @property
    def criticos(self) -> list[CampoCambiado]:
        return [c for c in self.cambios if c.critico]

    def resumen(self, maximo: int = 3) -> str:
        """Una línea para el título del registro."""
        if not self.cambios:
            return "Sin cambios"
        # Los críticos primero: es lo que alguien busca al abrir el historial.
        orden = self.criticos + [c for c in self.cambios if not c.critico]
        visibles = [str(c) for c in orden[:maximo]]
        resto = len(orden) - len(visibles)
        return " · ".join(visibles) + (f" (+{resto} campo{'s' if resto > 1 else ''})" if resto else "")

    def a_json(self) -> str:
        return json.dumps(
            [{"campo": c.campo, "etiqueta": c.etiqueta,
              "antes": _serializable(c.antes), "despues": _serializable(c.despues),
              "critico": c.critico} for c in self.cambios],
            ensure_ascii=False,
        )


def calcular_diff(antes: dict, despues: dict, campos: list[str] | None = None) -> Diferencia:
    """Compara dos estados y devuelve sólo lo que realmente cambió.

    `campos` acota qué se compara; sin él se comparan las claves de `despues`,
    que es lo que trae el formulario.

    Dos detalles que importan y que un `!=` crudo no resuelve:

    * `""`, `None` y `"  "` son el mismo "vacío". Sin esto, guardar un
      formulario sin tocar nada generaría decenas de "cambios" falsos.
    * `"100"` y `100` son el mismo valor. Los formularios HTML mandan todo como
      texto y la base devuelve números.
    """
    claves = campos if campos is not None else list(despues.keys())
    cambios: list[CampoCambiado] = []
    for k in claves:
        if k not in despues:
            continue
        va, vd = antes.get(k), despues.get(k)
        if _equivalentes(va, vd):
            continue
        secreto = k.lower() in CAMPOS_SECRETOS
        cambios.append(CampoCambiado(
            campo=k,
            etiqueta=ETIQUETAS.get(k, k.replace("_", " ").capitalize()),
            antes="(oculto)" if secreto else va,
            despues="(oculto)" if secreto else vd,
            critico=k in CAMPOS_CRITICOS,
        ))
    return Diferencia(cambios)


# ── helpers ──────────────────────────────────────────────────────────────
def _vacio(v) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def _equivalentes(a, b) -> bool:
    if _vacio(a) and _vacio(b):
        return True
    if _vacio(a) or _vacio(b):
        return False
    # Comparación numérica cuando ambos lo parecen: "100" == 100 == 100.0
    try:
        return float(str(a).replace(",", ".")) == float(str(b).replace(",", "."))
    except (TypeError, ValueError):
        pass
    return str(a).strip() == str(b).strip()


def _mostrar(v) -> str:
    return "(vacío)" if _vacio(v) else str(v)


def _serializable(v):
    return v if isinstance(v, (str, int, float, bool, type(None))) else str(v)
