"""Pruebas de Cotejo.

Este archivo se importa antes que conftest.py y que cualquier módulo de cotejo: fija un entorno determinista para
que las pruebas nunca dependan de las variables de quien las corre (E1, D8).
"""

import os
from pathlib import Path

os.environ.update(
    {
        "ENTORNO": "pruebas",
        "SECRET_KEY": "clave-de-pruebas-que-no-es-secreta-0123456789",
        "FECHA_HOY_FIJA": "2026-11-02",
        "EMBEDDINGS_PROVEEDOR": "determinista",
        "DEMO_HABILITADA": "1",
        "COOKIE_SEGURA": "0",
        "CONFIAR_PROXY": "0",
        "STATIC_DIR": str(Path(__file__).parent / "_sin_estaticos"),
    }
)
os.environ.pop("LLM_API_KEY", None)
