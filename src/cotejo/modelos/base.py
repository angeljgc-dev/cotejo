"""Base declarativa y tipos comunes del modelo de datos (DISEÑO sección 3)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated

from sqlalchemy import BigInteger, DateTime, Identity, MetaData, Numeric, Text, func
from sqlalchemy.orm import DeclarativeBase, mapped_column

# Nombres deterministas de restricciones: la migración y los modelos generan exactamente los mismos.
CONVENCION_NOMBRES = {
    "ix": "ix_%(column_0_N_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=CONVENCION_NOMBRES)


IdPk = Annotated[int, mapped_column(BigInteger, Identity(always=True), primary_key=True)]
CreadoEn = Annotated[datetime, mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)]
Texto = Annotated[str, mapped_column(Text, nullable=False)]
TextoNulo = Annotated[str | None, mapped_column(Text, nullable=True)]
# numeric(20,6): importes tal cual el XML (t_Importe del SAT admite 6 decimales).
ImporteXml = Annotated[Decimal, mapped_column(Numeric(20, 6), nullable=False)]
ImporteXmlNulo = Annotated[Decimal | None, mapped_column(Numeric(20, 6), nullable=True)]
# numeric(20,2): importes que calcula o captura Cotejo.
ImportePropio = Annotated[Decimal, mapped_column(Numeric(20, 2), nullable=False)]
