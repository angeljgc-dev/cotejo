"""Modelos de respuesta de las rutas de cuentas por pagar que no salen directo de `consultas`."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, PlainSerializer
from sqlalchemy import select
from sqlalchemy.orm import Session

from cotejo.cxp.consultas import FacturaResumen, ProveedorConAdeudo, SaldoMoneda
from cotejo.dinero import Importe
from cotejo.modelos import Alerta, Usuario


def _sin_ceros(valor: Decimal) -> str:
    """Número sin los ceros de relleno que agrega la columna ni notación científica: "2", "1.5", "0.16"."""
    normal = valor.normalize()
    if normal == normal.to_integral_value():
        return format(normal.quantize(Decimal(1)), "f")
    return format(normal, "f")


def _importe_xml(valor: Decimal) -> str:
    """Importe de concepto con al menos dos decimales y hasta los seis que admite el SAT: "2000.00", "0.125"."""
    texto = _sin_ceros(valor)
    entero, _, decimales = texto.partition(".")
    return f"{entero}.{decimales.ljust(2, '0')}"


# Cantidades, tasas e importes de conceptos: la base guarda 6 decimales; se devuelven sin los ceros de relleno.
DecimalXml = Annotated[Decimal, PlainSerializer(_sin_ceros, return_type=str, when_used="json")]
ImporteXml = Annotated[Decimal, PlainSerializer(_importe_xml, return_type=str, when_used="json")]
Rol = Literal["capturista", "aprobador"]


class _Modelo(BaseModel):
    model_config = ConfigDict(frozen=True)


class UsuarioCorto(_Modelo):
    id: int
    nombre: str
    rol: Rol

    @classmethod
    def de(cls, usuario: Usuario) -> UsuarioCorto:
        return cls(
            id=usuario.id, nombre=usuario.nombre, rol="aprobador" if usuario.rol == "aprobador" else "capturista"
        )


class AlertaSalida(_Modelo):
    id: int
    factura_id: int | None
    proveedor_id: int | None
    codigo: str
    severidad: Literal["alerta", "bloqueante"]
    mensaje: str
    detalle: dict[str, object]
    factura_relacionada_id: int | None
    estado: Literal["abierta", "resuelta"]
    creada_en: datetime
    resuelta_por: UsuarioCorto | None
    resuelta_en: datetime | None
    nota_resolucion: str | None


def alertas_salida(sesion: Session, alertas: list[Alerta]) -> list[AlertaSalida]:
    """Convierte alertas a la forma del contrato con una sola consulta para los usuarios que las resolvieron."""
    ids = {a.resuelta_por for a in alertas if a.resuelta_por is not None}
    usuarios = {u.id: u for u in sesion.scalars(select(Usuario).where(Usuario.id.in_(ids)))} if ids else {}
    salida = []
    for a in alertas:
        quien = usuarios.get(a.resuelta_por) if a.resuelta_por is not None else None
        salida.append(
            AlertaSalida.model_validate(
                {
                    "id": a.id,
                    "factura_id": a.factura_id,
                    "proveedor_id": a.proveedor_id,
                    "codigo": a.codigo,
                    "severidad": a.severidad,
                    "mensaje": a.mensaje,
                    "detalle": a.detalle,
                    "factura_relacionada_id": a.factura_relacionada_id,
                    "estado": a.estado,
                    "creada_en": a.creado_en,
                    "resuelta_por": UsuarioCorto.de(quien) if quien is not None else None,
                    "resuelta_en": a.resuelta_en,
                    "nota_resolucion": a.nota_resolucion,
                }
            )
        )
    return salida


class PaginaAlertas(_Modelo):
    elementos: list[AlertaSalida]
    total: int
    pagina: int
    por_pagina: int


class Receptor(_Modelo):
    rfc: str
    nombre: str
    uso_cfdi: str


class ConceptoSalida(_Modelo):
    orden: int
    clave_prod_serv: str
    cantidad: DecimalXml
    clave_unidad: str
    unidad: str | None
    descripcion: str
    valor_unitario: ImporteXml
    importe: ImporteXml
    descuento: ImporteXml | None


class ImpuestoSalida(_Modelo):
    clase: str
    impuesto: str
    tipo_factor: str | None
    tasa_o_cuota: DecimalXml | None
    base: ImporteXml | None
    importe: ImporteXml | None


class RelacionadoSalida(_Modelo):
    uuid: str
    tipo_relacion: str
    factura_id: int | None


class AplicacionSalida(_Modelo):
    id: int
    origen: Literal["complemento_pago", "nota_credito", "pago_aprobado"]
    importe: Importe
    importe_solicitado: Importe
    fecha: date
    origen_factura_id: int | None
    propuesta_id: int | None
    num_parcialidad: int | None


class CargaCorta(_Modelo):
    id: int
    creado_en: datetime
    usuario: UsuarioCorto


class FacturaDetalle(FacturaResumen):
    version: str
    fecha_timbrado: datetime
    receptor: Receptor
    subtotal: Importe
    descuento: Importe
    total_impuestos_trasladados: Importe | None
    total_impuestos_retenidos: Importe | None
    impuestos_locales_trasladados: Importe | None
    impuestos_locales_retenidos: Importe | None
    metodo_pago: str | None
    forma_pago: str | None
    condiciones_pago: str | None
    exportacion: str
    lugar_expedicion: str
    conceptos: list[ConceptoSalida]
    impuestos: list[ImpuestoSalida]
    relacionados: list[RelacionadoSalida]
    aplicaciones: list[AplicacionSalida]
    alertas: list[AlertaSalida]
    carga: CargaCorta


class DocumentoCorto(_Modelo):
    id: int
    nombre: str
    tipo: str
    estado: str


class ProveedorDetalle(ProveedorConAdeudo):
    adeudo_por_moneda: list[SaldoMoneda]
    documentos: list[DocumentoCorto]
