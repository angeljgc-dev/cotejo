"""Migraciones Alembic. `aplicar(url)` las corre desde código (pruebas, arranque) sin depender de alembic.ini."""

from __future__ import annotations

from alembic import command
from alembic.config import Config

from cotejo.db import normalizar_url


def configuracion(url: str | None = None) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", "cotejo:migraciones")
    if url is not None:
        # ConfigParser interpreta "%": se duplica para contraseñas con ese carácter.
        cfg.set_main_option("sqlalchemy.url", normalizar_url(url).replace("%", "%%"))
    return cfg


def aplicar(url: str, revision: str = "head") -> None:
    command.upgrade(configuracion(url), revision)


def revertir(url: str, revision: str = "base") -> None:
    command.downgrade(configuracion(url), revision)
