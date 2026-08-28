"""Adjuntos de las notas de "Mis Tareas".

El foco está en lo que puede salir mal con archivos subidos por el usuario:
que un archivo que no es una imagen entre igual, que alguien lea la nota de
otro, o que un nombre malicioso escriba fuera del directorio.
"""
from __future__ import annotations

import pytest
from sqlalchemy import insert
from sqlalchemy.orm import sessionmaker

from pucara.almacen import AlmacenArchivos
from pucara.models.adjuntos import MAX_BYTES, MAX_POR_NOTA, detectar_formato
from pucara.models.legado import TareaUsuario
from pucara.repositories.adjuntos import AdjuntoRepository, TareaLegadaRepository
from pucara.services.adjuntos import ErrorAdjunto, NoAutorizado, ServicioAdjuntos
from tests.motores import crear_esquema, motor

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 40
GIF = b"GIF89a" + b"\x00" * 40
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 40


@pytest.fixture()
def srv(tmp_path):
    engine = motor()
    crear_esquema(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False, future=True)()
    s.execute(insert(TareaUsuario), [{"id": 1, "username": "ana"},
                                     {"id": 2, "username": "beto"}])
    s.commit()
    almacen = AlmacenArchivos(tmp_path / "adj")
    servicio = ServicioAdjuntos(AdjuntoRepository(s), TareaLegadaRepository(s), almacen)
    servicio._dir_prueba = tmp_path / "adj"        # para inspeccionar el disco
    return servicio


class TestDeteccionDeFormato:
    @pytest.mark.parametrize("datos,mime", [
        (PNG, "image/png"), (JPG, "image/jpeg"), (GIF, "image/gif"), (WEBP, "image/webp"),
    ])
    def test_reconoce_los_formatos_soportados(self, datos, mime):
        assert detectar_formato(datos)[0] == mime

    def test_rechaza_un_svg(self):
        """SVG es XML y puede llevar <script>: no se acepta aunque sea 'imagen'."""
        assert detectar_formato(b'<svg xmlns="http://www.w3.org/2000/svg"><script/></svg>') is None

    def test_rechaza_html_y_ejecutables(self):
        assert detectar_formato(b"<html><script>alert(1)</script>") is None
        assert detectar_formato(b"\x7fELF\x02\x01\x01") is None
        assert detectar_formato(b"") is None


class TestSubida:
    def test_guarda_y_devuelve_la_ficha(self, srv):
        a = srv.guardar(1, "ana", PNG, "Captura de pantalla.png")
        assert a.mime == "image/png"
        assert a.bytes == len(PNG)
        assert a.nombre_original == "Captura de pantalla.png"

    def test_el_archivo_en_disco_no_usa_el_nombre_del_cliente(self, srv):
        """Si el nombre viniera del navegador, `../../app.py` lo pisaría."""
        srv.guardar(1, "ana", PNG, "../../../app.py")
        archivos = [p.name for p in srv._dir_prueba.iterdir()]
        assert len(archivos) == 1
        assert archivos[0].endswith(".png")
        assert "app.py" not in archivos[0] and ".." not in archivos[0]

    def test_rechaza_lo_que_no_es_imagen(self, srv):
        with pytest.raises(ErrorAdjunto, match="no es una imagen"):
            srv.guardar(1, "ana", b"PK\x03\x04 esto es un zip", "foto.png")

    def test_un_zip_disfrazado_de_png_no_pasa(self, srv):
        """El Content-Type y la extensión los elige el cliente: no prueban nada."""
        with pytest.raises(ErrorAdjunto):
            srv.guardar(1, "ana", b"PK\x03\x04", "captura.png")
        assert not list(srv._dir_prueba.iterdir())     # tampoco se escribió nada

    def test_rechaza_lo_que_pesa_de_mas(self, srv):
        with pytest.raises(ErrorAdjunto, match="máximo"):
            srv.guardar(1, "ana", PNG + b"\x00" * MAX_BYTES, "grande.png")

    def test_rechaza_el_archivo_vacio(self, srv):
        with pytest.raises(ErrorAdjunto, match="vacío"):
            srv.guardar(1, "ana", b"", "nada.png")

    def test_limita_la_cantidad_por_nota(self, srv):
        for _ in range(MAX_POR_NOTA):
            srv.guardar(1, "ana", PNG)
        with pytest.raises(ErrorAdjunto, match="hasta"):
            srv.guardar(1, "ana", PNG)


