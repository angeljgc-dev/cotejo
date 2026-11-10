"""Modelos de respuesta de documentos, fragmentos y búsqueda (contrato de la API)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from cotejo.cxp.consultas import ProveedorCorto
from cotejo.modelos import Usuario


class UsuarioCorto(BaseModel):
    id: int
    nombre: str
    rol: Literal["capturista", "aprobador"]

    @classmethod
    def de(cls, usuario: Usuario) -> UsuarioCorto:
        return cls(
            id=usuario.id, nombre=usuario.nombre, rol="aprobador" if usuario.rol == "aprobador" else "capturista"
        )


class Motivo(BaseModel):
    codigo: str
    mensaje: str
    severidad: Literal["rechazo", "alerta", "bloqueante"]


class ResultadoDocumento(BaseModel):
    nombre: str
    resultado: Literal["indexado", "sin_texto", "rechazado", "duplicado"]
    documento_id: int | None = None
    paginas: int | None = None
    fragmentos: int | None = None
    explicacion: str | None = None
    motivos: list[Motivo] = []


class DocumentoResumen(BaseModel):
    id: int
    nombre: str
    tipo: str
    proveedor: ProveedorCorto | None
    paginas: int
    fragmentos: int
    estado: Literal["indexado", "sin_texto"]
    explicacion: str | None
    subido_por: UsuarioCorto
    creado_en: datetime


class DocumentoDetalle(DocumentoResumen):
    paginas_con_texto: list[int]


class PaginaDocumentos(BaseModel):
    elementos: list[DocumentoResumen]
    total: int
    pagina: int
    por_pagina: int


class DocumentoDeFragmento(BaseModel):
    id: int
    nombre: str


class FragmentoSalida(BaseModel):
    id: int
    documento: DocumentoDeFragmento
    pagina: int
    orden: int
    texto: str
    anterior_id: int | None
    siguiente_id: int | None


class ResultadoBusqueda(BaseModel):
    fragmento_id: int
    documento_id: int
    documento: str
    pagina: int
    texto: str
    puntaje: float
    fuentes: list[Literal["vector", "texto"]]


class RespuestaBusqueda(BaseModel):
    resultados: list[ResultadoBusqueda]
