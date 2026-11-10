"""Sospecha de factura duplicada con folio fiscal distinto (A5).

Dos facturas de ingreso del mismo proveedor y con el mismo total son sospechosas si además comparten serie y
folio, o si sus fechas de emisión distan tres días o menos. La alerta queda en la más nueva y enlaza a la otra.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from cotejo.cfdi import codigos
from cotejo.cfdi.codigos import Motivo
from cotejo.cxp import alertas
from cotejo.dinero import texto
from cotejo.modelos import Factura

VENTANA = timedelta(days=3)


@dataclass(frozen=True)
class ParDuplicado:
    """`nueva` es la factura que carga la alerta; `otra` es a la que enlaza."""

    nueva: Factura
    otra: Factura


def buscar(sesion: Session, factura: Factura) -> list[ParDuplicado]:
    if factura.tipo != "I":
        return []
    misma_serie_y_folio = and_(
        Factura.serie.is_not(None),
        Factura.folio.is_not(None),
        Factura.serie == factura.serie,
        Factura.folio == factura.folio,
    )
    fecha_cercana = Factura.fecha_emision.between(factura.fecha_emision - VENTANA, factura.fecha_emision + VENTANA)
    otras = sesion.scalars(
        select(Factura)
        .where(
            Factura.proveedor_id == factura.proveedor_id,
            Factura.tipo == "I",
            Factura.total == factura.total,
            Factura.id != factura.id,
            or_(misma_serie_y_folio, fecha_cercana),
        )
        .order_by(Factura.id)
    ).all()
    pares = []
    for otra in otras:
        if (otra.fecha_emision, otra.id) > (factura.fecha_emision, factura.id):
            pares.append(ParDuplicado(nueva=otra, otra=factura))
        else:
            pares.append(ParDuplicado(nueva=factura, otra=otra))
    return pares


def registrar(sesion: Session, factura: Factura) -> list[Motivo]:
    """Abre las alertas de posible duplicado y devuelve los motivos para el resultado de la carga."""
    motivos = []
    for par in buscar(sesion, factura):
        referencia = " ".join(p for p in (par.otra.serie, par.otra.folio) if p) or par.otra.uuid
        mensaje = (
            f"Posible duplicado de la factura {referencia} del mismo proveedor: mismo total "
            f"({texto(par.nueva.total)} {par.nueva.moneda}) y serie y folio iguales o fechas a tres días o menos. "
            "No se puede proponer su pago hasta que alguien la revise."
        )
        detalle = {
            "uuid_otra": par.otra.uuid,
            "total": par.nueva.total,
            "fecha_emision": par.nueva.fecha_emision,
            "fecha_emision_otra": par.otra.fecha_emision,
        }
        alertas.abrir(
            sesion,
            codigo=codigos.POSIBLE_DUPLICADO,
            severidad="bloqueante",
            mensaje=mensaje,
            factura_id=par.nueva.id,
            detalle=detalle,
            factura_relacionada_id=par.otra.id,
        )
        if par.nueva.id == factura.id:
            motivos.append(codigos.alerta(codigos.POSIBLE_DUPLICADO, mensaje, detalle))
        else:
            otra_referencia = " ".join(p for p in (par.nueva.serie, par.nueva.folio) if p) or par.nueva.uuid
            motivos.append(
                codigos.alerta(
                    codigos.POSIBLE_DUPLICADO,
                    f"Esta factura parece ser la misma que {otra_referencia}, ya registrada con fecha posterior. "
                    "La alerta quedó en aquella, que es la más nueva.",
                    detalle,
                )
            )
    return motivos
