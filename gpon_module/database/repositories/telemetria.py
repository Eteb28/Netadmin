"""Repositorios de métricas, eventos, alarmas, operaciones y sincronizaciones.

Son las tablas del histórico y de la trazabilidad: lo que permite responder
"cómo venía esta ONU la semana pasada" y "quién ejecutó qué sobre la OLT".
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ...core.enums import (
    EstadoAlarma,
    Granularidad,
    NivelSincronizacion,
    ResultadoSincronizacion,
    Severidad,
    TipoAlarma,
    TipoEvento,
    TipoMetrica,
    TipoOperacion,
)
from ...core.models import (
    Alarma,
    Evento,
    Metrica,
    Operacion,
    RefONU,
    Sincronizacion,
)
from ..conexion import Conexion, a_fecha, a_texto

SEPARADOR_COMANDOS = "\n"


class RepositorioMetricaSQL:
    """Series temporales con retención escalonada.

    La granularidad es una columna, no una tabla: agregar y depurar es un
    ``INSERT ... SELECT`` seguido de un ``DELETE``, sin migrar nada.
    """

    def __init__(self, conexion: Conexion) -> None:
        self._db = conexion

    def _a_modelo(self, fila: dict[str, Any]) -> Metrica:
        return Metrica(
            id=fila["id"],
            olt_id=fila["olt_id"],
            entidad=fila["entidad"],
            entidad_id=fila["entidad_id"],
            tipo=TipoMetrica(fila["tipo"]),
            valor=fila["valor"],
            granularidad=Granularidad(fila["granularidad"]),
            muestras=fila["muestras"],
            valor_minimo=fila["valor_minimo"],
            valor_maximo=fila["valor_maximo"],
            registrada_en=a_fecha(fila["registrada_en"]),
        )

    def registrar(self, metrica: Metrica) -> None:
        self.registrar_muchas([metrica])

    def registrar_muchas(self, metricas: list[Metrica]) -> None:
        if not metricas:
            return
        ahora = a_texto(datetime.now(UTC))
        self._db.ejecutar_muchos(
            """
            INSERT INTO metricas (
                olt_id, entidad, entidad_id, tipo, valor, granularidad,
                muestras, valor_minimo, valor_maximo, registrada_en
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            [
                (
                    m.olt_id,
                    m.entidad,
                    m.entidad_id,
                    str(m.tipo),
                    m.valor,
                    str(m.granularidad),
                    m.muestras,
                    m.valor_minimo,
                    m.valor_maximo,
                    a_texto(m.registrada_en) or ahora,
                )
                for m in metricas
            ],
        )

    def serie(
        self,
        *,
        entidad: str,
        entidad_id: int,
        tipo: TipoMetrica,
        desde: datetime,
        hasta: datetime,
        granularidad: Granularidad = Granularidad.FINA,
    ) -> list[Metrica]:
        filas = self._db.consultar_todos(
            """
            SELECT * FROM metricas
            WHERE entidad = ? AND entidad_id = ? AND tipo = ? AND granularidad = ?
              AND registrada_en >= ? AND registrada_en <= ?
            ORDER BY registrada_en
            """,
            (
                entidad,
                entidad_id,
                str(tipo),
                str(granularidad),
                a_texto(desde),
                a_texto(hasta),
            ),
        )
        return [self._a_modelo(fila) for fila in filas]

    def ultimo_valor(
        self, *, entidad: str, entidad_id: int, tipo: TipoMetrica
    ) -> Metrica | None:
        fila = self._db.consultar_uno(
            """
            SELECT * FROM metricas
            WHERE entidad = ? AND entidad_id = ? AND tipo = ?
            ORDER BY registrada_en DESC, id DESC
            """,
            (entidad, entidad_id, str(tipo)),
        )
        return self._a_modelo(fila) if fila else None

    def depurar(self, *, granularidad: Granularidad, anterior_a: datetime) -> int:
        """Borra métricas viejas de un escalón. Devuelve cuántas quedaron fuera."""
        antes = self._db.consultar_uno(
            "SELECT COUNT(*) AS c FROM metricas WHERE granularidad = ? AND registrada_en < ?",
            (str(granularidad), a_texto(anterior_a)),
        )
        self._db.ejecutar(
            "DELETE FROM metricas WHERE granularidad = ? AND registrada_en < ?",
            (str(granularidad), a_texto(anterior_a)),
        )
        return int(antes["c"]) if antes else 0

    def contar(self) -> int:
        fila = self._db.consultar_uno("SELECT COUNT(*) AS c FROM metricas")
        return int(fila["c"]) if fila else 0


