"""Motor y sesiones de SQLAlchemy. Una sola variable: DATABASE_URL."""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from cotejo.config import ErrorConfiguracion, obtener_config


def normalizar_url(url: str) -> str:
    """Acepta postgres:// o postgresql:// (formato de Neon, Render, etc.) y fija el driver psycopg 3."""
    if url.startswith("postgres://"):
        url = "postgresql://" + url.removeprefix("postgres://")
    return make_url(url).set(drivername="postgresql+psycopg").render_as_string(hide_password=False)


def es_base_de_pruebas(url: str) -> bool:
    """Guardia de las pruebas: solo se corre contra una base cuyo nombre contiene "test"."""
    nombre = make_url(normalizar_url(url)).database or ""
    return "test" in nombre


def crear_motor(url: str) -> Engine:
    return create_engine(normalizar_url(url), pool_pre_ping=True)


@lru_cache(maxsize=1)
def obtener_motor() -> Engine:
    config = obtener_config()
    if config.database_url is None:
        raise ErrorConfiguracion("Falta DATABASE_URL.")
    return crear_motor(config.database_url.get_secret_value())


@lru_cache(maxsize=1)
def fabrica_sesiones() -> sessionmaker[Session]:
    return sessionmaker(bind=obtener_motor(), expire_on_commit=False)


def obtener_sesion() -> Iterator[Session]:
    """Dependencia de FastAPI: una transacción por petición; commit al final, rollback si hubo excepción.

    Se declara con `Depends(obtener_sesion, scope="function")` (ver api.dependencias.SesionDb) para que el
    commit ocurra antes de enviar la respuesta: si falla, el cliente recibe el error y no un 200 falso.
    """
    with fabrica_sesiones()() as sesion:
        try:
            yield sesion
            sesion.commit()
        except BaseException:
            sesion.rollback()
            raise
