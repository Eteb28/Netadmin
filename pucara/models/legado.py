"""Modelos de las tablas HEREDADAS que el código nuevo necesita leer.

Fase 7, paso 2. Estas tablas las crea y las mantiene `app.py` (`init_db()` y
`_migrate_columns()`); acá sólo se las **describe** para poder consultarlas con
SQLAlchemy en vez de con SQL en texto plano.

## Por qué una metadata aparte

Viven en `MetaData` propia, NO en `pucara.db.Base`, por una razón concreta de
seguridad operativa: `migrations/env.py` ignora toda tabla que no esté en
`Base.metadata`. Si estos modelos entraran ahí, el próximo
`alembic revision --autogenerate` propondría crear —y peor, alterar— las tablas
del sistema en producción a imagen de estas definiciones, que son parciales a
propósito. **Alembic no debe administrar nada de lo que ya administra app.py.**
`tests/test_convivencia_legado.py` lo verifica.

## Qué se declara y qué no

Sólo las columnas que el código nuevo lee o escribe. No es el esquema completo
de Pucará ni pretende serlo: declarar de más rompería contra una base real que
todavía no tenga esa columna.

## Para qué sirve además

Antes, cada archivo de pruebas escribía su propio `CREATE TABLE naps(...)` a
mano. Esas copias se desincronizaban: así fue como `naps.nivel_senal`, `red`,
`cdo`, `nap_numero` y `sitio` estuvieron en uso durante meses sin que
`init_db()` las creara, y las pruebas seguían en verde porque su DDL de juguete
tampoco las tenía. Ahora hay **una sola** declaración y las pruebas la usan.
"""
from __future__ import annotations

from sqlalchemy import Float, Integer, MetaData, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class BaseLegado(DeclarativeBase):
    """Base separada: Alembic no la mira. Ver el encabezado del módulo."""

    metadata = MetaData()


class Cliente(BaseLegado):
    """Padrón. `nro_cliente` es la clave con la que se cruza contra la OLT.

    Ojo: en producción `nro_cliente` viene con espacios en algunos registros;
    todo cruce contra `onu_senal` tiene que aplicar `TRIM` en ambos lados.
    """

    __tablename__ = "clientes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nombre: Mapped[str] = mapped_column(Text, nullable=False)
    nro_cliente: Mapped[str | None] = mapped_column(Text)
    estado: Mapped[str | None] = mapped_column(Text)
    tipo_servicio: Mapped[str | None] = mapped_column(Text)
    plan: Mapped[str | None] = mapped_column(Text)
    precio: Mapped[float | None] = mapped_column(Float)
    nap: Mapped[str | None] = mapped_column(Text)
    torre_id: Mapped[int | None] = mapped_column(Integer)
    ap_nombre: Mapped[str | None] = mapped_column(Text)
    olt_nombre: Mapped[str | None] = mapped_column(Text)
    olt_puerto: Mapped[str | None] = mapped_column(Text)
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    localidad: Mapped[str | None] = mapped_column(Text)
    # Fechas guardadas como TEXTO 'AAAA-MM-DD'. No se tipan como Date a
    # propósito: la base real tiene valores vacíos y con hora pegada, y
    # PostgreSQL —que sí valida— rechazaría la lectura entera. La conversión
    # se hace en Python (ver `_a_fecha`). Limpiarlas es trabajo de la fase 8
    # (riesgo R1 de PREPARACION-FASES-7-8).
    fecha_alta: Mapped[str | None] = mapped_column(Text)
    fecha_suspension: Mapped[str | None] = mapped_column(Text)
    fecha_rescision: Mapped[str | None] = mapped_column(Text)
    fecha_baja: Mapped[str | None] = mapped_column(Text)


class Olt(BaseLegado):
    __tablename__ = "olts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nombre: Mapped[str] = mapped_column(Text, nullable=False)
    ip_remota: Mapped[str | None] = mapped_column(Text)
    puertos_pon: Mapped[int | None] = mapped_column(Integer)
    activa: Mapped[int | None] = mapped_column(Integer)


