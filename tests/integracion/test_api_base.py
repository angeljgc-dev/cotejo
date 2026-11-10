"""Contrato de la sección 4 para sesión y salud, formato de error, roles, CSRF y cabeceras (sección 8)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Annotated

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from cotejo.api import app as modulo_app
from cotejo.api.app import crear_app
from cotejo.api.dependencias import SesionDb, VisitanteActual, requiere_rol
from cotejo.config import Settings
from cotejo.db import obtener_sesion
from cotejo.modelos import Bitacora, CuotaUso, Usuario
from cotejo.seguridad.sesion import NOMBRE_COOKIE
from tests.apoyo.fabricas import crear_usuario
from tests.apoyo.http import token_de

FabricaApp = Callable[[Settings], FastAPI]


def _error(respuesta_json: object) -> dict[str, object]:
    assert isinstance(respuesta_json, dict)
    error = respuesta_json["error"]
    assert isinstance(error, dict)
    assert set(error) == {"codigo", "mensaje", "detalle"}
    return error


def test_salud_ok(cliente: TestClient) -> None:
    r = cliente.get("/api/salud")
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["estado"] == "ok" and cuerpo["base"] == "ok"
    assert cuerpo["modo_demo"] is True
    assert cuerpo["asistente_configurado"] is False
    assert cuerpo["version"] == "0.1.0"


def test_salud_503_si_la_base_no_responde(config: Settings) -> None:
    aplicacion = crear_app(config)
    motor_muerto = create_engine(
        "postgresql+psycopg://nadie@127.0.0.1:9/no_existe_test", connect_args={"connect_timeout": 2}
    )

    def _sesion_rota() -> Iterator[Session]:
        with Session(motor_muerto) as s:
            yield s

    aplicacion.dependency_overrides[obtener_sesion] = _sesion_rota
    with TestClient(aplicacion) as c:
        r = c.get("/api/salud")
    motor_muerto.dispose()
    assert r.status_code == 503
    error = _error(r.json())
    assert error["codigo"] == "BASE_NO_DISPONIBLE"
    assert error["detalle"] == {
        "estado": "error",
        "base": "error",
        "version": "0.1.0",
        "modo_demo": True,
        "asistente_configurado": False,
    }


def test_ruta_inexistente_usa_formato_de_error(cliente: TestClient) -> None:
    r = cliente.get("/api/no-existe")
    assert r.status_code == 404
    assert _error(r.json())["codigo"] == "RUTA_NO_ENCONTRADA"


def test_validacion_422_con_campos(cliente: TestClient) -> None:
    r = cliente.post("/api/sesion/demo", json={"rol": "director"})
    assert r.status_code == 422
    error = _error(r.json())
    assert error["codigo"] == "VALIDACION"
    assert error["detalle"] == {"campos": [{"campo": "rol", "mensaje": "Valor no permitido."}]}


def test_error_no_controlado_es_500_sin_detalles_internos(app: FastAPI) -> None:
    router = APIRouter()

    @router.get("/prueba/explota")
    def explota() -> None:
        raise RuntimeError("detalle interno que no debe salir")

    app.include_router(router, prefix="/api")
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/api/prueba/explota")
    assert r.status_code == 500
    assert _error(r.json())["codigo"] == "ERROR_INTERNO"
    assert "detalle interno" not in r.text
    # Los 500 también llevan las cabeceras de seguridad.
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["cache-control"] == "no-store"


def test_csrf_faltante(app: FastAPI) -> None:
    with TestClient(app) as sin_cabecera:
        r = sin_cabecera.post("/api/sesion/demo", json={"rol": "capturista"})
        assert r.status_code == 403
        assert _error(r.json())["codigo"] == "CSRF_FALTANTE"
        r = sin_cabecera.post("/api/sesion/demo", json={"rol": "capturista"}, headers={"X-Cotejo": "0"})
        assert r.status_code == 403
        assert sin_cabecera.get("/api/salud").status_code == 200  # GET no la exige


def test_cabeceras_de_seguridad(cliente: TestClient) -> None:
    r = cliente.get("/api/salud")
    csp = r.headers["content-security-policy"]
    assert "default-src 'self'" in csp and "frame-ancestors 'none'" in csp and "script-src 'self'" in csp
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "same-origin"
    assert r.headers["permissions-policy"] == "camera=(), microphone=(), geolocation=()"
    assert r.headers["cache-control"] == "no-store"
    assert "strict-transport-security" not in r.headers
    rechazo = cliente.post("/api/sesion/demo", json={}, headers={"X-Cotejo": ""})
    assert rechazo.headers["x-content-type-options"] == "nosniff"


def test_hsts_y_cookie_segura_con_https(config: Settings, fabrica_app: FabricaApp) -> None:
    config.cookie_segura = True
    aplicacion = fabrica_app(config)
    with TestClient(aplicacion, headers={"X-Cotejo": "1"}) as c:
        r = c.post("/api/sesion/demo", json={"rol": "capturista"})
    assert r.headers["strict-transport-security"] == "max-age=31536000"
    assert "Secure" in r.headers["set-cookie"]


def test_peticion_demasiado_grande(cliente: TestClient) -> None:
    r = cliente.post("/api/sesion/demo", content=b"x", headers={"Content-Length": str(26 * 1024 * 1024)})
    assert r.status_code == 413
    assert _error(r.json())["codigo"] == "CARGA_DEMASIADO_GRANDE"


def test_cuerpo_por_bloques_demasiado_grande(cliente: TestClient) -> None:
    def bloques() -> Iterator[bytes]:
        for _ in range(30):
            yield b"x" * (1024 * 1024)

    r = cliente.post("/api/sesion/demo", content=bloques())
    assert r.status_code == 413
    assert _error(r.json())["codigo"] == "CARGA_DEMASIADO_GRANDE"


def test_cuerpo_por_bloques_pequeno_llega_completo(cliente: TestClient) -> None:
    def bloques() -> Iterator[bytes]:
        yield b'{"rol": '
        yield b'"capturista"}'

    r = cliente.post("/api/sesion/demo", content=bloques(), headers={"Content-Type": "application/json"})
    assert r.status_code == 200
    assert r.json()["rol"] == "capturista"


def test_entrar_demo_crea_cookie_y_bitacora(cliente: TestClient, sesion: Session) -> None:
    r = cliente.post("/api/sesion/demo", json={"rol": "aprobador"})
    assert r.status_code == 200
    cuerpo = r.json()
    assert set(cuerpo) == {"id", "usuario", "nombre", "rol", "es_demo"}
    assert cuerpo["usuario"] == "demo.aprobador" and cuerpo["rol"] == "aprobador" and cuerpo["es_demo"] is True
    cookie = r.headers["set-cookie"]
    assert cookie.startswith(f"{NOMBRE_COOKIE}=") and "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert "Max-Age=28800" in cookie and "Secure" not in cookie
    assert cliente.get("/api/sesion").json() == cuerpo
    # La segunda entrada reutiliza el mismo usuario de demo.
    assert cliente.post("/api/sesion/demo", json={"rol": "aprobador"}).json()["id"] == cuerpo["id"]
    eventos = sesion.scalars(select(Bitacora).where(Bitacora.accion == "SESION_INICIADA")).all()
    assert [(e.usuario_id, e.entidad, e.detalle) for e in eventos] == [(cuerpo["id"], "usuario", {"via": "demo"})] * 2


def test_demo_deshabilitada(config: Settings, fabrica_app: FabricaApp) -> None:
    config.demo_habilitada = False
    aplicacion = fabrica_app(config)
    with TestClient(aplicacion, headers={"X-Cotejo": "1"}) as c:
        r = c.post("/api/sesion/demo", json={"rol": "capturista"})
    assert r.status_code == 404
    assert _error(r.json())["codigo"] == "DEMO_DESHABILITADA"


def test_sin_sesion_o_cookie_alterada_es_401(cliente: TestClient, sesion: Session, config: Settings) -> None:
    assert _error(cliente.get("/api/sesion").json())["codigo"] == "NO_AUTENTICADO"
    usuario = crear_usuario(sesion)
    token = token_de(config, usuario.id)
    cliente.cookies.set(NOMBRE_COOKIE, token[:-3] + "AAA")
    assert cliente.get("/api/sesion").status_code == 401
    cliente.cookies.set(NOMBRE_COOKIE, token_de(Settings(secret_key="otra-clave" * 5), usuario.id))
    assert cliente.get("/api/sesion").status_code == 401
    r = cliente.get("/api/sesion", headers={b"Cookie": f"{NOMBRE_COOKIE}=abc.".encode() + "é".encode()})
    assert r.status_code == 401
    cliente.cookies.set(NOMBRE_COOKIE, token)
    assert cliente.get("/api/sesion").status_code == 200


def test_usuario_inactivo_pierde_la_sesion(
    cliente: TestClient, sesion: Session, entrar_como: Callable[[int], None]
) -> None:
    usuario = crear_usuario(sesion)
    entrar_como(usuario.id)
    assert cliente.get("/api/sesion").status_code == 200
    usuario.activo = False
    sesion.commit()
    assert cliente.get("/api/sesion").status_code == 401


def test_entrar_con_contrasena(cliente: TestClient, sesion: Session) -> None:
    crear_usuario(sesion, usuario="ana.ficticia", rol="aprobador", contrasena="clave-larga-de-prueba")
    r = cliente.post("/api/sesion", json={"usuario": "ana.ficticia", "contrasena": "clave-larga-de-prueba"})
    assert r.status_code == 200
    assert r.json()["rol"] == "aprobador" and r.json()["es_demo"] is False
    malo = cliente.post("/api/sesion", json={"usuario": "ana.ficticia", "contrasena": "otra"})
    assert malo.status_code == 401
    assert _error(malo.json())["codigo"] == "CREDENCIALES_INVALIDAS"
    inexistente = cliente.post("/api/sesion", json={"usuario": "nadie", "contrasena": "x"})
    assert _error(inexistente.json())["codigo"] == "CREDENCIALES_INVALIDAS"


def test_usuario_demo_no_entra_con_contrasena(cliente: TestClient) -> None:
    cliente.post("/api/sesion/demo", json={"rol": "capturista"})
    r = cliente.post("/api/sesion", json={"usuario": "demo.capturista", "contrasena": "cualquiera"})
    assert r.status_code == 401


def test_limite_de_intentos_por_minuto(cliente: TestClient, sesion: Session) -> None:
    for _ in range(5):
        assert cliente.post("/api/sesion", json={"usuario": "nadie", "contrasena": "x"}).status_code == 401
    r = cliente.post("/api/sesion", json={"usuario": "nadie", "contrasena": "x"})
    assert r.status_code == 429
    error = _error(r.json())
    assert error["codigo"] == "LIMITE_INTENTOS" and error["detalle"] == {"limite": 5}
    # Los intentos fallidos sí quedaron contados aunque la petición respondió con error.
    assert sesion.scalars(select(CuotaUso.contador).where(CuotaUso.clave.like("login:ip:%"))).one() == 5


def test_salir_borra_la_cookie(cliente: TestClient) -> None:
    cliente.post("/api/sesion/demo", json={"rol": "capturista"})
    r = cliente.delete("/api/sesion")
    assert r.status_code == 204
    assert f'{NOMBRE_COOKIE}=""' in r.headers["set-cookie"] or "Max-Age=0" in r.headers["set-cookie"]
    assert cliente.get("/api/sesion").status_code == 401


def test_configuracion(cliente: TestClient) -> None:
    assert cliente.get("/api/configuracion").status_code == 401
    cliente.post("/api/sesion/demo", json={"rol": "capturista"})
    assert cliente.get("/api/configuracion").json() == {
        "empresa_rfc": "EKU9003173C9",
        "empresa_nombre": "Comercializadora Ficticia del Centro",
        "modo_demo": True,
        "aviso_demo": "Demostración con datos ficticios: empresas, RFC e importes son inventados.",
        "hoy": "2026-11-02",
        "zona_horaria": "America/Mexico_City",
        "limites": {"chat_por_dia": 20, "archivos_por_carga": 50, "mb_por_xml": 2, "mb_por_documento": 10},
    }


@pytest.fixture
def app_con_ruta_de_aprobador(app: FastAPI) -> FastAPI:
    router = APIRouter()

    @router.post("/prueba/aprobar")
    def aprobar(usuario: Annotated[Usuario, Depends(requiere_rol("aprobador"))], sesion: SesionDb) -> dict[str, object]:
        sesion.add(Usuario(usuario=f"creado.por.{usuario.id}", nombre="Efecto", rol="capturista"))
        return {"usuario_id": usuario.id}

    app.include_router(router, prefix="/api")
    return app


def test_requiere_rol(app_con_ruta_de_aprobador: FastAPI, sesion: Session, config: Settings) -> None:
    capturista = crear_usuario(sesion, rol="capturista")
    aprobador = crear_usuario(sesion, rol="aprobador")
    with TestClient(app_con_ruta_de_aprobador, headers={"X-Cotejo": "1"}) as c:
        assert c.post("/api/prueba/aprobar").status_code == 401
        c.cookies.set(NOMBRE_COOKIE, token_de(config, capturista.id))
        r = c.post("/api/prueba/aprobar")
        assert r.status_code == 403
        assert _error(r.json()) == {
            "codigo": "ROL_INSUFICIENTE",
            "mensaje": "Esta acción es solo para el rol aprobador.",
            "detalle": {},
        }
        c.cookies.set(NOMBRE_COOKIE, token_de(config, aprobador.id))
        assert c.post("/api/prueba/aprobar").json() == {"usuario_id": aprobador.id}
    # La sesión de base de la ruta hizo commit: el efecto quedó guardado.
    assert sesion.scalar(select(Usuario).where(Usuario.usuario == f"creado.por.{aprobador.id}")) is not None


def test_visitante_y_hash_de_ip(app: FastAPI, config: Settings) -> None:
    router = APIRouter()

    @router.get("/prueba/visitante")
    def ver(visitante: VisitanteActual) -> dict[str, str]:
        return {"visitante": visitante.visitante, "ip_hash": visitante.ip_hash}

    app.include_router(router, prefix="/api")
    with TestClient(app) as c:
        anonimo = c.get("/api/prueba/visitante", headers={"X-Forwarded-For": "203.0.113.9"}).json()
        c.cookies.set(NOMBRE_COOKIE, token_de(config, 1, visitante="v-123"))
        con_sesion = c.get("/api/prueba/visitante").json()
    assert len(anonimo["ip_hash"]) == 64 and "203.0.113.9" not in anonimo["ip_hash"]
    assert anonimo["visitante"].startswith("ip:")
    assert con_sesion == {"visitante": "v-123", "ip_hash": anonimo["ip_hash"]}  # sin CONFIAR_PROXY se ignora XFF
    config.confiar_proxy = True
    with TestClient(app) as c:
        uno = c.get("/api/prueba/visitante", headers={"X-Forwarded-For": "203.0.113.9, 198.51.100.7"}).json()
        # El cliente puede inventar las primeras IP; solo cuenta la que agregó el proxy (la última).
        otro = c.get("/api/prueba/visitante", headers={"X-Forwarded-For": "6.6.6.6, 198.51.100.7"}).json()
        directa = c.get("/api/prueba/visitante", headers={"X-Forwarded-For": "198.51.100.7"}).json()
    assert uno["ip_hash"] == otro["ip_hash"] == directa["ip_hash"]
    assert uno["ip_hash"] != anonimo["ip_hash"]


def test_todos_los_routers_estan_montados() -> None:
    nombres = {r.tags[0] for r in modulo_app.ROUTERS if r.tags}
    assert {"documentos", "busqueda", "asistente", "propuestas", "sesion", "salud"} <= {str(n) for n in nombres}


def test_sirve_el_frontend_construido(config: Settings, fabrica_app: FabricaApp, tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<!doctype html><title>Cotejo</title>", encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path.parent / "secreto.txt").write_text("no", encoding="utf-8")
    config.static_dir = str(tmp_path)
    aplicacion = fabrica_app(config)
    with TestClient(aplicacion) as c:
        assert "<title>Cotejo</title>" in c.get("/").text
        assert "<title>Cotejo</title>" in c.get("/facturas/12").text  # ruta del cliente
        assert c.get("/assets/app.js").text == "console.log(1)"
        assert c.get("/..%2Fsecreto.txt").text != "no"
        assert c.get("/api/inexistente").status_code == 404
        assert c.get("/api/salud").status_code == 200
        assert "frame-ancestors" in c.get("/").headers["content-security-policy"]


def test_el_commit_ocurre_antes_de_responder(app: FastAPI) -> None:
    """Si el commit falla, el cliente recibe el error y no un 200 falso (SesionDb usa scope="function")."""
    router = APIRouter()

    @router.post("/prueba/commit-roto")
    def commit_roto(sesion: SesionDb) -> dict[str, str]:
        # El CHECK de rol solo salta al hacer flush, que ocurre en el commit de la dependencia.
        sesion.add(Usuario(usuario="rol.invalido", nombre="X", rol="director"))
        return {"estado": "aparentemente bien"}

    app.include_router(router, prefix="/api")
    with TestClient(app, headers={"X-Cotejo": "1"}, raise_server_exceptions=False) as c:
        r = c.post("/api/prueba/commit-roto")
    assert r.status_code == 500
    assert _error(r.json())["codigo"] == "ERROR_INTERNO"
