"""carga inicial de catalogos de reclamos

Migración de DATOS, no de esquema. Deja el sistema usable desde el minuto uno
sin que nadie tenga que tipear 34 opciones a mano.

Revision ID: c1a7f2d40b11
Revises: bb679c46b4e6
Create Date: 2026-08-06

"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy.orm import Session

from pucara.seeds import sembrar

# revision identifiers, used by Alembic.
revision: str = 'c1a7f2d40b11'
down_revision: Union[str, Sequence[str], None] = 'bb679c46b4e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with Session(bind=op.get_bind()) as s:
        sembrar(s)
        s.commit()


def downgrade() -> None:
    """A propósito, no borra nada.

    Bajar una revisión de esquema es reversible; borrar filas de catálogo no lo
    es, porque para entonces puede haber reclamos históricos apuntando a ellas.
    La revisión anterior elimina las tablas enteras de todos modos.
    """
