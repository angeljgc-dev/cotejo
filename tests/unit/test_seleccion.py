"""D5 sin base: barreras y selección voraz de una propuesta, con ejemplos y con datos generados."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from hypothesis import given
from hypothesis import strategies as st

from cotejo.cxp.consultas import BloqueoFactura, FacturaElegible, ProveedorCorto
from cotejo.propuestas import barreras
from cotejo.propuestas.seleccion import razon_de_pago, seleccionar

HOY = date(2026, 11, 2)
ZONA = ZoneInfo("America/Mexico_City")


def factura(
    factura_id: int,
    saldo: str,
    *,
    vence: date = HOY,
    tipo: str = "I",
    moneda: str = "MXN",
    saldo_mxn: str | None = "igual",
    bloqueos: list[BloqueoFactura] | None = None,
    en_propuesta: int | None = None,
) -> FacturaElegible:
    importe = Decimal(saldo)
    return FacturaElegible.model_validate(
        {
            "factura_id": factura_id,
            "uuid": f"00000000-0000-0000-0000-{factura_id:012d}",
            "tipo": tipo,
            "serie": "A",
            "folio": str(factura_id),
            "proveedor": ProveedorCorto(id=1, rfc="ZZA010101AAA", nombre="Proveedor Ficticio SA de CV"),
            "fecha_emision": datetime(2026, 10, 1, 10, 0, tzinfo=ZONA),
            "vencimiento": vence,
            "dias_vencido": (HOY - vence).days,
            "moneda": moneda,
            "tipo_cambio": None,
            "total": importe,
            "saldo": importe,
            "saldo_mxn": importe if saldo_mxn == "igual" else (Decimal(saldo_mxn) if saldo_mxn else None),
            "bloqueos": bloqueos or [],
            "en_propuesta_pendiente": en_propuesta,
        }
    )


def test_cada_barrera_tiene_su_codigo() -> None:
    bloqueo = BloqueoFactura(codigo="LISTA_69B", mensaje="El proveedor está en la lista 69-B.")
    casos = {
        barreras.NO_ES_INGRESO: factura(1, "0", tipo="E"),
        barreras.YA_PAGADA: factura(2, "0"),
        barreras.ALERTA_BLOQUEANTE: factura(3, "100.00", bloqueos=[bloqueo]),
        barreras.SIN_TIPO_CAMBIO: factura(4, "100.00", moneda="USD", saldo_mxn=None),
        barreras.EN_OTRA_PROPUESTA: factura(5, "100.00", en_propuesta=9),
    }
    for codigo, candidata in casos.items():
        incumplimiento = barreras.revisar(candidata, importe=candidata.saldo)
        assert incumplimiento is not None and incumplimiento.codigo == codigo, codigo
        assert incumplimiento.motivo
    excede = barreras.revisar(factura(6, "100.00"), importe=Decimal("100.01"))
    assert excede is not None and excede.codigo == barreras.EXCEDE_SALDO
    assert barreras.revisar(factura(7, "100.00"), importe=Decimal("100.00")) is None
    # Al aprobar, estar en la propia propuesta no cuenta como estar en otra.
    assert barreras.revisar(factura(8, "100.00", en_propuesta=9), importe=Decimal("100.00"), propuesta_propia=9) is None
    motivo_69b = barreras.revisar(casos[barreras.ALERTA_BLOQUEANTE], importe=Decimal("1"))
    assert motivo_69b is not None and "LISTA_69B" in motivo_69b.motivo and "lista 69-B" in motivo_69b.motivo


def test_seleccion_voraz_salta_la_que_no_cabe_y_sigue() -> None:
    candidatas = [
        factura(1, "600.00", vence=HOY - timedelta(days=10)),
        factura(2, "500.00", vence=HOY - timedelta(days=5)),
        factura(3, "400.00", vence=HOY + timedelta(days=2)),
        factura(4, "0.01", vence=HOY + timedelta(days=3)),
    ]
    seleccion = seleccionar(candidatas, Decimal("1000.00"), HOY)
    assert [r.factura.factura_id for r in seleccion.renglones] == [1, 3]
    assert seleccion.total_mxn == Decimal("1000.00")
    assert [(e.factura_id, e.codigo) for e in seleccion.excluidas] == [
        (2, barreras.EXCEDE_PRESUPUESTO),
        (4, barreras.EXCEDE_PRESUPUESTO),
    ]
    assert [r.razon for r in seleccion.renglones] == ["Vencida hace 10 días", "Vence el 4 de noviembre"]
    excluida = seleccion.excluidas[0]
    assert excluida.a_json() == {
        "factura_id": 2,
        "serie": "A",
        "folio": "2",
        "proveedor_nombre": "Proveedor Ficticio SA de CV",
        "saldo_mxn": "500.00",
        "codigo": "EXCEDE_PRESUPUESTO",
        "motivo": excluida.motivo,
    }
    assert "500.00" in excluida.motivo and "400.00" in excluida.motivo


def test_moneda_extranjera_cuenta_en_pesos_contra_el_presupuesto() -> None:
    dolares = factura(1, "100.00", moneda="USD", saldo_mxn="1850.00")
    assert seleccionar([dolares], Decimal("1849.99"), HOY).renglones == ()
    (renglon,) = seleccionar([dolares], Decimal("1850.00"), HOY).renglones
    assert renglon.importe == Decimal("100.00") and renglon.importe_mxn == Decimal("1850.00")


def test_razon_de_pago_en_palabras() -> None:
    assert razon_de_pago(HOY - timedelta(days=12), HOY) == "Vencida hace 12 días"
    assert razon_de_pago(HOY - timedelta(days=1), HOY) == "Venció ayer"
    assert razon_de_pago(HOY, HOY) == "Vence hoy"
    assert razon_de_pago(date(2026, 11, 14), HOY) == "Vence el 14 de noviembre"
    assert razon_de_pago(date(2027, 1, 5), HOY) == "Vence el 5 de enero de 2027"


centavos = st.integers(min_value=0, max_value=5_000_000).map(lambda c: Decimal(c) / 100)


@st.composite
def candidatas_generadas(draw: st.DrawFn) -> list[FacturaElegible]:
    cantidad = draw(st.integers(min_value=0, max_value=12))
    lista = []
    for i in range(1, cantidad + 1):
        clase = draw(st.sampled_from(["sana", "sana", "sana", "pagada", "bloqueada", "en_otra", "nota", "sin_cambio"]))
        saldo = draw(centavos)
        bloqueo = [BloqueoFactura(codigo="POSIBLE_DUPLICADO", mensaje="Posible duplicado.")]
        lista.append(
            factura(
                i,
                "0" if clase in ("pagada", "nota") else str(saldo),
                vence=HOY + timedelta(days=draw(st.integers(min_value=-120, max_value=30))),
                tipo="E" if clase == "nota" else "I",
                moneda="USD" if clase == "sin_cambio" else "MXN",
                saldo_mxn=None if clase == "sin_cambio" else "igual",
                bloqueos=bloqueo if clase == "bloqueada" else None,
                en_propuesta=77 if clase == "en_otra" else None,
            )
        )
    return lista


@given(candidatas=candidatas_generadas(), presupuesto=centavos.filter(lambda d: d > 0))
def test_invariantes_de_la_seleccion(candidatas: list[FacturaElegible], presupuesto: Decimal) -> None:
    seleccion = seleccionar(candidatas, presupuesto, HOY)
    elegidas = {r.factura.factura_id for r in seleccion.renglones}
    excluidas = {e.factura_id: e.codigo for e in seleccion.excluidas}
    # Cada candidata queda exactamente en un lado, con su motivo.
    assert elegidas.isdisjoint(excluidas)
    assert elegidas | set(excluidas) == {f.factura_id for f in candidatas}
    # Nunca se rebasa el presupuesto y el total es la suma exacta de los renglones.
    assert seleccion.total_mxn == sum((r.importe_mxn for r in seleccion.renglones), Decimal(0))
    assert seleccion.total_mxn <= presupuesto
    for renglon in seleccion.renglones:
        f = renglon.factura
        assert f.tipo == "I" and f.saldo > 0 and not f.bloqueos and f.en_propuesta_pendiente is None
        assert renglon.importe == f.saldo, "se propone el saldo completo, nunca más"
        assert renglon.importe_mxn == f.saldo_mxn
    # Voraz: una factura sana solo se excluye por presupuesto, y de verdad no cabía en su turno.
    acumulado = Decimal(0)
    for f in candidatas:
        if f.factura_id in elegidas:
            acumulado += f.saldo
        elif excluidas[f.factura_id] == barreras.EXCEDE_PRESUPUESTO:
            assert acumulado + f.saldo > presupuesto
