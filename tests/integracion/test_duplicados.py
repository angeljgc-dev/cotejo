"""A5: posible duplicado con UUID distinto, en la factura más nueva y con enlace a la otra."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from cotejo.cxp import saldos
from cotejo.modelos import Alerta
from tests.apoyo.cfdi import RFC_B, factura_de, ingerir, ingreso

BASE = datetime.fromisoformat("2026-10-01T10:00:00")


def _duplicados(sesion: Session) -> list[Alerta]:
    return list(sesion.scalars(select(Alerta).where(Alerta.codigo == "POSIBLE_DUPLICADO")))


def test_misma_serie_y_folio_aunque_esten_lejos_en_fecha(sesion: Session) -> None:
    primera = ingreso(Decimal("1160.00"), folio="77", fecha=BASE)
    segunda = ingreso(Decimal("1160.00"), folio="77", fecha=BASE + timedelta(days=10))
    r = ingerir(sesion, primera, segunda)
    (alerta,) = _duplicados(sesion)
    assert alerta.factura_id == factura_de(sesion, segunda).id
    assert alerta.factura_relacionada_id == factura_de(sesion, primera).id
    assert alerta.severidad == "bloqueante"
    assert [m.codigo for m in r.archivos[1].motivos] == ["POSIBLE_DUPLICADO"]
    assert [b.codigo for b in saldos.bloqueos(sesion, factura_de(sesion, segunda).id)] == ["POSIBLE_DUPLICADO"]


@pytest.mark.parametrize(
    ("separacion", "duplicado"),
    [(timedelta(days=3), True), (timedelta(days=3, minutes=1), False), (timedelta(days=4), False)],
)
def test_mismo_total_cerca_en_fecha(sesion: Session, separacion: timedelta, duplicado: bool) -> None:
    ingerir(sesion, ingreso(Decimal("2320.00"), fecha=BASE), ingreso(Decimal("2320.00"), fecha=BASE + separacion))
    assert bool(_duplicados(sesion)) is duplicado


def test_la_alerta_va_en_la_mas_nueva_aunque_llegue_primero(sesion: Session) -> None:
    nueva = ingreso(Decimal("3480.00"), fecha=BASE + timedelta(days=1))
    vieja = ingreso(Decimal("3480.00"), fecha=BASE)
    ingerir(sesion, nueva)
    r = ingerir(sesion, vieja)
    (alerta,) = _duplicados(sesion)
    assert alerta.factura_id == factura_de(sesion, nueva).id
    assert alerta.factura_relacionada_id == factura_de(sesion, vieja).id
    assert "POSIBLE_DUPLICADO" in {m.codigo for m in r.archivos[0].motivos}


def test_otro_proveedor_u_otro_total_no_es_duplicado(sesion: Session) -> None:
    ingerir(
        sesion,
        ingreso(Decimal("4640.00"), fecha=BASE),
        ingreso(Decimal("4640.00"), fecha=BASE, emisor=RFC_B),
        ingreso(Decimal("4641.16"), fecha=BASE),
    )
    assert _duplicados(sesion) == []
