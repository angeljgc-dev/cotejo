from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from cotejo.config import Settings
from cotejo.fechas import ahora_local, hoy, rango_horizonte, siguiente_medianoche

ZONA = ZoneInfo("America/Mexico_City")


def test_hoy_respeta_fecha_fija() -> None:
    assert hoy(Settings(fecha_hoy_fija=date(2026, 11, 2))) == date(2026, 11, 2)


def test_hoy_sin_fecha_fija_es_la_fecha_local_de_la_zona() -> None:
    config = Settings(fecha_hoy_fija=None, zona_horaria="America/Mexico_City")
    antes = datetime.now(ZONA).date()
    valor = hoy(config)
    despues = datetime.now(ZONA).date()
    assert antes <= valor <= despues


def test_ahora_local_con_fecha_fija_es_mediodia_con_zona() -> None:
    valor = ahora_local(Settings(fecha_hoy_fija=date(2026, 11, 2)))
    assert valor == datetime(2026, 11, 2, 12, 0, tzinfo=ZONA)
    assert valor.utcoffset() == timedelta(hours=-6)


@pytest.mark.parametrize(
    ("horizonte", "esperado"),
    [
        ("vencidas", (None, date(2026, 11, 3))),
        ("esta_semana", (date(2026, 11, 4), date(2026, 11, 8))),
        ("proximos_7_dias", (date(2026, 11, 4), date(2026, 11, 11))),
        ("proximos_30_dias", (date(2026, 11, 4), date(2026, 12, 4))),
    ],
)
def test_rango_horizonte_desde_un_miercoles(horizonte: str, esperado: tuple[date | None, date]) -> None:
    assert rango_horizonte(horizonte, date(2026, 11, 4)) == esperado


def test_esta_semana_en_domingo_es_solo_hoy() -> None:
    assert rango_horizonte("esta_semana", date(2026, 11, 8)) == (date(2026, 11, 8), date(2026, 11, 8))


def test_horizonte_desconocido() -> None:
    with pytest.raises(ValueError, match="Horizonte"):
        rango_horizonte("siempre", date(2026, 11, 4))


def test_siguiente_medianoche_con_desfase_de_mexico() -> None:
    valor = siguiente_medianoche(date(2026, 11, 9), "America/Mexico_City")
    assert valor.isoformat() == "2026-11-10T00:00:00-06:00"
