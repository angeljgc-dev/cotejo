"""Formato único de error de la API: {"error": {"codigo", "mensaje", "detalle"}}."""

from __future__ import annotations

import logging
from collections.abc import Mapping

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_log = logging.getLogger("cotejo.api")

_MENSAJES_VALIDACION = {
    "missing": "Campo obligatorio.",
    "string_too_short": "El texto es demasiado corto.",
    "string_too_long": "El texto es demasiado largo.",
    "literal_error": "Valor no permitido.",
    "enum": "Valor no permitido.",
    "int_parsing": "Debe ser un número entero.",
    "int_type": "Debe ser un número entero.",
    "greater_than_equal": "El valor es menor que el mínimo permitido.",
    "less_than_equal": "El valor es mayor que el máximo permitido.",
    "date_from_datetime_parsing": "Debe ser una fecha AAAA-MM-DD.",
    "date_parsing": "Debe ser una fecha AAAA-MM-DD.",
    "json_invalid": "El cuerpo no es JSON válido.",
    "model_attributes_type": "Se esperaba un objeto JSON.",
    "dict_type": "Se esperaba un objeto JSON.",
}

_CODIGOS_HTTP = {
    401: ("NO_AUTENTICADO", "Inicia sesión para continuar."),
    403: ("PROHIBIDO", "No tienes permiso para esta acción."),
    404: ("RUTA_NO_ENCONTRADA", "La ruta solicitada no existe."),
    405: ("METODO_NO_PERMITIDO", "Método no permitido en esta ruta."),
    413: ("CARGA_DEMASIADO_GRANDE", "La petición es demasiado grande."),
}


class ErrorApi(Exception):
    def __init__(self, estado: int, codigo: str, mensaje: str, detalle: Mapping[str, object] | None = None) -> None:
        super().__init__(mensaje)
        self.estado = estado
        self.codigo = codigo
        self.mensaje = mensaje
        self.detalle: dict[str, object] = dict(detalle or {})


def respuesta_error(
    estado: int, codigo: str, mensaje: str, detalle: Mapping[str, object] | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=estado, content={"error": {"codigo": codigo, "mensaje": mensaje, "detalle": dict(detalle or {})}}
    )


async def _error_api(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, ErrorApi):
        raise exc
    return respuesta_error(exc.estado, exc.codigo, exc.mensaje, exc.detalle)


async def _error_validacion(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):
        raise exc
    campos = []
    for err in exc.errors():
        ubicacion = [str(p) for p in err.get("loc", ()) if p not in ("body", "query", "path", "header", "cookie")]
        tipo = str(err.get("type", ""))
        campos.append({"campo": ".".join(ubicacion), "mensaje": _MENSAJES_VALIDACION.get(tipo, "Valor inválido.")})
    return respuesta_error(422, "VALIDACION", "Revisa los datos enviados.", {"campos": campos})


async def _error_http(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, StarletteHTTPException):
        raise exc
    codigo, mensaje = _CODIGOS_HTTP.get(exc.status_code, ("ERROR_HTTP", "La petición no se pudo atender."))
    return respuesta_error(exc.status_code, codigo, mensaje)


class CapturarErrores:
    """Convierte cualquier excepción no controlada en 500 ERROR_INTERNO con el formato del contrato.

    Va dentro del middleware de cabeceras para que los 500 también lleven CSP, nosniff y no-store; el manejador
    de Starlette para Exception corre fuera de todos los middlewares y los dejaría sin ellas.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        respuesta_iniciada = False

        async def enviar(mensaje: Message) -> None:
            nonlocal respuesta_iniciada
            if mensaje["type"] == "http.response.start":
                respuesta_iniciada = True
            await send(mensaje)

        try:
            await self.app(scope, receive, enviar)
        except Exception:
            _log.exception("Error no controlado en %s %s", scope.get("method"), scope.get("path"))
            if respuesta_iniciada:
                raise
            respuesta = respuesta_error(
                500, "ERROR_INTERNO", "Ocurrió un error inesperado. Intenta de nuevo más tarde."
            )
            await respuesta(scope, receive, send)


def registrar_manejadores(app: FastAPI) -> None:
    app.add_exception_handler(ErrorApi, _error_api)
    app.add_exception_handler(RequestValidationError, _error_validacion)
    app.add_exception_handler(StarletteHTTPException, _error_http)
