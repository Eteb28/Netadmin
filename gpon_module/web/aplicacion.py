"""Aplicación web del módulo GPON.

Aplicación **independiente**: no comparte nada con Pucará, ni base de datos ni
sesión ni plantillas. Se levanta sola y se apaga sola.

La regla de diseño que la ordena: **estas páginas no importan un servicio ni un
driver**. Son cáscaras HTML que consumen la API por ``fetch``. Ese límite es lo
que hace que la interfaz sea reemplazable sin tocar el módulo, y lo que permite
que mañana Pucará consuma exactamente los mismos datos.

Para levantarla::

    gpon web --puerto 8070
"""

from __future__ import annotations

import logging

from flask import Flask

from ..api.rutas import api
from ..services import Contenedor
from .rutas import web

log = logging.getLogger(__name__)


def crear_app(contenedor: Contenedor, *, modo_debug: bool = False) -> Flask:
    """Arma la aplicación con el contenedor ya construido.

    El contenedor entra por parámetro y no se crea acá: así los tests levantan
    la web contra una base en memoria y la OLT simulada, sin variables de
    entorno ni archivos.
    """
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
        static_url_path="/estatico",
    )
    app.config["CONTENEDOR"] = contenedor
    app.config["JSON_SORT_KEYS"] = False
    app.config["DEBUG"] = modo_debug

    app.register_blueprint(api)
    app.register_blueprint(web)

    @app.after_request
    def _sin_cache(respuesta):
        # Los datos de una OLT envejecen en segundos: que el navegador no los
        # guarde evita mostrar un parque que ya cambió.
        if respuesta.mimetype == "application/json":
            respuesta.headers["Cache-Control"] = "no-store"
        return respuesta

    log.info("Interfaz web lista. Base: %s", contenedor.configuracion.url_base_datos)
    return app
