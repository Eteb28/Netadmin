"""Driver simulado: contrato, modo simulación, capacidades y manejo de fallas.

Estos tests valen para cualquier driver: cuando llegue el de VSOL, la misma
batería debe pasar contra él. Ése es el sentido de tener una interfaz única.
"""

from __future__ import annotations

import pytest

from gpon_module.core.enums import (
    Capacidad,
    EstadoONU,
    Fabricante,
    ModoServicio,
    MotivoCaida,
    TipoOperacion,
)
from gpon_module.core.errors import (
    CapacidadNoSoportada,
    ErrorAutenticacion,
    ErrorLecturaParcial,
    ErrorTiempoAgotado,
    ErrorValidacion,
)
from gpon_module.core.interfaces import OLTDriver
from gpon_module.core.models import (
    OLT,
    ConfigWiFi,
    CredencialPPPoE,
    RefONU,
    SolicitudAutorizacion,
)
from gpon_module.drivers.mock import PERFIL_VSOL, DriverSimulado, FallasSimuladas

from ..conftest import CREDENCIALES


def _driver(parque, **kwargs) -> DriverSimulado:
    return DriverSimulado(
        olt=OLT(id=1, nombre="sim", host="10.255.0.9", fabricante=Fabricante.SIMULADO),
        credenciales=CREDENCIALES,
        parque=parque,
        **kwargs,
    )


class TestContrato:
    def test_cumple_la_interfaz_de_driver(self, driver: DriverSimulado) -> None:
        assert isinstance(driver, OLTDriver)

    def test_expone_todos_los_metodos_del_diseño(self, driver: DriverSimulado) -> None:
        """La lista de métodos acordada en la Fase 0, verificada una por una."""
        esperados = [
            "authorize_onu",
            "delete_onu",
            "reboot_onu",
            "factory_reset",
            "discover_onus",
            "discover_ports",
            "get_signal",
            "get_traffic",
            "get_temperature",
            "get_distance",
            "get_cpu",
            "get_memory",
            "get_uptime",
            "set_wifi",
            "change_wifi_password",
            "change_pppoe",
            "set_bridge",
            "set_router",
            "backup_configuration",
            "restore_configuration",
            "generate_running_config",
        ]
        faltantes = [nombre for nombre in esperados if not callable(getattr(driver, nombre, None))]
        assert faltantes == []


class TestModoSimulacion:
    def test_es_el_valor_por_defecto(self, parque) -> None:
        """Ejecutar de verdad debe pedirse; nunca ser lo que pasa por descuido."""
        assert _driver(parque).dry_run is True

    def test_no_envia_ningun_comando(self, driver: DriverSimulado) -> None:
        ref = next(iter(sorted(driver.parque.onus)))
        resultado = driver.reboot_onu(ref)

        assert resultado.ok is True
        assert resultado.simulado is True
        assert resultado.comandos_enviados  # sí arma los comandos
        assert driver.comandos_ejecutados == []  # y no envía ninguno

    def test_no_modifica_el_estado_del_equipo(self, driver: DriverSimulado) -> None:
        ref = next(iter(sorted(driver.parque.onus)))
        antes = len(driver.parque.onus)
        driver.delete_onu(ref)
        assert len(driver.parque.onus) == antes
        assert ref in driver.parque.onus

    def test_el_modo_real_si_ejecuta(self, driver_real: DriverSimulado) -> None:
        ref = next(iter(sorted(driver_real.parque.onus)))
        resultado = driver_real.delete_onu(ref)

        assert resultado.simulado is False
        assert driver_real.comandos_ejecutados
        assert ref not in driver_real.parque.onus


class TestCapacidades:
    def test_un_equipo_limitado_declara_lo_que_no_puede(self, parque) -> None:
        """El perfil VSOL refleja lo verificado en Fase 0 contra los equipos reales."""
        driver = _driver(parque, capacidades=PERFIL_VSOL)

        assert not driver.soporta(Capacidad.TRAFICO_POR_ONU)
        assert not driver.soporta(Capacidad.CPU)
        assert not driver.soporta(Capacidad.MEMORIA)
        assert not driver.soporta(Capacidad.TEMPERATURA_CHASIS)
        assert not driver.soporta(Capacidad.SERIAL_POR_SNMP)
        assert driver.soporta(Capacidad.POTENCIA_OPTICA)

    def test_pedir_lo_no_soportado_falla_antes_de_tocar_el_equipo(self, parque) -> None:
        driver = _driver(parque, capacidades=PERFIL_VSOL)
        with pytest.raises(CapacidadNoSoportada, match="TRAFICO_POR_ONU"):
            driver.get_traffic(RefONU(1, 1))

    def test_un_dato_ausente_es_none_y_nunca_cero(self, parque) -> None:
        """Un cero se grafica y se promedia: es una mentira que se propaga."""
        driver = _driver(parque, capacidades=PERFIL_VSOL)
        info = driver.get_system_info()

        assert info.cpu_porcentaje is None
        assert info.memoria_porcentaje is None
        assert info.temperatura_celsius is None


