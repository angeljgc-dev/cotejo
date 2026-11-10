"""Facturas: lista con filtros, detalle completo y descarga del XML."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Response
from sqlalchemy import or_, select

from cotejo.api.dependencias import ConfigApp, IdRuta, SesionDb, UsuarioActual
from cotejo.api.errores import ErrorApi
from cotejo.cxp import consultas
from cotejo.cxp.consultas import FiltrosFacturas, PaginaFacturas
from cotejo.cxp.contrato import FacturaDetalle, UsuarioCorto, alertas_salida
from cotejo.fechas import hoy
from cotejo.modelos import Alerta, Aplicacion, Carga, CargaArchivo, Factura, RenglonPropuesta, Usuario

router = APIRouter(tags=["facturas"])


def _no_encontrada() -> ErrorApi:
    return ErrorApi(404, "FACTURA_NO_ENCONTRADA", "La factura no existe.")


@router.get("/facturas")
def listar_facturas(
    sesion: SesionDb, config: ConfigApp, _usuario: UsuarioActual, filtros: Annotated[FiltrosFacturas, Query()]
) -> PaginaFacturas:
    return consultas.listar_facturas(sesion, filtros, hoy(config))


@router.get("/facturas/{factura_id}")
def ver_factura(factura_id: IdRuta, sesion: SesionDb, config: ConfigApp, _usuario: UsuarioActual) -> FacturaDetalle:
    resumen = consultas.resumen_factura(sesion, factura_id, hoy(config))
    factura = sesion.get(Factura, factura_id)
    if resumen is None or factura is None:
        raise _no_encontrada()

    uuids = [r.uuid_relacionado for r in factura.relacionados]
    ids_por_uuid: dict[str, int] = (
        dict(sesion.execute(select(Factura.uuid, Factura.id).where(Factura.uuid.in_(uuids))).all()) if uuids else {}
    )
    aplicaciones = sesion.execute(
        select(Aplicacion, RenglonPropuesta.propuesta_id)
        .outerjoin(RenglonPropuesta, RenglonPropuesta.id == Aplicacion.renglon_propuesta_id)
        .where(or_(Aplicacion.factura_id == factura_id, Aplicacion.origen_factura_id == factura_id))
        .order_by(Aplicacion.fecha, Aplicacion.id)
    ).all()
    # Las alertas del proveedor (lista 69-B) también se muestran en cada una de sus facturas.
    alertas = list(
        sesion.scalars(
            select(Alerta)
            .where(
                or_(
                    Alerta.factura_id == factura_id,
                    (Alerta.factura_id.is_(None)) & (Alerta.proveedor_id == factura.proveedor_id),
                )
            )
            .order_by(Alerta.id)
        )
    )
    carga, quien = sesion.execute(
        select(Carga, Usuario)
        .join(CargaArchivo, CargaArchivo.carga_id == Carga.id)
        .join(Usuario, Usuario.id == Carga.usuario_id)
        .where(CargaArchivo.id == factura.carga_archivo_id)
    ).one()

    return FacturaDetalle.model_validate(
        {
            **resumen.model_dump(),
            "version": factura.version,
            "fecha_timbrado": factura.fecha_timbrado,
            "receptor": {
                "rfc": factura.receptor_rfc,
                "nombre": factura.receptor_nombre,
                "uso_cfdi": factura.receptor_uso_cfdi,
            },
            "subtotal": factura.subtotal,
            "descuento": factura.descuento,
            "total_impuestos_trasladados": factura.total_impuestos_trasladados,
            "total_impuestos_retenidos": factura.total_impuestos_retenidos,
            "impuestos_locales_trasladados": factura.impuestos_locales_trasladados,
            "impuestos_locales_retenidos": factura.impuestos_locales_retenidos,
            "metodo_pago": factura.metodo_pago,
            "forma_pago": factura.forma_pago,
            "condiciones_pago": factura.condiciones_pago,
            "exportacion": factura.exportacion,
            "lugar_expedicion": factura.lugar_expedicion,
            "conceptos": [
                {
                    "orden": c.orden,
                    "clave_prod_serv": c.clave_prod_serv,
                    "cantidad": c.cantidad,
                    "clave_unidad": c.clave_unidad,
                    "unidad": c.unidad,
                    "descripcion": c.descripcion,
                    "valor_unitario": c.valor_unitario,
                    "importe": c.importe,
                    "descuento": c.descuento,
                }
                for c in sorted(factura.conceptos, key=lambda c: c.orden)
            ],
            "impuestos": [
                {
                    "clase": i.clase,
                    "impuesto": i.impuesto,
                    "tipo_factor": i.tipo_factor,
                    "tasa_o_cuota": i.tasa_o_cuota,
                    "base": i.base,
                    "importe": i.importe,
                }
                for i in factura.impuestos
            ],
            "relacionados": [
                {
                    "uuid": r.uuid_relacionado,
                    "tipo_relacion": r.tipo_relacion,
                    "factura_id": ids_por_uuid.get(r.uuid_relacionado),
                }
                for r in factura.relacionados
            ],
            "aplicaciones": [
                {
                    "id": a.id,
                    "origen": a.origen,
                    "importe": a.importe,
                    "importe_solicitado": a.importe_solicitado,
                    "fecha": a.fecha,
                    "origen_factura_id": a.origen_factura_id,
                    "propuesta_id": propuesta_id,
                    "num_parcialidad": a.num_parcialidad,
                }
                for a, propuesta_id in aplicaciones
            ],
            "alertas": alertas_salida(sesion, alertas),
            "carga": {"id": carga.id, "creado_en": carga.creado_en, "usuario": UsuarioCorto.de(quien)},
        }
    )


@router.get("/facturas/{factura_id}/xml")
def descargar_xml(factura_id: IdRuta, sesion: SesionDb, _usuario: UsuarioActual) -> Response:
    fila = sesion.execute(select(Factura.uuid, Factura.xml_original).where(Factura.id == factura_id)).one_or_none()
    if fila is None:
        raise _no_encontrada()
    uuid, xml = fila
    return Response(
        content=xml.encode("utf-8"),
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{uuid}.xml"'},
    )
