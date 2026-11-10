"""Ayudas de las pruebas del asistente: instalar un guion en lugar del modelo y fotografiar el estado de la base."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from decimal import Decimal

from fastapi import FastAPI
from sqlalchemy.orm import Session

from cotejo.asistente.cliente_modelo import MensajeModelo
from cotejo.asistente.guionado import ClienteGuionado, Paso, PasoGuion, resultados_de_herramientas
from cotejo.asistente.servicio import obtener_cliente_modelo
from cotejo.cxp import alertas
from cotejo.evaluacion.calificador import huella
from cotejo.modelos import (
    Concepto,
    Factura,
    Proveedor,
)
from tests.apoyo.fabricas import crear_factura

Entrar = Callable[[int], None]

__all__ = [
    "Entrar",
    "bloquear",
    "como_dict",
    "elementos",
    "factura_con",
    "huella",
    "instalar_guion",
    "texto_con",
    "ultimo_resultado",
]


def instalar_guion(app: FastAPI, pasos: Sequence[Paso]) -> ClienteGuionado:
    """Sustituye el modelo de lenguaje de la app por un guion. Todo lo demás es el código real."""
    guion = ClienteGuionado(pasos)
    app.dependency_overrides[obtener_cliente_modelo] = lambda: guion
    return guion


def ultimo_resultado(mensajes: Sequence[MensajeModelo]) -> dict[str, object]:
    return resultados_de_herramientas(mensajes)[-1]


def texto_con(plantilla: Callable[[dict[str, object]], str]) -> Paso:
    """Paso final cuyo texto se arma con el último resultado de herramienta, como haría un modelo que copia cifras."""

    def paso(mensajes: Sequence[MensajeModelo]) -> PasoGuion:
        return PasoGuion(texto=plantilla(ultimo_resultado(mensajes)))

    return paso


def factura_con(
    sesion: Session,
    total: str,
    emision: str,
    *,
    proveedor: Proveedor | None = None,
    tipo: str = "I",
    moneda: str = "MXN",
    tipo_cambio: Decimal | None = None,
    concepto: str | None = None,
) -> Factura:
    factura = crear_factura(
        sesion,
        proveedor=proveedor,
        tipo=tipo,
        total=Decimal(total),
        moneda=moneda,
        tipo_cambio=tipo_cambio,
        fecha_emision=datetime.fromisoformat(f"{emision}T10:00:00"),
    )
    if concepto is not None:
        sesion.add(
            Concepto(
                factura_id=factura.id,
                orden=1,
                clave_prod_serv="01010101",
                cantidad=Decimal(1),
                clave_unidad="H87",
                descripcion=concepto,
                valor_unitario=factura.subtotal,
                importe=factura.subtotal,
                objeto_imp="02",
            )
        )
        sesion.commit()
    return factura


def bloquear(
    sesion: Session, codigo: str, *, factura: Factura | None = None, proveedor: Proveedor | None = None
) -> None:
    """Abre una alerta bloqueante como las que deja la ingesta (69-B del proveedor o de una factura)."""
    alertas.abrir(
        sesion,
        codigo=codigo,
        severidad="bloqueante",
        mensaje=f"Alerta bloqueante de prueba ({codigo}).",
        factura_id=factura.id if factura is not None else None,
        proveedor_id=proveedor.id if proveedor is not None else (factura.proveedor_id if factura is not None else None),
    )
    sesion.commit()


def como_dict(dato: object) -> dict[str, object]:
    assert isinstance(dato, dict), f"se esperaba un objeto JSON y llegó {type(dato).__name__}"
    return dato


def elementos(dato: dict[str, object], clave: str) -> list[dict[str, object]]:
    """Lista de objetos dentro de un resultado JSON, con el tipo comprobado."""
    valor = dato[clave]
    assert isinstance(valor, list), f"{clave} no es una lista"
    return [como_dict(v) for v in valor]
