"""A7: notas de crédito (E) y complementos de pago (P), en orden y fuera de orden, con sus casos raros."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from cotejo.cxp import saldos
from cotejo.modelos import Alerta, Aplicacion
from tests.apoyo.cfdi import RFC_B, aplicado, docto, factura_de, ingerir, ingreso, nota, pago

DIA_PAGO = datetime.fromisoformat("2026-10-18T12:00:00")


def _alertas(sesion: Session, factura_id: int, codigo: str) -> list[Alerta]:
    return list(sesion.scalars(select(Alerta).where(Alerta.factura_id == factura_id, Alerta.codigo == codigo)))


def _codigos(resultado_archivo: object) -> set[str]:
    return {m.codigo for m in getattr(resultado_archivo, "motivos", ())}


def test_nota_despues_de_su_factura_reduce_el_saldo(sesion: Session) -> None:
    factura = ingreso(Decimal("1160.00"))
    ingerir(sesion, factura)
    resultado = ingerir(sesion, nota(Decimal("100.00"), factura.uuid))
    f = factura_de(sesion, factura)
    assert saldos.saldo(sesion, f.id) == Decimal("1044.00")
    assert resultado.archivos[0].resultado == "aceptada"


def test_nota_que_llega_antes_se_aplica_al_llegar_la_factura(sesion: Session) -> None:
    factura = ingreso(Decimal("2320.00"))
    la_nota = nota(Decimal("200.00"), factura.uuid)
    primero = ingerir(sesion, la_nota)
    assert "DOCUMENTO_RELACIONADO_PENDIENTE" in _codigos(primero.archivos[0])
    ingerir(sesion, factura)
    f, n = factura_de(sesion, factura), factura_de(sesion, la_nota)
    assert saldos.saldo(sesion, f.id) == Decimal("2088.00")
    pendiente = _alertas(sesion, n.id, "DOCUMENTO_RELACIONADO_PENDIENTE")
    assert [a.estado for a in pendiente] == ["resuelta"]


def test_pago_en_dos_parcialidades_liquida_la_factura(sesion: Session) -> None:
    factura = ingreso(Decimal("2320.00"))
    ingerir(sesion, factura)
    p1 = pago((DIA_PAGO, (docto(factura, 1, Decimal("2320.00"), Decimal("1000.00")),)))
    p2 = pago((DIA_PAGO, (docto(factura, 2, Decimal("1320.00"), Decimal("1320.00")),)))
    r = ingerir(sesion, p1, p2)
    f = factura_de(sesion, factura)
    assert saldos.saldo(sesion, f.id) == Decimal(0)
    assert [a.resultado for a in r.archivos] == ["aceptada", "aceptada"]
    parcialidades = sorted(
        n for n in sesion.scalars(select(Aplicacion.num_parcialidad).where(Aplicacion.factura_id == f.id)) if n
    )
    assert parcialidades == [1, 2]


def test_pago_que_llega_antes_que_su_factura(sesion: Session) -> None:
    factura = ingreso(Decimal("3480.00"))
    ingerir(sesion, pago((DIA_PAGO, (docto(factura, 1, Decimal("3480.00"), Decimal("480.00")),))))
    ingerir(sesion, factura)
    assert saldos.saldo(sesion, factura_de(sesion, factura).id) == Decimal("3000.00")


def test_complemento_repetido_no_aplica_dos_veces(sesion: Session) -> None:
    factura = ingreso(Decimal("4640.00"))
    complemento = pago((DIA_PAGO, (docto(factura, 1, Decimal("4640.00"), Decimal("640.00")),)))
    ingerir(sesion, factura, complemento)
    segundo = ingerir(sesion, complemento)
    assert segundo.archivos[0].resultado == "duplicada"
    assert aplicado(sesion, factura_de(sesion, factura).id) == Decimal("640.00")


def test_pago_que_excede_el_saldo_aplica_solo_hasta_el_saldo(sesion: Session) -> None:
    factura = ingreso(Decimal("1160.00"))
    ingerir(sesion, factura)
    r = ingerir(sesion, pago((DIA_PAGO, (docto(factura, 1, Decimal("1160.00"), Decimal("1500.00")),))))
    f = factura_de(sesion, factura)
    assert saldos.saldo(sesion, f.id) == Decimal(0)
    assert "PAGO_EXCEDE_SALDO" in _codigos(r.archivos[0])
    (alerta,) = _alertas(sesion, f.id, "PAGO_EXCEDE_SALDO")
    assert alerta.detalle["excedente"] == "340.000000"


def test_nota_de_otro_emisor_no_toca_la_factura(sesion: Session) -> None:
    factura = ingreso(Decimal("1160.00"))
    ingerir(sesion, factura)
    ajena = nota(Decimal("100.00"), factura.uuid, emisor=RFC_B)
    r = ingerir(sesion, ajena)
    assert saldos.saldo(sesion, factura_de(sesion, factura).id) == Decimal("1160.00")
    assert "DOCUMENTO_DE_OTRO_EMISOR" in _codigos(r.archivos[0])
    assert _alertas(sesion, factura_de(sesion, ajena).id, "DOCUMENTO_DE_OTRO_EMISOR")


def test_pago_en_otra_moneda_no_se_aplica(sesion: Session) -> None:
    factura = ingreso(Decimal("1160.00"))
    ingerir(sesion, factura)
    r = ingerir(sesion, pago((DIA_PAGO, (docto(factura, 1, Decimal("1160.00"), Decimal("50.00"), "USD"),))))
    f = factura_de(sesion, factura)
    assert saldos.saldo(sesion, f.id) == Decimal("1160.00")
    assert "PAGO_MONEDA_DISTINTA" in _codigos(r.archivos[0])
    assert _alertas(sesion, f.id, "PAGO_MONEDA_DISTINTA")


def test_pago_a_factura_pue_se_aplica_con_alerta(sesion: Session) -> None:
    factura = ingreso(Decimal("1160.00"), metodo_pago="PUE")
    ingerir(sesion, factura)
    ingerir(sesion, pago((DIA_PAGO, (docto(factura, 1, Decimal("1160.00"), Decimal("160.00")),))))
    f = factura_de(sesion, factura)
    assert saldos.saldo(sesion, f.id) == Decimal("1000.00")
    assert _alertas(sesion, f.id, "PAGO_A_FACTURA_PUE")


def test_saldo_anterior_distinto_alerta_y_aplica(sesion: Session) -> None:
    factura = ingreso(Decimal("1160.00"))
    ingerir(sesion, factura)
    ingerir(sesion, pago((DIA_PAGO, (docto(factura, 1, Decimal("999.00"), Decimal("100.00")),))))
    f = factura_de(sesion, factura)
    assert saldos.saldo(sesion, f.id) == Decimal("1060.00")
    (alerta,) = _alertas(sesion, f.id, "SALDO_ANTERIOR_DISTINTO")
    assert alerta.detalle["saldo_calculado"] == "1160.000000"


def test_nota_a_varias_facturas_reparte_por_fecha(sesion: Session) -> None:
    vieja = ingreso(Decimal("1160.00"), fecha=datetime.fromisoformat("2026-09-01T10:00:00"))
    nueva = ingreso(Decimal("2320.00"), fecha=datetime.fromisoformat("2026-09-20T10:00:00"))
    ingerir(sesion, vieja, nueva)
    r = ingerir(sesion, nota(Decimal("1500.00"), nueva.uuid, vieja.uuid))
    assert saldos.saldo(sesion, factura_de(sesion, vieja).id) == Decimal(0)
    assert saldos.saldo(sesion, factura_de(sesion, nueva).id) == Decimal("1740.00")
    assert "NOTA_VARIAS_FACTURAS" in _codigos(r.archivos[0])


def test_parcialidad_repetida_en_el_mismo_complemento_no_se_descarta_en_silencio(sesion: Session) -> None:
    """Dos nodos Pago a la misma factura con la misma parcialidad: el segundo no se aplica y queda a la vista."""
    factura = ingreso(Decimal("2320.00"))
    ingerir(sesion, factura)
    complemento = pago(
        (DIA_PAGO, (docto(factura, 1, Decimal("2320.00"), Decimal("500.00")),)),
        (datetime.fromisoformat("2026-10-19T12:00:00"), (docto(factura, 1, Decimal("1820.00"), Decimal("300.00")),)),
    )
    r = ingerir(sesion, complemento)
    f = factura_de(sesion, factura)
    assert aplicado(sesion, f.id) == Decimal("500.00")
    assert r.archivos[0].resultado == "aceptada_con_alertas"
    assert "PARCIALIDAD_REPETIDA" in _codigos(r.archivos[0])
    (alerta,) = _alertas(sesion, f.id, "PARCIALIDAD_REPETIDA")
    assert alerta.estado == "abierta"
    assert alerta.factura_relacionada_id == factura_de(sesion, complemento).id
    assert alerta.detalle["no_aplicado"] == "300.000000"
    assert "no se aplicó" in alerta.mensaje


def test_pago_que_senala_a_una_nota_no_se_descarta_en_silencio(sesion: Session) -> None:
    factura = ingreso(Decimal("1160.00"))
    la_nota = nota(Decimal("100.00"), factura.uuid)
    ingerir(sesion, factura, la_nota)
    complemento = pago((DIA_PAGO, (docto(la_nota, 1, Decimal("116.00"), Decimal("116.00")),)))
    r = ingerir(sesion, complemento)
    assert r.archivos[0].resultado == "aceptada_con_alertas"
    assert "DOCUMENTO_RELACIONADO_NO_ES_INGRESO" in _codigos(r.archivos[0])
    assert _alertas(sesion, factura_de(sesion, complemento).id, "DOCUMENTO_RELACIONADO_NO_ES_INGRESO")
    assert saldos.saldo(sesion, factura_de(sesion, factura).id) == Decimal("1044.00")


def test_misma_parcialidad_en_dos_complementos_distintos_no_aplica_dos_veces(sesion: Session) -> None:
    factura = ingreso(Decimal("2320.00"))
    ingerir(sesion, factura)
    primero = pago((DIA_PAGO, (docto(factura, 1, Decimal("2320.00"), Decimal("500.00")),)))
    segundo = pago((DIA_PAGO, (docto(factura, 1, Decimal("2320.00"), Decimal("500.00")),)))
    r = ingerir(sesion, primero, segundo)
    f = factura_de(sesion, factura)
    assert aplicado(sesion, f.id) == Decimal("500.00")
    assert "PARCIALIDAD_REPETIDA" in _codigos(r.archivos[1])
    (alerta,) = _alertas(sesion, f.id, "PARCIALIDAD_REPETIDA")
    assert alerta.factura_relacionada_id == factura_de(sesion, segundo).id


def test_sobrante_de_nota_queda_a_la_vista_aunque_la_ultima_factura_no_se_pueda_tocar(sesion: Session) -> None:
    propia = ingreso(Decimal("348.00"))
    ajena = ingreso(Decimal("1160.00"), emisor=RFC_B)
    ingerir(sesion, propia, ajena)
    la_nota = nota(Decimal("1000.00"), propia.uuid, ajena.uuid)
    r = ingerir(sesion, la_nota)
    assert saldos.saldo(sesion, factura_de(sesion, propia).id) == Decimal(0)
    assert {"PAGO_EXCEDE_SALDO", "DOCUMENTO_DE_OTRO_EMISOR"} <= _codigos(r.archivos[0])
    (alerta,) = _alertas(sesion, factura_de(sesion, propia).id, "PAGO_EXCEDE_SALDO")
    assert alerta.detalle["excedente"] == "812.000000"


def test_reparto_de_nota_a_varias_facturas_no_depende_del_orden_de_llegada(sesion: Session) -> None:
    vieja = ingreso(Decimal("1160.00"), fecha=datetime.fromisoformat("2026-09-01T10:00:00"))
    nueva = ingreso(Decimal("2320.00"), fecha=datetime.fromisoformat("2026-09-20T10:00:00"))
    la_nota = nota(Decimal("1000.00"), nueva.uuid, vieja.uuid)
    ingerir(sesion, la_nota)
    ingerir(sesion, nueva)
    assert saldos.saldo(sesion, factura_de(sesion, nueva).id) == Decimal("2320.00")
    ingerir(sesion, vieja)
    # Igual que si las facturas hubieran llegado primero: se reparte por fecha de emisión.
    assert saldos.saldo(sesion, factura_de(sesion, vieja).id) == Decimal(0)
    assert saldos.saldo(sesion, factura_de(sesion, nueva).id) == Decimal("2320.00")
    (pendiente,) = _alertas(sesion, factura_de(sesion, la_nota).id, "DOCUMENTO_RELACIONADO_PENDIENTE")
    assert pendiente.estado == "resuelta"
