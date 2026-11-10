"""Tablero de cuentas por pagar. Todas las cifras salen de `cxp.consultas`, la misma fuente que el resto."""

from __future__ import annotations

from fastapi import APIRouter

from cotejo.api.dependencias import ConfigApp, SesionDb, UsuarioActual
from cotejo.cxp import consultas
from cotejo.cxp.consultas import Tablero
from cotejo.fechas import hoy

router = APIRouter(tags=["tablero"])


@router.get("/tablero")
def ver_tablero(sesion: SesionDb, config: ConfigApp, _usuario: UsuarioActual) -> Tablero:
    return consultas.tablero(sesion, hoy(config))
