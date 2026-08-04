"""Interfaz web (Fase 3).

Aplicación independiente con Bootstrap 5: panel, listados de OLT, PON y ONU,
clientes, potencias, gráficos, históricos, alarmas, registros y configuración.

Consume exclusivamente la API de ``api/``. La regla es la del diseño: la web
nunca habla con un driver.

Un detalle que ordena toda la interfaz: cada pantalla consulta primero las
capacidades del equipo y **oculta** lo que ese modelo no soporta, en vez de
mostrar un botón que va a fallar.
"""
