"""Reglas sobre un CFDI ya leído. Son funciones puras: no consultan la base.

Las alertas no rechazan la factura ni cambian sus datos; solo avisan. Las que dependen de otras facturas o de la
lista 69-B (posible duplicado, documento relacionado pendiente, pagos) se evalúan en la ingesta.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from cotejo.cfdi import codigos, rfc
from cotejo.cfdi.codigos import Motivo, alerta
from cotejo.cfdi.modelo_leido import CfdiLeido
from cotejo.dinero import MONEDA_LOCAL, MONEDA_SIN_VALOR, texto

# La guía de llenado pide redondear al final: SubTotal, Descuento e impuestos llegan redondeados por separado y al
# recombinarlos pueden diferir del Total en un centavo.
TOLERANCIA = Decimal("0.01")
# La Fecha es hora local del lugar de expedición y en México hay husos de UTC-5 a UTC-8.
MARGEN_FECHA_FUTURA = timedelta(hours=2)
RELACIONES_QUE_REDUCEN_SALDO = frozenset({"01", "03"})

_CERO = Decimal(0)


def rechazo_por_emisor(cfdi: CfdiLeido, empresa_rfc: str) -> Motivo | None:
    """Un CFDI emitido por la propia empresa es una cuenta por cobrar: no entra a cuentas por pagar."""
    if cfdi.emisor_rfc == rfc.normalizar(empresa_rfc):
        return codigos.rechazo(
            codigos.EMITIDA_POR_LA_EMPRESA,
            "Este comprobante lo emitió la propia empresa. Cotejo solo registra comprobantes recibidos de proveedores.",
        )
    return None


def total_calculado(cfdi: CfdiLeido) -> Decimal:
    """Total según la regla del SAT: subtotal menos descuentos, más traslados, menos retenciones (con locales)."""
    return (
        cfdi.subtotal
        - (cfdi.descuento or _CERO)
        + (cfdi.total_impuestos_trasladados or _CERO)
        - (cfdi.total_impuestos_retenidos or _CERO)
        + (cfdi.impuestos_locales_trasladados or _CERO)
        - (cfdi.impuestos_locales_retenidos or _CERO)
    )


def _difiere(a: Decimal, b: Decimal) -> bool:
    return abs(a - b) > TOLERANCIA


def _alertas_rfc(cfdi: CfdiLeido) -> list[Motivo]:
    partes = (("emisor", cfdi.emisor_rfc), ("receptor", cfdi.receptor_rfc))
    formato = {parte: valor for parte, valor in partes if not rfc.formato_valido(valor)}
    digito = {parte: valor for parte, valor in partes if rfc.digito_valido(valor) is False}
    motivos = []
    if formato:
        motivos.append(
            alerta(
                codigos.RFC_FORMATO_INVALIDO,
                "El RFC del " + " y del ".join(formato) + " no tiene el formato que define el SAT.",
                formato,
            )
        )
    if digito:
        motivos.append(
            alerta(
                codigos.RFC_DIGITO_INVALIDO,
                "El dígito de verificación del RFC del " + " y del ".join(digito) + " no coincide. Puede ser un "
                "error de captura; conviene confirmarlo con el proveedor.",
                digito,
            )
        )
    return motivos


def _alertas_importes(cfdi: CfdiLeido) -> list[Motivo]:
    motivos = []
    calculado = total_calculado(cfdi)
    if _difiere(cfdi.total, calculado):
        motivos.append(
            alerta(
                codigos.TOTAL_NO_CUADRA,
                f"El total del comprobante ({texto(cfdi.total)}) no coincide con subtotal, descuento e impuestos "
                f"({texto(calculado)}).",
                {"total": cfdi.total, "calculado": calculado},
            )
        )
    suma_conceptos = sum((c.importe for c in cfdi.conceptos), _CERO)
    if _difiere(cfdi.subtotal, suma_conceptos):
        motivos.append(
            alerta(
                codigos.SUBTOTAL_NO_CUADRA,
                f"El subtotal ({texto(cfdi.subtotal)}) no coincide con la suma de los conceptos "
                f"({texto(suma_conceptos)}).",
                {"subtotal": cfdi.subtotal, "suma_conceptos": suma_conceptos},
            )
        )
    descuentos = [c.descuento for c in cfdi.conceptos if c.descuento is not None]
    if descuentos:
        suma_descuentos = sum(descuentos, _CERO)
        if cfdi.descuento is None or _difiere(cfdi.descuento, suma_descuentos):
            declarado = "no declara descuento" if cfdi.descuento is None else f"declara {texto(cfdi.descuento)}"
            motivos.append(
                alerta(
                    codigos.DESCUENTO_NO_CUADRA,
                    f"Los conceptos suman {texto(suma_descuentos)} de descuento y el comprobante {declarado}.",
                    {"descuento": cfdi.descuento, "suma_conceptos": suma_descuentos},
                )
            )
    motivos.extend(_alertas_impuestos(cfdi))
    return motivos


def _alertas_impuestos(cfdi: CfdiLeido) -> list[Motivo]:
    diferencias: dict[str, object] = {}
    for clase, declarado, nombre in (
        ("traslado", cfdi.total_impuestos_trasladados, "trasladados"),
        ("retencion", cfdi.total_impuestos_retenidos, "retenidos"),
    ):
        importes = [i.importe for i in cfdi.impuestos if i.clase == clase and i.importe is not None]
        if declarado is None and not importes:
            continue
        suma = sum(importes, _CERO)
        if _difiere(declarado or _CERO, suma):
            diferencias[nombre] = {"declarado": declarado, "suma": suma}
    if not diferencias:
        return []
    return [
        alerta(
            codigos.IMPUESTOS_NO_CUADRAN,
            "El total de impuestos " + " y ".join(diferencias) + " no coincide con la suma de su desglose.",
            diferencias,
        )
    ]


def evaluar(cfdi: CfdiLeido, *, empresa_rfc: str, ahora: datetime) -> list[Motivo]:
    """Alertas que se pueden decidir con el puro comprobante. `ahora` es la hora local sin zona."""
    motivos = _alertas_rfc(cfdi)
    if cfdi.tipo in ("I", "E"):
        motivos.extend(_alertas_importes(cfdi))
    elif cfdi.subtotal != 0 or cfdi.total != 0:
        motivos.append(
            alerta(
                codigos.TOTAL_PAGO_NO_CERO,
                "Un complemento de pago debe traer subtotal y total en cero; este trae otros importes.",
                {"subtotal": cfdi.subtotal, "total": cfdi.total},
            )
        )
    if cfdi.receptor_rfc != rfc.normalizar(empresa_rfc):
        motivos.append(
            alerta(
                codigos.RECEPTOR_AJENO,
                f"El receptor del comprobante es {cfdi.receptor_rfc}, no la empresa ({rfc.normalizar(empresa_rfc)}). "
                "No se puede proponer su pago mientras esta alerta siga abierta.",
                {"receptor_rfc": cfdi.receptor_rfc, "empresa_rfc": rfc.normalizar(empresa_rfc)},
            )
        )
    if cfdi.fecha_emision > ahora + MARGEN_FECHA_FUTURA:
        motivos.append(
            alerta(
                codigos.FECHA_FUTURA,
                f"La fecha de emisión ({cfdi.fecha_emision.isoformat(sep=' ')}) es posterior a la fecha actual.",
                {"fecha_emision": cfdi.fecha_emision, "ahora": ahora},
            )
        )
    if cfdi.moneda not in (MONEDA_LOCAL, MONEDA_SIN_VALOR) and cfdi.tipo_cambio is None:
        motivos.append(
            alerta(
                codigos.MONEDA_SIN_TIPO_CAMBIO,
                f"El comprobante está en {cfdi.moneda} y no trae tipo de cambio. Su equivalente en pesos no está "
                "disponible y no entra al adeudo en pesos.",
                {"moneda": cfdi.moneda},
            )
        )
    if cfdi.tipo == "E" and not any(r.tipo_relacion in RELACIONES_QUE_REDUCEN_SALDO for r in cfdi.relacionados):
        motivos.append(
            alerta(
                codigos.NOTA_SIN_RELACION,
                "La nota de crédito no dice a qué factura corresponde (relación 01 o 03), así que no reduce ningún "
                "saldo.",
            )
        )
    return motivos
