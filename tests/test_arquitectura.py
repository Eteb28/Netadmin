"""Hace cumplir las reglas del ADR-0001 de forma automática.

Sin esto, "no dejar SQL fuera del Repository" es una intención que se erosiona
con cada apuro. Acá es una prueba que falla en CI.
"""
from __future__ import annotations

import pathlib
import re

RAIZ = pathlib.Path(__file__).resolve().parent.parent / "pucara"


def _archivos(subcarpeta: str) -> list[pathlib.Path]:
    return [p for p in (RAIZ / subcarpeta).rglob("*.py") if p.name != "__init__.py"]


class TestReglasDeCapas:
    def test_los_servicios_no_conocen_http(self):
        """services/ es lógica de negocio: no debe depender de Flask."""
        infractores = [
            p.name for p in _archivos("services")
            if re.search(r"^\s*(from|import)\s+flask", p.read_text(encoding="utf-8"), re.M)
        ]
        assert not infractores, f"Servicios que importan flask: {infractores}"

    def test_los_servicios_no_arman_consultas(self):
        """El acceso a datos va en repositories/, no en services/."""
        infractores = []
        for p in _archivos("services"):
            texto = p.read_text(encoding="utf-8")
            if re.search(r"\bsession\.(execute|query)\b|\bselect\(", texto):
                infractores.append(p.name)
        assert not infractores, f"Servicios con consultas: {infractores}"

    def test_la_api_no_toca_repositorios_ni_modelos(self):
        """La API habla con Services. Si toca repos, se saltea la lógica.

        Vale igual para los adaptadores no-HTTP (pollers, cron): son la misma
        capa de entrada, con la misma regla.
        """
        infractores = []
        for p in _archivos("api") + _archivos("adaptadores"):
            texto = p.read_text(encoding="utf-8")
            if re.search(r"from\s+pucara\.repositories", texto):
                infractores.append(p.name)
        assert not infractores, f"API accediendo a repositorios: {infractores}"

    def test_nadie_abre_la_base_por_su_cuenta(self):
        """Toda conexión pasa por pucara/db.py (hoy hay 19 archivos que no)."""
        infractores = []
        for p in RAIZ.rglob("*.py"):
            if p.name == "db.py":
                continue
            if "sqlite3.connect" in p.read_text(encoding="utf-8"):
                infractores.append(p.name)
        assert not infractores, f"Archivos con sqlite3.connect: {infractores}"

    def test_el_sql_crudo_solo_vive_en_repositories(self):
        """text() está permitido, pero únicamente dentro de repositories/."""
        infractores = []
        for carpeta in ("services", "api", "models", "dto", "adaptadores"):
            for p in _archivos(carpeta):
                if re.search(r"\btext\(\s*['\"]\s*SELECT", p.read_text(encoding="utf-8"), re.I):
                    infractores.append(f"{carpeta}/{p.name}")
        assert not infractores, f"SQL crudo fuera de repositories: {infractores}"


    def test_la_api_no_usa_atributos_privados(self):
        """Alcanzar `servicio._repo` es saltearse la capa por la ventana.

        Si a la API le falta un dato, el servicio expone un método; no se le
        mete la mano adentro. (Esta regla nació de una violación real: la vista
        de pendientes de rescisión llamaba a `servicio_antiguedad(s)._r`.)
        """
        infractores = []
        for p in _archivos("api"):
            for n, linea in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                if re.search(r"\)\._[a-z]|\b[a-z_]+\._[a-z]\w*\s*\(", linea):
                    infractores.append(f"{p.name}:{n}")
        assert not infractores, f"API tocando atributos privados: {infractores}"


class TestAlcanceDeLaFase6:
    """El pedido fue explícito: 'no es necesario escribir en la OLT, sólo listar'.

    Se verifica acá para que nadie agregue una acción de baja sin discutirlo.
    """

    def test_pendientes_de_rescision_es_solo_lectura(self):
        texto = (RAIZ / "api" / "analitica.py").read_text(encoding="utf-8")
        # Cubre cualquier blueprint del módulo (bp, bp_rescisiones, …)
        escrituras = re.findall(r"@bp\w*\.(post|put|patch|delete)", texto)
        assert not escrituras, f"El módulo de fase 6 debe ser sólo lectura, tiene: {escrituras}"

    def test_el_servicio_de_rescisiones_no_escribe(self):
        texto = (RAIZ / "services" / "rescisiones.py").read_text(encoding="utf-8")
        assert not re.search(r"\b(commit|add|delete|update|flush)\s*\(", texto), (
            "El servicio de rescisiones no debe modificar nada"
        )


class TestTamanoDeArchivos:
    def test_ningun_archivo_gigante(self):
        """El pedido pide no crear archivos gigantes. app.py llegó a 9.858
        líneas justamente por no tener este límite."""
        grandes = [
            f"{p.relative_to(RAIZ)} ({len(p.read_text(encoding='utf-8').splitlines())} líneas)"
            for p in RAIZ.rglob("*.py")
            if len(p.read_text(encoding="utf-8").splitlines()) > 500
        ]
        assert not grandes, f"Archivos que superan las 500 líneas: {grandes}"
