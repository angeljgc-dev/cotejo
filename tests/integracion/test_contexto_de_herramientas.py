"""Lo que el modelo necesita ver para no afirmar de más (D1 y D2).

Dos errores vistos al evaluar con un modelo real: decir que nada impedía pagarle a un proveedor de la lista
69-B, y atribuirle a un proveedor el contrato de otro. En ambos casos el dato faltaba en el resultado de la
herramienta.
"""

from __future__ import annotations

from collections.abc import Sequence

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cotejo.asistente.cliente_modelo import MensajeModelo
from cotejo.asistente.guionado import PasoGuion, resultados_de_herramientas
from tests.apoyo.fabricas import crear_proveedor, crear_usuario
from tests.integracion.apoyo_asistente import Entrar, bloquear, elementos, factura_con, instalar_guion

RUTA = "/api/asistente/mensajes"


def test_el_adeudo_dice_que_facturas_estan_bloqueadas_para_pago(
    app: FastAPI, cliente: TestClient, sesion: Session, entrar_como: Entrar
) -> None:
    libre = crear_proveedor(sesion, nombre="Empaques Ficticios SA de CV")
    listado = crear_proveedor(sesion, nombre="Comercializadora Ficticia en Lista SA de CV")
    factura_con(sesion, "1000.00", "2026-10-01", proveedor=libre)
    factura_con(sesion, "2000.00", "2026-10-01", proveedor=listado)
    factura_con(sesion, "3000.00", "2026-10-05", proveedor=listado)
    bloquear(sesion, "LISTA_69B", proveedor=listado)
    guion = instalar_guion(
        app,
        [
            PasoGuion(
                llamadas=[
                    ("adeudo_proveedor", {"proveedor_id": libre.id}),
                    ("adeudo_proveedor", {"proveedor_id": listado.id}),
                ]
            ),
            PasoGuion(texto="Listo."),
        ],
    )
    entrar_como(crear_usuario(sesion, rol="capturista").id)
    assert cliente.post(RUTA, json={"texto": "¿Hay algo que impida pagarles?"}).status_code == 200

    del_libre, del_listado = resultados_de_herramientas(guion.recibidos[1])
    assert del_libre["facturas_bloqueadas"] == 0
    assert [f["bloqueada_para_pago"] for f in elementos(del_libre, "facturas")] == [False]
    assert del_listado["facturas_bloqueadas"] == 2
    assert [f["bloqueada_para_pago"] for f in elementos(del_listado, "facturas")] == [True, True]
    conteos = [f["alertas_abiertas"] for f in elementos(del_listado, "facturas")]
    assert all(isinstance(conteo, int) and conteo >= 1 for conteo in conteos)


def test_cada_fragmento_dice_de_que_proveedor_es_su_documento(
    app: FastAPI, cliente: TestClient, sesion: Session, entrar_como: Entrar
) -> None:
    transportes = crear_proveedor(sesion, nombre="Transportes Ficticios de la Sierra SA de CV")
    entrar_como(crear_usuario(sesion, rol="capturista").id)
    contrato = "CLÁUSULA CUARTA. El plazo de pago es de treinta días naturales desde la emisión de la factura."
    politica = "Política general: el plazo de pago se cuenta en días naturales y los pagos salen los viernes."
    cliente.post(
        "/api/documentos",
        data={"proveedor_id": str(transportes.id)},
        files=[("archivos", ("contrato_transportes.txt", contrato.encode(), "text/plain"))],
    )
    cliente.post("/api/documentos", files=[("archivos", ("politica.txt", politica.encode(), "text/plain"))])

    vistos: list[dict[str, object]] = []

    def responder(mensajes: Sequence[MensajeModelo]) -> PasoGuion:
        vistos.extend(elementos(resultados_de_herramientas(mensajes)[-1], "fragmentos"))
        return PasoGuion(texto="No lo encontré en los documentos cargados.")

    instalar_guion(app, [PasoGuion(llamadas=[("buscar_documentos", {"consulta": "plazo de pago"})]), responder])
    assert cliente.post(RUTA, json={"texto": "¿Qué plazo tiene Publicidad?"}).status_code == 200

    por_documento = {str(f["documento_no_confiable"]): f["proveedor_del_documento_no_confiable"] for f in vistos}
    assert por_documento == {"contrato_transportes.txt": transportes.nombre, "politica.txt": None}
