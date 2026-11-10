"""Efecto de las notas de crédito (tipo E) y de los complementos de pago (tipo P) en el saldo de las facturas.

Un E o un P puede llegar antes que la factura a la que se refiere: queda en espera con una alerta y se aplica en
cuanto esa factura se registra. Todo pasa por `cxp.saldos.aplicar`, así que el saldo nunca queda negativo y volver
a procesar el mismo documento no aplica dos veces.

Reglas de alcance: un documento solo afecta facturas de su mismo emisor y en su misma moneda, y los documentos
cuyo receptor no es la empresa no se aplican (ya llevan su propia alerta bloqueante).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from cotejo.bitacora import a_json
from cotejo.cfdi import codigos
from cotejo.cfdi.codigos import Motivo
from cotejo.cfdi.reglas import RELACIONES_QUE_REDUCEN_SALDO, TOLERANCIA
from cotejo.cxp import alertas, saldos
from cotejo.dinero import cuantizar, texto
from cotejo.modelos import Alerta, Aplicacion, CfdiRelacionado, DoctoPago, Factura

NOTA_CIERRE_PENDIENTE = "Las facturas relacionadas ya están registradas."


def _referencia(factura: Factura) -> str:
    return " ".join(parte for parte in (factura.serie, factura.folio) if parte) or factura.uuid


def _facturas_por_uuid(sesion: Session, uuids: set[str]) -> dict[str, Factura]:
    if not uuids:
        return {}
    return {f.uuid: f for f in sesion.scalars(select(Factura).where(Factura.uuid.in_(uuids)))}


def _alerta_en_destino(
    sesion: Session, codigo: str, mensaje: str, destino: Factura, documento: Factura, detalle: dict[str, object]
) -> Motivo:
    alertas.abrir(
        sesion,
        codigo=codigo,
        severidad="alerta",
        mensaje=mensaje,
        factura_id=destino.id,
        detalle=detalle,
        factura_relacionada_id=documento.id,
    )
    return codigos.alerta(codigo, mensaje, detalle)


def _no_es_ingreso(sesion: Session, documento: Factura, destino: Factura) -> Motivo:
    tipos = {"E": "una nota de crédito", "P": "un complemento de pago"}
    mensaje = (
        f"El documento {_referencia(documento)} señala al comprobante {_referencia(destino)}, que es "
        f"{tipos.get(destino.tipo, 'otro documento')} y no una factura de ingreso. No se aplicó nada."
    )
    detalle: dict[str, object] = {"uuid_destino": destino.uuid, "tipo_destino": destino.tipo}
    alertas.abrir(
        sesion,
        codigo=codigos.DOCUMENTO_RELACIONADO_NO_ES_INGRESO,
        severidad="alerta",
        mensaje=mensaje,
        factura_id=documento.id,
        detalle=detalle,
        factura_relacionada_id=destino.id,
    )
    return codigos.alerta(codigos.DOCUMENTO_RELACIONADO_NO_ES_INGRESO, mensaje, detalle)


def _puede_afectar(sesion: Session, documento: Factura, destino: Factura, moneda: str) -> Motivo | None:
    """None si el documento puede aplicarse a la factura; si no, el motivo (y deja la alerta)."""
    if documento.proveedor_id != destino.proveedor_id:
        mensaje = (
            f"El documento {_referencia(documento)} señala a la factura {_referencia(destino)}, que es de otro "
            "emisor. No se aplicó."
        )
        detalle: dict[str, object] = {"uuid_destino": destino.uuid}
        alertas.abrir(
            sesion,
            codigo=codigos.DOCUMENTO_DE_OTRO_EMISOR,
            severidad="alerta",
            mensaje=mensaje,
            factura_id=documento.id,
            detalle=detalle,
            factura_relacionada_id=destino.id,
        )
        return codigos.alerta(codigos.DOCUMENTO_DE_OTRO_EMISOR, mensaje, detalle)
    if moneda != destino.moneda:
        return _alerta_en_destino(
            sesion,
            codigos.PAGO_MONEDA_DISTINTA,
            f"El documento {_referencia(documento)} viene en {moneda} y la factura {_referencia(destino)} está en "
            f"{destino.moneda}. No se aplicó: hay que registrarlo a mano.",
            destino,
            documento,
            {"moneda_documento": moneda, "moneda_factura": destino.moneda},
        )
    return None


def _aplicar(
    sesion: Session,
    *,
    documento: Factura,
    destino: Factura,
    origen: str,
    importe: Decimal,
    num_parcialidad: int | None,
    fecha: date,
    motivos: list[Motivo],
) -> Aplicacion | None:
    """Aplica y traduce el excedente a un motivo. La alerta la deja `saldos.aplicar`."""
    try:
        aplicacion = saldos.aplicar(
            sesion,
            factura_id=destino.id,
            importe=importe,
            origen=origen,
            fecha=fecha,
            origen_factura_id=documento.id,
            num_parcialidad=num_parcialidad,
        )
    except saldos.SinSaldo:
        motivos.append(
            codigos.alerta(
                codigos.PAGO_EXCEDE_SALDO,
                f"La factura {_referencia(destino)} ya no tenía saldo: no se aplicaron {texto(importe)} del "
                f"documento {_referencia(documento)}.",
                {"solicitado": importe, "aplicado": Decimal(0)},
            )
        )
        return None
    excedente = cuantizar(aplicacion.importe_solicitado - aplicacion.importe)
    if excedente > 0:
        motivos.append(
            codigos.alerta(
                codigos.PAGO_EXCEDE_SALDO,
                f"El documento {_referencia(documento)} pedía aplicar {texto(aplicacion.importe_solicitado)} a la "
                f"factura {_referencia(destino)} y solo se debían {texto(aplicacion.importe)}. El excedente de "
                f"{texto(excedente)} no se aplicó.",
                {"solicitado": aplicacion.importe_solicitado, "aplicado": aplicacion.importe, "excedente": excedente},
            )
        )
    return aplicacion


def _actualizar_pendiente(sesion: Session, documento: Factura, uuids_pendientes: list[str]) -> Motivo | None:
    """Abre, actualiza o cierra la alerta de documento relacionado pendiente según lo que falte por llegar."""
    abiertas = alertas.ids_abiertas(sesion, codigo=codigos.DOCUMENTO_RELACIONADO_PENDIENTE, factura_id=documento.id)
    if not uuids_pendientes:
        alertas.cerrar_por_sistema(sesion, abiertas, NOTA_CIERRE_PENDIENTE)
        return None
    cuantas = "la factura" if len(uuids_pendientes) == 1 else "las facturas"
    mensaje = (
        f"Este documento se refiere a {cuantas} {', '.join(uuids_pendientes)}, que todavía no se ha registrado. "
        "Se aplicará sola en cuanto llegue."
    )
    detalle: dict[str, object] = {"uuids_pendientes": uuids_pendientes}
    if abiertas:
        sesion.execute(update(Alerta).where(Alerta.id.in_(abiertas)).values(mensaje=mensaje, detalle=a_json(detalle)))
    else:
        alertas.abrir(
            sesion,
            codigo=codigos.DOCUMENTO_RELACIONADO_PENDIENTE,
            severidad="alerta",
            mensaje=mensaje,
            factura_id=documento.id,
            detalle=detalle,
        )
    return codigos.alerta(codigos.DOCUMENTO_RELACIONADO_PENDIENTE, mensaje, detalle)


def _objetivos_nota(sesion: Session, nota: Factura) -> list[str]:
    return list(
        sesion.scalars(
            select(CfdiRelacionado.uuid_relacionado)
            .where(
                CfdiRelacionado.factura_id == nota.id,
                CfdiRelacionado.tipo_relacion.in_(RELACIONES_QUE_REDUCEN_SALDO),
            )
            .order_by(CfdiRelacionado.id)
        )
    )


def _aplicar_nota(sesion: Session, nota: Factura) -> list[Motivo]:
    """Reparte el total de la nota entre sus facturas, por fecha de emisión, hasta agotarlo.

    Si la nota se relaciona con varias facturas y alguna no ha llegado, espera a que estén todas: así el reparto
    por fecha de emisión no depende del orden en que se cargaron los archivos.
    """
    motivos: list[Motivo] = []
    objetivos = _objetivos_nota(sesion, nota)
    registradas = _facturas_por_uuid(sesion, set(objetivos))
    pendientes = [u for u in objetivos if u not in registradas]
    if pendientes and len(set(objetivos)) > 1:
        return motivos
    ya_aplicadas = set(sesion.scalars(select(Aplicacion.factura_id).where(Aplicacion.origen_factura_id == nota.id)))
    aplicado = sesion.execute(
        select(func.coalesce(func.sum(Aplicacion.importe), 0)).where(Aplicacion.origen_factura_id == nota.id)
    ).scalar_one()
    restante = nota.total - Decimal(aplicado)

    for otra in sorted((f for f in registradas.values() if f.tipo != "I"), key=lambda f: f.id):
        motivos.append(_no_es_ingreso(sesion, nota, otra))
    candidatas = sorted(
        (f for f in registradas.values() if f.tipo == "I" and f.id not in ya_aplicadas),
        key=lambda f: (f.fecha_emision, f.id),
    )
    # Primero se apartan las que la nota no puede tocar: así la última que sí puede recibe todo lo que quede y
    # un sobrante nunca se pierde sin aviso.
    destinos = []
    for candidata in candidatas:
        impedimento = _puede_afectar(sesion, nota, candidata, nota.moneda)
        if impedimento is None:
            destinos.append(candidata)
        else:
            motivos.append(impedimento)
    for posicion, destino in enumerate(destinos):
        if restante <= 0:
            break
        # A la última factura posible se le pide todo lo que queda de la nota: si sobra, queda a la vista.
        es_la_ultima = posicion == len(destinos) - 1 and not pendientes
        importe = restante if es_la_ultima else min(restante, saldos.saldo(sesion, destino.id))
        if importe <= 0:
            continue
        aplicacion = _aplicar(
            sesion,
            documento=nota,
            destino=destino,
            origen="nota_credito",
            importe=importe,
            num_parcialidad=None,
            fecha=nota.fecha_emision.date(),
            motivos=motivos,
        )
        if aplicacion is not None:
            restante -= aplicacion.importe
    return motivos


def _parcialidad_ya_aplicada(sesion: Session, destino: Factura, num_parcialidad: int) -> Aplicacion | None:
    """La aplicación de un complemento que ya pagó esa parcialidad de la factura, si existe.

    El SAT no admite dos pagos con la misma parcialidad de una factura, vengan en el mismo complemento o en otro
    (por ejemplo, uno reemitido). Aplicar el segundo pagaría dos veces lo mismo; y dentro del mismo complemento
    chocaría con la llave de idempotencia de `saldos.aplicar` y se descartaría sin aviso.
    """
    return sesion.execute(
        select(Aplicacion)
        .where(
            Aplicacion.origen == "complemento_pago",
            Aplicacion.factura_id == destino.id,
            Aplicacion.num_parcialidad == num_parcialidad,
        )
        .order_by(Aplicacion.id)
        .limit(1)
    ).scalar_one_or_none()


def _aplicar_pago(sesion: Session, pago: Factura, solo: Factura | None) -> list[Motivo]:
    motivos: list[Motivo] = []
    consulta = (
        select(DoctoPago)
        .where(DoctoPago.factura_pago_id == pago.id, DoctoPago.aplicacion_id.is_(None))
        .order_by(DoctoPago.fecha_pago, DoctoPago.num_parcialidad, DoctoPago.id)
    )
    if solo is not None:
        consulta = consulta.where(DoctoPago.id_documento == solo.uuid)
    doctos = sesion.scalars(consulta).all()
    registradas = _facturas_por_uuid(sesion, {d.id_documento for d in doctos})
    for docto in doctos:
        destino = registradas.get(docto.id_documento)
        if destino is None:
            continue
        if destino.tipo != "I":
            motivos.append(_no_es_ingreso(sesion, pago, destino))
            continue
        impedimento = _puede_afectar(sesion, pago, destino, docto.moneda_dr)
        if impedimento is not None:
            motivos.append(impedimento)
            continue
        repetida = _parcialidad_ya_aplicada(sesion, destino, docto.num_parcialidad)
        if repetida is not None:
            motivos.append(
                _alerta_en_destino(
                    sesion,
                    codigos.PARCIALIDAD_REPETIDA,
                    f"El complemento {_referencia(pago)} paga otra vez la parcialidad {docto.num_parcialidad} de "
                    f"la factura {_referencia(destino)}. Ya se había aplicado un pago por "
                    f"{texto(repetida.importe_solicitado)} con esa parcialidad; este por {texto(docto.imp_pagado)} "
                    "no se aplicó y hay que revisarlo con el proveedor.",
                    destino,
                    pago,
                    {
                        "num_parcialidad": docto.num_parcialidad,
                        "aplicado_primero": repetida.importe,
                        "complemento_primero_id": repetida.origen_factura_id,
                        "no_aplicado": docto.imp_pagado,
                    },
                )
            )
            continue
        if destino.metodo_pago == "PUE":
            motivos.append(
                _alerta_en_destino(
                    sesion,
                    codigos.PAGO_A_FACTURA_PUE,
                    f"El complemento {_referencia(pago)} paga la factura {_referencia(destino)}, que dice pago en "
                    "una sola exhibición (PUE). Los complementos corresponden a facturas PPD.",
                    destino,
                    pago,
                    {"metodo_pago": destino.metodo_pago},
                )
            )
        saldo_antes = saldos.saldo(sesion, destino.id)
        if abs(docto.imp_saldo_ant - saldo_antes) > TOLERANCIA:
            motivos.append(
                _alerta_en_destino(
                    sesion,
                    codigos.SALDO_ANTERIOR_DISTINTO,
                    f"El complemento {_referencia(pago)} dice que el saldo anterior de la factura "
                    f"{_referencia(destino)} era {texto(docto.imp_saldo_ant)} y Cotejo tenía {texto(saldo_antes)}. "
                    "Puede faltar un pago o una nota por registrar.",
                    destino,
                    pago,
                    {
                        "saldo_anterior_documento": docto.imp_saldo_ant,
                        "saldo_calculado": saldo_antes,
                        "num_parcialidad": docto.num_parcialidad,
                    },
                )
            )
        aplicacion = _aplicar(
            sesion,
            documento=pago,
            destino=destino,
            origen="complemento_pago",
            importe=docto.imp_pagado,
            num_parcialidad=docto.num_parcialidad,
            fecha=docto.fecha_pago.date(),
            motivos=motivos,
        )
        if aplicacion is not None:
            docto.aplicacion_id = aplicacion.id
    sesion.flush()
    return motivos


def _pendientes_de(sesion: Session, documento: Factura) -> list[str]:
    if documento.tipo == "E":
        objetivos = _objetivos_nota(sesion, documento)
    else:
        objetivos = list(
            sesion.scalars(select(DoctoPago.id_documento).where(DoctoPago.factura_pago_id == documento.id))
        )
    registradas = _facturas_por_uuid(sesion, set(objetivos))
    return sorted({u for u in objetivos if u not in registradas})


def aplicar_documento(sesion: Session, documento: Factura, *, empresa_rfc: str) -> list[Motivo]:
    """Aplica una nota de crédito o un complemento de pago recién registrado. Devuelve los motivos por avisar."""
    if documento.tipo not in ("E", "P") or documento.receptor_rfc != empresa_rfc:
        return []
    motivos: list[Motivo] = []
    if documento.tipo == "E":
        objetivos = _objetivos_nota(sesion, documento)
        if len(objetivos) > 1:
            mensaje = (
                f"La nota de crédito se relaciona con {len(objetivos)} facturas. Se repartió por fecha de emisión "
                "hasta agotar su total; conviene confirmar el reparto."
            )
            alertas.abrir(
                sesion,
                codigo=codigos.NOTA_VARIAS_FACTURAS,
                severidad="alerta",
                mensaje=mensaje,
                factura_id=documento.id,
                detalle={"uuids": objetivos},
            )
            motivos.append(codigos.alerta(codigos.NOTA_VARIAS_FACTURAS, mensaje, {"uuids": objetivos}))
        motivos.extend(_aplicar_nota(sesion, documento))
    else:
        motivos.extend(_aplicar_pago(sesion, documento, None))
    pendiente = _actualizar_pendiente(sesion, documento, _pendientes_de(sesion, documento))
    if pendiente is not None:
        motivos.append(pendiente)
    return motivos


def aplicar_pendientes(sesion: Session, factura: Factura, *, empresa_rfc: str) -> list[Motivo]:
    """Al registrar una factura de ingreso, aplica las notas y los pagos que la estaban esperando."""
    if factura.tipo != "I":
        return []
    ids_notas = select(CfdiRelacionado.factura_id).where(
        CfdiRelacionado.uuid_relacionado == factura.uuid,
        CfdiRelacionado.tipo_relacion.in_(RELACIONES_QUE_REDUCEN_SALDO),
    )
    ids_pagos = select(DoctoPago.factura_pago_id).where(
        DoctoPago.id_documento == factura.uuid, DoctoPago.aplicacion_id.is_(None)
    )
    documentos = sesion.scalars(
        select(Factura)
        .where(
            Factura.id.in_(ids_notas.union(ids_pagos)),
            Factura.tipo.in_(("E", "P")),
            Factura.receptor_rfc == empresa_rfc,
        )
        .order_by(Factura.fecha_emision, Factura.id)
    ).all()
    motivos: list[Motivo] = []
    for documento in documentos:
        if documento.tipo == "E":
            motivos.extend(_aplicar_nota(sesion, documento))
        else:
            motivos.extend(_aplicar_pago(sesion, documento, factura))
        _actualizar_pendiente(sesion, documento, _pendientes_de(sesion, documento))
    return motivos
