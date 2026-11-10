"""B6: todo importe de las consultas y del contrato es Decimal y viaja como texto, nunca como número binario."""

from __future__ import annotations

import typing
from decimal import Decimal

import pytest
from pydantic import BaseModel

from cotejo.api import rutas_cargas, rutas_lista69b
from cotejo.cxp import consultas, contrato

MODELOS: list[type[BaseModel]] = [
    obj
    for modulo in (consultas, contrato, rutas_cargas, rutas_lista69b)
    for obj in vars(modulo).values()
    if isinstance(obj, type) and issubclass(obj, BaseModel) and obj.__module__ == modulo.__name__
]


def _tipos(anotacion: object) -> set[object]:
    argumentos = typing.get_args(anotacion)
    if not argumentos:
        return {anotacion}
    return {anotacion} | {t for a in argumentos for t in _tipos(a)}


@pytest.mark.parametrize("modelo", MODELOS, ids=lambda m: m.__name__)
def test_ningun_campo_es_float(modelo: type[BaseModel]) -> None:
    for nombre, campo in modelo.model_fields.items():
        assert float not in _tipos(campo.annotation), f"{modelo.__name__}.{nombre} es float"


def test_importe_se_serializa_como_texto_exacto() -> None:
    saldo = consultas.SaldoMoneda(moneda="MXN", saldo=Decimal("0.1") + Decimal("0.2"), saldo_mxn=Decimal("0.305"))
    assert saldo.model_dump(mode="json") == {"moneda": "MXN", "saldo": "0.30", "saldo_mxn": "0.31"}
    assert 0.1 + 0.2 != 0.3
