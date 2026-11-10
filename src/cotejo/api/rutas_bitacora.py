"""Bitácora de operaciones: consulta con filtros. Nadie la modifica; la base rechaza cambios y borrados."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import ColumnElement, func, select

from cotejo.api.dependencias import ConfigApp, IdFiltro, Pagina, SesionDb, UsuarioActual
from cotejo.cxp.contrato import UsuarioCorto
from cotejo.modelos import Bitacora, Usuario

router = APIRouter(tags=["bitacora"])


class RenglonBitacora(BaseModel):
    id: int
    ocurrido_en: datetime
    usuario: UsuarioCorto | None
    accion: str
    entidad: str
    entidad_id: str | None
    detalle: dict[str, object]


class PaginaBitacora(BaseModel):
    elementos: list[RenglonBitacora]
    total: int
    pagina: int
    por_pagina: int


@router.get("/bitacora")
def listar_bitacora(
    sesion: SesionDb,
    config: ConfigApp,
    _usuario: UsuarioActual,
    accion: Annotated[str | None, Query(max_length=40)] = None,
    usuario_id: IdFiltro = None,
    entidad: Annotated[str | None, Query(max_length=40)] = None,
    entidad_id: Annotated[str | None, Query(max_length=40)] = None,
    desde: date | None = None,
    hasta: date | None = None,
    pagina: Pagina = 1,
    por_pagina: Annotated[int, Query(ge=1, le=100)] = 25,
) -> PaginaBitacora:
    zona = ZoneInfo(config.zona_horaria)
    condiciones: list[ColumnElement[bool]] = []
    if accion:
        condiciones.append(Bitacora.accion == accion)
    if usuario_id is not None:
        condiciones.append(Bitacora.usuario_id == usuario_id)
    if entidad:
        condiciones.append(Bitacora.entidad == entidad)
    if entidad_id:
        condiciones.append(Bitacora.entidad_id == entidad_id)
    # Los días se interpretan en la zona de la empresa, igual que los muestra la interfaz.
    if desde is not None:
        condiciones.append(Bitacora.ocurrido_en >= datetime.combine(desde, time.min, tzinfo=zona))
    if hasta is not None:
        condiciones.append(Bitacora.ocurrido_en < datetime.combine(hasta + timedelta(days=1), time.min, tzinfo=zona))
    total = sesion.execute(select(func.count()).select_from(Bitacora).where(*condiciones)).scalar_one()
    filas = sesion.execute(
        select(Bitacora, Usuario)
        .outerjoin(Usuario, Usuario.id == Bitacora.usuario_id)
        .where(*condiciones)
        .order_by(Bitacora.id.desc())
        .limit(por_pagina)
        .offset((pagina - 1) * por_pagina)
    ).all()
    return PaginaBitacora(
        elementos=[
            RenglonBitacora(
                id=b.id,
                ocurrido_en=b.ocurrido_en,
                usuario=UsuarioCorto.de(u) if u is not None else None,
                accion=b.accion,
                entidad=b.entidad,
                entidad_id=b.entidad_id,
                detalle=b.detalle,
            )
            for b, u in filas
        ],
        total=total,
        pagina=pagina,
        por_pagina=por_pagina,
    )