class TestLectura:
    def test_descubre_el_parque_completo(self, driver: DriverSimulado) -> None:
        onus = driver.discover_onus()
        assert len(onus) == len(driver.parque.onus)
        assert all(o.olt_id == 1 for o in onus)

    def test_descubre_los_puertos_con_su_conteo(self, driver: DriverSimulado) -> None:
        puertos = driver.discover_ports()
        assert len(puertos) == len(driver.parque.puertos)
        assert sum(p.cantidad_onus for p in puertos) == len(driver.parque.onus)
        for puerto in puertos:
            assert puerto.cantidad_onus_en_linea <= puerto.cantidad_onus

    def test_las_onu_caidas_no_reportan_potencia(self, driver: DriverSimulado) -> None:
        caidas = [
            o for o in driver.parque.onus.values() if o.estado is EstadoONU.FUERA_DE_LINEA
        ]
        assert caidas, "el parque simulado debe incluir ONU caídas"
        for onu in caidas:
            assert driver.get_signal(onu.ref).rx_onu_dbm is None

    def test_distingue_corte_de_luz_de_fibra_cortada(self) -> None:
        """La distinción que separa "no hay nada que hacer" de "mandar cuadrilla".

        Se prueba sobre el parque completo (473 ONU) porque es el que reproduce
        las proporciones reales medidas en las OLT de ERLAN.
        """
        motivos = {o.motivo_caida for o in generar_parque_grande().onus.values()}
        assert MotivoCaida.APAGADO in motivos
        assert MotivoCaida.PERDIDA_SENAL in motivos

    def test_una_onu_inexistente_no_devuelve_datos_inventados(
        self, driver: DriverSimulado
    ) -> None:
        with pytest.raises(ErrorValidacion, match="No existe la ONU"):
            driver.get_signal(RefONU(99, 99))


class TestFallas:
    def test_la_lectura_truncada_avisa_cuanto_alcanzo_a_leer(self, parque) -> None:
        """El caso que jamás debe interpretarse como una baja masiva."""
        driver = _driver(parque, fallas=FallasSimuladas(fraccion_lectura_parcial=0.5))

        with pytest.raises(ErrorLecturaParcial) as excepcion:
            driver.discover_onus()

        assert excepcion.value.obtenidos == len(parque.onus) // 2
        assert excepcion.value.esperados == len(parque.onus)

    def test_un_timeout_no_es_una_lista_vacia(self, parque) -> None:
        """Devolver [] ante un timeout es lo que produce bajas masivas falsas."""
        driver = _driver(parque, fallas=FallasSimuladas(lectura_agota_tiempo=True))
        with pytest.raises(ErrorTiempoAgotado):
            driver.discover_onus()

    def test_credenciales_rechazadas(self, parque) -> None:
        driver = _driver(parque, fallas=FallasSimuladas(autenticacion_falla=True))
        with pytest.raises(ErrorAutenticacion):
            driver.conectar()

    def test_un_comando_rechazado_deja_un_resultado_fallido_y_explicado(
        self, parque
    ) -> None:
        driver = _driver(parque, dry_run=False, fallas=FallasSimuladas(rechazar_comandos=True))
        ref = next(iter(sorted(parque.onus)))

        resultado = driver.reboot_onu(ref)

        assert resultado.ok is False
        assert resultado.error and "ErrorComando" in resultado.error
        assert ref in driver.parque.onus  # el estado no cambió


