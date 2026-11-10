"""Herramientas del asistente y del servidor MCP: todas leen, salvo `proponer_pagos`. Ninguna aprueba ni paga.

Cada herramienta consulta la base con código propio y devuelve las cifras ya calculadas (D1): el modelo de
lenguaje solo elige cuál usar y redacta. El texto que viene de terceros (nombres, conceptos, fragmentos de
documentos) se entrega únicamente en campos cuyo nombre termina en `no_confiable`, limpio y recortado (D6).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal, TypeVar

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from cotejo.asistente import esquemas
from cotejo.asistente.cliente_modelo import EsquemaHerramienta
from cotejo.asistente.verificacion import pide_propuesta, presupuestos_dichos
from cotejo.config import Settings
from cotejo.cxp import consultas
from cotejo.cxp.consultas import FacturaResumen, ProveedorCorto
from cotejo.dinero import a_decimal, texto
from cotejo.documentos.busqueda import buscar
from cotejo.documentos.embeddings import obtener_embedder
from cotejo.documentos.normalizar import quitar_controles
from cotejo.fechas import rango_horizonte
from cotejo.modelos import Alerta, Aplicacion, Concepto, Factura, Usuario
from cotejo.propuestas import servicio as propuestas

Json = dict[str, object]
A = TypeVar("A", bound=esquemas.Argumentos)

LIMITE_TEXTO_NO_CONFIABLE = 1500
LIMITE_NOMBRE = 120
LIMITE_IDENTIFICADOR = 40
MAX_FACTURAS_VENCIMIENTOS = 30
MAX_CONCEPTOS = 30
MAX_APLICACIONES = 30
MAX_EXCLUIDAS_DETALLADAS = 10


@dataclass(frozen=True)
class ContextoHerramienta:
    """Quién pregunta y cuándo. Sale de la sesión, nunca de los argumentos que escribe el modelo."""

    sesion: Session
    usuario: Usuario
    hoy: date
    origen: Literal["asistente", "mcp"]
    config: Settings
    # En el chat: los mensajes recientes de la persona. Una propuesta y su presupuesto deben venir de ahí.
    dicho_por_la_persona: tuple[str, ...] | None = None


@dataclass(frozen=True)
class ResultadoHerramienta:
    datos: Json
    # Facturas en que se basa el resultado: alimentan "cómo lo calculé".
    factura_ids: tuple[int, ...] = ()
    # Fragmentos devueltos: los únicos que el asistente puede citar en este turno.
    fragmentos: Mapping[int, tuple[int, str, int]] = field(default_factory=dict)
    propuesta_id: int | None = None


class ErrorHerramienta(Exception):
    """La herramienta no pudo atender la petición; el mensaje se devuelve al modelo como `error`."""

    def __init__(self, mensaje: str, detalle: Json | None = None) -> None:
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.detalle: Json = detalle or {}


@dataclass(frozen=True)
class Herramienta:
    nombre: str
    descripcion: str
    argumentos: type[esquemas.Argumentos]
    # Valida los argumentos (lanza pydantic.ValidationError) y ejecuta.
    ejecutar: Callable[[ContextoHerramienta, Mapping[str, object]], ResultadoHerramienta]

    @property
    def esquema(self) -> EsquemaHerramienta:
        return EsquemaHerramienta(self.nombre, self.descripcion, esquemas.esquema_json(self.argumentos))


def texto_externo(valor: str | None, limite: int = LIMITE_TEXTO_NO_CONFIABLE) -> str:
    """Texto de terceros listo para entregarse como dato: sin caracteres de control, en una línea y recortado."""
    limpio = " ".join(quitar_controles(valor or "").split())
    return limpio if len(limpio) <= limite else limpio[: limite - 1].rstrip() + "…"


def _proveedor(proveedor: ProveedorCorto) -> Json:
    return {
        "proveedor_id": proveedor.id,
        "rfc": texto_externo(proveedor.rfc, LIMITE_IDENTIFICADOR),
        "nombre_no_confiable": texto_externo(proveedor.nombre, LIMITE_NOMBRE),
    }


def _importe(valor: Decimal | None) -> str | None:
    return None if valor is None else texto(valor)


def _factura(factura: FacturaResumen) -> Json:
    return {
        "factura_id": factura.id,
        "uuid": factura.uuid,
        "serie_no_confiable": texto_externo(factura.serie, LIMITE_IDENTIFICADOR) or None,
        "folio_no_confiable": texto_externo(factura.folio, LIMITE_IDENTIFICADOR) or None,
        "proveedor": _proveedor(factura.proveedor),
        "fecha_emision": factura.fecha_emision.date().isoformat(),
        "vencimiento": factura.vencimiento.isoformat() if factura.vencimiento else None,
        "dias_vencido": factura.dias_vencido,
        "moneda": factura.moneda,
        "total": texto(factura.total),
        "saldo": _importe(factura.saldo),
        "saldo_mxn": _importe(factura.saldo_mxn),
        "alertas_abiertas": factura.alertas_abiertas,
        # Verdadero si tiene una alerta bloqueante propia o de su proveedor (lista 69-B): no se puede pagar.
        "bloqueada_para_pago": factura.tiene_bloqueante,
    }


def buscar_proveedores(ctx: ContextoHerramienta, args: esquemas.BuscarProveedores) -> ResultadoHerramienta:
    encontrados = consultas.buscar_proveedores(ctx.sesion, texto=args.texto, rfc=args.rfc, limite=args.limite)
    return ResultadoHerramienta(
        {
            "proveedores": [
                {
                    "proveedor_id": p.id,
                    "rfc": texto_externo(p.rfc, LIMITE_IDENTIFICADOR),
                    "nombre_no_confiable": texto_externo(p.nombre, LIMITE_NOMBRE),
                    "dias_credito": p.dias_credito,
                    "adeudo_mxn": texto(p.adeudo_mxn),
                    "facturas_con_saldo": p.facturas_con_saldo,
                    "situacion_69b": p.situacion_69b,
                }
                for p in encontrados
            ]
        }
    )


def adeudo_proveedor(ctx: ContextoHerramienta, args: esquemas.AdeudoProveedor) -> ResultadoHerramienta:
    try:
        adeudo = consultas.adeudo_proveedor(ctx.sesion, args.proveedor_id, ctx.hoy)
    except consultas.ProveedorNoEncontrado as exc:
        raise ErrorHerramienta(f"No existe el proveedor {args.proveedor_id}. Búscalo con buscar_proveedores.") from exc
    return ResultadoHerramienta(
        {
            "proveedor": _proveedor(adeudo.proveedor),
            "adeudo_mxn": texto(adeudo.adeudo_mxn),
            "adeudo_por_moneda": [
                {"moneda": m.moneda, "saldo": texto(m.saldo), "saldo_mxn": _importe(m.saldo_mxn)}
                for m in adeudo.adeudo_por_moneda
            ],
            "facturas": [_factura(f) for f in adeudo.facturas],
            "facturas_bloqueadas": sum(1 for f in adeudo.facturas if f.tiene_bloqueante),
            "facturas_omitidas": adeudo.facturas_omitidas,
        },
        factura_ids=tuple(f.id for f in adeudo.facturas),
    )


def listar_facturas(ctx: ContextoHerramienta, args: esquemas.ListarFacturas) -> ResultadoHerramienta:
    filtros = consultas.FiltrosFacturas(
        proveedor_id=args.proveedor_id,
        estado=args.estado or "todas",
        vence_desde=args.vence_desde,
        vence_hasta=args.vence_hasta,
        con_alertas=args.con_alertas,
        por_pagina=args.limite,
    )
    pagina = consultas.listar_facturas(ctx.sesion, filtros, ctx.hoy)
    return ResultadoHerramienta(
        {
            "facturas": [_factura(f) for f in pagina.elementos],
            "conteo_total": pagina.total,
            "saldo_total_mxn": texto(pagina.saldo_total_mxn),
        },
        factura_ids=tuple(f.id for f in pagina.elementos),
    )


def vencimientos(ctx: ContextoHerramienta, args: esquemas.Vencimientos) -> ResultadoHerramienta:
    desde, hasta = rango_horizonte(args.horizonte, ctx.hoy)
    resumen = consultas.vencimientos(ctx.sesion, desde, hasta, ctx.hoy, limite=MAX_FACTURAS_VENCIMIENTOS)
    return ResultadoHerramienta(
        {
            "desde": desde.isoformat() if desde else None,
            "hasta": hasta.isoformat(),
            "facturas": [_factura(f) for f in resumen.facturas],
            "saldo_total_mxn": texto(resumen.saldo_total_mxn),
            "conteo": resumen.conteo,
            "facturas_omitidas": resumen.conteo - len(resumen.facturas),
        },
        factura_ids=tuple(f.id for f in resumen.facturas),
    )


def totales_por_mes(ctx: ContextoHerramienta, args: esquemas.TotalesPorMes) -> ResultadoHerramienta:
    try:
        meses = consultas.totales_por_mes(
            ctx.sesion,
            medida=args.medida,
            desde_mes=args.desde_mes,
            hasta_mes=args.hasta_mes,
            proveedor_id=args.proveedor_id,
        )
    except ValueError as exc:
        raise ErrorHerramienta(str(exc)) from exc
    return ResultadoHerramienta(
        {
            "medida": args.medida,
            "meses": [{"mes": m.mes, "total_mxn": texto(m.total_mxn), "conteo": m.conteo} for m in meses],
            # La suma del periodo se entrega hecha: el modelo no suma los meses.
            "total_mxn": texto(sum((m.total_mxn for m in meses), Decimal(0))),
        }
    )


def antiguedad_saldos(ctx: ContextoHerramienta, args: esquemas.AntiguedadSaldos) -> ResultadoHerramienta:
    antiguedad = consultas.antiguedad(ctx.sesion, ctx.hoy)
    return ResultadoHerramienta(
        {
            "fecha_corte": antiguedad.fecha_corte.isoformat(),
            "grupos": [
                {"grupo": g.grupo, "etiqueta": g.etiqueta, "saldo_mxn": texto(g.saldo_mxn), "facturas": g.facturas}
                for g in antiguedad.grupos
            ],
            "adeudo_total_mxn": texto(antiguedad.adeudo_total_mxn),
        }
    )


def detalle_factura(ctx: ContextoHerramienta, args: esquemas.DetalleFactura) -> ResultadoHerramienta:
    sesion = ctx.sesion
    if args.factura_id is not None:
        factura = sesion.get(Factura, args.factura_id)
    else:
        factura = sesion.scalar(select(Factura).where(Factura.uuid == (args.uuid or "").upper()))
    resumen = consultas.resumen_factura(sesion, factura.id, ctx.hoy) if factura is not None else None
    if factura is None or resumen is None:
        raise ErrorHerramienta("No existe una factura con ese identificador.")
    conceptos = sesion.scalars(
        select(Concepto).where(Concepto.factura_id == factura.id).order_by(Concepto.orden).limit(MAX_CONCEPTOS)
    ).all()
    alertas = sesion.execute(
        select(Alerta.codigo, Alerta.severidad, Alerta.mensaje)
        .where(
            Alerta.estado == "abierta",
            or_(
                Alerta.factura_id == factura.id,
                Alerta.factura_id.is_(None) & (Alerta.proveedor_id == factura.proveedor_id),
            ),
        )
        .order_by(Alerta.id)
    ).all()
    aplicaciones = sesion.execute(
        select(Aplicacion.origen, Aplicacion.importe, Aplicacion.fecha)
        .where(Aplicacion.factura_id == factura.id)
        .order_by(Aplicacion.fecha, Aplicacion.id)
        .limit(MAX_APLICACIONES)
    ).all()
    datos = _factura(resumen)
    datos.update(
        {
            "tipo": factura.tipo,
            "subtotal": texto(factura.subtotal),
            "impuestos_trasladados": _importe(factura.total_impuestos_trasladados),
            "impuestos_retenidos": _importe(factura.total_impuestos_retenidos),
            "metodo_pago": factura.metodo_pago,
            "estado_pago": resumen.estado_pago,
        }
    )
    return ResultadoHerramienta(
        {
            "factura": datos,
            "conceptos": [
                {"descripcion_no_confiable": texto_externo(c.descripcion), "importe": texto(c.importe)}
                for c in conceptos
            ],
            "alertas": [
                {"codigo": a.codigo, "severidad": a.severidad, "mensaje_no_confiable": texto_externo(a.mensaje, 300)}
                for a in alertas
            ],
            "aplicaciones": [
                {"origen": a.origen, "importe": texto(a.importe), "fecha": a.fecha.isoformat()} for a in aplicaciones
            ],
        },
        factura_ids=(factura.id,),
    )


def buscar_documentos(ctx: ContextoHerramienta, args: esquemas.BuscarDocumentos) -> ResultadoHerramienta:
    hallazgos = buscar(
        ctx.sesion,
        args.consulta,
        embedder=obtener_embedder(ctx.config),
        modo=ctx.config.busqueda_modo,
        proveedor_id=args.proveedor_id,
        k=args.k,
    )
    return ResultadoHerramienta(
        {
            "fragmentos": [
                {
                    "fragmento_id": h.fragmento_id,
                    "documento_no_confiable": texto_externo(h.documento, LIMITE_NOMBRE),
                    # None en políticas generales. Un contrato de otro proveedor no responde por el consultado.
                    "proveedor_del_documento_no_confiable": (
                        texto_externo(h.proveedor, LIMITE_NOMBRE) if h.proveedor else None
                    ),
                    "pagina": h.pagina,
                    "texto_no_confiable": texto_externo(h.texto),
                }
                for h in hallazgos
            ],
            "sin_resultados": not hallazgos,
        },
        fragmentos={h.fragmento_id: (h.documento_id, h.documento, h.pagina) for h in hallazgos},
    )


def proponer_pagos(ctx: ContextoHerramienta, args: esquemas.ProponerPagos) -> ResultadoHerramienta:
    """Única herramienta que escribe: crea una propuesta `pendiente`. Las facturas las elige el código."""
    presupuesto = a_decimal(args.presupuesto_mxn)
    if ctx.dicho_por_la_persona is not None and not pide_propuesta(ctx.dicho_por_la_persona):
        # Ningún texto de una factura o de un documento puede hacer que se arme una propuesta por su cuenta.
        raise ErrorHerramienta(
            "La persona no pidió una propuesta de pagos en su mensaje. No se crea ninguna.",
            {"codigo": "PROPUESTA_NO_PEDIDA"},
        )
    if ctx.dicho_por_la_persona is not None and presupuesto not in presupuestos_dichos(ctx.dicho_por_la_persona):
        # El modelo no decide cuánto se propone pagar: ni por error ni porque un documento se lo "ordene".
        raise ErrorHerramienta(
            "El presupuesto debe ser el importe que la persona escribió en su mensaje. Pídele que lo indique "
            "con número (por ejemplo: 50,000).",
            {"codigo": "PRESUPUESTO_NO_INDICADO", "presupuesto_mxn": texto(presupuesto)},
        )
    try:
        propuesta = propuestas.crear_propuesta(
            ctx.sesion,
            usuario=ctx.usuario,
            presupuesto_mxn=presupuesto,
            origen=ctx.origen,
            hoy=ctx.hoy,
            horizonte=args.horizonte,
            factura_ids=args.factura_ids,
            nota=texto_externo(args.nota, 300) if args.nota else None,
        )
    except propuestas.ErrorPropuesta as exc:
        excluidas = exc.detalle.get("excluidas")
        detalle: Json = {"codigo": exc.codigo, "presupuesto_mxn": texto(presupuesto)}
        if isinstance(excluidas, list):
            detalle.update(_resumen_de_excluidas(excluidas))
        raise ErrorHerramienta(exc.mensaje, detalle) from exc
    ids = [r.factura_id for r in propuesta.renglones]
    facturas = {f.factura_id: f for f in consultas.facturas_elegibles(ctx.sesion, hasta=None, ids=ids, hoy=ctx.hoy)}
    renglones: list[Json] = []
    for renglon in propuesta.renglones:
        factura = facturas[renglon.factura_id]
        renglones.append(
            {
                "factura_id": renglon.factura_id,
                "uuid": factura.uuid,
                "serie_no_confiable": texto_externo(factura.serie, LIMITE_IDENTIFICADOR) or None,
                "folio_no_confiable": texto_externo(factura.folio, LIMITE_IDENTIFICADOR) or None,
                "proveedor": _proveedor(factura.proveedor),
                "moneda": factura.moneda,
                "importe": texto(renglon.importe),
                "importe_mxn": texto(renglon.importe_mxn),
                "razon": renglon.razon,
            }
        )
    return ResultadoHerramienta(
        {
            "propuesta_id": propuesta.id,
            "estado": propuesta.estado,
            "aviso": "La propuesta quedó pendiente. Nada se ha pagado: debe aprobarla una persona con rol aprobador.",
            "presupuesto_mxn": texto(propuesta.presupuesto_mxn),
            "total_mxn": texto(propuesta.total_mxn),
            "fecha_limite": propuesta.fecha_limite.isoformat(),
            "renglones": renglones,
            **_resumen_de_excluidas(propuesta.excluidas),
        },
        factura_ids=tuple(ids),
        propuesta_id=propuesta.id,
    )


def _resumen_de_excluidas(excluidas: Sequence[object]) -> Json:
    """Las facturas excluidas, acotadas: el conteo por motivo completo y el detalle de las primeras.

    Con un presupuesto chico casi todo queda fuera por no caber; listar cien facturas no le sirve al modelo y
    gasta su contexto. Primero van las excluidas por una barrera distinta del presupuesto, que son las que hay
    que explicar.
    """
    limpias = [_excluida(e) for e in excluidas if isinstance(e, dict)]
    por_codigo: dict[str, int] = {}
    for excluida in limpias:
        codigo = str(excluida["codigo"])
        por_codigo[codigo] = por_codigo.get(codigo, 0) + 1
    ordenadas = sorted(limpias, key=lambda e: e["codigo"] == "EXCEDE_PRESUPUESTO")
    return {
        "excluidas": ordenadas[:MAX_EXCLUIDAS_DETALLADAS],
        "excluidas_por_codigo": por_codigo,
        "excluidas_omitidas": max(len(limpias) - MAX_EXCLUIDAS_DETALLADAS, 0),
    }


def _excluida(excluida: object) -> Json:
    if not isinstance(excluida, dict):
        return {}
    return {
        "factura_id": excluida.get("factura_id"),
        "folio_no_confiable": texto_externo(str(excluida.get("folio") or ""), LIMITE_IDENTIFICADOR) or None,
        "proveedor_no_confiable": texto_externo(str(excluida.get("proveedor_nombre") or ""), LIMITE_NOMBRE) or None,
        "codigo": excluida.get("codigo"),
        "saldo_mxn": excluida.get("saldo_mxn"),
        # El motivo puede repetir texto de la factura (serie, folio, nombre): también es dato.
        "motivo_no_confiable": texto_externo(str(excluida.get("motivo") or ""), 300),
    }


def _herramienta(
    nombre: str,
    descripcion: str,
    argumentos: type[A],
    funcion: Callable[[ContextoHerramienta, A], ResultadoHerramienta],
) -> Herramienta:
    def ejecutar(ctx: ContextoHerramienta, crudos: Mapping[str, object]) -> ResultadoHerramienta:
        return funcion(ctx, argumentos.model_validate(dict(crudos)))

    return Herramienta(nombre=nombre, descripcion=descripcion, argumentos=argumentos, ejecutar=ejecutar)


_LISTA: tuple[Herramienta, ...] = (
    _herramienta(
        "buscar_proveedores",
        "Busca proveedores por nombre o RFC para obtener su id, días de crédito y situación 69-B. Para responder "
        "cuánto se le debe a uno, usa después adeudo_proveedor con ese id.",
        esquemas.BuscarProveedores,
        buscar_proveedores,
    ),
    _herramienta(
        "adeudo_proveedor",
        "Cuánto se le debe a un proveedor: adeudo total en pesos, por moneda, y sus facturas con saldo.",
        esquemas.AdeudoProveedor,
        adeudo_proveedor,
    ),
    _herramienta(
        "listar_facturas",
        "Lista facturas con filtros (proveedor, estado, rango de vencimiento, con alertas). Incluye el saldo total "
        "en pesos de todas las que cumplen el filtro.",
        esquemas.ListarFacturas,
        listar_facturas,
    ),
    _herramienta(
        "vencimientos",
        "Facturas con saldo que vencen en un horizonte (vencidas, esta semana, próximos 7 o 30 días), con su total.",
        esquemas.Vencimientos,
        vencimientos,
    ),
    _herramienta(
        "totales_por_mes",
        "Total facturado, pagado o saldo por mes de emisión, en pesos, con la suma del periodo ya calculada.",
        esquemas.TotalesPorMes,
        totales_por_mes,
    ),
    _herramienta(
        "antiguedad_saldos",
        "Antigüedad de saldos: adeudo por vencer y vencido de 1 a 30, 31 a 60, 61 a 90 y más de 90 días, y el total.",
        esquemas.AntiguedadSaldos,
        antiguedad_saldos,
    ),
    _herramienta(
        "detalle_factura",
        "Detalle de una factura por id o UUID: importes, conceptos, alertas abiertas y pagos o notas aplicados.",
        esquemas.DetalleFactura,
        detalle_factura,
    ),
    _herramienta(
        "buscar_documentos",
        "Busca en contratos y políticas cargados (plazo de pago, mora, descuentos, vigencia). Devuelve fragmentos "
        "con su fragmento_id para citarlos.",
        esquemas.BuscarDocumentos,
        buscar_documentos,
    ),
    _herramienta(
        "proponer_pagos",
        "Crea una propuesta de pago PENDIENTE con un presupuesto en pesos. El sistema elige las facturas y aplica "
        "las barreras. No paga ni aprueba: eso lo decide después una persona con rol aprobador.",
        esquemas.ProponerPagos,
        proponer_pagos,
    ),
)

HERRAMIENTAS: dict[str, Herramienta] = {h.nombre: h for h in _LISTA}
HERRAMIENTA_QUE_ESCRIBE = "proponer_pagos"


def herramientas_por_nombre() -> dict[str, Herramienta]:
    return {h.nombre: h for h in _LISTA}


def herramientas_para(usuario: Usuario) -> list[Herramienta]:
    """Las herramientas que se le ofrecen al modelo según el rol: solo un capturista puede proponer pagos."""
    return [h for h in _LISTA if h.nombre != HERRAMIENTA_QUE_ESCRIBE or usuario.rol == "capturista"]


def resumir(nombre: str, datos: Mapping[str, object], error: str | None) -> str:
    """Una línea en español de lo que devolvió la herramienta, para "cómo lo calculé" en la interfaz."""
    if error:
        return f"No se pudo completar: {error}"

    def cuantos(clave: str) -> int:
        valor = datos.get(clave)
        return len(valor) if isinstance(valor, list) else 0

    if nombre == "buscar_proveedores":
        return f"{cuantos('proveedores')} proveedores encontrados"
    if nombre == "adeudo_proveedor":
        return f"Adeudo de {datos.get('adeudo_mxn')} MXN en {cuantos('facturas')} facturas con saldo"
    if nombre == "listar_facturas":
        return f"{datos.get('conteo_total')} facturas; saldo total {datos.get('saldo_total_mxn')} MXN"
    if nombre == "vencimientos":
        return f"{datos.get('conteo')} facturas por {datos.get('saldo_total_mxn')} MXN hasta el {datos.get('hasta')}"
    if nombre == "totales_por_mes":
        return f"Total {datos.get('medida')} de {cuantos('meses')} meses: {datos.get('total_mxn')} MXN"
    if nombre == "antiguedad_saldos":
        return f"Adeudo total de {datos.get('adeudo_total_mxn')} MXN en {cuantos('grupos')} grupos de antigüedad"
    if nombre == "detalle_factura":
        return f"Detalle de una factura con {cuantos('conceptos')} conceptos y {cuantos('alertas')} alertas abiertas"
    if nombre == "buscar_documentos":
        return f"{cuantos('fragmentos')} fragmentos de documentos"
    if nombre == "proponer_pagos":
        por_codigo = datos.get("excluidas_por_codigo")
        excluidas = sum(v for v in por_codigo.values() if isinstance(v, int)) if isinstance(por_codigo, dict) else 0
        return (
            f"Propuesta {datos.get('propuesta_id')} pendiente por {datos.get('total_mxn')} MXN con "
            f"{cuantos('renglones')} facturas; {excluidas} excluidas"
        )
    return "Consulta realizada"
