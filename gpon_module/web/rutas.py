"""Rutas de las páginas.

Cada una devuelve una plantilla y nada más: no consulta servicios ni
repositorios. Los datos los pide el navegador a la API. Si alguna de estas
funciones empieza a llamar a un servicio, el límite se rompió.
"""

from __future__ import annotations

from flask import Blueprint, render_template

web = Blueprint("web", __name__)


@web.get("/")
def panel():
    return render_template("panel.html", seccion="panel")


@web.get("/olts")
def olts():
    return render_template("olts.html", seccion="olts")


@web.get("/olts/<int:olt_id>")
def olt(olt_id: int):
    return render_template("olt.html", seccion="olts", olt_id=olt_id)


@web.get("/olts/<int:olt_id>/onus")
def onus(olt_id: int):
    return render_template("onus.html", seccion="onus", olt_id=olt_id)


@web.get("/olts/<int:olt_id>/onus/<int:pon>/<int:numero>")
def onu(olt_id: int, pon: int, numero: int):
    return render_template("onu.html", seccion="onus", olt_id=olt_id, pon=pon, numero=numero)


@web.get("/olts/<int:olt_id>/potencias")
def potencias(olt_id: int):
    return render_template("potencias.html", seccion="potencias", olt_id=olt_id)


@web.get("/eventos")
def eventos():
    return render_template("eventos.html", seccion="eventos")


@web.get("/operaciones")
def operaciones():
    return render_template("operaciones.html", seccion="operaciones")


@web.get("/capacidades")
def capacidades():
    return render_template("capacidades.html", seccion="capacidades")
