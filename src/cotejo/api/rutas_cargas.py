"""Carga de CFDI. Un archivo malo nunca hace fallar la petición completa: cada uno recibe su resultado."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from cotejo.api.dependencias import ConfigApp, SesionDb, VisitanteActual, requiere_rol
from cotejo.api.errores import ErrorApi
from cotejo.cfdi import codigos
from cotejo.config import ARCHIVOS_POR_CARGA, MB_POR_XML
from cotejo.fechas import ahora_local, hoy
from cotejo.ingesta.servicio import ArchivoNoLeido, ArchivoPorIngerir, ingerir_lote
from cotejo.modelos import Usuario
from cotejo.seguridad import cuotas
from cotejo.seguridad.archivos import EXTENSIONES_CFDI, ArchivoRechazado, leer_subida, nombre_para_mostrar

router = APIRouter(tags=["cargas"])


class MotivoSalida(BaseModel):
    codigo: str
    mensaje: str
    severidad: Literal["rechazo", "alerta", "bloqueante"]


class ArchivoSalida(BaseModel):
    nombre: str
    resultado: Literal["aceptada", "aceptada_con_alertas", "rechazada", "duplicada"]
    motivos: list[MotivoSalida]
    uuid: str | None
    factura_id: int | None
    tipo: Literal["I", "E", "P"] | None
    ya_existia: bool


class ResumenCarga(BaseModel):
    aceptadas: int
    con_alertas: int
    rechazadas: int
    duplicadas: int


class CargaSalida(BaseModel):
    carga_id: int
    archivos: list[ArchivoSalida]
    resumen: ResumenCarga


@router.post("/cargas/cfdi")
async def cargar_cfdi(
    sesion: SesionDb,
    config: ConfigApp,
    visitante: VisitanteActual,
    usuario: Annotated[Usuario, Depends(requiere_rol("capturista"))],
    archivos: Annotated[list[UploadFile] | None, File()] = None,
) -> CargaSalida:
    if not archivos:
        raise ErrorApi(422, "SIN_ARCHIVOS", "Selecciona al menos un archivo XML para cargar.")
    if len(archivos) > ARCHIVOS_POR_CARGA:
        raise ErrorApi(
            422,
            "DEMASIADOS_ARCHIVOS",
            f"Sube como máximo {ARCHIVOS_POR_CARGA} archivos por carga.",
            {"maximo": ARCHIVOS_POR_CARGA, "recibidos": len(archivos)},
        )
    entradas: list[ArchivoPorIngerir | ArchivoNoLeido] = []
    for archivo in archivos:
        try:
            leido = await leer_subida(archivo, EXTENSIONES_CFDI, MB_POR_XML * 1024 * 1024)
            entradas.append(ArchivoPorIngerir(nombre=leido.nombre, contenido=leido.contenido))
        except ArchivoRechazado as exc:
            nombre = exc.nombre or nombre_para_mostrar(archivo.filename)
            entradas.append(ArchivoNoLeido(nombre=nombre, motivo=codigos.rechazo(exc.codigo, exc.mensaje)))

    def _procesar() -> CargaSalida:
        if config.demo_habilitada:
            clave = f"carga:v:{visitante.visitante}"
            try:
                for _ in entradas:
                    cuotas.consumir(sesion, clave, config.cargas_limite_visitante_dia, hoy(config))
            except cuotas.CuotaAgotada as exc:
                raise ErrorApi(
                    429,
                    "LIMITE_CARGAS",
                    "Llegaste al límite diario de archivos de la demostración. Vuelve a intentarlo mañana.",
                    exc.detalle(config.zona_horaria),
                ) from exc
        resultado = ingerir_lote(
            sesion,
            usuario_id=usuario.id,
            entradas=entradas,
            empresa_rfc=config.empresa_rfc,
            ahora=ahora_local(config).replace(tzinfo=None),
        )
        return CargaSalida.model_validate(
            {
                "carga_id": resultado.carga_id,
                "archivos": [
                    {
                        "nombre": a.nombre,
                        "resultado": a.resultado,
                        "motivos": [m.a_json() for m in a.motivos],
                        "uuid": a.uuid,
                        "factura_id": a.factura_id,
                        "tipo": a.tipo,
                        "ya_existia": a.ya_existia,
                    }
                    for a in resultado.archivos
                ],
                "resumen": resultado.resumen,
            }
        )

    # Leer y validar XML es trabajo de CPU: fuera del bucle de eventos.
    return await run_in_threadpool(_procesar)
