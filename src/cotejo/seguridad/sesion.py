"""Cookie de sesión firmada con HMAC-SHA256: base64url(json) + "." + firma. Sin tabla de sesiones (ADR-k)."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from dataclasses import dataclass

NOMBRE_COOKIE = "cotejo_sesion"
DURACION_S = 8 * 60 * 60


@dataclass(frozen=True)
class DatosSesion:
    usuario_id: int
    visitante: str
    expira: int  # segundos desde la época, UTC


def _b64(datos: bytes) -> str:
    return base64.urlsafe_b64encode(datos).decode("ascii").rstrip("=")


def _desde_b64(texto: str) -> bytes:
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))


def _firma(carga: str, clave: bytes) -> str:
    return _b64(hmac.new(clave, carga.encode("ascii"), hashlib.sha256).digest())


def crear_token(datos: DatosSesion, clave: bytes) -> str:
    cuerpo = json.dumps({"u": datos.usuario_id, "v": datos.visitante, "e": datos.expira}, separators=(",", ":"))
    carga = _b64(cuerpo.encode("utf-8"))
    return f"{carga}.{_firma(carga, clave)}"


def leer_token(token: str, clave: bytes, *, ahora: int) -> DatosSesion | None:
    """Devuelve los datos si la firma es válida y no ha expirado; None en cualquier otro caso."""
    partes = token.split(".")
    if len(partes) != 2 or not partes[0] or not partes[1]:
        return None
    carga, firma = partes
    if not (carga.isascii() and firma.isascii()):
        return None
    try:
        esperada = _firma(carga, clave)
    except UnicodeEncodeError:
        return None
    if not hmac.compare_digest(esperada, firma):
        return None
    try:
        cuerpo = json.loads(_desde_b64(carga))
    except (binascii.Error, ValueError):
        return None
    if not isinstance(cuerpo, dict):
        return None
    usuario_id, visitante, expira = cuerpo.get("u"), cuerpo.get("v"), cuerpo.get("e")
    if not isinstance(usuario_id, int) or not isinstance(visitante, str) or not isinstance(expira, int):
        return None
    if expira <= ahora:
        return None
    return DatosSesion(usuario_id=usuario_id, visitante=visitante, expira=expira)
