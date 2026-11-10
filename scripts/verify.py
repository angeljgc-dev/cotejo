"""Verificación completa del proyecto: lint, formato, tipos y pruebas de backend y frontend.

Uso: uv run python scripts/verify.py

Corre los pasos en orden y se detiene en el primero que falle, mostrando el comando y su salida.
"""

from __future__ import annotations

import io
import os
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
WEB = RAIZ / "web"
LINEAS_DE_RESUMEN = 3


@dataclass(frozen=True)
class Paso:
    nombre: str
    comando: list[str]
    mostrar: str


class PasoImposible(Exception):
    """El paso no puede ni siquiera empezar (por ejemplo, faltan dependencias del frontend)."""


def _python(*args: str) -> list[str]:
    # El intérprete del entorno de uv: equivale a `uv run <herramienta>` sin anidar otro uv.
    return [sys.executable, "-m", *args]


def pasos_backend() -> list[Paso]:
    return [
        Paso("lint", _python("ruff", "check", "."), "uv run ruff check ."),
        Paso("formato", _python("ruff", "format", "--check", "."), "uv run ruff format --check ."),
        Paso("tipos", _python("mypy"), "uv run mypy"),
        Paso("pruebas backend", _python("pytest", "-q"), "uv run pytest -q"),
    ]


def paso_frontend() -> Paso:
    mostrar = "npm --prefix web run verify"
    if not (WEB / "package.json").is_file() or not (WEB / "node_modules").is_dir():
        raise PasoImposible("Corre primero: npm --prefix web ci")
    npm = shutil.which("npm")
    if npm is None:
        raise PasoImposible("No se encontró npm en el PATH. Instala Node 24 y corre: npm --prefix web ci")
    return Paso("frontend", [npm, "--prefix", str(WEB), "run", "verify"], mostrar)


def correr(paso: Paso) -> bool:
    print(f"==> {paso.nombre}: {paso.mostrar}", flush=True)
    inicio = time.perf_counter()
    proceso = subprocess.run(
        paso.comando,
        cwd=RAIZ,
        env={**os.environ, "PYTHONUTF8": "1", "NO_COLOR": "1", "FORCE_COLOR": "0"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    duracion = time.perf_counter() - inicio
    salida = (proceso.stdout + proceso.stderr).rstrip()
    if proceso.returncode != 0:
        print(f"FALLÓ {paso.nombre} (código {proceso.returncode}, {duracion:.1f} s)")
        print(f"Comando: {shlex.join(paso.comando)}")
        print(salida)
        return False
    resumen = [linea for linea in salida.splitlines() if linea.strip()][-LINEAS_DE_RESUMEN:]
    for linea in resumen:
        print(f"    {linea}")
    print(f"    ok ({duracion:.1f} s)")
    return True


def main() -> int:
    # En Windows la consola suele ser cp1252 y la salida de las herramientas trae caracteres que no caben.
    for flujo in (sys.stdout, sys.stderr):
        if isinstance(flujo, io.TextIOWrapper):
            flujo.reconfigure(encoding="utf-8", errors="replace")
    for paso in pasos_backend():
        if not correr(paso):
            return 1
    try:
        frontend = paso_frontend()
    except PasoImposible as exc:
        print("==> frontend: npm --prefix web run verify")
        print(f"FALLÓ frontend: {exc}")
        return 1
    if not correr(frontend):
        return 1
    print("verify: todo en verde")
    return 0


if __name__ == "__main__":
    sys.exit(main())
