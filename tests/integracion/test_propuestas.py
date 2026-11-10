"""D3 y D4: una propuesta nace pendiente y no mueve nada; aprobarla es de otra persona y es todo o nada."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from cotejo import bitacora
from cotejo.cxp import saldos
from cotejo.modelos import Aplicacion, Bitacora, Factura, Propuesta, Proveedor, RenglonPropuesta, Usuario
from cotejo.propuestas import servicio
from tests.apoyo.fabricas import crear_factura, crear_proveedor, crear_usuario

Entrar = Callable[[int], None]
HOY = date(2026, 11, 2)
# Con 30 días de crédito: vencida hace 13 días, vencida hace 2, vence el miércoles y vence en 17 días.
EMISION_VENCIDA, EMISION_RECIENTE, EMISION_SEMANA, EMISION_FUTURA = (
    "2026-09-20",
    "2026-10-01",
    "2026-10-05",
    "2026-10-20",
)


def _factura(
    sesion: Session,
    total: str,
    emision: str,
    *,
    proveedor: Proveedor | None = None,
    tipo: str = "I",
    moneda: str = "MXN",
    tipo_cambio: Decimal | None = None,
) -> Factura:
    return crear_factura(
        sesion,
        proveedor=proveedor,
        tipo=tipo,
        total=Decimal(total),
        moneda=moneda,
        tipo_cambio=tipo_cambio,
        fecha_emision=datetime.fromisoformat(f"{emision}T10:00:00"),
    )


def _conteo(sesion: Session, modelo: type[Aplicacion] | type[Propuesta] | type[RenglonPropuesta]) -> int:
    return sesion.scalar(select(func.count()).select_from(modelo)) or 0


def _acciones(sesion: Session) -> list[str]:
    return list(sesion.scalars(select(Bitacora.accion).order_by(Bitacora.id)))


def _propuesta_pendiente(sesion: Session, capturista: Usuario, *totales: str) -> tuple[Propuesta, list[Factura]]:
    facturas = [_factura(sesion, total, EMISION_VENCIDA) for total in totales]
    propuesta = servicio.crear_propuesta(
        sesion,
        usuario=capturista,
        presupuesto_mxn=Decimal("1000000.00"),
        origen="api",
        hoy=HOY,
        factura_ids=[f.id for f in facturas],
    )
    sesion.commit()
    return propuesta, facturas


def test_crear_propuesta_la_deja_pendiente_con_razones_y_no_cambia_ningun_saldo(
    cliente: TestClient, sesion: Session, entrar_como: Entrar
) -> None:
    capturista = crear_usuario(sesion, rol="capturista")
    proveedor = crear_proveedor(sesion, nombre="Aceros Ficticios del Bajío SA de CV")
    vieja = _factura(sesion, "600.00", EMISION_VENCIDA, proveedor=proveedor)
    grande = _factura(sesion, "500.00", EMISION_RECIENTE, proveedor=proveedor)
    semana = _factura(sesion, "400.00", EMISION_SEMANA, proveedor=proveedor)
    futura = _factura(sesion, "50.00", EMISION_FUTURA, proveedor=proveedor)
    entrar_como(capturista.id)

    r = cliente.post("/api/propuestas", json={"presupuesto_mxn": "1000.00", "horizonte": "esta_semana"})
    assert r.status_code == 200, r.text
    propuesta = r.json()
    assert propuesta["estado"] == "pendiente" and propuesta["origen"] == "api"
    assert propuesta["presupuesto_mxn"] == "1000.00" and propuesta["total_mxn"] == "1000.00"
    assert propuesta["fecha_limite"] == "2026-11-08", "esta semana termina el domingo"
    assert propuesta["creada_por"] == {"id": capturista.id, "nombre": capturista.nombre, "rol": "capturista"}
    assert propuesta["decidida_por"] is None and propuesta["puede_decidir"] is False
    # La más antigua primero; la de 500 no cabe tras la de 600 y se sigue con la de 400. La futura no entra.
    renglones = propuesta["renglones"]
    assert [x["factura"]["id"] for x in renglones] == [vieja.id, semana.id]
    assert [x["razon"] for x in renglones] == ["Vencida hace 13 días", "Vence el 4 de noviembre"]
    assert [x["importe"] for x in renglones] == ["600.00", "400.00"]
    assert renglones[0]["factura"]["saldo_actual"] == "600.00"
    assert renglones[0]["factura"]["vencimiento"] == "2026-10-20"
    assert renglones[0]["factura"]["proveedor"]["nombre"] == proveedor.nombre
    (excluida,) = propuesta["excluidas"]
    assert excluida["factura_id"] == grande.id and excluida["codigo"] == "EXCEDE_PRESUPUESTO"
    assert excluida["serie"] == "A" and excluida["folio"] == grande.folio
    assert excluida["proveedor_nombre"] == proveedor.nombre and "500.00" in excluida["motivo"]

    # Nada se pagó: ninguna aplicación y todos los saldos intactos.
    assert _conteo(sesion, Aplicacion) == 0
    for factura in (vieja, grande, semana, futura):
        assert saldos.saldo(sesion, factura.id) == factura.total
    registro = sesion.scalars(select(Bitacora).where(Bitacora.accion == "PROPUESTA_CREADA")).one()
    assert registro.usuario_id == capturista.id and registro.entidad_id == str(propuesta["id"])
    assert registro.detalle["facturas"] == [vieja.id, semana.id] and registro.detalle["total_mxn"] == "1000.00"

    detalle = cliente.get(f"/api/propuestas/{propuesta['id']}").json()
    assert detalle == propuesta
    lista = cliente.get("/api/propuestas", params={"estado": "pendiente"}).json()
    assert lista["total"] == 1 and lista["elementos"][0]["renglones"] == 2
    assert lista["elementos"][0]["total_mxn"] == "1000.00"
    assert cliente.get("/api/propuestas", params={"estado": "aprobada"}).json()["total"] == 0


def test_validaciones_de_entrada_y_propuesta_vacia(cliente: TestClient, sesion: Session, entrar_como: Entrar) -> None:
    capturista = crear_usuario(sesion, rol="capturista")
    factura = _factura(sesion, "900.00", EMISION_VENCIDA)
    entrar_como(capturista.id)
    invalidas: list[dict[str, object]] = [
        {"presupuesto_mxn": "1000.00"},
        {"presupuesto_mxn": "1000.00", "horizonte": "vencidas", "fecha_limite": "2026-11-30"},
        {"presupuesto_mxn": 1000.0, "horizonte": "vencidas"},
        {"presupuesto_mxn": "1000.00", "horizonte": "el mes que viene"},
        {"presupuesto_mxn": "mucho", "horizonte": "vencidas"},
    ]
    for cuerpo in invalidas:
        r = cliente.post("/api/propuestas", json=cuerpo)
        assert r.status_code == 422 and r.json()["error"]["codigo"] == "VALIDACION", cuerpo
    for presupuesto in ("0", "-5.00", "10.001"):
        r = cliente.post("/api/propuestas", json={"presupuesto_mxn": presupuesto, "horizonte": "vencidas"})
        assert r.status_code == 422 and r.json()["error"]["codigo"] == "PRESUPUESTO_INVALIDO", presupuesto

    r = cliente.post("/api/propuestas", json={"presupuesto_mxn": "100.00", "horizonte": "vencidas"})
    assert r.status_code == 422
    error = r.json()["error"]
    assert error["codigo"] == "PROPUESTA_VACIA"
    assert isinstance(error["detalle"], dict), "todo detalle de error es un objeto"
    assert [(e["factura_id"], e["codigo"]) for e in error["detalle"]["excluidas"]] == [
        (factura.id, "EXCEDE_PRESUPUESTO")
    ]
    assert _conteo(sesion, Propuesta) == 0 and _conteo(sesion, RenglonPropuesta) == 0

    # Con fecha límite explícita y con facturas elegidas a mano.
    r = cliente.post("/api/propuestas", json={"presupuesto_mxn": "900.00", "fecha_limite": "2026-10-19"})
    assert r.status_code == 422 and r.json()["error"]["detalle"]["excluidas"] == []
    r = cliente.post(
        "/api/propuestas",
        json={"presupuesto_mxn": "900.00", "fecha_limite": "2026-10-20", "factura_ids": [factura.id, factura.id]},
    )
    assert r.status_code == 200 and len(r.json()["renglones"]) == 1


def test_solo_un_aprobador_distinto_del_creador_puede_aprobar(
    cliente: TestClient, sesion: Session, entrar_como: Entrar
) -> None:
    capturista = crear_usuario(sesion, rol="capturista")
    otro_capturista = crear_usuario(sesion, rol="capturista")
    aprobador = crear_usuario(sesion, rol="aprobador")
    propuesta, (factura,) = _propuesta_pendiente(sesion, capturista, "1160.00")
    ruta = f"/api/propuestas/{propuesta.id}/aprobar"

    assert cliente.post(ruta, json={}).status_code == 401
    for usuario in (capturista, otro_capturista):
        entrar_como(usuario.id)
        r = cliente.post(ruta, json={})
        assert r.status_code == 403 and r.json()["error"]["codigo"] == "ROL_INSUFICIENTE"
        assert (
            cliente.post(f"/api/propuestas/{propuesta.id}/rechazar", json={"motivo": "No procede"}).status_code == 403
        )
    # Un aprobador tampoco crea propuestas: pedir y aprobar son papeles separados.
    entrar_como(aprobador.id)
    r = cliente.post("/api/propuestas", json={"presupuesto_mxn": "5000.00", "horizonte": "vencidas"})
    assert r.status_code == 403 and r.json()["error"]["codigo"] == "ROL_INSUFICIENTE"

    # Quien la pidió no la aprueba aunque después le den el rol de aprobador.
    sesion.execute(update(Usuario).where(Usuario.id == capturista.id).values(rol="aprobador"))
    sesion.commit()
    entrar_como(capturista.id)
    assert cliente.get(f"/api/propuestas/{propuesta.id}").json()["puede_decidir"] is False
    for accion, cuerpo in (("aprobar", {}), ("rechazar", {"motivo": "Me la rechazo yo mismo"})):
        r = cliente.post(f"/api/propuestas/{propuesta.id}/{accion}", json=cuerpo)
        assert r.status_code == 403 and r.json()["error"]["codigo"] == "MISMO_USUARIO"
    # Y aunque el código fallara, la base tampoco lo permite.
    with pytest.raises(DBAPIError), sesion.begin_nested():
        sesion.execute(
            update(Propuesta)
            .where(Propuesta.id == propuesta.id)
            .values(estado="aprobada", decidida_por=capturista.id, decidida_en=func.now())
        )

    assert _conteo(sesion, Aplicacion) == 0
    assert saldos.saldo(sesion, factura.id) == Decimal("1160.00")
    assert sesion.scalar(select(Propuesta.estado).where(Propuesta.id == propuesta.id)) == "pendiente"
    entrar_como(aprobador.id)
    assert cliente.get(f"/api/propuestas/{propuesta.id}").json()["puede_decidir"] is True
    assert (
        cliente.post("/api/propuestas/999999/aprobar", json={}).json()["error"]["codigo"] == "PROPUESTA_NO_ENCONTRADA"
    )


def test_aprobar_registra_los_pagos_y_actualiza_saldos_una_sola_vez(
    cliente: TestClient, sesion: Session, entrar_como: Entrar
) -> None:
    capturista = crear_usuario(sesion, rol="capturista")
    aprobador = crear_usuario(sesion, rol="aprobador")
    propuesta, (f1, f2) = _propuesta_pendiente(sesion, capturista, "1160.00", "580.50")
    entrar_como(aprobador.id)

    r = cliente.post(f"/api/propuestas/{propuesta.id}/aprobar", json={})
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["estado"] == "aprobada" and cuerpo["puede_decidir"] is False
    assert cuerpo["decidida_por"]["id"] == aprobador.id and cuerpo["decidida_en"] is not None
    assert [x["factura"]["saldo_actual"] for x in cuerpo["renglones"]] == ["0.00", "0.00"]

    pagos = list(sesion.scalars(select(Aplicacion).order_by(Aplicacion.id)))
    assert [(p.factura_id, p.origen, p.importe, p.fecha, p.registrado_por) for p in pagos] == [
        (f1.id, "pago_aprobado", Decimal("1160.00"), HOY, aprobador.id),
        (f2.id, "pago_aprobado", Decimal("580.50"), HOY, aprobador.id),
    ]
    renglon_ids = set(sesion.scalars(select(RenglonPropuesta.id).where(RenglonPropuesta.propuesta_id == propuesta.id)))
    assert {p.renglon_propuesta_id for p in pagos} == renglon_ids
    assert saldos.saldo(sesion, f1.id) == 0 and saldos.saldo(sesion, f2.id) == 0
    assert _acciones(sesion) == ["PROPUESTA_CREADA", "PAGO_REGISTRADO", "PAGO_REGISTRADO", "PROPUESTA_APROBADA"]
    pago = sesion.scalars(select(Bitacora).where(Bitacora.accion == "PAGO_REGISTRADO").order_by(Bitacora.id)).first()
    assert pago is not None and pago.usuario_id == aprobador.id and pago.entidad_id == str(f1.id)
    assert pago.detalle["saldo_antes"] == "1160.00" and pago.detalle["saldo_despues"] == "0.00"

    # Aprobar o rechazar de nuevo no repite pagos.
    for accion, datos in (("aprobar", {}), ("rechazar", {"motivo": "Cambio de opinión"})):
        r = cliente.post(f"/api/propuestas/{propuesta.id}/{accion}", json=datos)
        assert r.status_code == 409 and r.json()["error"]["codigo"] == "PROPUESTA_NO_PENDIENTE"
    assert _conteo(sesion, Aplicacion) == 2
    # Una propuesta aprobada no se edita: la base rechaza cualquier cambio.
    with pytest.raises(DBAPIError), sesion.begin_nested():
        sesion.execute(update(Propuesta).where(Propuesta.id == propuesta.id).values(total_mxn=Decimal("1.00")))
    with pytest.raises(DBAPIError), sesion.begin_nested():
        sesion.execute(update(RenglonPropuesta).where(RenglonPropuesta.propuesta_id == propuesta.id).values(razon="x"))


def test_si_un_pago_falla_a_la_mitad_no_queda_nada_aplicado(sesion: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    capturista = crear_usuario(sesion, rol="capturista")
    aprobador = crear_usuario(sesion, rol="aprobador")
    propuesta, facturas = _propuesta_pendiente(sesion, capturista, "100.00", "200.00", "300.00")
    aplicar_real = saldos.aplicar
    llamadas = 0

    def aplicar_que_falla_en_el_segundo(
        sesion: Session,
        *,
        factura_id: int,
        importe: Decimal,
        origen: str,
        fecha: date,
        renglon_propuesta_id: int | None = None,
        usuario_id: int | None = None,
    ) -> Aplicacion:
        nonlocal llamadas
        llamadas += 1
        if llamadas == 2:
            raise saldos.ErrorAplicacion("Falla provocada a la mitad de la aprobación.")
        return aplicar_real(
            sesion,
            factura_id=factura_id,
            importe=importe,
            origen=origen,
            fecha=fecha,
            renglon_propuesta_id=renglon_propuesta_id,
            usuario_id=usuario_id,
        )

    monkeypatch.setattr(saldos, "aplicar", aplicar_que_falla_en_el_segundo)
    with pytest.raises(servicio.ErrorPropuesta) as info:
        servicio.aprobar(sesion, propuesta_id=propuesta.id, usuario=aprobador, hoy=HOY)
    assert info.value.codigo == "RENGLONES_INVALIDOS" and info.value.estado == 409
    sesion.commit()

    assert llamadas == 2, "el primer pago sí llegó a aplicarse antes de la falla"
    assert _conteo(sesion, Aplicacion) == 0
    assert [saldos.saldo(sesion, f.id) for f in facturas] == [Decimal("100.00"), Decimal("200.00"), Decimal("300.00")]
    sesion.refresh(propuesta)
    assert propuesta.estado == "pendiente" and propuesta.decidida_por is None
    assert _acciones(sesion) == ["PROPUESTA_CREADA"]
    # Corregida la falla, la misma propuesta se aprueba completa.
    monkeypatch.setattr(saldos, "aplicar", aplicar_real)
    servicio.aprobar(sesion, propuesta_id=propuesta.id, usuario=aprobador, hoy=HOY)
    assert _conteo(sesion, Aplicacion) == 3


def test_un_error_inesperado_al_aprobar_por_http_tampoco_deja_pagos(
    cliente: TestClient, sesion: Session, entrar_como: Entrar, monkeypatch: pytest.MonkeyPatch
) -> None:
    capturista = crear_usuario(sesion, rol="capturista")
    aprobador = crear_usuario(sesion, rol="aprobador")
    propuesta, facturas = _propuesta_pendiente(sesion, capturista, "100.00", "200.00")
    registrar_real = bitacora.registrar

    def bitacora_que_truena(
        sesion: Session,
        *,
        usuario_id: int | None,
        accion: str,
        entidad: str,
        entidad_id: str | int | None,
        detalle: Mapping[str, object],
    ) -> None:
        if accion == "PROPUESTA_APROBADA":
            raise RuntimeError("Falla inesperada después de aplicar todos los pagos.")
        registrar_real(
            sesion, usuario_id=usuario_id, accion=accion, entidad=entidad, entidad_id=entidad_id, detalle=detalle
        )

    monkeypatch.setattr(bitacora, "registrar", bitacora_que_truena)
    entrar_como(aprobador.id)
    r = cliente.post(f"/api/propuestas/{propuesta.id}/aprobar", json={})
    assert r.status_code == 500 and r.json()["error"]["codigo"] == "ERROR_INTERNO"
    assert _conteo(sesion, Aplicacion) == 0
    assert [saldos.saldo(sesion, f.id) for f in facturas] == [Decimal("100.00"), Decimal("200.00")]
    assert sesion.scalar(select(Propuesta.estado).where(Propuesta.id == propuesta.id)) == "pendiente"


def test_rechazar_pide_motivo_no_toca_saldos_y_libera_las_facturas(
    cliente: TestClient, sesion: Session, entrar_como: Entrar
) -> None:
    capturista = crear_usuario(sesion, rol="capturista")
    aprobador = crear_usuario(sesion, rol="aprobador")
    propuesta, (factura,) = _propuesta_pendiente(sesion, capturista, "750.00")
    entrar_como(aprobador.id)
    ruta = f"/api/propuestas/{propuesta.id}/rechazar"
    for corto in ({}, {"motivo": "no"}, {"motivo": "x" * 501}):
        assert cliente.post(ruta, json=corto).status_code == 422

    r = cliente.post(ruta, json={"motivo": "Falta la orden de compra del proveedor."})
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["estado"] == "rechazada" and cuerpo["motivo_rechazo"] == "Falta la orden de compra del proveedor."
    assert cuerpo["decidida_por"]["id"] == aprobador.id
    assert _conteo(sesion, Aplicacion) == 0 and saldos.saldo(sesion, factura.id) == Decimal("750.00")
    assert _acciones(sesion) == ["PROPUESTA_CREADA", "PROPUESTA_RECHAZADA"]
    assert cliente.post(f"/api/propuestas/{propuesta.id}/aprobar", json={}).json()["error"]["codigo"] == (
        "PROPUESTA_NO_PENDIENTE"
    )

    # La factura vuelve a estar disponible para una propuesta nueva.
    entrar_como(capturista.id)
    r = cliente.post("/api/propuestas", json={"presupuesto_mxn": "750.00", "horizonte": "vencidas"})
    assert r.status_code == 200 and [x["factura"]["id"] for x in r.json()["renglones"]] == [factura.id]


def test_un_motivo_de_rechazo_en_blanco_no_cuenta_como_motivo(
    cliente: TestClient, sesion: Session, entrar_como: Entrar
) -> None:
    capturista = crear_usuario(sesion, rol="capturista")
    aprobador = crear_usuario(sesion, rol="aprobador")
    propuesta, _ = _propuesta_pendiente(sesion, capturista, "750.00")
    entrar_como(aprobador.id)
    for motivo in ("     ", "  no  ", "\n\n\t   \n"):
        r = cliente.post(f"/api/propuestas/{propuesta.id}/rechazar", json={"motivo": motivo})
        assert r.status_code == 422, motivo
    assert sesion.scalar(select(Propuesta.estado).where(Propuesta.id == propuesta.id)) == "pendiente"
    r = cliente.post(f"/api/propuestas/{propuesta.id}/rechazar", json={"motivo": "   Falta la orden de compra.  "})
    assert r.status_code == 200 and r.json()["motivo_rechazo"] == "Falta la orden de compra."
