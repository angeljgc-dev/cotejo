"""A1, A2 y A4 por HTTP: campos guardados, resultado por archivo e idempotencia de la carga."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from lxml import etree
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from cotejo.api.rutas_cargas import CargaSalida
from cotejo.ingesta import servicio
from cotejo.ingesta.servicio import ingerir_lote
from cotejo.modelos import Concepto, Factura, Proveedor, Usuario
from tests.apoyo.cfdi import AHORA, FIXTURES, huella_tablas
from tests.apoyo.fabricas import EMPRESA_RFC, crear_usuario

VALIDOS = sorted((FIXTURES / "validos").glob("*.xml"))
NS = {
    "cfdi": "http://www.sat.gob.mx/cfd/4",
    "tfd": "http://www.sat.gob.mx/TimbreFiscalDigital",
}


def _subir(cliente: TestClient, archivos: list[tuple[str, bytes]]) -> CargaSalida:
    r = cliente.post(
        "/api/cargas/cfdi", files=[("archivos", (nombre, datos, "application/xml")) for nombre, datos in archivos]
    )
    assert r.status_code == 200, r.text
    return CargaSalida.model_validate(r.json())


@pytest.fixture
def como_capturista(sesion: Session, entrar_como: Callable[[int], None]) -> None:
    entrar_como(crear_usuario(sesion, rol="capturista").id)


def _dec(valor: str | None) -> Decimal | None:
    return None if valor is None else Decimal(valor)


@pytest.mark.parametrize("ruta", VALIDOS, ids=lambda p: p.stem)
def test_a1_guarda_cada_campo_del_xml(cliente: TestClient, sesion: Session, como_capturista: None, ruta: Path) -> None:
    datos = ruta.read_bytes()
    cuerpo = _subir(cliente, [(ruta.name, datos)])
    (archivo,) = cuerpo.archivos
    assert archivo.resultado in ("aceptada", "aceptada_con_alertas")

    # Oráculo independiente del lector de Cotejo: los atributos tal como vienen en el XML.
    raiz = etree.fromstring(datos)
    emisor, receptor = raiz.find("cfdi:Emisor", NS), raiz.find("cfdi:Receptor", NS)
    timbre = raiz.find("cfdi:Complemento/tfd:TimbreFiscalDigital", NS)
    impuestos = raiz.find("cfdi:Impuestos", NS)
    assert emisor is not None and receptor is not None and timbre is not None
    f = sesion.scalars(select(Factura).where(Factura.id == archivo.factura_id)).one()
    assert f.uuid == timbre.get("UUID")
    assert (f.serie, f.folio) == (raiz.get("Serie"), raiz.get("Folio"))
    assert f.fecha_emision.isoformat() == raiz.get("Fecha")
    assert (f.emisor_rfc, f.emisor_nombre) == (emisor.get("Rfc"), emisor.get("Nombre"))
    assert (f.receptor_rfc, f.receptor_nombre, f.receptor_uso_cfdi) == (
        receptor.get("Rfc"),
        receptor.get("Nombre"),
        receptor.get("UsoCFDI"),
    )
    assert f.subtotal == Decimal(raiz.get("SubTotal", ""))
    assert f.descuento == (_dec(raiz.get("Descuento")) or 0)
    assert f.total == Decimal(raiz.get("Total", ""))
    assert f.moneda == raiz.get("Moneda")
    assert f.tipo_cambio == _dec(raiz.get("TipoCambio"))
    assert (f.metodo_pago, f.forma_pago, f.tipo) == (
        raiz.get("MetodoPago"),
        raiz.get("FormaPago"),
        raiz.get("TipoDeComprobante"),
    )
    traslados = None if impuestos is None else impuestos.get("TotalImpuestosTrasladados")
    retenidos = None if impuestos is None else impuestos.get("TotalImpuestosRetenidos")
    assert f.total_impuestos_trasladados == _dec(traslados)
    assert f.total_impuestos_retenidos == _dec(retenidos)
    conceptos = raiz.findall("cfdi:Conceptos/cfdi:Concepto", NS)
    guardados = sesion.scalars(select(Concepto).where(Concepto.factura_id == f.id).order_by(Concepto.orden)).all()
    assert [(c.descripcion, c.importe, c.cantidad) for c in guardados] == [
        (c.get("Descripcion"), Decimal(c.get("Importe", "")), Decimal(c.get("Cantidad", ""))) for c in conceptos
    ]
    proveedor = sesion.get(Proveedor, f.proveedor_id)
    assert proveedor is not None and proveedor.rfc == emisor.get("Rfc")


def test_a1_proveedor_se_crea_una_sola_vez_por_rfc(cliente: TestClient, sesion: Session, como_capturista: None) -> None:
    base = (FIXTURES / "validos" / "ingreso_mxn.xml").read_bytes()
    otra = base.replace(b"0A1B2C3D-0001-4000-8000-000000000001", b"0A1B2C3D-0001-4000-8000-0000000000FF").replace(
        b'Folio="1001"', b'Folio="2002"'
    )
    _subir(cliente, [("a.xml", base), ("b.xml", otra)])
    assert len(sesion.scalars(select(Proveedor).where(Proveedor.rfc == "ZZA100115AB6")).all()) == 1


def test_a2_un_resultado_por_archivo_y_un_archivo_malo_no_tumba_el_lote(
    cliente: TestClient, como_capturista: None
) -> None:
    bueno = (FIXTURES / "validos" / "ingreso_mxn.xml").read_bytes()
    cuerpo = _subir(
        cliente,
        [
            ("roto.xml", b"<cfdi:Comprobante"),
            ("v33.xml", bueno.replace(b"http://www.sat.gob.mx/cfd/4", b"http://www.sat.gob.mx/cfd/3")),
            ("sin_timbre.xml", bueno.replace(b"tfd:TimbreFiscalDigital ", b"tfd:Otro ")),
            ("nomina.xml", bueno.replace(b'TipoDeComprobante="I"', b'TipoDeComprobante="N"')),
            ("traslado.xml", bueno.replace(b'TipoDeComprobante="I"', b'TipoDeComprobante="T"')),
            ("bueno.xml", bueno),
        ],
    )
    archivos = cuerpo.archivos
    codigos = [(a.nombre, a.resultado, [m.codigo for m in a.motivos]) for a in archivos]
    assert codigos[:5] == [
        ("roto.xml", "rechazada", ["XML_MAL_FORMADO"]),
        ("v33.xml", "rechazada", ["NO_ES_CFDI40"]),
        ("sin_timbre.xml", "rechazada", ["SIN_TIMBRE"]),
        ("nomina.xml", "rechazada", ["TIPO_NO_SOPORTADO"]),
        ("traslado.xml", "rechazada", ["TIPO_NO_SOPORTADO"]),
    ]
    assert codigos[5][1] in ("aceptada", "aceptada_con_alertas")
    assert all(m.mensaje and m.severidad == "rechazo" for a in archivos[:5] for m in a.motivos)
    assert cuerpo.resumen.model_dump() == {
        "aceptadas": 1 if codigos[5][1] == "aceptada" else 0,
        "con_alertas": 1 if codigos[5][1] == "aceptada_con_alertas" else 0,
        "rechazadas": 5,
        "duplicadas": 0,
    }


def test_a4_mismo_lote_dos_veces_deja_la_base_igual(
    cliente: TestClient, sesion: Session, como_capturista: None
) -> None:
    lote = [(p.name, p.read_bytes()) for p in VALIDOS]
    primero = _subir(cliente, lote)
    antes = huella_tablas(sesion)
    segundo = _subir(cliente, lote)
    assert huella_tablas(sesion) == antes
    archivos = segundo.archivos
    assert all(a.resultado == "duplicada" and a.ya_existia for a in archivos)
    assert all([m.codigo for m in a.motivos] == ["UUID_YA_REGISTRADO"] for a in archivos)
    assert [a.factura_id for a in archivos] == [a.factura_id for a in primero.archivos]
    assert segundo.resumen.model_dump() == {"aceptadas": 0, "con_alertas": 0, "rechazadas": 0, "duplicadas": len(lote)}


def test_dos_cargas_simultaneas_se_ponen_en_fila(motor: Engine) -> None:
    """Una nota y su factura en cargas simultáneas: sin fila, la factura no vería la nota aún sin confirmar."""
    with motor.connect() as primera, motor.connect() as segunda:
        primera.begin()
        segunda.begin()
        with Session(bind=primera) as s1:
            usuario = Usuario(usuario="fila.capturista", nombre="Persona Ficticia", rol="capturista")
            s1.add(usuario)
            s1.flush()
            ingerir_lote(s1, usuario_id=usuario.id, entradas=[], empresa_rfc=EMPRESA_RFC, ahora=AHORA)
            libre = segunda.execute(
                text("SELECT pg_try_advisory_xact_lock(:clave)"), {"clave": servicio.CLAVE_FILA_CARGAS}
            ).scalar_one()
            assert libre is False
        primera.rollback()
        segunda.rollback()
