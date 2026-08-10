"""Los datos del cliente, leídos del sistema comercial.

Esto es lo único del módulo que mira afuera, y lo hace con dos reglas que no se
negocian:

* **Sólo lectura.** La conexión se abre en modo lectura (``mode=ro``), así que
  no es una promesa sino algo que el driver de SQLite hace cumplir. El alta de
  una ONU no puede convertirse en un camino lateral para editar la base
  comercial.
* **Cero cambios del otro lado.** No se crean tablas, ni índices, ni columnas.
  Se consulta lo que ya existe. Si mañana el módulo se integra de otra forma
  —una API, otra base—, se cambia esta clase y nada más: el resto del módulo
  habla con el ``Protocol``, no con SQLite.

Lo que se lee de ``clientes``: el número, el nombre, el plan contratado, las
credenciales PPPoE, la NAP y el modelo de ONU. Con eso alcanza para que dar de
alta a un cliente sea confirmar datos en vez de retipearlos.
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
from pathlib import Path

from ...core.errors import ErrorRepositorio, NoEncontrado
from ...core.models import Cliente

log = logging.getLogger(__name__)

#: ``PUERTOSANCHEZ - CDO: 8 - NAP: 3``, que es como Pucará guarda la ubicación.
UBICACION = re.compile(
    r"^\s*(?P<sitio>.*?)\s*-\s*CDO:\s*(?P<cdo>\d+)\s*-\s*NAP:\s*(?P<nap>\d+)\s*$",
    re.IGNORECASE,
)

#: ``INTERNET 10 MB``, ``Abono residencial FIBRA 100 MB (Efectivo)``, ``300 MB``.
#: Los nombres de plan no son uniformes, así que se busca el número seguido de
#: la unidad en cualquier parte del texto.
MEGABITS = re.compile(r"(?<![\d.])(?P<valor>\d{1,4})\s*(?:MB|MEGAS?|M)\b", re.IGNORECASE)

#: ``ONU VSOL 2GE+1POTS+WIFI AC BRIDGE/ROUTER V2802DAC XPON`` → ``V2802DAC``.
MODELO_ONU = re.compile(r"\b(V\d{3,4}[A-Z]{0,4})\b")


class RepositorioClientesPucara:
    """Lee la base de Pucará sin tocarla."""

    def __init__(self, ruta: str | Path) -> None:
        self._ruta = Path(ruta)

    @property
    def disponible(self) -> bool:
        """Si no hay base configurada, el módulo sigue andando sin autocompletar.

        El alta a mano tiene que poder hacerse igual: que el sistema comercial
        no esté a mano no es motivo para dejar a un técnico esperando.
        """
        return not self.motivo_no_disponible

    @property
    def ruta(self) -> Path:
        return self._ruta

    @property
    def motivo_no_disponible(self) -> str:
        """Por qué no se puede leer, con la ruta que se intentó.

        Existe porque "no hay sistema comercial configurado" y "la ruta que
        configuraste no existe" mandan a buscar el problema a lugares
        distintos, y decir el primero cuando pasa el segundo hace perder la
        tarde. Vacío significa que sí se puede leer.
        """
        if not self._ruta.is_absolute() and not self._ruta.exists():
            # Una ruta relativa depende del directorio desde el que se arrancó,
            # que casi nunca es el que la persona tenía en la cabeza.
            return (
                f"La ruta configurada es relativa y no existe desde acá: {self._ruta}. "
                "Poné la ruta absoluta en GPON_BASE_CLIENTES."
            )
        if not self._ruta.exists():
            return f"No existe el archivo {self._ruta} (GPON_BASE_CLIENTES)."
        if self._ruta.is_dir():
            return f"{self._ruta} es un directorio, no la base de datos."
        if not os.access(self._ruta, os.R_OK):
            return f"No hay permiso de lectura sobre {self._ruta}."
        return ""

    def buscar(self, numero: str) -> Cliente:
        """Trae al cliente por su número. Levanta ``NoEncontrado`` si no está."""
        buscado = numero.strip()
        if not buscado:
            raise NoEncontrado("Falta el número de cliente")

        fila = self._consultar(
            """
            SELECT c.nro_cliente, c.nombre, c.plan, c.tipo_servicio, c.estado,
                   c.nap, c.pppoe_usuario, c.pppoe_clave,
                   c.equipo_modelo, c.equipo_serie,
                   a.velocidad_bajada AS megas
              FROM clientes c
              LEFT JOIN abonos a ON UPPER(TRIM(a.nombre)) = UPPER(TRIM(c.plan))
             WHERE TRIM(c.nro_cliente) = ?
             LIMIT 1
            """,
            (buscado,),
        )
        if fila is None:
            raise NoEncontrado(
                f"No hay ningún cliente con el número {buscado} en el sistema comercial."
            )
        return _a_cliente(fila)

    # --- internos ---------------------------------------------------------

    def _consultar(self, sql: str, parametros: tuple) -> sqlite3.Row | None:
        if motivo := self.motivo_no_disponible:
            raise ErrorRepositorio(motivo)
        # 'mode=ro' es lo que convierte "sólo lectura" en algo que no depende de
        # que el código se porte bien.
        uri = f"file:{self._ruta}?mode=ro"
        try:
            with sqlite3.connect(uri, uri=True) as conexion:
                conexion.row_factory = sqlite3.Row
                return conexion.execute(sql, parametros).fetchone()
        except sqlite3.Error as exc:
            raise ErrorRepositorio(f"No se pudo leer el sistema comercial: {exc}") from exc


def _a_cliente(fila: sqlite3.Row) -> Cliente:
    sitio, cdo, nap = _partir_ubicacion(fila["nap"])
    return Cliente(
        numero=(fila["nro_cliente"] or "").strip(),
        nombre=(fila["nombre"] or "").strip(),
        plan=(fila["plan"] or "").strip(),
        tipo_servicio=(fila["tipo_servicio"] or "").strip(),
        estado=(fila["estado"] or "").strip(),
        megabits_bajada=_megabits(fila["megas"], fila["plan"]),
        sitio=sitio,
        cdo=cdo,
        nap=nap,
        pppoe_usuario=(fila["pppoe_usuario"] or "").strip(),
        pppoe_password=(fila["pppoe_clave"] or "").strip(),
        modelo_equipo=_modelo(fila["equipo_modelo"]),
        numero_serie=(fila["equipo_serie"] or "").strip().upper(),
    )


def _partir_ubicacion(texto: str | None) -> tuple[str, int | None, int | None]:
    encontrado = UBICACION.match(texto or "")
    if encontrado is None:
        return "", None, None
    return (
        encontrado.group("sitio"),
        int(encontrado.group("cdo")),
        int(encontrado.group("nap")),
    )


def _megabits(declarados: object, plan: str | None) -> int | None:
    """Los megas del plan: primero lo declarado, después lo que diga el nombre.

    La tabla de abonos es la fuente buena, pero no todos los planes cargados en
    los clientes existen ahí —hay variantes tipeadas a mano como ``Abono
    residencial FIBRA 10 MB (Efectivo)``—, y para ésas el nombre es lo único
    que hay.
    """
    if isinstance(declarados, int) and declarados > 0:
        return declarados
    encontrado = MEGABITS.search(plan or "")
    return int(encontrado.group("valor")) if encontrado else None


def _modelo(texto: str | None) -> str:
    """Saca ``V2802DAC`` de la descripción larga del equipo."""
    encontrado = MODELO_ONU.search(texto or "")
    return encontrado.group(1) if encontrado else ""


__all__ = ["RepositorioClientesPucara"]
