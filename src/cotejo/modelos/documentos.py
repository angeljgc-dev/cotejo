"""Documentos (contratos, políticas) y sus fragmentos indexados para la búsqueda híbrida."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from pgvector.sqlalchemy import Vector
from sqlalchemy import CHAR, CheckConstraint, ForeignKey, Index, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cotejo.modelos.base import Base, CreadoEn, IdPk, Texto, TextoNulo

DIMENSION_EMBEDDING = 384


class Documento(Base):
    __tablename__ = "documentos"
    __table_args__ = (
        CheckConstraint("tipo in ('pdf','txt','md')", name="tipo_valido"),
        CheckConstraint("estado in ('indexado','sin_texto')", name="estado_valido"),
        CheckConstraint("estado <> 'sin_texto' or explicacion is not null", name="sin_texto_explicado"),
        CheckConstraint("paginas >= 0", name="paginas_no_negativas"),
    )

    id: Mapped[IdPk]
    nombre: Mapped[Texto]
    tipo: Mapped[Texto]
    sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False, unique=True)
    proveedor_id: Mapped[int | None] = mapped_column(ForeignKey("proveedores.id"), nullable=True)
    paginas: Mapped[int] = mapped_column(Integer, nullable=False)
    estado: Mapped[Texto]
    explicacion: Mapped[TextoNulo]
    subido_por: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), nullable=False)
    creado_en: Mapped[CreadoEn]

    fragmentos: Mapped[list[Fragmento]] = relationship(
        back_populates="documento", cascade="all, delete-orphan", passive_deletes=True
    )


class Fragmento(Base):
    __tablename__ = "fragmentos"
    __table_args__ = (
        CheckConstraint("pagina >= 1", name="pagina_positiva"),
        UniqueConstraint("documento_id", "pagina", "orden"),
        Index(
            "ix_fragmentos_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_fragmentos_tsv", "tsv", postgresql_using="gin"),
        Index("ix_fragmentos_documento", "documento_id"),
    )

    id: Mapped[IdPk]
    documento_id: Mapped[int] = mapped_column(ForeignKey("documentos.id", ondelete="CASCADE"), nullable=False)
    pagina: Mapped[int] = mapped_column(Integer, nullable=False)
    orden: Mapped[int] = mapped_column(Integer, nullable=False)
    texto: Mapped[Texto]
    texto_normalizado: Mapped[Texto]
    # Se llena en el INSERT con to_tsvector('spanish', texto_normalizado).
    tsv: Mapped[str] = mapped_column(TSVECTOR, nullable=False)
    embedding: Mapped[NDArray[np.float32]] = mapped_column(Vector(DIMENSION_EMBEDDING), nullable=False)

    documento: Mapped[Documento] = relationship(back_populates="fragmentos")
