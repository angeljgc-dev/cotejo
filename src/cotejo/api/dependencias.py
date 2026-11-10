"""Dependencias de FastAPI compartidas por todas las rutas.

Uso en una ruta:

    @router.get("/facturas")
    def listar(sesion: SesionDb, usuario: UsuarioActual, config: ConfigApp) -> ...

    @router.post("/alertas/{id}/resolver")
    def resolver(sesion: SesionDb, usuario: Annotated[Usuario, Depends(requiere_rol("aprobador"))]) -> ...
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends, Path, Query, Request
from sqlalchemy.orm import Session

from cotejo.api.errores import ErrorApi
from cotejo.config import Settings
from cotejo.db import obtener_sesion
from cotejo.modelos import Usuario
from cotejo.seguridad.sesion import NOMBRE_COOKIE, DatosSesion, leer_token

Rol = Literal["capturista", "aprobador"]

# Los identificadores son bigint: un número mayor no existe y debe responder 422, no reventar en la base.
MAX_ID = 2**63 - 1
MAX_PAGINA = 1_000_000
IdRuta = Annotated[int, Path(ge=1, le=MAX_ID)]
IdFiltro = Annotated[int | None, Query(ge=1, le=MAX_ID)]
Pagina = Annotated[int, Query(ge=1, le=MAX_PAGINA)]


def obtener_config_app(request: Request) -> Settings:
    config = request.app.state.config
    if not isinstance(config, Settings):
        raise TypeError("La aplicación no tiene configuración en app.state.config.")
    return config


ConfigApp = Annotated[Settings, Depends(obtener_config_app)]
# scope="function": el commit de la transacción ocurre antes de enviar la respuesta.
SesionDb = Annotated[Session, Depends(obtener_sesion, scope="function")]


@dataclass(frozen=True)
class Visitante:
    visitante: str
    ip_hash: str


def ip_cliente(request: Request, config: Settings) -> str:
    if config.confiar_proxy:
        # Se toma la última IP: la agregó el proxy de confianza. Las anteriores las puede escribir el cliente.
        reenviada = request.headers.get("x-forwarded-for", "")
        ultima = reenviada.split(",")[-1].strip()
        if ultima:
            return ultima
    return request.client.host if request.client else "desconocida"


def hash_ip(ip: str, config: Settings) -> str:
    """Hash con la clave secreta para que borrar la cookie no reinicie la cuota y no se guarde la IP."""
    return hashlib.sha256(ip.encode("utf-8") + config.clave_firma()).hexdigest()


def datos_sesion(request: Request, config: ConfigApp) -> DatosSesion | None:
    token = request.cookies.get(NOMBRE_COOKIE)
    if not token:
        return None
    return leer_token(token, config.clave_firma(), ahora=int(time.time()))


DatosSesionOpcional = Annotated[DatosSesion | None, Depends(datos_sesion)]


def usuario_actual(sesion: SesionDb, datos: DatosSesionOpcional) -> Usuario:
    if datos is None:
        raise ErrorApi(401, "NO_AUTENTICADO", "Inicia sesión para continuar.")
    usuario = sesion.get(Usuario, datos.usuario_id)
    if usuario is None or not usuario.activo:
        raise ErrorApi(401, "NO_AUTENTICADO", "Tu sesión ya no es válida. Inicia sesión de nuevo.")
    return usuario


UsuarioActual = Annotated[Usuario, Depends(usuario_actual)]


def requiere_rol(*roles: Rol) -> Callable[..., Usuario]:
    if not roles:
        raise ValueError("requiere_rol necesita al menos un rol.")
    permitidos = frozenset(roles)
    texto_roles = " o ".join(roles)

    def _verificar(usuario: UsuarioActual) -> Usuario:
        if usuario.rol not in permitidos:
            raise ErrorApi(403, "ROL_INSUFICIENTE", f"Esta acción es solo para el rol {texto_roles}.")
        return usuario

    return _verificar


def contexto_visitante(request: Request, config: ConfigApp, datos: DatosSesionOpcional) -> Visitante:
    """Identidad del visitante para cuotas: la de la cookie si hay sesión, y siempre el hash de la IP."""
    ip = hash_ip(ip_cliente(request, config), config)
    return Visitante(visitante=datos.visitante if datos is not None else f"ip:{ip[:32]}", ip_hash=ip)


VisitanteActual = Annotated[Visitante, Depends(contexto_visitante)]
