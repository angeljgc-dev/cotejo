"""Conversaciones del asistente y propuestas de pago."""

from __future__ import annotations

import uuid as uuid_mod
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    ARRAY,
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cotejo.modelos.base import Base, CreadoEn, IdPk, ImportePropio, Texto, TextoNulo


class Conversacion(Base):
    __tablename__ = "conversaciones"
    __table_args__ = (Index("ix_conversaciones_usuario", "usuario_id"),)

    id: Mapped[uuid_mod.UUID] = mapped_column(Uuid, primary_key=True, server_default=func.gen_random_uuid())
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), nullable=False)
    visitante: Mapped[Texto]
    creado_en: Mapped[CreadoEn]


class MensajeChat(Base):
    __tablename__ = "mensajes_chat"
    __table_args__ = (
        CheckConstraint("rol in ('usuario','asistente')", name="rol_valido"),
        Index("ix_mensajes_chat_conversacion", "conversacion_id"),
    )

    id: Mapped[IdPk]
    conversacion_id: Mapped[uuid_mod.UUID] = mapped_column(
        ForeignKey("conversaciones.id", ondelete="CASCADE"), nullable=False
    )
    rol: Mapped[Texto]
    texto: Mapped[Texto]
    herramientas: Mapped[list[object]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    facturas_base: Mapped[list[int]] = mapped_column(
        ARRAY(BigInteger), nullable=False, server_default=text("'{}'::bigint[]")
    )
    citas: Mapped[list[object]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    advertencias: Mapped[list[object]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    # use_alter rompe el ciclo propuestas <-> mensajes_chat.
    propuesta_id: Mapped[int | None] = mapped_column(ForeignKey("propuestas.id", use_alter=True), nullable=True)
    modelo: Mapped[TextoNulo]
    version_prompt: Mapped[TextoNulo]
    pasos: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_entrada: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_salida: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latencia_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[TextoNulo]
    creado_en: Mapped[CreadoEn]


class Propuesta(Base):
    """Propuesta de pago. Una vez decidida no se edita (trigger propuestas_inmutables)."""

    __tablename__ = "propuestas"
    __table_args__ = (
        CheckConstraint("estado in ('pendiente','aprobada','rechazada')", name="estado_valido"),
        CheckConstraint("presupuesto_mxn > 0", name="presupuesto_positivo"),
        CheckConstraint("total_mxn >= 0 and total_mxn <= presupuesto_mxn", name="total_en_presupuesto"),
        CheckConstraint("origen in ('asistente','mcp','api')", name="origen_valido"),
        CheckConstraint("decidida_por is null or decidida_por <> creada_por", name="decide_otra_persona"),
        CheckConstraint("(estado = 'pendiente') = (decidida_por is null)", name="decision_coherente"),
        CheckConstraint("(estado = 'pendiente') = (decidida_en is null)", name="fecha_decision_coherente"),
        CheckConstraint("(estado = 'rechazada') = (motivo_rechazo is not null)", name="rechazo_con_motivo"),
        Index("ix_propuestas_estado", "estado"),
    )

    id: Mapped[IdPk]
    estado: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pendiente'"))
    presupuesto_mxn: Mapped[ImportePropio]
    total_mxn: Mapped[ImportePropio]
    fecha_limite: Mapped[date] = mapped_column(Date, nullable=False)
    origen: Mapped[Texto]
    mensaje_id: Mapped[int | None] = mapped_column(ForeignKey("mensajes_chat.id"), nullable=True)
    creada_por: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), nullable=False)
    decidida_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    decidida_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    motivo_rechazo: Mapped[TextoNulo]
    excluidas: Mapped[list[object]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    creado_en: Mapped[CreadoEn]

    renglones: Mapped[list[RenglonPropuesta]] = relationship(back_populates="propuesta", order_by="RenglonPropuesta.id")


class RenglonPropuesta(Base):
    __tablename__ = "renglones_propuesta"
    __table_args__ = (
        CheckConstraint("importe > 0", name="importe_positivo"),
        CheckConstraint("importe_mxn > 0", name="importe_mxn_positivo"),
        UniqueConstraint("propuesta_id", "factura_id"),
        Index("ix_renglones_propuesta_factura", "factura_id"),
    )

    id: Mapped[IdPk]
    propuesta_id: Mapped[int] = mapped_column(ForeignKey("propuestas.id"), nullable=False)
    factura_id: Mapped[int] = mapped_column(ForeignKey("facturas.id"), nullable=False)
    # En la moneda de la factura.
    importe: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    importe_mxn: Mapped[ImportePropio]
    razon: Mapped[Texto]

    propuesta: Mapped[Propuesta] = relationship(back_populates="renglones")
