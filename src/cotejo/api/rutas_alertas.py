"""Alertas: lista paginada y resolución manual por el rol aprobador. Resolver no modifica la factura."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from cotejo import bitacora
from cotejo.api.dependencias import IdFiltro, IdRuta, Pagina, SesionDb, UsuarioActual, requiere_rol
from cotejo.api.errores import ErrorApi
from cotejo.cfdi.codigos import NO_RESOLUBLES_A_MANO
from cotejo.cxp.contrato import AlertaSalida, PaginaAlertas, alertas_salida
from cotejo.modelos import Alerta, Usuario

router = APIRouter(tags=["alertas"])


class EntradaResolver(BaseModel):
    nota: str = Field(min_length=5, max_length=500)


@router.get("/alertas")
def listar_alertas(
    sesion: SesionDb,
    _usuario: UsuarioActual,
    estado: Literal["abierta", "resuelta"] | None = None,
    severidad: Literal["alerta", "bloqueante"] | None = None,
    codigo: Annotated[str | None, Query(max_length=60)] = None,
    factura_id: IdFiltro = None,
    pagina: Pagina = 1,
    por_pagina: Annotated[int, Query(ge=1, le=100)] = 25,
) -> PaginaAlertas:
    condiciones = []
    if estado is not None:
        condiciones.append(Alerta.estado == estado)
    if severidad is not None:
        condiciones.append(Alerta.severidad == severidad)
    if codigo:
        condiciones.append(Alerta.codigo == codigo.strip().upper())
    if factura_id is not None:
        condiciones.append(Alerta.factura_id == factura_id)
    total = sesion.execute(select(func.count()).select_from(Alerta).where(*condiciones)).scalar_one()
    alertas = list(
        sesion.scalars(
            select(Alerta)
            .where(*condiciones)
            .order_by(Alerta.id.desc())
            .limit(por_pagina)
            .offset((pagina - 1) * por_pagina)
        )
    )
    return PaginaAlertas(elementos=alertas_salida(sesion, alertas), total=total, pagina=pagina, por_pagina=por_pagina)


@router.post("/alertas/{alerta_id}/resolver")
def resolver_alerta(
    alerta_id: IdRuta,
    entrada: EntradaResolver,
    sesion: SesionDb,
    usuario: Annotated[Usuario, Depends(requiere_rol("aprobador"))],
) -> AlertaSalida:
    nota = entrada.nota.strip()
    if len(nota) < 5:
        raise ErrorApi(
            422,
            "VALIDACION",
            "Revisa los datos enviados.",
            {"campos": [{"campo": "nota", "mensaje": "La nota debe tener al menos 5 caracteres."}]},
        )
    # Bloqueo de la fila: dos aprobadores que resuelven a la vez no se pisan; el segundo ve la alerta resuelta.
    alerta = sesion.execute(select(Alerta).where(Alerta.id == alerta_id).with_for_update()).scalar_one_or_none()
    if alerta is None:
        raise ErrorApi(404, "ALERTA_NO_ENCONTRADA", "La alerta no existe.")
    if alerta.estado == "resuelta":
        raise ErrorApi(409, "ALERTA_YA_RESUELTA", "Esta alerta ya estaba resuelta.")
    if alerta.codigo in NO_RESOLUBLES_A_MANO:
        raise ErrorApi(
            422,
            "ALERTA_NO_RESOLUBLE",
            "Las alertas de la lista 69-B solo se cierran al cargar una lista en la que el proveedor ya no aparezca.",
        )
    alerta.estado = "resuelta"
    alerta.resuelta_por = usuario.id
    alerta.resuelta_en = datetime.now(UTC)
    alerta.nota_resolucion = nota
    sesion.flush()
    bitacora.registrar(
        sesion,
        usuario_id=usuario.id,
        accion="ALERTA_RESUELTA",
        entidad="alerta",
        entidad_id=alerta.id,
        detalle={"codigo": alerta.codigo, "factura_id": alerta.factura_id, "nota": nota},
    )
    return alertas_salida(sesion, [alerta])[0]
