"""Comprobantes ficticios para pruebas: se construyen como XML y entran por la carga real."""

from __future__ import annotations

import itertools
import uuid
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from cotejo.ingesta.servicio import ArchivoPorIngerir, ResultadoCarga, ingerir_lote
from cotejo.modelos import Aplicacion, Factura, Usuario
from cotejo.semilla.cfdi_ficticio import CfdiFicticio, ConceptoFicticio, DoctoFicticio, PagoFicticio, construir_xml
from cotejo.semilla.rfc_ficticio import rfc_moral
from tests.apoyo.fabricas import EMPRESA_RFC, crear_usuario

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "cfdi"
EMPRESA_NOMBRE = "Comercializadora Ficticia del Centro"
# Hora de referencia de las cargas en pruebas: FECHA_HOY_FIJA a mediodía.
AHORA = datetime.fromisoformat("2026-11-02T12:00:00")
RFC_A = rfc_moral("A", date(2001, 1, 1), "AA")
RFC_B = rfc_moral("B", date(2002, 2, 2), "BB")
_n = itertools.count(1)
FECHA_FACTURA = datetime.fromisoformat("2026-10-01T10:00:00")
FECHA_NOTA = datetime.fromisoformat("2026-10-15T10:00:00")
FECHA_PAGO = datetime.fromisoformat("2026-10-20T10:00:00")

# Tablas que una carga duplicada no debe tocar (A4). La bitácora y las cargas sí registran el intento.
TABLAS_DE_NEGOCIO = (
    "proveedores",
    "facturas",
    "conceptos",
    "factura_impuestos",
    "cfdi_relacionados",
    "doctos_pago",
    "aplicaciones",
    "alertas",
    "lista_69b",
    "propuestas",
    "renglones_propuesta",
)


def uuid_nuevo() -> str:
    return str(uuid.UUID(int=0xC0FE << 96 | next(_n))).upper()


def ingreso(
    total: Decimal = Decimal("1160.00"),
    *,
    emisor: str = RFC_A,
    fecha: datetime = FECHA_FACTURA,
    folio: str | None = None,
    serie: str | None = "A",
    moneda: str = "MXN",
    tipo_cambio: Decimal | None = None,
    metodo_pago: str = "PPD",
    receptor: str = EMPRESA_RFC,
    uuid_cfdi: str | None = None,
) -> CfdiFicticio:
    """Factura de ingreso con un concepto de `total / 1.16` más IVA; el total sale exacto si es múltiplo de 1.16."""
    subtotal = (total / Decimal("1.16")).quantize(Decimal("0.01"))
    cfdi = CfdiFicticio(
        uuid=uuid_cfdi or uuid_nuevo(),
        fecha=fecha,
        emisor_rfc=emisor,
        emisor_nombre=f"Proveedor Ficticio {emisor[:3]} SA de CV",
        receptor_rfc=receptor,
        receptor_nombre=EMPRESA_NOMBRE,
        serie=serie,
        folio=folio or str(next(_n)),
        conceptos=(ConceptoFicticio(descripcion="Servicio ficticio", valor_unitario=subtotal),),
        moneda=moneda,
        tipo_cambio=tipo_cambio,
        metodo_pago=metodo_pago,
    )
    if total != subtotal + (subtotal * Decimal("0.16")).quantize(Decimal("0.01")):
        cfdi = replace(cfdi, total_forzado=total)
    return cfdi


