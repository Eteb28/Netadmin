"""Servicios de punta a punta: driver simulado, base real, reloj controlado.

Es la prueba de que el módulo funciona entero sin una OLT de verdad, que era
el entregable comprometido para esta fase.
"""

from __future__ import annotations

import pytest

from gpon_module.core.enums import (
    Capacidad,
    EstadoOLT,
    EstadoONU,
    Fabricante,
    ResultadoSincronizacion,
    TipoEvento,
)
from gpon_module.core.errors import (
    CapacidadNoSoportada,
    ErrorRepositorio,
    ErrorValidacion,
    NoEncontrado,
)
from gpon_module.core.models import ConfigWiFi, RefONU, SolicitudAutorizacion
from gpon_module.drivers.mock import PERFIL_VSOL, FallasSimuladas

from ..conftest import CREDENCIALES


class TestServicioOLT:
    def test_alta_y_listado(self, sistema, olt) -> None:
        assert olt.id is not None
        assert [o.host for o in sistema.servicio_olt.listar()] == ["10.255.0.1"]

    def test_no_se_registra_dos_veces_la_misma_direccion(self, sistema, olt) -> None:
        with pytest.raises(ErrorValidacion, match="Ya hay una OLT"):
            sistema.servicio_olt.registrar(
                nombre="Otra",
                host="10.255.0.1",
                fabricante=Fabricante.SIMULADO,
                credenciales=CREDENCIALES,
            )

    def test_no_se_registra_una_olt_sin_driver(self, sistema) -> None:
        """ZTE llega en la Fase 6: hasta entonces, el alta debe explicarlo."""
        with pytest.raises(ErrorValidacion, match="No hay driver"):
            sistema.servicio_olt.registrar(
                nombre="ZTE futura",
                host="10.255.0.50",
                fabricante=Fabricante.ZTE,
                credenciales=CREDENCIALES,
            )

    def test_faltan_datos_obligatorios(self, sistema) -> None:
        with pytest.raises(ErrorValidacion, match="nombre"):
            sistema.servicio_olt.registrar(
                nombre="   ",
                host="10.255.0.2",
                fabricante=Fabricante.SIMULADO,
                credenciales=CREDENCIALES,
            )

    def test_probar_conexion_toma_los_datos_del_equipo(self, sistema, olt) -> None:
        ok, detalle = sistema.servicio_olt.probar_conexion(olt.id)
        assert ok
        assert "V1600G1B" in detalle
        actualizada = sistema.servicio_olt.obtener(olt.id)
        assert actualizada.estado is EstadoOLT.EN_LINEA
        assert actualizada.modelo == "V1600G1B"

    def test_un_equipo_inalcanzable_queda_marcado_fuera_de_linea(
        self, sistema, olt, parque
    ) -> None:
        sistema.fabrica_drivers._extras["fallas"] = FallasSimuladas(conexion_falla=True)

        ok, detalle = sistema.servicio_olt.probar_conexion(olt.id)

        assert ok is False
        assert "ErrorTiempoAgotado" in detalle
        assert sistema.servicio_olt.obtener(olt.id).estado is EstadoOLT.FUERA_DE_LINEA

    def test_las_credenciales_sobreviven_el_viaje_a_la_base(self, sistema, olt) -> None:
        recuperadas = sistema.repositorio_olt.obtener_credenciales(olt.id)
        assert recuperadas.password == CREDENCIALES.password


class TestDescubrimiento:
    def test_inventaria_todo_el_parque(self, sistema, olt, parque) -> None:
        resultado = sistema.servicio_descubrimiento.descubrir(olt.id)

        assert resultado.completo
        assert resultado.onus_leidas == len(parque.onus)
        assert resultado.onus_nuevas == len(parque.onus)
        assert len(resultado.puertos) == len(parque.puertos)
        assert len(resultado.no_autorizadas) == len(parque.no_autorizadas)

    def test_persiste_lo_descubierto(self, sistema, olt, parque) -> None:
        sistema.servicio_descubrimiento.descubrir(olt.id)

        assert sistema.repositorio_onu.contar_de_olt(olt.id) == len(parque.onus)
        assert len(sistema.repositorio_puerto.listar_de_olt(olt.id)) == len(parque.puertos)
        perfiles = sistema.repositorio_perfiles.obtener_de_olt(olt.id)
        assert len(perfiles.dba) == len(parque.perfiles.dba)
        assert len(perfiles.vlans) == len(parque.perfiles.vlans)

    def test_la_segunda_corrida_no_duplica_ni_reporta_novedades(
        self, sistema, olt, parque
    ) -> None:
        sistema.servicio_descubrimiento.descubrir(olt.id)
        segunda = sistema.servicio_descubrimiento.descubrir(olt.id)

        assert segunda.onus_nuevas == 0
        assert sistema.repositorio_onu.contar_de_olt(olt.id) == len(parque.onus)

    def test_registra_un_evento_por_cada_onu_nueva(self, sistema, olt, parque) -> None:
        sistema.servicio_descubrimiento.descubrir(olt.id)
        eventos = sistema.repositorio_evento.listar(
            olt_id=olt.id, tipo=TipoEvento.ONU_NUEVA, limite=1000
        )
        assert len(eventos) == len(parque.onus)

    def test_deja_registrada_la_corrida(self, sistema, olt) -> None:
        sistema.servicio_descubrimiento.descubrir(olt.id)
        ultima = sistema.repositorio_sincronizacion.ultima_de_olt(olt.id)
        assert ultima is not None
        assert ultima.resultado is ResultadoSincronizacion.COMPLETA
        assert ultima.duracion_ms is not None


