"""Fábricas de datos ficticios para pruebas de integración.

Cada función confirma con `commit()` en la sesión de la prueba. Ese commit solo libera un savepoint: todo vive
dentro de la transacción externa del fixture `sesion`, que se revierte al final. Confirmar importa porque una
petición HTTP que falla hace rollback y, sin commit, se llevaría también los datos preparados por la prueba.
Los valores por omisión cumplen todas las restricciones de la base; cualquier campo se puede sobreescribir.
"""

from __future__ import annotations

import hashlib
import itertools
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from cotejo.modelos import Carga, CargaArchivo, Factura, Proveedor, Usuario
from cotejo.seguridad.contrasenas import hash_contrasena

EMPRESA_RFC = "EKU9003173C9"
_secuencia = itertools.count(1)
# Fecha de emisión por omisión: hora local del lugar de expedición, sin zona (así la define el SAT).
FECHA_EMISION = datetime.fromisoformat("2026-10-01T10:00:00")


def _n() -> int:
    return next(_secuencia)


def crear_usuario(
    sesion: Session,
    *,
    rol: str = "capturista",
    usuario: str | None = None,
    nombre: str | None = None,
    contrasena: str | None = None,
    es_demo: bool = False,
    activo: bool = True,
) -> Usuario:
    n = _n()
    obj = Usuario(
        usuario=usuario or f"{rol}.{n}",
        nombre=nombre or f"Persona Ficticia {n}",
        rol=rol,
        hash_contrasena=hash_contrasena(contrasena) if contrasena is not None else None,
        es_demo=es_demo,
        activo=activo,
    )
    sesion.add(obj)
    sesion.commit()
    return obj


def crear_proveedor(
    sesion: Session, *, rfc: str | None = None, nombre: str | None = None, dias_credito: int = 30
) -> Proveedor:
    n = _n()
    obj = Proveedor(
        # Prefijo ZZ: RFC ficticios que no corresponden a contribuyentes reales.
        rfc=rfc or f"ZZA{n % 100:02d}0101{n % 1000:03d}",
        nombre=nombre or f"Proveedor Ficticio {n} SA de CV",
        dias_credito=dias_credito,
        rfc_formato_valido=True,
        rfc_digito_valido=None,
    )
    sesion.add(obj)
    sesion.commit()
    return obj


def crear_carga_archivo(
    sesion: Session, *, usuario: Usuario | None = None, tipo: str = "cfdi", resultado: str = "aceptada"
) -> CargaArchivo:
    usuario = usuario or crear_usuario(sesion)
    carga = Carga(usuario_id=usuario.id, tipo=tipo)
    sesion.add(carga)
    sesion.flush()
    archivo = CargaArchivo(
        carga_id=carga.id,
        nombre_archivo=f"archivo_{carga.id}.xml",
        sha256=hashlib.sha256(str(carga.id).encode()).hexdigest(),
        tamano_bytes=1024,
        resultado=resultado,
    )
    sesion.add(archivo)
    sesion.commit()
    return archivo


def crear_factura(
    sesion: Session,
    *,
    proveedor: Proveedor | None = None,
    tipo: str = "I",
    total: Decimal = Decimal("1160.00"),
    subtotal: Decimal | None = None,
    moneda: str = "MXN",
    tipo_cambio: Decimal | None = None,
    fecha_emision: datetime = FECHA_EMISION,
    serie: str | None = "A",
    folio: str | None = None,
    metodo_pago: str | None = "PPD",
    uuid_cfdi: str | None = None,
    carga_archivo: CargaArchivo | None = None,
) -> Factura:
    """Factura mínima coherente. No pasa por el parser: sirve para probar consultas y reglas sobre la base."""
    proveedor = proveedor or crear_proveedor(sesion)
    carga_archivo = carga_archivo or crear_carga_archivo(sesion)
    n = _n()
    subtotal = subtotal if subtotal is not None else (total / Decimal("1.16")).quantize(Decimal("0.01"))
    xml = f"<cfdi:Comprobante Version='4.0' Total='{total}'/>"
    obj = Factura(
        uuid=(uuid_cfdi or str(uuid.UUID(int=n))).upper(),
        tipo=tipo,
        version="4.0",
        serie=serie,
        folio=folio or str(n),
        fecha_emision=fecha_emision,
        fecha_timbrado=fecha_emision,
        proveedor_id=proveedor.id,
        emisor_rfc=proveedor.rfc,
        emisor_nombre=proveedor.nombre,
        emisor_regimen="601",
        receptor_rfc=EMPRESA_RFC,
        receptor_nombre="Comercializadora Ficticia del Centro",
        receptor_uso_cfdi="G03",
        subtotal=subtotal,
        descuento=Decimal("0"),
        total_impuestos_trasladados=total - subtotal,
        total=total,
        moneda=moneda,
        tipo_cambio=tipo_cambio,
        metodo_pago=metodo_pago,
        forma_pago="99",
        exportacion="01",
        lugar_expedicion="64000",
        resultado="aceptada",
        xml_original=xml,
        xml_sha256=hashlib.sha256(xml.encode()).hexdigest(),
        carga_archivo_id=carga_archivo.id,
    )
    sesion.add(obj)
    sesion.flush()
    carga_archivo.factura_id = obj.id
    sesion.commit()
    return obj