class RepositorioEventoSQL:
    """Bitácora de cambios detectados. Es el histórico del inventario."""

    def __init__(self, conexion: Conexion) -> None:
        self._db = conexion

    def _a_modelo(self, fila: dict[str, Any]) -> Evento:
        ref = (
            RefONU(pon=fila["pon"], onu_id=fila["onu_id"])
            if fila["pon"] is not None and fila["onu_id"] is not None
            else None
        )
        return Evento(
            id=fila["id"],
            tipo=TipoEvento(fila["tipo"]),
            olt_id=fila["olt_id"],
            entidad=fila["entidad"],
            entidad_id=fila["entidad_id"],
            ref_onu=ref,
            descripcion=fila["descripcion"],
            valor_anterior=fila["valor_anterior"],
            valor_nuevo=fila["valor_nuevo"],
            ocurrido_en=a_fecha(fila["ocurrido_en"]),
        )

    def registrar(self, evento: Evento) -> Evento:
        nuevo_id = self._db.ejecutar(
            """
            INSERT INTO eventos (
                tipo, olt_id, entidad, entidad_id, pon, onu_id,
                descripcion, valor_anterior, valor_nuevo, ocurrido_en
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                str(evento.tipo),
                evento.olt_id,
                evento.entidad,
                evento.entidad_id,
                evento.ref_onu.pon if evento.ref_onu else None,
                evento.ref_onu.onu_id if evento.ref_onu else None,
                evento.descripcion,
                evento.valor_anterior,
                evento.valor_nuevo,
                a_texto(evento.ocurrido_en) or a_texto(datetime.now(UTC)),
            ),
        )
        fila = self._db.consultar_uno("SELECT * FROM eventos WHERE id = ?", (nuevo_id,))
        return self._a_modelo(fila)  # type: ignore[arg-type]

    def registrar_muchos(self, eventos: list[Evento]) -> None:
        if not eventos:
            return
        ahora = a_texto(datetime.now(UTC))
        self._db.ejecutar_muchos(
            """
            INSERT INTO eventos (
                tipo, olt_id, entidad, entidad_id, pon, onu_id,
                descripcion, valor_anterior, valor_nuevo, ocurrido_en
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            [
                (
                    str(e.tipo),
                    e.olt_id,
                    e.entidad,
                    e.entidad_id,
                    e.ref_onu.pon if e.ref_onu else None,
                    e.ref_onu.onu_id if e.ref_onu else None,
                    e.descripcion,
                    e.valor_anterior,
                    e.valor_nuevo,
                    a_texto(e.ocurrido_en) or ahora,
                )
                for e in eventos
            ],
        )

    def listar(
        self,
        *,
        olt_id: int | None = None,
        tipo: TipoEvento | None = None,
        limite: int = 100,
        desplazamiento: int = 0,
    ) -> list[Evento]:
        condiciones: list[str] = []
        parametros: list[Any] = []
        if olt_id is not None:
            condiciones.append("olt_id = ?")
            parametros.append(olt_id)
        if tipo is not None:
            condiciones.append("tipo = ?")
            parametros.append(str(tipo))
        donde = f"WHERE {' AND '.join(condiciones)}" if condiciones else ""
        filas = self._db.consultar_todos(
            f"""
            SELECT * FROM eventos {donde}
            ORDER BY ocurrido_en DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            (*parametros, limite, desplazamiento),
        )
        return [self._a_modelo(fila) for fila in filas]

    def contar(self, *, olt_id: int | None = None) -> int:
        if olt_id is None:
            fila = self._db.consultar_uno("SELECT COUNT(*) AS c FROM eventos")
        else:
            fila = self._db.consultar_uno(
                "SELECT COUNT(*) AS c FROM eventos WHERE olt_id = ?", (olt_id,)
            )
        return int(fila["c"]) if fila else 0


class RepositorioAlarmaSQL:
    """Alarmas abiertas, reconocidas y resueltas."""

    def __init__(self, conexion: Conexion) -> None:
        self._db = conexion

    def _a_modelo(self, fila: dict[str, Any]) -> Alarma:
        return Alarma(
            id=fila["id"],
            regla_id=fila["regla_id"],
            tipo=TipoAlarma(fila["tipo"]),
            severidad=Severidad(fila["severidad"]),
            estado=EstadoAlarma(fila["estado"]),
            olt_id=fila["olt_id"],
            entidad=fila["entidad"],
            entidad_id=fila["entidad_id"],
            mensaje=fila["mensaje"],
            valor=fila["valor"],
            abierta_en=a_fecha(fila["abierta_en"]),
            reconocida_en=a_fecha(fila["reconocida_en"]),
            reconocida_por=fila["reconocida_por"],
            resuelta_en=a_fecha(fila["resuelta_en"]),
        )

    def abrir(self, alarma: Alarma) -> Alarma:
        nuevo_id = self._db.ejecutar(
            """
            INSERT INTO alarmas (
                regla_id, tipo, severidad, estado, olt_id, entidad, entidad_id,
                mensaje, valor, abierta_en
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                alarma.regla_id,
                str(alarma.tipo),
                str(alarma.severidad),
                str(EstadoAlarma.ACTIVA),
                alarma.olt_id,
                alarma.entidad,
                alarma.entidad_id,
                alarma.mensaje,
                alarma.valor,
                a_texto(alarma.abierta_en) or a_texto(datetime.now(UTC)),
            ),
        )
        fila = self._db.consultar_uno("SELECT * FROM alarmas WHERE id = ?", (nuevo_id,))
        return self._a_modelo(fila)  # type: ignore[arg-type]

    def resolver(self, alarma_id: int, momento: datetime) -> None:
        self._db.ejecutar(
            "UPDATE alarmas SET estado = ?, resuelta_en = ? WHERE id = ?",
            (str(EstadoAlarma.RESUELTA), a_texto(momento), alarma_id),
        )

    def reconocer(self, alarma_id: int, usuario: str, momento: datetime) -> None:
        self._db.ejecutar(
            """
            UPDATE alarmas SET estado = ?, reconocida_en = ?, reconocida_por = ?
            WHERE id = ? AND estado = ?
            """,
            (
                str(EstadoAlarma.RECONOCIDA),
                a_texto(momento),
                usuario,
                alarma_id,
                str(EstadoAlarma.ACTIVA),
            ),
        )

    def listar_activas(self, olt_id: int | None = None) -> list[Alarma]:
        estados = (str(EstadoAlarma.ACTIVA), str(EstadoAlarma.RECONOCIDA))
        if olt_id is None:
            filas = self._db.consultar_todos(
                "SELECT * FROM alarmas WHERE estado IN (?,?) ORDER BY abierta_en DESC", estados
            )
        else:
            filas = self._db.consultar_todos(
                """
                SELECT * FROM alarmas WHERE estado IN (?,?) AND olt_id = ?
                ORDER BY abierta_en DESC
                """,
                (*estados, olt_id),
            )
        return [self._a_modelo(fila) for fila in filas]

    def buscar_activa(self, *, tipo: str, entidad: str, entidad_id: int) -> Alarma | None:
        """Evita duplicar una alarma que ya está abierta para la misma entidad."""
        fila = self._db.consultar_uno(
            """
            SELECT * FROM alarmas
            WHERE tipo = ? AND entidad = ? AND entidad_id = ? AND estado IN (?,?)
            ORDER BY abierta_en DESC
            """,
            (
                tipo,
                entidad,
                entidad_id,
                str(EstadoAlarma.ACTIVA),
                str(EstadoAlarma.RECONOCIDA),
            ),
        )
        return self._a_modelo(fila) if fila else None


class RepositorioOperacionSQL:
    """Auditoría de escrituras. Incluye las simuladas: también son intención."""

    def __init__(self, conexion: Conexion) -> None:
        self._db = conexion

    def _a_modelo(self, fila: dict[str, Any]) -> Operacion:
        ref = (
            RefONU(pon=fila["pon"], onu_id=fila["onu_id"])
            if fila["pon"] is not None and fila["onu_id"] is not None
            else None
        )
        comandos = tuple(fila["comandos"].split(SEPARADOR_COMANDOS)) if fila["comandos"] else ()
        return Operacion(
            id=fila["id"],
            tipo=TipoOperacion(fila["tipo"]),
            olt_id=fila["olt_id"],
            ref_onu=ref,
            usuario=fila["usuario"],
            ok=bool(fila["ok"]),
            simulado=bool(fila["simulado"]),
            comandos=comandos,
            salida=fila["salida"],
            error=fila["error"],
            duracion_ms=fila["duracion_ms"],
            ejecutada_en=a_fecha(fila["ejecutada_en"]),
        )

    def registrar(self, operacion: Operacion) -> Operacion:
        nuevo_id = self._db.ejecutar(
            """
            INSERT INTO operaciones (
                tipo, olt_id, pon, onu_id, usuario, ok, simulado,
                comandos, salida, error, duracion_ms, ejecutada_en
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                str(operacion.tipo),
                operacion.olt_id,
                operacion.ref_onu.pon if operacion.ref_onu else None,
                operacion.ref_onu.onu_id if operacion.ref_onu else None,
                operacion.usuario,
                int(operacion.ok),
                int(operacion.simulado),
                SEPARADOR_COMANDOS.join(operacion.comandos),
                operacion.salida,
                operacion.error,
                operacion.duracion_ms,
                a_texto(operacion.ejecutada_en) or a_texto(datetime.now(UTC)),
            ),
        )
        fila = self._db.consultar_uno("SELECT * FROM operaciones WHERE id = ?", (nuevo_id,))
        return self._a_modelo(fila)  # type: ignore[arg-type]

    def listar(
        self, *, olt_id: int | None = None, limite: int = 100, desplazamiento: int = 0
    ) -> list[Operacion]:
        if olt_id is None:
            filas = self._db.consultar_todos(
                """
                SELECT * FROM operaciones ORDER BY ejecutada_en DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                (limite, desplazamiento),
            )
        else:
            filas = self._db.consultar_todos(
                """
                SELECT * FROM operaciones WHERE olt_id = ?
                ORDER BY ejecutada_en DESC, id DESC LIMIT ? OFFSET ?
                """,
                (olt_id, limite, desplazamiento),
            )
        return [self._a_modelo(fila) for fila in filas]


class RepositorioSincronizacionSQL:
    """Corridas de sincronización, con su resultado completo o parcial."""

    def __init__(self, conexion: Conexion) -> None:
        self._db = conexion

    def _a_modelo(self, fila: dict[str, Any]) -> Sincronizacion:
        return Sincronizacion(
            id=fila["id"],
            olt_id=fila["olt_id"],
            nivel=NivelSincronizacion(fila["nivel"]),
            resultado=ResultadoSincronizacion(fila["resultado"]),
            onus_leidas=fila["onus_leidas"],
            onus_esperadas=fila["onus_esperadas"],
            eventos_generados=fila["eventos_generados"],
            detalle=fila["detalle"],
            iniciada_en=a_fecha(fila["iniciada_en"]),
            finalizada_en=a_fecha(fila["finalizada_en"]),
            duracion_ms=fila["duracion_ms"],
        )

    def registrar(self, sincronizacion: Sincronizacion) -> Sincronizacion:
        nuevo_id = self._db.ejecutar(
            """
            INSERT INTO sincronizaciones (
                olt_id, nivel, resultado, onus_leidas, onus_esperadas,
                eventos_generados, detalle, iniciada_en, finalizada_en, duracion_ms
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                sincronizacion.olt_id,
                str(sincronizacion.nivel),
                str(sincronizacion.resultado),
                sincronizacion.onus_leidas,
                sincronizacion.onus_esperadas,
                sincronizacion.eventos_generados,
                sincronizacion.detalle,
                a_texto(sincronizacion.iniciada_en) or a_texto(datetime.now(UTC)),
                a_texto(sincronizacion.finalizada_en),
                sincronizacion.duracion_ms,
            ),
        )
        fila = self._db.consultar_uno("SELECT * FROM sincronizaciones WHERE id = ?", (nuevo_id,))
        return self._a_modelo(fila)  # type: ignore[arg-type]

    def ultima_de_olt(self, olt_id: int) -> Sincronizacion | None:
        fila = self._db.consultar_uno(
            """
            SELECT * FROM sincronizaciones WHERE olt_id = ?
            ORDER BY iniciada_en DESC, id DESC
            """,
            (olt_id,),
        )
        return self._a_modelo(fila) if fila else None

    def listar(self, *, olt_id: int | None = None, limite: int = 50) -> list[Sincronizacion]:
        if olt_id is None:
            filas = self._db.consultar_todos(
                "SELECT * FROM sincronizaciones ORDER BY iniciada_en DESC, id DESC LIMIT ?",
                (limite,),
            )
        else:
            filas = self._db.consultar_todos(
                """
                SELECT * FROM sincronizaciones WHERE olt_id = ?
                ORDER BY iniciada_en DESC, id DESC LIMIT ?
                """,
                (olt_id, limite),
            )
        return [self._a_modelo(fila) for fila in filas]


__all__ = [
    "RepositorioAlarmaSQL",
    "RepositorioEventoSQL",
    "RepositorioMetricaSQL",
    "RepositorioOperacionSQL",
    "RepositorioSincronizacionSQL",
]
