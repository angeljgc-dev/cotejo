"""Cuotas de uso por clave y día (D10, límites de carga, intentos de inicio de sesión).

El incremento es atómico en una sola sentencia: dos peticiones simultáneas nunca rebasan el límite.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from cotejo.fechas import siguiente_medianoche
from cotejo.modelos import CuotaUso


class CuotaAgotada(Exception):
    def __init__(self, clave: str, limite: int, dia: date) -> None:
        super().__init__(f"Cuota agotada para {clave!r}: {limite} por día.")
        self.clave = clave
        self.limite = limite
        self.dia = dia

    def detalle(self, zona_horaria: str) -> dict[str, object]:
        """Detalle del error 429 del contrato: {"limite": 20, "se_reinicia": "2026-11-10T00:00:00-06:00"}."""
        return {"limite": self.limite, "se_reinicia": siguiente_medianoche(self.dia, zona_horaria).isoformat()}


def consumir(sesion: Session, clave: str, limite: int, dia: date) -> int:
    """Suma un uso y devuelve cuántos quedan. Lanza CuotaAgotada sin sumar si ya se llegó al límite.

    El conteo vive en la transacción de la petición: si la petición falla y se revierte, el uso no cuenta.
    Quien necesite que cuente aun con error (intentos de contraseña) debe hacer commit antes de lanzar.
    """
    if limite <= 0:
        raise CuotaAgotada(clave, limite, dia)
    sentencia = (
        insert(CuotaUso)
        .values(clave=clave, dia=dia, contador=1)
        .on_conflict_do_update(
            index_elements=[CuotaUso.clave, CuotaUso.dia],
            set_={"contador": CuotaUso.contador + 1},
            where=CuotaUso.contador < limite,
        )
        .returning(CuotaUso.contador)
    )
    contador = sesion.execute(sentencia).scalar_one_or_none()
    if contador is None:
        raise CuotaAgotada(clave, limite, dia)
    return limite - contador


def restantes(sesion: Session, clave: str, limite: int, dia: date) -> int:
    usado = sesion.scalar(select(CuotaUso.contador).where(CuotaUso.clave == clave, CuotaUso.dia == dia)) or 0
    return max(limite - usado, 0)
