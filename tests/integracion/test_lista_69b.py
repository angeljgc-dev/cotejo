"""A8: proveedor en la lista 69-B. Una alerta bloqueante por proveedor que bloquea todas sus facturas."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from cotejo import lista_69b
from cotejo.cxp import consultas, saldos
from cotejo.modelos import Alerta
from tests.apoyo.cfdi import RFC_A, RFC_B, factura_de, ingerir, ingreso
from tests.apoyo.fabricas import crear_usuario

AHORA = datetime(2026, 11, 2, 18, 0, tzinfo=UTC)
ENCABEZADO = "No,RFC,Nombre del Contribuyente,Situación del contribuyente\n"


def _csv(*renglones: tuple[str, str]) -> bytes:
    return (ENCABEZADO + "".join(f"{i},{r},Ficticio,{s}\n" for i, (r, s) in enumerate(renglones, 1))).encode()


def _alertas_69b(sesion: Session) -> list[Alerta]:
    return list(sesion.scalars(select(Alerta).where(Alerta.codigo == "LISTA_69B").order_by(Alerta.id)))


def test_alerta_al_ingerir_y_bloqueo_en_todas_las_facturas_del_proveedor(sesion: Session) -> None:
    lista_69b.cargar(sesion, _csv((RFC_A, "Presunto")), archivo="lista.csv", ahora=AHORA)
    una, otra = ingreso(Decimal("1160.00")), ingreso(Decimal("2320.00"))
    r = ingerir(sesion, una, otra, ingreso(Decimal("1160.00"), emisor=RFC_B))
    assert r.archivos[0].resultado == "aceptada_con_alertas"
    (alerta,) = _alertas_69b(sesion)
    assert (alerta.factura_id, alerta.severidad, alerta.estado) == (None, "bloqueante", "abierta")
    for cfdi in (una, otra):
        assert [b.codigo for b in saldos.bloqueos(sesion, factura_de(sesion, cfdi).id)] == ["LISTA_69B"]
        resumen = consultas.resumen_factura(
            sesion, factura_de(sesion, cfdi).id, datetime.fromisoformat("2026-11-02T00:00:00").date()
        )
        assert resumen is not None and resumen.tiene_bloqueante


def test_cerrar_al_salir_y_reabrir_al_volver(sesion: Session) -> None:
    ingerir(sesion, ingreso(Decimal("1160.00")))
    alta = lista_69b.cargar(sesion, _csv((RFC_A, "Definitivo")), archivo="1.csv", ahora=AHORA)
    assert (alta.proveedores_afectados, alta.alertas_creadas, alta.alertas_cerradas) == (1, 1, 0)
    salida = lista_69b.cargar(sesion, _csv((RFC_A, "Desvirtuado")), archivo="2.csv", ahora=AHORA)
    assert salida.alertas_cerradas == 1
    (alerta,) = _alertas_69b(sesion)
    assert alerta.estado == "resuelta" and alerta.resuelta_por is None and alerta.nota_resolucion
    regreso = lista_69b.cargar(sesion, _csv((RFC_A, "Presunto")), archivo="3.csv", ahora=AHORA)
    assert regreso.alertas_creadas == 1
    (alerta,) = _alertas_69b(sesion)
    sesion.refresh(alerta)
    assert alerta.estado == "abierta"


def test_carga_por_http_solo_aprobador_y_csv_invalido(
    cliente: TestClient, sesion: Session, entrar_como: Callable[[int], None]
) -> None:
    ingerir(sesion, ingreso(Decimal("1160.00")))
    entrar_como(crear_usuario(sesion, rol="capturista").id)
    archivo = {"archivo": ("lista.csv", _csv((RFC_A, "Presunto")), "text/csv")}
    assert cliente.post("/api/lista-69b", files=archivo).json()["error"]["codigo"] == "ROL_INSUFICIENTE"

    entrar_como(crear_usuario(sesion, rol="aprobador").id)
    r = cliente.post("/api/lista-69b", files=archivo)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["registros"] == 1 and cuerpo["alertas_creadas"] == 1 and cuerpo["proveedores_afectados"] == 1
    assert cuerpo["por_situacion"] == {"Presunto": 1, "Definitivo": 0, "Desvirtuado": 0, "Sentencia Favorable": 0}
    estado = cliente.get("/api/lista-69b/estado").json()
    assert (estado["cargada"], estado["registros"], estado["archivo"]) == (True, 1, "lista.csv")
    bitacora = cliente.get("/api/bitacora", params={"accion": "LISTA_69B_CARGADA"}).json()
    assert bitacora["total"] == 1

    malo = cliente.post("/api/lista-69b", files={"archivo": ("l.csv", b"No,Nombre\n1,X\n", "text/csv")})
    assert malo.status_code == 422
    assert malo.json()["error"] == {
        "codigo": "CSV_INVALIDO",
        "mensaje": "El archivo no tiene la columna RFC del listado 69-B.",
        "detalle": {"linea": 1, "columna": "RFC"},
    }
    ajeno = cliente.post("/api/lista-69b", files={"archivo": ("l.txt", b"x", "text/plain")})
    assert ajeno.status_code == 422 and ajeno.json()["error"]["codigo"] == "EXTENSION_NO_PERMITIDA"

    # La alerta de la lista no se resuelve a mano.
    (alerta,) = _alertas_69b(sesion)
    r = cliente.post(f"/api/alertas/{alerta.id}/resolver", json={"nota": "Ya lo revisé con el proveedor"})
    assert r.status_code == 422 and r.json()["error"]["codigo"] == "ALERTA_NO_RESOLUBLE"
