"""Drivers de OLT.

Importar este paquete registra todos los drivers disponibles. El resto del
sistema nunca importa un driver concreto: los pide por fabricante a
``core.registry``.

Estado de los drivers:

* ``mock``  — completo, es lo que permite correr el módulo sin una OLT real.
* ``vsol``  — lectura por SNMP (Fase 2). La escritura llega en la Fase 5.
* ``zte``   — Fase 6.
"""

from . import mock, vsol

__all__ = ["mock", "vsol"]
