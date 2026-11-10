"""Selección de las facturas de una propuesta (ADR-i): la hace el código, no el modelo de lenguaje.

Regla: las facturas llegan ordenadas por vencimiento (la más antigua primero); se toma el saldo completo de cada
una mientras quepa en el presupuesto. La que no cabe se excluye y se sigue con las siguientes. Así la misma
petición sobre los mismos datos produce siempre la misma propuesta.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from cotejo.cxp.consultas import FacturaElegible
from cotejo.dinero import texto
from cotejo.propuestas import barreras

_MESES = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)


@dataclass(frozen=True)
class RenglonElegido:
    factura: FacturaElegible
    # En la moneda de la factura: siempre el saldo completo (el pago parcial no existe en esta versión).
    importe: Decimal
    importe_mxn: Decimal
    razon: str


@dataclass(frozen=True)
class Exclusion:
    factura_id: int
    codigo: str
    motivo: str
    serie: str | None = None
    folio: str | None = None
    proveedor_nombre: str | None = None
    # Saldo en pesos de la factura excluida, si se conoce: es lo que no cupo o lo que quedó bloqueado.
    saldo_mxn: Decimal | None = None

    def a_json(self) -> dict[str, object]:
        return {
            "factura_id": self.factura_id,
            "serie": self.serie,
            "folio": self.folio,
            "proveedor_nombre": self.proveedor_nombre,
            "saldo_mxn": texto(self.saldo_mxn) if self.saldo_mxn is not None else None,
            "codigo": self.codigo,
            "motivo": self.motivo,
        }


@dataclass(frozen=True)
class Seleccion:
    renglones: tuple[RenglonElegido, ...]
    excluidas: tuple[Exclusion, ...]
    total_mxn: Decimal


def fecha_larga(dia: date, hoy: date) -> str:
    base = f"{dia.day} de {_MESES[dia.month - 1]}"
    return base if dia.year == hoy.year else f"{base} de {dia.year}"


def razon_de_pago(vencimiento: date, hoy: date) -> str:
    """Por qué entra la factura, en palabras: la genera el código a partir de las fechas."""
    dias = (hoy - vencimiento).days
    if dias > 1:
        return f"Vencida hace {dias} días"
    if dias == 1:
        return "Venció ayer"
    if dias == 0:
        return "Vence hoy"
    return f"Vence el {fecha_larga(vencimiento, hoy)}"


def excluir(factura: FacturaElegible, codigo: str, motivo: str) -> Exclusion:
    return Exclusion(
        factura_id=factura.factura_id,
        codigo=codigo,
        motivo=motivo,
        serie=factura.serie,
        folio=factura.folio,
        proveedor_nombre=factura.proveedor.nombre,
        saldo_mxn=factura.saldo_mxn if factura.tipo == "I" else None,
    )


def seleccionar(candidatas: Sequence[FacturaElegible], presupuesto_mxn: Decimal, hoy: date) -> Seleccion:
    """Aplica las barreras a cada candidata, en el orden recibido, y llena el presupuesto sin rebasarlo."""
    renglones: list[RenglonElegido] = []
    excluidas: list[Exclusion] = []
    total = Decimal(0)
    for factura in candidatas:
        incumplimiento = barreras.revisar(factura, importe=factura.saldo)
        if incumplimiento is not None:
            excluidas.append(excluir(factura, incumplimiento.codigo, incumplimiento.motivo))
            continue
        saldo_mxn = factura.saldo_mxn
        if saldo_mxn is None:
            # barreras.revisar ya lo descartó con SIN_TIPO_CAMBIO; se repite para que el tipo quede acotado.
            continue
        if total + saldo_mxn > presupuesto_mxn:
            disponible = presupuesto_mxn - total
            excluidas.append(
                excluir(
                    factura,
                    barreras.EXCEDE_PRESUPUESTO,
                    f"Su saldo de {texto(saldo_mxn)} MXN no cabe en lo que queda del presupuesto "
                    f"({texto(disponible)} MXN).",
                )
            )
            continue
        total += saldo_mxn
        renglones.append(
            RenglonElegido(
                factura=factura,
                importe=factura.saldo,
                importe_mxn=saldo_mxn,
                razon=razon_de_pago(factura.vencimiento, hoy),
            )
        )
    return Seleccion(renglones=tuple(renglones), excluidas=tuple(excluidas), total_mxn=total)