class TestEscritura:
    def test_autorizar_agrega_la_onu_y_la_saca_de_pendientes(
        self, driver_real: DriverSimulado
    ) -> None:
        pendiente = driver_real.parque.no_autorizadas[0]
        antes = len(driver_real.parque.onus)

        resultado = driver_real.authorize_onu(
            SolicitudAutorizacion(
                numero_serie=pendiente.numero_serie,
                pon=pendiente.pon,
                nombre="CLIENTE-NUEVO",
                vlan=2026,
            )
        )

        assert resultado.ok
        assert resultado.tipo is TipoOperacion.AUTORIZAR_ONU
        assert len(driver_real.parque.onus) == antes + 1
        assert pendiente not in driver_real.parque.no_autorizadas

    def test_no_se_autoriza_dos_veces_el_mismo_serial(
        self, driver_real: DriverSimulado
    ) -> None:
        existente = next(iter(driver_real.parque.onus.values()))
        resultado = driver_real.authorize_onu(
            SolicitudAutorizacion(numero_serie=existente.numero_serie, pon=existente.ref.pon)
        )
        assert resultado.ok is False
        assert "ya está autorizado" in (resultado.error or "")

    def test_autorizar_sin_serial_se_rechaza_antes_de_armar_comandos(
        self, driver_real: DriverSimulado
    ) -> None:
        with pytest.raises(ErrorValidacion, match="número de serie"):
            driver_real.authorize_onu(SolicitudAutorizacion(numero_serie="", pon=1))

    def test_cambiar_a_modo_router_actualiza_el_cpe(
        self, driver_real: DriverSimulado
    ) -> None:
        ref = next(iter(sorted(driver_real.parque.onus)))
        resultado = driver_real.set_router(
            ref, CredencialPPPoE(usuario="cliente9", password="clave-nueva"), vlan=2542
        )

        assert resultado.ok
        onu = driver_real.parque.onus[ref]
        assert onu.modo_servicio is ModoServicio.ROUTER
        assert onu.usuario_pppoe == "cliente9"
        assert onu.vlan == 2542

    def test_las_claves_nunca_quedan_en_la_auditoria(
        self, driver_real: DriverSimulado
    ) -> None:
        """La tabla de auditoría no debe convertirse en un depósito de contraseñas."""
        ref = next(iter(sorted(driver_real.parque.onus)))

        wifi = driver_real.set_wifi(ref, ConfigWiFi(ssid="ERLAN-99", password="secreta123"))
        pppoe = driver_real.change_pppoe(ref, CredencialPPPoE("cliente9", "otra-secreta"))
        clave = driver_real.change_wifi_password(ref, "clave-larga-123")

        todo = " ".join(
            comando
            for resultado in (wifi, pppoe, clave)
            for comando in resultado.comandos_enviados
        )
        assert "secreta123" not in todo
        assert "otra-secreta" not in todo
        assert "clave-larga-123" not in todo
        assert "********" in todo
        # …y sin embargo el cambio se aplicó de verdad:
        assert driver_real.parque.onus[ref].clave_wifi == "clave-larga-123"

    def test_clave_wifi_demasiado_corta_se_rechaza(
        self, driver_real: DriverSimulado
    ) -> None:
        ref = next(iter(sorted(driver_real.parque.onus)))
        with pytest.raises(ErrorValidacion, match="8 caracteres"):
            driver_real.change_wifi_password(ref, "corta")

    def test_respaldo_incluye_hash_para_detectar_cambios(
        self, driver: DriverSimulado
    ) -> None:
        respaldo = driver.backup_configuration()
        assert respaldo.contenido
        assert len(respaldo.hash_contenido) == 64

    def test_no_se_restaura_un_respaldo_vacio(self, driver_real: DriverSimulado) -> None:
        from gpon_module.core.models import RespaldoConfiguracion

        with pytest.raises(ErrorValidacion, match="vacío"):
            driver_real.restore_configuration(RespaldoConfiguracion(contenido="   "))


class TestParqueSimulado:
    def test_es_determinista(self) -> None:
        """Un simulador que cambia entre corridas no sirve para hacer tests."""
        from gpon_module.drivers.mock import generar_parque

        uno = generar_parque(semilla=7, cantidad_onus=30)
        otro = generar_parque(semilla=7, cantidad_onus=30)

        assert [o.numero_serie for o in uno.onus.values()] == [
            o.numero_serie for o in otro.onus.values()
        ]

    def test_incluye_los_casos_que_importan(self, parque) -> None:
        """Debe haber ONU en línea, caídas y con potencias en ambos extremos."""
        from gpon_module.core.optica import clasificar

        estados = {o.estado for o in parque.onus.values()}
        assert EstadoONU.EN_LINEA in estados
        assert EstadoONU.FUERA_DE_LINEA in estados

        grande = generar_parque_grande()
        clasificaciones = {
            clasificar(o.rx_onu_dbm) for o in grande.onus.values() if o.rx_onu_dbm is not None
        }
        assert len(clasificaciones) >= 3


def generar_parque_grande():
    from gpon_module.drivers.mock import generar_parque

    return generar_parque(cantidad_onus=473)
