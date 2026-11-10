"""D1, D2, D3 y D7 con el cliente guionado: el modelo se sustituye; el bucle, las herramientas y la verificación no."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cotejo.asistente.bucle import MAX_LLAMADAS_HERRAMIENTA, MAX_LLAMADAS_MODELO, TEXTO_LIMITE_PASOS
from cotejo.asistente.cliente_modelo import ErrorModelo, MensajeModelo
from cotejo.asistente.guionado import PasoGuion, resultados_de_herramientas
from cotejo.asistente.prompt import VERSION_PROMPT
from cotejo.cxp import saldos
from cotejo.modelos import Aplicacion, Bitacora, CuotaUso, MensajeChat, Propuesta
from tests.apoyo.fabricas import crear_proveedor, crear_usuario
from tests.integracion.apoyo_asistente import (
    Entrar,
    bloquear,
    como_dict,
    elementos,
    factura_con,
    instalar_guion,
    texto_con,
    ultimo_resultado,
)

VENCIDA, RECIENTE, FUTURA = "2026-09-20", "2026-10-01", "2026-10-20"
RUTA = "/api/asistente/mensajes"


def _pesos(valor: object) -> str:
    return f"${Decimal(str(valor)):,.2f}"


def _adeudo_del_encontrado(mensajes: Sequence[MensajeModelo]) -> PasoGuion:
    proveedor = elementos(ultimo_resultado(mensajes), "proveedores")[0]
    return PasoGuion(llamadas=[("adeudo_proveedor", {"proveedor_id": proveedor["proveedor_id"]})])


def test_pregunta_numerica_la_cifra_sale_de_la_herramienta_y_lista_sus_facturas(
    app: FastAPI, cliente: TestClient, sesion: Session, entrar_como: Entrar
) -> None:
    usuario = crear_usuario(sesion, rol="capturista")
    aceros = crear_proveedor(sesion, nombre="Aceros Ficticios del Bajío SA de CV")
    f1 = factura_con(sesion, "30000.10", VENCIDA, proveedor=aceros)
    f2 = factura_con(sesion, "18719.90", FUTURA, proveedor=aceros)
    factura_con(sesion, "999.00", RECIENTE, proveedor=crear_proveedor(sesion, nombre="Empaques Ficticios SA de CV"))
    guion = instalar_guion(
        app,
        [
            PasoGuion(llamadas=[("buscar_proveedores", {"texto": "aceros"})]),
            _adeudo_del_encontrado,
            texto_con(lambda r: f"A Aceros Ficticios le debemos {_pesos(r['adeudo_mxn'])} MXN en 2 facturas."),
        ],
    )
    entrar_como(usuario.id)

    r = cliente.post(RUTA, json={"conversacion_id": None, "texto": "¿Cuánto le debemos a Aceros?"})
    assert r.status_code == 200, r.text
    mensaje = r.json()
    assert mensaje["rol"] == "asistente" and mensaje["modelo"] == "guionado"
    assert mensaje["texto"] == "A Aceros Ficticios le debemos $48,720.00 MXN en 2 facturas."
    assert mensaje["advertencias"] == [] and mensaje["citas"] == [] and mensaje["propuesta_id"] is None
    assert [h["nombre"] for h in mensaje["herramientas"]] == ["buscar_proveedores", "adeudo_proveedor"]
    adeudo = mensaje["herramientas"][1]
    assert adeudo["argumentos"] == {"proveedor_id": aceros.id} and adeudo["error"] is None
    assert adeudo["resumen"] == "Adeudo de 48720.00 MXN en 2 facturas con saldo" and adeudo["duracion_ms"] >= 0
    # La respuesta lista las facturas en que se basa, con su saldo actual.
    assert [(f["id"], f["saldo"]) for f in mensaje["facturas_base"]] == [(f1.id, "30000.10"), (f2.id, "18719.90")]
    assert mensaje["facturas_base"][0]["proveedor"] == {"id": aceros.id, "rfc": aceros.rfc, "nombre": aceros.nombre}

    # El modelo recibió instrucciones, la pregunta y, después, los resultados como JSON; nunca SQL.
    primera, segunda, tercera = guion.recibidos
    assert [m.rol for m in primera] == ["system", "user"]
    assert "Hoy es lunes 2 de noviembre de 2026" in (primera[0].contenido or "")
    assert [m.rol for m in tercera] == ["system", "user", "assistant", "tool", "assistant", "tool"]
    encontrado = elementos(resultados_de_herramientas(segunda)[0], "proveedores")[0]
    assert encontrado["nombre_no_confiable"] == aceros.nombre and encontrado["adeudo_mxn"] == "48720.00"
    visto = resultados_de_herramientas(tercera)[1]
    assert visto["adeudo_mxn"] == "48720.00" and visto["facturas_omitidas"] == 0
    assert "proponer_pagos" in guion.herramientas_ofrecidas[0]

    # D7: el mensaje guardado conserva qué se consultó y qué devolvió cada herramienta.
    guardado = sesion.scalars(select(MensajeChat).where(MensajeChat.id == mensaje["id"])).one()
    assert guardado.facturas_base == [f1.id, f2.id] and guardado.pasos == 3
    assert guardado.version_prompt == VERSION_PROMPT and guardado.tokens_entrada == 300
    registro = como_dict(guardado.herramientas[1])
    assert como_dict(registro["resultado"])["adeudo_mxn"] == "48720.00"
    pregunta = sesion.scalars(
        select(MensajeChat).where(MensajeChat.conversacion_id == guardado.conversacion_id, MensajeChat.rol == "usuario")
    ).one()
    assert pregunta.texto == "¿Cuánto le debemos a Aceros?"


def test_una_cifra_que_no_viene_de_una_herramienta_queda_advertida(
    app: FastAPI, cliente: TestClient, sesion: Session, entrar_como: Entrar
) -> None:
    proveedor = crear_proveedor(sesion)
    factura_con(sesion, "30000.10", VENCIDA, proveedor=proveedor)
    factura_con(sesion, "18719.90", FUTURA, proveedor=proveedor)
    entrar_como(crear_usuario(sesion).id)
    consulta = PasoGuion(llamadas=[("listar_facturas", {"proveedor_id": proveedor.id})])

    # El modelo inventa un total.
    instalar_guion(app, [consulta, PasoGuion(texto="Le debemos $52,000.00 en total.")])
    inventada = cliente.post(RUTA, json={"texto": "¿Cuánto le debemos?"}).json()
    assert [a["codigo"] for a in inventada["advertencias"]] == ["CIFRA_NO_RESPALDADA"]
    assert "52,000.00" in inventada["advertencias"][0]["mensaje"]

    # El modelo hace la cuenta por su lado: suma solo una parte y redondea.
    instalar_guion(app, [consulta, PasoGuion(texto="Las facturas suman 30,000.10 + 18,719.90, unos 48.7 mil pesos.")])
    calculada = cliente.post(RUTA, json={"texto": "¿Cuánto le debemos?"}).json()
    assert [a["codigo"] for a in calculada["advertencias"]] == ["CIFRA_NO_RESPALDADA"]
    assert "48.7 mil" in calculada["advertencias"][0]["mensaje"]
    assert "30,000.10" not in calculada["advertencias"][0]["mensaje"]

    # Sin consultar nada, cualquier importe queda sin respaldo.
    instalar_guion(app, [PasoGuion(texto="El adeudo total es de $1,234,567.89.")])
    sin_herramientas = cliente.post(RUTA, json={"texto": "¿Cuánto debemos en total?"}).json()
    assert sin_herramientas["herramientas"] == [] and sin_herramientas["facturas_base"] == []
    assert [a["codigo"] for a in sin_herramientas["advertencias"]] == ["CIFRA_NO_RESPALDADA"]

    # El total que sí calculó la base pasa limpio.
    instalar_guion(app, [consulta, texto_con(lambda r: f"El saldo total es {_pesos(r['saldo_total_mxn'])}.")])
    correcta = cliente.post(RUTA, json={"texto": "¿Cuánto le debemos?"}).json()
    assert correcta["texto"] == "El saldo total es $48,720.00." and correcta["advertencias"] == []


def test_respuesta_sobre_un_contrato_cita_documento_y_pagina_y_la_cita_abre_el_fragmento(
    app: FastAPI, cliente: TestClient, sesion: Session, entrar_como: Entrar
) -> None:
    entrar_como(crear_usuario(sesion, rol="capturista").id)
    contrato = "CLÁUSULA SEXTA. El plazo de pago es de cuarenta y cinco días naturales desde la emisión de la factura."
    subida = cliente.post(
        "/api/documentos", files=[("archivos", ("contrato_aceros.txt", contrato.encode(), "text/plain"))]
    )
    documento_id = subida.json()[0]["documento_id"]
    buscar = PasoGuion(llamadas=[("buscar_documentos", {"consulta": "plazo de pago de la factura"})])

    def citar(mensajes: Sequence[MensajeModelo]) -> PasoGuion:
        fragmento = elementos(ultimo_resultado(mensajes), "fragmentos")[0]
        assert "cuarenta y cinco días" in str(fragmento["texto_no_confiable"])
        return PasoGuion(
            texto=f"El plazo de pago es de cuarenta y cinco días naturales [F:{fragmento['fragmento_id']}]."
        )

    instalar_guion(app, [buscar, citar])
    r = cliente.post(RUTA, json={"texto": "¿Cuál es el plazo de pago con Aceros?"})
    assert r.status_code == 200, r.text
    mensaje = r.json()
    (cita,) = mensaje["citas"]
    assert cita["documento_id"] == documento_id and cita["documento"] == "contrato_aceros.txt" and cita["pagina"] == 1
    assert f"[F:{cita['fragmento_id']}]" in mensaje["texto"] and mensaje["advertencias"] == []
    fragmento = cliente.get(f"/api/fragmentos/{cita['fragmento_id']}").json()
    assert fragmento["texto"] == contrato and fragmento["documento"]["id"] == documento_id

    # Una cita a un fragmento que no se devolvió en este turno se quita y se advierte.
    def citar_de_mas(mensajes: Sequence[MensajeModelo]) -> PasoGuion:
        real = elementos(ultimo_resultado(mensajes), "fragmentos")[0]["fragmento_id"]
        return PasoGuion(texto=f"El plazo es de cuarenta y cinco días [F:{real}] y la mora es del 9% [F:987654].")

    instalar_guion(app, [buscar, citar_de_mas])
    mezclada = cliente.post(RUTA, json={"texto": "¿Plazo y mora?"}).json()
    assert [c["fragmento_id"] for c in mezclada["citas"]] == [cita["fragmento_id"]]
    assert "987654" not in mezclada["texto"]
    assert [a["codigo"] for a in mezclada["advertencias"]] == ["CITA_INVALIDA"]

    # Citar un fragmento real sin haber buscado en este turno tampoco vale.
    instalar_guion(app, [PasoGuion(texto=f"El plazo es de cuarenta y cinco días [F:{cita['fragmento_id']}].")])
    sin_buscar = cliente.post(RUTA, json={"texto": "¿Plazo?"}).json()
    assert sin_buscar["citas"] == [] and [a["codigo"] for a in sin_buscar["advertencias"]] == ["CITA_INVALIDA"]

    # Si no está en los documentos, lo dice y no cita nada.
    instalar_guion(
        app,
        [
            PasoGuion(llamadas=[("buscar_documentos", {"consulta": "seguro de responsabilidad civil"})]),
            PasoGuion(texto="No lo encontré en los documentos cargados."),
        ],
    )
    negativa = cliente.post(RUTA, json={"texto": "¿Qué seguro de responsabilidad civil exige el contrato?"}).json()
    assert negativa["texto"] == "No lo encontré en los documentos cargados."
    assert negativa["citas"] == [] and negativa["advertencias"] == []


def test_proponer_pagos_crea_una_propuesta_pendiente_y_no_paga_nada(
    app: FastAPI, cliente: TestClient, sesion: Session, entrar_como: Entrar
) -> None:
    capturista = crear_usuario(sesion, rol="capturista")
    vieja = factura_con(sesion, "600.00", VENCIDA)
    grande = factura_con(sesion, "500.00", RECIENTE)
    futura = factura_con(sesion, "400.00", FUTURA)
    instalar_guion(
        app,
        [
            PasoGuion(llamadas=[("proponer_pagos", {"presupuesto_mxn": "1000.00", "horizonte": "esta_semana"})]),
            texto_con(
                lambda r: (
                    f"Creé la propuesta {r['propuesta_id']} por {_pesos(r['total_mxn'])} de un presupuesto de "
                    f"{_pesos(r['presupuesto_mxn'])}. Queda pendiente de aprobación."
                )
            ),
        ],
    )
    entrar_como(capturista.id)
    r = cliente.post(RUTA, json={"texto": "Propón los pagos de esta semana con presupuesto de 1,000 pesos"})
    assert r.status_code == 200, r.text
    mensaje = r.json()
    propuesta = sesion.scalars(select(Propuesta)).one()
    assert mensaje["propuesta_id"] == propuesta.id and mensaje["advertencias"] == []
    assert mensaje["texto"].startswith(f"Creé la propuesta {propuesta.id} por $600.00 de un presupuesto de $1,000.00.")
    assert propuesta.estado == "pendiente" and propuesta.origen == "asistente"
    assert propuesta.creada_por == capturista.id and propuesta.mensaje_id == mensaje["id"]
    assert propuesta.total_mxn == Decimal("600.00") and propuesta.decidida_por is None
    assert [(x.factura_id, x.importe, x.razon) for x in propuesta.renglones] == [
        (vieja.id, Decimal("600.00"), "Vencida hace 13 días")
    ]
    assert [como_dict(e)["codigo"] for e in propuesta.excluidas] == ["EXCEDE_PRESUPUESTO"]
    assert [f["id"] for f in mensaje["facturas_base"]] == [vieja.id]
    # Nunca marca nada como pagado.
    assert sesion.scalar(select(func.count()).select_from(Aplicacion)) == 0
    for factura in (vieja, grande, futura):
        assert saldos.saldo(sesion, factura.id) == factura.total
    acciones = list(sesion.scalars(select(Bitacora.accion).order_by(Bitacora.id)))
    assert acciones == ["PROPUESTA_CREADA"]
    detalle = cliente.get(f"/api/propuestas/{propuesta.id}").json()
    assert detalle["origen"] == "asistente" and detalle["puede_decidir"] is False


def test_lo_que_pide_el_modelo_se_valida_antes_de_ejecutarse(
    app: FastAPI, cliente: TestClient, sesion: Session, entrar_como: Entrar
) -> None:
    proveedor = crear_proveedor(sesion)
    factura_con(sesion, "100.00", VENCIDA, proveedor=proveedor)
    entrar_como(crear_usuario(sesion).id)
    guion = instalar_guion(
        app,
        [
            PasoGuion(
                llamadas=[
                    ("ejecutar_sql", {"sql": "update facturas set total = 0"}),
                    ("adeudo_proveedor", "{esto no es json"),
                    ("adeudo_proveedor", "[1, 2]"),
                    ("adeudo_proveedor", {"proveedor_id": "abc"}),
                    ("adeudo_proveedor", {"proveedor_id": proveedor.id, "usuario_id": 1}),
                    ("adeudo_proveedor", {"proveedor_id": 987654}),
                    ("totales_por_mes", {"medida": "saldo", "desde_mes": "2026-13", "hasta_mes": "2026-12"}),
                    ("detalle_factura", {}),
                    ("adeudo_proveedor", {"proveedor_id": proveedor.id}),
                ]
            ),
            texto_con(lambda r: f"El adeudo es de {_pesos(r['adeudo_mxn'])}."),
        ],
    )
    mensaje = cliente.post(RUTA, json={"texto": "¿Cuánto le debemos?"}).json()
    errores = [h["error"] for h in mensaje["herramientas"]]
    assert "no existe" in errores[0] and "ejecutar_sql" not in mensaje["herramientas"][0]["resumen"]
    assert errores[1] == "Los argumentos no son JSON válido."
    assert errores[2] == "Los argumentos deben ser un objeto JSON."
    assert errores[3].startswith("Argumentos inválidos. proveedor_id")
    assert errores[4].startswith("Argumentos inválidos. usuario_id"), "no se aceptan campos de más"
    assert errores[5].startswith("No existe el proveedor 987654")
    assert errores[6].startswith("Argumentos inválidos. desde_mes")
    assert errores[7].startswith("Argumentos inválidos.")
    assert errores[8] is None
    assert mensaje["texto"] == "El adeudo es de $100.00." and mensaje["advertencias"] == []
    # Cada error se le devolvió al modelo como resultado, y la conversación siguió.
    devueltos = resultados_de_herramientas(guion.recibidos[1])
    assert len(devueltos) == 9 and all("error" in d for d in devueltos[:8]) and "error" not in devueltos[8]


def test_limite_de_pasos_y_de_herramientas(
    app: FastAPI, cliente: TestClient, sesion: Session, entrar_como: Entrar
) -> None:
    entrar_como(crear_usuario(sesion).id)
    insistente = PasoGuion(llamadas=[("antiguedad_saldos", {})] * 3)
    guion = instalar_guion(app, [insistente])
    mensaje = cliente.post(RUTA, json={"texto": "Dame todo"}).json()
    assert mensaje["texto"] == TEXTO_LIMITE_PASOS
    assert [a["codigo"] for a in mensaje["advertencias"]] == ["LIMITE_PASOS"]
    assert len(guion.recibidos) == MAX_LLAMADAS_MODELO
    usos = mensaje["herramientas"]
    assert len(usos) == MAX_LLAMADAS_MODELO * 3
    assert [u["error"] is None for u in usos] == [True] * MAX_LLAMADAS_HERRAMIENTA + [False] * (
        len(usos) - MAX_LLAMADAS_HERRAMIENTA
    )
    assert "máximo de herramientas" in usos[-1]["error"]


def test_conversacion_guarda_historial_de_texto_y_es_privada(
    app: FastAPI, cliente: TestClient, sesion: Session, entrar_como: Entrar
) -> None:
    ana, luis = crear_usuario(sesion), crear_usuario(sesion)
    entrar_como(ana.id)
    assert cliente.get("/api/asistente/conversacion").json() is None
    creada = cliente.post("/api/asistente/conversaciones", json={})
    assert creada.status_code == 200
    conversacion_id = creada.json()["id"]
    assert cliente.get("/api/asistente/conversacion").json() is None, "una conversación sin mensajes no cuenta"

    guion = instalar_guion(app, [PasoGuion(llamadas=[("antiguedad_saldos", {})]), PasoGuion(texto="Sin adeudos.")])
    primera = cliente.post(RUTA, json={"conversacion_id": conversacion_id, "texto": "¿Cómo está la antigüedad?"}).json()
    assert primera["conversacion_id"] == conversacion_id
    guion = instalar_guion(app, [PasoGuion(texto="De nada.")])
    cliente.post(RUTA, json={"conversacion_id": conversacion_id, "texto": "Gracias"})
    # El historial que ve el modelo es solo texto: sin los resultados de herramientas de turnos anteriores.
    assert [(m.rol, m.contenido) for m in guion.recibidos[0][1:]] == [
        ("user", "¿Cómo está la antigüedad?"),
        ("assistant", "Sin adeudos."),
        ("user", "Gracias"),
    ]

    vista = cliente.get(f"/api/asistente/conversaciones/{conversacion_id}").json()
    assert [(m["rol"], m["texto"]) for m in vista["mensajes"]] == [
        ("usuario", "¿Cómo está la antigüedad?"),
        ("asistente", "Sin adeudos."),
        ("usuario", "Gracias"),
        ("asistente", "De nada."),
    ]
    assert vista["mensajes"][1]["herramientas"][0]["nombre"] == "antiguedad_saldos"
    assert vista["mensajes"][0]["herramientas"] == [] and vista["mensajes"][0]["modelo"] is None
    assert cliente.get("/api/asistente/conversacion").json() == vista

    # Otro usuario no la ve ni puede escribir en ella.
    entrar_como(luis.id)
    assert cliente.get(f"/api/asistente/conversaciones/{conversacion_id}").status_code == 404
    ajena = cliente.post(RUTA, json={"conversacion_id": conversacion_id, "texto": "Hola"})
    assert ajena.status_code == 404 and ajena.json()["error"]["codigo"] == "CONVERSACION_NO_ENCONTRADA"
    assert cliente.get("/api/asistente/conversacion").json() is None
    for cuerpo in ({"texto": ""}, {"texto": "x" * 2001}, {"conversacion_id": "no-es-uuid", "texto": "hola"}, {}):
        assert cliente.post(RUTA, json=cuerpo).status_code == 422


def test_si_el_proveedor_del_modelo_falla_responde_502_y_no_deja_nada_a_medias(
    app: FastAPI, cliente: TestClient, sesion: Session, entrar_como: Entrar
) -> None:
    capturista = crear_usuario(sesion, rol="capturista")
    factura = factura_con(sesion, "600.00", VENCIDA)
    entrar_como(capturista.id)
    instalar_guion(
        app,
        [
            PasoGuion(llamadas=[("proponer_pagos", {"presupuesto_mxn": "1000.00", "horizonte": "vencidas"})]),
            PasoGuion(error=ErrorModelo("LIMITE_PROVEEDOR", "El proveedor del modelo alcanzó su límite de uso.")),
        ],
    )
    r = cliente.post(RUTA, json={"texto": "Propón los pagos vencidos con 1,000 pesos"})
    assert r.status_code == 502
    error = r.json()["error"]
    assert error["codigo"] == "MODELO_NO_DISPONIBLE" and error["detalle"] == {"causa": "LIMITE_PROVEEDOR"}
    # La propuesta que se alcanzó a crear en este turno se deshizo; la pregunta y el uso de cuota sí quedan.
    assert sesion.scalar(select(func.count()).select_from(Propuesta)) == 0
    assert list(sesion.scalars(select(Bitacora.accion))) == []
    assert saldos.saldo(sesion, factura.id) == Decimal("600.00")
    guardados = sesion.scalars(select(MensajeChat)).all()
    assert [(m.rol, m.texto, m.error) for m in guardados] == [
        ("usuario", "Propón los pagos vencidos con 1,000 pesos", "LIMITE_PROVEEDOR")
    ]
    assert sesion.scalar(select(CuotaUso.contador).where(CuotaUso.clave == "chat:global")) == 1

    # Al reintentar, la pregunta fallida no se manda como historial.
    guion = instalar_guion(app, [PasoGuion(texto="Listo.")])
    conversacion_id = str(guardados[0].conversacion_id)
    assert cliente.post(RUTA, json={"conversacion_id": conversacion_id, "texto": "¿Sigues ahí?"}).status_code == 200
    assert [m.rol for m in guion.recibidos[0]] == ["system", "user"]


def test_un_aprobador_puede_preguntar_pero_no_proponer(
    app: FastAPI, cliente: TestClient, sesion: Session, entrar_como: Entrar
) -> None:
    aprobador = crear_usuario(sesion, rol="aprobador")
    factura_con(sesion, "600.00", VENCIDA)
    entrar_como(aprobador.id)
    guion = instalar_guion(
        app,
        [
            PasoGuion(llamadas=[("proponer_pagos", {"presupuesto_mxn": "1000.00", "horizonte": "vencidas"})]),
            PasoGuion(texto="No puedo crear la propuesta con tu rol."),
        ],
    )
    mensaje = cliente.post(RUTA, json={"texto": "Propón pagos vencidos con 1,000 pesos"}).json()
    assert "proponer_pagos" not in guion.herramientas_ofrecidas[0]
    assert len(guion.herramientas_ofrecidas[0]) == 8
    assert "solo para el rol capturista" in mensaje["herramientas"][0]["error"]
    assert mensaje["propuesta_id"] is None
    assert sesion.scalar(select(func.count()).select_from(Propuesta)) == 0


def test_el_texto_de_terceros_llega_al_modelo_solo_como_dato_limpio_y_recortado(
    app: FastAPI, cliente: TestClient, sesion: Session, entrar_como: Entrar
) -> None:
    proveedor = crear_proveedor(sesion, nombre="Proveedor\x1b con\u202e   controles\n\nSA de CV")
    sucio = "Servicio de\x07 mantenimiento\u200b preventivo. " + "relleno " * 400
    factura = factura_con(sesion, "1160.00", VENCIDA, proveedor=proveedor, concepto=sucio)
    entrar_como(crear_usuario(sesion).id)
    guion = instalar_guion(
        app, [PasoGuion(llamadas=[("detalle_factura", {"uuid": factura.uuid.lower()})]), PasoGuion(texto="Listo.")]
    )
    assert cliente.post(RUTA, json={"texto": "Detalle de la factura"}).status_code == 200
    detalle = ultimo_resultado(guion.recibidos[1])
    concepto = elementos(detalle, "conceptos")[0]
    descripcion = str(concepto["descripcion_no_confiable"])
    assert set(concepto) == {"descripcion_no_confiable", "importe"}
    assert descripcion.startswith("Servicio de mantenimiento preventivo. relleno")
    assert len(descripcion) == 1500 and descripcion.endswith("…")
    nombre = como_dict(como_dict(detalle["factura"])["proveedor"])["nombre_no_confiable"]
    assert nombre == "Proveedor con controles SA de CV"
    crudo = guion.recibidos[1][-1].contenido or ""
    assert "\\u001b" not in crudo and "\\u202e" not in crudo and "\\u0007" not in crudo
    assert como_dict(detalle["factura"])["saldo"] == "1160.00"


def test_muchas_excluidas_llegan_al_modelo_resumidas_por_motivo(
    app: FastAPI, cliente: TestClient, sesion: Session, entrar_como: Entrar
) -> None:
    caras = [factura_con(sesion, "900.00", VENCIDA) for _ in range(13)]
    bloqueada = factura_con(sesion, "50.00", VENCIDA)
    bloquear(sesion, "POSIBLE_DUPLICADO", factura=bloqueada)
    entrar_como(crear_usuario(sesion, rol="capturista").id)
    guion = instalar_guion(
        app,
        [
            PasoGuion(llamadas=[("proponer_pagos", {"presupuesto_mxn": "100.00", "horizonte": "vencidas"})]),
            PasoGuion(texto="Con ese presupuesto no cabe ninguna factura."),
        ],
    )
    mensaje = cliente.post(RUTA, json={"texto": "Propón pagar lo vencido con presupuesto de 100 pesos"}).json()
    devuelto = ultimo_resultado(guion.recibidos[1])
    assert devuelto["codigo"] == "PROPUESTA_VACIA"
    assert devuelto["excluidas_por_codigo"] == {"EXCEDE_PRESUPUESTO": len(caras), "ALERTA_BLOQUEANTE": 1}
    detalladas = elementos(devuelto, "excluidas")
    assert len(detalladas) == 10 and devuelto["excluidas_omitidas"] == 4
    assert detalladas[0]["factura_id"] == bloqueada.id, "primero las que no son por presupuesto"
    assert mensaje["propuesta_id"] is None and sesion.scalar(select(func.count()).select_from(Propuesta)) == 0
