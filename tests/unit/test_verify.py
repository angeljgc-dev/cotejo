"""G1: el script verify se detiene en el primer fallo y exige instalar el frontend antes."""

from __future__ import annotations

import importlib.util
import io
import sys
from pathlib import Path
from types import ModuleType

import pytest

RUTA = Path(__file__).resolve().parents[2] / "scripts" / "verify.py"


def _modulo() -> ModuleType:
    spec = importlib.util.spec_from_file_location("verify_script", RUTA)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    # dataclasses necesita encontrar el módulo registrado mientras se ejecuta.
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)
    return modulo


def test_pasos_de_backend_en_orden_y_sin_revisor_de_repo() -> None:
    verify = _modulo()
    mostrados = [p.mostrar for p in verify.pasos_backend()]
    assert mostrados == [
        "uv run ruff check .",
        "uv run ruff format --check .",
        "uv run mypy",
        "uv run pytest -q",
    ]


def test_sin_node_modules_pide_instalar(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    verify = _modulo()
    monkeypatch.setattr(verify, "WEB", tmp_path)
    with pytest.raises(verify.PasoImposible, match=r"Corre primero: npm --prefix web ci"):
        verify.paso_frontend()
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    with pytest.raises(verify.PasoImposible, match=r"Corre primero: npm --prefix web ci"):
        verify.paso_frontend()


def test_se_detiene_en_el_primer_fallo(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    verify = _modulo()
    exito = verify.Paso("uno", [sys.executable, "-c", "print('bien')"], "uno")
    falla = verify.Paso("dos", [sys.executable, "-c", "import sys; print('salida del fallo'); sys.exit(4)"], "dos")
    nunca = verify.Paso("tres", [sys.executable, "-c", "raise SystemExit(0)"], "tres")
    monkeypatch.setattr(verify, "pasos_backend", lambda: [exito, falla, nunca])
    assert verify.main() == 1
    salida = capsys.readouterr().out
    assert "==> uno" in salida and "==> dos" in salida and "==> tres" not in salida
    assert "FALLÓ dos (código 4" in salida and "salida del fallo" in salida and "Comando:" in salida


def test_fallo_con_caracteres_fuera_de_cp1252_se_muestra(monkeypatch: pytest.MonkeyPatch) -> None:
    """En una consola cp1252 la salida del paso que falla no debe reventar al imprimirse."""
    verify = _modulo()
    falla = verify.Paso("uno", [sys.executable, "-c", "import sys; sys.stdout.write('error λ漢'); sys.exit(1)"], "uno")
    monkeypatch.setattr(verify, "pasos_backend", lambda: [falla])
    crudo = io.BytesIO()
    consola = io.TextIOWrapper(crudo, encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", consola)
    assert verify.main() == 1
    consola.flush()
    assert "error λ漢" in crudo.getvalue().decode("utf-8")
