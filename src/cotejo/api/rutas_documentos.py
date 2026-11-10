"""Rutas de documentos. Se montan en app.py bajo /api; las rutas se declaran sin el prefijo /api."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from starlette.concurrency import run_in_threadpool

from cotejo.api.dependencias import ConfigApp, SesionDb, UsuarioActual, VisitanteActual, requiere_rol
from cotejo.api.errores import ErrorApi
from cotejo.config import MB_POR_DOCUMENTO
from cotejo.documentos import servicio
from cotejo.documentos.contrato import DocumentoDetalle, FragmentoSalida, PaginaDocumentos, ResultadoDocumento
from cotejo.documentos.embeddings import obtener_embedder
from cotejo.fechas import hoy
from cotejo.modelos import Proveedor, Usuario
from cotejo.seguridad import cuotas
from cotejo.seguridad.archivos import EXTENSIONES_DOCUMENTO, ArchivoRechazado, leer_subida, nombre_para_mostrar

router = APIRouter(tags=["documentos"])


@router.post("/documentos")
async def subir_documentos(
    sesion: SesionDb,
    config: ConfigApp,
    visitante: VisitanteActual,
    usuario: Annotated[Usuario, Depends(requiere_rol("capturista"))],
    archivos: Annotated[list[UploadFile], File()],
    proveedor_id: Annotated[int | None, Form()] = None,
) -> list[ResultadoDocumento]:
    """Indexa contratos y políticas (PDF, TXT o MD). Cada archivo recibe su propio resultado."""
    if len(archivos) > servicio.MAX_ARCHIVOS:
        raise ErrorApi(
            422,
            "DEMASIADOS_ARCHIVOS",
            f"Sube como máximo {servicio.MAX_ARCHIVOS} documentos por carga.",
            {"maximo": servicio.MAX_ARCHIVOS, "recibidos": len(archivos)},
        )
    pendientes: list[servicio.ArchivoPendiente] = []
    for archivo in archivos:
        try:
            leido = await leer_subida(archivo, EXTENSIONES_DOCUMENTO, MB_POR_DOCUMENTO * 1024 * 1024)
            pendientes.append(servicio.ArchivoPendiente(nombre=leido.nombre, archivo=leido))
        except ArchivoRechazado as exc:
            nombre = exc.nombre or nombre_para_mostrar(archivo.filename)
            pendientes.append(servicio.ArchivoPendiente(nombre=nombre, rechazo=exc))

    def _procesar() -> list[ResultadoDocumento]:
        if proveedor_id is not None and sesion.get(Proveedor, proveedor_id) is None:
            raise ErrorApi(422, "PROVEEDOR_NO_ENCONTRADO", "El proveedor indicado no existe.")
        if config.demo_habilitada:
            dia = hoy(config)
            clave = f"carga:v:{visitante.visitante}"
            try:
                for _ in pendientes:
                    cuotas.consumir(sesion, clave, config.cargas_limite_visitante_dia, dia)
            except cuotas.CuotaAgotada as exc:
                raise ErrorApi(
                    429,
                    "LIMITE_CARGAS",
                    "Llegaste al límite diario de archivos de la demostración. Vuelve a intentarlo mañana.",
                    exc.detalle(config.zona_horaria),
                ) from exc
        return servicio.cargar_documentos(
            sesion,
            pendientes=pendientes,
            proveedor_id=proveedor_id,
            usuario=usuario,
            embedder=obtener_embedder(config),
        )

    # Extraer texto y calcular vectores es trabajo de CPU: fuera del bucle de eventos.
    return await run_in_threadpool(_procesar)


@router.get("/documentos")
def listar_documentos(
    sesion: SesionDb,
    _usuario: UsuarioActual,
    proveedor_id: int | None = None,
    pagina: Annotated[int, Query(ge=1)] = 1,
    por_pagina: Annotated[int, Query(ge=1, le=100)] = 25,
) -> PaginaDocumentos:
    elementos, total = servicio.listar_documentos(
        sesion, proveedor_id=proveedor_id, pagina=pagina, por_pagina=por_pagina
    )
    return PaginaDocumentos(elementos=elementos, total=total, pagina=pagina, por_pagina=por_pagina)


@router.get("/documentos/{documento_id}")
def ver_documento(documento_id: int, sesion: SesionDb, _usuario: UsuarioActual) -> DocumentoDetalle:
    detalle = servicio.detalle_documento(sesion, documento_id)
    if detalle is None:
        raise ErrorApi(404, "DOCUMENTO_NO_ENCONTRADO", "El documento no existe.")
    return detalle


@router.get("/fragmentos/{fragmento_id}")
def ver_fragmento(fragmento_id: int, sesion: SesionDb, _usuario: UsuarioActual) -> FragmentoSalida:
    """Lo que abre una cita del asistente: el fragmento con su documento, página y vecinos."""
    fragmento = servicio.fragmento_con_vecinos(sesion, fragmento_id)
    if fragmento is None:
        raise ErrorApi(404, "FRAGMENTO_NO_ENCONTRADO", "El fragmento citado ya no existe.")
    return fragmento
