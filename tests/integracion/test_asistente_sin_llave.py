"""D8: sin llave de modelo el chat lo explica sin fallar y todo lo demás funciona."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cotejo.asistente.servicio import MOTIVO_SIN_LLAVE
from cotejo.config import Settings
from cotejo.modelos import Conversacion, CuotaUso, MensajeChat
from tests.apoyo.fabricas import crear_usuario
from tests.integracion.apoyo_asistente import Entrar, factura_con


def test_sin_llave_el_chat_explica_y_el_resto_funciona(
    cliente: TestClient, sesion: Session, config: Settings, entrar_como: Entrar
) -> None:
    assert config.asistente_configurado is False
    capturista = crear_usuario(sesion, rol="capturista")
    factura = factura_con(sesion, "1160.00", "2026-09-20")
    entrar_como(capturista.id)

    estado = cliente.get("/api/asistente/estado")
    assert estado.status_code == 200
    assert estado.json() == {
        "disponible": False,
        "motivo": "El asistente no está configurado en esta instalación. El resto de Cotejo funciona normalmente.",
        "modelo": None,
        "restantes_hoy": 20,
        "limite_dia": 20,
    }

    r = cliente.post("/api/asistente/mensajes", json={"conversacion_id": None, "texto": "¿Cuánto debemos?"})
    assert r.status_code == 503
    assert r.json()["error"] == {"codigo": "ASISTENTE_NO_CONFIGURADO", "mensaje": MOTIVO_SIN_LLAVE, "detalle": {}}
    # No se guardó nada ni se gastó cuota por una pregunta que no se pudo atender.
    for modelo in (MensajeChat, Conversacion, CuotaUso):
        assert sesion.scalar(select(func.count()).select_from(modelo)) == 0

    # Documentos, búsqueda y propuestas no dependen del modelo.
    assert cliente.get("/api/salud").status_code == 200
    subida = cliente.post(
        "/api/documentos", files=[("archivos", ("politica.txt", b"Los pagos se ejecutan los viernes.", "text/plain"))]
    )
    assert subida.status_code == 200 and subida.json()[0]["resultado"] == "indexado"
    busqueda = cliente.get("/api/busqueda", params={"q": "pagos viernes"})
    assert busqueda.status_code == 200 and len(busqueda.json()["resultados"]) == 1
    propuesta = cliente.post("/api/propuestas", json={"presupuesto_mxn": "2000.00", "horizonte": "vencidas"})
    assert propuesta.status_code == 200
    assert [x["factura"]["id"] for x in propuesta.json()["renglones"]] == [factura.id]
    assert cliente.get("/api/propuestas").json()["total"] == 1
    assert cliente.get("/api/asistente/conversacion").json() is None
