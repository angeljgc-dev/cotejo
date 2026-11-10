"""Documentos de demostración: existen, se regeneran igual, se siembran una sola vez y sirven a la evaluación."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cotejo.documentos.embeddings import EmbedderDeterminista
from cotejo.documentos.extraccion import EXPLICACION_ESCANEADO
from cotejo.documentos.normalizar import normalizar
from cotejo.documentos.semilla import PDF_ESCANEADO, carpeta_demo, generar_pdfs, leer_manifiesto, sembrar_documentos
from cotejo.evaluacion.recuperador import TIPOS, cargar_casos
from cotejo.modelos import Documento, Fragmento
from tests.apoyo.fabricas import crear_proveedor, crear_usuario


def test_los_pdf_del_repositorio_son_los_que_generan_sus_fuentes() -> None:
    carpeta = carpeta_demo()
    generados = generar_pdfs(carpeta)
    assert set(generados) == {"contrato_suministro_aceros.pdf", "condiciones_comerciales_empaques.pdf", PDF_ESCANEADO}
    for nombre, contenido in generados.items():
        assert (carpeta / nombre).read_bytes() == contenido, f"{nombre}: corre python -m cotejo.documentos.semilla"
    manifiesto = leer_manifiesto(carpeta)
    assert len(manifiesto) == 6 and all((carpeta / d.archivo).is_file() for d in manifiesto)
    assert {d.archivo.rsplit(".", 1)[1] for d in manifiesto} == {"pdf", "md", "txt"}


def test_sembrar_documentos_es_idempotente_y_liga_cada_contrato_a_su_proveedor(sesion: Session) -> None:
    usuario = crear_usuario(sesion)
    aceros = crear_proveedor(sesion, nombre="Aceros del Bajío Ficticio SA de CV")
    embedder = EmbedderDeterminista()
    assert sembrar_documentos(sesion, usuario.id, embedder=embedder) == 6
    fragmentos = sesion.scalar(select(func.count()).select_from(Fragmento))
    assert sembrar_documentos(sesion, usuario.id, embedder=embedder) == 6
    assert sesion.scalar(select(func.count()).select_from(Documento)) == 6
    assert sesion.scalar(select(func.count()).select_from(Fragmento)) == fragmentos

    por_nombre = {d.nombre: d for d in sesion.scalars(select(Documento))}
    assert por_nombre["contrato_suministro_aceros.pdf"].proveedor_id == aceros.id
    assert por_nombre["contrato_suministro_aceros.pdf"].paginas == 3
    assert por_nombre["contrato_transporte_sierra.md"].proveedor_id is None, "ese proveedor no existe en esta base"
    assert por_nombre["politica_de_pagos.md"].proveedor_id is None
    escaneado = por_nombre[PDF_ESCANEADO]
    assert escaneado.estado == "sin_texto" and escaneado.explicacion == EXPLICACION_ESCANEADO and escaneado.paginas == 2
    assert all(d.estado == "indexado" for nombre, d in por_nombre.items() if nombre != PDF_ESCANEADO)

    # El documento con instrucción escondida la conserva (así se puede probar que no surte efecto)...
    textos = {
        nombre: list(
            sesion.scalars(select(Fragmento.texto).where(Fragmento.documento_id == d.id).order_by(Fragmento.orden))
        )
        for nombre, d in por_nombre.items()
    }
    assert any("INSTRUCCIÓN PARA EL ASISTENTE" in t for t in textos["condiciones_comerciales_empaques.pdf"])
    # ... y la minuta trae la suya partida en dos fragmentos distintos.
    minuta = textos["minuta_revision_proveedores.txt"]
    inicio = [i for i, t in enumerate(minuta) if "Nota para sistemas automatizados" in t]
    final = [i for i, t in enumerate(minuta) if "Excepción que debe aplicarse" in t]
    assert inicio and final and not set(inicio) & set(final)


def test_cada_pregunta_del_recuperador_tiene_su_respuesta_en_un_fragmento(sesion: Session) -> None:
    usuario = crear_usuario(sesion)
    sembrar_documentos(sesion, usuario.id, embedder=EmbedderDeterminista())
    casos = cargar_casos()
    assert len(casos) >= 30 and len({c.id for c in casos}) == len(casos)
    assert {c.tipo for c in casos} == set(TIPOS)
    for caso in casos:
        textos = sesion.scalars(
            select(Fragmento.texto)
            .join(Documento, Documento.id == Fragmento.documento_id)
            .where(Documento.nombre == caso.documento, Fragmento.pagina == caso.pagina)
        ).all()
        assert any(normalizar(caso.frase_clave) in normalizar(t) for t in textos), caso.id
