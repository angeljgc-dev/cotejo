"""B1 vencimiento, B2 saldo nunca negativo (propiedades) y B5 otra moneda."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cotejo.cxp import consultas, saldos
from cotejo.dinero import cuantizar
from cotejo.modelos import Alerta, Aplicacion
from tests.apoyo.fabricas import crear_factura, crear_proveedor, crear_usuario

HOY = date(2026, 11, 2)


def test_b1_vencimiento_con_30_dias_por_omision_y_tras_editar(
    cliente: TestClient, sesion: Session, entrar_como: Callable[[int], None]
) -> None:
    proveedor = crear_proveedor(sesion)
    assert proveedor.dias_credito == 30
    factura = crear_factura(sesion, proveedor=proveedor, fecha_emision=datetime.fromisoformat("2026-10-01T23:59:00"))
    entrar_como(crear_usuario(sesion).id)
    assert cliente.get(f"/api/facturas/{factura.id}").json()["vencimiento"] == "2026-10-31"
    assert cliente.get(f"/api/facturas/{factura.id}").json()["dias_vencido"] == 2

    r = cliente.patch(f"/api/proveedores/{proveedor.id}", json={"dias_credito": 45})
    assert r.status_code == 200 and r.json()["dias_credito"] == 45
    detalle = cliente.get(f"/api/facturas/{factura.id}").json()
    assert (detalle["vencimiento"], detalle["dias_vencido"]) == ("2026-11-15", -13)


@pytest.mark.parametrize("dias", [-1, 366, "30"])
def test_b1_dias_de_credito_fuera_de_rango(
    cliente: TestClient, sesion: Session, entrar_como: Callable[[int], None], dias: object
) -> None:
    proveedor = crear_proveedor(sesion)
    entrar_como(crear_usuario(sesion).id)
    r = cliente.patch(f"/api/proveedores/{proveedor.id}", json={"dias_credito": dias})
    assert r.status_code == 422 and r.json()["error"]["codigo"] == "VALIDACION"


_importes = st.decimals(min_value=Decimal("0.01"), max_value=Decimal("2000.00"), places=2)
_operacion = st.tuples(st.sampled_from(["complemento_pago", "nota_credito"]), _importes)


def test_b2_saldo_nunca_negativo_y_excedente_con_alerta(sesion: Session) -> None:
    proveedor = crear_proveedor(sesion)
    factura = crear_factura(sesion, proveedor=proveedor, total=Decimal("1160.00"))
    documentos = {
        "complemento_pago": crear_factura(sesion, proveedor=proveedor, tipo="P", total=Decimal(0)),
        "nota_credito": crear_factura(sesion, proveedor=proveedor, tipo="E", total=Decimal("116.00")),
    }

    @settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(operaciones=st.lists(_operacion, min_size=1, max_size=8))
    def caso(operaciones: list[tuple[str, Decimal]]) -> None:
        punto = sesion.begin_nested()
        try:
            for parcialidad, (origen, importe) in enumerate(operaciones, start=1):
                antes = saldos.saldo(sesion, factura.id)
                try:
                    aplicacion = saldos.aplicar(
                        sesion,
                        factura_id=factura.id,
                        importe=importe,
                        origen=origen,
                        fecha=HOY,
                        origen_factura_id=documentos[origen].id,
                        num_parcialidad=parcialidad,
                    )
                except saldos.SinSaldo:
                    assert antes == 0
                    continue
                despues = saldos.saldo(sesion, factura.id)
                assert despues >= 0
                assert aplicacion.importe == min(importe, antes)
                assert despues == antes - aplicacion.importe
                excede = sesion.execute(
                    select(func.count())
                    .select_from(Alerta)
                    .where(Alerta.factura_id == factura.id, Alerta.codigo == "PAGO_EXCEDE_SALDO")
                ).scalar_one()
                if cuantizar(importe - antes) > 0:
                    assert excede >= 1
            total_aplicado = sesion.execute(
                select(func.coalesce(func.sum(Aplicacion.importe), 0)).where(Aplicacion.factura_id == factura.id)
            ).scalar_one()
            assert Decimal(total_aplicado) <= factura.total
        finally:
            punto.rollback()

    caso()


def test_b5_otra_moneda_con_y_sin_tipo_de_cambio(sesion: Session) -> None:
    proveedor = crear_proveedor(sesion)
    pesos = crear_factura(sesion, proveedor=proveedor, total=Decimal("1160.00"))
    dolares = crear_factura(
        sesion, proveedor=proveedor, total=Decimal("100.00"), moneda="USD", tipo_cambio=Decimal("18.555")
    )
    sin_tc = crear_factura(sesion, proveedor=proveedor, total=Decimal("50.00"), moneda="USD")

    usd = consultas.resumen_factura(sesion, dolares.id, HOY)
    assert usd is not None
    assert (usd.moneda, usd.total, usd.tipo_cambio, usd.total_mxn, usd.saldo_mxn) == (
        "USD",
        Decimal("100.000000"),
        Decimal("18.555000"),
        Decimal("1855.50"),
        Decimal("1855.50"),
    )
    huerfana = consultas.resumen_factura(sesion, sin_tc.id, HOY)
    assert huerfana is not None and huerfana.saldo_mxn is None and huerfana.total_mxn is None

    tablero = consultas.tablero(sesion, HOY)
    assert tablero.adeudo_total_mxn == Decimal("1160.00") + Decimal("1855.50")
    # La factura sin tipo de cambio va aparte: su renglón no tiene equivalente en pesos.
    assert [(m.moneda, m.saldo, m.saldo_mxn) for m in tablero.adeudo_por_moneda] == [
        ("MXN", Decimal("1160.00"), Decimal("1160.00")),
        ("USD", Decimal("100.00"), Decimal("1855.50")),
        ("USD", Decimal("50.00"), None),
    ]
    convertibles = [m.saldo_mxn for m in tablero.adeudo_por_moneda if m.saldo_mxn is not None]
    assert sum(convertibles, Decimal(0)) == tablero.adeudo_total_mxn
    assert pesos.id != dolares.id
