"""Bitácora de operaciones (D7). Solo agrega renglones; la base rechaza UPDATE y DELETE."""

from __future__ import annotations

import enum
import uuid
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from cotejo.modelos import ACCIONES_BITACORA, Bitacora

ENTIDADES = frozenset(
    {"factura", "propuesta", "carga", "proveedor", "alerta", "lista_69b", "demo", "usuario", "documento"}
)

ValorJson = str | int | float | bool | None | list["ValorJson"] | dict[str, "ValorJson"]


class AccionInvalida(ValueError):
    pass


def a_json(valor: object) -> ValorJson:
    """Convierte Decimal, fechas, UUID y enums a texto para guardarlos en jsonb sin perder exactitud."""
    if valor is None or isinstance(valor, (str, bool, int)):
        return valor
    if isinstance(valor, Decimal):
        return format(valor, "f")
    if isinstance(valor, float):
        return valor
    if isinstance(valor, (datetime, date)):
        return valor.isoformat()
    if isinstance(valor, uuid.UUID):
        return str(valor)
    if isinstance(valor, enum.Enum):
        return a_json(valor.value)
    if isinstance(valor, Mapping):
        return {str(k): a_json(v) for k, v in valor.items()}
    if isinstance(valor, Sequence | set | frozenset):
        return [a_json(v) for v in valor]
    raise TypeError(f"No se puede guardar en la bitácora un valor de tipo {type(valor).__name__}.")


def registrar(
    sesion: Session,
    *,
    usuario_id: int | None,
    accion: str,
    entidad: str,
    entidad_id: str | int | None,
    detalle: Mapping[str, object],
) -> None:
    """Agrega un renglón a la bitácora en la transacción en curso. No hace commit."""
    if accion not in ACCIONES_BITACORA:
        raise AccionInvalida(f"Acción de bitácora desconocida: {accion!r}.")
    if entidad not in ENTIDADES:
        raise AccionInvalida(f"Entidad de bitácora desconocida: {entidad!r}.")
    detalle_json: dict[str, ValorJson] = {str(k): a_json(v) for k, v in detalle.items()}
    sesion.add(
        Bitacora(
            usuario_id=usuario_id,
            accion=accion,
            entidad=entidad,
            entidad_id=None if entidad_id is None else str(entidad_id),
            detalle=dict(detalle_json.items()),
        )
    )
