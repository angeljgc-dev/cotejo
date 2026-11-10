"""A3: un caso por código de alerta del comprobante, con los bordes de la tolerancia de un centavo."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st
from stdnum.mx import rfc as rfc_oraculo

from cotejo.cfdi import parser, reglas, rfc
from cotejo.semilla.cfdi_ficticio import CfdiFicticio, ConceptoFicticio, construir_xml
from cotejo.semilla.rfc_ficticio import rfc_moral
from tests.apoyo.cfdi import AHORA, docto, ingreso, nota, pago
from tests.apoyo.fabricas import EMPRESA_RFC


def _codigos(cfdi: CfdiFicticio | bytes, ahora: datetime = AHORA) -> set[str]:
    xml = cfdi if isinstance(cfdi, bytes) else construir_xml(cfdi)
    return {m.codigo for m in reglas.evaluar(parser.leer(xml), empresa_rfc=EMPRESA_RFC, ahora=ahora)}


def test_factura_correcta_sin_alertas() -> None:
    assert _codigos(ingreso(Decimal("1160.00"))) == set()


def test_rfc_formato_invalido() -> None:
    assert "RFC_FORMATO_INVALIDO" in _codigos(ingreso(emisor="ZZ12345"))


def test_rfc_digito_invalido_y_genericos_no_alertan() -> None:
    malo = rfc_moral("A", date(2001, 1, 1), "AA", digito_correcto=False)
    assert "RFC_DIGITO_INVALIDO" in _codigos(ingreso(emisor=malo))
    assert rfc.digito_valido("XAXX010101000") is None
    assert rfc.digito_valido("XEXX010101000") is None


@pytest.mark.parametrize(("diferencia", "alerta"), [(Decimal("0.01"), False), (Decimal("0.02"), True)])
def test_total_no_cuadra_con_tolerancia_de_un_centavo(diferencia: Decimal, alerta: bool) -> None:
    cfdi = replace(ingreso(Decimal("1160.00")), total_forzado=Decimal("1160.00") + diferencia)
    assert ("TOTAL_NO_CUADRA" in _codigos(cfdi)) is alerta


@pytest.mark.parametrize(("subtotal", "alerta"), [(b"1000.01", False), (b"1000.02", True)])
def test_subtotal_no_cuadra(subtotal: bytes, alerta: bool) -> None:
    xml = construir_xml(ingreso(Decimal("1160.00"))).replace(b'SubTotal="1000.00"', b'SubTotal="' + subtotal + b'"')
    assert ("SUBTOTAL_NO_CUADRA" in _codigos(xml)) is alerta


def test_descuento_no_cuadra() -> None:
    cfdi = replace(
        ingreso(Decimal("1160.00")),
        conceptos=(
            ConceptoFicticio(descripcion="Con descuento", valor_unitario=Decimal(1000), descuento=Decimal(100)),
        ),
    )
    xml = construir_xml(cfdi)
    assert "DESCUENTO_NO_CUADRA" not in _codigos(xml)
    # El primer Descuento del documento es el del comprobante; el del concepto se queda.
    sin_descuento_global = xml.replace(b' Descuento="100.00"', b"", 1)
    assert sin_descuento_global.count(b'Descuento="100.00"') == 1
    assert "DESCUENTO_NO_CUADRA" in _codigos(sin_descuento_global)


def test_impuestos_no_cuadran() -> None:
    xml = construir_xml(ingreso(Decimal("1160.00")))
    alterado = xml.replace(b'TotalImpuestosTrasladados="160.00"', b'TotalImpuestosTrasladados="160.02"')
    assert "IMPUESTOS_NO_CUADRAN" in _codigos(alterado)


def test_receptor_ajeno_es_bloqueante() -> None:
    cfdi = parser.leer(construir_xml(ingreso(receptor=rfc_moral("X", date(2005, 5, 5), "OT"))))
    (motivo,) = [m for m in reglas.evaluar(cfdi, empresa_rfc=EMPRESA_RFC, ahora=AHORA) if m.codigo == "RECEPTOR_AJENO"]
    assert motivo.severidad == "bloqueante"


def test_fecha_futura_con_margen_de_dos_horas() -> None:
    limite = AHORA + timedelta(hours=2)
    assert "FECHA_FUTURA" not in _codigos(ingreso(fecha=limite))
    assert "FECHA_FUTURA" in _codigos(ingreso(fecha=limite + timedelta(seconds=1)))


def test_moneda_sin_tipo_de_cambio() -> None:
    assert "MONEDA_SIN_TIPO_CAMBIO" in _codigos(ingreso(moneda="USD"))
    assert "MONEDA_SIN_TIPO_CAMBIO" not in _codigos(ingreso(moneda="USD", tipo_cambio=Decimal("18.5")))


def test_nota_sin_relacion() -> None:
    assert "NOTA_SIN_RELACION" in _codigos(nota(Decimal(100)))
    assert "NOTA_SIN_RELACION" not in _codigos(nota(Decimal(100), ingreso().uuid))


def test_pago_con_total_distinto_de_cero() -> None:
    xml = construir_xml(pago((AHORA, (docto(ingreso(), 1, Decimal(1160), Decimal(1)),))))
    assert "TOTAL_PAGO_NO_CERO" not in _codigos(xml)
    assert "TOTAL_PAGO_NO_CERO" in _codigos(xml.replace(b'Total="0"', b'Total="5"', 1))


_LETRAS = st.sampled_from("ABCDEFGHIJKLMNOPQRSTUVWXYZ&")
_HOMOCLAVE = st.text("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", min_size=2, max_size=2)


@given(
    letras=st.lists(_LETRAS, min_size=3, max_size=4),
    fecha=st.dates(min_value=date(1950, 1, 1), max_value=date(2049, 12, 31)),
    homoclave=_HOMOCLAVE,
)
def test_digito_de_verificacion_contra_python_stdnum(letras: list[str], fecha: date, homoclave: str) -> None:
    cuerpo = f"{''.join(letras)}{fecha:%y%m%d}{homoclave}"
    assert rfc.digito_verificador(cuerpo) == rfc_oraculo.calc_check_digit(cuerpo)
    if rfc.formato_valido(cuerpo + rfc.digito_verificador(cuerpo)):
        assert rfc.digito_valido(cuerpo + rfc.digito_verificador(cuerpo)) is True
