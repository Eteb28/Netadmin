"""Pruebas del motor unificado de incidentes (fase 4, ADR-0003)."""
from __future__ import annotations

from datetime import timedelta

import pytest

from pucara.models.incidentes import AlcanceIncidente, CausaProbable, EstadoIncidente
from pucara.models.reclamos import ahora
from pucara.repositories.incidentes import IncidenteRepository
from pucara.services.incidentes import (
    ConfiguracionMotor, LecturaOnu, MotorIncidentes,
)


@pytest.fixture()
def motor(sesion):
    return MotorIncidentes(
        IncidenteRepository(sesion),
        ConfiguracionMotor(minutos_estabilidad=5, umbral_masivo=3),
    )


def onu(ref, online=False, pon=1, motivo=None, olt=1):
    return LecturaOnu(referencia=ref, olt_id=olt, pon=pon, online=online,
                      motivo_caida=motivo, nro_cliente=ref)


class TestNoDuplicar:
    def test_una_caida_abre_un_incidente(self, motor):
        r = motor.procesar_sondeo([onu("onu:1/1/1")])
        assert r["nuevos"] == 1

    def test_la_misma_caida_no_duplica(self, motor):
        motor.procesar_sondeo([onu("onu:1/1/1")])
        r = motor.procesar_sondeo([onu("onu:1/1/1")])   # sigue caída
        assert r["nuevos"] == 0


class TestCicloDeVida:
    def test_al_volver_pasa_a_recuperada_pero_no_cierra(self, motor, sesion):
        motor.procesar_sondeo([onu("onu:1/1/1")])
        r = motor.procesar_sondeo([onu("onu:1/1/1", online=True)])
        assert r["recuperados"] == 1
        assert r["cerrados"] == 0        # todavía no cumplió la estabilidad

        inc = IncidenteRepository(sesion).listar_activos()[0]
        assert inc.estado is EstadoIncidente.RECUPERADA

    def test_cierra_recien_tras_la_estabilidad(self, motor, sesion):
        motor.procesar_sondeo([onu("onu:1/1/1")])
        motor.procesar_sondeo([onu("onu:1/1/1", online=True)])

        repo = IncidenteRepository(sesion)
        inc = repo.listar_activos()[0]
        inc.recuperado = ahora() - timedelta(minutes=6)   # ya pasó el tiempo
        repo.guardar(inc)

        assert motor.cerrar_estables() == 1
        assert not repo.listar_activos()

    def test_cierre_registra_sistema_y_motivo(self, motor, sesion):
        motor.procesar_sondeo([onu("onu:1/1/1")])
        motor.procesar_sondeo([onu("onu:1/1/1", online=True)])
        repo = IncidenteRepository(sesion)
        inc = repo.listar_activos()[0]
        inc.recuperado = ahora() - timedelta(minutes=6)
        repo.guardar(inc)
        motor.cerrar_estables()

        cerrado = repo.historial()[0]
        assert cerrado.usuario_cierre == "Sistema"
        assert cerrado.motivo_cierre == "Recuperación automática"
        assert cerrado.minutos_caida is not None

    def test_si_vuelve_a_caer_suma_ciclo_y_no_crea_otro(self, motor, sesion):
        """Una ONU intermitente debe verse como UN incidente con varios ciclos."""
        motor.procesar_sondeo([onu("onu:1/1/1")])
        motor.procesar_sondeo([onu("onu:1/1/1", online=True)])
        r = motor.procesar_sondeo([onu("onu:1/1/1")])      # se cae de nuevo

        assert r["nuevos"] == 0
        incs = IncidenteRepository(sesion).listar_activos()
        assert len(incs) == 1
        assert incs[0].ciclos == 2
        assert incs[0].estado is EstadoIncidente.ACTIVA


