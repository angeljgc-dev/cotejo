"""F3 (backend): reiniciar la demostración, con límite de uno cada dos minutos y apagado fuera del modo demo."""

from __future__ import annotations

import time
from collections.abc import Callable

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from cotejo.config import Settings
from cotejo.modelos import Bitacora, Factura
from tests.apoyo.fabricas import crear_factura, crear_usuario
from tests.apoyo.http import entrar


@pytest.fixture
def reloj(monkeypatch: pytest.MonkeyPatch) -> Callable[[float], None]:
    """Fija el reloj, para que la ventana de dos minutos del reinicio no dependa de cuándo corre la prueba."""

    def _fijar(segundos: float) -> None:
        monkeypatch.setattr(time, "time", lambda: segundos)

    return _fijar


def test_reiniciar_deja_la_demo_sembrada_y_limita_a_uno_cada_dos_minutos(
    cliente: TestClient, sesion: Session, entrar_como: Callable[[int], None], reloj: Callable[[float], None]
) -> None:
    uuid_ajeno = crear_factura(sesion).uuid
    usuario = crear_usuario(sesion, rol="aprobador")
    entrar_como(usuario.id)
    inicio = (int(time.time()) // 120) * 120 + 5.0
    reloj(inicio)

    r = cliente.post("/api/demo/reiniciar", json={})
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert set(cuerpo) == {"reiniciada_en", "facturas", "documentos"}
    assert cuerpo["facturas"] == 120
    assert sesion.scalar(select(Factura.id).where(Factura.uuid == uuid_ajeno)) is None
    assert len(sesion.scalars(select(Factura.id).where(Factura.tipo == "I")).all()) == 120
    assert sesion.scalars(select(Bitacora.accion).where(Bitacora.accion == "DEMO_REINICIADA")).all()

    otra = cliente.post("/api/demo/reiniciar", json={})
    assert otra.status_code == 429
    error = otra.json()["error"]
    assert error["codigo"] == "LIMITE_REINICIO" and error["detalle"]["limite"] == 1 and error["detalle"]["se_reinicia"]

    reloj(inicio + 120)
    assert cliente.post("/api/demo/reiniciar", json={}).status_code == 200


def test_reiniciar_exige_sesion(cliente: TestClient) -> None:
    r = cliente.post("/api/demo/reiniciar", json={})
    assert r.status_code == 401 and r.json()["error"]["codigo"] == "NO_AUTENTICADO"


def test_reiniciar_sin_modo_demo_es_404(
    config: Settings, fabrica_app: Callable[[Settings], FastAPI], sesion: Session
) -> None:
    config.demo_habilitada = False
    usuario = crear_usuario(sesion)
    with TestClient(fabrica_app(config), headers={"X-Cotejo": "1"}) as cliente:
        entrar(cliente, config, usuario.id)
        r = cliente.post("/api/demo/reiniciar", json={})
    assert r.status_code == 404 and r.json()["error"]["codigo"] == "DEMO_DESHABILITADA"
