"""A2: un caso por código de rechazo del lector de CFDI."""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from cotejo.cfdi import parser, reglas, xml_seguro
from cotejo.semilla.cfdi_ficticio import construir_xml
from tests.apoyo import xsd_sat
from tests.apoyo.cfdi import FIXTURES, docto, ingreso, nota, pago
from tests.apoyo.fabricas import EMPRESA_RFC

BUENO = (FIXTURES / "validos" / "ingreso_mxn.xml").read_bytes()


def _codigo(datos: bytes) -> str:
    with pytest.raises((xml_seguro.XmlRechazado, parser.CfdiRechazado)) as info:
        parser.leer(datos)
    error = info.value
    assert isinstance(error, (xml_seguro.XmlRechazado, parser.CfdiRechazado)) and error.mensaje
    return error.codigo


@pytest.mark.parametrize(
    ("datos", "esperado"),
    [
        (b"", "ARCHIVO_VACIO"),
        (b"<a>" + b"x" * (2 * 1024 * 1024) + b"</a>", "ARCHIVO_DEMASIADO_GRANDE"),
        (b'<!DOCTYPE a [<!ENTITY e "x">]><a>&e;</a>', "XML_DTD_PROHIBIDO"),
        (b"<cfdi:Comprobante", "XML_MAL_FORMADO"),
        (BUENO.replace(b"http://www.sat.gob.mx/cfd/4", b"http://www.sat.gob.mx/cfd/3"), "NO_ES_CFDI40"),
        (BUENO.replace(b'Version="4.0"', b'Version="3.3"', 1), "NO_ES_CFDI40"),
        (BUENO.replace(b"tfd:TimbreFiscalDigital ", b"tfd:Otro "), "SIN_TIMBRE"),
        (BUENO.replace(b'TipoDeComprobante="I"', b'TipoDeComprobante="N"'), "TIPO_NO_SOPORTADO"),
        (BUENO.replace(b'TipoDeComprobante="I"', b'TipoDeComprobante="T"'), "TIPO_NO_SOPORTADO"),
        (BUENO.replace(b' Total="6845.16"', b""), "ATRIBUTO_REQUERIDO"),
        (BUENO.replace(b'Total="6845.16"', b'Total="-6845.16"'), "IMPORTE_INVALIDO"),
        (BUENO.replace(b'Total="6845.16"', b'Total="6845.1234567"'), "IMPORTE_INVALIDO"),
        (BUENO.replace(b'Fecha="2026-10-01T10:00:00"', b'Fecha="2026-13-01T10:00:00"'), "FECHA_INVALIDA"),
        (BUENO.replace(b'Moneda="MXN"', b'Moneda="PESOS"'), "ATRIBUTO_INVALIDO"),
        (BUENO.replace(b'MetodoPago="PPD"', b'MetodoPago="XYZ"'), "ATRIBUTO_INVALIDO"),
    ],
    ids=lambda v: v if isinstance(v, str) else "",
)
def test_rechazo(datos: bytes, esperado: str) -> None:
    assert _codigo(datos) == esperado


def test_pago_sin_complemento() -> None:
    factura = ingreso()
    completo = construir_xml(
        pago((datetime.fromisoformat("2026-10-01T12:00:00"), (docto(factura, 1, Decimal(1160), Decimal(1)),)))
    )
    xml = re.sub(rb"<pago20:Pagos.*</pago20:Pagos>", b"", completo, flags=re.DOTALL)
    assert b"pago20:Pagos" not in xml
    assert _codigo(xml) == "PAGO_SIN_COMPLEMENTO"


def test_emitida_por_la_empresa_se_rechaza() -> None:
    cfdi = parser.leer(construir_xml(ingreso(emisor=EMPRESA_RFC)))
    motivo = reglas.rechazo_por_emisor(cfdi, EMPRESA_RFC.lower())
    assert motivo is not None and motivo.codigo == "EMITIDA_POR_LA_EMPRESA" and motivo.severidad == "rechazo"


@pytest.mark.parametrize("ruta", sorted((FIXTURES / "validos").glob("*.xml")), ids=lambda p: p.stem)
def test_fixtures_validos_se_leen(ruta: Path) -> None:
    assert parser.leer(ruta.read_bytes()).uuid


@pytest.mark.parametrize("ruta", sorted((FIXTURES / "validos").glob("*.xml")), ids=lambda p: p.stem)
def test_fixtures_validos_cumplen_los_xsd_del_sat(ruta: Path) -> None:
    assert xsd_sat.errores(ruta.read_bytes()) == []


def test_xsd_oficiales_sin_modificar() -> None:
    assert {nombre: xsd_sat.suma_de(nombre) for nombre in xsd_sat.sumas_registradas()} == xsd_sat.sumas_registradas()


def test_comprobantes_de_las_pruebas_cumplen_los_xsd() -> None:
    factura = ingreso()
    for cfdi in (
        factura,
        ingreso(moneda="USD", tipo_cambio=Decimal("18.5")),
        nota(Decimal(100), factura.uuid),
        pago((datetime.fromisoformat("2026-10-01T12:00:00"), (docto(factura, 1, Decimal(1160), Decimal(10)),))),
    ):
        assert xsd_sat.errores(construir_xml(cfdi)) == []
