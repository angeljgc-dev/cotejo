"""Fecha y hora "de negocio": siempre en la zona configurada y con FECHA_HOY_FIJA para pruebas."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from cotejo.config import Settings, obtener_config

HORIZONTES = ("vencidas", "esta_semana", "proximos_7_dias", "proximos_30_dias")


def hoy(config: Settings | None = None) -> date:
    config = config or obtener_config()
    if config.fecha_hoy_fija is not None:
        return config.fecha_hoy_fija
    return datetime.now(ZoneInfo(config.zona_horaria)).date()


def ahora_local(config: Settings | None = None) -> datetime:
    """Hora local con zona. Con fecha fija devuelve ese día a las 12:00 para que las pruebas sean deterministas."""
    config = config or obtener_config()
    zona = ZoneInfo(config.zona_horaria)
    if config.fecha_hoy_fija is not None:
        return datetime.combine(config.fecha_hoy_fija, time(12, 0), tzinfo=zona)
    return datetime.now(zona)


def rango_horizonte(horizonte: str, hoy: date) -> tuple[date | None, date]:
    """Rango inclusivo de vencimientos. `desde` es None cuando no hay límite inferior (vencidas)."""
    if horizonte == "vencidas":
        return None, hoy - timedelta(days=1)
    if horizonte == "esta_semana":
        domingo = hoy + timedelta(days=6 - hoy.weekday())
        return hoy, domingo
    if horizonte == "proximos_7_dias":
        return hoy, hoy + timedelta(days=7)
    if horizonte == "proximos_30_dias":
        return hoy, hoy + timedelta(days=30)
    raise ValueError(f"Horizonte desconocido: {horizonte!r}. Opciones: {', '.join(HORIZONTES)}.")


def siguiente_medianoche(dia: date, zona_horaria: str) -> datetime:
    """Momento en que se reinicia una cuota diaria."""
    return datetime.combine(dia + timedelta(days=1), time(0, 0), tzinfo=ZoneInfo(zona_horaria))
