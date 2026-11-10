"""Salud del servicio: la usa el hospedaje y la prueba de humo del contenedor."""

from __future__ import annotations

import logging
from importlib.metadata import PackageNotFoundError, version
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from cotejo.api.dependencias import ConfigApp, SesionDb
from cotejo.api.errores import ErrorApi

router = APIRouter(tags=["salud"])
_log = logging.getLogger("cotejo.salud")


def version_cotejo() -> str:
    try:
        return version("cotejo")
    except PackageNotFoundError:
        return "desconocida"


class Salud(BaseModel):
    estado: Literal["ok"]
    base: Literal["ok"]
    version: str
    modo_demo: bool
    asistente_configurado: bool


@router.get("/salud", response_model=Salud)
def salud(sesion: SesionDb, config: ConfigApp) -> Salud:
    try:
        sesion.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        _log.warning("La base de datos no responde: %s", type(exc).__name__)
        raise ErrorApi(
            503,
            "BASE_NO_DISPONIBLE",
            "La base de datos no responde.",
            {
                "estado": "error",
                "base": "error",
                "version": version_cotejo(),
                "modo_demo": config.demo_habilitada,
                "asistente_configurado": config.asistente_configurado,
            },
        ) from exc
    return Salud(
        estado="ok",
        base="ok",
        version=version_cotejo(),
        modo_demo=config.demo_habilitada,
        asistente_configurado=config.asistente_configurado,
    )
