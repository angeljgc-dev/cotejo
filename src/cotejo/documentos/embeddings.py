"""Vectores de significado para la búsqueda (384 dimensiones).

Dos implementaciones del mismo protocolo: el modelo real multilingual-e5-small con fastembed (ONNX en CPU, sin
torch) y una determinista para pruebas, que no descarga nada. Con la determinista se prueban el indexado, el
SQL y la fusión; la calidad del modelo real se mide aparte en la evaluación del recuperador.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import numpy as np
from numpy.typing import NDArray

from cotejo.config import Settings
from cotejo.documentos.normalizar import normalizar
from cotejo.modelos import DIMENSION_EMBEDDING

if TYPE_CHECKING:
    # fastembed carga onnxruntime al importarse: solo se importa de verdad cuando se usa el modelo real.
    from fastembed import TextEmbedding

_log = logging.getLogger("cotejo.documentos")

Vector = NDArray[np.float32]

# Revisión del repositorio intfloat/multilingual-e5-small con la que se midió la evaluación del recuperador.
REVISION_E5_SMALL = "614241f622f53c4eeff9890bdc4f31cfecc418b3"
MODELO_E5_SMALL = "intfloat/multilingual-e5-small"
# Carpeta local (ignorada por git) cuando HF_HOME no está definida.
CARPETA_MODELOS = ".modelos"
ARCHIVOS_TOKENIZADOR = ("config.json", "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json")
# e5 se entrenó con estos prefijos; sin ellos la calidad baja.
PREFIJO_PASAJE = "passage: "
PREFIJO_CONSULTA = "query: "
LOTE = 32

_PALABRA = re.compile(r"[a-z0-9ñ]+")


class ModeloNoDisponible(RuntimeError):
    """El modelo de embeddings no está descargado y no se pudo obtener."""


class Embedder(Protocol):
    nombre: str

    def pasajes(self, textos: Sequence[str]) -> list[Vector]: ...

    def consulta(self, texto: str) -> Vector: ...


class EmbedderDeterminista:
    """Bolsa de palabras proyectada con un hash: mismo texto, mismo vector, sin modelo ni red.

    Dos textos que comparten palabras quedan cerca; no entiende sinónimos. Suficiente para probar la tubería.
    """

    nombre = "determinista"

    def _vector(self, texto: str) -> Vector:
        vector = np.zeros(DIMENSION_EMBEDDING, dtype=np.float32)
        for palabra in _PALABRA.findall(normalizar(texto)):
            resumen = hashlib.sha256(palabra.encode("utf-8")).digest()
            indice = int.from_bytes(resumen[:4], "big") % DIMENSION_EMBEDDING
            vector[indice] += 1.0 if resumen[4] % 2 == 0 else -1.0
        norma = float(np.linalg.norm(vector))
        if norma == 0.0:
            # pgvector no define la distancia coseno del vector cero.
            vector[0] = 1.0
            return vector
        normalizado: Vector = vector / np.float32(norma)
        return normalizado

    def pasajes(self, textos: Sequence[str]) -> list[Vector]:
        return [self._vector(t) for t in textos]

    def consulta(self, texto: str) -> Vector:
        return self._vector(texto)


def carpeta_cache() -> Path | None:
    """None deja que la biblioteca de Hugging Face use HF_HOME; sin esa variable se usa una carpeta local."""
    if os.environ.get("HF_HOME", "").strip():
        return None
    return Path.cwd() / CARPETA_MODELOS


def revision_configurada(config: Settings) -> str | None:
    if config.embeddings_revision:
        return config.embeddings_revision
    return REVISION_E5_SMALL if config.embeddings_modelo == MODELO_E5_SMALL else None


def ruta_modelo(config: Settings, *, descargar: bool) -> Path:
    """Carpeta local con el ONNX y el tokenizador de la revisión fijada. Solo usa la red si `descargar`."""
    from huggingface_hub import snapshot_download
    from huggingface_hub.errors import LocalEntryNotFoundError

    revision = revision_configurada(config)
    cache = carpeta_cache()
    patrones = [config.embeddings_archivo, *ARCHIVOS_TOKENIZADOR]
    try:
        local = Path(
            snapshot_download(
                config.embeddings_modelo,
                revision=revision,
                cache_dir=cache,
                allow_patterns=patrones,
                local_files_only=True,
            )
        )
        if (local / config.embeddings_archivo).is_file():
            return local
    except LocalEntryNotFoundError:
        _log.info("El modelo %s no está en la caché local.", config.embeddings_modelo)
    if not descargar:
        raise ModeloNoDisponible(
            f"El modelo de embeddings {config.embeddings_modelo} no está descargado. "
            "Corre: python -m cotejo.documentos.descargar_modelo"
        )
    _log.info("Descargando el modelo de embeddings %s (una sola vez).", config.embeddings_modelo)
    try:
        return Path(
            snapshot_download(config.embeddings_modelo, revision=revision, cache_dir=cache, allow_patterns=patrones)
        )
    except OSError as exc:
        raise ModeloNoDisponible(
            f"No se pudo descargar el modelo de embeddings {config.embeddings_modelo}: {exc}"
        ) from exc


class EmbedderFastembed:
    """multilingual-e5-small en ONNX. El modelo se carga en el primer uso y se queda en memoria."""

    def __init__(self, config: Settings) -> None:
        self.nombre = config.embeddings_modelo
        self._config = config
        self._modelo: TextEmbedding | None = None
        # La sesión ONNX no se comparte entre hilos: el candado serializa la carga y las inferencias.
        self._candado = threading.Lock()

    def _cargar(self) -> TextEmbedding:
        from fastembed import TextEmbedding
        from fastembed.common.model_description import ModelSource, PoolingType

        config = self._config
        registrados = {str(m["model"]) for m in TextEmbedding.list_supported_models()}
        if config.embeddings_modelo not in registrados:
            # El modelo no viene en el catálogo de fastembed: se registra con el ONNX oficial de su repositorio.
            TextEmbedding.add_custom_model(
                model=config.embeddings_modelo,
                pooling=PoolingType.MEAN,
                normalization=True,
                sources=ModelSource(hf=config.embeddings_modelo),
                dim=DIMENSION_EMBEDDING,
                model_file=config.embeddings_archivo,
                license="mit",
            )
        ruta = ruta_modelo(config, descargar=True)
        return TextEmbedding(model_name=config.embeddings_modelo, specific_model_path=str(ruta))

    def _vectores(self, textos: Sequence[str]) -> list[Vector]:
        with self._candado:
            if self._modelo is None:
                self._modelo = self._cargar()
            return [np.asarray(v, dtype=np.float32) for v in self._modelo.embed(list(textos), batch_size=LOTE)]

    def pasajes(self, textos: Sequence[str]) -> list[Vector]:
        if not textos:
            return []
        return self._vectores([PREFIJO_PASAJE + t for t in textos])

    def consulta(self, texto: str) -> Vector:
        return self._vectores([PREFIJO_CONSULTA + texto])[0]


_instancias: dict[tuple[str, str, str, str | None], Embedder] = {}
_candado_instancias = threading.Lock()


def obtener_embedder(config: Settings) -> Embedder:
    """Una sola instancia por proceso y configuración: cargar el modelo cuesta cerca de 1 GB de memoria."""
    clave = (
        config.embeddings_proveedor,
        config.embeddings_modelo,
        config.embeddings_archivo,
        config.embeddings_revision,
    )
    with _candado_instancias:
        if clave not in _instancias:
            _instancias[clave] = (
                EmbedderDeterminista() if config.embeddings_proveedor == "determinista" else EmbedderFastembed(config)
            )
        return _instancias[clave]
