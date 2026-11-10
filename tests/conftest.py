"""Configuración común de pruebas: entorno determinista, base PostgreSQL por sesión y cliente HTTP.

Las pruebas que piden `sesion`, `app` o `cliente` usan una base real (ver tests/apoyo/pg_local.py). Cada prueba
corre dentro de una transacción que se revierte al final, así no se contaminan entre sí.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from cotejo import migraciones
from cotejo.api.app import crear_app
from cotejo.config import Settings, obtener_config
from cotejo.db import obtener_sesion
from tests.apoyo import pg_local
from tests.apoyo.http import entrar

_RESUMEN_BASE: list[str] = []


def pytest_report_header() -> str:
    if os.environ.get("DATABASE_URL", "").strip():
        return "base de pruebas: servidor de DATABASE_URL, base única por sesión"
    return f"base de pruebas: PostgreSQL local en {pg_local.PGDATA}, base única por sesión"


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    for linea in _RESUMEN_BASE:
        terminalreporter.write_line(f"[base de pruebas] {linea}")


@pytest.fixture(scope="session")
def base_prueba() -> Iterator[pg_local.BasePrueba]:
    t0 = time.perf_counter()
    try:
        base = pg_local.preparar()
    except pg_local.BaseNoEsDePruebas as exc:
        pytest.exit(f"Se niega a correr: {exc}", returncode=3)
    t1 = time.perf_counter()
    migraciones.aplicar(base.url)
    base.tiempos["migraciones"] = time.perf_counter() - t1
    base.tiempos["arranque_total"] = time.perf_counter() - t0
    _RESUMEN_BASE.append(base.resumen())
    try:
        yield base
    finally:
        pg_local.liberar(base)


@pytest.fixture(scope="session")
def motor(base_prueba: pg_local.BasePrueba) -> Iterator[Engine]:
    eng = create_engine(base_prueba.url)
    yield eng
    eng.dispose()


@pytest.fixture
def sesion(motor: Engine) -> Iterator[Session]:
    """Sesión dentro de una transacción externa que se revierte; los commit del código solo liberan savepoints."""
    with motor.connect() as conexion:
        transaccion = conexion.begin()
        with Session(bind=conexion, join_transaction_mode="create_savepoint", expire_on_commit=False) as s:
            yield s
        transaccion.rollback()


@pytest.fixture
def config() -> Settings:
    obtener_config.cache_clear()
    return Settings()


@pytest.fixture
def fabrica_app(sesion: Session) -> Callable[[Settings], FastAPI]:
    """Crea una app con la configuración dada y la sesión de base de la prueba."""

    def _crear(config: Settings) -> FastAPI:
        aplicacion = crear_app(config)

        def _sesion_de_prueba() -> Iterator[Session]:
            # Mismo contrato que db.obtener_sesion: commit al final, rollback ante error.
            try:
                yield sesion
                sesion.commit()
            except BaseException:
                sesion.rollback()
                raise

        aplicacion.dependency_overrides[obtener_sesion] = _sesion_de_prueba
        return aplicacion

    return _crear


@pytest.fixture
def app(config: Settings, fabrica_app: Callable[[Settings], FastAPI]) -> FastAPI:
    return fabrica_app(config)


@pytest.fixture
def cliente(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, headers={"X-Cotejo": "1"}) as c:
        yield c


@pytest.fixture
def entrar_como(cliente: TestClient, config: Settings) -> Callable[[int], None]:
    """Pone en el cliente la cookie de sesión de un usuario ya creado: `entrar_como(usuario.id)`."""

    def _entrar(usuario_id: int) -> None:
        entrar(cliente, config, usuario_id)

    return _entrar
