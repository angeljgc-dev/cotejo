"""Alta de un documento: texto por página, fragmentos, vectores e índice de palabras (C1, C3)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal

from sqlalchemy import cast, func, insert, select
from sqlalchemy.dialects.postgresql import REGCONFIG
from sqlalchemy.orm import Session

from cotejo.documentos.embeddings import Embedder
from cotejo.documentos.extraccion import extraer
from cotejo.documentos.fragmentador import fragmentar_pagina
from cotejo.documentos.normalizar import normalizar
from cotejo.modelos import Documento, Fragmento, Proveedor

# Configuración de texto completo integrada en PostgreSQL: raíces de palabras y palabras vacías del español.
IDIOMA = cast("spanish", REGCONFIG)
_SEPARADORES = re.compile(r"[_\-.]+")


@dataclass(frozen=True)
class DocumentoIndexado:
    resultado: Literal["indexado", "sin_texto", "duplicado"]
    documento: Documento
    fragmentos: int


def contexto_documento(nombre: str, proveedor_nombre: str | None) -> str:
    """Título legible del documento y su proveedor, que acompaña a cada fragmento al indexarlo.

    Una cláusula suelta ("JURISDICCIÓN. Las partes se someten...") no dice de qué contrato es. Con este contexto,
    una pregunta que nombra al proveedor o al tipo de documento encuentra las cláusulas de ese documento. El
    texto que se guarda para mostrar y citar no cambia.
    """
    titulo = _SEPARADORES.sub(" ", PurePosixPath(nombre).stem).strip()
    return f"{titulo} ({proveedor_nombre})" if proveedor_nombre else titulo


def contar_fragmentos(sesion: Session, documento_id: int) -> int:
    return sesion.scalar(select(func.count()).select_from(Fragmento).where(Fragmento.documento_id == documento_id)) or 0


def indexar_documento(
    sesion: Session,
    *,
    nombre: str,
    tipo: str,
    contenido: bytes,
    sha256: str,
    proveedor_id: int | None,
    usuario_id: int,
    embedder: Embedder,
) -> DocumentoIndexado:
    """Guarda el documento y sus fragmentos en la transacción en curso. No hace commit.

    El mismo archivo (mismo SHA-256) no se duplica. Lanza `DocumentoRechazado` si el archivo no se puede leer.
    """
    existente = sesion.scalar(select(Documento).where(Documento.sha256 == sha256))
    if existente is not None:
        return DocumentoIndexado("duplicado", existente, contar_fragmentos(sesion, existente.id))

    extraido = extraer(tipo, contenido)
    documento = Documento(
        nombre=nombre,
        tipo=tipo,
        sha256=sha256,
        proveedor_id=proveedor_id,
        paginas=len(extraido.paginas),
        estado="sin_texto" if extraido.sin_texto else "indexado",
        explicacion=extraido.explicacion_sin_texto,
        subido_por=usuario_id,
    )
    sesion.add(documento)
    sesion.flush()
    if extraido.sin_texto:
        return DocumentoIndexado("sin_texto", documento, 0)

    piezas: list[tuple[int, str]] = []
    for numero, texto in enumerate(extraido.paginas, start=1):
        piezas.extend((numero, fragmento) for fragmento in fragmentar_pagina(texto))
    proveedor_nombre = sesion.scalar(select(Proveedor.nombre).where(Proveedor.id == proveedor_id))
    contexto = contexto_documento(nombre, proveedor_nombre)
    vectores = embedder.pasajes([f"{contexto}. {texto}" for _, texto in piezas])
    contexto_normalizado = normalizar(contexto)
    renglones = []
    for orden, ((pagina, texto), vector) in enumerate(zip(piezas, vectores, strict=True), start=1):
        normalizado = normalizar(texto)
        renglones.append(
            {
                "documento_id": documento.id,
                "pagina": pagina,
                "orden": orden,
                "texto": texto,
                "texto_normalizado": normalizado,
                "tsv": func.to_tsvector(IDIOMA, f"{contexto_normalizado} {normalizado}"),
                "embedding": vector,
            }
        )
    for renglon in renglones:
        # Un INSERT por fragmento: cada uno lleva su propia expresión to_tsvector.
        sesion.execute(insert(Fragmento).values(**renglon))
    return DocumentoIndexado("indexado", documento, len(renglones))
