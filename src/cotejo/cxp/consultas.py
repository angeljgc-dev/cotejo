"""Consultas de cuentas por pagar. Las usan las rutas, las herramientas del asistente y el servidor MCP.

Todas son de solo lectura y devuelven modelos Pydantic. Las sumas las hace la base con `numeric`; aquí no se
suma dinero en Python salvo para armar renglones ya calculados.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import ColumnElement, Date, Row, Select, Subquery, and_, case, cast, false, func, literal, or_, select
from sqlalchemy.orm import Session

from cotejo.cxp.antiguedad import columna_grupo
from cotejo.dinero import MONEDA_LOCAL, MONEDA_SIN_VALOR, Importe
from cotejo.modelos import Alerta, Aplicacion, Factura, Lista69b, Propuesta, Proveedor, RenglonPropuesta

TipoComprobante = Literal["I", "E", "P"]
EstadoFiltro = Literal["pendiente", "vencida", "por_vencer", "pagada", "todas"]
EstadoPago = Literal["pendiente", "parcial", "pagada", "no_aplica"]
Severidad = Literal["alerta", "bloqueante"]
OrdenFacturas = Literal["vencimiento", "fecha", "saldo", "total"]
GrupoAntiguedadClave = Literal["por_vencer", "1_30", "31_60", "61_90", "mas_90"]
Medida = Literal["facturado", "pagado", "saldo"]
Situacion69b = Literal["Presunto", "Definitivo"]

GRUPOS_ANTIGUEDAD: tuple[tuple[GrupoAntiguedadClave, str], ...] = (
    ("por_vencer", "Por vencer"),
    ("1_30", "1 a 30 días"),
    ("31_60", "31 a 60 días"),
    ("61_90", "61 a 90 días"),
    ("mas_90", "Más de 90 días"),
)
MAX_FACTURAS_ADEUDO = 50
MAX_MESES = 24


class ProveedorNoEncontrado(LookupError):
    def __init__(self, proveedor_id: int) -> None:
        super().__init__(f"No existe el proveedor {proveedor_id}.")
        self.proveedor_id = proveedor_id


class _Modelo(BaseModel):
    model_config = ConfigDict(frozen=True)


class ProveedorCorto(_Modelo):
    id: int
    rfc: str
    nombre: str


class SaldoMoneda(_Modelo):
    moneda: str
    saldo: Importe
    # None cuando la moneda es extranjera y alguna factura no trae tipo de cambio.
    saldo_mxn: Importe | None


class ProveedorConAdeudo(_Modelo):
    id: int
    rfc: str
    nombre: str
    dias_credito: int
    rfc_valido: bool
    situacion_69b: Situacion69b | None
    adeudo_mxn: Importe
    facturas_con_saldo: int


class FacturaResumen(_Modelo):
    """Forma de `FacturaResumen` del contrato. En tipos E y P el saldo y el vencimiento son None."""

    id: int
    uuid: str
    tipo: TipoComprobante
    serie: str | None
    folio: str | None
    fecha_emision: datetime
    proveedor: ProveedorCorto
    moneda: str
    tipo_cambio: Decimal | None
    total: Importe
    # None si la moneda es extranjera y la factura no trae tipo de cambio.
    total_mxn: Importe | None
    saldo: Importe | None
    saldo_mxn: Importe | None
    vencimiento: date | None
    # Negativo: faltan días para vencer.
    dias_vencido: int | None
    estado_pago: EstadoPago
    resultado: Literal["aceptada", "aceptada_con_alertas"]
    alertas_abiertas: int
    tiene_bloqueante: bool
    en_propuesta_pendiente: int | None


class FiltrosFacturas(BaseModel):
    proveedor_id: int | None = Field(default=None, ge=1, le=2**63 - 1)
    tipo: TipoComprobante = "I"
    estado: EstadoFiltro = "todas"
    con_alertas: bool | None = None
    severidad: Severidad | None = None
    moneda: str | None = None
    desde: date | None = None
    hasta: date | None = None
    vence_desde: date | None = None
    vence_hasta: date | None = None
    texto: str | None = Field(default=None, max_length=120)
    orden: OrdenFacturas = "vencimiento"
    pagina: int = Field(default=1, ge=1, le=1_000_000)
    por_pagina: int = Field(default=25, ge=1, le=100)


class PaginaFacturas(_Modelo):
    elementos: list[FacturaResumen]
    total: int
    pagina: int
    por_pagina: int
    # Suma del saldo en pesos de TODAS las facturas que cumplen el filtro, no solo las de esta página.
    saldo_total_mxn: Importe


class AdeudoProveedor(_Modelo):
    proveedor: ProveedorCorto
    adeudo_mxn: Importe
    adeudo_por_moneda: list[SaldoMoneda]
    # Facturas con saldo, por vencimiento; como máximo MAX_FACTURAS_ADEUDO.
    facturas: list[FacturaResumen]
    facturas_omitidas: int


class ResumenFacturas(_Modelo):
    desde: date | None
    hasta: date
    facturas: list[FacturaResumen]
    saldo_total_mxn: Importe
    # Total de facturas del rango, aunque `facturas` venga recortada por `limite`.
    conteo: int


class TotalMes(_Modelo):
    mes: str
    total_mxn: Importe
    conteo: int


class GrupoAntiguedad(_Modelo):
    grupo: GrupoAntiguedadClave
    etiqueta: str
    saldo_mxn: Importe
    facturas: int


class Antiguedad(_Modelo):
    fecha_corte: date
    grupos: list[GrupoAntiguedad]
    adeudo_total_mxn: Importe


class SaldoProveedor(_Modelo):
    proveedor: ProveedorCorto
    saldo_mxn: Importe
    facturas: int


class OtrosProveedores(_Modelo):
    saldo_mxn: Importe
    proveedores: int


class SaldoYConteo(_Modelo):
    saldo_mxn: Importe
    facturas: int


class Tablero(_Modelo):
    fecha_corte: date
    adeudo_total_mxn: Importe
    adeudo_por_moneda: list[SaldoMoneda]
    por_proveedor: list[SaldoProveedor]
    otros_proveedores: OtrosProveedores
    antiguedad: list[GrupoAntiguedad]
    vencen_7_dias: SaldoYConteo
    vencen_30_dias: SaldoYConteo
    facturas_con_alertas: int
    facturas_bloqueadas: int
    propuestas_pendientes: int


class BloqueoFactura(_Modelo):
    codigo: str
    mensaje: str


class FacturaElegible(_Modelo):
    """Datos que la selección y las barreras de una propuesta necesitan de una factura.

    Con `ids` se devuelven todas las facturas pedidas que existan, también las que no se pueden pagar (tipo E o
    P, saldo cero, bloqueadas), para que quien arma la propuesta explique por qué las excluye.
    """

    factura_id: int
    uuid: str
    tipo: TipoComprobante
    serie: str | None
    folio: str | None
    proveedor: ProveedorCorto
    fecha_emision: datetime
    vencimiento: date
    dias_vencido: int
    moneda: str
    tipo_cambio: Decimal | None
    total: Importe
    # Cero en tipos E y P.
    saldo: Importe
    # None si la moneda es extranjera y no hay tipo de cambio.
    saldo_mxn: Importe | None
    # Alertas bloqueantes abiertas (lista 69-B, posible duplicado, receptor ajeno).
    bloqueos: list[BloqueoFactura]
    en_propuesta_pendiente: int | None


class PaginaProveedores(_Modelo):
    elementos: list[ProveedorConAdeudo]
    total: int
    pagina: int
    por_pagina: int


_MONEDAS_SIN_CONVERSION = (MONEDA_LOCAL, MONEDA_SIN_VALOR)
_ORIGENES_DE_PAGO = ("complemento_pago", "pago_aprobado")
# El saldo no depende de la fecha: las consultas que no usan vencimientos pasan esta a la vista.
_SIN_FECHA = date(2000, 1, 1)
_PATRON_MES = re.compile(r"[0-9]{4}-(0[1-9]|1[0-2])", flags=re.ASCII)


def _factor_mxn() -> ColumnElement[Decimal]:
    """Uno para pesos; el tipo de cambio para otra moneda (nulo si la factura no lo trae)."""
    return case((Factura.moneda.in_(_MONEDAS_SIN_CONVERSION), literal(Decimal(1))), else_=Factura.tipo_cambio)


def vista_facturas(hoy: date) -> Subquery:
    """Una fila por factura con todo lo calculado: saldo, equivalente en pesos, vencimiento y alertas.

    Es la única definición de saldo y vencimiento para lectura; todas las consultas parten de aquí, así los
    totales del tablero, los listados y lo que ve el asistente no pueden diferir entre sí. El saldo se redondea
    a centavos y el equivalente en pesos se calcula por factura antes de sumar.
    """
    aplicado = (
        select(Aplicacion.factura_id.label("factura_id"), func.sum(Aplicacion.importe).label("aplicado"))
        .group_by(Aplicacion.factura_id)
        .subquery("aplicado")
    )
    de_factura = (
        select(
            Alerta.factura_id.label("factura_id"),
            func.count().label("abiertas"),
            func.bool_or(Alerta.severidad == "bloqueante").label("bloqueante"),
        )
        .where(Alerta.estado == "abierta", Alerta.factura_id.is_not(None))
        .group_by(Alerta.factura_id)
        .subquery("alertas_factura")
    )
    # Las alertas sin factura son del proveedor (lista 69-B) y pesan sobre todas sus facturas.
    de_proveedor = (
        select(
            Alerta.proveedor_id.label("proveedor_id"),
            func.count().label("abiertas"),
            func.bool_or(Alerta.severidad == "bloqueante").label("bloqueante"),
        )
        .where(Alerta.estado == "abierta", Alerta.factura_id.is_(None))
        .group_by(Alerta.proveedor_id)
        .subquery("alertas_proveedor")
    )
    en_propuesta = (
        select(RenglonPropuesta.factura_id.label("factura_id"), func.min(Propuesta.id).label("propuesta_id"))
        .join(Propuesta, Propuesta.id == RenglonPropuesta.propuesta_id)
        .where(Propuesta.estado == "pendiente")
        .group_by(RenglonPropuesta.factura_id)
        .subquery("en_propuesta")
    )
    es_ingreso = Factura.tipo == "I"
    monto_aplicado = func.coalesce(aplicado.c.aplicado, 0)
    saldo = func.round(Factura.total - monto_aplicado, 2)
    vencimiento = cast(Factura.fecha_emision, Date) + Proveedor.dias_credito
    return (
        select(
            Factura.id.label("id"),
            Factura.uuid.label("uuid"),
            Factura.tipo.label("tipo"),
            Factura.serie.label("serie"),
            Factura.folio.label("folio"),
            Factura.fecha_emision.label("fecha_emision"),
            Factura.emisor_rfc.label("emisor_rfc"),
            Factura.emisor_nombre.label("emisor_nombre"),
            Factura.proveedor_id.label("proveedor_id"),
            Proveedor.rfc.label("proveedor_rfc"),
            Proveedor.nombre.label("proveedor_nombre"),
            Factura.moneda.label("moneda"),
            Factura.tipo_cambio.label("tipo_cambio"),
            Factura.total.label("total"),
            func.round(Factura.total * _factor_mxn(), 2).label("total_mxn"),
            monto_aplicado.label("aplicado"),
            case((es_ingreso, saldo), else_=literal(Decimal(0))).label("saldo"),
            case((es_ingreso, func.round(saldo * _factor_mxn(), 2)), else_=literal(Decimal(0))).label("saldo_mxn"),
            vencimiento.label("vencimiento"),
            (literal(hoy, Date) - vencimiento).label("dias_vencido"),
            Factura.resultado.label("resultado"),
            (func.coalesce(de_factura.c.abiertas, 0) + func.coalesce(de_proveedor.c.abiertas, 0)).label(
                "alertas_abiertas"
            ),
            (func.coalesce(de_factura.c.bloqueante, false()) | func.coalesce(de_proveedor.c.bloqueante, false())).label(
                "tiene_bloqueante"
            ),
            en_propuesta.c.propuesta_id.label("en_propuesta_pendiente"),
        )
        .select_from(Factura)
        .join(Proveedor, Proveedor.id == Factura.proveedor_id)
        .outerjoin(aplicado, aplicado.c.factura_id == Factura.id)
        .outerjoin(de_factura, de_factura.c.factura_id == Factura.id)
        .outerjoin(de_proveedor, de_proveedor.c.proveedor_id == Factura.proveedor_id)
        .outerjoin(en_propuesta, en_propuesta.c.factura_id == Factura.id)
        .subquery("v")
    )


def con_saldo(v: Subquery) -> ColumnElement[bool]:
    """Facturas de ingreso a las que todavía se les debe algo."""
    return and_(v.c.tipo == "I", v.c.saldo > 0)


def con_adeudo_en_pesos(v: Subquery) -> ColumnElement[bool]:
    """Como `con_saldo`, sin las facturas en otra moneda que no traen tipo de cambio: no se pueden sumar en pesos."""
    return and_(con_saldo(v), v.c.saldo_mxn.is_not(None))


def _estado_pago(fila: Row[Any]) -> EstadoPago:
    if fila.tipo != "I":
        return "no_aplica"
    if fila.saldo <= 0:
        return "pagada"
    return "parcial" if fila.aplicado > 0 else "pendiente"


def _proveedor_corto(fila: Row[Any]) -> ProveedorCorto:
    return ProveedorCorto(id=fila.proveedor_id, rfc=fila.proveedor_rfc, nombre=fila.proveedor_nombre)


def _resumen(fila: Row[Any]) -> FacturaResumen:
    es_ingreso = fila.tipo == "I"
    return FacturaResumen(
        id=fila.id,
        uuid=fila.uuid,
        tipo=fila.tipo,
        serie=fila.serie,
        folio=fila.folio,
        fecha_emision=fila.fecha_emision,
        proveedor=_proveedor_corto(fila),
        moneda=fila.moneda,
        tipo_cambio=fila.tipo_cambio,
        total=fila.total,
        total_mxn=fila.total_mxn,
        saldo=fila.saldo if es_ingreso else None,
        saldo_mxn=fila.saldo_mxn if es_ingreso else None,
        vencimiento=fila.vencimiento if es_ingreso else None,
        dias_vencido=fila.dias_vencido if es_ingreso else None,
        estado_pago=_estado_pago(fila),
        resultado=fila.resultado,
        alertas_abiertas=fila.alertas_abiertas,
        tiene_bloqueante=fila.tiene_bloqueante,
        en_propuesta_pendiente=fila.en_propuesta_pendiente,
    )


def _patron_contiene(texto: str) -> str:
    """Patrón de ILIKE que busca el texto tal cual: los comodines que escriba la persona no cuentan."""
    escapado = texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escapado}%"


def _condiciones(v: Subquery, filtros: FiltrosFacturas, hoy: date) -> list[ColumnElement[bool]]:
    condiciones: list[ColumnElement[bool]] = [v.c.tipo == filtros.tipo]
    if filtros.proveedor_id is not None:
        condiciones.append(v.c.proveedor_id == filtros.proveedor_id)
    if filtros.estado == "pendiente":
        condiciones.append(con_saldo(v))
    elif filtros.estado == "vencida":
        condiciones.extend([con_saldo(v), v.c.vencimiento < hoy])
    elif filtros.estado == "por_vencer":
        condiciones.extend([con_saldo(v), v.c.vencimiento >= hoy])
    elif filtros.estado == "pagada":
        condiciones.extend([v.c.tipo == "I", v.c.saldo <= 0])
    if filtros.con_alertas is True:
        condiciones.append(v.c.alertas_abiertas > 0)
    elif filtros.con_alertas is False:
        condiciones.append(v.c.alertas_abiertas == 0)
    if filtros.severidad == "bloqueante":
        condiciones.append(v.c.tiene_bloqueante)
    elif filtros.severidad == "alerta":
        condiciones.extend([v.c.alertas_abiertas > 0, v.c.tiene_bloqueante.is_(False)])
    if filtros.moneda:
        condiciones.append(v.c.moneda == filtros.moneda.strip().upper())
    if filtros.desde is not None:
        condiciones.append(v.c.fecha_emision >= datetime.combine(filtros.desde, time.min))
    if filtros.hasta is not None:
        condiciones.append(v.c.fecha_emision < datetime.combine(filtros.hasta + timedelta(days=1), time.min))
    if filtros.vence_desde is not None:
        condiciones.append(v.c.vencimiento >= filtros.vence_desde)
    if filtros.vence_hasta is not None:
        condiciones.append(v.c.vencimiento <= filtros.vence_hasta)
    if filtros.texto and filtros.texto.strip():
        patron = _patron_contiene(filtros.texto.strip())
        serie_y_folio = func.concat(func.coalesce(v.c.serie, ""), func.coalesce(v.c.folio, ""))
        condiciones.append(
            or_(
                v.c.uuid.ilike(patron, escape="\\"),
                v.c.serie.ilike(patron, escape="\\"),
                v.c.folio.ilike(patron, escape="\\"),
                serie_y_folio.ilike(patron, escape="\\"),
                v.c.emisor_rfc.ilike(patron, escape="\\"),
                v.c.emisor_nombre.ilike(patron, escape="\\"),
                v.c.proveedor_nombre.ilike(patron, escape="\\"),
            )
        )
    return condiciones


def _orden(v: Subquery, orden: OrdenFacturas) -> list[ColumnElement[Any]]:
    if orden == "fecha":
        return [v.c.fecha_emision.desc(), v.c.id.desc()]
    if orden == "saldo":
        return [v.c.saldo_mxn.desc().nulls_last(), v.c.id]
    if orden == "total":
        return [v.c.total_mxn.desc().nulls_last(), v.c.id]
    return [v.c.vencimiento, v.c.id]


def listar_facturas(sesion: Session, filtros: FiltrosFacturas, hoy: date) -> PaginaFacturas:
    v = vista_facturas(hoy)
    condiciones = _condiciones(v, filtros, hoy)
    total, saldo_total = sesion.execute(
        select(func.count(), func.coalesce(func.sum(v.c.saldo_mxn), 0)).select_from(v).where(*condiciones)
    ).one()
    filas = sesion.execute(
        select(v)
        .where(*condiciones)
        .order_by(*_orden(v, filtros.orden))
        .limit(filtros.por_pagina)
        .offset((filtros.pagina - 1) * filtros.por_pagina)
    ).all()
    return PaginaFacturas(
        elementos=[_resumen(f) for f in filas],
        total=total,
        pagina=filtros.pagina,
        por_pagina=filtros.por_pagina,
        saldo_total_mxn=saldo_total,
    )


def resumen_factura(sesion: Session, factura_id: int, hoy: date) -> FacturaResumen | None:
    v = vista_facturas(hoy)
    fila = sesion.execute(select(v).where(v.c.id == factura_id)).one_or_none()
    return None if fila is None else _resumen(fila)


def adeudo_por_moneda(sesion: Session, hoy: date, proveedor_id: int | None = None) -> list[SaldoMoneda]:
    v = vista_facturas(hoy)
    # Las facturas sin tipo de cambio van en su propio renglón con saldo_mxn nulo. Si se mezclaran con las
    # convertibles, el renglón mostraría un saldo en la moneda que no corresponde a su equivalente en pesos.
    sin_conversion = v.c.saldo_mxn.is_(None)
    consulta = (
        select(v.c.moneda, func.sum(v.c.saldo), func.sum(v.c.saldo_mxn))
        .where(con_saldo(v))
        .group_by(v.c.moneda, sin_conversion)
        .order_by(v.c.moneda, sin_conversion)
    )
    if proveedor_id is not None:
        consulta = consulta.where(v.c.proveedor_id == proveedor_id)
    return [
        SaldoMoneda(moneda=moneda, saldo=saldo, saldo_mxn=saldo_mxn)
        for moneda, saldo, saldo_mxn in sesion.execute(consulta)
    ]


def _consulta_proveedores(hoy: date) -> tuple[Select[Any], Subquery]:
    v = vista_facturas(hoy)
    adeudo = (
        select(
            v.c.proveedor_id.label("proveedor_id"),
            func.coalesce(func.sum(v.c.saldo_mxn), 0).label("adeudo_mxn"),
            func.count().label("facturas_con_saldo"),
        )
        .where(con_saldo(v))
        .group_by(v.c.proveedor_id)
        .subquery("adeudo")
    )
    situacion = case((Lista69b.situacion.in_(("Presunto", "Definitivo")), Lista69b.situacion), else_=None)
    consulta = (
        select(
            Proveedor.id,
            Proveedor.rfc,
            Proveedor.nombre,
            Proveedor.dias_credito,
            Proveedor.rfc_formato_valido,
            Proveedor.rfc_digito_valido,
            situacion.label("situacion_69b"),
            func.coalesce(adeudo.c.adeudo_mxn, 0).label("adeudo_mxn"),
            func.coalesce(adeudo.c.facturas_con_saldo, 0).label("facturas_con_saldo"),
        )
        .select_from(Proveedor)
        .outerjoin(adeudo, adeudo.c.proveedor_id == Proveedor.id)
        .outerjoin(Lista69b, Lista69b.rfc == Proveedor.rfc)
    )
    return consulta, adeudo


def _proveedor_con_adeudo(fila: Row[Any]) -> ProveedorConAdeudo:
    return ProveedorConAdeudo(
        id=fila.id,
        rfc=fila.rfc,
        nombre=fila.nombre,
        dias_credito=fila.dias_credito,
        # Un dígito que no se puede calcular (RFC genérico) no cuenta como inválido.
        rfc_valido=bool(fila.rfc_formato_valido) and fila.rfc_digito_valido is not False,
        situacion_69b=fila.situacion_69b,
        adeudo_mxn=fila.adeudo_mxn,
        facturas_con_saldo=fila.facturas_con_saldo,
    )


def _filtro_texto_proveedor(texto: str) -> ColumnElement[bool]:
    patron = _patron_contiene(texto.strip())
    return or_(Proveedor.nombre.ilike(patron, escape="\\"), Proveedor.rfc.ilike(patron, escape="\\"))


def buscar_proveedores(sesion: Session, *, texto: str | None, rfc: str | None, limite: int) -> list[ProveedorConAdeudo]:
    """Proveedores cuyo nombre o RFC contiene `texto`, o con ese `rfc` exacto, con su adeudo en pesos."""
    consulta, adeudo = _consulta_proveedores(_SIN_FECHA)
    if rfc and rfc.strip():
        consulta = consulta.where(Proveedor.rfc == rfc.strip().upper())
    if texto and texto.strip():
        consulta = consulta.where(_filtro_texto_proveedor(texto))
    consulta = consulta.order_by(func.coalesce(adeudo.c.adeudo_mxn, 0).desc(), Proveedor.nombre, Proveedor.id)
    return [_proveedor_con_adeudo(f) for f in sesion.execute(consulta.limit(max(1, limite)))]


def listar_proveedores(
    sesion: Session, *, texto: str | None, pagina: int, por_pagina: int, hoy: date
) -> PaginaProveedores:
    consulta, _ = _consulta_proveedores(hoy)
    conteo = select(func.count()).select_from(Proveedor)
    if texto and texto.strip():
        consulta = consulta.where(_filtro_texto_proveedor(texto))
        conteo = conteo.where(_filtro_texto_proveedor(texto))
    filas = sesion.execute(
        consulta.order_by(Proveedor.nombre, Proveedor.id).limit(por_pagina).offset((pagina - 1) * por_pagina)
    ).all()
    return PaginaProveedores(
        elementos=[_proveedor_con_adeudo(f) for f in filas],
        total=sesion.execute(conteo).scalar_one(),
        pagina=pagina,
        por_pagina=por_pagina,
    )


def proveedor_con_adeudo(sesion: Session, proveedor_id: int, hoy: date) -> ProveedorConAdeudo:
    consulta, _ = _consulta_proveedores(hoy)
    fila = sesion.execute(consulta.where(Proveedor.id == proveedor_id)).one_or_none()
    if fila is None:
        raise ProveedorNoEncontrado(proveedor_id)
    return _proveedor_con_adeudo(fila)


def adeudo_proveedor(sesion: Session, proveedor_id: int, hoy: date) -> AdeudoProveedor:
    """Adeudo de un proveedor con sus facturas con saldo. Lanza ProveedorNoEncontrado si no existe."""
    proveedor = sesion.get(Proveedor, proveedor_id)
    if proveedor is None:
        raise ProveedorNoEncontrado(proveedor_id)
    v = vista_facturas(hoy)
    condicion = and_(con_saldo(v), v.c.proveedor_id == proveedor_id)
    adeudo, conteo = sesion.execute(
        select(func.coalesce(func.sum(v.c.saldo_mxn), 0), func.count()).select_from(v).where(condicion)
    ).one()
    filas = sesion.execute(
        select(v).where(condicion).order_by(v.c.vencimiento, v.c.id).limit(MAX_FACTURAS_ADEUDO)
    ).all()
    return AdeudoProveedor(
        proveedor=ProveedorCorto(id=proveedor.id, rfc=proveedor.rfc, nombre=proveedor.nombre),
        adeudo_mxn=adeudo,
        adeudo_por_moneda=adeudo_por_moneda(sesion, hoy, proveedor_id),
        facturas=[_resumen(f) for f in filas],
        facturas_omitidas=conteo - len(filas),
    )


def vencimientos(
    sesion: Session, desde: date | None, hasta: date, hoy: date, *, limite: int | None = None
) -> ResumenFacturas:
    """Facturas tipo I con saldo cuyo vencimiento cae en [desde, hasta], ambos inclusivos."""
    v = vista_facturas(hoy)
    condiciones = [con_saldo(v), v.c.vencimiento <= hasta]
    if desde is not None:
        condiciones.append(v.c.vencimiento >= desde)
    saldo_total, conteo = sesion.execute(
        select(func.coalesce(func.sum(v.c.saldo_mxn), 0), func.count()).select_from(v).where(*condiciones)
    ).one()
    consulta = select(v).where(*condiciones).order_by(v.c.vencimiento, v.c.id)
    if limite is not None:
        consulta = consulta.limit(max(0, limite))
    return ResumenFacturas(
        desde=desde,
        hasta=hasta,
        facturas=[_resumen(f) for f in sesion.execute(consulta)],
        saldo_total_mxn=saldo_total,
        conteo=conteo,
    )


def _meses(desde_mes: str, hasta_mes: str) -> list[str]:
    for valor in (desde_mes, hasta_mes):
        if _PATRON_MES.fullmatch(valor) is None:
            raise ValueError(f"El mes {valor!r} no tiene el formato AAAA-MM.")
    anio, mes = int(desde_mes[:4]), int(desde_mes[5:])
    anio_fin, mes_fin = int(hasta_mes[:4]), int(hasta_mes[5:])
    if (anio, mes) > (anio_fin, mes_fin):
        raise ValueError("El mes inicial es posterior al mes final.")
    meses = []
    while (anio, mes) <= (anio_fin, mes_fin):
        meses.append(f"{anio:04d}-{mes:02d}")
        anio, mes = (anio + 1, 1) if mes == 12 else (anio, mes + 1)
        if len(meses) > MAX_MESES:
            raise ValueError(f"El rango no puede pasar de {MAX_MESES} meses.")
    return meses


def totales_por_mes(
    sesion: Session, *, medida: str, desde_mes: str, hasta_mes: str, proveedor_id: int | None
) -> list[TotalMes]:
    """Un renglón por mes del rango (también los meses en cero). Lanza ValueError si el rango es inválido.

    `facturado`: total de las facturas de ingreso emitidas en el mes. `pagado`: pagos aplicados en el mes
    (complementos y pagos aprobados; las notas de crédito no son pagos). `saldo`: lo que hoy se debe de las
    facturas emitidas en el mes. Todo en pesos, con el tipo de cambio de cada factura.
    """
    if medida not in ("facturado", "pagado", "saldo"):
        raise ValueError("La medida debe ser facturado, pagado o saldo.")
    meses = _meses(desde_mes, hasta_mes)
    inicio = date(int(meses[0][:4]), int(meses[0][5:]), 1)
    ultimo = date(int(meses[-1][:4]), int(meses[-1][5:]), 1)
    fin = date(ultimo.year + 1, 1, 1) if ultimo.month == 12 else date(ultimo.year, ultimo.month + 1, 1)

    consulta: Select[Any]
    if medida == "pagado":
        mes = func.to_char(Aplicacion.fecha, "YYYY-MM")
        consulta = (
            select(mes, func.coalesce(func.sum(func.round(Aplicacion.importe * _factor_mxn(), 2)), 0), func.count())
            .select_from(Aplicacion)
            .join(Factura, Factura.id == Aplicacion.factura_id)
            .where(Aplicacion.origen.in_(_ORIGENES_DE_PAGO), Aplicacion.fecha >= inicio, Aplicacion.fecha < fin)
            .group_by(mes)
        )
        if proveedor_id is not None:
            consulta = consulta.where(Factura.proveedor_id == proveedor_id)
    else:
        # La fecha de hoy no cambia totales ni saldos; la vista la pide para calcular vencimientos.
        v = vista_facturas(inicio)
        mes = func.to_char(v.c.fecha_emision, "YYYY-MM")
        columna = v.c.total_mxn if medida == "facturado" else v.c.saldo_mxn
        consulta = (
            select(mes, func.coalesce(func.sum(columna), 0), func.count())
            .select_from(v)
            .where(
                v.c.tipo == "I",
                v.c.fecha_emision >= datetime.combine(inicio, time.min),
                v.c.fecha_emision < datetime.combine(fin, time.min),
            )
            .group_by(mes)
        )
        if medida == "saldo":
            consulta = consulta.where(v.c.saldo > 0)
        if proveedor_id is not None:
            consulta = consulta.where(v.c.proveedor_id == proveedor_id)
    por_mes = {clave: (total, conteo) for clave, total, conteo in sesion.execute(consulta)}
    return [
        TotalMes(mes=clave, total_mxn=por_mes.get(clave, (Decimal(0), 0))[0], conteo=por_mes.get(clave, (0, 0))[1])
        for clave in meses
    ]


def antiguedad(sesion: Session, hoy: date) -> Antiguedad:
    """Adeudo en pesos por grupo de antigüedad. La suma de los grupos es igual al adeudo total (B3)."""
    v = vista_facturas(hoy)
    grupo = columna_grupo(v.c.dias_vencido)
    por_grupo = {
        clave: (suma, cuenta)
        for clave, suma, cuenta in sesion.execute(
            select(grupo, func.sum(v.c.saldo_mxn), func.count()).where(con_adeudo_en_pesos(v)).group_by(grupo)
        )
    }
    total = sesion.execute(select(func.coalesce(func.sum(v.c.saldo_mxn), 0)).where(con_adeudo_en_pesos(v))).scalar_one()
    return Antiguedad(
        fecha_corte=hoy,
        grupos=[
            GrupoAntiguedad(
                grupo=clave,
                etiqueta=etiqueta,
                saldo_mxn=por_grupo.get(clave, (Decimal(0), 0))[0],
                facturas=por_grupo.get(clave, (Decimal(0), 0))[1],
            )
            for clave, etiqueta in GRUPOS_ANTIGUEDAD
        ],
        adeudo_total_mxn=total,
    )


def tablero(sesion: Session, hoy: date) -> Tablero:
    from cotejo.cxp import tablero as calculo

    return calculo.calcular(sesion, hoy)


def _bloqueos_de(sesion: Session, filas: Sequence[Row[Any]]) -> dict[int, list[BloqueoFactura]]:
    if not filas:
        return {}
    factura_ids = [f.id for f in filas]
    proveedor_ids = {f.proveedor_id for f in filas}
    alertas = sesion.execute(
        select(Alerta.factura_id, Alerta.proveedor_id, Alerta.codigo, Alerta.mensaje)
        .where(
            Alerta.severidad == "bloqueante",
            Alerta.estado == "abierta",
            or_(
                Alerta.factura_id.in_(factura_ids),
                and_(Alerta.factura_id.is_(None), Alerta.proveedor_id.in_(proveedor_ids)),
            ),
        )
        .order_by(Alerta.id)
    ).all()
    de_factura: dict[int, list[BloqueoFactura]] = {}
    de_proveedor: dict[int, list[BloqueoFactura]] = {}
    for factura_id, proveedor_id, codigo, mensaje in alertas:
        bloqueo = BloqueoFactura(codigo=codigo, mensaje=mensaje)
        if factura_id is not None:
            de_factura.setdefault(factura_id, []).append(bloqueo)
        elif proveedor_id is not None:
            de_proveedor.setdefault(proveedor_id, []).append(bloqueo)
    return {f.id: de_factura.get(f.id, []) + de_proveedor.get(f.proveedor_id, []) for f in filas}


def facturas_elegibles(
    sesion: Session, *, hasta: date | None, ids: list[int] | None, hoy: date, desde: date | None = None
) -> list[FacturaElegible]:
    """Sin `ids`: facturas tipo I con saldo y vencimiento en [desde, hasta], por vencimiento y luego saldo.

    Con `ids`: esas facturas, existan o no las condiciones para pagarlas, en el mismo orden.
    """
    v = vista_facturas(hoy)
    consulta = select(v)
    if ids is not None:
        consulta = consulta.where(v.c.id.in_(ids))
    else:
        consulta = consulta.where(con_saldo(v))
        if hasta is not None:
            consulta = consulta.where(v.c.vencimiento <= hasta)
        if desde is not None:
            consulta = consulta.where(v.c.vencimiento >= desde)
    filas = sesion.execute(consulta.order_by(v.c.vencimiento, v.c.saldo_mxn.desc().nulls_last(), v.c.id)).all()
    bloqueos = _bloqueos_de(sesion, filas)
    return [
        FacturaElegible(
            factura_id=f.id,
            uuid=f.uuid,
            tipo=f.tipo,
            serie=f.serie,
            folio=f.folio,
            proveedor=_proveedor_corto(f),
            fecha_emision=f.fecha_emision,
            vencimiento=f.vencimiento,
            dias_vencido=f.dias_vencido,
            moneda=f.moneda,
            tipo_cambio=f.tipo_cambio,
            total=f.total,
            saldo=f.saldo,
            saldo_mxn=f.saldo_mxn,
            bloqueos=bloqueos[f.id],
            en_propuesta_pendiente=f.en_propuesta_pendiente,
        )
        for f in filas
    ]
