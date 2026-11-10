"""Aplicación FastAPI: monta routers bajo /api, middlewares de seguridad, errores y estáticos del frontend.

Cada módulo de rutas expone `router = APIRouter(tags=[...])` con rutas sin el prefijo /api, y se agrega a
ROUTERS. Arranque: `uvicorn cotejo.api.app:app`.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.responses import FileResponse, Response

from cotejo.api import (
    rutas_alertas,
    rutas_asistente,
    rutas_bitacora,
    rutas_busqueda,
    rutas_cargas,
    rutas_demo,
    rutas_documentos,
    rutas_facturas,
    rutas_lista69b,
    rutas_propuestas,
    rutas_proveedores,
    rutas_salud,
    rutas_sesion,
    rutas_tablero,
)
from cotejo.api.errores import CapturarErrores, ErrorApi, registrar_manejadores
from cotejo.config import MB_POR_PETICION, Settings, obtener_config
from cotejo.seguridad.cabeceras import CabecerasSeguridad
from cotejo.seguridad.csrf import ExigirCabeceraCsrf, LimiteTamanoPeticion

ROUTERS: tuple[APIRouter, ...] = (
    rutas_salud.router,
    rutas_sesion.router,
    rutas_demo.router,
    rutas_cargas.router,
    rutas_facturas.router,
    rutas_proveedores.router,
    rutas_alertas.router,
    rutas_tablero.router,
    rutas_lista69b.router,
    rutas_bitacora.router,
    rutas_documentos.router,
    rutas_busqueda.router,
    rutas_asistente.router,
    rutas_propuestas.router,
)


def _montar_estaticos(app: FastAPI, carpeta: Path) -> None:
    """Sirve el frontend construido; cualquier ruta que no sea archivo devuelve index.html (rutas del cliente)."""
    raiz = carpeta.resolve()
    indice = raiz / "index.html"

    @app.get("/{ruta:path}", include_in_schema=False)
    def estatico(ruta: str) -> Response:
        if ruta == "api" or ruta.startswith("api/"):
            raise ErrorApi(404, "RUTA_NO_ENCONTRADA", "La ruta solicitada no existe.")
        candidato = (raiz / ruta).resolve()
        # Primero la contención: así nunca se consulta el disco (ni rutas de red) fuera de la carpeta.
        if ruta and candidato.is_relative_to(raiz) and candidato.is_file():
            return FileResponse(candidato)
        return FileResponse(indice, headers={"Cache-Control": "no-cache"})


def crear_app(config: Settings | None = None) -> FastAPI:
    config = config or obtener_config()
    config.validar_para_arranque()
    app = FastAPI(
        title="Cotejo",
        description="Asistente de cuentas por pagar: CFDI 4.0, adeudos, documentos y propuestas de pago.",
        version="0.1.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )
    app.state.config = config
    registrar_manejadores(app)
    for router in ROUTERS:
        app.include_router(router, prefix="/api")

    carpeta = Path(config.static_dir)
    if (carpeta / "index.html").is_file():
        _montar_estaticos(app, carpeta)

    # El último agregado es el más externo: las cabeceras se aplican también a los rechazos de CSRF y tamaño.
    app.add_middleware(CapturarErrores)
    app.add_middleware(ExigirCabeceraCsrf)
    app.add_middleware(LimiteTamanoPeticion, limite_bytes=MB_POR_PETICION * 1024 * 1024)
    app.add_middleware(CabecerasSeguridad, frame_ancestors=config.frame_ancestors, hsts=config.cookie_segura)
    return app


app = crear_app()
