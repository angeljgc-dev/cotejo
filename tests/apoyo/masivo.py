"""Inserción directa de muchas facturas para propiedades y rendimiento. No confirma: solo `flush`."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import insert
from sqlalchemy.orm import Session

from cotejo.modelos import Factura
from tests.apoyo.fabricas import EMPRESA_RFC

_XML = "<cfdi:Comprobante Version='4.0'/>"


@dataclass(frozen=True)
class FacturaMasiva:
    proveedor_id: int
    proveedor_rfc: str
    total: Decimal
    fecha_emision: datetime
    moneda: str = "MXN"
    tipo_cambio: Decimal | None = None


def insertar(sesion: Session, facturas: Sequence[FacturaMasiva], *, carga_archivo_id: int, lote: int = 0) -> list[int]:
    """Inserta las facturas en una sola sentencia y devuelve sus id en el mismo orden."""
    if not facturas:
        return []
    filas = [
        {
            "uuid": str(uuid.UUID(int=(0xB0 << 120) | (lote << 32) | i)).upper(),
            "tipo": "I",
            "version": "4.0",
            "serie": "M",
            "folio": f"{lote}-{i}",
            "fecha_emision": f.fecha_emision,
            "fecha_timbrado": f.fecha_emision,
            "proveedor_id": f.proveedor_id,
            "emisor_rfc": f.proveedor_rfc,
            "emisor_nombre": "Proveedor Ficticio",
            "emisor_regimen": "601",
            "receptor_rfc": EMPRESA_RFC,
            "receptor_nombre": "Comercializadora Ficticia del Centro",
            "receptor_uso_cfdi": "G03",
            "subtotal": f.total,
            "descuento": Decimal(0),
            "total": f.total,
            "moneda": f.moneda,
            "tipo_cambio": f.tipo_cambio,
            "metodo_pago": "PPD",
            "forma_pago": "99",
            "exportacion": "01",
            "lugar_expedicion": "64000",
            "resultado": "aceptada",
            "xml_original": _XML,
            "xml_sha256": hashlib.sha256(_XML.encode()).hexdigest(),
            "carga_archivo_id": carga_archivo_id,
        }
        for i, f in enumerate(facturas)
    ]
    ids = list(sesion.scalars(insert(Factura).returning(Factura.id, sort_by_parameter_order=True), filas))
    sesion.flush()
    return ids
