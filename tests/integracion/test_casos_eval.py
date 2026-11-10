"""E2: la batería del asistente es válida y coherente con la base de demostración sembrada."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from cotejo.asistente.herramientas import HERRAMIENTAS
from cotejo.config import Settings
from cotejo.evaluacion import calificador
from cotejo.evaluacion.casos import MINIMO_TOTAL, MINIMOS_POR_CATEGORIA, cargar_casos, conteo_por_categoria
from cotejo.modelos import Documento, Fragmento
from cotejo.semilla.generador import reiniciar_demo

HOY = date(2026, 11, 2)


@pytest.fixture
def base_sembrada(sesion: Session, config: Settings) -> Session:
    reiniciar_demo(sesion, semilla=config.semilla, fecha_base=HOY)
    sesion.commit()
    return sesion


def test_la_bateria_cubre_las_categorias_con_sus_minimos() -> None:
    casos = cargar_casos()
    conteo = conteo_por_categoria(casos)
    assert len(casos) >= MINIMO_TOTAL
    for categoria, minimo in MINIMOS_POR_CATEGORIA.items():
        assert conteo[categoria] >= minimo, f"{categoria}: {conteo[categoria]} de {minimo}"
    documentos = [c for c in casos if c.categoria == "documentos"]
    assert sum(c.esperado.negativa and c.esperado.sin_citas for c in documentos) >= 3, "preguntas sin respuesta"
    assert sum(bool(c.esperado.citas_incluyen) for c in documentos) >= 7
    # Las herramientas que nombran los casos existen.
    for caso in casos:
        nombradas = [
            *caso.esperado.herramientas_incluye,
            *caso.esperado.herramientas_incluye_alguna,
            *caso.esperado.herramientas_excluye,
            *(c.herramienta for c in caso.esperado.cifras),
        ]
        assert set(nombradas) <= set(HERRAMIENTAS), caso.id
    # Ningún ataque ni negativa espera que algo cambie más allá de una propuesta pendiente.
    for caso in casos:
        if caso.categoria == "negativa":
            assert caso.esperado.propuesta is None, caso.id


def test_lo_esperado_de_cada_caso_se_puede_resolver_contra_la_base_sembrada(
    base_sembrada: Session, config: Settings
) -> None:
    sesion = base_sembrada
    antes = calificador.huella(sesion)
    selecciones = 0
    for caso in cargar_casos():
        expectativa = calificador.preparar(sesion, caso, config, HOY)
        assert expectativa.problemas == (), f"{caso.id}: {expectativa.problemas}"
        assert len(expectativa.cifras) == len(caso.esperado.cifras), caso.id
        for nombre, valor in expectativa.cifras:
            assert valor >= 0, f"{caso.id}: {nombre}"
        if caso.categoria == "numerica":
            assert expectativa.cifras, f"{caso.id}: una pregunta numérica necesita su cifra esperada"
        for cita in caso.esperado.citas_incluyen:
            fragmentos = sesion.scalars(
                select(Fragmento.id)
                .join(Documento, Documento.id == Fragmento.documento_id)
                .where(Documento.nombre == cita.documento, Fragmento.pagina == cita.pagina)
            ).all()
            assert fragmentos, f"{caso.id}: no hay fragmentos de {cita.documento} página {cita.pagina}"
        esperada = caso.esperado.propuesta
        if esperada is not None and esperada.modo == "igual_a_seleccion":
            assert expectativa.seleccion is not None, caso.id
            selecciones += bool(expectativa.seleccion)
    # Resolver lo esperado no deja rastro: ni propuestas de ensayo ni nada más.
    assert calificador.huella(sesion) == antes
    assert selecciones >= 5, "la mayoría de los casos de propuesta deben producir una propuesta real"


def test_las_cifras_esperadas_salen_de_la_base_y_no_son_triviales(base_sembrada: Session, config: Settings) -> None:
    casos = {c.id: c for c in cargar_casos()}
    adeudo = calificador.preparar(base_sembrada, casos["num-01"], config, HOY).cifras[0][1]
    total = calificador.preparar(base_sembrada, casos["num-02"], config, HOY).cifras[0][1]
    vencido = calificador.preparar(base_sembrada, casos["num-04"], config, HOY).cifras[0][1]
    por_vencer = calificador.preparar(base_sembrada, casos["num-11"], config, HOY).cifras[0][1]
    assert 0 < adeudo < total
    assert vencido + por_vencer == total, "vencido más por vencer es el adeudo total"
    # Con 500 pesos no alcanza para ninguna factura vencida: lo correcto es que no se cree propuesta.
    assert calificador.preparar(base_sembrada, casos["pro-03"], config, HOY).seleccion == ()
    assert len(calificador.preparar(base_sembrada, casos["pro-08"], config, HOY).seleccion or ()) > 10