class Nap(BaseLegado):
    """Caja de distribución de fibra.

    Las cinco últimas columnas son las que faltaban en `init_db()`: se declaran
    acá para que no vuelva a haber una definición de juguete distinta en cada
    archivo de pruebas.
    """

    __tablename__ = "naps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nombre: Mapped[str] = mapped_column(Text, nullable=False)
    descripcion: Mapped[str | None] = mapped_column(Text)
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    capacidad: Mapped[int | None] = mapped_column(Integer)
    localidad: Mapped[str | None] = mapped_column(Text)
    estado: Mapped[str | None] = mapped_column(Text)
    nivel_senal: Mapped[float | None] = mapped_column(Float)
    red: Mapped[str | None] = mapped_column(Text)
    cdo: Mapped[str | None] = mapped_column(Text)
    nap_numero: Mapped[int | None] = mapped_column(Integer)
    sitio: Mapped[str | None] = mapped_column(Text)


class OnuSenal(BaseLegado):
    """Última lectura conocida de cada ONU. La pisa el poller en cada pasada."""

    __tablename__ = "onu_senal"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    olt_id: Mapped[int | None] = mapped_column(Integer)
    pon: Mapped[int | None] = mapped_column(Integer)
    onu: Mapped[int | None] = mapped_column(Integer)
    nro_cliente: Mapped[str | None] = mapped_column(Text)
    serial_onu: Mapped[str | None] = mapped_column(Text)
    rx_power: Mapped[float | None] = mapped_column(Float)
    tx_power: Mapped[float | None] = mapped_column(Float)
    temperatura: Mapped[float | None] = mapped_column(Float)
    # 0/1 y no Boolean: así está en producción. Tiparlo como booleano es parte
    # de la fase 8 y hay que hacerlo junto con las comparaciones `= 1`.
    online: Mapped[int | None] = mapped_column(Integer)
    last_check: Mapped[str | None] = mapped_column(Text)


class OnuSenalHist(BaseLegado):
    """Histórico de señal. Es la tabla grande: se copia antes del corte."""

    __tablename__ = "onu_senal_hist"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nro_cliente: Mapped[str | None] = mapped_column(Text)
    olt_id: Mapped[int | None] = mapped_column(Integer)
    pon: Mapped[int | None] = mapped_column(Integer)
    onu: Mapped[int | None] = mapped_column(Integer)
    rx_power: Mapped[float | None] = mapped_column(Float)
    tx_power: Mapped[float | None] = mapped_column(Float)
    temperatura: Mapped[float | None] = mapped_column(Float)
    fecha: Mapped[str | None] = mapped_column(Text)


class Historial(BaseLegado):
    """Bitácora de la aplicación. Es donde escribe la auditoría de cambios."""

    __tablename__ = "historial"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tipo: Mapped[str | None] = mapped_column(Text)
    modulo: Mapped[str | None] = mapped_column(Text)
    titulo: Mapped[str | None] = mapped_column(Text)
    detalle: Mapped[str | None] = mapped_column(Text)
    diff: Mapped[str | None] = mapped_column(Text)
    usuario: Mapped[str | None] = mapped_column(Text)
    fecha: Mapped[str | None] = mapped_column(Text)


class TareaUsuario(BaseLegado):
    """Notas de "Mis Tareas". Los adjuntos cuelgan de acá."""

    __tablename__ = "tareas_usuario"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(Text, nullable=False)
    texto: Mapped[str | None] = mapped_column(Text)
    completada: Mapped[int | None] = mapped_column(Integer)


#: Tablas heredadas que las pruebas necesitan crear. Se exporta como lista
#: explícita para que agregar un modelo acá sea una decisión visible.
TABLAS_LEGADAS = (
    Cliente.__table__, Olt.__table__, Nap.__table__, OnuSenal.__table__,
    OnuSenalHist.__table__, Historial.__table__, TareaUsuario.__table__,
)


def crear_esquema_legado(engine) -> None:
    """Crea las tablas heredadas. **Sólo para pruebas y entornos de prueba.**

    En producción las crea `app.py`. Existe para que las pruebas dejen de
    escribir DDL a mano y no se repita la desincronización que ocultó las cinco
    columnas faltantes de `naps`.
    """
    BaseLegado.metadata.create_all(engine)