class TestLecturaIncompleta:
    """La regla más importante del módulo, probada de varias maneras.

    Una lectura incompleta no es una baja masiva. Este error ya ocurrió en
    producción con Pucará: un walk truncado se interpretó como que todas las
    ONU se habían caído.
    """

    def test_una_lectura_truncada_no_borra_el_inventario(
        self, sistema, olt, parque
    ) -> None:
        sistema.servicio_descubrimiento.descubrir(olt.id)
        total = sistema.repositorio_onu.contar_de_olt(olt.id)

        sistema.fabrica_drivers._extras["fallas"] = FallasSimuladas(
            fraccion_lectura_parcial=0.3
        )
        resultado = sistema.servicio_descubrimiento.descubrir(olt.id)

        assert resultado.completo is False
        assert sistema.repositorio_onu.contar_de_olt(olt.id) == total

    def test_la_corrida_queda_marcada_como_parcial(self, sistema, olt) -> None:
        sistema.fabrica_drivers._extras["fallas"] = FallasSimuladas(
            fraccion_lectura_parcial=0.3
        )
        sistema.servicio_descubrimiento.descubrir(olt.id)

        ultima = sistema.repositorio_sincronizacion.ultima_de_olt(olt.id)
        assert ultima.resultado is ResultadoSincronizacion.PARCIAL
        assert "parcial" in ultima.detalle.lower()

    def test_no_se_pisa_el_total_conocido_de_onu(self, sistema, olt, parque) -> None:
        """Bajar el contador a 0 en la base es la baja masiva que hay que evitar."""
        sistema.servicio_descubrimiento.descubrir(olt.id)
        assert sistema.servicio_olt.obtener(olt.id).cantidad_onus == len(parque.onus)

        sistema.fabrica_drivers._extras["fallas"] = FallasSimuladas(
            lectura_agota_tiempo=True
        )
        resultado = sistema.servicio_descubrimiento.descubrir(olt.id)

        # No se leyó absolutamente nada: eso es una corrida fallida, no una OLT
        # que se quedó sin ONU.
        assert resultado.fallido
        actualizada = sistema.servicio_olt.obtener(olt.id)
        assert actualizada.cantidad_onus == len(parque.onus)
        assert actualizada.estado is EstadoOLT.FUERA_DE_LINEA

    def test_leer_algo_a_medias_deja_la_olt_degradada_y_no_caida(
        self, sistema, olt, parque
    ) -> None:
        """Distinguir "leí a medias" de "no pude leer nada" cambia la decisión."""
        sistema.servicio_descubrimiento.descubrir(olt.id)

        sistema.fabrica_drivers._extras["fallas"] = FallasSimuladas(
            fraccion_lectura_parcial=0.3
        )
        resultado = sistema.servicio_descubrimiento.descubrir(olt.id)

        assert resultado.resultado is ResultadoSincronizacion.PARCIAL
        actualizada = sistema.servicio_olt.obtener(olt.id)
        assert actualizada.estado is EstadoOLT.DEGRADADA
        assert actualizada.cantidad_onus == len(parque.onus)

    def test_un_timeout_no_deja_el_inventario_vacio(self, sistema, olt, parque) -> None:
        sistema.servicio_descubrimiento.descubrir(olt.id)
        sistema.fabrica_drivers._extras["fallas"] = FallasSimuladas(
            lectura_agota_tiempo=True
        )

        resultado = sistema.servicio_descubrimiento.descubrir(olt.id)

        assert resultado.completo is False
        assert sistema.repositorio_onu.contar_de_olt(olt.id) == len(parque.onus)


