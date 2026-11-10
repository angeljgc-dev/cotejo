"""Ayudas para pruebas HTTP."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from cotejo.config import Settings
from cotejo.seguridad.sesion import DURACION_S, NOMBRE_COOKIE, DatosSesion, crear_token


def token_de(config: Settings, usuario_id: int, visitante: str = "visitante-de-prueba") -> str:
    datos = DatosSesion(usuario_id=usuario_id, visitante=visitante, expira=int(time.time()) + DURACION_S)
    return crear_token(datos, config.clave_firma())


def entrar(cliente: TestClient, config: Settings, usuario_id: int, visitante: str = "visitante-de-prueba") -> None:
    cliente.cookies.set(NOMBRE_COOKIE, token_de(config, usuario_id, visitante))
