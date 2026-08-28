"""Pruebas de antigüedad y churn (fase 5) y del listado de bajas (fase 6)."""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import insert

from pucara.models.legado import Cliente, Olt, OnuSenal
from pucara.repositories.clientes import ClienteAnaliticaRepository
from pucara.services.antiguedad import ServicioAntiguedad


@pytest.fixture()
def base_clientes(sesion):
    """Las tablas heredadas ya vienen creadas desde `pucara.models.legado`;
    acá sólo se carga el dato mínimo que necesitan estas pruebas."""
    sesion.execute(insert(Olt).values(id=1, nombre="OLT Centro"))
    sesion.commit()
    return sesion


def alta(sesion, cid, meses_atras, estado="activo", baja_meses=None, nro=None):
    f_alta = date.today() - timedelta(days=int(meses_atras * 30.44))
    f_baja = (date.today() - timedelta(days=int(baja_meses * 30.44))) if baja_meses else None
    sesion.execute(insert(Cliente).values(
        id=cid, nombre=f"Cliente {cid}", nro_cliente=nro or str(cid),
        estado=estado, tipo_servicio="fibra", fecha_alta=f_alta.isoformat(),
        fecha_baja=f_baja.isoformat() if f_baja else None))


class TestAntiguedad:
    def test_sin_clientes(self, base_clientes):
        e = ServicioAntiguedad(ClienteAnaliticaRepository(base_clientes)).calcular()
        assert e.total_activos == 0
        assert e.permanencia_media_meses is None

    def test_distribuye_por_tramos(self, base_clientes):
        alta(base_clientes, 1, 1)      # 0-3
        alta(base_clientes, 2, 4)      # 3-6
        alta(base_clientes, 3, 9)      # 6-12
        alta(base_clientes, 4, 18)     # 12-24
        alta(base_clientes, 5, 40)     # +24
        base_clientes.commit()

        e = ServicioAntiguedad(ClienteAnaliticaRepository(base_clientes)).calcular()
        assert e.total_activos == 5
        assert dict(e.distribucion_activos)["0-3 meses"] == 1
        assert dict(e.distribucion_activos)["Más de 24 meses"] == 1

    def test_separa_activos_de_bajas(self, base_clientes):
        alta(base_clientes, 1, 10)
        alta(base_clientes, 2, 20, estado="baja", baja_meses=2)
        base_clientes.commit()

        e = ServicioAntiguedad(ClienteAnaliticaRepository(base_clientes)).calcular()
        assert e.total_activos == 1
        assert e.total_bajas == 1

    def test_la_permanencia_de_la_baja_se_corta_en_la_fecha_de_baja(self, base_clientes):
        """Un cliente de alta hace 20 meses que se fue hace 2 permaneció 18,
        no 20. Si se midiera hasta hoy, la permanencia estaría inflada."""
        alta(base_clientes, 1, 20, estado="baja", baja_meses=2)
        base_clientes.commit()

        e = ServicioAntiguedad(ClienteAnaliticaRepository(base_clientes)).calcular()
        assert 17 <= e.permanencia_media_bajas_meses <= 19

    def test_churn_anual(self, base_clientes):
        for i in range(1, 10):
            alta(base_clientes, i, 12)
        alta(base_clientes, 99, 12, estado="baja", baja_meses=1)
        base_clientes.commit()

        e = ServicioAntiguedad(ClienteAnaliticaRepository(base_clientes)).calcular()
        assert e.churn_anual == 10.0        # 1 de 10


class TestPendientesDeBaja:
    def test_lista_rescindidos_y_pendientes(self, base_clientes):
        alta(base_clientes, 1, 12, estado="rescision", nro="1001")
        alta(base_clientes, 2, 12, estado="pte_rescision", nro="1002")
        alta(base_clientes, 3, 12, estado="activo", nro="1003")   # no debe salir
        base_clientes.execute(insert(OnuSenal), [
            {"olt_id": 1, "pon": pon, "onu": 10, "nro_cliente": nro,
             "serial_onu": f"SN{nro}"}
            for nro, pon in (("1001", 1), ("1002", 2), ("1003", 3))
        ])
        base_clientes.commit()

        filas = ClienteAnaliticaRepository(base_clientes).onus_de_clientes_a_dar_de_baja()
        estados = {f.estado_comercial for f in filas}
        assert estados == {"rescision", "pte_rescision"}
        assert len(filas) == 2
        assert all(f.serial for f in filas)
        assert all(f.olt_nombre == "OLT Centro" for f in filas)


def onu(sesion, nro, pon=1, onu_id=10, olt=1, online=1):
    sesion.execute(insert(OnuSenal).values(
        olt_id=olt, pon=pon, onu=onu_id, nro_cliente=nro, serial_onu=f"SN{nro}",
        online=online, last_check="2026-08-06 10:00"))


def con_baja(sesion, cid, nro, estado, dias_atras):
    """Cliente en estado de baja con fecha de rescisión hace N días."""
    f = (date.today() - timedelta(days=dias_atras)).isoformat()
    sesion.execute(insert(Cliente).values(
        id=cid, nombre=f"Cliente {cid}", nro_cliente=nro, estado=estado,
        tipo_servicio="fibra", fecha_alta="2020-01-01", fecha_rescision=f))


class TestServicioRescisiones:
    """Fase 6. El servicio ordena, filtra y resume; nunca escribe."""

    @pytest.fixture()
    def srv(self, base_clientes):
        from pucara.services.rescisiones import ServicioRescisiones
        con_baja(base_clientes, 1, "1001", "rescision", 200)      # antigua
        con_baja(base_clientes, 2, "1002", "pte_rescision", 5)    # en trámite
        con_baja(base_clientes, 3, "1003", "baja", 95)            # antigua
        onu(base_clientes, "1001", pon=1)
        onu(base_clientes, "1002", pon=2, online=0)
        onu(base_clientes, "1003", pon=3)
        base_clientes.commit()
        return ServicioRescisiones(ClienteAnaliticaRepository(base_clientes))

    def test_ordena_lo_mas_viejo_primero(self, srv):
        """Lo que más tiempo lleva ocupando un puerto es lo que hay que mirar."""
        dias = [f.dias_desde_cambio for f in srv.listar()]
        assert dias == sorted(dias, reverse=True)
        assert dias[0] == 200

    def test_marca_en_tramite_y_antigua(self, srv):
        por_nro = {f.nro_cliente: f for f in srv.listar()}
        assert por_nro["1002"].en_tramite is True
        assert por_nro["1002"].antigua is False       # 5 días
        assert por_nro["1001"].en_tramite is False
        assert por_nro["1003"].antigua is True        # 95 >= 90

    def test_ubicacion_legible(self, srv):
        por_nro = {f.nro_cliente: f for f in srv.listar()}
        assert por_nro["1001"].ubicacion == "OLT Centro · GPON0/1:10"

    def test_filtra_por_estado_y_antiguedad(self, srv):
        assert len(srv.listar(estado="pte_rescision")) == 1
        assert len(srv.listar(dias_minimos=90)) == 2
        assert len(srv.listar(olt_id=99)) == 0

    def test_resumen(self, srv):
        r = srv.resumen()
        assert r.total == 3
        assert r.en_tramite == 1
        assert r.confirmadas == 2
        assert r.online == 2          # la 1002 está caída
        assert r.antiguas == 2
        assert r.por_olt == [("OLT Centro", 3)]

    def test_el_resumen_acepta_las_filas_ya_filtradas(self, srv):
        """Para no golpear la base dos veces al pintar la pantalla."""
        filas = srv.listar(estado="rescision")
        assert srv.resumen(filas).total == 1
