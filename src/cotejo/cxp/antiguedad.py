"""Antigüedad de saldos: cinco grupos según los días que lleva vencida una factura (B3).

Cada factura cae en exactamente un grupo, por eso la suma de los grupos es igual al adeudo total. La misma regla
existe en dos formas que las pruebas comparan: `grupo_de` en Python y `columna_grupo` en SQL.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from typing import Literal

from sqlalchemy import ColumnElement, case

Grupo = Literal["por_vencer", "1_30", "31_60", "61_90", "mas_90"]

GRUPOS: tuple[tuple[Grupo, str], ...] = (
    ("por_vencer", "Por vencer"),
    ("1_30", "1 a 30 días"),
    ("31_60", "31 a 60 días"),
    ("61_90", "61 a 90 días"),
    ("mas_90", "Más de 90 días"),
)


def grupo_de(dias_vencido: int) -> Grupo:
    """Grupo de una factura. `dias_vencido` es hoy menos el vencimiento: cero o negativo aún no vence."""
    if dias_vencido <= 0:
        return "por_vencer"
    if dias_vencido <= 30:
        return "1_30"
    if dias_vencido <= 60:
        return "31_60"
    if dias_vencido <= 90:
        return "61_90"
    return "mas_90"


def columna_grupo(dias_vencido: ColumnElement[int]) -> ColumnElement[str]:
    return case(
        (dias_vencido <= 0, "por_vencer"),
        (dias_vencido <= 30, "1_30"),
        (dias_vencido <= 60, "31_60"),
        (dias_vencido <= 90, "61_90"),
        else_="mas_90",
    )


def agrupar(saldos: Iterable[tuple[int, Decimal]]) -> dict[Grupo, tuple[Decimal, int]]:
    """Suma y cuenta por grupo una lista de (días vencido, saldo). Siempre devuelve los cinco grupos."""
    resultado: dict[Grupo, tuple[Decimal, int]] = {clave: (Decimal(0), 0) for clave, _ in GRUPOS}
    for dias, saldo in saldos:
        clave = grupo_de(dias)
        suma, cuenta = resultado[clave]
        resultado[clave] = (suma + saldo, cuenta + 1)
    return resultado
