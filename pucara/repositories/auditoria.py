"""Escritura en el historial de auditoría.

**Va por la misma sesión que la operación auditada, a propósito.**

El primer intento fue inyectar la función `log()` de `app.py` como callback,
igual que se hace con el autorizador (ADR-0004). No funciona: `log()` abre su
propia conexión sqlite3, y llamarla desde adentro de un `with sesion()` que ya
tiene una escritura pendiente da `database is locked`. El `except: pass` que
tiene `log()` se comía el error, así que la operación parecía exitosa y el
registro de auditoría simplemente no existía.

Escribir por la sesión compartida resuelve las dos cosas: no hay dos escritores
sobre el mismo archivo, y el registro **entra en la misma transacción** que el
cambio — si el cambio se revierte, la constancia también.

`historial` la sigue creando `app.py`, pero está descrita en
`pucara.models.legado`: las sentencias se arman con SQLAlchemy y no con texto.
"""
from __future__ import annotations

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from pucara.models.legado import Historial


class AuditoriaRepository:
    def __init__(self, sesion: Session) -> None:
        self._s = sesion

    def registrar(
        self, tipo: str, modulo: str, titulo: str,
        detalle: str = "", usuario: str = "sistema", diff: str | None = None,
    ) -> None:
        # `fecha` se deja al DEFAULT de la tabla, que es el mismo que usa el
        # resto de la aplicación: poner la hora desde acá haría que los
        # registros del código nuevo tuvieran otro formato que los del viejo.
        self._s.execute(
            insert(Historial).values(
                tipo=tipo, modulo=modulo, titulo=titulo,
                detalle=detalle, usuario=usuario, diff=diff,
            )
        )

    def registrar_cambio(
        self, modulo: str, entidad: str, entidad_id, diferencia,
        usuario: str = "sistema",
    ) -> bool:
        """Registra un cambio con el antes y el después de cada campo.

        Devuelve False y no escribe nada si no cambió nada: guardar un
        formulario sin tocarlo no es un evento auditable, y llenar el historial
        de ruido es la forma más segura de que nadie lo mire.
        """
        if not diferencia.hubo_cambios:
            return False
        self.registrar(
            tipo="mod",
            modulo=modulo,
            titulo=f"{entidad} #{entidad_id}: {diferencia.resumen()}",
            detalle="\n".join(str(c) for c in diferencia.cambios),
            usuario=usuario,
            diff=diferencia.a_json(),
        )
        return True

    def historial_de(self, modulo: str, entidad_id, limite: int = 50) -> list[dict]:
        """Cambios de una entidad concreta, del más reciente al más viejo."""
        filas = self._s.execute(
            select(
                Historial.id, Historial.tipo, Historial.titulo, Historial.detalle,
                Historial.diff, Historial.usuario, Historial.fecha,
            )
            .where(
                Historial.modulo == modulo,
                # El id va entre `#` y `:` para no confundir la NAP 1 con la 12.
                Historial.titulo.like(f"%#{entidad_id}:%"),
            )
            .order_by(Historial.id.desc())
            .limit(limite)
        ).mappings().all()
        return [dict(f) for f in filas]
