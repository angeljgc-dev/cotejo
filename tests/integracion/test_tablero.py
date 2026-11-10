"""B4 tablero contra datos conocidos y B3 como propiedad: la suma de los grupos es el adeudo total."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import literal, select
from sqlalchemy.orm import Session

from cotejo.cxp import alertas, consultas
from cotejo.cxp.antiguedad import columna_grupo, grupo_de
from tests.apoyo.fabricas import crear_carga_archivo, crear_factura, crear_proveedor, crear_usuario
from tests.apoyo.masivo import FacturaMasiva, insertar

HOY = date(2026, 11, 2)


def test_b4_tablero_por_http_con_datos_conocidos(
    cliente: TestClient, sesion: Session, entrar_como: Callable[[int], None]
) -> None:
    uno = crear_proveedor(sesion, nombre="Uno Ficticio SA")
    dos = crear_proveedor(sesion, nombre="Dos Ficticio SA")
    crear_factura(
        sesion, proveedor=uno, total=Decimal("1160.00"), fecha_emision=datetime.fromisoformat("2026-10-20T09:00:00")
    )
    crear_factura(
        sesion, proveedor=uno, total=Decimal("2320.00"), fecha_emision=datetime.fromisoformat("2026-10-05T09:00:00")
    )
    crear_factura(
        sesion, proveedor=uno, total=Decimal("580.00"), fecha_emision=datetime.fromisoformat("2026-09-01T09:00:00")
    )
    vieja = crear_factura(
        sesion, proveedor=dos, total=Decimal("10000.00"), fecha_emision=datetime.fromisoformat("2026-06-01T09:00:00")
    )
    alertas.abrir(sesion, codigo="RECEPTOR_AJENO", severidad="bloqueante", mensaje="Ajena", factura_id=vieja.id)
    sesion.commit()
    entrar_como(crear_usuario(sesion).id)

    r = cliente.get("/api/tablero")
    assert r.status_code == 200
    t = r.json()
    assert t["fecha_corte"] == "2026-11-02"
    assert t["adeudo_total_mxn"] == "14060.00"
    assert t["adeudo_por_moneda"] == [{"moneda": "MXN", "saldo": "14060.00", "saldo_mxn": "14060.00"}]
    assert [(p["proveedor"]["nombre"], p["saldo_mxn"], p["facturas"]) for p in t["por_proveedor"]] == [
        ("Dos Ficticio SA", "10000.00", 1),
        ("Uno Ficticio SA", "4060.00", 3),
    ]
    assert t["otros_proveedores"] == {"saldo_mxn": "0.00", "proveedores": 0}
    assert [(g["grupo"], g["saldo_mxn"], g["facturas"]) for g in t["antiguedad"]] == [
        ("por_vencer", "3480.00", 2),
        ("1_30", "0.00", 0),
        ("31_60", "580.00", 1),
        ("61_90", "0.00", 0),
        ("mas_90", "10000.00", 1),
    ]
    assert t["vencen_7_dias"] == {"saldo_mxn": "2320.00", "facturas": 1}
    assert t["vencen_30_dias"] == {"saldo_mxn": "3480.00", "facturas": 2}
    assert (t["facturas_con_alertas"], t["facturas_bloqueadas"], t["propuestas_pendientes"]) == (1, 1, 0)


def test_b4_mas_de_diez_proveedores_van_a_otros(sesion: Session) -> None:
    for n in range(12):
        crear_factura(
            sesion,
            proveedor=crear_proveedor(sesion),
            total=Decimal(1000 + n),
            fecha_emision=datetime.fromisoformat("2026-10-01T00:00:00"),
        )
    t = consultas.tablero(sesion, HOY)
    assert len(t.por_proveedor) == 10
    assert (t.otros_proveedores.proveedores, t.otros_proveedores.saldo_mxn) == (2, Decimal("2001.00"))


_factura = st.tuples(
    st.integers(min_value=-60, max_value=400),
    st.decimals(min_value=Decimal("0.01"), max_value=Decimal("999999.99"), places=2),
    st.sampled_from([("MXN", None), ("USD", Decimal("18.123456")), ("USD", None)]),
)


def test_b3_suma_de_grupos_igual_al_adeudo_con_datos_generados(sesion: Session) -> None:
    proveedor = crear_proveedor(sesion, dias_credito=0)
    archivo = crear_carga_archivo(sesion)

    @settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(facturas=st.lists(_factura, max_size=25))
    def caso(facturas: list[tuple[int, Decimal, tuple[str, Decimal | None]]]) -> None:
        punto = sesion.begin_nested()
        try:
            insertar(
                sesion,
                [
                    FacturaMasiva(
                        proveedor_id=proveedor.id,
                        proveedor_rfc=proveedor.rfc,
                        total=total,
                        # Con cero días de crédito, los días vencidos son los días desde la emisión.
                        fecha_emision=datetime.combine(HOY - timedelta(days=dias), time(10)),
                        moneda=moneda,
                        tipo_cambio=tc,
                    )
                    for dias, total, (moneda, tc) in facturas
                ],
                carga_archivo_id=archivo.id,
            )
            antiguedad = consultas.antiguedad(sesion, HOY)
            tablero = consultas.tablero(sesion, HOY)
            suma = sum((g.saldo_mxn for g in antiguedad.grupos), Decimal(0))
            assert suma == antiguedad.adeudo_total_mxn == tablero.adeudo_total_mxn
            # Oráculo en Python: cada factura convertible se redondea a centavos y cae en un solo grupo.
            esperado: dict[str, Decimal] = {}
            for dias, total, (moneda, tc) in facturas:
                if moneda != "MXN" and tc is None:
                    continue
                pesos = total if tc is None else (total * tc).quantize(Decimal("0.01"))
                esperado[grupo_de(dias)] = esperado.get(grupo_de(dias), Decimal(0)) + pesos
            assert {g.grupo: g.saldo_mxn for g in antiguedad.grupos if g.facturas} == esperado
        finally:
            punto.rollback()

    caso()


def test_b3_la_regla_en_sql_es_la_misma_que_en_python(sesion: Session) -> None:
    for dias in (-1, 0, 1, 30, 31, 60, 61, 90, 91):
        assert sesion.execute(select(columna_grupo(literal(dias)))).scalar_one() == grupo_de(dias)
