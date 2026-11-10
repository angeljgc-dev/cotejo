"""Barreras de una propuesta de pago (D5). Viven en código y se aplican igual venga de donde venga la petición.

Las mismas comprobaciones corren dos veces: al armar la propuesta y otra vez al aprobarla, contra el estado
de la base en ese momento. Ninguna depende de lo que diga el modelo de lenguaje.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from cotejo.cxp.consultas import FacturaElegible
from cotejo.dinero import texto

ALERTA_BLOQUEANTE = "ALERTA_BLOQUEANTE"
YA_PAGADA = "YA_PAGADA"
EXCEDE_SALDO = "EXCEDE_SALDO"
EXCEDE_PRESUPUESTO = "EXCEDE_PRESUPUESTO"
EN_OTRA_PROPUESTA = "EN_OTRA_PROPUESTA"
NO_ES_INGRESO = "NO_ES_INGRESO"
SIN_TIPO_CAMBIO = "SIN_TIPO_CAMBIO"
FACTURA_NO_ENCONTRADA = "FACTURA_NO_ENCONTRADA"

_TIPOS = {"E": "una nota de crédito", "P": "un complemento de pago"}


@dataclass(frozen=True)
class Incumplimiento:
    codigo: str
    motivo: str


def revisar(
    factura: FacturaElegible, *, importe: Decimal, propuesta_propia: int | None = None
) -> Incumplimiento | None:
    """Primera barrera que la factura no pasa para pagarle `importe` (en su moneda), o None si las pasa todas.

    `propuesta_propia` es la propuesta que se está aprobando: estar en ella no cuenta como estar en otra.
    """
    if factura.tipo != "I":
        return Incumplimiento(
            NO_ES_INGRESO, f"No es una factura por pagar: es {_TIPOS.get(factura.tipo, 'otro tipo')}."
        )
    if factura.saldo <= 0:
        return Incumplimiento(YA_PAGADA, "La factura ya no tiene saldo por pagar.")
    if factura.bloqueos:
        detalle = " ".join(b.mensaje for b in factura.bloqueos)
        codigos = ", ".join(sorted({b.codigo for b in factura.bloqueos}))
        return Incumplimiento(ALERTA_BLOQUEANTE, f"Tiene una alerta bloqueante abierta ({codigos}). {detalle}".strip())
    if factura.saldo_mxn is None:
        return Incumplimiento(
            SIN_TIPO_CAMBIO, f"Está en {factura.moneda} y no trae tipo de cambio: no se puede valuar en pesos."
        )
    if factura.en_propuesta_pendiente is not None and factura.en_propuesta_pendiente != propuesta_propia:
        return Incumplimiento(EN_OTRA_PROPUESTA, f"Ya está en la propuesta pendiente {factura.en_propuesta_pendiente}.")
    if importe > factura.saldo:
        return Incumplimiento(
            EXCEDE_SALDO,
            f"El importe propuesto ({texto(importe)} {factura.moneda}) es mayor que el saldo actual "
            f"({texto(factura.saldo)} {factura.moneda}).",
        )
    return None
