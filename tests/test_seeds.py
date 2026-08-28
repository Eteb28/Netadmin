"""La carga inicial de catálogos tiene que poder correrse muchas veces."""
from __future__ import annotations

from pucara.repositories.reclamos import CausaRepository, ResolucionRepository
from pucara.seeds import CAUSAS, RESOLUCIONES, sembrar


def test_siembra_todo_el_catalogo(sesion):
    agregados = sembrar(sesion)
    sesion.commit()
    assert agregados == {"causas": len(CAUSAS), "resoluciones": len(RESOLUCIONES)}
    assert len(CausaRepository(sesion).listar()) == len(CAUSAS)


def test_es_idempotente(sesion):
    sembrar(sesion)
    sesion.commit()
    assert sembrar(sesion) == {"causas": 0, "resoluciones": 0}
    assert len(CausaRepository(sesion).listar()) == len(CAUSAS)


def test_no_revive_lo_que_el_usuario_desactivo(sesion):
    """Si alguien dio de baja 'Facturación', un redeploy no debe devolvérsela."""
    sembrar(sesion)
    sesion.commit()
    repo = CausaRepository(sesion)
    facturacion = repo.buscar_por_nombre("Facturación")
    repo.desactivar(facturacion.id)
    sesion.commit()

    sembrar(sesion)
    sesion.commit()
    assert repo.buscar_por_nombre("Facturación").activo is False
    assert len(repo.listar()) == len(CAUSAS) - 1


def test_otro_queda_al_final(sesion):
    """'Otro' es el cajón de sastre: nunca debe aparecer primero en el desplegable."""
    sembrar(sesion)
    sesion.commit()
    for repo in (CausaRepository(sesion), ResolucionRepository(sesion)):
        assert repo.listar()[-1].nombre == "Otro"
