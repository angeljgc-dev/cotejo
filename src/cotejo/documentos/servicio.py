"""Carga de documentos: indexa cada archivo por separado y deja la carga en la bitácora (C1, C3, D7)."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cotejo import bitacora
from cotejo.cxp.consultas import ProveedorCorto
from cotejo.documentos.contrato import (
    DocumentoDetalle,
    DocumentoResumen,
    FragmentoSalida,
    Motivo,
    ResultadoDocumento,
    UsuarioCorto,
)
from cotejo.documentos.embeddings import Embedder
from cotejo.documentos.extraccion import DocumentoRechazado
from cotejo.documentos.indexado import indexar_documento
from cotejo.modelos import Carga, CargaArchivo, Documento, Fragmento, Proveedor, Usuario
from cotejo.seguridad.archivos import ArchivoRechazado, ArchivoSubido

_log = logging.getLogger("cotejo.documentos")

MAX_ARCHIVOS = 10
# Resultado del contrato -> valor permitido en carga_archivos.resultado.
_RESULTADO_EN_CARGA = {
    "indexado": "indexado",
    "sin_texto": "sin_texto",
    "rechazado": "rechazada",
    "duplicado": "duplicada",
}


@dataclass(frozen=True)
class ArchivoPendiente:
    """Un archivo de la carga: leído correctamente o rechazado antes de leerse (extensión, tamaño, firma)."""

    nombre: str
    archivo: ArchivoSubido | None = None
    rechazo: ArchivoRechazado | None = None


def _indexar_uno(
    sesion: Session, archivo: ArchivoSubido, proveedor_id: int | None, usuario_id: int, embedder: Embedder
) -> ResultadoDocumento:
    try:
        # Savepoint por archivo: un archivo que falla no se lleva a los demás.
        with sesion.begin_nested():
            indexado = indexar_documento(
                sesion,
                nombre=archivo.nombre,
                tipo=archivo.extension.removeprefix("."),
                contenido=archivo.contenido,
                sha256=archivo.sha256,
                proveedor_id=proveedor_id,
                usuario_id=usuario_id,
                embedder=embedder,
            )
    except DocumentoRechazado as exc:
        return ResultadoDocumento(
            nombre=archivo.nombre,
            resultado="rechazado",
            motivos=[Motivo(codigo=exc.codigo, mensaje=exc.mensaje, severidad="rechazo")],
        )
    except IntegrityError:
        # Otra petición subió el mismo archivo entre la consulta y el INSERT: ya existe.
        existente = sesion.scalar(select(Documento).where(Documento.sha256 == archivo.sha256))
        if existente is None:
            raise
        return ResultadoDocumento(
            nombre=archivo.nombre,
            resultado="duplicado",
            documento_id=existente.id,
            paginas=existente.paginas,
            explicacion="Este archivo ya estaba cargado.",
        )
    except Exception:
        # Lo que falle con un archivo (el savepoint ya se deshizo) no debe perder los demás de la misma carga.
        _log.exception("No se pudo indexar el documento %s.", archivo.nombre)
        return ResultadoDocumento(
            nombre=archivo.nombre,
            resultado="rechazado",
            motivos=[
                Motivo(
                    codigo="ERROR_AL_PROCESAR",
                    mensaje="No se pudo procesar el archivo. Intenta de nuevo; si se repite, revisa el archivo.",
                    severidad="rechazo",
                )
            ],
        )
    documento = indexado.documento
    explicacion = documento.explicacion
    if indexado.resultado == "duplicado":
        explicacion = f"Este archivo ya estaba cargado como «{documento.nombre}»."
    return ResultadoDocumento(
        nombre=archivo.nombre,
        resultado=indexado.resultado,
        documento_id=documento.id,
        paginas=documento.paginas,
        fragmentos=indexado.fragmentos,
        explicacion=explicacion,
    )


def cargar_documentos(
    sesion: Session,
    *,
    pendientes: Sequence[ArchivoPendiente],
    proveedor_id: int | None,
    usuario: Usuario,
    embedder: Embedder,
) -> list[ResultadoDocumento]:
    """Procesa la carga completa en la transacción en curso y la registra en bitácora. No hace commit."""
    carga = Carga(usuario_id=usuario.id, tipo="documento")
    sesion.add(carga)
    sesion.flush()
    resultados: list[ResultadoDocumento] = []
    for pendiente in pendientes:
        if pendiente.archivo is None:
            rechazo = pendiente.rechazo
            codigo = rechazo.codigo if rechazo else "ARCHIVO_INVALIDO"
            mensaje = rechazo.mensaje if rechazo else "El archivo no se pudo leer."
            resultados.append(
                ResultadoDocumento(
                    nombre=pendiente.nombre,
                    resultado="rechazado",
                    motivos=[Motivo(codigo=codigo, mensaje=mensaje, severidad="rechazo")],
                )
            )
            continue
        resultado = _indexar_uno(sesion, pendiente.archivo, proveedor_id, usuario.id, embedder)
        resultados.append(resultado)
        sesion.add(
            CargaArchivo(
                carga_id=carga.id,
                nombre_archivo=pendiente.archivo.nombre,
                sha256=pendiente.archivo.sha256,
                tamano_bytes=len(pendiente.archivo.contenido),
                resultado=_RESULTADO_EN_CARGA[resultado.resultado],
                motivos=[m.model_dump() for m in resultado.motivos],
                documento_id=resultado.documento_id,
            )
        )
    bitacora.registrar(
        sesion,
        usuario_id=usuario.id,
        accion="CARGA_DOCUMENTO",
        entidad="carga",
        entidad_id=carga.id,
        detalle={
            "proveedor_id": proveedor_id,
            "archivos": [
                {"nombre": r.nombre, "resultado": r.resultado, "documento_id": r.documento_id} for r in resultados
            ],
        },
    )
    sesion.flush()
    return resultados


def _resumen(sesion: Session, documento: Documento, fragmentos: int) -> DocumentoResumen:
    proveedor = sesion.get(Proveedor, documento.proveedor_id) if documento.proveedor_id is not None else None
    autor = sesion.get_one(Usuario, documento.subido_por)
    return DocumentoResumen(
        id=documento.id,
        nombre=documento.nombre,
        tipo=documento.tipo,
        proveedor=ProveedorCorto(id=proveedor.id, rfc=proveedor.rfc, nombre=proveedor.nombre) if proveedor else None,
        paginas=documento.paginas,
        fragmentos=fragmentos,
        estado="sin_texto" if documento.estado == "sin_texto" else "indexado",
        explicacion=documento.explicacion,
        subido_por=UsuarioCorto.de(autor),
        creado_en=documento.creado_en,
    )


def listar_documentos(
    sesion: Session, *, proveedor_id: int | None, pagina: int, por_pagina: int
) -> tuple[list[DocumentoResumen], int]:
    conteo = select(Fragmento.documento_id, func.count().label("n")).group_by(Fragmento.documento_id).subquery()
    base = select(Documento, func.coalesce(conteo.c.n, 0)).outerjoin(conteo, conteo.c.documento_id == Documento.id)
    total_q = select(func.count()).select_from(Documento)
    if proveedor_id is not None:
        base = base.where(Documento.proveedor_id == proveedor_id)
        total_q = total_q.where(Documento.proveedor_id == proveedor_id)
    filas = sesion.execute(
        base.order_by(Documento.creado_en.desc(), Documento.id.desc())
        .limit(por_pagina)
        .offset((pagina - 1) * por_pagina)
    ).all()
    return [_resumen(sesion, documento, int(n)) for documento, n in filas], sesion.scalar(total_q) or 0


def detalle_documento(sesion: Session, documento_id: int) -> DocumentoDetalle | None:
    documento = sesion.get(Documento, documento_id)
    if documento is None:
        return None
    paginas = list(
        sesion.scalars(
            select(Fragmento.pagina).where(Fragmento.documento_id == documento_id).distinct().order_by(Fragmento.pagina)
        )
    )
    fragmentos = sesion.scalar(
        select(func.count()).select_from(Fragmento).where(Fragmento.documento_id == documento_id)
    )
    resumen = _resumen(sesion, documento, fragmentos or 0)
    return DocumentoDetalle(**resumen.model_dump(), paginas_con_texto=paginas)


def fragmento_con_vecinos(sesion: Session, fragmento_id: int) -> FragmentoSalida | None:
    """El fragmento que abre una cita, con los ids del anterior y el siguiente para leer el contexto."""
    fila = sesion.execute(
        select(
            Fragmento.id, Fragmento.documento_id, Fragmento.pagina, Fragmento.orden, Fragmento.texto, Documento.nombre
        )
        .join(Documento, Documento.id == Fragmento.documento_id)
        .where(Fragmento.id == fragmento_id)
    ).one_or_none()
    if fila is None:
        return None
    anterior = sesion.scalar(
        select(Fragmento.id)
        .where(Fragmento.documento_id == fila.documento_id, Fragmento.orden < fila.orden)
        .order_by(Fragmento.orden.desc())
        .limit(1)
    )
    siguiente = sesion.scalar(
        select(Fragmento.id)
        .where(Fragmento.documento_id == fila.documento_id, Fragmento.orden > fila.orden)
        .order_by(Fragmento.orden)
        .limit(1)
    )
    return FragmentoSalida(
        id=fila.id,
        documento={"id": fila.documento_id, "nombre": fila.nombre},
        pagina=fila.pagina,
        orden=fila.orden,
        texto=fila.texto,
        anterior_id=anterior,
        siguiente_id=siguiente,
    )
