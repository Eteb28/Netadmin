"""Repositorios contra una base SQLite real (en memoria)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from gpon_module.core.cifrado import CifradorFernet, CifradorNulo
from gpon_module.core.enums import (
    EstadoAlarma,
    EstadoONU,
    Fabricante,
    Granularidad,
    MotivoCaida,
    Severidad,
    TipoAlarma,
    TipoEvento,
    TipoMetrica,
    TipoOperacion,
)
from gpon_module.core.errors import NoEncontrado
from gpon_module.core.models import (
    OLT,
    ONU,
    Alarma,
    CredencialesOLT,
    Evento,
    Metrica,
    Operacion,
    RefONU,
)
from gpon_module.database.repositories import (
    RepositorioAlarmaSQL,
    RepositorioEventoSQL,
    RepositorioMetricaSQL,
    RepositorioOLTSQL,
    RepositorioONUSQL,
    RepositorioOperacionSQL,
)

CREDENCIALES = CredencialesOLT(
    usuario="admin", password="Xpon@Olt9417#", comunidad_snmp_lectura="publica"
)


@pytest.fixture
def repo_olt(conexion) -> RepositorioOLTSQL:
    return RepositorioOLTSQL(conexion, CifradorNulo())


@pytest.fixture
def olt_guardada(repo_olt) -> OLT:
    return repo_olt.crear(
        OLT(nombre="OLT Centro", host="10.0.0.1", fabricante=Fabricante.SIMULADO),
        CREDENCIALES,
    )


class TestRepositorioOLT:
    def test_alta_y_lectura(self, repo_olt, olt_guardada) -> None:
        recuperada = repo_olt.obtener(olt_guardada.id)
        assert recuperada.nombre == "OLT Centro"
        assert recuperada.fabricante is Fabricante.SIMULADO
        assert recuperada.creada_en is not None

    def test_no_se_repite_el_host(self, repo_olt, olt_guardada) -> None:
        """Dos registros de la misma OLT duplicarían el inventario entero."""
        from gpon_module.core.errors import ErrorRepositorio

        with pytest.raises(ErrorRepositorio):
            repo_olt.crear(
                OLT(nombre="Duplicada", host="10.0.0.1", fabricante=Fabricante.SIMULADO),
                CREDENCIALES,
            )

    def test_las_credenciales_vuelven_en_claro(self, repo_olt, olt_guardada) -> None:
        credenciales = repo_olt.obtener_credenciales(olt_guardada.id)
        assert credenciales.password == "Xpon@Olt9417#"
        assert credenciales.comunidad_snmp_lectura == "publica"

    def test_pero_en_la_tabla_estan_cifradas(self, conexion) -> None:
        """Quien mire la base no debe encontrar la clave de la OLT."""
        repositorio = RepositorioOLTSQL(conexion, CifradorFernet(CifradorFernet.generar_clave()))
        olt = repositorio.crear(
            OLT(nombre="Cifrada", host="10.0.0.2", fabricante=Fabricante.SIMULADO),
            CREDENCIALES,
        )
        fila = conexion.consultar_uno(
            "SELECT password_cifrado FROM olts WHERE id = ?", (olt.id,)
        )
        assert "Xpon@Olt9417#" not in fila["password_cifrado"]
        assert repositorio.obtener_credenciales(olt.id).password == "Xpon@Olt9417#"

    def test_obtener_una_olt_inexistente(self, repo_olt) -> None:
        with pytest.raises(NoEncontrado):
            repo_olt.obtener(9999)

    def test_listar_solo_activas(self, repo_olt, olt_guardada) -> None:
        from dataclasses import replace

        repo_olt.crear(
            OLT(nombre="Inactiva", host="10.0.0.3", fabricante=Fabricante.SIMULADO, activa=False),
            CREDENCIALES,
        )
        assert len(repo_olt.listar()) == 2
        assert [o.nombre for o in repo_olt.listar(solo_activas=True)] == ["OLT Centro"]
        repo_olt.actualizar(replace(olt_guardada, activa=False))
        assert repo_olt.listar(solo_activas=True) == []


class TestRepositorioONU:
    @pytest.fixture
    def repo(self, conexion) -> RepositorioONUSQL:
        return RepositorioONUSQL(conexion)

    def _onu(self, olt_id: int, **kwargs) -> ONU:
        base = {
            "olt_id": olt_id,
            "ref": RefONU(1, 5),
            "numero_serie": "VSOL1234ABCD",
            "nombre": "CLI1000",
            "estado": EstadoONU.EN_LINEA,
            "motivo_caida": MotivoCaida.NINGUNO,
        }
        return ONU(**{**base, **kwargs})

    def test_guardar_dos_veces_actualiza_en_vez_de_duplicar(self, repo, olt_guardada) -> None:
        primera = repo.guardar(self._onu(olt_guardada.id))
        segunda = repo.guardar(
            self._onu(
                olt_guardada.id, estado=EstadoONU.FUERA_DE_LINEA, motivo_caida=MotivoCaida.APAGADO
            )
        )

        assert primera.id == segunda.id
        assert repo.contar_de_olt(olt_guardada.id) == 1
        assert segunda.estado is EstadoONU.FUERA_DE_LINEA
        assert segunda.motivo_caida is MotivoCaida.APAGADO

    def test_la_primera_vez_vista_no_se_pisa(self, repo, olt_guardada) -> None:
        """Es el dato que dice desde cuándo está esa ONU en la red."""
        primera = repo.guardar(self._onu(olt_guardada.id))
        segunda = repo.guardar(self._onu(olt_guardada.id, nombre="CLI1000 renombrada"))
        assert primera.primera_vez_vista == segunda.primera_vez_vista

    def test_una_lectura_sin_serial_no_borra_el_serial_conocido(
        self, repo, olt_guardada
    ) -> None:
        """En VSOL el serial no viene por SNMP: la lectura rápida no debe perderlo."""
        repo.guardar(self._onu(olt_guardada.id, numero_serie="VSOL1234ABCD"))
        actualizada = repo.guardar(self._onu(olt_guardada.id, numero_serie=""))
        assert actualizada.numero_serie == "VSOL1234ABCD"

    def test_buscar_por_serie(self, repo, olt_guardada) -> None:
        repo.guardar(self._onu(olt_guardada.id))
        assert repo.obtener_por_serie("VSOL1234ABCD") is not None
        assert repo.obtener_por_serie("INEXISTENTE") is None
        assert repo.obtener_por_serie("") is None

    def test_listar_por_puerto_pon(self, repo, olt_guardada) -> None:
        repo.guardar(self._onu(olt_guardada.id, ref=RefONU(1, 1), numero_serie="A"))
        repo.guardar(self._onu(olt_guardada.id, ref=RefONU(2, 1), numero_serie="B"))
        assert len(repo.listar_de_olt(olt_guardada.id)) == 2
        assert len(repo.listar_de_olt(olt_guardada.id, pon=2)) == 1

    def test_contar_por_estado(self, repo, olt_guardada) -> None:
        repo.guardar(self._onu(olt_guardada.id, ref=RefONU(1, 1), numero_serie="A"))
        repo.guardar(
            self._onu(
                olt_guardada.id,
                ref=RefONU(1, 2),
                numero_serie="B",
                estado=EstadoONU.FUERA_DE_LINEA,
            )
        )
        assert repo.contar_por_estado(olt_guardada.id) == {"en_linea": 1, "fuera_de_linea": 1}

    def test_al_borrar_la_olt_se_van_sus_onu(self, repo, repo_olt, olt_guardada) -> None:
        repo.guardar(self._onu(olt_guardada.id))
        repo_olt.eliminar(olt_guardada.id)
        assert repo.contar_de_olt(olt_guardada.id) == 0


class TestRepositorioMetrica:
    @pytest.fixture
    def repo(self, conexion) -> RepositorioMetricaSQL:
        return RepositorioMetricaSQL(conexion)

    def test_serie_acotada_por_fechas(self, repo, olt_guardada) -> None:
        base = datetime(2026, 8, 1, tzinfo=UTC)
        repo.registrar_muchas(
            [
                Metrica(
                    olt_id=olt_guardada.id,
                    entidad="onu",
                    entidad_id=1,
                    tipo=TipoMetrica.RX_ONU,
                    valor=-22.0 - indice,
                    registrada_en=base + timedelta(hours=indice),
                )
                for indice in range(10)
            ]
        )
        serie = repo.serie(
            entidad="onu",
            entidad_id=1,
            tipo=TipoMetrica.RX_ONU,
            desde=base + timedelta(hours=2),
            hasta=base + timedelta(hours=4),
        )
        assert [m.valor for m in serie] == [-24.0, -25.0, -26.0]

    def test_las_granularidades_no_se_mezclan(self, repo, olt_guardada) -> None:
        momento = datetime(2026, 8, 1, tzinfo=UTC)
        repo.registrar(
            Metrica(
                olt_id=olt_guardada.id,
                entidad="onu",
                entidad_id=1,
                tipo=TipoMetrica.RX_ONU,
                valor=-22.0,
                granularidad=Granularidad.FINA,
                registrada_en=momento,
            )
        )
        repo.registrar(
            Metrica(
                olt_id=olt_guardada.id,
                entidad="onu",
                entidad_id=1,
                tipo=TipoMetrica.RX_ONU,
                valor=-23.0,
                granularidad=Granularidad.HORARIA,
                registrada_en=momento,
            )
        )
        finas = repo.serie(
            entidad="onu",
            entidad_id=1,
            tipo=TipoMetrica.RX_ONU,
            desde=momento - timedelta(days=1),
            hasta=momento + timedelta(days=1),
            granularidad=Granularidad.FINA,
        )
        assert [m.valor for m in finas] == [-22.0]

    def test_depurar_borra_solo_el_escalon_pedido(self, repo, olt_guardada) -> None:
        """La retención escalonada es lo que evita una base inmanejable."""
        viejo = datetime(2026, 1, 1, tzinfo=UTC)
        nuevo = datetime(2026, 8, 1, tzinfo=UTC)
        for granularidad in (Granularidad.FINA, Granularidad.DIARIA):
            repo.registrar(
                Metrica(
                    olt_id=olt_guardada.id,
                    entidad="olt",
                    entidad_id=olt_guardada.id,
                    tipo=TipoMetrica.CPU,
                    valor=10.0,
                    granularidad=granularidad,
                    registrada_en=viejo,
                )
            )
        borradas = repo.depurar(granularidad=Granularidad.FINA, anterior_a=nuevo)
        assert borradas == 1
        assert repo.contar() == 1


class TestRepositorioEvento:
    @pytest.fixture
    def repo(self, conexion) -> RepositorioEventoSQL:
        return RepositorioEventoSQL(conexion)

    def test_guarda_la_referencia_de_la_onu(self, repo, olt_guardada) -> None:
        evento = repo.registrar(
            Evento(
                tipo=TipoEvento.ONU_NUEVA,
                olt_id=olt_guardada.id,
                ref_onu=RefONU(3, 12),
                descripcion="ONU 3:12 descubierta",
                ocurrido_en=datetime(2026, 8, 4, tzinfo=UTC),
            )
        )
        assert evento.ref_onu == RefONU(3, 12)
        assert evento.id is not None

    def test_listado_filtrado_y_paginado(self, repo, olt_guardada) -> None:
        repo.registrar_muchos(
            [
                Evento(
                    tipo=TipoEvento.CAMBIO_ESTADO if indice % 2 else TipoEvento.ONU_NUEVA,
                    olt_id=olt_guardada.id,
                    ref_onu=RefONU(1, indice),
                    ocurrido_en=datetime(2026, 8, 4, 12, indice, tzinfo=UTC),
                )
                for indice in range(10)
            ]
        )
        assert repo.contar(olt_id=olt_guardada.id) == 10
        assert len(repo.listar(olt_id=olt_guardada.id, tipo=TipoEvento.ONU_NUEVA)) == 5
        assert len(repo.listar(olt_id=olt_guardada.id, limite=3)) == 3

    def test_se_listan_del_mas_reciente_al_mas_viejo(self, repo, olt_guardada) -> None:
        for minuto in (0, 30, 15):
            repo.registrar(
                Evento(
                    tipo=TipoEvento.CAMBIO_ESTADO,
                    olt_id=olt_guardada.id,
                    descripcion=f"minuto {minuto}",
                    ocurrido_en=datetime(2026, 8, 4, 12, minuto, tzinfo=UTC),
                )
            )
        assert [e.descripcion for e in repo.listar()] == [
            "minuto 30",
            "minuto 15",
            "minuto 0",
        ]


class TestRepositorioAlarma:
    @pytest.fixture
    def repo(self, conexion) -> RepositorioAlarmaSQL:
        return RepositorioAlarmaSQL(conexion)

    def test_ciclo_de_vida(self, repo, olt_guardada) -> None:
        alarma = repo.abrir(
            Alarma(
                tipo=TipoAlarma.POTENCIA_CRITICA,
                severidad=Severidad.CRITICA,
                olt_id=olt_guardada.id,
                entidad="onu",
                entidad_id=1,
                mensaje="RX −31,4 dBm",
                valor=-31.4,
                abierta_en=datetime(2026, 8, 4, tzinfo=UTC),
            )
        )
        assert alarma.estado is EstadoAlarma.ACTIVA

        repo.reconocer(alarma.id, "operador", datetime(2026, 8, 4, 1, tzinfo=UTC))
        activas = repo.listar_activas(olt_guardada.id)
        assert activas[0].estado is EstadoAlarma.RECONOCIDA
        assert activas[0].reconocida_por == "operador"

        repo.resolver(alarma.id, datetime(2026, 8, 4, 2, tzinfo=UTC))
        assert repo.listar_activas(olt_guardada.id) == []

    def test_buscar_activa_evita_duplicar_la_misma_alarma(self, repo, olt_guardada) -> None:
        """Sin esto, cada ciclo de sondeo abriría una alarma nueva por lo mismo."""
        repo.abrir(
            Alarma(
                tipo=TipoAlarma.ONU_FUERA_DE_LINEA,
                olt_id=olt_guardada.id,
                entidad="onu",
                entidad_id=7,
                abierta_en=datetime(2026, 8, 4, tzinfo=UTC),
            )
        )
        encontrada = repo.buscar_activa(
            tipo=str(TipoAlarma.ONU_FUERA_DE_LINEA), entidad="onu", entidad_id=7
        )
        assert encontrada is not None
        assert (
            repo.buscar_activa(
                tipo=str(TipoAlarma.ONU_FUERA_DE_LINEA), entidad="onu", entidad_id=8
            )
            is None
        )


class TestRepositorioOperacion:
    def test_la_auditoria_conserva_los_comandos(self, conexion, olt_guardada) -> None:
        repositorio = RepositorioOperacionSQL(conexion)
        operacion = repositorio.registrar(
            Operacion(
                tipo=TipoOperacion.AUTORIZAR_ONU,
                olt_id=olt_guardada.id,
                ref_onu=RefONU(2, 9),
                usuario="tecnico1",
                ok=True,
                simulado=False,
                comandos=("configure terminal", "onu 9 type auto sn VSOLABCD1234"),
                salida="ok",
                ejecutada_en=datetime(2026, 8, 4, tzinfo=UTC),
            )
        )
        recuperada = repositorio.listar(olt_id=olt_guardada.id)[0]
        assert recuperada.comandos == operacion.comandos
        assert recuperada.usuario == "tecnico1"
        assert recuperada.ref_onu == RefONU(2, 9)
        assert recuperada.simulado is False
