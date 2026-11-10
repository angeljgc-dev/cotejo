"""D5: cada barrera con su código, por los tres caminos que crean propuestas (API, asistente y MCP).

Las barreras viven en el servicio de propuestas, así que el resultado debe ser idéntico venga de donde venga
la petición. Al aprobar se vuelven a aplicar contra el estado de ese momento.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal

import anyio
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mcp import Client
from sqlalchemy import func, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from cotejo.asistente.guionado import PasoGuion
from cotejo.config import Settings
from cotejo.cxp import alertas, saldos
from cotejo.mcp_servidor import crear_servidor
from cotejo.modelos import Alerta, Aplicacion, Factura, Propuesta, RenglonPropuesta, Usuario
from cotejo.propuestas import servicio
from tests.apoyo.fabricas import crear_usuario
from tests.integracion.apoyo_asistente import (
    Entrar,
    bloquear,
    como_dict,
    elementos,
    factura_con,
    instalar_guion,
    ultimo_resultado,
)

HOY = date(2026, 11, 2)
VENCIDA = "2026-09-20"
CANALES = ("api", "asistente", "mcp")

# Devuelve (ids de facturas incluidas, [(factura_id, código)] de las excluidas).
Proponer = Callable[[str, list[int]], tuple[list[int], list[tuple[int, str]]]]


@pytest.fixture
def proponer(
    request: pytest.FixtureRequest,
    app: FastAPI,
    cliente: TestClient,
    sesion: Session,
    config: Settings,
    entrar_como: Entrar,
) -> Proponer:
    """Pide una propuesta por el canal indicado en el parámetro de la prueba, con el usuario capturista."""
    canal = str(request.param)
    capturista = crear_usuario(sesion, rol="capturista", usuario=config.mcp_usuario)
    entrar_como(capturista.id)

    def _leer(datos: dict[str, object]) -> tuple[list[int], list[tuple[int, str]]]:
        incluidas = [int(str(r["factura_id"])) for r in elementos(datos, "renglones")] if "renglones" in datos else []
        return incluidas, [(int(str(e["factura_id"])), str(e["codigo"])) for e in elementos(datos, "excluidas")]

    def por_api(presupuesto: str, ids: list[int]) -> tuple[list[int], list[tuple[int, str]]]:
        r = cliente.post(
            "/api/propuestas",
            json={"presupuesto_mxn": presupuesto, "fecha_limite": HOY.isoformat(), "factura_ids": ids},
        )
        if r.status_code == 422:
            assert r.json()["error"]["codigo"] == "PROPUESTA_VACIA"
            return _leer(como_dict(r.json()["error"]["detalle"]))
        assert r.status_code == 200, r.text
        cuerpo = como_dict(r.json())
        incluidas = [int(str(como_dict(x["factura"])["id"])) for x in elementos(cuerpo, "renglones")]
        return incluidas, _leer({"excluidas": cuerpo["excluidas"]})[1]

    def por_asistente(presupuesto: str, ids: list[int]) -> tuple[list[int], list[tuple[int, str]]]:
        guion = instalar_guion(
            app,
            [
                PasoGuion(llamadas=[("proponer_pagos", {"presupuesto_mxn": presupuesto, "factura_ids": ids})]),
                PasoGuion(texto="Listo."),
            ],
        )
        r = cliente.post("/api/asistente/mensajes", json={"texto": f"Propón pagar con presupuesto de {presupuesto}"})
        assert r.status_code == 200, r.text
        return _leer(ultimo_resultado(guion.recibidos[1]))

    def por_mcp(presupuesto: str, ids: list[int]) -> tuple[list[int], list[tuple[int, str]]]:
        @contextmanager
        def misma_sesion() -> Iterator[Session]:
            yield sesion

        async def llamar() -> dict[str, object]:
            async with Client(crear_servidor(misma_sesion, config), raise_exceptions=True) as mcp:
                resultado = await mcp.call_tool("proponer_pagos", {"presupuesto_mxn": presupuesto, "factura_ids": ids})
            return como_dict(resultado.structured_content)

        return _leer(anyio.run(llamar))

    return {"api": por_api, "asistente": por_asistente, "mcp": por_mcp}[canal]


def _origenes(sesion: Session) -> list[str]:
    return list(sesion.scalars(select(Propuesta.origen).order_by(Propuesta.id)))


@pytest.mark.parametrize("proponer", CANALES, indirect=True)
@pytest.mark.parametrize("codigo_alerta", ["LISTA_69B", "POSIBLE_DUPLICADO", "RECEPTOR_AJENO"])
def test_factura_con_alerta_bloqueante_no_se_propone(sesion: Session, proponer: Proponer, codigo_alerta: str) -> None:
    sana = factura_con(sesion, "1000.00", VENCIDA)
    bloqueada = factura_con(sesion, "500.00", VENCIDA)
    if codigo_alerta == "LISTA_69B":
        # La alerta de la lista 69-B es del proveedor y pesa sobre todas sus facturas.
        alertas.abrir(
            sesion,
            codigo="LISTA_69B",
            severidad="bloqueante",
            mensaje="En lista 69-B.",
            proveedor_id=bloqueada.proveedor_id,
        )
        sesion.commit()
    else:
        bloquear(sesion, codigo_alerta, factura=bloqueada)
    incluidas, excluidas = proponer("5000.00", [sana.id, bloqueada.id])
    assert incluidas == [sana.id]
    assert excluidas == [(bloqueada.id, "ALERTA_BLOQUEANTE")]
    assert (
        sesion.scalar(
            select(func.count()).select_from(RenglonPropuesta).where(RenglonPropuesta.factura_id == bloqueada.id)
        )
        == 0
    )


@pytest.mark.parametrize("proponer", CANALES, indirect=True)
def test_ya_pagada_nota_de_credito_en_otra_propuesta_sin_tipo_de_cambio_e_inexistente(
    sesion: Session, proponer: Proponer
) -> None:
    sana = factura_con(sesion, "1000.00", VENCIDA)
    pagada = factura_con(sesion, "400.00", VENCIDA)
    nota = factura_con(sesion, "400.00", VENCIDA, tipo="E")
    saldos.aplicar(
        sesion,
        factura_id=pagada.id,
        importe=Decimal("400.00"),
        origen="nota_credito",
        fecha=HOY,
        origen_factura_id=nota.id,
    )
    sin_cambio = factura_con(sesion, "100.00", VENCIDA, moneda="USD")
    en_otra = factura_con(sesion, "300.00", VENCIDA)
    otro = crear_usuario(sesion, rol="capturista")
    previa = servicio.crear_propuesta(
        sesion, usuario=otro, presupuesto_mxn=Decimal("300.00"), origen="api", hoy=HOY, factura_ids=[en_otra.id]
    )
    sesion.commit()

    incluidas, excluidas = proponer("5000.00", [sana.id, pagada.id, nota.id, sin_cambio.id, en_otra.id, 987654321])
    assert incluidas == [sana.id]
    assert sorted(excluidas) == sorted(
        [
            (pagada.id, "YA_PAGADA"),
            (nota.id, "NO_ES_INGRESO"),
            (sin_cambio.id, "SIN_TIPO_CAMBIO"),
            (en_otra.id, "EN_OTRA_PROPUESTA"),
            (987654321, "FACTURA_NO_ENCONTRADA"),
        ]
    )
    assert sesion.scalar(select(Propuesta.estado).where(Propuesta.id == previa.id)) == "pendiente"
    assert sesion.scalar(select(func.count()).select_from(Aplicacion)) == 1, "solo la nota de crédito de la preparación"


@pytest.mark.parametrize("proponer", CANALES, indirect=True)
def test_nunca_se_rebasa_el_presupuesto_ni_el_saldo(sesion: Session, proponer: Proponer) -> None:
    grande = factura_con(sesion, "800.00", "2026-09-01")
    mediana = factura_con(sesion, "300.00", "2026-09-10")
    chica = factura_con(sesion, "200.00", "2026-09-20")
    dolares = factura_con(sesion, "10.00", "2026-09-25", moneda="USD", tipo_cambio=Decimal("18.50"))
    incluidas, excluidas = proponer("1000.00", [grande.id, mediana.id, chica.id, dolares.id])
    # 800 entra; 300 ya no cabe; 200 sí; 10 dólares son 185 pesos y ya no caben en lo que queda.
    assert incluidas == [grande.id, chica.id]
    assert excluidas == [(mediana.id, "EXCEDE_PRESUPUESTO"), (dolares.id, "EXCEDE_PRESUPUESTO")]
    propuesta = sesion.scalars(select(Propuesta).order_by(Propuesta.id.desc())).first()
    assert propuesta is not None and propuesta.estado == "pendiente"
    assert propuesta.total_mxn == Decimal("1000.00") and propuesta.total_mxn <= propuesta.presupuesto_mxn
    for renglon in propuesta.renglones:
        assert renglon.importe == saldos.saldo(sesion, renglon.factura_id), "se propone el saldo, nunca más"
    # La base tampoco acepta una propuesta cuyo total rebase su presupuesto.
    with pytest.raises(DBAPIError), sesion.begin_nested():
        sesion.execute(update(Propuesta).where(Propuesta.id == propuesta.id).values(total_mxn=Decimal("1000.01")))


@pytest.mark.parametrize("proponer", CANALES, indirect=True)
def test_si_ninguna_pasa_no_se_crea_propuesta(sesion: Session, proponer: Proponer) -> None:
    cara = factura_con(sesion, "900.00", VENCIDA)
    bloqueada = factura_con(sesion, "50.00", VENCIDA)
    bloquear(sesion, "POSIBLE_DUPLICADO", factura=bloqueada)
    incluidas, excluidas = proponer("100.00", [cara.id, bloqueada.id])
    assert incluidas == []
    # Mismas exclusiones por los tres caminos; el asistente y MCP muestran primero las que no son por presupuesto.
    assert sorted(excluidas) == sorted([(cara.id, "EXCEDE_PRESUPUESTO"), (bloqueada.id, "ALERTA_BLOQUEANTE")])
    assert sesion.scalar(select(func.count()).select_from(Propuesta)) == 0


@pytest.mark.parametrize("proponer", CANALES, indirect=True)
def test_el_origen_de_la_propuesta_queda_registrado(
    request: pytest.FixtureRequest, sesion: Session, proponer: Proponer
) -> None:
    factura = factura_con(sesion, "100.00", VENCIDA)
    assert proponer("100.00", [factura.id]) == ([factura.id], [])
    canal = request.node.callspec.params["proponer"]
    assert _origenes(sesion) == [canal]


def test_una_alerta_resuelta_deja_de_bloquear_y_en_dolares_cuenta_el_equivalente_en_pesos(sesion: Session) -> None:
    capturista = crear_usuario(sesion, rol="capturista")
    duplicada = factura_con(sesion, "500.00", VENCIDA)
    bloquear(sesion, "POSIBLE_DUPLICADO", factura=duplicada)
    dolares = factura_con(sesion, "100.00", VENCIDA, moneda="USD", tipo_cambio=Decimal("18.50"))
    with pytest.raises(servicio.ErrorPropuesta) as info:
        servicio.crear_propuesta(
            sesion, usuario=capturista, presupuesto_mxn=Decimal("1849.99"), origen="api", hoy=HOY, horizonte="vencidas"
        )
    assert info.value.codigo == "PROPUESTA_VACIA"
    sesion.execute(
        update(Alerta).where(Alerta.factura_id == duplicada.id).values(estado="resuelta", resuelta_en=func.now())
    )
    sesion.commit()
    propuesta = servicio.crear_propuesta(
        sesion, usuario=capturista, presupuesto_mxn=Decimal("2350.00"), origen="api", hoy=HOY, horizonte="vencidas"
    )
    assert {(r.factura_id, r.importe, r.importe_mxn) for r in propuesta.renglones} == {
        (duplicada.id, Decimal("500.00"), Decimal("500.00")),
        (dolares.id, Decimal("100.00"), Decimal("1850.00")),
    }
    assert propuesta.total_mxn == Decimal("2350.00")


def _propuesta_de(sesion: Session, *totales: str) -> tuple[Propuesta, list[Factura], Usuario]:
    capturista = crear_usuario(sesion, rol="capturista")
    facturas = [factura_con(sesion, total, VENCIDA) for total in totales]
    propuesta = servicio.crear_propuesta(
        sesion,
        usuario=capturista,
        presupuesto_mxn=Decimal("100000.00"),
        origen="api",
        hoy=HOY,
        factura_ids=[f.id for f in facturas],
    )
    sesion.commit()
    return propuesta, facturas, crear_usuario(sesion, rol="aprobador")


def test_al_aprobar_se_revalidan_las_barreras_contra_el_estado_actual(
    cliente: TestClient, sesion: Session, entrar_como: Entrar
) -> None:
    propuesta, (bajo, pagada, bloqueada, intacta), aprobador = _propuesta_de(
        sesion, "1000.00", "400.00", "500.00", "250.00"
    )
    # Después de armarla: llega una nota de crédito parcial, otra factura se liquida y un proveedor entra a la 69-B.
    for factura, importe in ((bajo, "300.00"), (pagada, "400.00")):
        nota = factura_con(sesion, importe, VENCIDA, tipo="E")
        saldos.aplicar(
            sesion,
            factura_id=factura.id,
            importe=Decimal(importe),
            origen="nota_credito",
            fecha=HOY,
            origen_factura_id=nota.id,
        )
    alertas.abrir(
        sesion,
        codigo="LISTA_69B",
        severidad="bloqueante",
        mensaje="En lista 69-B.",
        proveedor_id=bloqueada.proveedor_id,
    )
    sesion.commit()
    entrar_como(aprobador.id)

    r = cliente.post(f"/api/propuestas/{propuesta.id}/aprobar", json={})
    assert r.status_code == 409
    error = r.json()["error"]
    assert error["codigo"] == "RENGLONES_INVALIDOS"
    assert isinstance(error["detalle"], dict), "el detalle es un objeto con la lista adentro"
    renglones = {x.factura_id: x.id for x in propuesta.renglones}
    assert sorted((x["renglon_id"], x["codigo"]) for x in error["detalle"]["renglones"]) == sorted(
        [
            (renglones[bajo.id], "EXCEDE_SALDO"),
            (renglones[pagada.id], "YA_PAGADA"),
            (renglones[bloqueada.id], "ALERTA_BLOQUEANTE"),
        ]
    )
    assert all(x["motivo"] for x in error["detalle"]["renglones"])
    # No se aplicó nada, ni siquiera el renglón que seguía siendo válido.
    assert sesion.scalar(select(func.count()).select_from(Aplicacion).where(Aplicacion.origen == "pago_aprobado")) == 0
    assert saldos.saldo(sesion, intacta.id) == Decimal("250.00") and saldos.saldo(sesion, bajo.id) == Decimal("700.00")
    assert sesion.scalar(select(Propuesta.estado).where(Propuesta.id == propuesta.id)) == "pendiente"
    # Se rechaza y se pide otra: la nueva ya refleja el estado actual.
    assert (
        cliente.post(f"/api/propuestas/{propuesta.id}/rechazar", json={"motivo": "Cambiaron los saldos."}).status_code
        == 200
    )


def test_dos_propuestas_no_pueden_llevar_la_misma_factura_ni_pagarla_dos_veces(sesion: Session) -> None:
    propuesta, (factura,), aprobador = _propuesta_de(sesion, "600.00")
    otro = crear_usuario(sesion, rol="capturista")
    with pytest.raises(servicio.ErrorPropuesta) as info:
        servicio.crear_propuesta(
            sesion, usuario=otro, presupuesto_mxn=Decimal("600.00"), origen="api", hoy=HOY, factura_ids=[factura.id]
        )
    assert como_dict(elementos(info.value.detalle, "excluidas")[0])["codigo"] == "EN_OTRA_PROPUESTA"
    servicio.aprobar(sesion, propuesta_id=propuesta.id, usuario=aprobador, hoy=HOY)
    sesion.commit()
    with pytest.raises(servicio.ErrorPropuesta) as pagada:
        servicio.crear_propuesta(
            sesion, usuario=otro, presupuesto_mxn=Decimal("600.00"), origen="api", hoy=HOY, factura_ids=[factura.id]
        )
    assert como_dict(elementos(pagada.value.detalle, "excluidas")[0])["codigo"] == "YA_PAGADA"
    assert sesion.scalar(select(func.count()).select_from(Aplicacion)) == 1
    assert saldos.saldo(sesion, factura.id) == 0
