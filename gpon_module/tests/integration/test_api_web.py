"""API y páginas web, de punta a punta contra la OLT simulada.

El test que más importa de este archivo es el último: verifica que la web
**no importa** servicios ni drivers. Ese límite es la razón de que exista la
API, y sin un test que lo sostenga se erosiona en la primera urgencia.
"""

from __future__ import annotations

import pytest

flask = pytest.importorskip("flask", reason="la interfaz web necesita Flask")

from gpon_module.drivers.mock import FallasSimuladas  # noqa: E402
from gpon_module.web import crear_app  # noqa: E402


@pytest.fixture
def cliente(sistema, olt):
    sistema.servicio_descubrimiento.descubrir(olt.id)
    app = crear_app(sistema)
    app.config.update(TESTING=True)
    return app.test_client()


class TestAPILectura:
    def test_salud(self, cliente) -> None:
        datos = cliente.get("/api/salud").get_json()
        assert datos["ok"] is True
        assert datos["olts"] == 1
        assert datos["dry_run_por_defecto"] is True

    def test_la_salud_no_filtra_la_ruta_de_la_base(self, cliente) -> None:
        """El panel muestra el motor, no dónde vive el archivo."""
        assert "…" in cliente.get("/api/salud").get_json()["base_datos"]

    def test_listar_olts(self, cliente, olt) -> None:
        datos = cliente.get("/api/olts").get_json()
        assert len(datos) == 1
        assert datos[0]["host"] == olt.host
        # Ninguna credencial sale por la API, ni cifrada.
        assert not any("password" in clave or "comunidad" in clave for clave in datos[0])

    def test_detalle_de_olt_incluye_capacidades(self, cliente, olt) -> None:
        datos = cliente.get(f"/api/olts/{olt.id}").get_json()
        assert "POTENCIA_OPTICA" in datos["capacidades"]
        assert datos["ultima_corrida"]["resultado"] == "completa"

    def test_inventario_paginado(self, cliente, olt, parque) -> None:
        datos = cliente.get(f"/api/olts/{olt.id}/onus?limite=5").get_json()
        assert datos["total"] == len(parque.onus)
        assert len(datos["resultados"]) == 5

    def test_filtro_por_estado_y_por_puerto(self, cliente, olt) -> None:
        en_linea = cliente.get(f"/api/olts/{olt.id}/onus?estado=en_linea&limite=999").get_json()
        assert all(o["estado"] == "en_linea" for o in en_linea["resultados"])

        pon2 = cliente.get(f"/api/olts/{olt.id}/onus?pon=2&limite=999").get_json()
        assert all(o["pon"] == 2 for o in pon2["resultados"])

    def test_busqueda_por_nombre(self, cliente, olt) -> None:
        datos = cliente.get(f"/api/olts/{olt.id}/onus?buscar=CLI10&limite=999").get_json()
        assert datos["total"] >= 1

    def test_resumen_separa_corte_de_luz_de_fibra_cortada(self, cliente, olt) -> None:
        datos = cliente.get(f"/api/olts/{olt.id}/resumen").get_json()
        assert set(datos["por_motivo_caida"]) <= {"apagado", "perdida_senal", "desconocido"}
        assert sum(datos["por_estado"].values()) == datos["total_onus"]

    def test_potencias_llegan_ya_clasificadas(self, cliente, olt) -> None:
        """La regla de qué es "saturada" pertenece al dominio, no al navegador."""
        datos = cliente.get(f"/api/olts/{olt.id}/potencias").get_json()
        assert datos["resumen"]
        assert all("clasificacion" in lectura for lectura in datos["lecturas"])

    def test_una_onu_caida_viaja_como_null_y_no_como_cero(self, cliente, olt) -> None:
        datos = cliente.get(f"/api/olts/{olt.id}/potencias").get_json()
        sin_lectura = [
            le for le in datos["lecturas"] if le["clasificacion"] == "sin_lectura"
        ]
        assert sin_lectura
        assert all(le["rx_onu_dbm"] is None for le in sin_lectura)

    def test_capacidades_declara_las_dos_listas(self, cliente, olt) -> None:
        datos = cliente.get(f"/api/olts/{olt.id}/capacidades").get_json()
        assert datos["soportadas"]
        assert isinstance(datos["no_soportadas"], list)

    def test_catalogo_de_drivers(self, cliente) -> None:
        datos = cliente.get("/api/fabricantes").get_json()
        fabricantes = {d["fabricante"] for d in datos}
        assert {"simulado", "vsol"} <= fabricantes
        vsol = next(d for d in datos if d["fabricante"] == "vsol")
        # Lo verificado en Fase 0 llega hasta la interfaz.
        assert "TRAFICO_POR_ONU" not in vsol["capacidades"]
        assert "SERIAL_POR_SNMP" not in vsol["capacidades"]


