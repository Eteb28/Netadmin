"""Reubicación de NAPs desde el mapa."""
from __future__ import annotations

import pytest
from sqlalchemy import insert, text
from sqlalchemy.orm import sessionmaker

from pucara.models.legado import Nap
from pucara.repositories.auditoria import AuditoriaRepository
from pucara.repositories.naps import NapRepository
from pucara.services.ubicaciones import (
    ErrorUbicacion, NapInexistente, ServicioUbicacionNap,
)
from tests.motores import crear_esquema, motor

# Coordenadas reales de la zona de operación (Paraná, Entre Ríos)
PARANA = (-31.7346, -60.5289)


@pytest.fixture()
def sesion_naps():
    engine = motor()
    crear_esquema(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False, future=True)()
    s.execute(insert(Nap), [
        {"id": 1, "nombre": "PROCREAR - CDO 21 - NAP 6", "lat": -31.7000, "lng": -60.5000},
        {"id": 2, "nombre": "SIN COORDENADAS - CDO 1 - NAP 1", "lat": None, "lng": None},
    ])
    s.commit()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


@pytest.fixture()
def srv(sesion_naps):
    return ServicioUbicacionNap(NapRepository(sesion_naps), AuditoriaRepository(sesion_naps))


def _historial(s):
    return s.execute(
        text("SELECT tipo, modulo, titulo, detalle, usuario FROM historial ORDER BY id")
    ).all()


class TestMover:
    def test_guarda_la_posicion_nueva(self, srv, sesion_naps):
        srv.mover(1, *PARANA)
        fila = sesion_naps.execute(text("SELECT lat, lng FROM naps WHERE id=1")).first()
        assert (round(fila[0], 4), round(fila[1], 4)) == PARANA

    def test_no_toca_los_demas_campos(self, srv, sesion_naps):
        """El PUT heredado reescribe la fila entera; éste no puede."""
        srv.mover(1, *PARANA)
        nombre = sesion_naps.execute(text("SELECT nombre FROM naps WHERE id=1")).scalar()
        assert nombre == "PROCREAR - CDO 21 - NAP 6"

    def test_informa_cuanto_se_movio(self, srv):
        """Sirve para que la auditoría diga algo útil y para confirmar al usuario."""
        m = srv.mover(1, -31.7010, -60.5000)      # ~111 m al sur
        assert 100 <= m.metros_movidos <= 125

    def test_una_nap_sin_coordenadas_previas_no_reporta_distancia(self, srv):
        m = srv.mover(2, *PARANA)
        assert m.metros_movidos is None
        assert m.lat_anterior is None

    def test_acepta_coordenadas_como_texto(self, srv):
        """El frontend puede mandarlas de un input."""
        m = srv.mover(1, "-31.7346", "-60.5289")
        assert m.lat == pytest.approx(-31.7346)


class TestValidacion:
    @pytest.mark.parametrize("lat,lng", [(91, -60), (-91, -60), (-31, 181), (-31, -181)])
    def test_rechaza_coordenadas_imposibles(self, srv, lat, lng):
        with pytest.raises(ErrorUbicacion, match="fuera del rango"):
            srv.mover(1, lat, lng)

    @pytest.mark.parametrize("lat,lng", [(None, -60), (-31, None), ("", ""), ("ahí", "por allá")])
    def test_rechaza_lo_que_no_es_una_coordenada(self, srv, lat, lng):
        with pytest.raises(ErrorUbicacion):
            srv.mover(1, lat, lng)

    def test_una_nap_inexistente_da_su_propio_error(self, srv):
        with pytest.raises(NapInexistente):
            srv.mover(999, *PARANA)

    def test_no_escribe_nada_si_la_coordenada_es_invalida(self, srv, sesion_naps):
        with pytest.raises(ErrorUbicacion):
            srv.mover(1, 500, 500)
        fila = sesion_naps.execute(text("SELECT lat FROM naps WHERE id=1")).scalar()
        assert fila == -31.7000

    def test_avisa_si_cae_fuera_de_la_zona_de_operacion(self, srv):
        """El error típico es invertir latitud y longitud: (-31.7, -60.5) al
        revés da (-60.5, -31.7), que está en el Atlántico Sur."""
        m = srv.mover(1, -60.5289, -31.7346)
        assert m.fuera_de_zona is True

    def test_dentro_de_la_zona_no_avisa(self, srv):
        assert srv.mover(1, *PARANA).fuera_de_zona is False

    def test_fuera_de_zona_avisa_pero_igual_guarda(self, srv, sesion_naps):
        """Es una advertencia, no un veto: el ISP podría expandirse."""
        srv.mover(1, 40.4168, -3.7038)            # Madrid
        assert sesion_naps.execute(text("SELECT lat FROM naps WHERE id=1")).scalar() == 40.4168


class TestAuditoria:
    def test_deja_constancia_con_el_antes_y_el_despues(self, srv, sesion_naps):
        srv.mover(1, *PARANA, usuario="eaguiar")
        filas = _historial(sesion_naps)
        assert len(filas) == 1
        tipo, modulo, titulo, detalle, usuario = filas[0]
        assert (tipo, modulo, usuario) == ("mod", "naps", "eaguiar")
        assert "PROCREAR - CDO 21 - NAP 6" in titulo
        assert "-31.700000" in detalle and "-31.734600" in detalle

    def test_no_audita_un_intento_rechazado(self, srv, sesion_naps):
        with pytest.raises(ErrorUbicacion):
            srv.mover(1, 500, 500)
        assert _historial(sesion_naps) == []

    def test_marca_los_movimientos_fuera_de_zona(self, srv, sesion_naps):
        srv.mover(1, 40.4168, -3.7038)      # Madrid
        assert "FUERA de la zona" in _historial(sesion_naps)[0][3]

    def test_la_constancia_va_en_la_misma_transaccion(self, srv, sesion_naps):
        """Si se revierte el movimiento, no puede quedar una auditoría
        diciendo que se hizo. Escribir por una conexión aparte —que además
        daba 'database is locked'— rompía esta garantía."""
        srv.mover(1, *PARANA)
        sesion_naps.rollback()
        assert _historial(sesion_naps) == []
        assert sesion_naps.execute(text("SELECT lat FROM naps WHERE id=1")).scalar() == -31.70
