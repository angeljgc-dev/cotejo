"""Entorno de Alembic: usa sqlalchemy.url si se pasó desde código; si no, DATABASE_URL."""

from __future__ import annotations

from alembic import context
from sqlalchemy import Connection, create_engine, pool

import cotejo.modelos
from cotejo.config import ErrorConfiguracion, obtener_config
from cotejo.db import normalizar_url

config = context.config
metadatos = cotejo.modelos.Base.metadata


def _url() -> str:
    url = config.get_main_option("sqlalchemy.url")
    if url:
        return url
    ajustes = obtener_config()
    if ajustes.database_url is None:
        raise ErrorConfiguracion("Falta DATABASE_URL para correr las migraciones.")
    return normalizar_url(ajustes.database_url.get_secret_value())


def _configurar(conexion: Connection) -> None:
    context.configure(connection=conexion, target_metadata=metadatos, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def correr_en_linea() -> None:
    conexion_externa = config.attributes.get("connection")
    if isinstance(conexion_externa, Connection):
        _configurar(conexion_externa)
        return
    motor = create_engine(_url(), poolclass=pool.NullPool)
    with motor.connect() as conexion:
        _configurar(conexion)
    motor.dispose()


if context.is_offline_mode():
    context.configure(url=_url(), target_metadata=metadatos, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    correr_en_linea()