class TestAPIErrores:
    def test_una_olt_inexistente_da_404_y_no_una_traza(self, cliente) -> None:
        respuesta = cliente.get("/api/olts/999")
        assert respuesta.status_code == 404
        assert respuesta.get_json()["error"] == "no_encontrado"

    def test_una_capacidad_ausente_da_501(self, cliente, sistema, olt) -> None:
        """501 y no 400: la petición es válida, el equipo no sabe hacerlo."""
        from gpon_module.core.enums import Capacidad
        from gpon_module.drivers.mock import PERFIL_VSOL

        sistema.fabrica_drivers._extras["capacidades"] = PERFIL_VSOL - {
            Capacidad.REINICIAR_ONU
        }
        respuesta = cliente.post(f"/api/olts/{olt.id}/onus/1/1/reiniciar", json={})
        assert respuesta.status_code == 501
        assert respuesta.get_json()["error"] == "capacidad_no_soportada"

    def test_un_equipo_inalcanzable_da_502(self, cliente, sistema, olt) -> None:
        """502: el problema está entre nosotros y la OLT, no en la petición."""
        sistema.fabrica_drivers._extras["fallas"] = FallasSimuladas(conexion_falla=True)
        respuesta = cliente.get(f"/api/olts/{olt.id}/potencias")
        assert respuesta.status_code == 502
        assert respuesta.get_json()["error"] == "sin_comunicacion"

    def test_un_parametro_invalido_da_400(self, cliente, olt) -> None:
        respuesta = cliente.get(f"/api/olts/{olt.id}/onus?limite=muchas")
        assert respuesta.status_code == 400


class TestAPIEscritura:
    def test_por_defecto_la_operacion_sale_simulada(self, cliente, olt, parque) -> None:
        """El navegador no decide si se toca el equipo. Decide la configuración."""
        ref = next(iter(sorted(parque.onus)))
        datos = cliente.post(
            f"/api/olts/{olt.id}/onus/{ref.pon}/{ref.onu_id}/reiniciar", json={}
        ).get_json()

        assert datos["ok"] is True
        assert datos["simulado"] is True
        assert datos["comandos"]

    def test_ejecutar_de_verdad_hay_que_pedirlo_en_el_cuerpo(
        self, cliente, olt, parque
    ) -> None:
        ref = next(iter(sorted(parque.onus)))
        datos = cliente.post(
            f"/api/olts/{olt.id}/onus/{ref.pon}/{ref.onu_id}/reiniciar",
            json={"dry_run": False, "usuario": "tecnico1"},
        ).get_json()
        assert datos["simulado"] is False

    def test_toda_operacion_queda_en_la_auditoria(self, cliente, olt, parque) -> None:
        ref = next(iter(sorted(parque.onus)))
        cliente.post(
            f"/api/olts/{olt.id}/onus/{ref.pon}/{ref.onu_id}/reiniciar",
            json={"usuario": "tecnico1"},
        )
        operaciones = cliente.get(f"/api/operaciones?olt_id={olt.id}").get_json()
        assert operaciones[0]["usuario"] == "tecnico1"
        assert operaciones[0]["simulado"] is True


class TestPaginas:
    @pytest.mark.parametrize(
        "ruta",
        ["/", "/olts", "/eventos", "/operaciones", "/capacidades"],
    )
    def test_las_paginas_generales_responden(self, cliente, ruta: str) -> None:
        assert cliente.get(ruta).status_code == 200

    @pytest.mark.parametrize(
        "plantilla", ["/olts/{id}", "/olts/{id}/onus", "/olts/{id}/potencias"]
    )
    def test_las_paginas_de_una_olt_responden(self, cliente, olt, plantilla: str) -> None:
        assert cliente.get(plantilla.format(id=olt.id)).status_code == 200

    def test_la_pagina_de_una_onu_responde(self, cliente, olt) -> None:
        assert cliente.get(f"/olts/{olt.id}/onus/1/1").status_code == 200

    def test_bootstrap_se_sirve_local_y_no_desde_un_cdn(self, cliente) -> None:
        """Un servidor de NOC suele no tener salida a internet."""
        html = cliente.get("/").get_data(as_text=True)
        assert "cdn.jsdelivr.net" not in html
        assert "vendor/bootstrap.min.css" in html
        assert cliente.get("/estatico/vendor/bootstrap.min.css").status_code == 200
        assert cliente.get("/estatico/vendor/chart.umd.min.js").status_code == 200


class TestLimiteDeCapas:
    def test_la_web_no_importa_servicios_ni_drivers(self) -> None:
        """El requisito explícito del diseño, sostenido por un test.

        Las páginas consumen la API por HTTP. Si una ruta web empieza a llamar
        a un servicio, el límite se rompió y esto lo detecta.
        """
        import ast
        import pathlib

        rutas_web = pathlib.Path(__file__).resolve().parents[2] / "web" / "rutas.py"
        arbol = ast.parse(rutas_web.read_text(encoding="utf-8"))

        importados: list[str] = []
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Import):
                importados += [alias.name for alias in nodo.names]
            elif isinstance(nodo, ast.ImportFrom):
                importados.append(nodo.module or "")

        prohibidos = ("services", "drivers", "database", "core")
        filtrados = [
            modulo
            for modulo in importados
            for prohibido in prohibidos
            if prohibido in modulo
        ]
        assert filtrados == [], f"web/rutas.py no debe importar: {filtrados}"

    def test_las_plantillas_no_reciben_datos_del_dominio(self) -> None:
        """Las páginas son cáscaras: los datos los pide el navegador a la API."""
        import pathlib
        import re

        rutas_web = pathlib.Path(__file__).resolve().parents[2] / "web" / "rutas.py"
        for llamada in re.findall(r"render_template\((.*?)\)", rutas_web.read_text(), re.S):
            # Sólo se admiten identificadores de contexto, nunca entidades.
            assert "onu=" not in llamada and "olt=" not in llamada.replace("olt_id=", "")
