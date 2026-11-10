from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, Text, false, true
from sqlalchemy.orm import Mapped, mapped_column

from cotejo.modelos.base import Base, CreadoEn, IdPk, Texto, TextoNulo

ROLES = ("capturista", "aprobador")


class Usuario(Base):
    __tablename__ = "usuarios"
    __table_args__ = (
        CheckConstraint(r"usuario ~ '^[a-z0-9._-]{3,40}$'", name="usuario_formato"),
        CheckConstraint("rol in ('capturista','aprobador')", name="rol_valido"),
    )

    id: Mapped[IdPk]
    usuario: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    nombre: Mapped[Texto]
    rol: Mapped[Texto]
    hash_contrasena: Mapped[TextoNulo]
    es_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=true())
    creado_en: Mapped[CreadoEn]