def nota(
    total_subtotal: Decimal,
    *uuids: str,
    emisor: str = RFC_A,
    fecha: datetime = FECHA_NOTA,
    moneda: str = "MXN",
    tipo_cambio: Decimal | None = None,
) -> CfdiFicticio:
    """Nota de crédito tipo E por `total_subtotal` antes de IVA, relacionada (01) con las facturas dadas."""
    return CfdiFicticio(
        uuid=uuid_nuevo(),
        fecha=fecha,
        tipo="E",
        emisor_rfc=emisor,
        emisor_nombre=f"Proveedor Ficticio {emisor[:3]} SA de CV",
        receptor_rfc=EMPRESA_RFC,
        receptor_nombre=EMPRESA_NOMBRE,
        serie="NC",
        folio=str(next(_n)),
        conceptos=(ConceptoFicticio(descripcion="Bonificación", valor_unitario=total_subtotal),),
        moneda=moneda,
        tipo_cambio=tipo_cambio,
        metodo_pago="PUE",
        forma_pago="03",
        uso_cfdi="G02",
        relacionados=tuple(("01", u) for u in uuids),
    )


def pago(
    *pagos: tuple[datetime, tuple[DoctoFicticio, ...]],
    emisor: str = RFC_A,
    fecha: datetime = FECHA_PAGO,
) -> CfdiFicticio:
    return CfdiFicticio(
        uuid=uuid_nuevo(),
        fecha=fecha,
        tipo="P",
        emisor_rfc=emisor,
        emisor_nombre=f"Proveedor Ficticio {emisor[:3]} SA de CV",
        receptor_rfc=EMPRESA_RFC,
        receptor_nombre=EMPRESA_NOMBRE,
        serie="CP",
        folio=str(next(_n)),
        pagos=tuple(PagoFicticio(fecha=f, doctos=d, moneda=d[0].moneda) for f, d in pagos),
    )


def docto(
    factura: CfdiFicticio, parcialidad: int, saldo_anterior: Decimal, pagado: Decimal, moneda: str = "MXN"
) -> DoctoFicticio:
    return DoctoFicticio(
        id_documento=factura.uuid,
        num_parcialidad=parcialidad,
        saldo_anterior=saldo_anterior,
        pagado=pagado,
        moneda=moneda,
        serie=factura.serie,
        folio=factura.folio,
    )


def capturista(sesion: Session) -> Usuario:
    return crear_usuario(sesion, rol="capturista")


def ingerir(sesion: Session, *comprobantes: CfdiFicticio | bytes, usuario: Usuario | None = None) -> ResultadoCarga:
    usuario = usuario or capturista(sesion)
    entradas = [
        ArchivoPorIngerir(nombre=f"archivo_{i}.xml", contenido=c if isinstance(c, bytes) else construir_xml(c))
        for i, c in enumerate(comprobantes)
    ]
    resultado = ingerir_lote(sesion, usuario_id=usuario.id, entradas=entradas, empresa_rfc=EMPRESA_RFC, ahora=AHORA)
    sesion.commit()
    return resultado


def factura_de(sesion: Session, cfdi: CfdiFicticio) -> Factura:
    return sesion.scalars(select(Factura).where(Factura.uuid == cfdi.uuid)).one()


def aplicado(sesion: Session, factura_id: int) -> Decimal:
    return Decimal(
        sesion.execute(
            select(func.coalesce(func.sum(Aplicacion.importe), 0)).where(Aplicacion.factura_id == factura_id)
        ).scalar_one()
    )


def huella_tablas(
    sesion: Session, tablas: tuple[str, ...] = TABLAS_DE_NEGOCIO, *, sin_columnas: frozenset[str] = frozenset()
) -> dict[str, str]:
    """Hash del contenido completo de cada tabla (renglones ordenados), opcionalmente sin algunas columnas."""
    huellas = {}
    for tabla in tablas:
        columnas = [
            c
            for c in sesion.scalars(
                text(
                    "SELECT column_name FROM information_schema.columns WHERE table_name = :t ORDER BY ordinal_position"
                ),
                {"t": tabla},
            )
            if c not in sin_columnas
        ]
        lista = ", ".join(f'"{c}"' for c in columnas)
        huellas[tabla] = sesion.execute(
            text(
                f"SELECT md5(coalesce(string_agg(r::text, '|' ORDER BY r::text), '')) "
                f"FROM (SELECT {lista} FROM {tabla}) r"
            )
        ).scalar_one()
    return huellas
