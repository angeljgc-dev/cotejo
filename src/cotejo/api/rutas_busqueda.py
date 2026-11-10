"""Rutas de búsqueda. Se montan en app.py bajo /api; las rutas se declaran sin el prefijo /api."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from cotejo.api.dependencias import ConfigApp, SesionDb, UsuarioActual
from cotejo.documentos.busqueda import buscar
from cotejo.documentos.contrato import RespuestaBusqueda, ResultadoBusqueda
from cotejo.documentos.embeddings import obtener_embedder

router = APIRouter(tags=["busqueda"])


@router.get("/busqueda")
def buscar_fragmentos(
    sesion: SesionDb,
    config: ConfigApp,
    _usuario: UsuarioActual,
    q: Annotated[str, Query(min_length=2, max_length=300)],
    proveedor_id: int | None = None,
    k: Annotated[int, Query(ge=1, le=10)] = 5,
) -> RespuestaBusqueda:
    """Búsqueda híbrida en los documentos: por significado y por palabras exactas."""
    hallazgos = buscar(
        sesion, q, embedder=obtener_embedder(config), modo=config.busqueda_modo, proveedor_id=proveedor_id, k=k
    )
    return RespuestaBusqueda(
        resultados=[
            ResultadoBusqueda(
                fragmento_id=h.fragmento_id,
                documento_id=h.documento_id,
                documento=h.documento,
                pagina=h.pagina,
                texto=h.texto,
                puntaje=h.puntaje,
                fuentes=list(h.fuentes),
            )
            for h in hallazgos
        ]
    )
