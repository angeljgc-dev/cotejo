"""Generador de XML de CFDI 4.0 ficticios, válidos contra los XSD del SAT.

Sirve a la semilla de la demostración y a las pruebas. Los sellos y certificados son texto de relleno: estos
comprobantes no tienen validez fiscal ni la aparentan. Los importes se calculan con Decimal y se redondean al
final, como pide la guía de llenado.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from lxml import etree

NS_CFDI = "http://www.sat.gob.mx/cfd/4"
NS_TFD = "http://www.sat.gob.mx/TimbreFiscalDigital"
NS_PAGOS = "http://www.sat.gob.mx/Pagos20"
NS_XSI = "http://www.w3.org/2001/XMLSchema-instance"

SELLO_FICTICIO = "SELLO-FICTICIO-SIN-VALIDEZ-FISCAL"
CERTIFICADO_FICTICIO = "CERTIFICADO-FICTICIO-SIN-VALIDEZ-FISCAL"
NO_CERTIFICADO_FICTICIO = "00000000000000000000"
RFC_PAC_FICTICIO = "ZZP010101AA0"

_CENTAVO = Decimal("0.01")
_IVA = Decimal("0.160000")


def _redondear(valor: Decimal) -> Decimal:
    return valor.quantize(_CENTAVO, rounding=ROUND_HALF_UP)


def _dinero(valor: Decimal) -> str:
    return format(_redondear(valor), "f")


def _fecha(valor: datetime) -> str:
    return valor.strftime("%Y-%m-%dT%H:%M:%S")


@dataclass(frozen=True)
class ConceptoFicticio:
    descripcion: str
    cantidad: Decimal = Decimal(1)
    valor_unitario: Decimal = Decimal("1000.00")
    descuento: Decimal | None = None
    clave_prod_serv: str = "84111506"
    clave_unidad: str = "E48"
    unidad: str | None = "Servicio"
    # None: el concepto no es objeto de impuesto.
    tasa_iva: Decimal | None = _IVA

    @property
    def importe(self) -> Decimal:
        return _redondear(self.cantidad * self.valor_unitario)

    @property
    def base(self) -> Decimal:
        return self.importe - (self.descuento or Decimal(0))

    @property
    def iva(self) -> Decimal:
        return Decimal(0) if self.tasa_iva is None else _redondear(self.base * self.tasa_iva)


@dataclass(frozen=True)
class DoctoFicticio:
    id_documento: str
    num_parcialidad: int
    saldo_anterior: Decimal
    pagado: Decimal
    moneda: str = "MXN"
    serie: str | None = None
    folio: str | None = None


@dataclass(frozen=True)
class PagoFicticio:
    fecha: datetime
    doctos: tuple[DoctoFicticio, ...]
    forma_pago: str = "03"
    moneda: str = "MXN"

    @property
    def monto(self) -> Decimal:
        return sum((d.pagado for d in self.doctos), Decimal(0))


@dataclass(frozen=True)
class CfdiFicticio:
    uuid: str
    fecha: datetime
    emisor_rfc: str
    emisor_nombre: str
    receptor_rfc: str
    receptor_nombre: str
    tipo: str = "I"
    serie: str | None = "A"
    folio: str | None = "1"
    conceptos: tuple[ConceptoFicticio, ...] = (ConceptoFicticio(descripcion="Servicio ficticio"),)
    moneda: str = "MXN"
    tipo_cambio: Decimal | None = None
    metodo_pago: str | None = "PPD"
    forma_pago: str | None = "99"
    condiciones_pago: str | None = None
    emisor_regimen: str = "601"
    receptor_regimen: str = "601"
    receptor_cp: str = "06000"
    uso_cfdi: str = "G03"
    lugar_expedicion: str = "64000"
    # Pares (tipo de relación, UUID), por ejemplo ("01", uuid) en una nota de crédito.
    relacionados: tuple[tuple[str, str], ...] = ()
    pagos: tuple[PagoFicticio, ...] = ()
    # Tasa de ISR retenido sobre el subtotal menos descuentos (honorarios, arrendamiento).
    tasa_retencion_isr: Decimal | None = None
    # Para probar alertas: sustituye el Total calculado por otro.
    total_forzado: Decimal | None = None
    extras: dict[str, str] = field(default_factory=dict)

    @property
    def subtotal(self) -> Decimal:
        return sum((c.importe for c in self.conceptos), Decimal(0))

    @property
    def descuento(self) -> Decimal | None:
        descuentos = [c.descuento for c in self.conceptos if c.descuento is not None]
        return sum(descuentos, Decimal(0)) if descuentos else None

    @property
    def iva(self) -> Decimal:
        return sum((c.iva for c in self.conceptos), Decimal(0))

    @property
    def retencion_isr(self) -> Decimal:
        if self.tasa_retencion_isr is None:
            return Decimal(0)
        return _redondear((self.subtotal - (self.descuento or Decimal(0))) * self.tasa_retencion_isr)

    @property
    def total(self) -> Decimal:
        if self.total_forzado is not None:
            return self.total_forzado
        if self.tipo == "P":
            return Decimal(0)
        return self.subtotal - (self.descuento or Decimal(0)) + self.iva - self.retencion_isr


def _sub(padre: etree._Element, espacio: str, nombre: str, atributos: dict[str, str | None]) -> etree._Element:
    nodo = etree.SubElement(padre, f"{{{espacio}}}{nombre}")
    for clave, valor in atributos.items():
        if valor is not None:
            nodo.set(clave, valor)
    return nodo


def _agregar_conceptos(raiz: etree._Element, cfdi: CfdiFicticio) -> None:
    conceptos = _sub(raiz, NS_CFDI, "Conceptos", {})
    if cfdi.tipo == "P":
        # El complemento de pagos lleva un único concepto fijo que define la guía de llenado.
        _sub(
            conceptos,
            NS_CFDI,
            "Concepto",
            {
                "ClaveProdServ": "84111506",
                "Cantidad": "1",
                "ClaveUnidad": "ACT",
                "Descripcion": "Pago",
                "ValorUnitario": "0",
                "Importe": "0",
                "ObjetoImp": "01",
            },
        )
        return
    for concepto in cfdi.conceptos:
        nodo = _sub(
            conceptos,
            NS_CFDI,
            "Concepto",
            {
                "ClaveProdServ": concepto.clave_prod_serv,
                "Cantidad": format(concepto.cantidad, "f"),
                "ClaveUnidad": concepto.clave_unidad,
                "Unidad": concepto.unidad,
                "Descripcion": concepto.descripcion,
                "ValorUnitario": format(concepto.valor_unitario, "f"),
                "Importe": _dinero(concepto.importe),
                "Descuento": None if concepto.descuento is None else _dinero(concepto.descuento),
                "ObjetoImp": "01" if concepto.tasa_iva is None else "02",
            },
        )
        if concepto.tasa_iva is not None:
            traslados = _sub(_sub(nodo, NS_CFDI, "Impuestos", {}), NS_CFDI, "Traslados", {})
            _sub(
                traslados,
                NS_CFDI,
                "Traslado",
                {
                    "Base": _dinero(concepto.base),
                    "Impuesto": "002",
                    "TipoFactor": "Tasa",
                    "TasaOCuota": format(concepto.tasa_iva, "f"),
                    "Importe": _dinero(concepto.iva),
                },
            )


def _agregar_impuestos(raiz: etree._Element, cfdi: CfdiFicticio) -> None:
    gravados = [c for c in cfdi.conceptos if c.tasa_iva is not None]
    if cfdi.tipo == "P" or (not gravados and cfdi.tasa_retencion_isr is None):
        return
    impuestos = _sub(
        raiz,
        NS_CFDI,
        "Impuestos",
        {
            "TotalImpuestosRetenidos": None if cfdi.tasa_retencion_isr is None else _dinero(cfdi.retencion_isr),
            "TotalImpuestosTrasladados": _dinero(cfdi.iva) if gravados else None,
        },
    )
    if cfdi.tasa_retencion_isr is not None:
        retenciones = _sub(impuestos, NS_CFDI, "Retenciones", {})
        _sub(retenciones, NS_CFDI, "Retencion", {"Impuesto": "001", "Importe": _dinero(cfdi.retencion_isr)})
    if gravados:
        traslados = _sub(impuestos, NS_CFDI, "Traslados", {})
        por_tasa: dict[Decimal, tuple[Decimal, Decimal]] = {}
        for concepto in gravados:
            if concepto.tasa_iva is None:
                continue
            base, importe = por_tasa.get(concepto.tasa_iva, (Decimal(0), Decimal(0)))
            por_tasa[concepto.tasa_iva] = (base + concepto.base, importe + concepto.iva)
        for tasa, (base, importe) in por_tasa.items():
            _sub(
                traslados,
                NS_CFDI,
                "Traslado",
                {
                    "Base": _dinero(base),
                    "Impuesto": "002",
                    "TipoFactor": "Tasa",
                    "TasaOCuota": format(tasa, "f"),
                    "Importe": _dinero(importe),
                },
            )


def _agregar_pagos(complemento: etree._Element, cfdi: CfdiFicticio) -> None:
    pagos = _sub(complemento, NS_PAGOS, "Pagos", {"Version": "2.0"})
    total = sum((p.monto for p in cfdi.pagos), Decimal(0))
    _sub(pagos, NS_PAGOS, "Totales", {"MontoTotalPagos": _dinero(total)})
    for pago in cfdi.pagos:
        nodo = _sub(
            pagos,
            NS_PAGOS,
            "Pago",
            {
                "FechaPago": _fecha(pago.fecha),
                "FormaDePagoP": pago.forma_pago,
                "MonedaP": pago.moneda,
                "TipoCambioP": "1" if pago.moneda == "MXN" else None,
                "Monto": _dinero(pago.monto),
            },
        )
        for docto in pago.doctos:
            _sub(
                nodo,
                NS_PAGOS,
                "DoctoRelacionado",
                {
                    "IdDocumento": docto.id_documento,
                    "Serie": docto.serie,
                    "Folio": docto.folio,
                    "MonedaDR": docto.moneda,
                    "EquivalenciaDR": "1" if docto.moneda == pago.moneda else None,
                    "NumParcialidad": str(docto.num_parcialidad),
                    "ImpSaldoAnt": _dinero(docto.saldo_anterior),
                    "ImpPagado": _dinero(docto.pagado),
                    "ImpSaldoInsoluto": _dinero(max(docto.saldo_anterior - docto.pagado, Decimal(0))),
                    "ObjetoImpDR": "01",
                },
            )


def construir_arbol(cfdi: CfdiFicticio) -> etree._Element:
    mapa = {"cfdi": NS_CFDI, "tfd": NS_TFD, "xsi": NS_XSI}
    if cfdi.tipo == "P":
        mapa["pago20"] = NS_PAGOS
    es_pago = cfdi.tipo == "P"
    raiz = etree.Element(f"{{{NS_CFDI}}}Comprobante", nsmap=mapa)
    raiz.set(
        f"{{{NS_XSI}}}schemaLocation",
        "http://www.sat.gob.mx/cfd/4 http://www.sat.gob.mx/sitio_internet/cfd/4/cfdv40.xsd",
    )
    atributos: dict[str, str | None] = {
        "Version": "4.0",
        "Serie": cfdi.serie,
        "Folio": cfdi.folio,
        "Fecha": _fecha(cfdi.fecha),
        "Sello": SELLO_FICTICIO,
        "FormaPago": None if es_pago else cfdi.forma_pago,
        "NoCertificado": NO_CERTIFICADO_FICTICIO,
        "Certificado": CERTIFICADO_FICTICIO,
        "CondicionesDePago": cfdi.condiciones_pago,
        "SubTotal": "0" if es_pago else _dinero(cfdi.subtotal),
        "Descuento": None if es_pago or cfdi.descuento is None else _dinero(cfdi.descuento),
        "Moneda": "XXX" if es_pago else cfdi.moneda,
        "TipoCambio": None if es_pago or cfdi.tipo_cambio is None else format(cfdi.tipo_cambio, "f"),
        "Total": "0" if es_pago and cfdi.total_forzado is None else _dinero(cfdi.total),
        "TipoDeComprobante": cfdi.tipo,
        "Exportacion": "01",
        "MetodoPago": None if es_pago else cfdi.metodo_pago,
        "LugarExpedicion": cfdi.lugar_expedicion,
    }
    atributos.update(cfdi.extras)
    for clave, valor in atributos.items():
        if valor is not None:
            raiz.set(clave, valor)

    por_tipo: dict[str, list[str]] = {}
    for tipo_relacion, uuid in cfdi.relacionados:
        por_tipo.setdefault(tipo_relacion, []).append(uuid)
    for tipo_relacion, uuids in por_tipo.items():
        grupo = _sub(raiz, NS_CFDI, "CfdiRelacionados", {"TipoRelacion": tipo_relacion})
        for uuid in uuids:
            _sub(grupo, NS_CFDI, "CfdiRelacionado", {"UUID": uuid})

    _sub(
        raiz,
        NS_CFDI,
        "Emisor",
        {"Rfc": cfdi.emisor_rfc, "Nombre": cfdi.emisor_nombre, "RegimenFiscal": cfdi.emisor_regimen},
    )
    _sub(
        raiz,
        NS_CFDI,
        "Receptor",
        {
            "Rfc": cfdi.receptor_rfc,
            "Nombre": cfdi.receptor_nombre,
            "DomicilioFiscalReceptor": cfdi.receptor_cp,
            "RegimenFiscalReceptor": cfdi.receptor_regimen,
            "UsoCFDI": "CP01" if es_pago else cfdi.uso_cfdi,
        },
    )
    _agregar_conceptos(raiz, cfdi)
    _agregar_impuestos(raiz, cfdi)
    complemento = _sub(raiz, NS_CFDI, "Complemento", {})
    if es_pago:
        _agregar_pagos(complemento, cfdi)
    _sub(
        complemento,
        NS_TFD,
        "TimbreFiscalDigital",
        {
            "Version": "1.1",
            "UUID": cfdi.uuid,
            "FechaTimbrado": _fecha(cfdi.fecha + timedelta(minutes=2)),
            "RfcProvCertif": RFC_PAC_FICTICIO,
            "SelloCFD": SELLO_FICTICIO,
            "NoCertificadoSAT": NO_CERTIFICADO_FICTICIO,
            "SelloSAT": SELLO_FICTICIO,
        },
    )
    return raiz


def construir_xml(cfdi: CfdiFicticio) -> bytes:
    return bytes(etree.tostring(construir_arbol(cfdi), xml_declaration=True, encoding="UTF-8"))
