"""Configuración (G6) y guardia de la base de pruebas."""

import re
from pathlib import Path

import pytest

from cotejo.config import ErrorConfiguracion, Settings
from cotejo.db import es_base_de_pruebas, normalizar_url

RAIZ = Path(__file__).resolve().parents[2]


def test_env_example_documenta_cada_campo_de_settings() -> None:
    contenido = (RAIZ / ".env.example").read_text(encoding="utf-8")
    variables = set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", contenido, flags=re.MULTILINE))
    faltan = {campo.upper() for campo in Settings.model_fields} - variables
    assert not faltan, f"Faltan en .env.example: {sorted(faltan)}"


def test_env_example_no_trae_secretos() -> None:
    contenido = (RAIZ / ".env.example").read_text(encoding="utf-8")
    for linea in contenido.splitlines():
        if linea.startswith(("SECRET_KEY=", "LLM_API_KEY=")):
            assert linea.split("=", 1)[1].strip() == ""


def test_produccion_exige_secret_key_larga() -> None:
    with pytest.raises(ErrorConfiguracion, match="SECRET_KEY"):
        Settings(entorno="produccion", secret_key="corta").validar_para_arranque()
    Settings(entorno="produccion", secret_key="x" * 32).validar_para_arranque()


def test_sin_entorno_se_asume_produccion(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENTORNO", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    config = Settings()
    assert config.entorno == "produccion"
    with pytest.raises(ErrorConfiguracion, match="SECRET_KEY"):
        config.validar_para_arranque()


def test_desarrollo_sin_secret_key_genera_una_temporal() -> None:
    config = Settings(entorno="desarrollo", secret_key="")
    config.validar_para_arranque()
    assert len(config.clave_firma()) >= 32


def test_variables_vacias_se_ignoran(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FECHA_HOY_FIJA", "")
    monkeypatch.setenv("LLM_API_KEY", "")
    config = Settings()
    assert config.fecha_hoy_fija is None
    assert not config.asistente_configurado


def test_secretos_no_aparecen_en_repr() -> None:
    config = Settings(secret_key="s" * 40, llm_api_key="clave-del-modelo", database_url="postgresql://u:pw@h/db_test")
    assert "clave-del-modelo" not in repr(config)
    assert ":pw@" not in repr(config)


@pytest.mark.parametrize(
    ("entrada", "esperada"),
    [
        ("postgres://u:p@h:5432/cotejo_test", "postgresql+psycopg://u:p@h:5432/cotejo_test"),
        ("postgresql://u@h/cotejo_test", "postgresql+psycopg://u@h/cotejo_test"),
        ("postgresql+psycopg://u@h/x_test", "postgresql+psycopg://u@h/x_test"),
    ],
)
def test_normalizar_url(entrada: str, esperada: str) -> None:
    assert normalizar_url(entrada) == esperada


def test_guardia_de_nombre_de_base() -> None:
    assert es_base_de_pruebas("postgresql://u@h/cotejo_test")
    assert es_base_de_pruebas("postgresql://u@h/test_x")
    assert not es_base_de_pruebas("postgresql://u@h/produccion")
    assert not es_base_de_pruebas("postgresql://u@h/")