class TestCapacidadesLimitadas:
    """Un equipo limitado debe degradar con elegancia, no romper."""

    def test_el_descubrimiento_sigue_sin_las_capacidades_ausentes(
        self, sistema, olt, parque
    ) -> None:
        sistema.fabrica_drivers._extras["capacidades"] = PERFIL_VSOL - {
            Capacidad.DESCUBRIR_NO_AUTORIZADAS,
            Capacidad.DESCUBRIR_PERFILES,
        }

        resultado = sistema.servicio_descubrimiento.descubrir(olt.id)

        assert resultado.completo
        assert resultado.onus_leidas == len(parque.onus)
        assert resultado.no_autorizadas == ()
        assert any("sin autorizar" in a for a in resultado.advertencias)
        assert any("perfiles" in a for a in resultado.advertencias)

    def test_una_operacion_no_soportada_avisa_antes_de_intentarla(
        self, sistema, olt
    ) -> None:
        sistema.fabrica_drivers._extras["capacidades"] = PERFIL_VSOL  # sin WiFi por OMCI

        with pytest.raises(CapacidadNoSoportada, match="WIFI_POR_OMCI"):
            sistema.servicio_onu.configurar_wifi(
                olt.id, RefONU(1, 1), ConfigWiFi(ssid="ERLAN-1", password="clave1234")
            )

    def test_la_interfaz_puede_consultar_capacidades_sin_conectarse(
        self, sistema, olt
    ) -> None:
        capacidades = sistema.servicio_olt.capacidades(olt.id)
        assert Capacidad.POTENCIA_OPTICA in capacidades


class TestServicioONU:
    def test_potencias_clasificadas(self, sistema, olt, parque) -> None:
        potencias = sistema.servicio_onu.potencias(olt.id)
        assert len(potencias) == len(parque.onus)
        con_lectura = [p for p in potencias if p.rx_dbm is not None]
        assert con_lectura
        assert all(p.clasificacion is not None for p in potencias)

    def test_las_onu_caidas_aparecen_como_sin_lectura_y_no_como_criticas(
        self, sistema, olt
    ) -> None:
        from gpon_module.core.enums import ClasificacionOptica

        sistema.servicio_descubrimiento.descubrir(olt.id)
        caidas = [
            o
            for o in sistema.servicio_onu.listar(olt.id)
            if o.estado is EstadoONU.FUERA_DE_LINEA
        ]
        assert caidas
        potencia = sistema.servicio_onu.potencia(olt.id, caidas[0].ref)
        assert potencia.clasificacion is ClasificacionOptica.SIN_LECTURA

    def test_resumen_por_estado(self, sistema, olt, parque) -> None:
        sistema.servicio_descubrimiento.descubrir(olt.id)
        resumen = sistema.servicio_onu.resumen_estado(olt.id)
        assert sum(resumen.values()) == len(parque.onus)

    def test_buscar_una_onu_que_no_esta(self, sistema, olt) -> None:
        with pytest.raises(NoEncontrado):
            sistema.servicio_onu.obtener_por_ref(olt.id, RefONU(99, 99))


class TestAuditoria:
    def test_toda_escritura_queda_registrada(self, sistema, olt, parque) -> None:
        ref = next(iter(sorted(parque.onus)))
        sistema.servicio_onu.reiniciar(olt.id, ref, usuario="tecnico1")

        operaciones = sistema.repositorio_operacion.listar(olt_id=olt.id)
        assert len(operaciones) == 1
        assert operaciones[0].usuario == "tecnico1"
        assert operaciones[0].ref_onu == ref
        assert operaciones[0].comandos  # los comandos quedan guardados

    def test_las_simuladas_tambien_se_auditan_y_se_distinguen(
        self, sistema, olt, parque
    ) -> None:
        """Una intención registrada vale tanto como una ejecución."""
        ref = next(iter(sorted(parque.onus)))
        sistema.servicio_onu.reiniciar(olt.id, ref)

        operacion = sistema.repositorio_operacion.listar(olt_id=olt.id)[0]
        assert operacion.simulado is True
        assert operacion.ok is True

    def test_una_operacion_fallida_tambien_queda(self, sistema, olt, parque) -> None:
        sistema.fabrica_drivers._extras["fallas"] = FallasSimuladas(rechazar_comandos=True)
        ref = next(iter(sorted(parque.onus)))

        resultado = sistema.servicio_onu.reiniciar(olt.id, ref, dry_run=False)

        assert resultado.ok is False
        operacion = sistema.repositorio_operacion.listar(olt_id=olt.id)[0]
        assert operacion.ok is False
        assert "ErrorComando" in operacion.error

    def test_una_operacion_exitosa_deja_evento(self, sistema, olt, parque) -> None:
        ref = next(iter(sorted(parque.onus)))
        sistema.servicio_onu.reiniciar(olt.id, ref)

        eventos = sistema.repositorio_evento.listar(olt_id=olt.id, tipo=TipoEvento.REINICIO_ONU)
        assert len(eventos) == 1
        assert eventos[0].ref_onu == ref


