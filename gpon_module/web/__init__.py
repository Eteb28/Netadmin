"""Interfaz web del módulo GPON (Bootstrap 5).

Aplicación independiente: no comparte base de datos, sesión ni plantillas con
Pucará. Se levanta con ``gpon web``.

Las páginas son cáscaras HTML que consumen la API por ``fetch``; ninguna
importa un servicio ni un driver. Un detalle que ordena toda la interfaz: cada
pantalla consulta primero las capacidades del equipo y **oculta** lo que ese
modelo no soporta, en vez de mostrar un botón que va a fallar.
"""

from .aplicacion import crear_app

__all__ = ["crear_app"]
