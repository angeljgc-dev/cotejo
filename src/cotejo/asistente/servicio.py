"""Servicio del asistente: cuotas, conversación, bucle de herramientas y registro de cada respuesta (D7, D10).

De cada respuesta se guarda qué herramientas se usaron, con qué argumentos y qué devolvieron, las facturas en
que se basa, las citas válidas y las advertencias. La interfaz muestra "cómo lo calculé" con esos datos, no con
lo que el modelo diga de sí mismo.
"""

from __future__ import annotations

import time
import uuid as uuid_mod
from collections.abc import Sequence
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from cotejo.api.dependencias import ConfigApp, Visitante
from cotejo.asistente import bucle
from cotejo.asistente.cliente_modelo import ClienteModelo, ErrorModelo, MensajeModelo, cliente_de_config
from cotejo.asistente.herramientas import ContextoHerramienta, Json, resumir
from cotejo.asistente.prompt import VERSION_PROMPT
from cotejo.config import Settings
from cotejo.cxp import consultas
from cotejo.cxp.consultas import ProveedorCorto
from cotejo.dinero import Importe
from cotejo.fechas import hoy
from cotejo.modelos import Conversacion, Documento, Fragmento, MensajeChat, Propuesta, Usuario
from cotejo.seguridad import cuotas

MENSAJES_DE_HISTORIAL = 6
MAX_CARACTERES_HISTORIAL = 2000
MAX_BYTES_RESULTADO_GUARDADO = 20_000
MAX_FACTURAS_BASE = 50
MOTIVO_SIN_LLAVE = "El asistente no está configurado en esta instalación. El resto de Cotejo funciona normalmente."


class ErrorAsistente(Exception):
    """Error del asistente con el estado HTTP y el código del contrato de la API."""

    def __init__(self, estado: int, codigo: str, mensaje: str, detalle: dict[str, object] | None = None) -> None:
        super().__init__(mensaje)
        self.estado = estado
        self.codigo = codigo
        self.mensaje = mensaje
        self.detalle: dict[str, object] = detalle or {}


class EstadoAsistente(BaseModel):
    disponible: bool
    motivo: str | None
    modelo: str | None
    restantes_hoy: int
    limite_dia: int


class HerramientaUsada(BaseModel):
    nombre: str
    argumentos: dict[str, object]
    resumen: str
    duracion_ms: int
    error: str | None


class FacturaBase(BaseModel):
    id: int
    uuid: str
    serie: str | None
    folio: str | None
    proveedor: ProveedorCorto
    moneda: str
    saldo: Importe | None


class Cita(BaseModel):
    fragmento_id: int
    documento_id: int
    documento: str
    pagina: int


class Advertencia(BaseModel):
    codigo: str
    mensaje: str


class MensajeSalida(BaseModel):
    id: int
    conversacion_id: uuid_mod.UUID
    rol: Literal["usuario", "asistente"]
    texto: str
    creado_en: datetime
    herramientas: list[HerramientaUsada] = Field(default_factory=list)
    facturas_base: list[FacturaBase] = Field(default_factory=list)
    citas: list[Cita] = Field(default_factory=list)
    propuesta_id: int | None = None
    advertencias: list[Advertencia] = Field(default_factory=list)
    modelo: str | None = None


class ConversacionSalida(BaseModel):
    id: uuid_mod.UUID
    mensajes: list[MensajeSalida]


class ConversacionCreada(BaseModel):
    id: uuid_mod.UUID


class NuevoMensaje(BaseModel):
    conversacion_id: uuid_mod.UUID | None = None
    texto: str = Field(min_length=1, max_length=2000)


def obtener_cliente_modelo(config: ConfigApp) -> ClienteModelo | None:
    """Dependencia de FastAPI: el cliente del modelo, o None si no hay llave. Las pruebas la sustituyen."""
    return cliente_de_config(config)


def _claves_de_cuota(visitante: Visitante) -> tuple[str, str, str]:
    return f"chat:v:{visitante.visitante}", f"chat:ip:{visitante.ip_hash}", "chat:global"


