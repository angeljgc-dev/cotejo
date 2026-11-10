"""Protección CSRF y límite de tamaño de petición, como middlewares ASGI.

CSRF: cookie SameSite=Lax más la cabecera obligatoria `X-Cotejo: 1` en métodos que modifican. Sin CORS, otro
sitio no puede mandar esa cabecera desde el navegador.
"""

from __future__ import annotations

import json

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

CABECERA_CSRF = "x-cotejo"
METODOS_QUE_MODIFICAN = frozenset({"POST", "PUT", "PATCH", "DELETE"})


async def _responder_error(send: Send, estado: int, codigo: str, mensaje: str) -> None:
    cuerpo = json.dumps({"error": {"codigo": codigo, "mensaje": mensaje, "detalle": {}}}).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": estado,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(cuerpo)).encode())],
        }
    )
    await send({"type": "http.response.body", "body": cuerpo})


class ExigirCabeceraCsrf:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] == "http"
            and scope["method"] in METODOS_QUE_MODIFICAN
            and str(scope.get("path", "")).startswith("/api/")
            and Headers(scope=scope).get(CABECERA_CSRF) != "1"
        ):
            await _responder_error(
                send, 403, "CSRF_FALTANTE", "Falta la cabecera de protección X-Cotejo en una petición que modifica."
            )
            return
        await self.app(scope, receive, send)


class LimiteTamanoPeticion:
    """Rechaza con 413 las peticiones más grandes que el límite.

    Con Content-Length se corta antes de leer el cuerpo. Sin él (cuerpo por bloques) se lee hasta el límite y se
    corta en cuanto lo rebasa; lo leído se le entrega íntegro a la aplicación. La memoria queda acotada al límite.
    """

    def __init__(self, app: ASGIApp, *, limite_bytes: int) -> None:
        self.app = app
        self.limite_bytes = limite_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declarado = Headers(scope=scope).get("content-length")
        if declarado is not None:
            if not declarado.isdigit() or int(declarado) > self.limite_bytes:
                await _responder_413(send)
                return
            await self.app(scope, receive, send)
            return

        bloques: list[bytes] = []
        recibidos = 0
        while True:
            mensaje = await receive()
            if mensaje["type"] != "http.request":
                # El cliente se desconectó: no hay a quién responder.
                return
            cuerpo = mensaje.get("body", b"")
            recibidos += len(cuerpo)
            if recibidos > self.limite_bytes:
                await _responder_413(send)
                return
            bloques.append(cuerpo)
            if not mensaje.get("more_body", False):
                break

        entregado = False

        async def reproducir() -> Message:
            nonlocal entregado
            if not entregado:
                entregado = True
                return {"type": "http.request", "body": b"".join(bloques), "more_body": False}
            return await receive()

        await self.app(scope, reproducir, send)


async def _responder_413(send: Send) -> None:
    await _responder_error(send, 413, "CARGA_DEMASIADO_GRANDE", "La petición rebasa el tamaño máximo permitido.")
