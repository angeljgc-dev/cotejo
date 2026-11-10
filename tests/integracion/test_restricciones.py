"""Restricciones y triggers que protegen invariantes en la base (no solo en código)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from cotejo.bitacora import registrar
from cotejo.modelos import Alerta, Aplicacion, Bitacora, Propuesta, RenglonPropuesta
from tests.apoyo.fabricas import crear_carga_archivo, crear_factura, crear_proveedor, crear_usuario


def _propuesta(sesion: Session, creada_por: int, factura_id: int) -> Propuesta:
    propuesta = Propuesta(
        presupuesto_mxn=Decimal("5000.00"),
        total_mxn=Decimal("1160.00"),
        fecha_limite=date(2026, 11, 9),
        origen="api",
        creada_por=creada_por,
    )
    sesion.add(propuesta)
    sesion.flush()
    sesion.add(
        RenglonPropuesta(
            propuesta_id=propuesta.id,
            factura_id=factura_id,
            importe=Decimal("1160.00"),
            importe_mxn=Decimal("1160.00"),
            razon="Vence el 9 de noviembre",
        )
    )
    sesion.flush()
    return propuesta


def test_bitacora_no_se_modifica_ni_se_borra(sesion: Session) -> None:
    registrar(sesion, usuario_id=None, accion="DEMO_REINICIADA", entidad="demo", entidad_id=None, detalle={})
    sesion.flush()
    with pytest.raises(DBAPIError, match="solo admite agregar"), sesion.begin_nested():
        sesion.execute(text("UPDATE bitacora SET entidad = 'otra'"))
    with pytest.raises(DBAPIError, match="solo admite agregar"), sesion.begin_nested():
        sesion.execute(text("DELETE FROM bitacora"))
    assert sesion.query(Bitacora).count() == 1


def test_propuesta_decidida_es_inmutable(sesion: Session) -> None:
    capturista = crear_usuario(sesion, rol="capturista")
    aprobador = crear_usuario(sesion, rol="aprobador")
    factura = crear_factura(sesion)
    propuesta = _propuesta(sesion, capturista.id, factura.id)
    propuesta.estado = "aprobada"
    propuesta.decidida_por = aprobador.id
    propuesta.decidida_en = datetime.fromisoformat("2026-11-02T12:00:00-06:00")
    sesion.flush()
    with pytest.raises(DBAPIError, match="ya fue decidida"), sesion.begin_nested():
        sesion.execute(text("UPDATE propuestas SET total_mxn = 1 WHERE id = :i"), {"i": propuesta.id})
    with pytest.raises(DBAPIError, match="no se modifican"), sesion.begin_nested():
        sesion.execute(text("UPDATE renglones_propuesta SET importe = 1 WHERE propuesta_id = :i"), {"i": propuesta.id})
    with pytest.raises(DBAPIError, match="no se modifican"), sesion.begin_nested():
        sesion.execute(text("DELETE FROM renglones_propuesta WHERE propuesta_id = :i"), {"i": propuesta.id})


def test_quien_crea_no_aprueba_en_la_base(sesion: Session) -> None:
    capturista = crear_usuario(sesion, rol="capturista")
    propuesta = _propuesta(sesion, capturista.id, crear_factura(sesion).id)
    with pytest.raises(IntegrityError, match="decide_otra_persona"), sesion.begin_nested():
        sesion.execute(
            text("UPDATE propuestas SET estado='aprobada', decidida_por=creada_por, decidida_en=now() WHERE id=:i"),
            {"i": propuesta.id},
        )


def test_total_de_propuesta_no_excede_presupuesto(sesion: Session) -> None:
    capturista = crear_usuario(sesion)
    sesion.add(
        Propuesta(
            presupuesto_mxn=Decimal("100.00"),
            total_mxn=Decimal("100.01"),
            fecha_limite=date(2026, 11, 9),
            origen="api",
            creada_por=capturista.id,
        )
    )
    with pytest.raises(IntegrityError, match="total_en_presupuesto"):
        sesion.flush()


def test_aplicacion_sin_documento_de_origen_es_incoherente(sesion: Session) -> None:
    factura = crear_factura(sesion)
    sesion.add(
        Aplicacion(
            factura_id=factura.id,
            origen="nota_credito",
            importe_solicitado=Decimal("10"),
            importe=Decimal("10"),
            fecha=date(2026, 11, 2),
        )
    )
    with pytest.raises(IntegrityError, match="coherencia_documento"):
        sesion.flush()


def test_aplicacion_no_excede_lo_solicitado(sesion: Session) -> None:
    factura = crear_factura(sesion)
    nota = crear_factura(sesion, tipo="E")
    sesion.add(
        Aplicacion(
            factura_id=factura.id,
            origen="nota_credito",
            origen_factura_id=nota.id,
            importe_solicitado=Decimal("10"),
            importe=Decimal("10.01"),
            fecha=date(2026, 11, 2),
        )
    )
    with pytest.raises(IntegrityError, match="importe_valido"):
        sesion.flush()


def test_reaplicar_el_mismo_documento_choca_con_la_llave_unica(sesion: Session) -> None:
    factura = crear_factura(sesion)
    nota = crear_factura(sesion, tipo="E", total=Decimal("100"))

    def aplicar() -> None:
        sesion.add(
            Aplicacion(
                factura_id=factura.id,
                origen="nota_credito",
                origen_factura_id=nota.id,
                importe_solicitado=Decimal("100"),
                importe=Decimal("100"),
                fecha=date(2026, 11, 2),
            )
        )
        sesion.flush()

    aplicar()
    with pytest.raises(IntegrityError, match="uq_aplicaciones_documento"):
        aplicar()


def test_uuid_de_factura_es_unico(sesion: Session) -> None:
    proveedor = crear_proveedor(sesion)
    archivo = crear_carga_archivo(sesion)
    crear_factura(sesion, proveedor=proveedor, uuid_cfdi="7C1E0000-0000-4000-8000-000000000001")
    with pytest.raises(IntegrityError, match="uq_facturas_uuid"):
        crear_factura(
            sesion, proveedor=proveedor, carga_archivo=archivo, uuid_cfdi="7C1E0000-0000-4000-8000-000000000001"
        )


def test_alertas_de_proveedor_son_idempotentes_por_proveedor(sesion: Session) -> None:
    uno, dos = crear_proveedor(sesion), crear_proveedor(sesion)

    def alerta(proveedor_id: int) -> Alerta:
        return Alerta(
            proveedor_id=proveedor_id, codigo="LISTA_69B", severidad="bloqueante", mensaje="En la lista 69-B."
        )

    sesion.add_all([alerta(uno.id), alerta(dos.id)])
    sesion.flush()
    sesion.add(alerta(uno.id))
    with pytest.raises(IntegrityError, match="uq_alertas_idempotencia"):
        sesion.flush()
