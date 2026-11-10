"""Cookie firmada (ADR-k) y contraseñas con scrypt."""

import base64
import json

from cotejo.seguridad.contrasenas import hash_contrasena, verificar_contrasena
from cotejo.seguridad.sesion import DatosSesion, crear_token, leer_token

CLAVE = b"k" * 32


def test_token_ida_y_vuelta() -> None:
    token = crear_token(DatosSesion(usuario_id=7, visitante="abc", expira=2_000), CLAVE)
    assert leer_token(token, CLAVE, ahora=1_000) == DatosSesion(usuario_id=7, visitante="abc", expira=2_000)


def test_token_expirado() -> None:
    token = crear_token(DatosSesion(usuario_id=7, visitante="abc", expira=2_000), CLAVE)
    assert leer_token(token, CLAVE, ahora=2_000) is None


def test_token_con_otra_clave_o_alterado() -> None:
    token = crear_token(DatosSesion(usuario_id=7, visitante="abc", expira=2_000), CLAVE)
    assert leer_token(token, b"x" * 32, ahora=1_000) is None
    carga, firma = token.split(".")
    otra = base64.urlsafe_b64encode(json.dumps({"u": 1, "v": "abc", "e": 2_000}).encode()).decode().rstrip("=")
    assert leer_token(f"{otra}.{firma}", CLAVE, ahora=1_000) is None
    assert leer_token(f"{carga}.{firma[:-2]}AA", CLAVE, ahora=1_000) is None


def test_token_basura() -> None:
    for basura in ["", ".", "abc", "a.b.c", "!!!.???", "e30.e30", "abc.é", "é.abc"]:
        assert leer_token(basura, CLAVE, ahora=1_000) is None


def test_contrasena_scrypt() -> None:
    guardado = hash_contrasena("correcto caballo bateria")
    partes = guardado.split("$")
    assert partes[:4] == ["scrypt", "16384", "8", "1"]
    assert len(partes) == 6
    assert verificar_contrasena("correcto caballo bateria", guardado)
    assert not verificar_contrasena("otra", guardado)
    assert hash_contrasena("correcto caballo bateria") != guardado  # sal distinta


def test_contrasena_con_hash_malformado() -> None:
    assert not verificar_contrasena("x", "no-es-un-hash")
    assert not verificar_contrasena("x", "scrypt$a$b$c$d$e")
