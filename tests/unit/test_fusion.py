"""C2 sin base: fusión por rango recíproco con listas fijas y el embedder determinista de pruebas."""

from __future__ import annotations

import numpy as np
import pytest

from cotejo.documentos.busqueda import CONSTANTE_RRF, fusionar_rrf
from cotejo.documentos.embeddings import EmbedderDeterminista
from cotejo.modelos import DIMENSION_EMBEDDING


def test_rrf_suma_los_rangos_reciprocos_de_cada_lista() -> None:
    fusion = fusionar_rrf({"vector": [10, 20, 30], "texto": [20, 40]}, k=5)
    assert [f.fragmento_id for f in fusion] == [20, 10, 40, 30]
    por_id = {f.fragmento_id: f for f in fusion}
    assert por_id[20].puntaje == pytest.approx(1 / (CONSTANTE_RRF + 2) + 1 / (CONSTANTE_RRF + 1))
    assert por_id[10].puntaje == pytest.approx(1 / (CONSTANTE_RRF + 1))
    assert por_id[20].fuentes == ("vector", "texto")
    assert por_id[10].fuentes == ("vector",)
    assert por_id[40].fuentes == ("texto",)


def test_rrf_el_que_esta_en_las_dos_listas_le_gana_al_primero_de_una_sola() -> None:
    fusion = fusionar_rrf({"vector": [1, 2, 3, 4, 5, 6, 7, 8, 9], "texto": [9]}, k=3)
    assert fusion[0].fragmento_id == 9


def test_rrf_empata_por_id_y_respeta_k() -> None:
    fusion = fusionar_rrf({"vector": [7], "texto": [3]}, k=1)
    assert [f.fragmento_id for f in fusion] == [3]
    assert fusionar_rrf({}, k=5) == []
    assert fusionar_rrf({"vector": [], "texto": []}, k=5) == []


def test_embedder_determinista_es_estable_normalizado_y_agrupa_por_palabras() -> None:
    embedder = EmbedderDeterminista()
    a = embedder.consulta("Plazo de pago de treinta días")
    b = embedder.pasajes(["plazo de PAGO de treinta dias"])[0]
    c = embedder.consulta("garantía contra defectos de fabricación")
    assert a.shape == (DIMENSION_EMBEDDING,)
    assert np.allclose(a, b), "mismas palabras sin importar acentos ni mayúsculas"
    assert float(np.linalg.norm(a)) == pytest.approx(1.0, abs=1e-5)
    assert float(a @ b) > float(a @ c)
    assert float(np.linalg.norm(embedder.consulta("¿?"))) == pytest.approx(1.0)
