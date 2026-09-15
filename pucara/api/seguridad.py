"""Control de acceso de los blueprints de la arquitectura nueva.

El problema a resolver: los decoradores `login_required` / `requiere_permiso`
viven en `app.py`. Si el paquete `pucara` los importara, la dependencia quedaría
al revés (el módulo nuevo dependería del monolito) y el paquete dejaría de ser
probable por separado.

La solución es un **punto de extensión**: acá se define la política mínima
—hace falta sesión iniciada— y `app.py` inyecta su motor de permisos con
`registrar_autorizador()`. Sin autorizador registrado la regla sigue siendo
restrictiva: si no hay usuario en sesión, 401. Nunca "abierto por defecto".
"""
from __future__ import annotations

from collections.abc import Callable

from flask import Blueprint, jsonify, session

# (usuario_id, rol, modulo, accion) -> True si puede
Autorizador = Callable[[int, str | None, str, str | None], bool]

_autorizador: Autorizador | None = None


def registrar_autorizador(fn: Autorizador) -> None:
    """Lo llama app.py al registrar los blueprints, pasándole su motor real."""
    global _autorizador
    _autorizador = fn


def proteger(bp: Blueprint, modulo: str | None, accion: str | None = None) -> None:
    """Exige sesión (y permiso, si hay autorizador) en TODAS las rutas del bp.

    Se aplica al blueprint entero y no ruta por ruta a propósito: agregar una
    ruta nueva no debe poder dejarla abierta por olvido.

    `modulo=None` significa **sólo hace falta sesión iniciada**. Es para los
    recursos estrictamente personales —las notas de "Mis Tareas"— donde no
    existe un permiso por módulo que tenga sentido: cada usuario ve lo suyo y
    nada más, y eso lo verifica el servicio en cada operación.
    """

    @bp.before_request
    def _verificar():  # noqa: ANN202  (handler de Flask)
        uid = session.get("user_id")
        if not uid:
            return jsonify({"error": "no_auth"}), 401
        if modulo is None:
            return None
        rol = session.get("rol")
        if rol in ("admin", "root"):
            return None
        if _autorizador is not None and not _autorizador(uid, rol, modulo, accion):
            return jsonify({"error": "forbidden", "detalle": f"Sin permiso para {modulo}"}), 403
        return None
