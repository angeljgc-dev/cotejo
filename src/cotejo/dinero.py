"""Dinero con Decimal exacto (B6). Ningún importe pasa por float."""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated

from pydantic import BeforeValidator, PlainSerializer

# Hasta 18 enteros (t_Importe del SAT) y 10 decimales (EquivalenciaDR): cabe en la precisión de 28 dígitos.
_PATRON_IMPORTE = re.compile(r"-?[0-9]{1,18}(\.[0-9]{1,10})?", flags=re.ASCII)
MONEDA_LOCAL = "MXN"
# Clave del SAT para comprobantes sin operación monetaria (tipo P): no se convierte.
MONEDA_SIN_VALOR = "XXX"


class ErrorImporte(ValueError):
    """El texto no representa un importe decimal válido."""


def a_decimal(texto: str) -> Decimal:
    """Convierte texto como "1160.00" en Decimal; rechaza exponentes, separadores de miles, NaN y float."""
    if not isinstance(texto, str):
        raise ErrorImporte("El importe debe llegar como texto decimal, no como número.")
    if _PATRON_IMPORTE.fullmatch(texto) is None:
        raise ErrorImporte(f"Importe inválido: {texto!r}.")
    return Decimal(texto)


def cuantizar(valor: Decimal, decimales: int = 2) -> Decimal:
    resultado = valor.quantize(Decimal(1).scaleb(-decimales), rounding=ROUND_HALF_UP)
    # Evita "-0.00" cuando un negativo pequeño redondea a cero.
    return resultado + 0 if resultado.is_zero() else resultado


def texto(valor: Decimal, decimales: int = 2) -> str:
    return format(cuantizar(valor, decimales), "f")


def a_mxn(importe: Decimal, moneda: str, tipo_cambio: Decimal | None) -> Decimal | None:
    """Equivalente en pesos a 2 decimales; None si la moneda es extranjera y no hay tipo de cambio (B5)."""
    clave = moneda.upper()
    if clave in (MONEDA_LOCAL, MONEDA_SIN_VALOR):
        return cuantizar(importe)
    if tipo_cambio is None:
        return None
    return cuantizar(importe * tipo_cambio)


def _solo_texto(valor: object) -> object:
    if isinstance(valor, Decimal):
        return valor
    if isinstance(valor, str):
        return a_decimal(valor)
    raise ErrorImporte("El importe debe llegar como texto decimal, no como número.")


# Importe de salida: siempre texto con 2 decimales en JSON.
Importe = Annotated[Decimal, PlainSerializer(texto, return_type=str, when_used="json")]
# Importe de entrada: solo texto decimal (o Decimal desde código); un float del cliente es error de validación.
ImporteEntrada = Annotated[
    Decimal,
    BeforeValidator(_solo_texto),
    PlainSerializer(lambda v: format(v, "f"), return_type=str, when_used="json"),
]
