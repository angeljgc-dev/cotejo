"""Rutas de propuestas. Se montan en app.py bajo /api; las rutas se declaran sin el prefijo /api.

Aprobar y rechazar no pasan por el modelo de lenguaje: son decisiones de una persona con rol aprobador.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from cotejo.api.dependencias import ConfigApp, SesionDb, UsuarioActual, requiere_rol
from cotejo.api.errores import ErrorApi
from cotejo.fechas import hoy
from cotejo.modelos import Propuesta, Usuario
from cotejo.propuestas import contrato, servicio
from cotejo.propuestas.contrato import (
    EstadoPropuesta,
    MotivoRechazo,
    NuevaPropuesta,
    PaginaPropuestas,
    PropuestaSalida,
)

router = APIRouter(tags=["propuestas"])


def _como_error_api(exc: servicio.ErrorPropuesta) -> ErrorApi:
    return ErrorApi(exc.estado, exc.codigo, exc.mensaje, exc.detalle)


@router.post("/propuestas")
def crear_propuesta(
    datos: NuevaPropuesta,
    sesion: SesionDb,
    config: ConfigApp,
    usuario: Annotated[Usuario, Depends(requiere_rol("capturista"))],
) -> PropuestaSalida:
    """Arma una propuesta pendiente. Las facturas las elige el sistema con las barreras; nada se paga aquí."""
    dia = hoy(config)
    try:
        propuesta = servicio.crear_propuesta(
            sesion,
            usuario=usuario,
            presupuesto_mxn=datos.presupuesto_mxn,
            origen="api",
            hoy=dia,
            horizonte=datos.horizonte,
            fecha_limite=datos.fecha_limite,
            factura_ids=datos.factura_ids,
        )
    except servicio.ErrorPropuesta as exc:
        raise _como_error_api(exc) from exc
    return contrato.a_salida(sesion, propuesta, usuario, dia)


@router.get("/propuestas")
def listar_propuestas(
    sesion: SesionDb,
    _usuario: UsuarioActual,
    estado: EstadoPropuesta | None = None,
    pagina: Annotated[int, Query(ge=1)] = 1,
    por_pagina: Annotated[int, Query(ge=1, le=100)] = 25,
) -> PaginaPropuestas:
    return contrato.listar(sesion, estado=estado, pagina=pagina, por_pagina=por_pagina)


@router.get("/propuestas/{propuesta_id}")
def ver_propuesta(propuesta_id: int, sesion: SesionDb, config: ConfigApp, usuario: UsuarioActual) -> PropuestaSalida:
    propuesta = sesion.get(Propuesta, propuesta_id)
    if propuesta is None:
        raise ErrorApi(404, "PROPUESTA_NO_ENCONTRADA", "La propuesta no existe.")
    return contrato.a_salida(sesion, propuesta, usuario, hoy(config))


@router.post("/propuestas/{propuesta_id}/aprobar")
def aprobar_propuesta(
    propuesta_id: int,
    sesion: SesionDb,
    config: ConfigApp,
    usuario: Annotated[Usuario, Depends(requiere_rol("aprobador"))],
) -> PropuestaSalida:
    """Registra los pagos de la propuesta y actualiza los saldos en una sola transacción."""
    dia = hoy(config)
    try:
        propuesta = servicio.aprobar(sesion, propuesta_id=propuesta_id, usuario=usuario, hoy=dia)
    except servicio.ErrorPropuesta as exc:
        raise _como_error_api(exc) from exc
    return contrato.a_salida(sesion, propuesta, usuario, dia)


@router.post("/propuestas/{propuesta_id}/rechazar")
def rechazar_propuesta(
    propuesta_id: int,
    datos: MotivoRechazo,
    sesion: SesionDb,
    config: ConfigApp,
    usuario: Annotated[Usuario, Depends(requiere_rol("aprobador"))],
) -> PropuestaSalida:
    try:
        propuesta = servicio.rechazar(sesion, propuesta_id=propuesta_id, usuario=usuario, motivo=datos.motivo)
    except servicio.ErrorPropuesta as exc:
        raise _como_error_api(exc) from exc
    return contrato.a_salida(sesion, propuesta, usuario, hoy(config))
