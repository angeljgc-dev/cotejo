"""Configuración de Cotejo leída de variables de entorno.

No se lee ningún archivo `.env` automáticamente: en desarrollo se usa `uv run --env-file .env ...` y en el
contenedor las variables del hospedaje. Así las pruebas nunca heredan una llave real por accidente.
"""

from __future__ import annotations

import secrets
from datetime import date
from functools import lru_cache
from typing import Literal

from pydantic import Field, PrivateAttr, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

LARGO_MINIMO_SECRET_KEY = 32

# Límites fijos de subida que la interfaz muestra en /api/configuracion.
ARCHIVOS_POR_CARGA = 50
MB_POR_XML = 2
MB_POR_DOCUMENTO = 10
MB_POR_PETICION = 25


class ErrorConfiguracion(RuntimeError):
    """La configuración no permite arrancar la aplicación."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_ignore_empty=True, extra="ignore", case_sensitive=False)

    # Por omisión producción: olvidar la variable nunca deja arrancar sin SECRET_KEY.
    entorno: Literal["desarrollo", "pruebas", "produccion"] = "produccion"
    database_url: SecretStr | None = None
    secret_key: SecretStr = SecretStr("")
    cookie_segura: bool = False
    confiar_proxy: bool = False
    frame_ancestors: str = "'none'"

    empresa_rfc: str = "EKU9003173C9"
    empresa_nombre: str = "Comercializadora Ficticia del Centro"
    zona_horaria: str = "America/Mexico_City"
    fecha_hoy_fija: date | None = None

    demo_habilitada: bool = False
    sembrar_si_vacia: bool = False
    semilla: int = 20261102

    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_modelo: str = "openai/gpt-oss-120b"
    llm_api_key: SecretStr | None = None

    chat_limite_visitante_dia: int = Field(default=20, ge=0)
    chat_limite_global_dia: int = Field(default=60, ge=0)
    cargas_limite_visitante_dia: int = Field(default=60, ge=0)

    embeddings_proveedor: Literal["fastembed", "determinista"] = "fastembed"
    embeddings_modelo: str = "intfloat/multilingual-e5-small"
    embeddings_archivo: str = "onnx/model.onnx"
    embeddings_revision: str | None = None
    busqueda_modo: Literal["hibrida", "texto"] = "hibrida"

    static_dir: str = "/app/static"
    mcp_usuario: str = "demo.capturista"
    eval_pausa_s: float = Field(default=3.0, ge=0)

    _clave_temporal: bytes = PrivateAttr(default=b"")

    @property
    def asistente_configurado(self) -> bool:
        return self.llm_api_key is not None and bool(self.llm_api_key.get_secret_value().strip())

    @property
    def aviso_demo(self) -> str | None:
        if not self.demo_habilitada:
            return None
        return "Demostración con datos ficticios: empresas, RFC e importes son inventados."

    def validar_para_arranque(self) -> None:
        """En producción la clave de firma es obligatoria; en desarrollo y pruebas se genera una temporal."""
        largo = len(self.secret_key.get_secret_value())
        if self.entorno == "produccion" and largo < LARGO_MINIMO_SECRET_KEY:
            raise ErrorConfiguracion(
                f"SECRET_KEY debe tener al menos {LARGO_MINIMO_SECRET_KEY} caracteres en producción."
            )

    def clave_firma(self) -> bytes:
        valor = self.secret_key.get_secret_value()
        if len(valor) >= LARGO_MINIMO_SECRET_KEY or self.entorno == "produccion":
            return valor.encode("utf-8")
        # Sin clave en desarrollo: una por proceso. Las sesiones no sobreviven a un reinicio, y está bien así.
        if not self._clave_temporal:
            self._clave_temporal = secrets.token_bytes(32)
        return self._clave_temporal


@lru_cache(maxsize=1)
def obtener_config() -> Settings:
    config = Settings()
    config.validar_para_arranque()
    return config
