"""Convierte el XML de un CFDI 4.0 en un `CfdiLeido`. Solo lee los nodos que Cotejo usa.

No valida contra el XSD del SAT ni verifica sellos: eso ya lo hizo el PAC al timbrar. Aquí se rechaza lo que no
es un CFDI 4.0 timbrado de tipo I, E o P, y lo que no se podría guardar sin inventar datos.
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal

from lxml import etree

from cotejo.cfdi import codigos, xml_seguro
from cotejo.cfdi.modelo_leido import CfdiLeido, ConceptoLeido, DoctoPagoLeido, ImpuestoLeido, RelacionLeida

NS_CFDI = "http://www.sat.gob.mx/cfd/4"
NS_CFDI33 = "http://www.sat.gob.mx/cfd/3"
NS_TFD = "http://www.sat.gob.mx/TimbreFiscalDigital"
NS_PAGOS = "http://www.sat.gob.mx/Pagos20"
NS_IMPLOCAL = "http://www.sat.gob.mx/implocal"

TIPOS_SOPORTADOS = frozenset({"I", "E", "P"})
_NOMBRES_TIPO = {"N": "nómina", "T": "traslado"}

_PATRON_UUID = re.compile(r"[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}")
_PATRON_DECIMAL = re.compile(r"[0-9]{1,18}(\.[0-9]{1,10})?", flags=re.ASCII)
_PATRON_FECHA = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}", flags=re.ASCII)
_PATRON_MONEDA = re.compile(r"[A-Z]{3}", flags=re.ASCII)
_PATRON_PARCIALIDAD = re.compile(r"[1-9][0-9]{0,2}", flags=re.ASCII)

# Dígitos enteros y decimales que caben en cada columna de la base.
_IMPORTE = (14, 6)
_CANTIDAD = (18, 6)
_TIPO_CAMBIO = (12, 6)
_TASA = (6, 6)
_EQUIVALENCIA = (10, 10)


class CfdiRechazado(Exception):
    def __init__(self, codigo: str, mensaje: str) -> None:
        super().__init__(mensaje)
        self.codigo = codigo
        self.mensaje = mensaje


def _q(espacio: str, nombre: str) -> str:
    return f"{{{espacio}}}{nombre}"


def _opcional(nodo: etree._Element, atributo: str) -> str | None:
    valor = nodo.get(atributo)
    if valor is None:
        return None
    valor = valor.strip()
    return valor or None


def _requerido(nodo: etree._Element, atributo: str, donde: str) -> str:
    valor = _opcional(nodo, atributo)
    if valor is None:
        raise CfdiRechazado(codigos.ATRIBUTO_REQUERIDO, f"Falta el dato obligatorio {atributo} en {donde}.")
    return valor


def _decimal(texto: str, atributo: str, donde: str, limites: tuple[int, int] = _IMPORTE) -> Decimal:
    enteros, decimales = limites
    if _PATRON_DECIMAL.fullmatch(texto) is None:
        raise CfdiRechazado(
            codigos.IMPORTE_INVALIDO,
            f"El valor de {atributo} en {donde} no es un número válido (sin signo y con punto decimal).",
        )
    parte_entera, _, parte_decimal = texto.partition(".")
    if len(parte_entera.lstrip("0")) > enteros or len(parte_decimal) > decimales:
        raise CfdiRechazado(
            codigos.IMPORTE_INVALIDO,
            f"El valor de {atributo} en {donde} está fuera del rango permitido "
            f"(hasta {enteros} enteros y {decimales} decimales).",
        )
    return Decimal(texto)


def _decimal_requerido(nodo: etree._Element, atributo: str, donde: str, limites: tuple[int, int] = _IMPORTE) -> Decimal:
    return _decimal(_requerido(nodo, atributo, donde), atributo, donde, limites)


def _decimal_opcional(
    nodo: etree._Element, atributo: str, donde: str, limites: tuple[int, int] = _IMPORTE
) -> Decimal | None:
    valor = _opcional(nodo, atributo)
    return None if valor is None else _decimal(valor, atributo, donde, limites)


def _fecha(texto: str, atributo: str, donde: str) -> datetime:
    if _PATRON_FECHA.fullmatch(texto) is None:
        raise CfdiRechazado(
            codigos.FECHA_INVALIDA, f"La fecha {atributo} en {donde} no tiene el formato AAAA-MM-DDThh:mm:ss."
        )
    try:
        return datetime.fromisoformat(texto)
    except ValueError as exc:
        raise CfdiRechazado(codigos.FECHA_INVALIDA, f"La fecha {atributo} en {donde} no existe.") from exc


def _uuid(texto: str, atributo: str, donde: str) -> str:
    if _PATRON_UUID.fullmatch(texto) is None:
        raise CfdiRechazado(codigos.ATRIBUTO_INVALIDO, f"El valor de {atributo} en {donde} no es un folio fiscal.")
    return texto.upper()


def _moneda(texto: str, atributo: str, donde: str) -> str:
    if _PATRON_MONEDA.fullmatch(texto) is None:
        raise CfdiRechazado(
            codigos.ATRIBUTO_INVALIDO, f"El valor de {atributo} en {donde} no es una clave de moneda de tres letras."
        )
    return texto


def _verificar_raiz(raiz: etree._Element) -> None:
    if raiz.tag == _q(NS_CFDI33, "Comprobante"):
        raise CfdiRechazado(
            codigos.NO_ES_CFDI40, "El archivo es un CFDI versión 3.3. Cotejo solo procesa CFDI versión 4.0."
        )
    if raiz.tag != _q(NS_CFDI, "Comprobante"):
        raise CfdiRechazado(codigos.NO_ES_CFDI40, "El archivo no es un CFDI: la raíz no es un Comprobante del SAT.")
    version = _opcional(raiz, "Version")
    if version != "4.0":
        raise CfdiRechazado(
            codigos.NO_ES_CFDI40, f"El comprobante dice versión {version or 'desconocida'}; se esperaba 4.0."
        )


def _leer_timbre(raiz: etree._Element) -> tuple[str, datetime]:
    timbre = raiz.find(f"{_q(NS_CFDI, 'Complemento')}/{_q(NS_TFD, 'TimbreFiscalDigital')}")
    if timbre is None:
        raise CfdiRechazado(codigos.SIN_TIMBRE, "El comprobante no tiene timbre fiscal digital.")
    uuid = _opcional(timbre, "UUID")
    fecha = _opcional(timbre, "FechaTimbrado")
    if _opcional(timbre, "Version") != "1.1" or uuid is None or _PATRON_UUID.fullmatch(uuid) is None or fecha is None:
        raise CfdiRechazado(codigos.SIN_TIMBRE, "El timbre fiscal digital está incompleto o no es versión 1.1.")
    return uuid.upper(), _fecha(fecha, "FechaTimbrado", "el timbre")


def _leer_conceptos(raiz: etree._Element) -> tuple[ConceptoLeido, ...]:
    nodos = raiz.findall(f"{_q(NS_CFDI, 'Conceptos')}/{_q(NS_CFDI, 'Concepto')}")
    if not nodos:
        raise CfdiRechazado(codigos.ATRIBUTO_REQUERIDO, "El comprobante no tiene conceptos.")
    conceptos = []
    for orden, nodo in enumerate(nodos, start=1):
        donde = f"el concepto {orden}"
        conceptos.append(
            ConceptoLeido(
                orden=orden,
                clave_prod_serv=_requerido(nodo, "ClaveProdServ", donde),
                no_identificacion=_opcional(nodo, "NoIdentificacion"),
                cantidad=_decimal_requerido(nodo, "Cantidad", donde, _CANTIDAD),
                clave_unidad=_requerido(nodo, "ClaveUnidad", donde),
                unidad=_opcional(nodo, "Unidad"),
                descripcion=_requerido(nodo, "Descripcion", donde),
                valor_unitario=_decimal_requerido(nodo, "ValorUnitario", donde, _CANTIDAD),
                importe=_decimal_requerido(nodo, "Importe", donde),
                descuento=_decimal_opcional(nodo, "Descuento", donde),
                objeto_imp=_requerido(nodo, "ObjetoImp", donde),
            )
        )
    return tuple(conceptos)


def _leer_impuestos(raiz: etree._Element) -> tuple[Decimal | None, Decimal | None, tuple[ImpuestoLeido, ...]]:
    # El nodo Impuestos del comprobante es hijo directo de la raíz; los de cada concepto no se leen.
    nodo = raiz.find(_q(NS_CFDI, "Impuestos"))
    if nodo is None:
        return None, None, ()
    donde = "los impuestos del comprobante"
    renglones = []
    for traslado in nodo.findall(f"{_q(NS_CFDI, 'Traslados')}/{_q(NS_CFDI, 'Traslado')}"):
        renglones.append(
            ImpuestoLeido(
                clase="traslado",
                impuesto=_requerido(traslado, "Impuesto", donde),
                tipo_factor=_opcional(traslado, "TipoFactor"),
                tasa_o_cuota=_decimal_opcional(traslado, "TasaOCuota", donde, _TASA),
                base=_decimal_opcional(traslado, "Base", donde),
                importe=_decimal_opcional(traslado, "Importe", donde),
            )
        )
    for retencion in nodo.findall(f"{_q(NS_CFDI, 'Retenciones')}/{_q(NS_CFDI, 'Retencion')}"):
        renglones.append(
            ImpuestoLeido(
                clase="retencion",
                impuesto=_requerido(retencion, "Impuesto", donde),
                tipo_factor=None,
                tasa_o_cuota=None,
                base=None,
                importe=_decimal_opcional(retencion, "Importe", donde),
            )
        )
    return (
        _decimal_opcional(nodo, "TotalImpuestosTrasladados", donde),
        _decimal_opcional(nodo, "TotalImpuestosRetenidos", donde),
        tuple(renglones),
    )


def _leer_impuestos_locales(raiz: etree._Element) -> tuple[Decimal | None, Decimal | None]:
    nodo = raiz.find(f"{_q(NS_CFDI, 'Complemento')}/{_q(NS_IMPLOCAL, 'ImpuestosLocales')}")
    if nodo is None:
        return None, None
    donde = "el complemento de impuestos locales"
    return (
        _decimal_opcional(nodo, "TotaldeTraslados", donde),
        _decimal_opcional(nodo, "TotaldeRetenciones", donde),
    )


def _leer_relacionados(raiz: etree._Element) -> tuple[RelacionLeida, ...]:
    relaciones: dict[tuple[str, str], RelacionLeida] = {}
    for grupo in raiz.findall(_q(NS_CFDI, "CfdiRelacionados")):
        tipo = _requerido(grupo, "TipoRelacion", "los CFDI relacionados")
        if len(tipo) != 2:
            raise CfdiRechazado(codigos.ATRIBUTO_INVALIDO, "El TipoRelacion debe ser una clave de dos caracteres.")
        for nodo in grupo.findall(_q(NS_CFDI, "CfdiRelacionado")):
            uuid = _uuid(_requerido(nodo, "UUID", "un CFDI relacionado"), "UUID", "un CFDI relacionado")
            relaciones.setdefault((tipo, uuid), RelacionLeida(tipo_relacion=tipo, uuid=uuid))
    return tuple(relaciones.values())


def _leer_pagos(raiz: etree._Element) -> tuple[DoctoPagoLeido, ...]:
    pagos = raiz.find(f"{_q(NS_CFDI, 'Complemento')}/{_q(NS_PAGOS, 'Pagos')}")
    if pagos is None or _opcional(pagos, "Version") != "2.0":
        raise CfdiRechazado(
            codigos.PAGO_SIN_COMPLEMENTO,
            "El comprobante es de tipo pago pero no trae el complemento de recepción de pagos 2.0.",
        )
    doctos: list[DoctoPagoLeido] = []
    vistos: set[tuple[int, str]] = set()
    for indice, pago in enumerate(pagos.findall(_q(NS_PAGOS, "Pago")), start=1):
        donde = f"el pago {indice}"
        fecha_pago = _fecha(_requerido(pago, "FechaPago", donde), "FechaPago", donde)
        for docto in pago.findall(_q(NS_PAGOS, "DoctoRelacionado")):
            id_documento = _requerido(docto, "IdDocumento", donde).upper()
            if len(id_documento) > 36:
                raise CfdiRechazado(codigos.ATRIBUTO_INVALIDO, f"El IdDocumento en {donde} es demasiado largo.")
            if (indice, id_documento) in vistos:
                raise CfdiRechazado(
                    codigos.ATRIBUTO_INVALIDO, f"El documento {id_documento} aparece dos veces en {donde}."
                )
            vistos.add((indice, id_documento))
            parcialidad = _requerido(docto, "NumParcialidad", donde)
            if _PATRON_PARCIALIDAD.fullmatch(parcialidad) is None:
                raise CfdiRechazado(
                    codigos.ATRIBUTO_INVALIDO, f"El NumParcialidad en {donde} debe ser un entero entre 1 y 999."
                )
            pagado = _decimal_requerido(docto, "ImpPagado", donde)
            if pagado <= 0:
                # Un documento relacionado sin importe pagado no cambia ningún saldo.
                continue
            doctos.append(
                DoctoPagoLeido(
                    pago_indice=indice,
                    fecha_pago=fecha_pago,
                    id_documento=id_documento,
                    moneda_dr=_moneda(_requerido(docto, "MonedaDR", donde), "MonedaDR", donde),
                    equivalencia_dr=_decimal_opcional(docto, "EquivalenciaDR", donde, _EQUIVALENCIA),
                    num_parcialidad=int(parcialidad),
                    imp_saldo_ant=_decimal_requerido(docto, "ImpSaldoAnt", donde),
                    imp_pagado=pagado,
                    imp_saldo_insoluto=_decimal_requerido(docto, "ImpSaldoInsoluto", donde),
                )
            )
    return tuple(doctos)


def leer_arbol(raiz: etree._Element) -> CfdiLeido:
    _verificar_raiz(raiz)
    uuid, fecha_timbrado = _leer_timbre(raiz)
    comprobante = "el comprobante"

    tipo = _requerido(raiz, "TipoDeComprobante", comprobante)
    if tipo not in TIPOS_SOPORTADOS:
        nombre = _NOMBRES_TIPO.get(tipo)
        detalle = f"de {nombre} (tipo {tipo})" if nombre else f"de tipo {tipo}"
        raise CfdiRechazado(
            codigos.TIPO_NO_SOPORTADO,
            f"El comprobante es {detalle}. Cotejo solo procesa facturas, notas de crédito y complementos de pago.",
        )

    emisor = raiz.find(_q(NS_CFDI, "Emisor"))
    receptor = raiz.find(_q(NS_CFDI, "Receptor"))
    if emisor is None or receptor is None:
        raise CfdiRechazado(codigos.ATRIBUTO_REQUERIDO, "Falta el nodo Emisor o el nodo Receptor del comprobante.")

    fecha = _fecha(_requerido(raiz, "Fecha", comprobante), "Fecha", comprobante)
    subtotal = _decimal_requerido(raiz, "SubTotal", comprobante)
    moneda = _moneda(_requerido(raiz, "Moneda", comprobante), "Moneda", comprobante)
    total = _decimal_requerido(raiz, "Total", comprobante)
    tipo_cambio = _decimal_opcional(raiz, "TipoCambio", comprobante, _TIPO_CAMBIO)
    if tipo_cambio is not None and tipo_cambio <= 0:
        raise CfdiRechazado(codigos.IMPORTE_INVALIDO, "El TipoCambio del comprobante debe ser mayor que cero.")
    metodo_pago = _opcional(raiz, "MetodoPago")
    if metodo_pago is not None and metodo_pago not in ("PUE", "PPD"):
        raise CfdiRechazado(codigos.ATRIBUTO_INVALIDO, "El MetodoPago del comprobante debe ser PUE o PPD.")

    trasladados, retenidos, impuestos = _leer_impuestos(raiz)
    locales_trasladados, locales_retenidos = _leer_impuestos_locales(raiz)
    return CfdiLeido(
        uuid=uuid,
        tipo=tipo,
        version="4.0",
        serie=_opcional(raiz, "Serie"),
        folio=_opcional(raiz, "Folio"),
        fecha_emision=fecha,
        fecha_timbrado=fecha_timbrado,
        emisor_rfc=_requerido(emisor, "Rfc", "el emisor").upper(),
        emisor_nombre=_requerido(emisor, "Nombre", "el emisor"),
        emisor_regimen=_requerido(emisor, "RegimenFiscal", "el emisor"),
        receptor_rfc=_requerido(receptor, "Rfc", "el receptor").upper(),
        receptor_nombre=_requerido(receptor, "Nombre", "el receptor"),
        receptor_uso_cfdi=_requerido(receptor, "UsoCFDI", "el receptor"),
        subtotal=subtotal,
        descuento=_decimal_opcional(raiz, "Descuento", comprobante),
        total_impuestos_trasladados=trasladados,
        total_impuestos_retenidos=retenidos,
        impuestos_locales_trasladados=locales_trasladados,
        impuestos_locales_retenidos=locales_retenidos,
        total=total,
        moneda=moneda,
        tipo_cambio=tipo_cambio,
        metodo_pago=metodo_pago,
        forma_pago=_opcional(raiz, "FormaPago"),
        condiciones_pago=_opcional(raiz, "CondicionesDePago"),
        exportacion=_requerido(raiz, "Exportacion", comprobante),
        lugar_expedicion=_requerido(raiz, "LugarExpedicion", comprobante),
        conceptos=_leer_conceptos(raiz),
        impuestos=impuestos,
        relacionados=_leer_relacionados(raiz),
        doctos_pago=_leer_pagos(raiz) if tipo == "P" else (),
    )


def leer(contenido: bytes) -> CfdiLeido:
    """Lee los bytes de un XML. Lanza `xml_seguro.XmlRechazado` o `CfdiRechazado` con el motivo en español."""
    return leer_arbol(xml_seguro.parsear(contenido))
