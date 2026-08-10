"""Los perfiles de tráfico de la OLT de ERLAN, para arrancar sin inventario.

**La fuente de verdad sigue siendo el equipo**: ``gpon inventario-cli`` los lee
del ``show running-config`` y pisa esta lista. Esto es una semilla, y existe por
una razón práctica: el desplegable del alta tiene que estar lleno la primera vez
que alguien abre la pantalla, no después de correr un comando que todavía no
sabe que existe.

Los nombres están **verificados contra la OLT 192.168.10.247 (Belgrano)** en
agosto de 2026, y se transcriben tal cual, con sus inconsistencias: ``5M-Dom-Dow``
y ``10M-Dom-UP`` no usan las mismas mayúsculas, ``100M-Pymes-Dowm`` termina en M
y ``50M-PYMES-DOW`` va todo en mayúsculas. Corregir cualquiera de esas rarezas
rompería el comando contra el equipo, que es exactamente lo que ya pasó una vez.

Si aparece una OLT con otros perfiles, la respuesta no es editar este archivo:
es correr el inventario. Por eso la lista está atada a un fabricante y no se usa
como valor por defecto de nada.
"""

from __future__ import annotations

#: Verificados contra la OLT Belgrano. El orden es el que usa el operador: de
#: menor a mayor velocidad, hogar y empresa mezclados como están en el equipo.
PLANES_ERLAN: tuple[str, ...] = (
    "5M-Dom-Dow",
    "5M-Dom-Up",
    "10M-Dom-Dow",
    "10M-Dom-UP",
    "20M-Dom-DOW",
    "20M-Dom-UP",
    "50M-Dom-DOW",
    "50M-Dom-UP",
    "50M-PYMES-DOW",
    "50M-PYMES-UP",
    "100M-Dom-DOW",
    "100M-Dom-UP",
    "100M-Pymes-Dowm",
    "100M-Pymes-UP",
    "150M-Pymes-Dowm",
    "150M-Pymes-UP",
    "200M-Dom-DOW",
    "200M-Dom-UP",
    "200M-Pymes-Dowm",
    "200M-Pymes-UP",
    "300M-Dom-DOW",
    "300M-Dom-UP",
    "300M-Pymes-Dowm",
    "300M-Pymes-UP",
    "600M-Pymes-Dowm",
    "600M-Pymes-UP",
)

__all__ = ["PLANES_ERLAN"]
