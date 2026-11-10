"""Rutas del asistente. Se montan en app.py bajo /api; las rutas se declaran sin el prefijo /api."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from cotejo.api.dependencias import ConfigApp, SesionDb, UsuarioActual, VisitanteActual
from cotejo.api.errores import ErrorApi
from cotejo.asistente import servicio
from cotejo.asistente.cliente_modelo import ClienteModelo
from cotejo.asistente.servicio import (
    ConversacionCreada,
    ConversacionSalida,
    EstadoAsistente,
    MensajeSalida,
    NuevoMensaje,
    obtener_cliente_modelo,
)

router = APIRouter(tags=["asistente"])


ClienteDelModelo = Annotated[ClienteModelo | None, Depends(obtener_cliente_modelo)]


def _como_error_api(exc: servicio.ErrorAsistente) -> ErrorApi:
    return ErrorApi(exc.estado, exc.codigo, exc.mensaje, exc.detalle)


@router.get("/asistente/estado")
def estado_asistente(
    sesion: SesionDb, config: ConfigApp, cliente: ClienteDelModelo, _usuario: UsuarioActual, visitante: VisitanteActual
) -> EstadoAsistente:
    return servicio.estado(sesion, config, cliente, visitante)


@router.post("/asistente/conversaciones")
def crear_conversacion(sesion: SesionDb, usuario: UsuarioActual, visitante: VisitanteActual) -> ConversacionCreada:
    return ConversacionCreada(id=servicio.crear_conversacion(sesion, usuario, visitante).id)


@router.get("/asistente/conversacion")
def conversacion_reciente(
    sesion: SesionDb, config: ConfigApp, usuario: UsuarioActual, visitante: VisitanteActual
) -> ConversacionSalida | None:
    """La conversación más reciente de quien consulta, o null si aún no tiene."""
    return servicio.conversacion_reciente(sesion, usuario, visitante, config)


@router.get("/asistente/conversaciones/{conversacion_id}")
def ver_conversacion(
    conversacion_id: uuid.UUID, sesion: SesionDb, config: ConfigApp, usuario: UsuarioActual, visitante: VisitanteActual
) -> ConversacionSalida:
    try:
        return servicio.ver_conversacion(sesion, conversacion_id, usuario, visitante, config)
    except servicio.ErrorAsistente as exc:
        raise _como_error_api(exc) from exc


@router.post("/asistente/mensajes")
def enviar_mensaje(
    datos: NuevoMensaje,
    sesion: SesionDb,
    config: ConfigApp,
    cliente: ClienteDelModelo,
    usuario: UsuarioActual,
    visitante: VisitanteActual,
) -> MensajeSalida:
    """Una pregunta, una respuesta. Las cifras de la respuesta salen de herramientas que consultan la base."""
    try:
        return servicio.responder(
            sesion,
            config=config,
            cliente=cliente,
            usuario=usuario,
            visitante=visitante,
            conversacion_id=datos.conversacion_id,
            texto=datos.texto,
        )
    except servicio.ErrorAsistente as exc:
        raise _como_error_api(exc) from exc
