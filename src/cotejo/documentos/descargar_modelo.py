"""Descarga el modelo de embeddings a la caché local. Uso: python -m cotejo.documentos.descargar_modelo

Se corre una vez (al construir la imagen o al preparar el entorno) para que el primer documento no espere la
descarga. El modelo no forma parte del repositorio.
"""

from __future__ import annotations

import sys

from cotejo.config import Settings
from cotejo.documentos.embeddings import ModeloNoDisponible, revision_configurada, ruta_modelo


def main() -> int:
    config = Settings()
    if config.embeddings_proveedor != "fastembed":
        sys.stdout.write("EMBEDDINGS_PROVEEDOR no es fastembed: no hay modelo que descargar.\n")
        return 0
    try:
        ruta = ruta_modelo(config, descargar=True)
    except ModeloNoDisponible as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    revision = revision_configurada(config) or "main"
    sys.stdout.write(f"Modelo {config.embeddings_modelo} (revisión {revision}) listo en {ruta}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
