"""Cliente del modelo de lenguaje detrás de un protocolo propio (D9).

El resto del asistente solo conoce `ClienteModelo`. La implementación real usa el SDK `openai` contra cualquier
API compatible (se configura con URL base, modelo y llave); en pruebas se sustituye por un cliente guionado.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol

import httpx2
import openai
from openai.types.chat import (
    ChatCompletionAssistantMessageParam,
    ChatCompletionFunctionToolParam,
    ChatCompletionMessageFunctionToolCallParam,
    ChatCompletionMessageParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionToolMessageParam,
    ChatCompletionUserMessageParam,
)

from cotejo.config import Settings

RolMensaje = Literal["system", "user", "assistant", "tool"]

TIEMPO_POR_LLAMADA_S = 30.0
REINTENTOS = 1
MAX_TOKENS_SALIDA = 1500


@dataclass(frozen=True)
class LlamadaHerramienta:
    id: str
    nombre: str
    argumentos_json: str


@dataclass(frozen=True)
class MensajeModelo:
    """Un mensaje de la conversación con el modelo, independiente del proveedor."""

    rol: RolMensaje
    contenido: str | None = None
    # Solo en mensajes del asistente: las herramientas que pidió.
    llamadas: tuple[LlamadaHerramienta, ...] = ()
    # Solo en mensajes de herramienta: a qué llamada responde.
    llamada_id: str | None = None


@dataclass(frozen=True)
class EsquemaHerramienta:
    nombre: str
    descripcion: str
    parametros: dict[str, object]


@dataclass(frozen=True)
class RespuestaModelo:
    texto: str | None
    llamadas: list[LlamadaHerramienta]
    modelo: str
    tokens_entrada: int | None = None
    tokens_salida: int | None = None


class ErrorModelo(Exception):
    """El proveedor del modelo falló o tardó demasiado. El mensaje es para la persona, sin datos internos."""

    def __init__(self, codigo: str, mensaje: str) -> None:
        super().__init__(mensaje)
        self.codigo = codigo
        self.mensaje = mensaje


class ClienteModelo(Protocol):
    modelo: str

    def completar(
        self, mensajes: Sequence[MensajeModelo], herramientas: Sequence[EsquemaHerramienta]
    ) -> RespuestaModelo: ...


def _a_mensaje_openai(mensaje: MensajeModelo) -> ChatCompletionMessageParam:
    if mensaje.rol == "system":
        return ChatCompletionSystemMessageParam(role="system", content=mensaje.contenido or "")
    if mensaje.rol == "user":
        return ChatCompletionUserMessageParam(role="user", content=mensaje.contenido or "")
    if mensaje.rol == "tool":
        return ChatCompletionToolMessageParam(
            role="tool", tool_call_id=mensaje.llamada_id or "", content=mensaje.contenido or ""
        )
    asistente = ChatCompletionAssistantMessageParam(role="assistant", content=mensaje.contenido)
    if mensaje.llamadas:
        asistente["tool_calls"] = [
            ChatCompletionMessageFunctionToolCallParam(
                id=llamada.id, type="function", function={"name": llamada.nombre, "arguments": llamada.argumentos_json}
            )
            for llamada in mensaje.llamadas
        ]
    return asistente


def _a_herramienta_openai(esquema: EsquemaHerramienta) -> ChatCompletionFunctionToolParam:
    return ChatCompletionFunctionToolParam(
        type="function",
        function={"name": esquema.nombre, "description": esquema.descripcion, "parameters": esquema.parametros},
    )


class ClienteOpenAI:
    """Chat con herramientas contra una API compatible con OpenAI (Groq, Gemini, OpenRouter y otras)."""

    def __init__(
        self,
        *,
        base_url: str,
        modelo: str,
        api_key: str,
        tiempo_s: float = TIEMPO_POR_LLAMADA_S,
        http_client: httpx2.Client | None = None,
    ) -> None:
        self.modelo = modelo
        self.base_url = base_url
        self._cliente = openai.OpenAI(
            base_url=base_url, api_key=api_key, timeout=tiempo_s, max_retries=REINTENTOS, http_client=http_client
        )

    def completar(
        self, mensajes: Sequence[MensajeModelo], herramientas: Sequence[EsquemaHerramienta]
    ) -> RespuestaModelo:
        try:
            # No se manda parallel_tool_calls: algunos modelos no lo aceptan; el bucle procesa una o varias.
            respuesta = self._cliente.chat.completions.create(
                model=self.modelo,
                messages=[_a_mensaje_openai(m) for m in mensajes],
                tools=[_a_herramienta_openai(h) for h in herramientas],
                tool_choice="auto",
                temperature=0,
                max_tokens=MAX_TOKENS_SALIDA,
            )
        except openai.RateLimitError as exc:
            raise ErrorModelo(
                "LIMITE_PROVEEDOR",
                "El proveedor del modelo alcanzó su límite de uso. Intenta de nuevo en unos minutos.",
            ) from exc
        except openai.APIConnectionError as exc:
            # Incluye el tiempo de espera agotado (APITimeoutError hereda de esta).
            raise ErrorModelo(
                "SIN_RESPUESTA", "El modelo de lenguaje no respondió a tiempo. Intenta de nuevo."
            ) from exc
        except openai.APIStatusError as exc:
            raise ErrorModelo(
                "ERROR_PROVEEDOR", f"El proveedor del modelo respondió con un error ({exc.status_code})."
            ) from exc
        except openai.OpenAIError as exc:
            raise ErrorModelo("ERROR_PROVEEDOR", "No se pudo consultar el modelo de lenguaje.") from exc
        if not respuesta.choices:
            raise ErrorModelo("RESPUESTA_VACIA", "El modelo de lenguaje devolvió una respuesta vacía.")
        mensaje = respuesta.choices[0].message
        llamadas = [
            LlamadaHerramienta(id=tc.id, nombre=tc.function.name, argumentos_json=tc.function.arguments or "")
            for tc in (mensaje.tool_calls or [])
            if tc.type == "function"
        ]
        uso = respuesta.usage
        return RespuestaModelo(
            texto=mensaje.content,
            llamadas=llamadas,
            modelo=respuesta.model or self.modelo,
            tokens_entrada=uso.prompt_tokens if uso else None,
            tokens_salida=uso.completion_tokens if uso else None,
        )


@dataclass
class _Cache:
    candado: threading.Lock = field(default_factory=threading.Lock)
    clientes: dict[tuple[str, str, str], ClienteOpenAI] = field(default_factory=dict)


_cache = _Cache()


def cliente_de_config(config: Settings) -> ClienteModelo | None:
    """Cliente real según la configuración, o None si no hay llave (D8). Se reutiliza entre peticiones."""
    if not config.asistente_configurado or config.llm_api_key is None:
        return None
    llave = config.llm_api_key.get_secret_value().strip()
    clave = (config.llm_base_url, config.llm_modelo, llave)
    with _cache.candado:
        if clave not in _cache.clientes:
            _cache.clientes[clave] = ClienteOpenAI(
                base_url=config.llm_base_url, modelo=config.llm_modelo, api_key=llave
            )
        return _cache.clientes[clave]
