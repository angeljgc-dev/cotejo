"""Lista 69-B del SAT: carga del CSV (rol aprobador) y estado de la lista vigente."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from cotejo import bitacora, lista_69b
from cotejo.api.dependencias import SesionDb, UsuarioActual, requiere_rol
from cotejo.api.errores import ErrorApi
from cotejo.modelos import Carga, CargaArchivo, Usuario
from cotejo.seguridad.archivos import EXTENSIONES_LISTA_69B, ArchivoRechazado, leer_subida

router = APIRouter(tags=["lista_69b"])


class ResultadoLista(BaseModel):
    registros: int
    por_situacion: dict[str, int]
    proveedores_afectados: int
    alertas_creadas: int
    alertas_cerradas: int
    cargado_en: datetime


class EstadoListaSalida(BaseModel):
    cargada: bool
    registros: int
    cargado_en: datetime | None
    archivo: str | None


@router.post("/lista-69b")
async def cargar_lista(
    sesion: SesionDb,
    usuario: Annotated[Usuario, Depends(requiere_rol("aprobador"))],
    archivo: Annotated[UploadFile | None, File()] = None,
) -> ResultadoLista:
    if archivo is None:
        raise ErrorApi(422, "SIN_ARCHIVOS", "Selecciona el archivo CSV de la lista 69-B.")
    try:
        leido = await leer_subida(archivo, EXTENSIONES_LISTA_69B, lista_69b.MAX_BYTES)
    except ArchivoRechazado as exc:
        estado = 413 if exc.codigo == "ARCHIVO_DEMASIADO_GRANDE" else 422
        raise ErrorApi(estado, exc.codigo, exc.mensaje) from exc

    def _procesar() -> ResultadoLista:
        try:
            resumen = lista_69b.cargar(sesion, leido.contenido, archivo=leido.nombre, ahora=datetime.now(UTC))
        except lista_69b.CsvInvalido as exc:
            raise ErrorApi(422, "CSV_INVALIDO", exc.mensaje, {"linea": exc.linea, "columna": exc.columna}) from exc
        carga = Carga(usuario_id=usuario.id, tipo="lista_69b")
        sesion.add(carga)
        sesion.flush()
        sesion.add(
            CargaArchivo(
                carga_id=carga.id,
                nombre_archivo=leido.nombre,
                sha256=hashlib.sha256(leido.contenido).hexdigest(),
                tamano_bytes=len(leido.contenido),
                resultado="aceptada",
            )
        )
        bitacora.registrar(
            sesion,
            usuario_id=usuario.id,
            accion="LISTA_69B_CARGADA",
            entidad="lista_69b",
            entidad_id=carga.id,
            detalle={
                "archivo": leido.nombre,
                "registros": resumen.registros,
                "alertas_creadas": resumen.alertas_creadas,
                "alertas_cerradas": resumen.alertas_cerradas,
            },
        )
        return ResultadoLista(
            registros=resumen.registros,
            por_situacion=resumen.por_situacion,
            proveedores_afectados=resumen.proveedores_afectados,
            alertas_creadas=resumen.alertas_creadas,
            alertas_cerradas=resumen.alertas_cerradas,
            cargado_en=resumen.cargado_en,
        )

    return await run_in_threadpool(_procesar)


@router.get("/lista-69b/estado")
def estado_lista(sesion: SesionDb, _usuario: UsuarioActual) -> EstadoListaSalida:
    estado = lista_69b.estado(sesion)
    return EstadoListaSalida(
        cargada=estado.cargada, registros=estado.registros, cargado_en=estado.cargado_en, archivo=estado.archivo
    )
