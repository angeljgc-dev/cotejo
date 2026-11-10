"""Contraseñas con hashlib.scrypt (n=2^14, r=8, p=1). Formato: scrypt$n$r$p$sal_b64$hash_b64."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets

_N, _R, _P = 2**14, 8, 1
_LARGO = 32


def _derivar(contrasena: str, sal: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(contrasena.encode("utf-8"), salt=sal, n=n, r=r, p=p, dklen=_LARGO, maxmem=64 * 1024 * 1024)


def hash_contrasena(contrasena: str) -> str:
    sal = secrets.token_bytes(16)
    derivada = _derivar(contrasena, sal, _N, _R, _P)
    sal_b64 = base64.b64encode(sal).decode()
    hash_b64 = base64.b64encode(derivada).decode()
    return f"scrypt${_N}${_R}${_P}${sal_b64}${hash_b64}"


def verificar_contrasena(contrasena: str, guardado: str) -> bool:
    partes = guardado.split("$")
    if len(partes) != 6 or partes[0] != "scrypt":
        return False
    try:
        n, r, p = int(partes[1]), int(partes[2]), int(partes[3])
        sal = base64.b64decode(partes[4], validate=True)
        esperado = base64.b64decode(partes[5], validate=True)
    except (ValueError, binascii.Error):
        return False
    # Parámetros fuera de rango harían que scrypt falle o consuma memoria de más.
    if (n, r, p) != (_N, _R, _P):
        return False
    return hmac.compare_digest(_derivar(contrasena, sal, n, r, p), esperado)
