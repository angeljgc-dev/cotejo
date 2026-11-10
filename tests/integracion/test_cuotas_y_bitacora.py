"""Mecanismo de cuotas (D10) y registro en bitácora (D7) contra la base real."""

from __future__ import annotations

import threading
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from cotejo.bitacora import AccionInvalida, registrar
from cotejo.modelos import Bitacora, CuotaUso
from cotejo.seguridad.cuotas import CuotaAgotada, consumir, restantes
from tests.apoyo.fabricas import crear_usuario

DIA = date(2026, 11, 2)


def test_consumir_hasta_el_limite(sesion: Session) -> None:
    assert restantes(sesion, "chat:v:abc", 3, DIA) == 3
    assert [consumir(sesion, "chat:v:abc", 3, DIA) for _ in range(3)] == [2, 1, 0]
    with pytest.raises(CuotaAgotada) as exc:
        consumir(sesion, "chat:v:abc", 3, DIA)
    assert exc.value.limite == 3
    assert exc.value.detalle("America/Mexico_City") == {"limite": 3, "se_reinicia": "2026-11-03T00:00:00-06:00"}
    assert restantes(sesion, "chat:v:abc", 3, DIA) == 0
    # El intento rechazado no sumó.
    assert sesion.scalar(select(CuotaUso.contador).where(CuotaUso.clave == "chat:v:abc")) == 3


def test_cuota_por_dia_y_por_clave(sesion: Session) -> None:
    consumir(sesion, "chat:global", 1, DIA)
    assert consumir(sesion, "chat:global", 1, date(2026, 11, 3)) == 0
    assert consumir(sesion, "chat:v:otro", 1, DIA) == 0


def test_limite_cero_siempre_agotado(sesion: Session) -> None:
    with pytest.raises(CuotaAgotada):
        consumir(sesion, "chat:global", 0, DIA)


def test_consumo_simultaneo_no_rebasa_el_limite(motor: Engine) -> None:
    """Diez hilos con su propia conexión y commit compiten por 4 usos: exactamente 4 ganan."""
    clave = "prueba:concurrencia"
    resultados: list[str] = []
    candado = threading.Lock()

    def intentar() -> None:
        with Session(motor) as s:
            try:
                consumir(s, clave, 4, DIA)
                s.commit()
                estado = "ok"
            except CuotaAgotada:
                s.rollback()
                estado = "agotada"
        with candado:
            resultados.append(estado)

    hilos = [threading.Thread(target=intentar) for _ in range(10)]
    try:
        for h in hilos:
            h.start()
        for h in hilos:
            h.join()
        assert sorted(resultados) == ["agotada"] * 6 + ["ok"] * 4
    finally:
        with Session(motor) as s:
            s.execute(delete(CuotaUso).where(CuotaUso.clave == clave))
            s.commit()


def test_registrar_en_bitacora(sesion: Session) -> None:
    usuario = crear_usuario(sesion)
    registrar(
        sesion,
        usuario_id=usuario.id,
        accion="PROVEEDOR_EDITADO",
        entidad="proveedor",
        entidad_id=15,
        detalle={"antes": {"dias_credito": 30}, "despues": {"dias_credito": 45}, "saldo": Decimal("10.50")},
    )
    sesion.flush()
    fila = sesion.scalars(select(Bitacora)).one()
    assert (fila.usuario_id, fila.accion, fila.entidad, fila.entidad_id) == (
        usuario.id,
        "PROVEEDOR_EDITADO",
        "proveedor",
        "15",
    )
    assert fila.detalle == {"antes": {"dias_credito": 30}, "despues": {"dias_credito": 45}, "saldo": "10.50"}
    assert fila.ocurrido_en.tzinfo is not None


@pytest.mark.parametrize(("accion", "entidad"), [("BORRAR_TODO", "factura"), ("CARGA_CFDI", "planeta")])
def test_registrar_rechaza_accion_o_entidad_desconocida(sesion: Session, accion: str, entidad: str) -> None:
    with pytest.raises(AccionInvalida):
        registrar(sesion, usuario_id=None, accion=accion, entidad=entidad, entidad_id=None, detalle={})
