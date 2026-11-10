"""Tablero de cuentas por pagar (B4): unas cuantas sumas sobre la misma vista de facturas."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from cotejo.cxp import consultas
from cotejo.cxp.consultas import (
    OtrosProveedores,
    ProveedorCorto,
    SaldoProveedor,
    SaldoYConteo,
    Tablero,
    con_adeudo_en_pesos,
    con_saldo,
    vista_facturas,
)
from cotejo.modelos import Propuesta

PROVEEDORES_EN_TABLERO = 10


def calcular(sesion: Session, hoy: date) -> Tablero:
    v = vista_facturas(hoy)
    en_pesos = con_adeudo_en_pesos(v)
    en_7_dias = and_(en_pesos, v.c.vencimiento >= hoy, v.c.vencimiento <= hoy + timedelta(days=7))
    en_30_dias = and_(en_pesos, v.c.vencimiento >= hoy, v.c.vencimiento <= hoy + timedelta(days=30))
    totales = sesion.execute(
        select(
            func.coalesce(func.sum(v.c.saldo_mxn).filter(en_7_dias), 0).label("saldo_7"),
            func.count().filter(en_7_dias).label("facturas_7"),
            func.coalesce(func.sum(v.c.saldo_mxn).filter(en_30_dias), 0).label("saldo_30"),
            func.count().filter(en_30_dias).label("facturas_30"),
            func.count().filter(v.c.alertas_abiertas > 0).label("con_alertas"),
            func.count().filter(and_(con_saldo(v), v.c.tiene_bloqueante)).label("bloqueadas"),
        )
        .select_from(v)
        .where(v.c.tipo == "I")
    ).one()

    por_proveedor = sesion.execute(
        select(
            v.c.proveedor_id,
            v.c.proveedor_rfc,
            v.c.proveedor_nombre,
            func.sum(v.c.saldo_mxn).label("saldo_mxn"),
            func.count().label("facturas"),
        )
        .where(en_pesos)
        .group_by(v.c.proveedor_id, v.c.proveedor_rfc, v.c.proveedor_nombre)
        .order_by(func.sum(v.c.saldo_mxn).desc(), v.c.proveedor_id)
    ).all()
    mayores, resto = por_proveedor[:PROVEEDORES_EN_TABLERO], por_proveedor[PROVEEDORES_EN_TABLERO:]

    antiguedad = consultas.antiguedad(sesion, hoy)
    pendientes = sesion.execute(
        select(func.count()).select_from(Propuesta).where(Propuesta.estado == "pendiente")
    ).scalar_one()
    return Tablero(
        fecha_corte=hoy,
        adeudo_total_mxn=antiguedad.adeudo_total_mxn,
        adeudo_por_moneda=consultas.adeudo_por_moneda(sesion, hoy),
        por_proveedor=[
            SaldoProveedor(
                proveedor=ProveedorCorto(id=f.proveedor_id, rfc=f.proveedor_rfc, nombre=f.proveedor_nombre),
                saldo_mxn=f.saldo_mxn,
                facturas=f.facturas,
            )
            for f in mayores
        ],
        otros_proveedores=OtrosProveedores(
            saldo_mxn=sum((f.saldo_mxn for f in resto), Decimal(0)), proveedores=len(resto)
        ),
        antiguedad=antiguedad.grupos,
        vencen_7_dias=SaldoYConteo(saldo_mxn=totales.saldo_7, facturas=totales.facturas_7),
        vencen_30_dias=SaldoYConteo(saldo_mxn=totales.saldo_30, facturas=totales.facturas_30),
        facturas_con_alertas=totales.con_alertas,
        facturas_bloqueadas=totales.bloqueadas,
        propuestas_pendientes=pendientes,
    )
