"""Carga de CFDI: un resultado por archivo y nunca un fallo de todo el lote por un archivo malo.

Cada archivo se procesa dentro de su propio punto de guardado. Orden: seguridad y estructura (rechazos), folio
fiscal ya registrado (duplicada, sin tocar nada), y si es nuevo se guarda con sus alertas y se aplican las notas
de crédito y los pagos que correspondan.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cotejo import bitacora, lista_69b
from cotejo.cfdi import codigos, parser, reglas, rfc, xml_seguro
from cotejo.cfdi.codigos import Motivo
from cotejo.cfdi.modelo_leido import CfdiLeido
from cotejo.cxp import alertas
from cotejo.ingesta import aplicaciones, duplicados
from cotejo.modelos import (
    Carga,
    CargaArchivo,
    CfdiRelacionado,
    Concepto,
    DoctoPago,
    Factura,
    FacturaImpuesto,
    Proveedor,
)

_log = logging.getLogger("cotejo.ingesta")
# Candado de transacción que pone en fila las cargas de CFDI. Sin él, una nota y su factura cargadas a la vez
# en dos transacciones no se verían entre sí y la nota nunca se aplicaría.
CLAVE_FILA_CARGAS = 7_301_202_611
_SHA_VACIO = hashlib.sha256(b"").hexdigest()
_DECLARACION_CODIFICACION = re.compile(r"""(\A<\?xml[^>]*?encoding=["'])[^"']+""")


@dataclass(frozen=True)
class ArchivoPorIngerir:
    nombre: str
    contenido: bytes


@dataclass(frozen=True)
class ArchivoNoLeido:
    """Archivo que se rechazó antes de leerlo completo (extensión, tamaño o vacío)."""

    nombre: str
    motivo: Motivo


@dataclass(frozen=True)
class ResultadoArchivo:
    nombre: str
    resultado: str
    motivos: tuple[Motivo, ...]
    uuid: str | None = None
    factura_id: int | None = None
    tipo: str | None = None
    ya_existia: bool = False


@dataclass(frozen=True)
class ResultadoCarga:
    carga_id: int
    archivos: tuple[ResultadoArchivo, ...]

    @property
    def resumen(self) -> dict[str, int]:
        conteo = {"aceptadas": 0, "con_alertas": 0, "rechazadas": 0, "duplicadas": 0}
        claves = {
            "aceptada": "aceptadas",
            "aceptada_con_alertas": "con_alertas",
            "rechazada": "rechazadas",
            "duplicada": "duplicadas",
        }
        for archivo in self.archivos:
            conteo[claves[archivo.resultado]] += 1
        return conteo


def _anotar(
    sesion: Session, carga_id: int, nombre: str, contenido: bytes | None, resultado: ResultadoArchivo
) -> CargaArchivo:
    archivo = CargaArchivo(
        carga_id=carga_id,
        nombre_archivo=nombre,
        sha256=hashlib.sha256(contenido).hexdigest() if contenido is not None else _SHA_VACIO,
        tamano_bytes=len(contenido) if contenido is not None else 0,
        resultado=resultado.resultado,
        motivos=[m.a_json() for m in resultado.motivos],
        factura_id=resultado.factura_id,
    )
    sesion.add(archivo)
    sesion.flush()
    return archivo


def _rechazado(nombre: str, motivo: Motivo) -> ResultadoArchivo:
    return ResultadoArchivo(nombre=nombre, resultado="rechazada", motivos=(motivo,))


def _proveedor_de(sesion: Session, cfdi: CfdiLeido) -> Proveedor:
    """El proveedor es el emisor. Se crea con el nombre del primer CFDI recibido y después no se cambia."""
    sesion.execute(
        pg_insert(Proveedor)
        .values(
            rfc=cfdi.emisor_rfc,
            nombre=cfdi.emisor_nombre,
            rfc_formato_valido=rfc.formato_valido(cfdi.emisor_rfc),
            rfc_digito_valido=rfc.digito_valido(cfdi.emisor_rfc),
        )
        .on_conflict_do_nothing(index_elements=[Proveedor.rfc])
    )
    return sesion.scalars(select(Proveedor).where(Proveedor.rfc == cfdi.emisor_rfc)).one()


def _guardar(sesion: Session, cfdi: CfdiLeido, proveedor: Proveedor, xml_texto: str, archivo: CargaArchivo) -> Factura:
    factura = Factura(
        uuid=cfdi.uuid,
        tipo=cfdi.tipo,
        version=cfdi.version,
        serie=cfdi.serie,
        folio=cfdi.folio,
        fecha_emision=cfdi.fecha_emision,
        fecha_timbrado=cfdi.fecha_timbrado,
        proveedor_id=proveedor.id,
        emisor_rfc=cfdi.emisor_rfc,
        emisor_nombre=cfdi.emisor_nombre,
        emisor_regimen=cfdi.emisor_regimen,
        receptor_rfc=cfdi.receptor_rfc,
        receptor_nombre=cfdi.receptor_nombre,
        receptor_uso_cfdi=cfdi.receptor_uso_cfdi,
        subtotal=cfdi.subtotal,
        descuento=cfdi.descuento if cfdi.descuento is not None else 0,
        total_impuestos_trasladados=cfdi.total_impuestos_trasladados,
        total_impuestos_retenidos=cfdi.total_impuestos_retenidos,
        impuestos_locales_trasladados=cfdi.impuestos_locales_trasladados,
        impuestos_locales_retenidos=cfdi.impuestos_locales_retenidos,
        total=cfdi.total,
        moneda=cfdi.moneda,
        tipo_cambio=cfdi.tipo_cambio,
        metodo_pago=cfdi.metodo_pago,
        forma_pago=cfdi.forma_pago,
        condiciones_pago=cfdi.condiciones_pago,
        exportacion=cfdi.exportacion,
        lugar_expedicion=cfdi.lugar_expedicion,
        resultado="aceptada",
        xml_original=xml_texto,
        xml_sha256=archivo.sha256,
        carga_archivo_id=archivo.id,
    )
    factura.conceptos = [
        Concepto(
            orden=c.orden,
            clave_prod_serv=c.clave_prod_serv,
            no_identificacion=c.no_identificacion,
            cantidad=c.cantidad,
            clave_unidad=c.clave_unidad,
            unidad=c.unidad,
            descripcion=c.descripcion,
            valor_unitario=c.valor_unitario,
            importe=c.importe,
            descuento=c.descuento,
            objeto_imp=c.objeto_imp,
        )
        for c in cfdi.conceptos
    ]
    factura.impuestos = [
        FacturaImpuesto(
            clase=i.clase,
            impuesto=i.impuesto,
            tipo_factor=i.tipo_factor,
            tasa_o_cuota=i.tasa_o_cuota,
            base=i.base,
            importe=i.importe,
        )
        for i in cfdi.impuestos
    ]
    factura.relacionados = [
        CfdiRelacionado(tipo_relacion=r.tipo_relacion, uuid_relacionado=r.uuid) for r in cfdi.relacionados
    ]
    sesion.add(factura)
    sesion.flush()
    sesion.add_all(
        DoctoPago(
            factura_pago_id=factura.id,
            pago_indice=d.pago_indice,
            fecha_pago=d.fecha_pago,
            id_documento=d.id_documento,
            moneda_dr=d.moneda_dr,
            equivalencia_dr=d.equivalencia_dr,
            num_parcialidad=d.num_parcialidad,
            imp_saldo_ant=d.imp_saldo_ant,
            imp_pagado=d.imp_pagado,
            imp_saldo_insoluto=d.imp_saldo_insoluto,
        )
        for d in cfdi.doctos_pago
    )
    sesion.flush()
    return factura


def _texto_xml(xml: bytes, codificacion: str | None) -> str:
    """Texto del XML para guardarlo y descargarlo después como UTF-8.

    Se decodifica con la codificación que detectó el lector y la declaración se ajusta a UTF-8 para que el
    archivo descargado siga siendo coherente. PostgreSQL no admite el carácter nulo, que tampoco es válido en XML.
    """
    try:
        texto = xml.decode(codificacion or "utf-8", errors="replace")
    except LookupError:
        texto = xml.decode("utf-8", errors="replace")
    texto = texto.removeprefix("\ufeff").replace("\x00", "")
    return _DECLARACION_CODIFICACION.sub(r"\g<1>UTF-8", texto, count=1)


def _procesar(
    sesion: Session, carga_id: int, entrada: ArchivoPorIngerir, *, empresa_rfc: str, ahora: datetime
) -> ResultadoArchivo:
    nombre, contenido = entrada.nombre, entrada.contenido
    try:
        raiz = xml_seguro.parsear(contenido)
        cfdi = parser.leer_arbol(raiz)
    except (xml_seguro.XmlRechazado, parser.CfdiRechazado) as exc:
        resultado = _rechazado(nombre, codigos.rechazo(exc.codigo, exc.mensaje))
        _anotar(sesion, carga_id, nombre, contenido, resultado)
        return resultado
    por_emisor = reglas.rechazo_por_emisor(cfdi, empresa_rfc)
    if por_emisor is not None:
        resultado = _rechazado(nombre, por_emisor)
        _anotar(sesion, carga_id, nombre, contenido, resultado)
        return resultado

    existente = sesion.execute(select(Factura.id, Factura.tipo).where(Factura.uuid == cfdi.uuid)).one_or_none()
    if existente is not None:
        resultado = ResultadoArchivo(
            nombre=nombre,
            resultado="duplicada",
            motivos=(
                Motivo(
                    codigo=codigos.UUID_YA_REGISTRADO,
                    mensaje="Este CFDI ya estaba registrado; no se cambió nada.",
                    severidad="alerta",
                ),
            ),
            uuid=cfdi.uuid,
            factura_id=existente.id,
            tipo=existente.tipo,
            ya_existia=True,
        )
        _anotar(sesion, carga_id, nombre, contenido, resultado)
        return resultado

    proveedor = _proveedor_de(sesion, cfdi)
    archivo = _anotar(
        sesion, carga_id, nombre, contenido, ResultadoArchivo(nombre=nombre, resultado="aceptada", motivos=())
    )
    factura = _guardar(sesion, cfdi, proveedor, _texto_xml(contenido, raiz.getroottree().docinfo.encoding), archivo)

    empresa = rfc.normalizar(empresa_rfc)
    motivos = reglas.evaluar(cfdi, empresa_rfc=empresa, ahora=ahora)
    for motivo in motivos:
        alertas.abrir(
            sesion,
            codigo=motivo.codigo,
            severidad=motivo.severidad,
            mensaje=motivo.mensaje,
            factura_id=factura.id,
            detalle=motivo.detalle,
        )
    en_lista = lista_69b.evaluar_proveedor(sesion, proveedor)
    if en_lista is not None:
        motivos.append(en_lista)
    motivos.extend(duplicados.registrar(sesion, factura))
    if factura.tipo == "I":
        motivos.extend(aplicaciones.aplicar_pendientes(sesion, factura, empresa_rfc=empresa))
    else:
        motivos.extend(aplicaciones.aplicar_documento(sesion, factura, empresa_rfc=empresa))

    resultado_texto = "aceptada_con_alertas" if motivos else "aceptada"
    factura.resultado = resultado_texto
    archivo.resultado = resultado_texto
    archivo.motivos = [m.a_json() for m in motivos]
    archivo.factura_id = factura.id
    sesion.flush()
    return ResultadoArchivo(
        nombre=nombre,
        resultado=resultado_texto,
        motivos=tuple(motivos),
        uuid=factura.uuid,
        factura_id=factura.id,
        tipo=factura.tipo,
    )


def _ingerir_uno(
    sesion: Session, carga_id: int, entrada: ArchivoPorIngerir, *, empresa_rfc: str, ahora: datetime
) -> ResultadoArchivo:
    for intento in (1, 2):
        try:
            with sesion.begin_nested():
                return _procesar(sesion, carga_id, entrada, empresa_rfc=empresa_rfc, ahora=ahora)
        except IntegrityError:
            # Otra carga registró el mismo folio fiscal al mismo tiempo: al reintentar ya se ve como duplicada.
            if intento == 2:
                _log.exception("No se pudo registrar el archivo %s", entrada.nombre)
        except Exception:
            _log.exception("Error inesperado al procesar el archivo %s", entrada.nombre)
            break
    resultado = _rechazado(
        entrada.nombre,
        codigos.rechazo(
            codigos.ERROR_AL_PROCESAR,
            "No se pudo procesar este archivo por un error inesperado. Los demás archivos no se vieron afectados.",
        ),
    )
    _anotar(sesion, carga_id, entrada.nombre, entrada.contenido, resultado)
    return resultado


def ingerir_lote(
    sesion: Session,
    *,
    usuario_id: int,
    entradas: Sequence[ArchivoPorIngerir | ArchivoNoLeido],
    empresa_rfc: str,
    ahora: datetime,
) -> ResultadoCarga:
    """Procesa los archivos en orden y deja una carga con su bitácora. No hace commit.

    `ahora` es la hora local sin zona, la misma referencia que usa la fecha de un CFDI.
    """
    sesion.execute(text("SELECT pg_advisory_xact_lock(:clave)"), {"clave": CLAVE_FILA_CARGAS})
    carga = Carga(usuario_id=usuario_id, tipo="cfdi")
    sesion.add(carga)
    sesion.flush()
    resultados: list[ResultadoArchivo] = []
    for entrada in entradas:
        if isinstance(entrada, ArchivoNoLeido):
            resultado = _rechazado(entrada.nombre, entrada.motivo)
            _anotar(sesion, carga.id, entrada.nombre, None, resultado)
        else:
            resultado = _ingerir_uno(sesion, carga.id, entrada, empresa_rfc=empresa_rfc, ahora=ahora)
        resultados.append(resultado)
    carga_resultado = ResultadoCarga(carga_id=carga.id, archivos=tuple(resultados))
    bitacora.registrar(
        sesion,
        usuario_id=usuario_id,
        accion="CARGA_CFDI",
        entidad="carga",
        entidad_id=carga.id,
        detalle={
            "archivos": len(resultados),
            **carga_resultado.resumen,
            "facturas": [r.factura_id for r in resultados if r.factura_id is not None and not r.ya_existia],
        },
    )
    return carga_resultado
