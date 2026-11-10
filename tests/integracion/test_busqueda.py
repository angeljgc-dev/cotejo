"""C2 con base: la búsqueda combina significado y palabras exactas, y devuelve documento y página."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence

import numpy as np
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cotejo.documentos.busqueda import buscar
from cotejo.documentos.embeddings import Vector
from cotejo.documentos.indexado import indexar_documento
from cotejo.modelos import DIMENSION_EMBEDDING, Usuario
from tests.apoyo.fabricas import crear_proveedor, crear_usuario

Entrar = Callable[[int], None]


class EmbedderDeTemas:
    """Sustituto del modelo de significado: coloca cada texto en el eje de su tema aunque no comparta palabras.

    Imita lo que hace un modelo real con los sinónimos ("me atraso" queda junto a "intereses moratorios") para
    poder probar de forma determinista el SQL de vecinos y la fusión, que es lo que se prueba aquí.
    """

    nombre = "temas"
    TEMAS: tuple[tuple[str, ...], ...] = (
        ("moratorio", "atraso", "retraso"),
        ("garantía", "defectuosa", "descompone"),
        ("vigencia", "dura", "renovará"),
    )

    def _vector(self, texto: str) -> Vector:
        vector = np.zeros(DIMENSION_EMBEDDING, dtype=np.float32)
        minusculas = texto.lower()
        for eje, palabras in enumerate(self.TEMAS):
            if any(p in minusculas for p in palabras):
                vector[eje] = 1.0
        if not vector.any():
            vector[DIMENSION_EMBEDDING - 1] = 1.0
        return vector

    def pasajes(self, textos: Sequence[str]) -> list[Vector]:
        return [self._vector(t) for t in textos]

    def consulta(self, texto: str) -> Vector:
        return self._vector(texto)


MORA = "CLÁUSULA SEXTA. El cliente pagará un interés moratorio del 1.5% mensual sobre saldos insolutos."
GARANTIA = "CLÁUSULA SÉPTIMA. Garantía de doce meses contra vicios ocultos y defectos de fabricación."
VIGENCIA = "CLÁUSULA DÉCIMA. Vigencia de un año; se renovará por periodos iguales salvo aviso en contrario."
CODIGO = "ANEXO DE GARANTÍA. Las refacciones se surten bajo el número de parte XK-4471 del catálogo del fabricante."


def _indexar(sesion: Session, usuario: Usuario, nombre: str, texto: str, proveedor_id: int | None = None) -> int:
    contenido = texto.encode()
    indexado = indexar_documento(
        sesion,
        nombre=nombre,
        tipo="txt",
        contenido=contenido,
        sha256=hashlib.sha256(contenido).hexdigest(),
        proveedor_id=proveedor_id,
        usuario_id=usuario.id,
        embedder=EmbedderDeTemas(),
    )
    return indexado.documento.id


def test_el_significado_encuentra_lo_que_las_palabras_no(sesion: Session) -> None:
    usuario = crear_usuario(sesion)
    for nombre, texto in (("garantia.txt", GARANTIA), ("vigencia.txt", VIGENCIA), ("mora.txt", MORA)):
        _indexar(sesion, usuario, nombre, texto)
    pregunta = "¿Qué sucede si tengo un atraso?"
    # Ninguna palabra de la pregunta está en la cláusula de mora: por palabras no hay nada.
    assert buscar(sesion, pregunta, embedder=EmbedderDeTemas(), modo="texto") == []
    hibrida = buscar(sesion, pregunta, embedder=EmbedderDeTemas(), modo="hibrida")
    assert hibrida[0].documento == "mora.txt" and hibrida[0].pagina == 1
    assert hibrida[0].fuentes == ("vector",)
    assert "interés moratorio" in hibrida[0].texto


def test_la_palabra_exacta_encuentra_lo_que_el_significado_no(sesion: Session) -> None:
    usuario = crear_usuario(sesion)
    for nombre, texto in (
        ("mora.txt", MORA),
        ("garantia.txt", GARANTIA),
        ("vigencia.txt", VIGENCIA),
        ("anexo.txt", CODIGO),
    ):
        _indexar(sesion, usuario, nombre, texto)
    # Un número de parte no tiene "significado": para el vector todos los textos quedan igual de lejos.
    solo_vector = buscar(sesion, "XK-4471", embedder=EmbedderDeTemas(), modo="vector")
    assert solo_vector[0].documento != "anexo.txt"
    solo_texto = buscar(sesion, "XK-4471", embedder=EmbedderDeTemas(), modo="texto")
    assert [h.documento for h in solo_texto] == ["anexo.txt"]
    hibrida = buscar(sesion, "XK-4471", embedder=EmbedderDeTemas(), modo="hibrida")
    assert hibrida[0].documento == "anexo.txt"
    assert set(hibrida[0].fuentes) == {"vector", "texto"}
    assert hibrida[0].puntaje > hibrida[1].puntaje


def test_las_palabras_coinciden_sin_acentos_y_por_raiz(sesion: Session) -> None:
    usuario = crear_usuario(sesion)
    _indexar(sesion, usuario, "garantia.txt", GARANTIA)
    _indexar(sesion, usuario, "vigencia.txt", VIGENCIA)
    for consulta in ("garantia", "GARANTÍAS", "defecto de fabricacion"):
        hallazgos = buscar(sesion, consulta, embedder=EmbedderDeTemas(), modo="texto")
        assert [h.documento for h in hallazgos] == ["garantia.txt"], consulta
    # Solo palabras vacías: no hay términos que buscar y no truena.
    assert buscar(sesion, "de la que", embedder=EmbedderDeTemas(), modo="texto") == []


def test_una_pregunta_larga_no_exige_todas_sus_palabras(sesion: Session) -> None:
    usuario = crear_usuario(sesion)
    _indexar(sesion, usuario, "garantia.txt", GARANTIA)
    _indexar(sesion, usuario, "vigencia.txt", VIGENCIA)
    pregunta = "¿Cuántos meses de garantía ofrece el proveedor de tornillos?"
    assert buscar(sesion, pregunta, embedder=EmbedderDeTemas(), modo="texto", todas_las_palabras=True) == []
    flexible = buscar(sesion, pregunta, embedder=EmbedderDeTemas(), modo="texto")
    assert flexible[0].documento == "garantia.txt"


def test_filtro_por_proveedor_incluye_las_politicas_generales(sesion: Session) -> None:
    usuario = crear_usuario(sesion)
    propio, ajeno = crear_proveedor(sesion), crear_proveedor(sesion)
    _indexar(sesion, usuario, "contrato_propio.txt", GARANTIA + " Proveedor uno.", propio.id)
    _indexar(sesion, usuario, "contrato_ajeno.txt", GARANTIA + " Proveedor dos.", ajeno.id)
    _indexar(sesion, usuario, "politica_general.txt", "Política general: toda garantía se reclama por escrito.")
    documentos = {h.documento for h in buscar(sesion, "garantía", embedder=EmbedderDeTemas(), proveedor_id=propio.id)}
    assert documentos == {"contrato_propio.txt", "politica_general.txt"}
    todos = {h.documento for h in buscar(sesion, "garantía", embedder=EmbedderDeTemas())}
    assert todos == {"contrato_propio.txt", "contrato_ajeno.txt", "politica_general.txt"}
    uno = buscar(sesion, "garantía", embedder=EmbedderDeTemas(), k=1)
    assert len(uno) == 1


def test_ruta_de_busqueda_devuelve_documento_pagina_y_fuentes(
    cliente: TestClient, sesion: Session, entrar_como: Entrar
) -> None:
    assert cliente.get("/api/busqueda", params={"q": "garantía"}).status_code == 401
    entrar_como(crear_usuario(sesion, rol="capturista").id)
    for nombre, texto in (("garantia.txt", GARANTIA), ("mora.txt", MORA)):
        r = cliente.post("/api/documentos", files=[("archivos", (nombre, texto.encode(), "text/plain"))])
        assert r.status_code == 200, r.text
    r = cliente.get("/api/busqueda", params={"q": "garantía contra defectos", "k": 2})
    assert r.status_code == 200, r.text
    resultados = r.json()["resultados"]
    assert len(resultados) == 2
    primero = resultados[0]
    assert primero["documento"] == "garantia.txt" and primero["pagina"] == 1
    assert set(primero["fuentes"]) == {"vector", "texto"}
    assert set(primero) == {"fragmento_id", "documento_id", "documento", "pagina", "texto", "puntaje", "fuentes"}
    assert isinstance(primero["puntaje"], float) and primero["puntaje"] > resultados[1]["puntaje"]
    assert cliente.get("/api/busqueda", params={"q": "g"}).status_code == 422
    assert cliente.get("/api/busqueda", params={"q": "garantía", "k": 11}).status_code == 422
