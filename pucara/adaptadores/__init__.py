"""Adaptadores de entrada que NO son HTTP.

Misma función que `pucara/api`, pero para procesos: pollers, tareas de cron,
comandos. Traducen el mundo exterior a los tipos del dominio y llaman a un
servicio. No contienen lógica de negocio ni acceso a datos.
"""
