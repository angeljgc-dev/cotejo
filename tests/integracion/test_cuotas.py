"""D10: límite de preguntas por visitante y por día, límite global y reinicio al cambiar el día."""

from __future__ import annotations

from datetime import date

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cotejo.asistente.guionado import PasoGuion
from cotejo.config import Settings
from cotejo.modelos import MensajeChat
from tests.apoyo.fabricas import crear_usuario
from tests.apoyo.http import entrar
from tests.integracion.apoyo_asistente import instalar_guion

RUTA = "/api/asistente/mensajes"


def _preguntar(cliente: TestClient, ip: str | None = None) -> int:
    cabeceras = {"X-Forwarded-For": ip} if ip else {}
    return cliente.post(RUTA, json={"texto": "¿Cómo va la antigüedad de saldos?"}, headers=cabeceras).status_code


def _restantes(cliente: TestClient) -> int:
    valor = cliente.get("/api/asistente/estado").json()["restantes_hoy"]
    assert isinstance(valor, int)
    return valor


def test_la_pregunta_21_del_dia_recibe_429_y_al_dia_siguiente_se_reinicia(
    app: FastAPI, cliente: TestClient, sesion: Session, config: Settings
) -> None:
    usuario = crear_usuario(sesion)
    entrar(cliente, config, usuario.id, visitante="visitante-uno")
    instalar_guion(app, [PasoGuion(texto="Sin adeudos.")])
    assert config.chat_limite_visitante_dia == 20 and _restantes(cliente) == 20

    assert [_preguntar(cliente) for _ in range(20)] == [200] * 20
    assert _restantes(cliente) == 0
    r = cliente.post(RUTA, json={"texto": "Una más"})
    assert r.status_code == 429
    error = r.json()["error"]
    assert error["codigo"] == "LIMITE_CHAT" and "20 preguntas por día" in error["mensaje"]
    assert error["detalle"] == {"limite": 20, "se_reinicia": "2026-11-03T00:00:00-06:00"}
    # La pregunta rechazada no se guarda ni llega al modelo.
    assert sesion.scalar(select(func.count()).select_from(MensajeChat).where(MensajeChat.rol == "usuario")) == 20
    estado = cliente.get("/api/asistente/estado").json()
    assert estado["disponible"] is True and estado["modelo"] == "guionado" and estado["limite_dia"] == 20

    # Borrar la cookie (otro visitante desde la misma red) no reinicia la cuota.
    entrar(cliente, config, usuario.id, visitante="visitante-nuevo-misma-red")
    assert _preguntar(cliente) == 429

    # Al día siguiente vuelve a tener sus 20.
    config.fecha_hoy_fija = date(2026, 11, 3)
    assert _restantes(cliente) == 20 and _preguntar(cliente) == 200


def test_cuota_global_protege_la_cuota_del_proveedor_entre_todos_los_visitantes(
    app: FastAPI, cliente: TestClient, sesion: Session, config: Settings
) -> None:
    config.confiar_proxy = True
    config.chat_limite_global_dia = 3
    usuario = crear_usuario(sesion)
    instalar_guion(app, [PasoGuion(texto="Sin adeudos.")])
    for numero in (1, 2, 3):
        entrar(cliente, config, usuario.id, visitante=f"visitante-{numero}")
        assert _preguntar(cliente, ip=f"203.0.113.{numero}") == 200
    entrar(cliente, config, usuario.id, visitante="visitante-4")
    r = cliente.post(RUTA, json={"texto": "¿Y yo?"}, headers={"X-Forwarded-For": "203.0.113.4"})
    assert r.status_code == 429
    assert r.json()["error"]["codigo"] == "LIMITE_CHAT" and "por hoy" in r.json()["error"]["mensaje"]
    assert r.json()["error"]["detalle"]["limite"] == 3
    estado = cliente.get("/api/asistente/estado", headers={"X-Forwarded-For": "203.0.113.4"}).json()
    assert estado["restantes_hoy"] == 0
    # El rechazo global no le descuenta su cuota personal al visitante.
    config.chat_limite_global_dia = 60
    estado = cliente.get("/api/asistente/estado", headers={"X-Forwarded-For": "203.0.113.4"}).json()
    assert estado["restantes_hoy"] == 20


def test_la_cuota_es_por_visitante_y_por_red(
    app: FastAPI, cliente: TestClient, sesion: Session, config: Settings
) -> None:
    config.confiar_proxy = True
    config.chat_limite_visitante_dia = 2
    usuario = crear_usuario(sesion)
    instalar_guion(app, [PasoGuion(texto="Sin adeudos.")])
    entrar(cliente, config, usuario.id, visitante="ana")
    assert [_preguntar(cliente, ip="203.0.113.10") for _ in range(3)] == [200, 200, 429]
    # Mismo visitante desde otra red: su cuota personal sigue agotada.
    assert _preguntar(cliente, ip="203.0.113.11") == 429
    # Otro visitante desde otra red sí puede.
    entrar(cliente, config, usuario.id, visitante="luis")
    assert _preguntar(cliente, ip="203.0.113.12") == 200
