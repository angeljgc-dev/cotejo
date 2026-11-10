"""G4: el servidor MCP ofrece las consultas y la creación de propuestas; ninguna herramienta aprueba ni paga."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal

import pytest
from mcp import Client
from mcp.server import MCPServer
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cotejo.asistente import esquemas
from cotejo.asistente.herramientas import HERRAMIENTAS
from cotejo.config import Settings
from cotejo.cxp import saldos
from cotejo.mcp_servidor import crear_servidor
from cotejo.modelos import Aplicacion, Bitacora, Propuesta, Usuario
from tests.apoyo.fabricas import crear_proveedor, crear_usuario
from tests.integracion.apoyo_asistente import bloquear, como_dict, elementos, factura_con

pytestmark = pytest.mark.anyio

VENCIDA = "2026-09-20"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def usuario_mcp(sesion: Session, config: Settings) -> Usuario:
    return crear_usuario(sesion, rol="capturista", usuario=config.mcp_usuario)


@pytest.fixture
def servidor(sesion: Session, config: Settings) -> MCPServer:
    @contextmanager
    def misma_sesion() -> Iterator[Session]:
        yield sesion

    return crear_servidor(misma_sesion, config)


async def test_expone_exactamente_las_nueve_herramientas_y_ninguna_aprueba_ni_paga(servidor: MCPServer) -> None:
    async with Client(servidor, raise_exceptions=True) as cliente:
        listado = await cliente.list_tools()
    nombres = [h.name for h in listado.tools]
    assert sorted(nombres) == sorted(HERRAMIENTAS)
    assert len(nombres) == 9
    for nombre in nombres:
        sin_proponer = nombre.replace("proponer_pagos", "")
        for prohibido in ("aprob", "pag", "borr", "edit", "rechaz", "elimin", "resolv", "sql"):
            assert prohibido not in sin_proponer, f"{nombre} no debería existir"
    # Los parámetros son los mismos que valida el asistente: no hay una puerta distinta por MCP.
    por_nombre = {h.name: h for h in listado.tools}
    for nombre, herramienta in HERRAMIENTAS.items():
        esperados = como_dict(esquemas.esquema_json(herramienta.argumentos)["properties"])
        ofrecidos = como_dict(por_nombre[nombre].input_schema.get("properties", {}))
        assert set(ofrecidos) == set(esperados), nombre
        assert por_nombre[nombre].description == herramienta.descripcion
    propiedades = set(como_dict(por_nombre["proponer_pagos"].input_schema["properties"]))
    assert propiedades == {"presupuesto_mxn", "horizonte", "factura_ids", "nota"}


async def test_consulta_y_propuesta_pendiente_por_mcp(
    servidor: MCPServer, sesion: Session, usuario_mcp: Usuario
) -> None:
    proveedor = crear_proveedor(sesion, nombre="Aceros Ficticios del Bajío SA de CV")
    factura = factura_con(sesion, "1160.00", VENCIDA, proveedor=proveedor)
    bloqueada = factura_con(sesion, "500.00", VENCIDA)
    bloquear(sesion, "POSIBLE_DUPLICADO", factura=bloqueada)
    async with Client(servidor, raise_exceptions=True) as cliente:
        adeudo = await cliente.call_tool("adeudo_proveedor", {"proveedor_id": proveedor.id})
        propuesta = await cliente.call_tool("proponer_pagos", {"presupuesto_mxn": "5000.00", "horizonte": "vencidas"})
        repetida = await cliente.call_tool("proponer_pagos", {"presupuesto_mxn": "5000.00", "horizonte": "vencidas"})
        invalida = await cliente.call_tool("proponer_pagos", {"presupuesto_mxn": "cinco mil", "horizonte": "vencidas"})
        sin_criterio = await cliente.call_tool("proponer_pagos", {"presupuesto_mxn": "5000.00"})
    datos = como_dict(adeudo.structured_content)
    assert datos["adeudo_mxn"] == "1160.00"
    assert elementos(datos, "facturas")[0]["factura_id"] == factura.id

    creada = como_dict(propuesta.structured_content)
    assert creada["estado"] == "pendiente" and creada["total_mxn"] == "1160.00"
    assert [x["factura_id"] for x in elementos(creada, "renglones")] == [factura.id]
    assert [(x["factura_id"], x["codigo"]) for x in elementos(creada, "excluidas")] == [
        (bloqueada.id, "ALERTA_BLOQUEANTE")
    ]
    guardada = sesion.scalars(select(Propuesta)).one()
    assert guardada.id == creada["propuesta_id"] and guardada.origen == "mcp"
    assert guardada.estado == "pendiente" and guardada.creada_por == usuario_mcp.id
    assert sesion.scalar(select(func.count()).select_from(Aplicacion)) == 0
    assert saldos.saldo(sesion, factura.id) == Decimal("1160.00")
    assert list(sesion.scalars(select(Bitacora.accion))) == ["PROPUESTA_CREADA"]

    # Las barreras son las mismas: lo que ya está en una propuesta pendiente o bloqueado no se propone otra vez.
    rechazo = como_dict(repetida.structured_content)
    assert rechazo["codigo"] == "PROPUESTA_VACIA" and "error" in rechazo
    assert sorted(str(x["codigo"]) for x in elementos(rechazo, "excluidas")) == [
        "ALERTA_BLOQUEANTE",
        "EN_OTRA_PROPUESTA",
    ]
    assert "Argumentos inválidos" in str(como_dict(invalida.structured_content)["error"])
    assert "horizonte o una lista" in str(como_dict(sin_criterio.structured_content)["error"])
    assert sesion.scalar(select(func.count()).select_from(Propuesta)) == 1


async def test_sin_usuario_configurado_o_sin_rol_capturista_no_propone(
    servidor: MCPServer, sesion: Session, config: Settings
) -> None:
    factura_con(sesion, "100.00", VENCIDA)
    argumentos: dict[str, object] = {"presupuesto_mxn": "5000.00", "horizonte": "vencidas"}
    async with Client(servidor, raise_exceptions=True) as cliente:
        sin_usuario = await cliente.call_tool("proponer_pagos", argumentos)
        crear_usuario(sesion, rol="aprobador", usuario=config.mcp_usuario)
        como_aprobador = await cliente.call_tool("proponer_pagos", argumentos)
        consulta = await cliente.call_tool("antiguedad_saldos", {})
    assert "MCP_USUARIO" in str(como_dict(sin_usuario.structured_content)["error"])
    assert "solo para el rol capturista" in str(como_dict(como_aprobador.structured_content)["error"])
    assert como_dict(consulta.structured_content)["adeudo_total_mxn"] == "100.00"
    assert sesion.scalar(select(func.count()).select_from(Propuesta)) == 0
