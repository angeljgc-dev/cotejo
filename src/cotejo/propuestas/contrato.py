"""Modelos de entrada y salida de propuestas (contrato de la API) y su armado desde la base."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cotejo.cxp import consultas
from cotejo.cxp.consultas import ProveedorCorto
from cotejo.dinero import Importe, ImporteEntrada
from cotejo.documentos.contrato import UsuarioCorto
from cotejo.modelos import Propuesta, RenglonPropuesta, Usuario

Horizonte = Literal["vencidas", "esta_semana", "proximos_7_dias", "proximos_30_dias"]
EstadoPropuesta = Literal["pendiente", "aprobada", "rechazada"]


class NuevaPropuesta(BaseModel):
    presupuesto_mxn: ImporteEntrada
    horizonte: Horizonte | None = None
    fecha_limite: date | None = None
    factura_ids: list[int] | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def _un_solo_corte(self) -> Self:
        if (self.horizonte is None) == (self.fecha_limite is None):
            raise ValueError("Indica exactamente uno: horizonte o fecha_limite.")
        return self


class MotivoRechazo(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    motivo: str = Field(min_length=5, max_length=500)


class FacturaDeRenglon(BaseModel):
    id: int
    uuid: str
    serie: str | None
    folio: str | None
    proveedor: ProveedorCorto
    moneda: str
    vencimiento: date | None
    saldo_actual: Importe


class RenglonSalida(BaseModel):
    id: int
    factura: FacturaDeRenglon
    importe: Importe
    importe_mxn: Importe
    razon: str


class ExcluidaSalida(BaseModel):
    factura_id: int
    serie: str | None = None
    folio: str | None = None
    proveedor_nombre: str | None = None
    saldo_mxn: str | None = None
    codigo: str
    motivo: str


class PropuestaSalida(BaseModel):
    id: int
    estado: EstadoPropuesta
    presupuesto_mxn: Importe
    total_mxn: Importe
    fecha_limite: date
    origen: str
    creada_por: UsuarioCorto
    creado_en: datetime
    renglones: list[RenglonSalida]
    excluidas: list[ExcluidaSalida]
    decidida_por: UsuarioCorto | None
    decidida_en: datetime | None
    motivo_rechazo: str | None
    # Verdadero si quien consulta es aprobador, no la creó y sigue pendiente.
    puede_decidir: bool


class PropuestaResumen(BaseModel):
    id: int
    estado: EstadoPropuesta
    presupuesto_mxn: Importe
    total_mxn: Importe
    renglones: int
    creada_por: UsuarioCorto
    creado_en: datetime
    decidida_por: UsuarioCorto | None


class PaginaPropuestas(BaseModel):
    elementos: list[PropuestaResumen]
    total: int
    pagina: int
    por_pagina: int


def _estado(valor: str) -> EstadoPropuesta:
    if valor == "aprobada":
        return "aprobada"
    return "rechazada" if valor == "rechazada" else "pendiente"


def _usuario_corto(sesion: Session, usuario_id: int | None) -> UsuarioCorto | None:
    if usuario_id is None:
        return None
    usuario = sesion.get(Usuario, usuario_id)
    return UsuarioCorto.de(usuario) if usuario is not None else None


def puede_decidir(propuesta: Propuesta, usuario: Usuario) -> bool:
    return usuario.rol == "aprobador" and propuesta.creada_por != usuario.id and propuesta.estado == "pendiente"


def a_salida(sesion: Session, propuesta: Propuesta, usuario: Usuario, hoy: date) -> PropuestaSalida:
    """Propuesta completa, con el saldo actual de cada factura (puede haber cambiado desde que se armó)."""
    renglones = list(
        sesion.scalars(
            select(RenglonPropuesta).where(RenglonPropuesta.propuesta_id == propuesta.id).order_by(RenglonPropuesta.id)
        )
    )
    ids = [r.factura_id for r in renglones]
    facturas = {
        f.factura_id: f for f in (consultas.facturas_elegibles(sesion, hasta=None, ids=ids, hoy=hoy) if ids else [])
    }
    salida_renglones = []
    for renglon in renglones:
        factura = facturas[renglon.factura_id]
        salida_renglones.append(
            RenglonSalida(
                id=renglon.id,
                factura=FacturaDeRenglon(
                    id=factura.factura_id,
                    uuid=factura.uuid,
                    serie=factura.serie,
                    folio=factura.folio,
                    proveedor=factura.proveedor,
                    moneda=factura.moneda,
                    vencimiento=factura.vencimiento,
                    saldo_actual=factura.saldo,
                ),
                importe=renglon.importe,
                importe_mxn=renglon.importe_mxn,
                razon=renglon.razon,
            )
        )
    creador = _usuario_corto(sesion, propuesta.creada_por)
    if creador is None:
        raise LookupError(f"La propuesta {propuesta.id} no tiene usuario creador.")
    return PropuestaSalida(
        id=propuesta.id,
        estado=_estado(propuesta.estado),
        presupuesto_mxn=propuesta.presupuesto_mxn,
        total_mxn=propuesta.total_mxn,
        fecha_limite=propuesta.fecha_limite,
        origen=propuesta.origen,
        creada_por=creador,
        creado_en=propuesta.creado_en,
        renglones=salida_renglones,
        excluidas=[ExcluidaSalida.model_validate(e) for e in propuesta.excluidas],
        decidida_por=_usuario_corto(sesion, propuesta.decidida_por),
        decidida_en=propuesta.decidida_en,
        motivo_rechazo=propuesta.motivo_rechazo,
        puede_decidir=puede_decidir(propuesta, usuario),
    )


def listar(sesion: Session, *, estado: EstadoPropuesta | None, pagina: int, por_pagina: int) -> PaginaPropuestas:
    conteo = (
        select(RenglonPropuesta.propuesta_id, func.count().label("n"))
        .group_by(RenglonPropuesta.propuesta_id)
        .subquery()
    )
    consulta = select(Propuesta, func.coalesce(conteo.c.n, 0)).outerjoin(conteo, conteo.c.propuesta_id == Propuesta.id)
    total_q = select(func.count()).select_from(Propuesta)
    if estado is not None:
        consulta = consulta.where(Propuesta.estado == estado)
        total_q = total_q.where(Propuesta.estado == estado)
    filas = sesion.execute(
        consulta.order_by(Propuesta.creado_en.desc(), Propuesta.id.desc())
        .limit(por_pagina)
        .offset((pagina - 1) * por_pagina)
    ).all()
    elementos = []
    for propuesta, renglones in filas:
        creador = _usuario_corto(sesion, propuesta.creada_por)
        if creador is None:
            continue
        elementos.append(
            PropuestaResumen(
                id=propuesta.id,
                estado=_estado(propuesta.estado),
                presupuesto_mxn=propuesta.presupuesto_mxn,
                total_mxn=propuesta.total_mxn,
                renglones=int(renglones),
                creada_por=creador,
                creado_en=propuesta.creado_en,
                decidida_por=_usuario_corto(sesion, propuesta.decidida_por),
            )
        )
    return PaginaPropuestas(
        elementos=elementos, total=sesion.scalar(total_q) or 0, pagina=pagina, por_pagina=por_pagina
    )
