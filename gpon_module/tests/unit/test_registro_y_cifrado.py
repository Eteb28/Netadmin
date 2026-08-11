"""Registro de drivers y cifrado de credenciales."""

from __future__ import annotations

import pytest

from gpon_module.core.cifrado import CifradorFernet, CifradorNulo
from gpon_module.core.enums import Capacidad, Fabricante
from gpon_module.core.errors import DriverNoRegistrado, ErrorCifrado, ErrorConfiguracion
from gpon_module.core.models import OLT, CredencialesOLT
from gpon_module.core.registry import (
    crear_driver,
    describir,
    fabricantes_registrados,
)


class TestRegistroDeDrivers:
    def test_el_driver_simulado_queda_registrado_al_importar(self) -> None:
        import gpon_module.drivers  # noqa: F401

        assert Fabricante.SIMULADO in fabricantes_registrados()

    def test_se_puede_saber_que_hace_un_driver_sin_instanciarlo(self) -> None:
        """La interfaz web necesita esto para decidir qué mostrar sin conectarse."""
        descripcion = describir(Fabricante.SIMULADO)
        assert descripcion.fabricante is Fabricante.SIMULADO
        assert Capacidad.POTENCIA_OPTICA in descripcion.capacidades

    def test_un_fabricante_sin_driver_falla_con_un_mensaje_util(self) -> None:
        with pytest.raises(DriverNoRegistrado) as excepcion:
            describir(Fabricante.ZTE)
        assert "zte" in str(excepcion.value).lower()

    def test_crear_driver_devuelve_el_del_fabricante_de_la_olt(self) -> None:
        olt = OLT(id=1, nombre="x", host="10.0.0.1", fabricante=Fabricante.SIMULADO)
        driver = crear_driver(olt=olt, credenciales=CredencialesOLT())
        assert driver.fabricante is Fabricante.SIMULADO

    def test_el_driver_sale_en_modo_simulacion_salvo_pedido_explicito(self) -> None:
        olt = OLT(id=1, nombre="x", host="10.0.0.1", fabricante=Fabricante.SIMULADO)
        assert crear_driver(olt=olt, credenciales=CredencialesOLT()).dry_run is True
        assert (
            crear_driver(olt=olt, credenciales=CredencialesOLT(), dry_run=False).dry_run
            is False
        )


class TestCifrado:
    def test_ida_y_vuelta(self) -> None:
        cifrador = CifradorFernet(CifradorFernet.generar_clave())
        assert cifrador.descifrar(cifrador.cifrar("Xpon@Olt9417#")) == "Xpon@Olt9417#"

    def test_el_texto_cifrado_no_deja_ver_el_secreto(self) -> None:
        cifrador = CifradorFernet(CifradorFernet.generar_clave())
        assert "Xpon@Olt9417#" not in cifrador.cifrar("Xpon@Olt9417#")

    def test_dos_cifrados_del_mismo_texto_no_son_iguales(self) -> None:
        """Fernet incluye un vector aleatorio: dos OLT con la misma clave no se delatan."""
        cifrador = CifradorFernet(CifradorFernet.generar_clave())
        assert cifrador.cifrar("misma") != cifrador.cifrar("misma")

    def test_una_clave_ajena_no_puede_leer(self) -> None:
        cifrado = CifradorFernet(CifradorFernet.generar_clave()).cifrar("secreto")
        otro = CifradorFernet(CifradorFernet.generar_clave())
        with pytest.raises(ErrorCifrado, match=r"[Nn]o se pudo descifrar"):
            otro.descifrar(cifrado)

    def test_una_clave_invalida_falla_al_construir_y_no_al_usar(self) -> None:
        with pytest.raises(ErrorConfiguracion, match="inválida"):
            CifradorFernet("esto-no-es-una-clave")

    def test_sin_clave_no_arranca(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GPON_CLAVE_CIFRADO", raising=False)
        with pytest.raises(ErrorConfiguracion, match="GPON_CLAVE_CIFRADO"):
            CifradorFernet()

    def test_el_vacio_queda_vacio(self) -> None:
        cifrador = CifradorFernet(CifradorFernet.generar_clave())
        assert cifrador.cifrar("") == ""
        assert cifrador.descifrar("") == ""


class TestCifradorNulo:
    def test_marca_los_valores_para_que_se_note_que_no_estan_protegidos(self) -> None:
        cifrador = CifradorNulo()
        assert cifrador.cifrar("clave").startswith("plano:")
        assert cifrador.descifrar(cifrador.cifrar("clave")) == "clave"

    def test_no_puede_leer_lo_cifrado_de_verdad(self) -> None:
        """Evita confundir un valor de desarrollo con uno realmente cifrado."""
        real = CifradorFernet(CifradorFernet.generar_clave()).cifrar("clave")
        with pytest.raises(ErrorCifrado):
            CifradorNulo().descifrar(real)
