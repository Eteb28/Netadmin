"""Pruebas de caracterización: la misma consulta, los dos motores, el mismo resultado.

Fase 7, paso 1. Es la prueba que hacía falta antes de tocar nada: sin ella, la
fase 8 se hace a ciegas y una consulta que en PostgreSQL devuelve algo distinto
—no que falla, que devuelve OTRA COSA— no se descubre hasta que un cliente
llama.

Se saltea si no hay `PUCARA_TEST_PG_URL`, así la suite sigue corriendo en
cualquier máquina. Para ejecutarla:

    export PUCARA_TEST_PG_URL="postgresql+psycopg2://pucara@127.0.0.1:5432/pucara_test"
    python3 -m pytest tests/test_paridad_motores.py -q

Los casos no son inventados: reproducen las trampas concretas del padrón real
—`nro_cliente` con espacios, fechas vacías, `fecha_rescision` nula con
`fecha_baja` cargada— que son las que hacen que una migración "que anduvo"
devuelva números distintos.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, insert
from sqlalchemy.orm import sessionmaker

from pucara.models.legado import BaseLegado, Cliente, Olt, OnuSenal, OnuSenalHist
from pucara.repositories.clientes import ClienteAnaliticaRepository
from pucara.repositories.optica import OpticaRepository
from pucara.services.degradacion import ServicioDegradacion
from tests.motores import solo_postgres, url_postgres

# --- Datos idénticos para los dos motores -----------------------------------

OLTS = [{"id": 1, "nombre": "Puerto Sánchez"}, {"id": 2, "nombre": "Alcaín"}]

CLIENTES = [
    # nro_cliente con espacios: existe así en producción y el cruce contra
    # onu_senal se hace con TRIM en los dos lados.
    {"id": 1, "nombre": "Ana", "nro_cliente": " 1001 ", "estado": "activo",
     "tipo_servicio": "fibra", "fecha_alta": "2022-01-15"},
    {"id": 2, "nombre": "Beto", "nro_cliente": "1002", "estado": "rescision",
     "tipo_servicio": "fibra", "fecha_alta": "2023-06-01", "fecha_rescision": "2026-05-01"},
    # Pendiente de rescisión con fecha_baja y sin fecha_rescision: el COALESCE
    # tiene que tomar la que exista.
    {"id": 3, "nombre": "Cora", "nro_cliente": "1003", "estado": "pte_rescision",
     "tipo_servicio": "fibra", "fecha_alta": "2024-02-20", "fecha_baja": "2026-07-10"},
    # fecha_alta vacía: SQLite la acepta, y el repositorio la filtra antes de
    # que PostgreSQL tenga que opinar.
    {"id": 4, "nombre": "Dani", "nro_cliente": "1004", "estado": "activo",
     "tipo_servicio": "fibra", "fecha_alta": "   "},
    # Fecha con hora pegada: se recorta a los 10 primeros caracteres.
    {"id": 5, "nombre": "Eli", "nro_cliente": "1005", "estado": "baja",
     "tipo_servicio": "fibra", "fecha_alta": "2021-11-03 08:30:00",
     "fecha_baja": "2026-01-09"},
    # Inalámbrico: no debe aparecer en la antigüedad de fibra.
    {"id": 6, "nombre": "Fabi", "nro_cliente": "1006", "estado": "activo",
     "tipo_servicio": "inalambrico", "fecha_alta": "2020-05-05"},
]

ONUS = [
    {"olt_id": 1, "pon": 1, "onu": 10, "nro_cliente": "1001", "serial_onu": "VSOL01",
     "rx_power": -21.4, "online": 1, "last_check": "2026-08-27 09:00"},
    {"olt_id": 1, "pon": 1, "onu": 11, "nro_cliente": "1002", "serial_onu": "VSOL02",
     "rx_power": -25.9, "online": 1, "last_check": "2026-08-27 09:00"},
    {"olt_id": 1, "pon": 3, "onu": 12, "nro_cliente": "1003", "serial_onu": "VSOL03",
     "rx_power": -28.7, "online": 1, "last_check": "2026-08-27 09:00"},
    {"olt_id": 2, "pon": 5, "onu": 13, "nro_cliente": "1005", "serial_onu": "VSOL04",
     "rx_power": -30.2, "online": 0, "last_check": "2026-08-27 09:00"},
    # Sin cliente asociado: el LEFT JOIN tiene que devolverla igual.
    {"olt_id": 2, "pon": 5, "onu": 14, "nro_cliente": "9999", "serial_onu": "VSOL05",
     "rx_power": -6.1, "online": 1, "last_check": "2026-08-27 09:00"},
]

HIST = [
    {"olt_id": 1, "pon": 1, "onu": 11, "rx_power": v, "fecha": f"2026-08-{d:02d}"}
    for d, v in enumerate([-21.2, -21.4, -21.1, -21.3, -21.5, -21.2, -25.9], start=15)
]


def _cargar(sesion) -> None:
    sesion.execute(insert(Olt), OLTS)
    sesion.execute(insert(Cliente), [
        {**{"fecha_baja": None, "fecha_rescision": None}, **c} for c in CLIENTES
    ])
    sesion.execute(insert(OnuSenal), ONUS)
    sesion.execute(insert(OnuSenalHist), HIST)
    sesion.commit()


def _sesion(url: str, tmp_path=None):
    eng = create_engine(url, future=True)
    if url.startswith("postgresql"):
        from sqlalchemy import text
        with eng.connect() as c:
            c.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            c.execute(text("CREATE SCHEMA public"))
            c.commit()
    BaseLegado.metadata.create_all(eng)
    s = sessionmaker(bind=eng, expire_on_commit=False, future=True)()
    _cargar(s)
    return s, eng


def _radiografia(s) -> dict:
    """Todo lo que el código nuevo le pregunta a las tablas heredadas.

    Se comparan valores, no cantidades: dos motores pueden coincidir en el
    total y diferir en el orden o en un redondeo, y eso ya es un cambio de
    comportamiento para el que mira la pantalla.
    """
    cli, opt = ClienteAnaliticaRepository(s), OpticaRepository(s)
    deg = ServicioDegradacion(opt).analizar()
    return {
        "antiguedad": [
            (c.id, c.nombre, str(c.fecha_alta), str(c.fecha_baja), c.estado, c.meses)
            for c in cli.clientes_con_antiguedad()
        ],
        "nombres": cli.nombres([1, 2, 3, 99]),
        "olts": cli.nombres_olts(),
        "bajas": [
            (o.cliente_id, o.nombre, o.olt_nombre, o.pon, o.onu, o.serial,
             o.fecha_estado, o.dias_desde_cambio, o.online)
            for o in cli.onus_de_clientes_a_dar_de_baja()
        ],
        "lecturas": [
            (l.olt_id, l.olt_nombre, l.pon, l.onu, l.nro_cliente,
             l.cliente_nombre, l.cliente_id, l.rx, l.online)
            for l in opt.lecturas_actuales()
        ],
        "historico": {k: v for k, v in sorted(opt.historico_rx(3650).items())},
        "ocupacion": [
            (o.olt_id, o.olt_nombre, o.pon, o.onus, o.online)
            for o in opt.ocupacion_por_pon()
        ],
        "degradacion": (
            deg.total_onus, deg.online, deg.offline, deg.saturadas,
            round(deg.rx_promedio, 6) if deg.rx_promedio is not None else None,
            [(c.pon, c.onu, c.severidad, c.motivo, round(c.caida_db or 0, 6))
             for c in deg.en_riesgo],
        ),
    }


@pytest.fixture(scope="module")
def radiografias(tmp_path_factory):
    s_lite, e_lite = _sesion(f"sqlite:///{tmp_path_factory.mktemp('par')/'t.db'}")
    lite = _radiografia(s_lite)
    s_lite.close(); e_lite.dispose()

    s_pg, e_pg = _sesion(url_postgres())
    pg = _radiografia(s_pg)
    s_pg.close(); e_pg.dispose()
    return lite, pg


@solo_postgres
@pytest.mark.parametrize("clave", [
    "antiguedad", "nombres", "olts", "bajas", "lecturas", "historico",
    "ocupacion", "degradacion",
])
def test_los_dos_motores_devuelven_lo_mismo(radiografias, clave):
    lite, pg = radiografias
    assert lite[clave] == pg[clave], (
        f"`{clave}` cambia al migrar de motor.\n"
        f"  SQLite:     {lite[clave]}\n"
        f"  PostgreSQL: {pg[clave]}"
    )


@solo_postgres
def test_el_cruce_por_nro_cliente_con_espacios_funciona_en_los_dos(radiografias):
    """`TRIM` en ambos lados. Sin él, PostgreSQL no encuentra ' 1001 ' y el
    cliente aparecería sin nombre en toda la vista de señal."""
    for radiografia in radiografias:
        por_onu = {(l[2], l[3]): l[5] for l in radiografia["lecturas"]}
        assert por_onu[(1, 10)] == "Ana"


@solo_postgres
def test_una_onu_sin_cliente_no_desaparece(radiografias):
    """Es un LEFT JOIN: la ONU huérfana tiene que salir igual, con nombre nulo.
    Justamente esas son las que hay que investigar."""
    for radiografia in radiografias:
        huerfanas = [l for l in radiografia["lecturas"] if l[6] is None]
        assert len(huerfanas) == 1 and huerfanas[0][4] == "9999"