class TestEventosMasivos:
    def test_agrupa_en_un_incidente_de_pon(self, motor, sesion):
        caidas = [onu(f"onu:1/5/{i}", pon=5) for i in range(1, 6)]
        r = motor.procesar_sondeo(caidas)

        assert r["masivos"] == 1
        assert r["nuevos"] == 0          # NO se crean 5 incidentes sueltos
        inc = IncidenteRepository(sesion).listar_activos()[0]
        assert inc.alcance is AlcanceIncidente.PON
        assert inc.cantidad_afectados == 5

    def test_debajo_del_umbral_van_individuales(self, motor):
        r = motor.procesar_sondeo([onu("onu:1/5/1", pon=5), onu("onu:1/5/2", pon=5)])
        assert r["masivos"] == 0
        assert r["nuevos"] == 2

    def test_no_cierra_si_vuelve_solo_una_parte(self, motor):
        caidas = [onu(f"onu:1/5/{i}", pon=5) for i in range(1, 6)]
        motor.procesar_sondeo(caidas)
        # vuelven 3 de 5
        lecturas = [onu(f"onu:1/5/{i}", online=True, pon=5) for i in range(1, 4)]
        lecturas += [onu(f"onu:1/5/{i}", pon=5) for i in range(4, 6)]
        r = motor.procesar_sondeo(lecturas)
        assert r["recuperados"] == 0     # el problema sigue

    def test_cierra_cuando_vuelven_todas(self, motor):
        caidas = [onu(f"onu:1/5/{i}", pon=5) for i in range(1, 6)]
        motor.procesar_sondeo(caidas)
        r = motor.procesar_sondeo([onu(f"onu:1/5/{i}", online=True, pon=5) for i in range(1, 6)])
        assert r["recuperados"] == 1


class TestCausaProbable:
    def test_mayoria_power_off_es_corte_electrico(self, motor, sesion):
        caidas = [onu(f"onu:1/5/{i}", pon=5, motivo="Power Off") for i in range(1, 6)]
        motor.procesar_sondeo(caidas)
        inc = IncidenteRepository(sesion).listar_activos()[0]
        assert inc.causa_probable is CausaProbable.CORTE_ELECTRICO

    def test_mayoria_los_es_corte_de_fibra(self, motor, sesion):
        caidas = [onu(f"onu:1/5/{i}", pon=5, motivo="Onu Los") for i in range(1, 6)]
        motor.procesar_sondeo(caidas)
        inc = IncidenteRepository(sesion).listar_activos()[0]
        assert inc.causa_probable is CausaProbable.CORTE_FIBRA

    def test_mezcla_queda_desconocida(self, motor, sesion):
        caidas = [
            onu("onu:1/5/1", pon=5, motivo="Power Off"),
            onu("onu:1/5/2", pon=5, motivo="Onu Los"),
            onu("onu:1/5/3", pon=5, motivo="Power Off"),
            onu("onu:1/5/4", pon=5, motivo="Onu Los"),
        ]
        motor.procesar_sondeo(caidas)
        inc = IncidenteRepository(sesion).listar_activos()[0]
        assert inc.causa_probable is CausaProbable.DESCONOCIDA


class TestLecturaParcial:
    def test_una_lectura_truncada_no_abre_incidentes(self, motor):
        """Regla de oro: un sondeo incompleto NO significa que todo se cayó.
        Este error ya ocurrió en producción y disparó avisos masivos falsos."""
        caidas = [onu(f"onu:1/5/{i}", pon=5) for i in range(1, 10)]
        r = motor.procesar_sondeo(caidas, lectura_completa=False)

        assert r["nuevos"] == 0
        assert r["masivos"] == 0
        assert r["omitido_por_lectura_parcial"] is True

    def test_pero_si_procesa_las_recuperaciones(self, motor):
        """Confirmar que algo VOLVIÓ con datos parciales es seguro."""
        motor.procesar_sondeo([onu("onu:1/1/1")])
        r = motor.procesar_sondeo([onu("onu:1/1/1", online=True)], lectura_completa=False)
        assert r["recuperados"] == 1
