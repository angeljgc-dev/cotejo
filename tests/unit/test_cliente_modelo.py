"""D9 y E1: el proveedor del modelo se cambia por configuración y las pruebas nunca tocan un modelo real.

El cliente real se ejercita contra un transporte HTTP simulado: se comprueba qué manda (URL, llave, modelo,
herramientas, mensajes) y cómo interpreta la respuesta, sin salir a la red.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence

import httpx2
import pytest
from pydantic import SecretStr

from cotejo.asistente import esquemas
from cotejo.asistente.cliente_modelo import (
    ClienteOpenAI,
    ErrorModelo,
    EsquemaHerramienta,
    LlamadaHerramienta,
    MensajeModelo,
    cliente_de_config,
)
from cotejo.asistente.guionado import ClienteGuionado, PasoGuion
from cotejo.asistente.herramientas import HERRAMIENTAS
from cotejo.config import Settings

HERRAMIENTA = EsquemaHerramienta("adeudo_proveedor", "Adeudo de un proveedor.", {"type": "object", "properties": {}})


def _cliente(manejador: httpx2.MockTransport, base_url: str = "https://modelo.ejemplo.test/v1") -> ClienteOpenAI:
    return ClienteOpenAI(
        base_url=base_url,
        modelo="modelo-de-prueba",
        api_key="llave-ficticia",
        http_client=httpx2.Client(transport=manejador),
    )


def _respuesta(mensaje: dict[str, object]) -> dict[str, object]:
    return {
        "id": "resp-1",
        "object": "chat.completion",
        "created": 0,
        "model": "modelo-de-prueba-2026",
        "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", **mensaje}}],
        "usage": {"prompt_tokens": 321, "completion_tokens": 45, "total_tokens": 366},
    }


def test_las_pruebas_corren_sin_llave_y_sin_cliente_real(config: Settings) -> None:
    assert "LLM_API_KEY" not in os.environ
    assert config.asistente_configurado is False
    assert cliente_de_config(config) is None


def test_el_cliente_se_arma_con_url_modelo_y_llave_de_la_configuracion() -> None:
    config = Settings(
        llm_base_url="https://otro-proveedor.ejemplo.test/openai/v1",
        llm_modelo="otro/modelo-grande",
        llm_api_key=SecretStr("llave-ficticia-de-configuracion"),
    )
    cliente = cliente_de_config(config)
    assert isinstance(cliente, ClienteOpenAI)
    assert cliente.modelo == "otro/modelo-grande"
    assert cliente.base_url == "https://otro-proveedor.ejemplo.test/openai/v1"
    assert cliente_de_config(config) is cliente, "se reutiliza entre peticiones"
    otro = cliente_de_config(config.model_copy(update={"llm_modelo": "modelo-chico"}))
    assert isinstance(otro, ClienteOpenAI) and otro is not cliente and otro.modelo == "modelo-chico"


def test_manda_mensajes_y_herramientas_en_el_formato_de_chat_completions() -> None:
    peticiones: list[httpx2.Request] = []

    def manejador(peticion: httpx2.Request) -> httpx2.Response:
        peticiones.append(peticion)
        llamada = {
            "id": "call_1",
            "type": "function",
            "function": {"name": "adeudo_proveedor", "arguments": '{"proveedor_id": 7}'},
        }
        return httpx2.Response(200, json=_respuesta({"content": None, "tool_calls": [llamada]}))

    cliente = _cliente(httpx2.MockTransport(manejador))
    respuesta = cliente.completar(
        [
            MensajeModelo("system", "Eres el asistente."),
            MensajeModelo("user", "¿Cuánto debemos?"),
            MensajeModelo("assistant", None, llamadas=(LlamadaHerramienta("call_0", "buscar_proveedores", "{}"),)),
            MensajeModelo("tool", '{"proveedores":[]}', llamada_id="call_0"),
        ],
        [HERRAMIENTA],
    )
    (peticion,) = peticiones
    assert str(peticion.url) == "https://modelo.ejemplo.test/v1/chat/completions"
    assert peticion.headers["authorization"] == "Bearer llave-ficticia"
    cuerpo = json.loads(peticion.content)
    assert cuerpo["model"] == "modelo-de-prueba" and cuerpo["temperature"] == 0 and cuerpo["tool_choice"] == "auto"
    assert "parallel_tool_calls" not in cuerpo and "stream" not in cuerpo
    assert cuerpo["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "adeudo_proveedor",
                "description": "Adeudo de un proveedor.",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    assert [m["role"] for m in cuerpo["messages"]] == ["system", "user", "assistant", "tool"]
    assert cuerpo["messages"][2]["tool_calls"] == [
        {"id": "call_0", "type": "function", "function": {"name": "buscar_proveedores", "arguments": "{}"}}
    ]
    assert cuerpo["messages"][3] == {"role": "tool", "tool_call_id": "call_0", "content": '{"proveedores":[]}'}

    assert respuesta.texto is None
    assert respuesta.llamadas == [LlamadaHerramienta("call_1", "adeudo_proveedor", '{"proveedor_id": 7}')]
    assert respuesta.modelo == "modelo-de-prueba-2026"
    assert (respuesta.tokens_entrada, respuesta.tokens_salida) == (321, 45)


def test_respuesta_de_texto_sin_herramientas() -> None:
    transporte = httpx2.MockTransport(lambda _: httpx2.Response(200, json=_respuesta({"content": "Le debemos poco."})))
    respuesta = _cliente(transporte).completar([MensajeModelo("user", "hola")], [HERRAMIENTA])
    assert respuesta.texto == "Le debemos poco." and respuesta.llamadas == []


@pytest.mark.parametrize(
    ("estado", "codigo"),
    [(429, "LIMITE_PROVEEDOR"), (500, "ERROR_PROVEEDOR"), (401, "ERROR_PROVEEDOR"), (400, "ERROR_PROVEEDOR")],
)
def test_los_errores_del_proveedor_se_traducen_sin_filtrar_la_llave(estado: int, codigo: str) -> None:
    cuerpo = {"error": {"message": "fallo del proveedor con llave-ficticia", "type": "x"}}
    transporte = httpx2.MockTransport(lambda _: httpx2.Response(estado, json=cuerpo))
    cliente = ClienteOpenAI(
        base_url="https://modelo.ejemplo.test/v1",
        modelo="m",
        api_key="llave-ficticia",
        http_client=httpx2.Client(transport=transporte),
    )
    cliente._cliente.max_retries = 0
    with pytest.raises(ErrorModelo) as info:
        cliente.completar([MensajeModelo("user", "hola")], [HERRAMIENTA])
    assert info.value.codigo == codigo
    assert "llave-ficticia" not in info.value.mensaje


def test_sin_conexion_o_tiempo_agotado_es_un_error_del_modelo() -> None:
    def manejador(peticion: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectTimeout("tiempo agotado", request=peticion)

    cliente = _cliente(httpx2.MockTransport(manejador))
    cliente._cliente.max_retries = 0
    with pytest.raises(ErrorModelo) as info:
        cliente.completar([MensajeModelo("user", "hola")], [HERRAMIENTA])
    assert info.value.codigo == "SIN_RESPUESTA"


def test_cliente_guionado_devuelve_los_pasos_en_orden_y_registra_lo_recibido() -> None:
    def segundo(mensajes: Sequence[MensajeModelo]) -> PasoGuion:
        return PasoGuion(texto=f"recibí {len(mensajes)} mensajes")

    guion = ClienteGuionado(
        [PasoGuion(llamadas=[("antiguedad_saldos", {}), ("detalle_factura", "{no es json")]), segundo]
    )
    primera = guion.completar([MensajeModelo("user", "a")], [HERRAMIENTA])
    assert [(x.nombre, x.argumentos_json) for x in primera.llamadas] == [
        ("antiguedad_saldos", "{}"),
        ("detalle_factura", "{no es json"),
    ]
    assert len({x.id for x in primera.llamadas}) == 2
    assert guion.completar([MensajeModelo("user", "a"), MensajeModelo("user", "b")], []).texto == "recibí 2 mensajes"
    assert guion.completar([MensajeModelo("user", "c")], []).texto == "recibí 1 mensajes", "repite el último paso"
    assert len(guion.recibidos) == 3 and guion.herramientas_ofrecidas[0] == ["adeudo_proveedor"]
    with pytest.raises(ErrorModelo):
        ClienteGuionado([PasoGuion(error=ErrorModelo("X", "falla"))]).completar([], [])


def test_los_esquemas_de_herramientas_son_cerrados_y_compactos() -> None:
    assert list(HERRAMIENTAS) == [
        "buscar_proveedores",
        "adeudo_proveedor",
        "listar_facturas",
        "vencimientos",
        "totales_por_mes",
        "antiguedad_saldos",
        "detalle_factura",
        "buscar_documentos",
        "proponer_pagos",
    ]
    total = 0
    for herramienta in HERRAMIENTAS.values():
        esquema = herramienta.esquema
        assert esquema.parametros["type"] == "object"
        assert esquema.parametros["additionalProperties"] is False, herramienta.nombre
        assert "title" not in json.dumps(esquema.parametros)
        total += len(json.dumps(esquema.parametros, ensure_ascii=False)) + len(esquema.descripcion)
    assert total < 6000, "los esquemas caben holgados en el presupuesto de tokens por pregunta"
    # Ningún parámetro deja al modelo decidir quién es el usuario, la fecha o el estado de una propuesta.
    for prohibido in ("usuario", "rol", "estado_propuesta", "aprob", "hoy", "pagad"):
        assert prohibido not in json.dumps(esquemas.esquema_json(esquemas.ProponerPagos))
