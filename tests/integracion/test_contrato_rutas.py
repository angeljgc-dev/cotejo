"""Contrato de las rutas de cuentas por pagar: forma de cada respuesta, errores y permisos por rol."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

import httpx2
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from cotejo.config import Settings
from cotejo.cxp import alertas
from cotejo.modelos import Alerta, Usuario
from tests.apoyo.cfdi import FIXTURES, factura_de, ingerir, ingreso, nota
from tests.apoyo.fabricas import crear_proveedor, crear_usuario
from tests.apoyo.http import entrar

LECTURAS = [
    "/api/facturas",
    "/api/facturas/1",
    "/api/facturas/1/xml",
    "/api/proveedores",
    "/api/proveedores/1",
    "/api/alertas",
    "/api/tablero",
    "/api/lista-69b/estado",
    "/api/bitacora",
]
XML_BUENO = (FIXTURES / "validos" / "ingreso_mxn.xml").read_bytes()
ALERTA_KEYS = {
    "id",
    "factura_id",
    "proveedor_id",
    "codigo",
    "severidad",
    "mensaje",
    "detalle",
    "factura_relacionada_id",
    "estado",
    "creada_en",
    "resuelta_por",
    "resuelta_en",
    "nota_resolucion",
}
RESUMEN_KEYS = {
    "id",
    "uuid",
    "tipo",
    "serie",
    "folio",
    "fecha_emision",
    "proveedor",
    "moneda",
    "tipo_cambio",
    "total",
    "total_mxn",
    "saldo",
    "saldo_mxn",
    "vencimiento",
    "dias_vencido",
    "estado_pago",
    "resultado",
    "alertas_abiertas",
    "tiene_bloqueante",
    "en_propuesta_pendiente",
}
PAGINA_KEYS = {"elementos", "total", "pagina", "por_pagina"}


def _error(r: httpx2.Response, estado: int, codigo: str) -> dict[str, object]:
    assert r.status_code == estado, r.text
    cuerpo = r.json()
    assert set(cuerpo["error"]) == {"codigo", "mensaje", "detalle"}
    assert cuerpo["error"]["codigo"] == codigo and isinstance(cuerpo["error"]["detalle"], dict)
    assert cuerpo["error"]["mensaje"]
    error: dict[str, object] = cuerpo["error"]
    return error


@pytest.fixture
def capturista(sesion: Session) -> Usuario:
    return crear_usuario(sesion, rol="capturista")


@pytest.fixture
def aprobador(sesion: Session) -> Usuario:
    return crear_usuario(sesion, rol="aprobador")


def _subir(cliente: TestClient, *archivos: tuple[str, bytes]) -> httpx2.Response:
    return cliente.post("/api/cargas/cfdi", files=[("archivos", (n, d, "application/xml")) for n, d in archivos])


def test_las_rutas_del_contrato_estan_en_openapi(app: FastAPI) -> None:
    rutas = {(metodo.upper(), ruta) for ruta, metodos in app.openapi()["paths"].items() for metodo in metodos}
    assert {
        ("POST", "/api/cargas/cfdi"),
        ("GET", "/api/facturas"),
        ("GET", "/api/facturas/{factura_id}"),
        ("GET", "/api/facturas/{factura_id}/xml"),
        ("GET", "/api/alertas"),
        ("POST", "/api/alertas/{alerta_id}/resolver"),
        ("GET", "/api/proveedores"),
        ("GET", "/api/proveedores/{proveedor_id}"),
        ("PATCH", "/api/proveedores/{proveedor_id}"),
        ("GET", "/api/tablero"),
        ("POST", "/api/lista-69b"),
        ("GET", "/api/lista-69b/estado"),
        ("GET", "/api/bitacora"),
        ("POST", "/api/demo/reiniciar"),
    } <= rutas


@pytest.mark.parametrize("ruta", LECTURAS)
def test_lecturas_exigen_sesion(cliente: TestClient, ruta: str) -> None:
    _error(cliente.get(ruta), 401, "NO_AUTENTICADO")


@pytest.mark.parametrize(
    ("metodo", "ruta", "datos"),
    [
        ("post", "/api/cargas/cfdi", None),
        ("post", "/api/lista-69b", None),
        ("post", "/api/alertas/1/resolver", {"nota": "Revisado con el proveedor"}),
        ("patch", "/api/proveedores/1", {"dias_credito": 10}),
        ("post", "/api/demo/reiniciar", {}),
    ],
)
def test_escrituras_exigen_sesion_y_cabecera_csrf(
    cliente: TestClient, app: FastAPI, metodo: str, ruta: str, datos: dict[str, object] | None
) -> None:
    _error(cliente.request(metodo, ruta, json=datos), 401, "NO_AUTENTICADO")
    with TestClient(app) as sin_cabecera:
        _error(sin_cabecera.request(metodo, ruta, json=datos), 403, "CSRF_FALTANTE")


def test_roles_cargar_cfdi_solo_capturista_y_lista_y_alertas_solo_aprobador(
    cliente: TestClient, entrar_como: Callable[[int], None], capturista: Usuario, aprobador: Usuario
) -> None:
    entrar_como(aprobador.id)
    _error(_subir(cliente, ("a.xml", XML_BUENO)), 403, "ROL_INSUFICIENTE")
    entrar_como(capturista.id)
    _error(cliente.post("/api/lista-69b", files={"archivo": ("l.csv", b"RFC\n", "text/csv")}), 403, "ROL_INSUFICIENTE")
    _error(cliente.post("/api/alertas/1/resolver", json={"nota": "Revisado"}), 403, "ROL_INSUFICIENTE")


def test_cargas_errores_del_contrato(
    config: Settings,
    fabrica_app: Callable[[Settings], FastAPI],
    cliente: TestClient,
    entrar_como: Callable[[int], None],
    capturista: Usuario,
) -> None:
    entrar_como(capturista.id)
    _error(cliente.post("/api/cargas/cfdi", files={"otro": ("a.xml", b"x")}), 422, "SIN_ARCHIVOS")
    demasiados = _subir(cliente, *[(f"{i}.xml", b"<a/>") for i in range(51)])
    assert _error(demasiados, 422, "DEMASIADOS_ARCHIVOS")["detalle"] == {"maximo": 50, "recibidos": 51}
    grande = cliente.post(
        "/api/cargas/cfdi",
        content=b"x" * (26 * 1024 * 1024),
        headers={"Content-Type": "multipart/form-data; boundary=x"},
    )
    _error(grande, 413, "CARGA_DEMASIADO_GRANDE")

    # Extensión y tamaño se rechazan por archivo; el resto del lote sigue.
    r = _subir(
        cliente, ("factura.pdf", b"%PDF-1.4"), ("enorme.xml", b"x" * (2 * 1024 * 1024 + 1)), ("ok.xml", XML_BUENO)
    )
    assert r.status_code == 200
    archivos = r.json()["archivos"]
    assert [a["motivos"][0]["codigo"] for a in archivos[:2]] == ["EXTENSION_NO_PERMITIDA", "ARCHIVO_DEMASIADO_GRANDE"]
    assert archivos[2]["resultado"] in ("aceptada", "aceptada_con_alertas")
    assert set(r.json()) == {"carga_id", "archivos", "resumen"}
    assert set(archivos[2]) == {"nombre", "resultado", "motivos", "uuid", "factura_id", "tipo", "ya_existia"}

    config.cargas_limite_visitante_dia = 2
    with TestClient(fabrica_app(config), headers={"X-Cotejo": "1"}) as limitado:
        entrar(limitado, config, capturista.id, visitante="visitante-con-limite")
        assert _subir(limitado, ("a.xml", b"<a/>"), ("b.xml", b"<a/>")).status_code == 200
        detalle = _error(_subir(limitado, ("c.xml", b"<a/>")), 429, "LIMITE_CARGAS")["detalle"]
        assert isinstance(detalle, dict) and set(detalle) == {"limite", "se_reinicia"}


def test_facturas_lista_detalle_y_xml(
    cliente: TestClient, sesion: Session, entrar_como: Callable[[int], None], capturista: Usuario
) -> None:
    factura = ingreso(Decimal("2320.00"))
    la_nota = nota(Decimal("100.00"), factura.uuid)
    ingerir(sesion, factura, la_nota, usuario=capturista)
    entrar_como(capturista.id)
    f = factura_de(sesion, factura)

    pagina = cliente.get("/api/facturas", params={"estado": "pendiente", "orden": "saldo", "por_pagina": 10}).json()
    assert set(pagina) >= PAGINA_KEYS and pagina["total"] == 1
    (resumen,) = pagina["elementos"]
    assert set(resumen) == RESUMEN_KEYS
    assert (resumen["saldo"], resumen["estado_pago"], resumen["total"]) == ("2204.00", "parcial", "2320.00")
    assert cliente.get("/api/facturas", params={"tipo": "E"}).json()["elementos"][0]["saldo"] is None
    _error(cliente.get("/api/facturas", params={"por_pagina": 101}), 422, "VALIDACION")
    _error(cliente.get("/api/facturas", params={"estado": "otra"}), 422, "VALIDACION")

    detalle = cliente.get(f"/api/facturas/{f.id}").json()
    assert set(detalle) >= RESUMEN_KEYS
    assert {"conceptos", "impuestos", "relacionados", "aplicaciones", "alertas", "carga", "receptor"} <= set(detalle)
    (concepto,) = detalle["conceptos"]
    assert (concepto["cantidad"], concepto["importe"], concepto["valor_unitario"]) == ("1", "2000.00", "2000.00")
    (impuesto,) = detalle["impuestos"]
    assert (impuesto["tasa_o_cuota"], impuesto["importe"]) == ("0.16", "320.00")
    (aplicacion,) = detalle["aplicaciones"]
    assert (aplicacion["origen"], aplicacion["importe"]) == ("nota_credito", "116.00")
    assert detalle["carga"]["usuario"] == {"id": capturista.id, "nombre": capturista.nombre, "rol": "capturista"}
    detalle_nota = cliente.get(f"/api/facturas/{factura_de(sesion, la_nota).id}").json()
    assert detalle_nota["relacionados"] == [{"uuid": factura.uuid, "tipo_relacion": "01", "factura_id": f.id}]
    _error(cliente.get("/api/facturas/999999"), 404, "FACTURA_NO_ENCONTRADA")

    xml = cliente.get(f"/api/facturas/{f.id}/xml")
    assert xml.status_code == 200 and xml.headers["content-type"].startswith("application/xml")
    assert xml.headers["content-disposition"] == f'attachment; filename="{factura.uuid}.xml"'
    assert factura.uuid.encode() in xml.content
    _error(cliente.get("/api/facturas/999999/xml"), 404, "FACTURA_NO_ENCONTRADA")


def test_alertas_lista_y_resolucion(
    cliente: TestClient, sesion: Session, entrar_como: Callable[[int], None], aprobador: Usuario
) -> None:
    factura = ingreso(Decimal("1160.00"))
    ingerir(sesion, factura)
    f = factura_de(sesion, factura)
    alertas.abrir(sesion, codigo="POSIBLE_DUPLICADO", severidad="bloqueante", mensaje="Duplicado", factura_id=f.id)
    sesion.commit()
    alerta = sesion.scalars(select(Alerta).where(Alerta.factura_id == f.id)).one()
    entrar_como(aprobador.id)

    pagina = cliente.get("/api/alertas", params={"estado": "abierta", "severidad": "bloqueante"}).json()
    assert set(pagina) >= PAGINA_KEYS and [a["id"] for a in pagina["elementos"]] == [alerta.id]
    assert set(pagina["elementos"][0]) == ALERTA_KEYS

    _error(cliente.post(f"/api/alertas/{alerta.id}/resolver", json={"nota": "    ok   "}), 422, "VALIDACION")
    _error(cliente.post(f"/api/alertas/{alerta.id}/resolver", json={"nota": "x" * 501}), 422, "VALIDACION")
    r = cliente.post(f"/api/alertas/{alerta.id}/resolver", json={"nota": "No es duplicado: son dos pedidos"})
    assert r.status_code == 200, r.text
    resuelta = r.json()
    assert resuelta["estado"] == "resuelta" and resuelta["nota_resolucion"] == "No es duplicado: son dos pedidos"
    assert resuelta["resuelta_por"] == {"id": aprobador.id, "nombre": aprobador.nombre, "rol": "aprobador"}
    _error(cliente.post(f"/api/alertas/{alerta.id}/resolver", json={"nota": "Otra vez"}), 409, "ALERTA_YA_RESUELTA")
    _error(cliente.post("/api/alertas/999999/resolver", json={"nota": "No existe"}), 404, "ALERTA_NO_ENCONTRADA")
    # Resolver no toca la factura: solo deja de bloquearla.
    assert cliente.get(f"/api/facturas/{f.id}").json()["total"] == "1160.00"
    assert cliente.get(f"/api/facturas/{f.id}").json()["tiene_bloqueante"] is False

    bitacora = cliente.get("/api/bitacora", params={"accion": "ALERTA_RESUELTA", "entidad": "alerta"}).json()
    (renglon,) = bitacora["elementos"]
    assert renglon["entidad_id"] == str(alerta.id) and renglon["usuario"]["id"] == aprobador.id
    assert set(renglon) == {"id", "ocurrido_en", "usuario", "accion", "entidad", "entidad_id", "detalle"}


def test_proveedores_lista_detalle_y_edicion(
    cliente: TestClient, sesion: Session, entrar_como: Callable[[int], None], capturista: Usuario
) -> None:
    ingerir(sesion, ingreso(Decimal("1160.00")), ingreso(Decimal("100.00"), moneda="USD", tipo_cambio=Decimal(18)))
    sin_facturas = crear_proveedor(sesion, nombre="Sin Facturas Ficticio SA")
    entrar_como(capturista.id)

    pagina = cliente.get("/api/proveedores", params={"texto": "ficticio"}).json()
    assert set(pagina) >= PAGINA_KEYS and pagina["total"] >= 2
    esperado = {
        "id",
        "rfc",
        "nombre",
        "dias_credito",
        "rfc_valido",
        "situacion_69b",
        "adeudo_mxn",
        "facturas_con_saldo",
    }
    assert all(set(p) == esperado for p in pagina["elementos"])
    con_adeudo = next(p for p in pagina["elementos"] if p["facturas_con_saldo"] == 2)
    assert con_adeudo["adeudo_mxn"] == "2960.00"

    detalle = cliente.get(f"/api/proveedores/{con_adeudo['id']}").json()
    assert detalle["adeudo_por_moneda"] == [
        {"moneda": "MXN", "saldo": "1160.00", "saldo_mxn": "1160.00"},
        {"moneda": "USD", "saldo": "100.00", "saldo_mxn": "1800.00"},
    ]
    assert detalle["documentos"] == []
    _error(cliente.get("/api/proveedores/999999"), 404, "PROVEEDOR_NO_ENCONTRADO")

    r = cliente.patch(f"/api/proveedores/{sin_facturas.id}", json={"dias_credito": 60})
    assert r.status_code == 200 and set(r.json()) == esperado and r.json()["dias_credito"] == 60
    _error(cliente.patch("/api/proveedores/999999", json={"dias_credito": 60}), 404, "PROVEEDOR_NO_ENCONTRADO")
    bitacora = cliente.get(
        "/api/bitacora", params={"accion": "PROVEEDOR_EDITADO", "entidad_id": str(sin_facturas.id)}
    ).json()
    (renglon,) = bitacora["elementos"]
    assert renglon["detalle"] == {"campo": "dias_credito", "anterior": 30, "nuevo": 60}


def test_bitacora_filtros_y_carga_registrada(
    cliente: TestClient, sesion: Session, entrar_como: Callable[[int], None], capturista: Usuario
) -> None:
    entrar_como(capturista.id)
    carga = _subir(cliente, ("a.xml", XML_BUENO)).json()
    pagina = cliente.get("/api/bitacora", params={"accion": "CARGA_CFDI", "usuario_id": capturista.id}).json()
    (renglon,) = pagina["elementos"]
    assert renglon["entidad"] == "carga" and renglon["entidad_id"] == str(carga["carga_id"])
    assert renglon["detalle"]["archivos"] == 1
    assert cliente.get("/api/bitacora", params={"desde": "2000-01-01", "hasta": "2000-01-02"}).json()["total"] == 0
    _error(cliente.get("/api/bitacora", params={"desde": "no-es-fecha"}), 422, "VALIDACION")


ENORME = "99999999999999999999"


@pytest.mark.parametrize(
    "ruta",
    [
        f"/api/facturas?pagina={ENORME}",
        f"/api/facturas?proveedor_id={ENORME}",
        f"/api/alertas?pagina={ENORME}",
        f"/api/alertas?factura_id={ENORME}",
        f"/api/bitacora?pagina={ENORME}",
        f"/api/bitacora?usuario_id={ENORME}",
        f"/api/proveedores?pagina={ENORME}",
        f"/api/facturas/{ENORME}",
        f"/api/facturas/{ENORME}/xml",
        f"/api/proveedores/{ENORME}",
        "/api/facturas/0",
    ],
)
def test_identificadores_y_paginas_fuera_de_rango_son_422(
    cliente: TestClient, entrar_como: Callable[[int], None], capturista: Usuario, ruta: str
) -> None:
    entrar_como(capturista.id)
    _error(cliente.get(ruta), 422, "VALIDACION")


def test_escrituras_con_identificador_fuera_de_rango_son_422(
    cliente: TestClient, entrar_como: Callable[[int], None], aprobador: Usuario
) -> None:
    entrar_como(aprobador.id)
    _error(cliente.post(f"/api/alertas/{ENORME}/resolver", json={"nota": "Revisado"}), 422, "VALIDACION")
    _error(cliente.patch(f"/api/proveedores/{ENORME}", json={"dias_credito": 5}), 422, "VALIDACION")
