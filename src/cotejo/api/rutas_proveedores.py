"""Proveedores: lista con adeudo, detalle por moneda con sus documentos y edición de los días de crédito."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from cotejo import bitacora
from cotejo.api.dependencias import ConfigApp, IdRuta, Pagina, SesionDb, UsuarioActual
from cotejo.api.errores import ErrorApi
from cotejo.cxp import consultas
from cotejo.cxp.consultas import PaginaProveedores, ProveedorConAdeudo
from cotejo.cxp.contrato import ProveedorDetalle
from cotejo.fechas import hoy
from cotejo.modelos import Documento, Proveedor

router = APIRouter(tags=["proveedores"])


class EdicionProveedor(BaseModel):
    dias_credito: int = Field(ge=0, le=365, strict=True)


def _no_encontrado() -> ErrorApi:
    return ErrorApi(404, "PROVEEDOR_NO_ENCONTRADO", "El proveedor no existe.")


@router.get("/proveedores")
def listar_proveedores(
    sesion: SesionDb,
    config: ConfigApp,
    _usuario: UsuarioActual,
    texto: Annotated[str | None, Query(max_length=120)] = None,
    pagina: Pagina = 1,
    por_pagina: Annotated[int, Query(ge=1, le=100)] = 25,
) -> PaginaProveedores:
    return consultas.listar_proveedores(sesion, texto=texto, pagina=pagina, por_pagina=por_pagina, hoy=hoy(config))


@router.get("/proveedores/{proveedor_id}")
def ver_proveedor(
    proveedor_id: IdRuta, sesion: SesionDb, config: ConfigApp, _usuario: UsuarioActual
) -> ProveedorDetalle:
    dia = hoy(config)
    try:
        base = consultas.proveedor_con_adeudo(sesion, proveedor_id, dia)
    except consultas.ProveedorNoEncontrado as exc:
        raise _no_encontrado() from exc
    documentos = sesion.scalars(
        select(Documento).where(Documento.proveedor_id == proveedor_id).order_by(Documento.id)
    ).all()
    return ProveedorDetalle.model_validate(
        {
            **base.model_dump(),
            "adeudo_por_moneda": consultas.adeudo_por_moneda(sesion, dia, proveedor_id=proveedor_id),
            "documentos": [{"id": d.id, "nombre": d.nombre, "tipo": d.tipo, "estado": d.estado} for d in documentos],
        }
    )


@router.patch("/proveedores/{proveedor_id}")
def editar_proveedor(
    proveedor_id: IdRuta, entrada: EdicionProveedor, sesion: SesionDb, config: ConfigApp, usuario: UsuarioActual
) -> ProveedorConAdeudo:
    proveedor = sesion.execute(
        select(Proveedor).where(Proveedor.id == proveedor_id).with_for_update()
    ).scalar_one_or_none()
    if proveedor is None:
        raise _no_encontrado()
    anterior = proveedor.dias_credito
    if anterior != entrada.dias_credito:
        proveedor.dias_credito = entrada.dias_credito
        proveedor.actualizado_en = datetime.now(UTC)
        sesion.flush()
        bitacora.registrar(
            sesion,
            usuario_id=usuario.id,
            accion="PROVEEDOR_EDITADO",
            entidad="proveedor",
            entidad_id=proveedor.id,
            detalle={"campo": "dias_credito", "anterior": anterior, "nuevo": entrada.dias_credito},
        )
    return consultas.proveedor_con_adeudo(sesion, proveedor_id, hoy(config))
