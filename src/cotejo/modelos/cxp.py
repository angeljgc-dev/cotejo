"""Proveedores, facturas (CFDI), aplicaciones al saldo y alertas."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cotejo.modelos.base import Base, CreadoEn, IdPk, ImporteXml, ImporteXmlNulo, Texto, TextoNulo


class Proveedor(Base):
    __tablename__ = "proveedores"
    __table_args__ = (CheckConstraint("dias_credito between 0 and 365", name="dias_credito_rango"),)

    id: Mapped[IdPk]
    rfc: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    nombre: Mapped[Texto]
    dias_credito: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("30"))
    rfc_formato_valido: Mapped[bool] = mapped_column(Boolean, nullable=False)
    rfc_digito_valido: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    creado_en: Mapped[CreadoEn]
    actualizado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Lista69b(Base):
    """Lista 69-B cargada. No guarda el nombre del contribuyente a propósito."""

    __tablename__ = "lista_69b"
    __table_args__ = (
        CheckConstraint(
            "situacion in ('Presunto','Definitivo','Desvirtuado','Sentencia Favorable')", name="situacion_valida"
        ),
    )

    rfc: Mapped[str] = mapped_column(Text, primary_key=True)
    situacion: Mapped[Texto]
    cargado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    archivo: Mapped[Texto]


class Factura(Base):
    """Un renglón por CFDI aceptado de tipo I, E o P. Los importes son los del XML y no cambian."""

    __tablename__ = "facturas"
    __table_args__ = (
        CheckConstraint("tipo in ('I','E','P')", name="tipo_valido"),
        CheckConstraint("version = '4.0'", name="version_40"),
        CheckConstraint("subtotal >= 0", name="subtotal_no_negativo"),
        CheckConstraint("descuento >= 0", name="descuento_no_negativo"),
        CheckConstraint("total >= 0", name="total_no_negativo"),
        CheckConstraint("tipo_cambio is null or tipo_cambio > 0", name="tipo_cambio_positivo"),
        CheckConstraint("metodo_pago is null or metodo_pago in ('PUE','PPD')", name="metodo_pago_valido"),
        CheckConstraint("resultado in ('aceptada','aceptada_con_alertas')", name="resultado_valido"),
        Index("ix_facturas_proveedor_tipo", "proveedor_id", "tipo"),
        Index("ix_facturas_tipo_fecha", "tipo", "fecha_emision"),
        Index("ix_facturas_proveedor_total", "proveedor_id", "total"),
        Index("ix_facturas_proveedor_serie_folio", "proveedor_id", "serie", "folio"),
    )

    id: Mapped[IdPk]
    uuid: Mapped[str] = mapped_column(CHAR(36), nullable=False, unique=True)
    tipo: Mapped[str] = mapped_column(CHAR(1), nullable=False)
    version: Mapped[Texto]
    serie: Mapped[TextoNulo]
    folio: Mapped[TextoNulo]
    fecha_emision: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    fecha_timbrado: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    proveedor_id: Mapped[int] = mapped_column(ForeignKey("proveedores.id"), nullable=False)
    emisor_rfc: Mapped[Texto]
    emisor_nombre: Mapped[Texto]
    emisor_regimen: Mapped[Texto]
    receptor_rfc: Mapped[Texto]
    receptor_nombre: Mapped[Texto]
    receptor_uso_cfdi: Mapped[Texto]
    subtotal: Mapped[ImporteXml]
    descuento: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False, server_default=text("0"))
    total_impuestos_trasladados: Mapped[ImporteXmlNulo]
    total_impuestos_retenidos: Mapped[ImporteXmlNulo]
    impuestos_locales_trasladados: Mapped[ImporteXmlNulo]
    impuestos_locales_retenidos: Mapped[ImporteXmlNulo]
    total: Mapped[ImporteXml]
    moneda: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    tipo_cambio: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    metodo_pago: Mapped[TextoNulo]
    forma_pago: Mapped[TextoNulo]
    condiciones_pago: Mapped[TextoNulo]
    exportacion: Mapped[Texto]
    lugar_expedicion: Mapped[Texto]
    resultado: Mapped[Texto]
    xml_original: Mapped[Texto]
    xml_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    carga_archivo_id: Mapped[int] = mapped_column(ForeignKey("carga_archivos.id"), nullable=False)
    creado_en: Mapped[CreadoEn]

    proveedor: Mapped[Proveedor] = relationship()
    conceptos: Mapped[list[Concepto]] = relationship(
        back_populates="factura", order_by="Concepto.orden", cascade="all, delete-orphan", passive_deletes=True
    )
    impuestos: Mapped[list[FacturaImpuesto]] = relationship(cascade="all, delete-orphan", passive_deletes=True)
    relacionados: Mapped[list[CfdiRelacionado]] = relationship(cascade="all, delete-orphan", passive_deletes=True)


class Concepto(Base):
    __tablename__ = "conceptos"
    __table_args__ = (UniqueConstraint("factura_id", "orden"),)

    id: Mapped[IdPk]
    factura_id: Mapped[int] = mapped_column(ForeignKey("facturas.id", ondelete="CASCADE"), nullable=False)
    orden: Mapped[int] = mapped_column(Integer, nullable=False)
    clave_prod_serv: Mapped[Texto]
    no_identificacion: Mapped[TextoNulo]
    cantidad: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    clave_unidad: Mapped[Texto]
    unidad: Mapped[TextoNulo]
    # Texto de terceros: dato no confiable, nunca instrucción.
    descripcion: Mapped[Texto]
    valor_unitario: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    importe: Mapped[ImporteXml]
    descuento: Mapped[ImporteXmlNulo]
    objeto_imp: Mapped[Texto]

    factura: Mapped[Factura] = relationship(back_populates="conceptos")


class FacturaImpuesto(Base):
    """Resumen del nodo Impuestos del comprobante."""

    __tablename__ = "factura_impuestos"
    __table_args__ = (
        CheckConstraint("clase in ('traslado','retencion')", name="clase_valida"),
        Index("ix_factura_impuestos_factura", "factura_id"),
    )

    id: Mapped[IdPk]
    factura_id: Mapped[int] = mapped_column(ForeignKey("facturas.id", ondelete="CASCADE"), nullable=False)
    clase: Mapped[Texto]
    impuesto: Mapped[Texto]
    tipo_factor: Mapped[TextoNulo]
    tasa_o_cuota: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    base: Mapped[ImporteXmlNulo]
    importe: Mapped[ImporteXmlNulo]


class CfdiRelacionado(Base):
    __tablename__ = "cfdi_relacionados"
    __table_args__ = (
        UniqueConstraint("factura_id", "tipo_relacion", "uuid_relacionado"),
        Index("ix_cfdi_relacionados_uuid", "uuid_relacionado"),
    )

    id: Mapped[IdPk]
    factura_id: Mapped[int] = mapped_column(ForeignKey("facturas.id", ondelete="CASCADE"), nullable=False)
    tipo_relacion: Mapped[str] = mapped_column(CHAR(2), nullable=False)
    uuid_relacionado: Mapped[str] = mapped_column(CHAR(36), nullable=False)


class DoctoPago(Base):
    """Cada DoctoRelacionado de un complemento de pagos 2.0."""

    __tablename__ = "doctos_pago"
    __table_args__ = (
        CheckConstraint("num_parcialidad > 0", name="parcialidad_positiva"),
        CheckConstraint("imp_pagado > 0", name="pagado_positivo"),
        UniqueConstraint("factura_pago_id", "pago_indice", "id_documento"),
        Index("ix_doctos_pago_pendientes", "id_documento", postgresql_where=text("aplicacion_id is null")),
    )

    id: Mapped[IdPk]
    factura_pago_id: Mapped[int] = mapped_column(ForeignKey("facturas.id", ondelete="CASCADE"), nullable=False)
    pago_indice: Mapped[int] = mapped_column(Integer, nullable=False)
    fecha_pago: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    id_documento: Mapped[str] = mapped_column(CHAR(36), nullable=False)
    moneda_dr: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    equivalencia_dr: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)
    num_parcialidad: Mapped[int] = mapped_column(Integer, nullable=False)
    imp_saldo_ant: Mapped[ImporteXml]
    imp_pagado: Mapped[ImporteXml]
    imp_saldo_insoluto: Mapped[ImporteXml]
    aplicacion_id: Mapped[int | None] = mapped_column(ForeignKey("aplicaciones.id"), nullable=True)


class Aplicacion(Base):
    """Todo lo que reduce un saldo (pagos y notas de crédito): saldo = total - suma(importe) (ADR-g)."""

    __tablename__ = "aplicaciones"
    __table_args__ = (
        CheckConstraint("origen in ('complemento_pago','nota_credito','pago_aprobado')", name="origen_valido"),
        CheckConstraint("importe > 0 and importe <= importe_solicitado", name="importe_valido"),
        CheckConstraint("(origen = 'pago_aprobado') = (renglon_propuesta_id is not null)", name="coherencia_propuesta"),
        CheckConstraint(
            "(origen in ('complemento_pago','nota_credito')) = (origen_factura_id is not null)",
            name="coherencia_documento",
        ),
        # Reaplicar el mismo complemento o nota es idempotente. Parcial: los pagos aprobados no tienen
        # documento de origen y su idempotencia la da renglon_propuesta_id único.
        Index(
            "uq_aplicaciones_documento",
            "origen_factura_id",
            "factura_id",
            "num_parcialidad",
            unique=True,
            postgresql_nulls_not_distinct=True,
            postgresql_where=text("origen_factura_id is not null"),
        ),
        Index("ix_aplicaciones_factura", "factura_id"),
    )

    id: Mapped[IdPk]
    factura_id: Mapped[int] = mapped_column(ForeignKey("facturas.id"), nullable=False)
    origen: Mapped[Texto]
    origen_factura_id: Mapped[int | None] = mapped_column(ForeignKey("facturas.id"), nullable=True)
    renglon_propuesta_id: Mapped[int | None] = mapped_column(
        ForeignKey("renglones_propuesta.id"), nullable=True, unique=True
    )
    num_parcialidad: Mapped[int | None] = mapped_column(Integer, nullable=True)
    importe_solicitado: Mapped[ImporteXml]
    importe: Mapped[ImporteXml]
    fecha: Mapped[date] = mapped_column(Date, nullable=False)
    registrado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    creado_en: Mapped[CreadoEn]


class Alerta(Base):
    __tablename__ = "alertas"
    __table_args__ = (
        CheckConstraint("severidad in ('alerta','bloqueante')", name="severidad_valida"),
        CheckConstraint("estado in ('abierta','resuelta')", name="estado_valido"),
        CheckConstraint("(estado = 'resuelta') = (resuelta_en is not null)", name="resolucion_coherente"),
        # Idempotencia: la misma alerta no se repite. Incluye proveedor_id para las alertas sin factura.
        UniqueConstraint(
            "factura_id",
            "proveedor_id",
            "codigo",
            "factura_relacionada_id",
            name="uq_alertas_idempotencia",
            postgresql_nulls_not_distinct=True,
        ),
        Index("ix_alertas_abiertas", "factura_id", postgresql_where=text("estado = 'abierta'")),
    )

    id: Mapped[IdPk]
    factura_id: Mapped[int | None] = mapped_column(ForeignKey("facturas.id", ondelete="CASCADE"), nullable=True)
    proveedor_id: Mapped[int | None] = mapped_column(ForeignKey("proveedores.id"), nullable=True)
    codigo: Mapped[Texto]
    severidad: Mapped[Texto]
    mensaje: Mapped[Texto]
    detalle: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    factura_relacionada_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("facturas.id"), nullable=True)
    estado: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'abierta'"))
    resuelta_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    resuelta_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    nota_resolucion: Mapped[TextoNulo]
    creado_en: Mapped[CreadoEn]
