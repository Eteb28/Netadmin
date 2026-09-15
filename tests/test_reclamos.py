"""Pruebas del dominio Reclamos (fases 2 y 3)."""
from __future__ import annotations

from datetime import timedelta

import pytest

from pucara.models.reclamos import EstadoReclamo, ahora
from pucara.services.reclamos import ErrorReclamo


class TestRegistro:
    def test_registrar_deja_el_reclamo_abierto(self, servicio, catalogos):
        r = servicio.registrar(cliente_id=1, usuario="admin", causa_id=catalogos["c1"].id)
        assert r.estado == EstadoReclamo.ABIERTO.value
        assert r.fecha_cierre is None
        assert r.minutos_resolucion is None

    def test_rechaza_causa_inexistente(self, servicio):
        with pytest.raises(ErrorReclamo, match="no existe"):
            servicio.registrar(cliente_id=1, usuario="admin", causa_id=9999)

    def test_exige_usuario(self, servicio):
        with pytest.raises(ErrorReclamo, match="usuario"):
            servicio.registrar(cliente_id=1, usuario="")

    def test_copia_el_contexto_de_red(self, servicio):
        """El AP/PON se guarda copiado: si el cliente se muda, el reclamo debe
        seguir contando contra el equipo que falló."""
        r = servicio.registrar(
            cliente_id=1, usuario="admin",
            contexto_red={"ap_nombre": "AP-Norte", "olt_id": 3, "pon": 5},
        )
        assert r.ap_nombre == "AP-Norte"
        assert r.pon == 5


class TestCierre:
    def test_cerrar_calcula_la_duracion(self, servicio, catalogos, sesion):
        r = servicio.registrar(cliente_id=1, usuario="admin")
        # Simulamos que se abrió hace 30 minutos
        from pucara.models.reclamos import Reclamo
        modelo = sesion.get(Reclamo, r.id)
        modelo.fecha_alta = ahora() - timedelta(minutes=30)
        sesion.flush()

        cerrado = servicio.cerrar(r.id, usuario="tecnico", resolucion_id=catalogos["r1"].id)
        assert cerrado.estado == EstadoReclamo.CERRADO.value
        assert 29 <= cerrado.minutos_resolucion <= 31
        assert cerrado.resolucion == "Reinicio ONU"

    def test_no_permite_cerrar_dos_veces(self, servicio):
        r = servicio.registrar(cliente_id=1, usuario="admin")
        servicio.cerrar(r.id, usuario="tecnico")
        with pytest.raises(ErrorReclamo, match="ya está"):
            servicio.cerrar(r.id, usuario="tecnico")

    def test_rechaza_reclamo_inexistente(self, servicio):
        with pytest.raises(ErrorReclamo, match="no existe"):
            servicio.cerrar(9999, usuario="tecnico")


class TestEstadisticasCliente:
    def test_cliente_sin_reclamos(self, servicio):
        e = servicio.estadisticas_cliente(cliente_id=42)
        assert e.total == 0
        assert e.mttr_minutos is None
        assert e.mtbf_dias is None

    def test_mtbf_none_con_un_solo_reclamo(self, servicio):
        """Con un reclamo no hay intervalo: debe ser None, NUNCA 0.
        Un 0 se leería como 'falla continuamente'."""
        servicio.registrar(cliente_id=1, usuario="admin")
        e = servicio.estadisticas_cliente(cliente_id=1)
        assert e.total == 1
        assert e.mtbf_dias is None

    def test_mtbf_con_varios_reclamos(self, servicio, sesion):
        from pucara.models.reclamos import Reclamo
        base = ahora() - timedelta(days=30)
        for i in range(3):                       # separados 10 días
            r = servicio.registrar(cliente_id=7, usuario="admin")
            sesion.get(Reclamo, r.id).fecha_alta = base + timedelta(days=10 * i)
        sesion.flush()

        e = servicio.estadisticas_cliente(cliente_id=7)
        assert e.total == 3
        assert 9.5 <= e.mtbf_dias <= 10.5

    def test_agrupa_por_causa(self, servicio, catalogos):
        for _ in range(3):
            servicio.registrar(cliente_id=5, usuario="a", causa_id=catalogos["c1"].id)
        servicio.registrar(cliente_id=5, usuario="a", causa_id=catalogos["c2"].id)

        e = servicio.estadisticas_cliente(cliente_id=5)
        assert e.total == 4
        assert e.por_causa[0] == ("Sin servicio", 3)   # ordenado por frecuencia

    def test_los_abiertos_no_cuentan_en_el_mttr(self, servicio, sesion):
        """Un reclamo abierto no tiene duración: no debe bajar el promedio."""
        from pucara.models.reclamos import Reclamo
        r1 = servicio.registrar(cliente_id=9, usuario="a")
        sesion.get(Reclamo, r1.id).fecha_alta = ahora() - timedelta(minutes=60)
        sesion.flush()
        servicio.cerrar(r1.id, usuario="t")
        servicio.registrar(cliente_id=9, usuario="a")     # queda abierto

        e = servicio.estadisticas_cliente(cliente_id=9)
        assert e.total == 2
        assert e.abiertos == 1
        assert 59 <= e.mttr_minutos <= 61                 # sólo el cerrado


class TestCatalogos:
    def test_baja_logica_conserva_el_historico(self, servicio, catalogos, sesion):
        """Desactivar una causa no debe romper los reclamos que la usan."""
        r = servicio.registrar(cliente_id=1, usuario="a", causa_id=catalogos["c1"].id)
        catalogos["causas"].desactivar(catalogos["c1"].id)
        sesion.flush()

        assert catalogos["c1"].id not in [c.id for c in catalogos["causas"].listar()]
        historial = servicio.historial(cliente_id=1)
        assert historial[0].causa == "Sin servicio"      # sigue visible

    def test_listar_excluye_inactivos_por_defecto(self, catalogos, sesion):
        catalogos["causas"].desactivar(catalogos["c2"].id)
        sesion.flush()
        assert len(catalogos["causas"].listar()) == 1
        assert len(catalogos["causas"].listar(incluir_inactivos=True)) == 2
