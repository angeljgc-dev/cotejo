"""Saldo de una factura y única puerta de escritura de lo que lo reduce.

saldo = total - suma(aplicaciones.importe). Toda aplicación (complemento de pago, nota de crédito o pago
aprobado) entra por `aplicar`, que bloquea la factura, calcula el saldo y nunca aplica más de lo que se debe.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from cotejo.cxp import alertas
from cotejo.dinero import cuantizar, texto
from cotejo.modelos import Alerta, Aplicacion, Factura

ORIGENES_DOCUMENTO = frozenset({"complemento_pago", "nota_credito"})
ORIGEN_PROPUESTA = "pago_aprobado"
CODIGO_EXCEDE_SALDO = "PAGO_EXCEDE_SALDO"


@dataclass(frozen=True)
class Bloqueo:
    codigo: str
    mensaje: str


class FacturaNoEncontrada(LookupError):
    def __init__(self, factura_id: int) -> None:
        super().__init__(f"No existe la factura {factura_id}.")
        self.factura_id = factura_id


class ErrorAplicacion(ValueError):
    """La aplicación pedida no es válida y no se registró nada."""


class ExcedeSaldo(ErrorAplicacion):
    """Un pago aprobado pide más que el saldo. Los pagos aprobados no se recortan: se rechazan completos."""

    def __init__(self, factura_id: int, importe: Decimal, saldo_actual: Decimal) -> None:
        super().__init__(
            f"El pago de {texto(importe)} excede el saldo de {texto(saldo_actual)} de la factura {factura_id}."
        )
        self.factura_id = factura_id
        self.importe = importe
        self.saldo_actual = saldo_actual


class SinSaldo(ErrorAplicacion):
    """La factura ya no tiene saldo: no hay nada que aplicar. La alerta PAGO_EXCEDE_SALDO ya quedó registrada."""

    def __init__(self, factura_id: int, importe: Decimal) -> None:
        super().__init__(f"La factura {factura_id} ya no tiene saldo; no se aplicaron {texto(importe)}.")
        self.factura_id = factura_id
        self.importe = importe


def _aplicado(sesion: Session, factura_id: int) -> Decimal:
    suma = sesion.execute(
        select(func.coalesce(func.sum(Aplicacion.importe), 0)).where(Aplicacion.factura_id == factura_id)
    ).scalar_one()
    return Decimal(suma)


def saldo(sesion: Session, factura_id: int, *, bloquear: bool = False) -> Decimal:
    """Saldo en la moneda de la factura. Con `bloquear`, la factura queda bloqueada hasta el fin de la transacción.

    Las notas de crédito y los complementos de pago (tipos E y P) no tienen saldo: devuelve cero.
    """
    consulta = select(Factura.total, Factura.tipo).where(Factura.id == factura_id)
    if bloquear:
        consulta = consulta.with_for_update()
    fila = sesion.execute(consulta).one_or_none()
    if fila is None:
        raise FacturaNoEncontrada(factura_id)
    total, tipo = fila
    if tipo != "I":
        return Decimal(0)
    return Decimal(total) - _aplicado(sesion, factura_id)


def bloqueos(sesion: Session, factura_id: int) -> list[Bloqueo]:
    """Alertas bloqueantes abiertas de la factura o de su proveedor (lista 69-B)."""
    proveedor_id = sesion.execute(select(Factura.proveedor_id).where(Factura.id == factura_id)).scalar_one_or_none()
    if proveedor_id is None:
        raise FacturaNoEncontrada(factura_id)
    filas = sesion.execute(
        select(Alerta.codigo, Alerta.mensaje)
        .where(
            Alerta.severidad == "bloqueante",
            Alerta.estado == "abierta",
            or_(
                Alerta.factura_id == factura_id,
                (Alerta.factura_id.is_(None)) & (Alerta.proveedor_id == proveedor_id),
            ),
        )
        .order_by(Alerta.id)
    ).all()
    return [Bloqueo(codigo=codigo, mensaje=mensaje) for codigo, mensaje in filas]


def _existente(
    sesion: Session,
    *,
    factura_id: int,
    origen_factura_id: int | None,
    renglon_propuesta_id: int | None,
    num_parcialidad: int | None,
) -> Aplicacion | None:
    if renglon_propuesta_id is not None:
        return sesion.execute(
            select(Aplicacion).where(Aplicacion.renglon_propuesta_id == renglon_propuesta_id)
        ).scalar_one_or_none()
    return sesion.execute(
        select(Aplicacion).where(
            Aplicacion.origen_factura_id == origen_factura_id,
            Aplicacion.factura_id == factura_id,
            Aplicacion.num_parcialidad.is_not_distinct_from(num_parcialidad),
        )
    ).scalar_one_or_none()


def aplicar(
    sesion: Session,
    *,
    factura_id: int,
    importe: Decimal,
    origen: str,
    fecha: date,
    origen_factura_id: int | None = None,
    renglon_propuesta_id: int | None = None,
    num_parcialidad: int | None = None,
    usuario_id: int | None = None,
) -> Aplicacion:
    """Reduce el saldo de una factura tipo I. No hace commit.

    Idempotente: repetir el mismo documento (origen, factura y parcialidad) o el mismo renglón de propuesta
    devuelve la aplicación que ya existía. Un complemento o una nota que pide más que el saldo se aplica solo
    hasta el saldo y deja la alerta PAGO_EXCEDE_SALDO; si el saldo ya es cero lanza `SinSaldo`. Un pago aprobado
    que pide más que el saldo lanza `ExcedeSaldo` y no aplica nada.
    """
    if origen == ORIGEN_PROPUESTA:
        if renglon_propuesta_id is None or origen_factura_id is not None:
            raise ErrorAplicacion("Un pago aprobado se liga a un renglón de propuesta y no a un documento.")
    elif origen in ORIGENES_DOCUMENTO:
        if origen_factura_id is None or renglon_propuesta_id is not None:
            raise ErrorAplicacion("Un complemento de pago o una nota de crédito se liga a su CFDI de origen.")
    else:
        raise ErrorAplicacion(f"Origen de aplicación desconocido: {origen!r}.")
    if not isinstance(importe, Decimal) or not importe.is_finite() or importe <= 0:
        raise ErrorAplicacion("El importe por aplicar debe ser un decimal mayor que cero.")

    # El bloqueo de la factura pone en fila a todo el que quiera aplicarle algo: el saldo leído es el vigente.
    saldo_actual = saldo(sesion, factura_id, bloquear=True)
    tipo = sesion.execute(select(Factura.tipo).where(Factura.id == factura_id)).scalar_one()
    if tipo != "I":
        raise ErrorAplicacion("Solo las facturas de ingreso (tipo I) tienen saldo.")

    existente = _existente(
        sesion,
        factura_id=factura_id,
        origen_factura_id=origen_factura_id,
        renglon_propuesta_id=renglon_propuesta_id,
        num_parcialidad=num_parcialidad,
    )
    if existente is not None:
        return existente

    # Los saldos se muestran y se pagan a centavos: un pago aprobado por el saldo redondeado liquida la factura.
    if origen == ORIGEN_PROPUESTA and importe > cuantizar(saldo_actual):
        raise ExcedeSaldo(factura_id, importe, saldo_actual)

    aplicado = max(min(importe, saldo_actual), Decimal(0))
    excedente = importe - aplicado
    if origen != ORIGEN_PROPUESTA and cuantizar(excedente) > 0:
        alertas.abrir(
            sesion,
            codigo=CODIGO_EXCEDE_SALDO,
            severidad="alerta",
            mensaje=(
                f"Un pago o nota de crédito por {texto(importe)} supera el saldo de {texto(saldo_actual)}; "
                f"se aplicaron {texto(aplicado)} y el resto no se aplicó."
            ),
            factura_id=factura_id,
            detalle={
                "solicitado": importe,
                "saldo_anterior": saldo_actual,
                "aplicado": aplicado,
                "excedente": excedente,
                "origen": origen,
                "num_parcialidad": num_parcialidad,
            },
            factura_relacionada_id=origen_factura_id,
        )
    if aplicado <= 0:
        raise SinSaldo(factura_id, importe)

    aplicacion = Aplicacion(
        factura_id=factura_id,
        origen=origen,
        origen_factura_id=origen_factura_id,
        renglon_propuesta_id=renglon_propuesta_id,
        num_parcialidad=num_parcialidad,
        importe_solicitado=importe,
        importe=aplicado,
        fecha=fecha,
        registrado_por=usuario_id,
    )
    sesion.add(aplicacion)
    sesion.flush()
    return aplicacion
