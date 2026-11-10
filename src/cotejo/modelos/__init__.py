"""Modelo de datos. Importar este paquete registra todas las tablas en `Base.metadata`."""

from cotejo.modelos.asistente import Conversacion, MensajeChat, Propuesta, RenglonPropuesta
from cotejo.modelos.base import Base
from cotejo.modelos.cxp import (
    Alerta,
    Aplicacion,
    CfdiRelacionado,
    Concepto,
    DoctoPago,
    Factura,
    FacturaImpuesto,
    Lista69b,
    Proveedor,
)
from cotejo.modelos.documentos import DIMENSION_EMBEDDING, Documento, Fragmento
from cotejo.modelos.operacion import ACCIONES_BITACORA, Bitacora, Carga, CargaArchivo, CuotaUso
from cotejo.modelos.usuarios import ROLES, Usuario

__all__ = [
    "ACCIONES_BITACORA",
    "DIMENSION_EMBEDDING",
    "ROLES",
    "Alerta",
    "Aplicacion",
    "Base",
    "Bitacora",
    "Carga",
    "CargaArchivo",
    "CfdiRelacionado",
    "Concepto",
    "Conversacion",
    "CuotaUso",
    "DoctoPago",
    "Documento",
    "Factura",
    "FacturaImpuesto",
    "Fragmento",
    "Lista69b",
    "MensajeChat",
    "Propuesta",
    "Proveedor",
    "RenglonPropuesta",
    "Usuario",
]
