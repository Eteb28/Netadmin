"""Drivers de OLT.

Importar este paquete registra todos los drivers disponibles. El resto del
sistema nunca importa un driver concreto: los pide por fabricante a
``core.registry``.

Estado de los drivers:

* ``mock``  — completo, es lo que permite correr el módulo sin una OLT real.
* ``vsol``  — Fase 2 (lectura) y Fase 5 (escritura).
* ``zte``   — Fase 6.
"""

from . import mock

__all__ = ["mock"]
