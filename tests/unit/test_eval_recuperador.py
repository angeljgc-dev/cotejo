"""E3 sin base: el calificador del recuperador con resultados fijos."""

from __future__ import annotations

import pytest

from cotejo.documentos.busqueda import Hallazgo
from cotejo.evaluacion.recuperador import CasoRecuperador, calificar, es_acierto, posicion_del_acierto, tabla

CASO = CasoRecuperador("c1", "¿Plazo de pago?", "contrato.pdf", 2, "cuarenta y cinco (45) días")


def hallazgo(fragmento_id: int, documento: str, pagina: int, texto: str) -> Hallazgo:
    return Hallazgo(
        fragmento_id=fragmento_id,
        documento_id=1,
        documento=documento,
        pagina=pagina,
        orden=fragmento_id,
        texto=texto,
        puntaje=1.0 / fragmento_id,
        fuentes=("vector",),
    )


CORRECTO = hallazgo(9, "contrato.pdf", 2, "SEXTA. Pagará dentro de los CUARENTA Y CINCO (45) DIAS naturales.")
OTRA_PAGINA = hallazgo(2, "contrato.pdf", 3, "cuarenta y cinco (45) días")
OTRO_DOCUMENTO = hallazgo(3, "politica.md", 2, "cuarenta y cinco (45) días")
SIN_LA_FRASE = hallazgo(4, "contrato.pdf", 2, "QUINTA. Facturación por cada entrega.")


def test_acierto_exige_documento_pagina_y_frase_sin_importar_acentos_ni_mayusculas() -> None:
    assert es_acierto(CASO, CORRECTO)
    assert not es_acierto(CASO, OTRA_PAGINA)
    assert not es_acierto(CASO, OTRO_DOCUMENTO)
    assert not es_acierto(CASO, SIN_LA_FRASE)


def test_posicion_del_acierto_solo_cuenta_los_primeros_k() -> None:
    assert posicion_del_acierto(CASO, [SIN_LA_FRASE, OTRA_PAGINA, CORRECTO]) == 3
    assert posicion_del_acierto(CASO, [CORRECTO]) == 1
    assert posicion_del_acierto(CASO, [SIN_LA_FRASE] * 5 + [CORRECTO]) is None
    assert posicion_del_acierto(CASO, [SIN_LA_FRASE] * 5 + [CORRECTO], k=6) == 6
    assert posicion_del_acierto(CASO, []) is None


def test_recall_y_mrr_con_resultados_fijos() -> None:
    casos = [
        CASO,
        CasoRecuperador("c2", "p", "contrato.pdf", 2, "cuarenta y cinco (45) días"),
        CasoRecuperador("c3", "p", "contrato.pdf", 2, "cuarenta y cinco (45) días"),
        CasoRecuperador("c4", "p", "contrato.pdf", 2, "cuarenta y cinco (45) días"),
    ]
    resultados = {
        "c1": [CORRECTO],
        "c2": [SIN_LA_FRASE, CORRECTO],
        "c3": [SIN_LA_FRASE, OTRA_PAGINA, OTRO_DOCUMENTO, CORRECTO],
        "c4": [SIN_LA_FRASE],
    }
    metricas = calificar(casos, resultados)
    assert metricas.casos == 4 and metricas.aciertos == 3
    assert metricas.recall_en_k == pytest.approx(0.75)
    assert metricas.mrr == pytest.approx((1 + 1 / 2 + 1 / 4 + 0) / 4)
    assert metricas.fallos == ("c4",)
    # Un caso sin resultados cuenta como fallo, y una batería vacía no divide entre cero.
    assert calificar([CASO], {}).recall_en_k == 0.0
    vacio = calificar([], {})
    assert vacio.casos == 0 and vacio.recall_en_k == 0.0 and vacio.mrr == 0.0


def test_tabla_muestra_cada_variante_con_sus_aciertos_por_tipo() -> None:
    por_tipo = {
        "parafrasis": {"aciertos": 33, "casos": 37},
        "termino_exacto": {"aciertos": 10, "casos": 10},
    }
    resultado: dict[str, object] = {
        "embeddings": "modelo-de-prueba",
        "k": 5,
        "casos": 47,
        "documentos": 5,
        "fragmentos": 25,
        "variantes": [
            {
                "etiqueta": "Híbrida (vector + texto, RRF)",
                "recall_en_k": 0.915,
                "mrr": 0.747,
                "aciertos": 43,
                "casos": 47,
                "por_tipo": por_tipo,
            }
        ],
    }
    texto = tabla(resultado)
    assert "47 preguntas, 25 fragmentos de 5 documentos" in texto
    assert "0.915" in texto and "0.747" in texto and "33/37" in texto and "10/10" in texto
