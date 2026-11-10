"""Sesión (demo y contraseña) y configuración visible para la interfaz."""

from __future__ import annotations

import secrets
import time
from datetime import date
from typing import Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from cotejo import bitacora, fechas
from cotejo.api.dependencias import ConfigApp, SesionDb, UsuarioActual, VisitanteActual
from cotejo.api.errores import ErrorApi
from cotejo.config import ARCHIVOS_POR_CARGA, MB_POR_DOCUMENTO, MB_POR_XML, Settings
from cotejo.modelos import Usuario
from cotejo.seguridad import cuotas
from cotejo.seguridad.contrasenas import verificar_contrasena
from cotejo.seguridad.sesion import DURACION_S, NOMBRE_COOKIE, DatosSesion, crear_token

router = APIRouter(tags=["sesion"])

INTENTOS_POR_MINUTO = 5
USUARIOS_DEMO: dict[str, tuple[str, str]] = {
    "capturista": ("demo.capturista", "Capturista de demostración"),
    "aprobador": ("demo.aprobador", "Aprobador de demostración"),
}


class UsuarioSalida(BaseModel):
    id: int
    usuario: str
    nombre: str
    rol: Literal["capturista", "aprobador"]
    es_demo: bool


class EntradaDemo(BaseModel):
    rol: Literal["capturista", "aprobador"]


class EntradaContrasena(BaseModel):
    usuario: str = Field(min_length=1, max_length=40)
    contrasena: str = Field(min_length=1, max_length=200)


class Limites(BaseModel):
    chat_por_dia: int
    archivos_por_carga: int
    mb_por_xml: int
    mb_por_documento: int


class ConfiguracionSalida(BaseModel):
    empresa_rfc: str
    empresa_nombre: str
    modo_demo: bool
    aviso_demo: str | None
    hoy: date
    zona_horaria: str
    limites: Limites


def _salida(usuario: Usuario) -> UsuarioSalida:
    return UsuarioSalida.model_validate(
        {
            "id": usuario.id,
            "usuario": usuario.usuario,
            "nombre": usuario.nombre,
            "rol": usuario.rol,
            "es_demo": usuario.es_demo,
        }
    )


def _iniciar(sesion: Session, respuesta: Response, config: Settings, usuario: Usuario, via: str) -> UsuarioSalida:
    datos = DatosSesion(
        usuario_id=usuario.id, visitante=secrets.token_urlsafe(16), expira=int(time.time()) + DURACION_S
    )
    respuesta.set_cookie(
        NOMBRE_COOKIE,
        crear_token(datos, config.clave_firma()),
        max_age=DURACION_S,
        httponly=True,
        samesite="lax",
        secure=config.cookie_segura,
        path="/",
    )
    bitacora.registrar(
        sesion,
        usuario_id=usuario.id,
        accion="SESION_INICIADA",
        entidad="usuario",
        entidad_id=usuario.id,
        detalle={"via": via},
    )
    return _salida(usuario)


def asegurar_usuario_demo(sesion: Session, rol: Literal["capturista", "aprobador"]) -> Usuario:
    """Devuelve el usuario de demo del rol, creándolo si la base todavía no lo tiene."""
    clave, nombre = USUARIOS_DEMO[rol]
    usuario = sesion.scalar(select(Usuario).where(Usuario.usuario == clave))
    if usuario is None:
        usuario = Usuario(usuario=clave, nombre=nombre, rol=rol, es_demo=True, activo=True)
        sesion.add(usuario)
        sesion.flush()
    return usuario


@router.post("/sesion/demo", response_model=UsuarioSalida)
def entrar_demo(entrada: EntradaDemo, respuesta: Response, sesion: SesionDb, config: ConfigApp) -> UsuarioSalida:
    if not config.demo_habilitada:
        raise ErrorApi(404, "DEMO_DESHABILITADA", "El modo de demostración no está habilitado en esta instalación.")
    usuario = asegurar_usuario_demo(sesion, entrada.rol)
    return _iniciar(sesion, respuesta, config, usuario, "demo")


@router.post("/sesion", response_model=UsuarioSalida)
def entrar_con_contrasena(
    entrada: EntradaContrasena,
    respuesta: Response,
    sesion: SesionDb,
    config: ConfigApp,
    visitante: VisitanteActual,
) -> UsuarioSalida:
    minuto = time.strftime("%Y%m%d%H%M", time.gmtime())
    try:
        cuotas.consumir(sesion, f"login:ip:{visitante.ip_hash}:{minuto}", INTENTOS_POR_MINUTO, fechas.hoy(config))
    except cuotas.CuotaAgotada as exc:
        raise ErrorApi(
            429,
            "LIMITE_INTENTOS",
            "Demasiados intentos de inicio de sesión. Espera un minuto.",
            {"limite": exc.limite},
        ) from exc
    usuario = sesion.scalar(select(Usuario).where(Usuario.usuario == entrada.usuario))
    valido = (
        usuario is not None
        and usuario.activo
        and not usuario.es_demo
        and usuario.hash_contrasena is not None
        and verificar_contrasena(entrada.contrasena, usuario.hash_contrasena)
    )
    if not valido or usuario is None:
        # El intento debe contar aunque la petición termine en error: se confirma antes de lanzar.
        sesion.commit()
        raise ErrorApi(401, "CREDENCIALES_INVALIDAS", "Usuario o contraseña incorrectos.")
    return _iniciar(sesion, respuesta, config, usuario, "contrasena")


@router.get("/sesion", response_model=UsuarioSalida)
def sesion_actual(usuario: UsuarioActual) -> UsuarioSalida:
    return _salida(usuario)


@router.delete("/sesion", status_code=204)
def salir(config: ConfigApp) -> Response:
    respuesta = Response(status_code=204)
    respuesta.delete_cookie(NOMBRE_COOKIE, path="/", httponly=True, samesite="lax", secure=config.cookie_segura)
    return respuesta


@router.get("/configuracion", response_model=ConfiguracionSalida)
def configuracion(_: UsuarioActual, config: ConfigApp) -> ConfiguracionSalida:
    return ConfiguracionSalida(
        empresa_rfc=config.empresa_rfc,
        empresa_nombre=config.empresa_nombre,
        modo_demo=config.demo_habilitada,
        aviso_demo=config.aviso_demo,
        hoy=fechas.hoy(config),
        zona_horaria=config.zona_horaria,
        limites=Limites(
            chat_por_dia=config.chat_limite_visitante_dia,
            archivos_por_carga=ARCHIVOS_POR_CARGA,
            mb_por_xml=MB_POR_XML,
            mb_por_documento=MB_POR_DOCUMENTO,
        ),
    )
