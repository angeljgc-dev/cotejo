"""B6: los importes se manejan con Decimal exacto y viajan como texto."""

from decimal import Decimal
from typing import cast

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import BaseModel, ValidationError

from cotejo.dinero import ErrorImporte, Importe, ImporteEntrada, a_decimal, a_mxn, cuantizar, texto


def test_a_decimal_es_exacto_donde_el_binario_falla() -> None:
    assert a_decimal("0.1") + a_decimal("0.2") == Decimal("0.3")
    assert 0.1 + 0.2 != 0.3  # el motivo de B6, documentado en la propia prueba


@pytest.mark.parametrize("valor", ["1160.00", "0", "0.000001", "123456789012345678.123456", "-5.5"])
def test_a_decimal_acepta_numeros_decimales(valor: str) -> None:
    assert a_decimal(valor) == Decimal(valor)


def test_a_decimal_limita_digitos_para_no_rebasar_la_precision() -> None:
    assert texto(a_decimal("9" * 18 + ".1234567891"), 6) == "9" * 18 + ".123457"
    for valor in ["1" * 19, "1." + "1" * 11]:
        with pytest.raises(ErrorImporte):
            a_decimal(valor)


@pytest.mark.parametrize("valor", ["", " ", "1e3", "NaN", "Infinity", "1,160.00", "abc", "1.", ".5", "+1", "１２"])
def test_a_decimal_rechaza_texto_que_no_es_importe(valor: str) -> None:
    with pytest.raises(ErrorImporte):
        a_decimal(valor)


def test_a_decimal_rechaza_float() -> None:
    with pytest.raises(ErrorImporte):
        a_decimal(cast(str, 0.1))


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [("2.005", "2.01"), ("2.004", "2.00"), ("-2.005", "-2.01"), ("1160", "1160.00"), ("-0.001", "0.00")],
)
def test_texto_redondea_half_up_y_sin_exponente(valor: str, esperado: str) -> None:
    assert texto(Decimal(valor)) == esperado


def test_texto_con_seis_decimales_y_numero_grande() -> None:
    assert texto(Decimal("1E+3"), 6) == "1000.000000"
    assert texto(Decimal("123456789012345678.1234565"), 6) == "123456789012345678.123457"


def test_cuantizar() -> None:
    assert cuantizar(Decimal("10.125")) == Decimal("10.13")


def test_a_mxn() -> None:
    assert a_mxn(Decimal("100"), "MXN", None) == Decimal("100.00")
    assert a_mxn(Decimal("100"), "usd", Decimal("17.2345")) == Decimal("1723.45")
    assert a_mxn(Decimal("100"), "USD", None) is None
    assert a_mxn(Decimal("0"), "XXX", None) == Decimal("0.00")


@given(st.decimals(min_value=-(10**15), max_value=10**15, places=6, allow_nan=False, allow_infinity=False))
def test_texto_y_a_decimal_ida_y_vuelta(valor: Decimal) -> None:
    assert a_decimal(texto(valor, 6)) == valor


class _Modelo(BaseModel):
    salida: Importe
    entrada: ImporteEntrada


def test_tipos_pydantic_serializan_como_texto_y_no_aceptan_float() -> None:
    m = _Modelo.model_validate({"salida": Decimal("1160"), "entrada": "10.50"})
    assert m.model_dump(mode="json") == {"salida": "1160.00", "entrada": "10.50"}
    with pytest.raises(ValidationError):
        _Modelo.model_validate({"salida": Decimal("1"), "entrada": 10.5})
