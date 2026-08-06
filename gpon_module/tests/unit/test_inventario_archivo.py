"""Alta de OLT desde archivo.

Lo que se protege acá es que volver a correrlo sea inofensivo: durante el
desarrollo se corre muchas veces, y duplicar equipos o perder credenciales en
el camino haría más daño que el trabajo manual que ahorra.
"""

from __future__ import annotations

import pytest

from gpon_module.core.enums import Fabricante
from gpon_module.core.errors import ErrorConfiguracion, ErrorValidacion
from gpon_module.core.models import OLT
from gpon_module.services.inventario_archivo import (
    ServicioInventarioArchivo,
    leer_equipos,
)

ARCHIVO = """
[[olt]]
nombre = "OLT Belgrano"
host = "192.168.10.247"
fabricante = "vsol"
usuario = "eaguiar"
password = "#clave$con:simbolos"
comunidad = "publica"
puerto_ssh = 2222
"""


@pytest.fixture
def archivo(tmp_path):
    def _escribir(contenido: str = ARCHIVO):
        ruta = tmp_path / "equipos.toml"
        ruta.write_text(contenido, encoding="utf-8")
        return ruta

    return _escribir


class ServicioOLTFalso:
    def __init__(self) -> None:
        self.registradas: list[OLT] = []
        self.credenciales_actualizadas: list[tuple[int, object]] = []

    def registrar(self, *, nombre, host, fabricante, credenciales, descripcion=""):
        olt = OLT(id=len(self.registradas) + 1, nombre=nombre, host=host, fabricante=fabricante)
        self.registradas.append(olt)
        return olt

    def actualizar_credenciales(self, olt_id, credenciales) -> None:
        self.credenciales_actualizadas.append((olt_id, credenciales))


class RepositorioFalso:
    def __init__(self, existentes: dict[str, OLT] | None = None) -> None:
        self._por_host = existentes or {}

    def obtener_por_host(self, host: str) -> OLT | None:
        return self._por_host.get(host)


class TestLectura:
    def test_lee_un_equipo_completo(self, archivo) -> None:
        equipos = leer_equipos(archivo())

        assert len(equipos) == 1
        equipo = equipos[0]
        assert equipo.nombre == "OLT Belgrano"
        assert equipo.host == "192.168.10.247"
        assert equipo.fabricante is Fabricante.VSOL
        assert equipo.credenciales.usuario == "eaguiar"
        assert equipo.credenciales.puerto_ssh == 2222

    def test_una_contrasena_con_simbolos_llega_intacta(self, archivo) -> None:
        """'#', '$' y ':' son habituales en contraseñas de equipos."""
        equipos = leer_equipos(archivo())
        assert equipos[0].credenciales.password == "#clave$con:simbolos"

    def test_la_contrasena_puede_venir_de_una_variable_de_entorno(
        self, archivo, monkeypatch
    ) -> None:
        monkeypatch.setenv("GPON_PASSWORD_BELGRANO", "desde-el-entorno")
        equipos = leer_equipos(
            archivo(
                """
[[olt]]
nombre = "OLT Belgrano"
host = "192.168.10.247"
fabricante = "vsol"
password_entorno = "GPON_PASSWORD_BELGRANO"
"""
            )
        )
        assert equipos[0].credenciales.password == "desde-el-entorno"

    def test_una_variable_de_entorno_ausente_falla_con_motivo(self, archivo, monkeypatch) -> None:
        """Callar acá dejaría una OLT registrada con la contraseña vacía."""
        monkeypatch.delenv("GPON_PASSWORD_FALTANTE", raising=False)
        with pytest.raises(ErrorConfiguracion, match="GPON_PASSWORD_FALTANTE"):
            leer_equipos(
                archivo(
                    """
[[olt]]
nombre = "X"
host = "10.0.0.1"
fabricante = "vsol"
password_entorno = "GPON_PASSWORD_FALTANTE"
"""
                )
            )

    def test_un_fabricante_sin_driver_se_rechaza_antes_de_tocar_la_base(self, archivo) -> None:
        with pytest.raises(ErrorValidacion, match="sin driver"):
            leer_equipos(
                archivo('[[olt]]\nnombre = "X"\nhost = "10.0.0.1"\nfabricante = "huawei"\n')
            )

    def test_falta_un_campo_obligatorio(self, archivo) -> None:
        with pytest.raises(ErrorValidacion, match="host"):
            leer_equipos(archivo('[[olt]]\nnombre = "X"\nfabricante = "vsol"\n'))

    def test_un_archivo_inexistente_dice_qué_hacer(self, tmp_path) -> None:
        with pytest.raises(ErrorConfiguracion, match="ejemplo"):
            leer_equipos(tmp_path / "no-existe.toml")


class TestAplicacion:
    def test_da_de_alta_lo_que_no_estaba(self, archivo) -> None:
        servicio, repositorio = ServicioOLTFalso(), RepositorioFalso()
        resultado = ServicioInventarioArchivo(servicio, repositorio).aplicar(
            leer_equipos(archivo())
        )

        assert len(resultado.creadas) == 1
        assert resultado.actualizadas == ()
        assert servicio.registradas[0].host == "192.168.10.247"

    def test_correrlo_dos_veces_no_duplica_el_equipo(self, archivo) -> None:
        """Se corre muchas veces durante el desarrollo: tiene que ser inofensivo."""
        existente = OLT(id=7, nombre="OLT Belgrano", host="192.168.10.247")
        servicio = ServicioOLTFalso()
        resultado = ServicioInventarioArchivo(
            servicio, RepositorioFalso({"192.168.10.247": existente})
        ).aplicar(leer_equipos(archivo()))

        assert resultado.creadas == ()
        assert len(resultado.actualizadas) == 1
        assert servicio.registradas == []

    def test_al_reaplicar_se_actualizan_las_credenciales(self, archivo) -> None:
        """Corregir una contraseña es editar el archivo y volver a correrlo."""
        existente = OLT(id=7, nombre="OLT Belgrano", host="192.168.10.247")
        servicio = ServicioOLTFalso()
        ServicioInventarioArchivo(
            servicio, RepositorioFalso({"192.168.10.247": existente})
        ).aplicar(leer_equipos(archivo()))

        olt_id, credenciales = servicio.credenciales_actualizadas[0]
        assert olt_id == 7
        assert credenciales.usuario == "eaguiar"
        assert credenciales.password == "#clave$con:simbolos"