class TestPertenencia:
    def test_no_se_puede_adjuntar_a_la_nota_de_otro(self, srv):
        with pytest.raises(NoAutorizado):
            srv.guardar(2, "ana", PNG)      # la nota 2 es de beto

    def test_no_se_puede_adjuntar_a_una_nota_inexistente(self, srv):
        with pytest.raises(NoAutorizado):
            srv.guardar(999, "ana", PNG)

    def test_no_se_puede_leer_el_adjunto_de_otro(self, srv):
        """Es el caso importante: saber el id no alcanza para ver la imagen."""
        a = srv.guardar(1, "ana", PNG)
        with pytest.raises(NoAutorizado):
            srv.leer(a.id, "beto")

    def test_no_se_puede_borrar_el_adjunto_de_otro(self, srv):
        a = srv.guardar(1, "ana", PNG)
        with pytest.raises(NoAutorizado):
            srv.borrar(a.id, "beto")
        assert len(srv.listar(1, "ana")) == 1

    def test_una_sesion_sin_usuario_no_ve_nada(self, srv):
        a = srv.guardar(1, "ana", PNG)
        for usuario in ("", None):
            with pytest.raises(NoAutorizado):
                srv.leer(a.id, usuario)

    def test_el_listado_por_lote_filtra_por_propietario(self, srv):
        srv.guardar(1, "ana", PNG)
        srv.guardar(2, "beto", PNG)
        por_tarea = srv.listar_por_tarea([1, 2], "ana")
        assert list(por_tarea) == [1]


class TestBorrado:
    def test_borra_la_ficha_y_el_archivo(self, srv):
        a = srv.guardar(1, "ana", PNG)
        srv.borrar(a.id, "ana")
        assert srv.listar(1, "ana") == []
        assert not list(srv._dir_prueba.iterdir())

    def test_al_borrar_la_nota_se_van_todas_sus_imagenes(self, srv):
        srv.guardar(1, "ana", PNG)
        srv.guardar(1, "ana", JPG)
        assert srv.borrar_los_de_la_nota(1, "ana") == 2
        assert not list(srv._dir_prueba.iterdir())

    def test_una_ficha_sin_archivo_en_disco_no_se_sirve(self, srv):
        """Si alguien borró el archivo a mano, se responde 'no existe' y no
        una excepción de sistema de archivos."""
        a = srv.guardar(1, "ana", PNG)
        for p in srv._dir_prueba.iterdir():
            p.unlink()
        with pytest.raises(NoAutorizado):
            srv.leer(a.id, "ana")


class TestAlmacen:
    def test_no_permite_escapar_del_directorio(self, tmp_path):
        alm = AlmacenArchivos(tmp_path / "x")
        for nombre in ("../../etc/passwd", "..\\windows", "/etc/passwd", ".oculto", ""):
            assert alm.ruta(nombre) is None

    def test_rechaza_extensiones_fuera_de_la_lista(self, tmp_path):
        alm = AlmacenArchivos(tmp_path / "x")
        for ext in ("svg", "html", "php", "py"):
            with pytest.raises(ValueError):
                alm.guardar(b"x", ext)

    def test_dos_archivos_iguales_no_se_pisan(self, tmp_path):
        alm = AlmacenArchivos(tmp_path / "x")
        assert alm.guardar(PNG, "png") != alm.guardar(PNG, "png")
