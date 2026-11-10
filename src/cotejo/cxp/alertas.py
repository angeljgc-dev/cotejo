"""Alta y cierre de alertas. Abrir la misma alerta dos veces no la duplica (llave única en la base)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from cotejo.bitacora import a_json
from cotejo.modelos import Alerta


def abrir(
    sesion: Session,
    *,
    codigo: str,
    severidad: str,
    mensaje: str,
    factura_id: int | None = None,
    proveedor_id: int | None = None,
    detalle: Mapping[str, object] | None = None,
    factura_relacionada_id: int | None = None,
    reabrir: bool = False,
) -> bool:
    """Registra la alerta si no existía. Devuelve True si quedó una alerta nueva o reabierta.

    Con `reabrir`, una alerta igual que ya estaba resuelta vuelve a quedar abierta (la condición reapareció).
    Sin `reabrir`, una alerta resuelta por una persona se respeta y no se vuelve a abrir.
    """
    if factura_id is None and proveedor_id is None:
        raise ValueError("Una alerta necesita factura o proveedor.")
    detalle_json = {str(k): a_json(v) for k, v in (detalle or {}).items()}
    creada = sesion.execute(
        insert(Alerta)
        .values(
            factura_id=factura_id,
            proveedor_id=proveedor_id,
            codigo=codigo,
            severidad=severidad,
            mensaje=mensaje,
            detalle=detalle_json,
            factura_relacionada_id=factura_relacionada_id,
        )
        .on_conflict_do_nothing(constraint="uq_alertas_idempotencia")
        .returning(Alerta.id)
    ).scalar_one_or_none()
    if creada is not None:
        return True
    if not reabrir:
        return False
    reabierta = sesion.execute(
        update(Alerta)
        .where(
            Alerta.factura_id.is_not_distinct_from(factura_id),
            Alerta.proveedor_id.is_not_distinct_from(proveedor_id),
            Alerta.codigo == codigo,
            Alerta.factura_relacionada_id.is_not_distinct_from(factura_relacionada_id),
            Alerta.estado == "resuelta",
        )
        .values(
            estado="abierta",
            resuelta_en=None,
            resuelta_por=None,
            nota_resolucion=None,
            mensaje=mensaje,
            detalle=detalle_json,
        )
        .returning(Alerta.id)
    ).scalar_one_or_none()
    return reabierta is not None


def cerrar_por_sistema(sesion: Session, alerta_ids: list[int], nota: str) -> int:
    """Cierra alertas abiertas sin usuario (las resolvió el sistema). Devuelve cuántas cerró."""
    if not alerta_ids:
        return 0
    cerradas = sesion.execute(
        update(Alerta)
        .where(Alerta.id.in_(alerta_ids), Alerta.estado == "abierta")
        .values(estado="resuelta", resuelta_en=datetime.now(UTC), resuelta_por=None, nota_resolucion=nota)
        .returning(Alerta.id)
    ).all()
    return len(cerradas)


def ids_abiertas(
    sesion: Session, *, codigo: str, factura_id: int | None = None, proveedor_id: int | None = None
) -> list[int]:
    consulta = select(Alerta.id).where(Alerta.codigo == codigo, Alerta.estado == "abierta")
    if factura_id is not None:
        consulta = consulta.where(Alerta.factura_id == factura_id)
    if proveedor_id is not None:
        consulta = consulta.where(Alerta.proveedor_id == proveedor_id)
    return list(sesion.scalars(consulta))
