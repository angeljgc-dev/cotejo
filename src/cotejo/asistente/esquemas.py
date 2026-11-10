"""Argumentos de cada herramienta del asistente, validados con Pydantic.

El modelo de lenguaje solo puede pedir estas operaciones con estos parámetros cerrados. No hay parámetro para
el usuario, la fecha ni el estado de una propuesta: eso lo pone el código a partir de la sesión.
"""

from __future__ import annotations

from datetime import date
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Horizonte = Literal["vencidas", "esta_semana", "proximos_7_dias", "proximos_30_dias"]

PATRON_MES = r"^[0-9]{4}-(0[1-9]|1[0-2])$"
PATRON_IMPORTE = r"^[0-9]{1,12}(\.[0-9]{1,2})?$"
PATRON_UUID = r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$"


class Argumentos(BaseModel):
    """Base de los argumentos: campos desconocidos se rechazan en lugar de ignorarse."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class BuscarProveedores(Argumentos):
    texto: str | None = Field(default=None, min_length=2, max_length=80, description="Parte del nombre o del RFC.")
    rfc: str | None = Field(default=None, min_length=12, max_length=13, description="RFC exacto.")
    limite: int = Field(default=10, ge=1, le=20)


class AdeudoProveedor(Argumentos):
    proveedor_id: int = Field(description="Id del proveedor; se obtiene con buscar_proveedores.")


class ListarFacturas(Argumentos):
    proveedor_id: int | None = None
    estado: Literal["pendiente", "vencida", "por_vencer", "pagada"] | None = None
    vence_desde: date | None = Field(default=None, description="Vencimiento desde, AAAA-MM-DD.")
    vence_hasta: date | None = Field(default=None, description="Vencimiento hasta, AAAA-MM-DD.")
    con_alertas: bool | None = None
    limite: int = Field(default=20, ge=1, le=50)


class Vencimientos(Argumentos):
    horizonte: Horizonte


class TotalesPorMes(Argumentos):
    medida: Literal["facturado", "pagado", "saldo"]
    desde_mes: str = Field(pattern=PATRON_MES, description="AAAA-MM")
    hasta_mes: str = Field(pattern=PATRON_MES, description="AAAA-MM; máximo 24 meses de rango.")
    proveedor_id: int | None = None


class AntiguedadSaldos(Argumentos):
    pass


class DetalleFactura(Argumentos):
    factura_id: int | None = None
    uuid: str | None = Field(default=None, pattern=PATRON_UUID, description="Folio fiscal (UUID) del CFDI.")

    @model_validator(mode="after")
    def _uno_de_los_dos(self) -> Self:
        if (self.factura_id is None) == (self.uuid is None):
            raise ValueError("Indica factura_id o uuid, solo uno.")
        return self


class BuscarDocumentos(Argumentos):
    consulta: str = Field(min_length=3, max_length=300, description="Qué se busca en contratos y políticas.")
    proveedor_id: int | None = Field(default=None, description="Limita a documentos de ese proveedor y generales.")
    k: int = Field(default=5, ge=1, le=8)


class ProponerPagos(Argumentos):
    presupuesto_mxn: str = Field(
        pattern=PATRON_IMPORTE, description='Presupuesto en pesos como texto, p. ej. "50000.00".'
    )
    horizonte: Horizonte | None = Field(default=None, description="Qué vencimientos considerar; incluye lo ya vencido.")
    factura_ids: list[int] | None = Field(default=None, min_length=1, max_length=30)
    nota: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def _algun_criterio(self) -> Self:
        if self.horizonte is None and self.factura_ids is None:
            raise ValueError("Indica un horizonte o una lista de factura_ids.")
        return self


def _sin_titulos(nodo: object) -> object:
    """Quita los títulos que Pydantic agrega al esquema: no aportan al modelo y gastan tokens."""
    if isinstance(nodo, dict):
        return {k: _sin_titulos(v) for k, v in nodo.items() if not (k == "title" and isinstance(v, str))}
    if isinstance(nodo, list):
        return [_sin_titulos(v) for v in nodo]
    return nodo


def esquema_json(modelo: type[Argumentos]) -> dict[str, object]:
    """JSON Schema de los parámetros de una herramienta, compacto."""
    esquema = _sin_titulos(modelo.model_json_schema())
    if not isinstance(esquema, dict):
        raise TypeError("El esquema de argumentos debe ser un objeto.")
    esquema.pop("description", None)
    esquema.setdefault("properties", {})
    return esquema