def restantes_hoy(sesion: Session, config: Settings, visitante: Visitante) -> int:
    """Preguntas que le quedan hoy a este visitante: el menor entre su cuota, la de su red y la global."""
    dia = hoy(config)
    por_visitante, por_ip, global_ = _claves_de_cuota(visitante)
    return min(
        cuotas.restantes(sesion, por_visitante, config.chat_limite_visitante_dia, dia),
        cuotas.restantes(sesion, por_ip, config.chat_limite_visitante_dia, dia),
        cuotas.restantes(sesion, global_, config.chat_limite_global_dia, dia),
    )


def estado(sesion: Session, config: Settings, cliente: ClienteModelo | None, visitante: Visitante) -> EstadoAsistente:
    return EstadoAsistente(
        disponible=cliente is not None,
        motivo=None if cliente is not None else MOTIVO_SIN_LLAVE,
        modelo=cliente.modelo if cliente is not None else None,
        restantes_hoy=restantes_hoy(sesion, config, visitante),
        limite_dia=config.chat_limite_visitante_dia,
    )


def _consumir_cuota(sesion: Session, config: Settings, visitante: Visitante) -> None:
    dia = hoy(config)
    por_visitante, por_ip, global_ = _claves_de_cuota(visitante)
    try:
        cuotas.consumir(sesion, por_visitante, config.chat_limite_visitante_dia, dia)
        cuotas.consumir(sesion, por_ip, config.chat_limite_visitante_dia, dia)
    except cuotas.CuotaAgotada as exc:
        raise ErrorAsistente(
            429,
            "LIMITE_CHAT",
            f"Llegaste al límite de {exc.limite} preguntas por día de esta demostración. Vuelve mañana.",
            exc.detalle(config.zona_horaria),
        ) from exc
    try:
        cuotas.consumir(sesion, global_, config.chat_limite_global_dia, dia)
    except cuotas.CuotaAgotada as exc:
        raise ErrorAsistente(
            429,
            "LIMITE_CHAT",
            "El asistente de la demostración ya atendió todas las preguntas que tiene disponibles por hoy. "
            "El resto de Cotejo sigue funcionando.",
            exc.detalle(config.zona_horaria),
        ) from exc


def crear_conversacion(sesion: Session, usuario: Usuario, visitante: Visitante) -> Conversacion:
    conversacion = Conversacion(usuario_id=usuario.id, visitante=visitante.visitante)
    sesion.add(conversacion)
    sesion.flush()
    return conversacion


def _conversacion_propia(
    sesion: Session, conversacion_id: uuid_mod.UUID, usuario: Usuario, visitante: Visitante
) -> Conversacion:
    """La conversación solo existe para quien la abrió: mismo usuario y mismo visitante de la demostración."""
    conversacion = sesion.get(Conversacion, conversacion_id)
    if conversacion is None or conversacion.usuario_id != usuario.id or conversacion.visitante != visitante.visitante:
        raise ErrorAsistente(404, "CONVERSACION_NO_ENCONTRADA", "La conversación no existe.")
    return conversacion


def _historial(sesion: Session, conversacion_id: uuid_mod.UUID) -> list[MensajeModelo]:
    """Últimos mensajes de texto de la conversación, sin resultados de herramientas, en orden cronológico."""
    recientes = sesion.scalars(
        select(MensajeChat)
        .where(MensajeChat.conversacion_id == conversacion_id, MensajeChat.error.is_(None))
        .order_by(MensajeChat.id.desc())
        .limit(MENSAJES_DE_HISTORIAL)
    ).all()
    return [
        MensajeModelo("user" if m.rol == "usuario" else "assistant", m.texto[:MAX_CARACTERES_HISTORIAL])
        for m in reversed(recientes)
    ]


