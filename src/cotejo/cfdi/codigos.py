"""Catálogo de motivos: por qué se rechaza un CFDI y qué alertas puede dejar.

Un rechazo impide guardar la factura. Una alerta la deja guardada y visible. Una alerta bloqueante además impide
proponer su pago mientras esté abierta.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

Severidad = Literal["rechazo", "alerta", "bloqueante"]

# Rechazos de estructura y seguridad.
EXTENSION_NO_PERMITIDA = "EXTENSION_NO_PERMITIDA"
ARCHIVO_DEMASIADO_GRANDE = "ARCHIVO_DEMASIADO_GRANDE"
ARCHIVO_VACIO = "ARCHIVO_VACIO"
XML_DTD_PROHIBIDO = "XML_DTD_PROHIBIDO"
XML_MAL_FORMADO = "XML_MAL_FORMADO"
NO_ES_CFDI40 = "NO_ES_CFDI40"
SIN_TIMBRE = "SIN_TIMBRE"
TIPO_NO_SOPORTADO = "TIPO_NO_SOPORTADO"
ATRIBUTO_REQUERIDO = "ATRIBUTO_REQUERIDO"
# Valor que el XSD del SAT no permite y que Cotejo no puede guardar (moneda que no es de tres letras, método de
# pago distinto de PUE o PPD, UUID relacionado mal escrito, parcialidad que no es un entero positivo).
ATRIBUTO_INVALIDO = "ATRIBUTO_INVALIDO"
IMPORTE_INVALIDO = "IMPORTE_INVALIDO"
FECHA_INVALIDA = "FECHA_INVALIDA"
EMITIDA_POR_LA_EMPRESA = "EMITIDA_POR_LA_EMPRESA"
PAGO_SIN_COMPLEMENTO = "PAGO_SIN_COMPLEMENTO"
ERROR_AL_PROCESAR = "ERROR_AL_PROCESAR"

UUID_YA_REGISTRADO = "UUID_YA_REGISTRADO"

# Alertas.
RFC_FORMATO_INVALIDO = "RFC_FORMATO_INVALIDO"
RFC_DIGITO_INVALIDO = "RFC_DIGITO_INVALIDO"
TOTAL_NO_CUADRA = "TOTAL_NO_CUADRA"
TOTAL_PAGO_NO_CERO = "TOTAL_PAGO_NO_CERO"
SUBTOTAL_NO_CUADRA = "SUBTOTAL_NO_CUADRA"
DESCUENTO_NO_CUADRA = "DESCUENTO_NO_CUADRA"
IMPUESTOS_NO_CUADRAN = "IMPUESTOS_NO_CUADRAN"
RECEPTOR_AJENO = "RECEPTOR_AJENO"
FECHA_FUTURA = "FECHA_FUTURA"
MONEDA_SIN_TIPO_CAMBIO = "MONEDA_SIN_TIPO_CAMBIO"
LISTA_69B = "LISTA_69B"
POSIBLE_DUPLICADO = "POSIBLE_DUPLICADO"
NOTA_SIN_RELACION = "NOTA_SIN_RELACION"
NOTA_VARIAS_FACTURAS = "NOTA_VARIAS_FACTURAS"
DOCUMENTO_RELACIONADO_PENDIENTE = "DOCUMENTO_RELACIONADO_PENDIENTE"
# Una nota de crédito o un complemento de pago solo puede afectar facturas del mismo emisor.
DOCUMENTO_DE_OTRO_EMISOR = "DOCUMENTO_DE_OTRO_EMISOR"
PAGO_EXCEDE_SALDO = "PAGO_EXCEDE_SALDO"
PAGO_MONEDA_DISTINTA = "PAGO_MONEDA_DISTINTA"
SALDO_ANTERIOR_DISTINTO = "SALDO_ANTERIOR_DISTINTO"
PAGO_A_FACTURA_PUE = "PAGO_A_FACTURA_PUE"
# Un complemento trae dos pagos a la misma factura con el mismo número de parcialidad: solo se aplica el primero.
PARCIALIDAD_REPETIDA = "PARCIALIDAD_REPETIDA"
# Un pago o una nota señala un comprobante registrado que no es factura de ingreso (otra nota, otro complemento).
DOCUMENTO_RELACIONADO_NO_ES_INGRESO = "DOCUMENTO_RELACIONADO_NO_ES_INGRESO"

BLOQUEANTES = frozenset({RECEPTOR_AJENO, LISTA_69B, POSIBLE_DUPLICADO})
# Las alertas de la lista 69-B solo se cierran cargando una lista en la que el proveedor ya no aparezca.
NO_RESOLUBLES_A_MANO = frozenset({LISTA_69B})


@dataclass(frozen=True)
class Motivo:
    codigo: str
    mensaje: str
    severidad: Severidad
    detalle: Mapping[str, object] = field(default_factory=dict)

    def a_json(self) -> dict[str, str]:
        return {"codigo": self.codigo, "mensaje": self.mensaje, "severidad": self.severidad}


def rechazo(codigo: str, mensaje: str) -> Motivo:
    return Motivo(codigo=codigo, mensaje=mensaje, severidad="rechazo")


def alerta(codigo: str, mensaje: str, detalle: Mapping[str, object] | None = None) -> Motivo:
    severidad: Severidad = "bloqueante" if codigo in BLOQUEANTES else "alerta"
    return Motivo(codigo=codigo, mensaje=mensaje, severidad=severidad, detalle=dict(detalle or {}))
