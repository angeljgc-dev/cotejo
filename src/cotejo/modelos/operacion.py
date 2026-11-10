"""Cargas de archivos, bitácora y cuotas de uso."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import CHAR, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from cotejo.modelos.base import Base, CreadoEn, IdPk, Texto, TextoNulo

ACCIONES_BITACORA = (
    "SESION_INICIADA",
    "CARGA_CFDI",
    "CARGA_DOCUMENTO",
    "LISTA_69B_CARGADA",
    "PROVEEDOR_EDITADO",
    "ALERTA_RESUELTA",
    "PROPUESTA_CREADA",
    "PROPUESTA_APROBADA",
    "PROPUESTA_RECHAZADA",
    "PAGO_REGISTRADO",
    "DEMO_REINICIADA",
)


def _lista_sql(valores: tuple[str, ...]) -> str:
    return ",".join(f"'{v}'" for v in valores)


class Carga(Base):
    __tablename__ = "cargas"
    __table_args__ = (CheckConstraint("tipo in ('cfdi','documento','lista_69b')", name="tipo_valido"),)

    id: Mapped[IdPk]
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), nullable=False)
    tipo: Mapped[Texto]
    creado_en: Mapped[CreadoEn]


class CargaArchivo(Base):
    __tablename__ = "carga_archivos"
    __table_args__ = (
        CheckConstraint(
            "resultado in ('aceptada','aceptada_con_alertas','rechazada','duplicada','indexado','sin_texto')",
            name="resultado_valido",
        ),
        Index("ix_carga_archivos_carga", "carga_id"),
    )

    id: Mapped[IdPk]
    carga_id: Mapped[int] = mapped_column(ForeignKey("cargas.id", ondelete="CASCADE"), nullable=False)
    # Solo para mostrar: nunca se usa como ruta del sistema de archivos.
    nombre_archivo: Mapped[Texto]
    sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    tamano_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    resultado: Mapped[Texto]
    motivos: Mapped[list[object]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    # use_alter rompe el ciclo facturas <-> carga_archivos al crear y borrar tablas.
    factura_id: Mapped[int | None] = mapped_column(ForeignKey("facturas.id", use_alter=True), nullable=True)
    documento_id: Mapped[int | None] = mapped_column(ForeignKey("documentos.id"), nullable=True)
    creado_en: Mapped[CreadoEn]


class Bitacora(Base):
    """Solo se agrega: un trigger rechaza UPDATE y DELETE (migración 0001)."""

    __tablename__ = "bitacora"
    __table_args__ = (
        CheckConstraint(f"accion in ({_lista_sql(ACCIONES_BITACORA)})", name="accion_valida"),
        Index("ix_bitacora_ocurrido_en", text("ocurrido_en DESC")),
        Index("ix_bitacora_entidad", "entidad", "entidad_id"),
    )

    id: Mapped[IdPk]
    ocurrido_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    accion: Mapped[Texto]
    entidad: Mapped[Texto]
    entidad_id: Mapped[TextoNulo]
    detalle: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))


class CuotaUso(Base):
    __tablename__ = "cuota_uso"
    __table_args__ = (CheckConstraint("contador >= 0", name="contador_no_negativo"),)

    clave: Mapped[str] = mapped_column(Text, primary_key=True)
    dia: Mapped[date] = mapped_column(Date, primary_key=True)
    contador: Mapped[int] = mapped_column(Integer, nullable=False)
