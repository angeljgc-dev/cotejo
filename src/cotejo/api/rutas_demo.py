"""Reinicio de la demostración: deja la base como recién sembrada. Limitado a uno cada dos minutos."""

from __future__ import annotations

import time
from datetime import UTC, datetime

from fastapi import APIRouter
from pydantic import BaseModel

from cotejo import bitacora
from cotejo.api.dependencias import ConfigApp, SesionDb, UsuarioActual
from cotejo.api.errores import ErrorApi
from cotejo.fechas import hoy
from cotejo.seguridad import cuotas
from cotejo.semilla import generador

router = APIRouter(tags=["demo"])

VENTANA_REINICIO_S = 120


class ReinicioSalida(BaseModel):
    reiniciada_en: datetime
    facturas: int
    documentos: int


@router.post("/demo/reiniciar")
def reiniciar_demo(sesion: SesionDb, config: ConfigApp, usuario: UsuarioActual) -> ReinicioSalida:
    if not config.demo_habilitada:
        raise ErrorApi(404, "DEMO_DESHABILITADA", "El modo de demostración no está habilitado en esta instalación.")
    dia = hoy(config)
    ventana = int(time.time()) // VENTANA_REINICIO_S
    # Una clave por ventana de dos minutos, común a todos los visitantes: la demostración es compartida.
    try:
        cuotas.consumir(sesion, f"demo:reinicio:{ventana}", 1, dia)
    except cuotas.CuotaAgotada as exc:
        siguiente = datetime.fromtimestamp((ventana + 1) * VENTANA_REINICIO_S, UTC)
        raise ErrorApi(
            429,
            "LIMITE_REINICIO",
            "La demostración se reinició hace poco. Espera un par de minutos para volver a reiniciarla.",
            {"limite": exc.limite, "se_reinicia": siguiente.isoformat()},
        ) from exc
    resumen = generador.reiniciar_demo(
        sesion,
        semilla=config.semilla,
        fecha_base=dia,
        empresa_rfc=config.empresa_rfc,
        empresa_nombre=config.empresa_nombre,
    )
    bitacora.registrar(
        sesion,
        usuario_id=usuario.id,
        accion="DEMO_REINICIADA",
        entidad="demo",
        entidad_id=None,
        detalle={"facturas": resumen.facturas, "documentos": resumen.documentos, "semilla": config.semilla},
    )
    return ReinicioSalida(reiniciada_en=datetime.now(UTC), facturas=resumen.facturas, documentos=resumen.documentos)