def _resultado_para_guardar(resultado: Json) -> Json:
    if len(bucle.a_json_compacto(resultado).encode("utf-8")) <= MAX_BYTES_RESULTADO_GUARDADO:
        return resultado
    return bucle.recortar(resultado, MAX_BYTES_RESULTADO_GUARDADO // 4)


def _facturas_base(sesion: Session, ids: Sequence[int], config: Settings) -> list[FacturaBase]:
    if not ids:
        return []
    acotados = list(ids)[:MAX_FACTURAS_BASE]
    por_id = {f.factura_id: f for f in consultas.facturas_elegibles(sesion, hasta=None, ids=acotados, hoy=hoy(config))}
    return [
        FacturaBase(
            id=f.factura_id,
            uuid=f.uuid,
            serie=f.serie,
            folio=f.folio,
            proveedor=f.proveedor,
            moneda=f.moneda,
            saldo=f.saldo if f.tipo == "I" else None,
        )
        for f in (por_id[i] for i in acotados if i in por_id)
    ]


def _citas(sesion: Session, guardadas: Sequence[object]) -> list[Cita]:
    """Citas guardadas con el nombre actual del documento. Una cita a un documento borrado se omite."""
    ids = [int(c["fragmento_id"]) for c in guardadas if isinstance(c, dict) and "fragmento_id" in c]
    if not ids:
        return []
    filas = sesion.execute(
        select(Fragmento.id, Fragmento.documento_id, Documento.nombre, Fragmento.pagina)
        .join(Documento, Documento.id == Fragmento.documento_id)
        .where(Fragmento.id.in_(ids))
    ).all()
    por_id = {f.id: f for f in filas}
    return [
        Cita(fragmento_id=i, documento_id=por_id[i].documento_id, documento=por_id[i].nombre, pagina=por_id[i].pagina)
        for i in ids
        if i in por_id
    ]


def a_salida(sesion: Session, mensaje: MensajeChat, config: Settings) -> MensajeSalida:
    herramientas = [
        HerramientaUsada(
            nombre=str(h.get("nombre", "")),
            argumentos=h["argumentos"] if isinstance(h.get("argumentos"), dict) else {},
            resumen=str(h.get("resumen", "")),
            duracion_ms=int(h.get("duracion_ms") or 0),
            error=h.get("error") if isinstance(h.get("error"), str) else None,
        )
        for h in mensaje.herramientas
        if isinstance(h, dict)
    ]
    return MensajeSalida(
        id=mensaje.id,
        conversacion_id=mensaje.conversacion_id,
        rol="usuario" if mensaje.rol == "usuario" else "asistente",
        texto=mensaje.texto,
        creado_en=mensaje.creado_en,
        herramientas=herramientas,
        facturas_base=_facturas_base(sesion, mensaje.facturas_base, config),
        citas=_citas(sesion, mensaje.citas),
        propuesta_id=mensaje.propuesta_id,
        advertencias=[
            Advertencia(codigo=str(a.get("codigo", "")), mensaje=str(a.get("mensaje", "")))
            for a in mensaje.advertencias
            if isinstance(a, dict)
        ],
        modelo=mensaje.modelo,
    )


def ver_conversacion(
    sesion: Session, conversacion_id: uuid_mod.UUID, usuario: Usuario, visitante: Visitante, config: Settings
) -> ConversacionSalida:
    conversacion = _conversacion_propia(sesion, conversacion_id, usuario, visitante)
    mensajes = sesion.scalars(
        select(MensajeChat).where(MensajeChat.conversacion_id == conversacion.id).order_by(MensajeChat.id)
    ).all()
    return ConversacionSalida(id=conversacion.id, mensajes=[a_salida(sesion, m, config) for m in mensajes])


def conversacion_reciente(
    sesion: Session, usuario: Usuario, visitante: Visitante, config: Settings
) -> ConversacionSalida | None:
    """La conversación más reciente de este usuario y visitante, para no perder el chat al recargar la página."""
    conversacion_id = sesion.scalar(
        select(Conversacion.id)
        .join(MensajeChat, MensajeChat.conversacion_id == Conversacion.id)
        .where(Conversacion.usuario_id == usuario.id, Conversacion.visitante == visitante.visitante)
        .order_by(MensajeChat.id.desc())
        .limit(1)
    )
    if conversacion_id is None:
        return None
    return ver_conversacion(sesion, conversacion_id, usuario, visitante, config)


def responder(
    sesion: Session,
    *,
    config: Settings,
    cliente: ClienteModelo | None,
    usuario: Usuario,
    visitante: Visitante,
    conversacion_id: uuid_mod.UUID | None,
    texto: str,
) -> MensajeSalida:
    """Atiende una pregunta de punta a punta y devuelve el mensaje del asistente ya guardado.

    La cuota y la pregunta de la persona se confirman antes de llamar al modelo: así cuentan aunque el proveedor
    falle. Si el proveedor falla, lo que las herramientas hayan escrito en este turno se deshace.
    """
    if cliente is None:
        raise ErrorAsistente(503, "ASISTENTE_NO_CONFIGURADO", MOTIVO_SIN_LLAVE)
    conversacion = (
        _conversacion_propia(sesion, conversacion_id, usuario, visitante)
        if conversacion_id is not None
        else crear_conversacion(sesion, usuario, visitante)
    )
    _consumir_cuota(sesion, config, visitante)
    historial = _historial(sesion, conversacion.id)
    pregunta = MensajeChat(conversacion_id=conversacion.id, rol="usuario", texto=texto)
    sesion.add(pregunta)
    sesion.commit()

    ctx = ContextoHerramienta(
        sesion=sesion,
        usuario=usuario,
        hoy=hoy(config),
        origen="asistente",
        config=config,
        # Solo cuentan la pregunta actual y la anterior de la persona: una petición vieja no autoriza nada.
        dicho_por_la_persona=(*[m.contenido or "" for m in historial if m.rol == "user"][-1:], texto),
    )
    inicio = time.perf_counter()
    turno = sesion.begin_nested()
    try:
        resultado = bucle.ejecutar(cliente, ctx, pregunta=texto, historial=historial)
    except ErrorModelo as exc:
        turno.rollback()
        pregunta.error = exc.codigo
        sesion.commit()
        raise ErrorAsistente(502, "MODELO_NO_DISPONIBLE", exc.mensaje, {"causa": exc.codigo}) from exc
    except BaseException:
        turno.rollback()
        raise
    turno.commit()

    respuesta = MensajeChat(
        conversacion_id=conversacion.id,
        rol="asistente",
        texto=resultado.texto,
        herramientas=[
            {
                "nombre": uso.nombre,
                "argumentos": uso.argumentos,
                "resultado": _resultado_para_guardar(uso.resultado),
                "error": uso.error,
                "duracion_ms": uso.duracion_ms,
                "resumen": resumir(uso.nombre, uso.resultado, uso.error),
            }
            for uso in resultado.herramientas
        ],
        facturas_base=resultado.factura_ids,
        citas=[
            {"fragmento_id": i, "documento_id": resultado.fragmentos[i][0], "pagina": resultado.fragmentos[i][2]}
            for i in resultado.citas
        ],
        advertencias=list(resultado.advertencias),
        propuesta_id=resultado.propuesta_id,
        modelo=resultado.modelo,
        version_prompt=VERSION_PROMPT,
        pasos=resultado.pasos,
        tokens_entrada=resultado.tokens_entrada,
        tokens_salida=resultado.tokens_salida,
        latencia_ms=int((time.perf_counter() - inicio) * 1000),
    )
    sesion.add(respuesta)
    sesion.flush()
    if resultado.propuesta_id is not None:
        propuesta = sesion.get(Propuesta, resultado.propuesta_id)
        if propuesta is not None:
            # La propuesta queda ligada al mensaje que la originó (sigue pendiente, así que aún se puede editar).
            propuesta.mensaje_id = respuesta.id
            sesion.flush()
    return a_salida(sesion, respuesta, config)
