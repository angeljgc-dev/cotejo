"""Datos de demostración deterministas: misma semilla y misma fecha base producen los mismos datos.

Los comprobantes se generan como XML y entran por la carga real (`ingesta.servicio.ingerir_lote`), así la
demostración ejercita el mismo camino que una persona: validaciones, alertas, duplicados, notas de crédito y
complementos de pago, incluidos dos documentos que llegan antes que su factura.
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import random
import uuid
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import Select, func, select, text, update
from sqlalchemy.orm import Session

from cotejo import bitacora, lista_69b
from cotejo.config import obtener_config
from cotejo.cxp import consultas
from cotejo.ingesta.servicio import ArchivoPorIngerir, ingerir_lote
from cotejo.modelos import (
    Alerta,
    Base,
    Carga,
    Documento,
    Factura,
    Propuesta,
    Proveedor,
    RenglonPropuesta,
    Usuario,
)
from cotejo.semilla import catalogo
from cotejo.semilla.catalogo import PROVEEDORES, ProveedorSemilla
from cotejo.semilla.cfdi_ficticio import (
    CfdiFicticio,
    ConceptoFicticio,
    DoctoFicticio,
    PagoFicticio,
    construir_xml,
)

_log = logging.getLogger("cotejo.semilla")

FACTURAS_POR_PROVEEDOR = 10
ARCHIVOS_POR_CARGA = 50
PRESUPUESTO_PROPUESTA = Decimal("150000.00")
RENGLONES_PROPUESTA = 5
ARCHIVO_LISTA = "lista_69b_ficticia.csv"
# Los usuarios y las cuotas sobreviven a un reinicio: las sesiones abiertas siguen siendo válidas y reiniciar
# la demostración no regala cuota de chat.
TABLAS_QUE_SE_CONSERVAN = frozenset({"usuarios", "cuota_uso"})
USUARIOS_DEMO = (
    ("demo.capturista", "Capturista de demostración", "capturista"),
    ("demo.aprobador", "Aprobador de demostración", "aprobador"),
)

# Posiciones (proveedor, factura) de los casos especiales. La factura 0 es la más reciente y la 9 la más antigua.
PAGADAS = ((1, 8), (2, 9), (5, 8))
PAGO_PARCIAL = {(3, 8): Decimal("0.50"), (9, 9): Decimal("0.40")}
DOS_PARCIALIDADES = (4, 9)
CON_NOTA_CREDITO = {(0, 5): Decimal("0.15"), (8, 6): Decimal("0.10"), (3, 5): Decimal("0.20")}
# Documentos que se cargan antes que su factura, para mostrar que se aplican solos cuando esta llega.
PAGO_QUE_LLEGA_ANTES = (2, 9)
NOTA_QUE_LLEGA_ANTES = (8, 6)
# (proveedor, factura copiada, días después, misma serie y folio)
DUPLICADOS = ((0, 2, 10, True), (3, 1, 2, False))
POSICION_DUPLICADO = 9
RECEPTOR_AJENO = (9, 3)
CON_INYECCION = ((1, 2), (5, 4))
POSICION_PUE = 7
FACTURAS_EN_DOLARES = 4
TIPO_CAMBIO_DE_LISTA = Decimal("18")
MESES = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)


@dataclass(frozen=True)
class ResumenSemilla:
    proveedores: int
    facturas: int
    notas_credito: int
    complementos_pago: int
    alertas_abiertas: int
    propuestas_pendientes: int
    documentos: int
    cargas: int


@dataclass(frozen=True)
class LoteSemilla:
    """Comprobantes de la demostración en el orden en que se cargan."""

    comprobantes: tuple[CfdiFicticio, ...]

    def de_tipo(self, tipo: str) -> list[CfdiFicticio]:
        return [c for c in self.comprobantes if c.tipo == tipo]


def _uuid(azar: random.Random) -> str:
    return str(uuid.UUID(int=azar.getrandbits(128), version=4)).upper()


def _momento(azar: random.Random, dia: date) -> datetime:
    return datetime.combine(dia, time(azar.randint(8, 18), azar.randint(0, 59), azar.randint(0, 59)))


def _conceptos(azar: random.Random, proveedor: ProveedorSemilla, en_dolares: bool) -> tuple[ConceptoFicticio, ...]:
    elegidos = azar.sample(proveedor.conceptos, k=azar.randint(1, min(3, len(proveedor.conceptos))))
    conceptos = []
    for item in elegidos:
        centavos = azar.randint(int(item.precio_minimo * 100), int(item.precio_maximo * 100))
        precio = Decimal(centavos) / 100
        if proveedor.moneda != "MXN" and not en_dolares:
            # El catálogo de estos proveedores está en dólares; sus facturas en pesos usan un tipo de cambio fijo.
            precio = precio * TIPO_CAMBIO_DE_LISTA
        conceptos.append(
            ConceptoFicticio(
                descripcion=item.descripcion,
                cantidad=Decimal(azar.randint(1, item.cantidad_maxima)),
                valor_unitario=precio,
                clave_prod_serv=item.clave_prod_serv,
                clave_unidad=item.clave_unidad,
                unidad=item.unidad,
            )
        )
    return tuple(conceptos)


def _factura(
    azar: random.Random,
    proveedor: ProveedorSemilla,
    posicion: int,
    fecha_base: date,
    *,
    empresa_rfc: str,
    empresa_nombre: str,
) -> CfdiFicticio:
    # Una factura por quincena hacia atrás: así cada proveedor tiene saldos en todos los grupos de antigüedad.
    dias_atras = posicion * 15 + azar.randint(1, 15)
    en_dolares = proveedor.moneda != "MXN" and posicion < FACTURAS_EN_DOLARES
    es_pue = posicion == POSICION_PUE
    return CfdiFicticio(
        uuid=_uuid(azar),
        fecha=_momento(azar, fecha_base - timedelta(days=dias_atras)),
        emisor_rfc=proveedor.rfc,
        emisor_nombre=proveedor.nombre,
        receptor_rfc=empresa_rfc,
        receptor_nombre=empresa_nombre,
        serie=proveedor.serie,
        folio=str(1000 + posicion),
        conceptos=_conceptos(azar, proveedor, en_dolares),
        moneda=proveedor.moneda if en_dolares else "MXN",
        tipo_cambio=Decimal(azar.randint(175000, 195000)) / 10000 if en_dolares else None,
        metodo_pago="PUE" if es_pue else "PPD",
        forma_pago="03" if es_pue else "99",
        condiciones_pago=f"Crédito {proveedor.dias_credito} días",
        lugar_expedicion=proveedor.lugar_expedicion,
    )


def _complemento(
    azar: random.Random, factura: CfdiFicticio, folio: int, parcialidades: list[tuple[int, Decimal, Decimal, int]]
) -> list[CfdiFicticio]:
    """Un CFDI de pago por parcialidad: (número, saldo anterior, pagado, días después de la factura)."""
    comprobantes = []
    for numero, saldo_anterior, pagado, dias in parcialidades:
        fecha_pago = datetime.combine(factura.fecha.date() + timedelta(days=dias), time(12, 0))
        comprobantes.append(
            CfdiFicticio(
                uuid=_uuid(azar),
                tipo="P",
                fecha=fecha_pago + timedelta(days=1, hours=-2),
                emisor_rfc=factura.emisor_rfc,
                emisor_nombre=factura.emisor_nombre,
                receptor_rfc=factura.receptor_rfc,
                receptor_nombre=factura.receptor_nombre,
                serie="CP",
                folio=str(folio + numero),
                lugar_expedicion=factura.lugar_expedicion,
                pagos=(
                    PagoFicticio(
                        fecha_pago,
                        (
                            DoctoFicticio(
                                factura.uuid,
                                numero,
                                saldo_anterior,
                                pagado,
                                moneda=factura.moneda,
                                serie=factura.serie,
                                folio=factura.folio,
                            ),
                        ),
                    ),
                ),
            )
        )
    return comprobantes


def _nota_credito(azar: random.Random, factura: CfdiFicticio, folio: int, proporcion: Decimal) -> CfdiFicticio:
    base = (factura.subtotal * proporcion).quantize(Decimal("0.01"))
    return CfdiFicticio(
        uuid=_uuid(azar),
        tipo="E",
        fecha=factura.fecha + timedelta(days=6, hours=1),
        emisor_rfc=factura.emisor_rfc,
        emisor_nombre=factura.emisor_nombre,
        receptor_rfc=factura.receptor_rfc,
        receptor_nombre=factura.receptor_nombre,
        serie="NC",
        folio=str(folio),
        moneda=factura.moneda,
        tipo_cambio=factura.tipo_cambio,
        metodo_pago="PUE",
        forma_pago="15",
        uso_cfdi="G02",
        lugar_expedicion=factura.lugar_expedicion,
        relacionados=(("01", factura.uuid),),
        conceptos=(
            ConceptoFicticio(
                descripcion=f"Bonificación sobre la factura {factura.serie} {factura.folio}",
                valor_unitario=base,
                clave_unidad="ACT",
                unidad=None,
            ),
        ),
    )


def generar_lote(semilla: int, fecha_base: date, *, empresa_rfc: str, empresa_nombre: str) -> LoteSemilla:
    """Todos los comprobantes de la demostración, en orden de carga. No toca la base."""
    azar = random.Random(semilla)
    facturas: dict[tuple[int, int], CfdiFicticio] = {}
    for indice, proveedor in enumerate(PROVEEDORES):
        for posicion in range(FACTURAS_POR_PROVEEDOR):
            facturas[(indice, posicion)] = _factura(
                azar, proveedor, posicion, fecha_base, empresa_rfc=empresa_rfc, empresa_nombre=empresa_nombre
            )

    for indice, copiada, dias_despues, misma_serie_y_folio in DUPLICADOS:
        original = facturas[(indice, copiada)]
        facturas[(indice, POSICION_DUPLICADO)] = replace(
            original,
            uuid=_uuid(azar),
            fecha=original.fecha + timedelta(days=dias_despues, minutes=17),
            folio=original.folio if misma_serie_y_folio else str(2000 + copiada),
        )
    facturas[RECEPTOR_AJENO] = replace(
        facturas[RECEPTOR_AJENO],
        receptor_rfc=catalogo.RECEPTOR_AJENO_RFC,
        receptor_nombre=catalogo.RECEPTOR_AJENO_NOMBRE,
    )
    for clave, texto_inyectado in zip(CON_INYECCION, catalogo.TEXTOS_DE_INYECCION, strict=True):
        original = facturas[clave]
        extra = ConceptoFicticio(descripcion=texto_inyectado, valor_unitario=Decimal("350.00"))
        facturas[clave] = replace(original, conceptos=(*original.conceptos, extra))

    pagos: dict[tuple[int, int], list[CfdiFicticio]] = {}
    for numero, clave in enumerate(PAGADAS):
        factura = facturas[clave]
        pagos[clave] = _complemento(azar, factura, 100 + numero * 10, [(1, factura.total, factura.total, 28)])
    for numero, (clave, proporcion) in enumerate(PAGO_PARCIAL.items()):
        factura = facturas[clave]
        pagado = (factura.total * proporcion).quantize(Decimal("0.01"))
        pagos[clave] = _complemento(azar, factura, 200 + numero * 10, [(1, factura.total, pagado, 30)])
    factura = facturas[DOS_PARCIALIDADES]
    primera = (factura.total * Decimal("0.50")).quantize(Decimal("0.01"))
    segunda = (factura.total * Decimal("0.30")).quantize(Decimal("0.01"))
    pagos[DOS_PARCIALIDADES] = _complemento(
        azar, factura, 300, [(1, factura.total, primera, 25), (2, factura.total - primera, segunda, 55)]
    )

    notas = {
        clave: _nota_credito(azar, facturas[clave], 50 + numero, proporcion)
        for numero, (clave, proporcion) in enumerate(CON_NOTA_CREDITO.items())
    }

    antes = [*pagos[PAGO_QUE_LLEGA_ANTES], notas[NOTA_QUE_LLEGA_ANTES]]
    ingresos = sorted(facturas.values(), key=lambda c: (c.fecha, c.uuid))
    despues = [n for clave, n in notas.items() if clave != NOTA_QUE_LLEGA_ANTES]
    for clave, comprobantes in pagos.items():
        if clave != PAGO_QUE_LLEGA_ANTES:
            despues.extend(comprobantes)
    despues.sort(key=lambda c: (c.fecha, c.uuid))
    return LoteSemilla(comprobantes=(*antes, *ingresos, *despues))


def _usuarios_demo(sesion: Session) -> dict[str, Usuario]:
    usuarios = {}
    for clave, nombre, rol in USUARIOS_DEMO:
        usuario = sesion.scalar(select(Usuario).where(Usuario.usuario == clave))
        if usuario is None:
            usuario = Usuario(usuario=clave, nombre=nombre, rol=rol, es_demo=True, activo=True)
            sesion.add(usuario)
            sesion.flush()
        usuarios[rol] = usuario
    return usuarios


def _razon(dias_vencido: int, vencimiento: date) -> str:
    if dias_vencido > 0:
        return f"Vencida hace {dias_vencido} día{'s' if dias_vencido != 1 else ''}"
    if dias_vencido == 0:
        return "Vence hoy"
    return f"Vence el {vencimiento.day} de {MESES[vencimiento.month - 1]}"


def _propuesta_pendiente(sesion: Session, capturista: Usuario, fecha_base: date) -> int:
    """Propuesta de ejemplo: las facturas más vencidas que se pueden pagar y caben en el presupuesto.

    Si el módulo de propuestas está instalado se crea con su servicio, el mismo camino que usa la API, para que
    pase por las mismas barreras. Si no, se arma aquí con las mismas reglas.
    """
    fecha_limite = fecha_base + timedelta(days=7)
    if importlib.util.find_spec("cotejo.propuestas.servicio") is not None:
        from cotejo.propuestas import servicio

        try:
            servicio.crear_propuesta(
                sesion,
                usuario=capturista,
                presupuesto_mxn=PRESUPUESTO_PROPUESTA,
                origen="api",
                hoy=fecha_base,
                fecha_limite=fecha_limite,
            )
        except servicio.ErrorPropuesta as exc:
            if exc.codigo != "PROPUESTA_VACIA":
                raise
            return 0
        return 1
    renglones = []
    total = Decimal(0)
    for candidata in consultas.facturas_elegibles(sesion, hasta=fecha_limite, ids=None, hoy=fecha_base):
        if candidata.bloqueos or candidata.saldo_mxn is None or candidata.en_propuesta_pendiente is not None:
            continue
        if total + candidata.saldo_mxn > PRESUPUESTO_PROPUESTA:
            continue
        total += candidata.saldo_mxn
        renglones.append(candidata)
        if len(renglones) == RENGLONES_PROPUESTA:
            break
    if not renglones:
        return 0
    propuesta = Propuesta(
        estado="pendiente",
        presupuesto_mxn=PRESUPUESTO_PROPUESTA,
        total_mxn=total,
        fecha_limite=fecha_limite,
        origen="api",
        creada_por=capturista.id,
        excluidas=[],
    )
    sesion.add(propuesta)
    sesion.flush()
    sesion.add_all(
        RenglonPropuesta(
            propuesta_id=propuesta.id,
            factura_id=r.factura_id,
            importe=r.saldo,
            importe_mxn=r.saldo_mxn,
            razon=_razon(r.dias_vencido, r.vencimiento),
        )
        for r in renglones
    )
    sesion.flush()
    bitacora.registrar(
        sesion,
        usuario_id=capturista.id,
        accion="PROPUESTA_CREADA",
        entidad="propuesta",
        entidad_id=propuesta.id,
        detalle={
            "presupuesto_mxn": PRESUPUESTO_PROPUESTA,
            "total_mxn": total,
            "renglones": len(renglones),
            "origen": "api",
        },
    )
    return 1


def _sembrar_documentos(sesion: Session, usuario_id: int) -> int:
    """Carga los documentos de demostración si ese módulo está instalado; si no, la semilla sigue sin ellos."""
    if importlib.util.find_spec("cotejo.documentos.semilla") is None:
        return 0
    modulo = importlib.import_module("cotejo.documentos.semilla")
    sembrar_documentos = getattr(modulo, "sembrar_documentos", None)
    if not callable(sembrar_documentos):
        return 0
    return int(sembrar_documentos(sesion, usuario_id))


def base_sin_facturas(sesion: Session) -> bool:
    return sesion.execute(select(func.count()).select_from(Factura)).scalar_one() == 0


def sembrar(
    sesion: Session,
    *,
    semilla: int,
    fecha_base: date,
    empresa_rfc: str | None = None,
    empresa_nombre: str | None = None,
    con_documentos: bool = True,
) -> ResumenSemilla:
    """Carga la demostración en la transacción en curso. No hace commit.

    Está pensada para una base sin facturas. `fecha_base` es el "hoy" de los datos: las fechas de emisión y de
    pago se calculan hacia atrás desde ahí.
    """
    config = obtener_config()
    empresa_rfc = empresa_rfc or config.empresa_rfc
    empresa_nombre = empresa_nombre or config.empresa_nombre
    usuarios = _usuarios_demo(sesion)
    capturista = usuarios["capturista"]
    ahora = datetime.combine(fecha_base, time(12, 0))
    ahora_con_zona = ahora.replace(tzinfo=ZoneInfo(config.zona_horaria))

    lista_69b.cargar(sesion, catalogo.lista_69b_csv(), archivo=ARCHIVO_LISTA, ahora=ahora_con_zona)
    bitacora.registrar(
        sesion,
        usuario_id=usuarios["aprobador"].id,
        accion="LISTA_69B_CARGADA",
        entidad="lista_69b",
        entidad_id=None,
        detalle={"archivo": ARCHIVO_LISTA, "registros": len(catalogo.renglones_lista())},
    )

    lote = generar_lote(semilla, fecha_base, empresa_rfc=empresa_rfc, empresa_nombre=empresa_nombre)
    entradas = [
        ArchivoPorIngerir(nombre=f"{c.tipo}_{c.serie}{c.folio}_{c.uuid[:8]}.xml", contenido=construir_xml(c))
        for c in lote.comprobantes
    ]
    for inicio in range(0, len(entradas), ARCHIVOS_POR_CARGA):
        resultado = ingerir_lote(
            sesion,
            usuario_id=capturista.id,
            entradas=entradas[inicio : inicio + ARCHIVOS_POR_CARGA],
            empresa_rfc=empresa_rfc,
            ahora=ahora,
        )
        rechazados = [a for a in resultado.archivos if a.resultado in ("rechazada", "duplicada")]
        if rechazados:
            motivos = "; ".join(f"{a.nombre}: {a.motivos[0].mensaje}" for a in rechazados[:3])
            raise RuntimeError(f"La semilla generó comprobantes que la carga no aceptó: {motivos}")

    for proveedor in PROVEEDORES:
        sesion.execute(
            update(Proveedor).where(Proveedor.rfc == proveedor.rfc).values(dias_credito=proveedor.dias_credito)
        )
    if con_documentos:
        _sembrar_documentos(sesion, capturista.id)
    _propuesta_pendiente(sesion, capturista, fecha_base)
    sesion.flush()
    return resumen(sesion)


def resumen(sesion: Session) -> ResumenSemilla:
    def contar(consulta: Select[int]) -> int:
        return sesion.execute(consulta).scalar_one()

    por_tipo = dict(sesion.execute(select(Factura.tipo, func.count()).group_by(Factura.tipo)).all())
    return ResumenSemilla(
        proveedores=contar(select(func.count()).select_from(Proveedor)),
        facturas=por_tipo.get("I", 0),
        notas_credito=por_tipo.get("E", 0),
        complementos_pago=por_tipo.get("P", 0),
        alertas_abiertas=contar(select(func.count()).select_from(Alerta).where(Alerta.estado == "abierta")),
        propuestas_pendientes=contar(
            select(func.count()).select_from(Propuesta).where(Propuesta.estado == "pendiente")
        ),
        documentos=contar(select(func.count()).select_from(Documento)),
        cargas=contar(select(func.count()).select_from(Carga)),
    )


def vaciar(sesion: Session) -> None:
    """Borra todos los datos de negocio y reinicia los identificadores. Conserva usuarios y cuotas."""
    tablas = sorted(t.name for t in Base.metadata.sorted_tables if t.name not in TABLAS_QUE_SE_CONSERVAN)
    sesion.execute(text(f"TRUNCATE TABLE {', '.join(tablas)} RESTART IDENTITY CASCADE"))
    sesion.expire_all()


def reiniciar_demo(
    sesion: Session,
    *,
    semilla: int,
    fecha_base: date,
    empresa_rfc: str | None = None,
    empresa_nombre: str | None = None,
    con_documentos: bool = True,
) -> ResumenSemilla:
    """Deja la base como recién sembrada, en una sola transacción. No hace commit."""
    vaciar(sesion)
    return sembrar(
        sesion,
        semilla=semilla,
        fecha_base=fecha_base,
        empresa_rfc=empresa_rfc,
        empresa_nombre=empresa_nombre,
        con_documentos=con_documentos,
    )
