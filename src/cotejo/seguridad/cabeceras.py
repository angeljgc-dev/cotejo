"""Middleware ASGI de cabeceras de seguridad (DISEÑO sección 8)."""

from __future__ import annotations

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send


def politica_contenido(frame_ancestors: str) -> str:
    return (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
        f"object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors {frame_ancestors}"
    )


class CabecerasSeguridad:
    def __init__(self, app: ASGIApp, *, frame_ancestors: str, hsts: bool) -> None:
        self.app = app
        self.fijas = {
            "Content-Security-Policy": politica_contenido(frame_ancestors),
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "same-origin",
            "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
        }
        if hsts:
            self.fijas["Strict-Transport-Security"] = "max-age=31536000"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        es_api = str(scope.get("path", "")).startswith("/api/")

        async def enviar(mensaje: Message) -> None:
            if mensaje["type"] == "http.response.start":
                cabeceras = MutableHeaders(scope=mensaje)
                for nombre, valor in self.fijas.items():
                    cabeceras[nombre] = valor
                if es_api:
                    cabeceras["Cache-Control"] = "no-store"
            await send(mensaje)

        await self.app(scope, receive, enviar)
