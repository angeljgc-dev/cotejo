"""G5: misma semilla, mismos datos (contenido de las tablas). Y la propuesta pendiente que la demo necesita."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from cotejo.cxp import saldos
from cotejo.dinero import cuantizar
from cotejo.modelos import Factura, Propuesta, RenglonPropuesta, Usuario
from cotejo.semilla import generador
from cotejo.semilla.cfdi_ficticio import construir_xml
from tests.apoyo import xsd_sat
from tests.apoyo.cfdi import TABLAS_DE_NEGOCIO, huella_tablas
from tests.apoyo.fabricas import EMPRESA_RFC

FECHA = date(2026, 11, 2)
# Las marcas de tiempo de registro dependen del reloj, no de la semilla.
MARCAS_DE_TIEMPO = frozenset({"creado_en", "actualizado_en", "resuelta_en", "decidida_en", "ocurrido_en"})
TABLAS = (*TABLAS_DE_NEGOCIO, "documentos", "fragmentos", "cargas", "carga_archivos", "bitacora")


def _sembrar(sesion: Session, semilla: int) -> dict[str, str]:
    generador.reiniciar_demo(sesion, semilla=semilla, fecha_base=FECHA)
    sesion.flush()
    return huella_tablas(sesion, TABLAS, sin_columnas=MARCAS_DE_TIEMPO)


def test_g5_misma_semilla_mismo_contenido_de_tablas(sesion: Session) -> None:
    primera = _sembrar(sesion, 20261102)
    segunda = _sembrar(sesion, 20261102)
    assert primera == segunda
    otra = _sembrar(sesion, 7)
    assert otra["facturas"] != primera["facturas"]


def test_g5_cada_xml_de_la_semilla_cumple_los_xsd_del_sat() -> None:
    lote = generador.generar_lote(20261102, FECHA, empresa_rfc=EMPRESA_RFC, empresa_nombre="Empresa Ficticia")
    invalidos = {c.uuid: xsd_sat.errores(construir_xml(c)) for c in lote.comprobantes}
    assert {u: e for u, e in invalidos.items() if e} == {}
    assert len(lote.comprobantes) == 130


def test_propuesta_pendiente_de_la_semilla_respeta_las_invariantes(sesion: Session) -> None:
    resumen = generador.reiniciar_demo(sesion, semilla=20261102, fecha_base=FECHA)
    assert (resumen.facturas, resumen.notas_credito, resumen.complementos_pago) == (120, 3, 7)
    capturista = sesion.scalars(select(Usuario).where(Usuario.usuario == "demo.capturista")).one()
    propuestas = sesion.scalars(select(Propuesta).where(Propuesta.estado == "pendiente")).all()
    assert propuestas, "la demo necesita al menos una propuesta pendiente"
    for propuesta in propuestas:
        assert propuesta.creada_por == capturista.id
        renglones = sesion.scalars(select(RenglonPropuesta).where(RenglonPropuesta.propuesta_id == propuesta.id)).all()
        assert renglones
        total = Decimal(0)
        for renglon in renglones:
            factura = sesion.get(Factura, renglon.factura_id)
            assert factura is not None and factura.tipo == "I"
            assert renglon.importe == cuantizar(saldos.saldo(sesion, factura.id)) > 0
            assert saldos.bloqueos(sesion, factura.id) == []
            total += renglon.importe_mxn
        assert total == propuesta.total_mxn <= propuesta.presupuesto_mxn


def test_reinicio_conserva_usuarios_y_deja_la_demo_completa(sesion: Session) -> None:
    generador.reiniciar_demo(sesion, semilla=20261102, fecha_base=FECHA)
    usuarios = sesion.scalars(select(Usuario.id).order_by(Usuario.id)).all()
    resumen = generador.reiniciar_demo(sesion, semilla=20261102, fecha_base=FECHA)
    assert sesion.scalars(select(Usuario.id).order_by(Usuario.id)).all() == usuarios
    assert resumen.proveedores == 12 and resumen.propuestas_pendientes >= 1 and resumen.alertas_abiertas > 0