class TestModoSimulacionEnServicios:
    def test_es_el_comportamiento_por_defecto(self, sistema, olt, parque) -> None:
        ref = next(iter(sorted(parque.onus)))
        resultado = sistema.servicio_onu.eliminar(olt.id, ref)

        assert resultado.simulado is True
        assert ref in parque.onus  # la ONU sigue en el equipo

    def test_ejecutar_de_verdad_hay_que_pedirlo(self, sistema, olt, parque) -> None:
        ref = next(iter(sorted(parque.onus)))
        resultado = sistema.servicio_onu.eliminar(olt.id, ref, dry_run=False)

        assert resultado.simulado is False
        assert ref not in parque.onus

    def test_autorizar_de_verdad_agrega_la_onu_al_equipo(
        self, sistema, olt, parque
    ) -> None:
        pendiente = parque.no_autorizadas[0]
        antes = len(parque.onus)

        resultado = sistema.servicio_onu.autorizar(
            olt.id,
            SolicitudAutorizacion(
                numero_serie=pendiente.numero_serie,
                pon=pendiente.pon,
                nombre="CLIENTE-NUEVO",
                vlan=2026,
            ),
            usuario="tecnico1",
            dry_run=False,
        )

        assert resultado.ok
        assert len(parque.onus) == antes + 1

        # …y la novedad aparece en el siguiente descubrimiento:
        sistema.servicio_descubrimiento.descubrir(olt.id)
        assert sistema.servicio_onu.buscar_por_serie(pendiente.numero_serie) is not None

    def test_una_solicitud_incompleta_se_rechaza_antes_de_conectarse(
        self, sistema, olt
    ) -> None:
        with pytest.raises(ErrorValidacion, match="número de serie"):
            sistema.servicio_onu.autorizar(
                olt.id, SolicitudAutorizacion(numero_serie="", pon=1)
            )
        with pytest.raises(ErrorValidacion, match="puerto PON"):
            sistema.servicio_onu.autorizar(
                olt.id, SolicitudAutorizacion(numero_serie="VSOL1234", pon=0)
            )


class TestContenedor:
    def test_arma_el_sistema_completo(self, sistema) -> None:
        assert sistema.servicio_olt is not None
        assert sistema.servicio_onu is not None
        assert sistema.servicio_descubrimiento is not None
        assert sistema.conexion.version_esquema() >= 1

    def test_el_modulo_no_importa_codigo_de_pucara(self) -> None:
        """Requisito explícito: sin dependencias hacia Pucará, en ninguna dirección.

        Lo que se mide es el **módulo importado**, no el texto de la línea: el
        módulo lee la base comercial de Pucará —de sólo lectura, y por una ruta
        de configuración—, así que tiene clases con "Pucara" en el nombre. Eso
        no es una dependencia de código; importar ``pucara.algo`` sí lo sería,
        y es lo que este test prohíbe.
        """
        import ast
        import pathlib

        raiz = pathlib.Path(__file__).resolve().parents[2]
        prohibidos = ("pucara", "netadmin")
        sospechosos = []

        for archivo in raiz.rglob("*.py"):
            if "tests" in archivo.parts:
                continue
            arbol = ast.parse(archivo.read_text(encoding="utf-8"), filename=str(archivo))
            for nodo in ast.walk(arbol):
                if isinstance(nodo, ast.Import):
                    modulos = [alias.name for alias in nodo.names]
                elif isinstance(nodo, ast.ImportFrom):
                    modulos = [nodo.module or ""]
                else:
                    continue
                for modulo in modulos:
                    raiz_modulo = modulo.split(".")[0].lower()
                    if raiz_modulo in prohibidos:
                        sospechosos.append(f"{archivo.name}: {modulo}")

        assert sospechosos == []

    def test_la_base_comercial_se_abre_de_solo_lectura(self, tmp_path) -> None:
        """Que el alta de una ONU no pueda editar la base comercial.

        No alcanza con no escribir: se abre con ``mode=ro``, así que el intento
        lo rechaza SQLite. Es la diferencia entre una convención y una garantía.
        """
        import sqlite3

        from gpon_module.database.repositories import RepositorioClientesPucara

        base = tmp_path / "comercial.db"
        with sqlite3.connect(base) as preparacion:
            preparacion.execute("CREATE TABLE clientes (nro_cliente TEXT)")
            preparacion.execute("INSERT INTO clientes VALUES ('034716')")

        repositorio = RepositorioClientesPucara(base)
        with pytest.raises(ErrorRepositorio):
            repositorio._consultar("DELETE FROM clientes", ())

        with sqlite3.connect(base) as comprobacion:
            assert comprobacion.execute("SELECT COUNT(*) FROM clientes").fetchone()[0] == 1
