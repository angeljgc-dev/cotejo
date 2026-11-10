"""Lo que Cotejo toma de un CFDI 4.0, ya con tipos: importes en Decimal y fechas sin zona (hora local del emisor)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class ConceptoLeido:
    orden: int
    clave_prod_serv: str
    no_identificacion: str | None
    cantidad: Decimal
    clave_unidad: str
    unidad: str | None
    # Texto escrito por el emisor: dato no confiable.
    descripcion: str
    valor_unitario: Decimal
    importe: Decimal
    descuento: Decimal | None
    objeto_imp: str


@dataclass(frozen=True)
class ImpuestoLeido:
    clase: str
    impuesto: str
    tipo_factor: str | None
    tasa_o_cuota: Decimal | None
    base: Decimal | None
    importe: Decimal | None


@dataclass(frozen=True)
class RelacionLeida:
    tipo_relacion: str
    uuid: str


@dataclass(frozen=True)
class DoctoPagoLeido:
    pago_indice: int
    fecha_pago: datetime
    id_documento: str
    moneda_dr: str
    equivalencia_dr: Decimal | None
    num_parcialidad: int
    imp_saldo_ant: Decimal
    imp_pagado: Decimal
    imp_saldo_insoluto: Decimal


@dataclass(frozen=True)
class CfdiLeido:
    uuid: str
    tipo: str
    version: str
    serie: str | None
    folio: str | None
    fecha_emision: datetime
    fecha_timbrado: datetime
    emisor_rfc: str
    emisor_nombre: str
    emisor_regimen: str
    receptor_rfc: str
    receptor_nombre: str
    receptor_uso_cfdi: str
    subtotal: Decimal
    # None cuando el comprobante no trae el atributo Descuento.
    descuento: Decimal | None
    total_impuestos_trasladados: Decimal | None
    total_impuestos_retenidos: Decimal | None
    impuestos_locales_trasladados: Decimal | None
    impuestos_locales_retenidos: Decimal | None
    total: Decimal
    moneda: str
    tipo_cambio: Decimal | None
    metodo_pago: str | None
    forma_pago: str | None
    condiciones_pago: str | None
    exportacion: str
    lugar_expedicion: str
    conceptos: tuple[ConceptoLeido, ...]
    impuestos: tuple[ImpuestoLeido, ...]
    relacionados: tuple[RelacionLeida, ...]
    doctos_pago: tuple[DoctoPagoLeido, ...]
