"""Formato de los casos de evaluación del asistente (`eval/casos_asistente.json`).

Lo esperado no se escribe como texto de respuesta sino como hechos comprobables: qué cifra debe aparecer (se
calcula con la misma consulta contra la base sembrada), qué documento y página debe citar, y qué debe o no debe
existir en la base después de la pregunta.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RUTA_CASOS = Path("eval") / "casos_asistente.json"

Categoria = Literal["numerica", "documentos", "propuestas", "negativa", "ataque"]
MINIMOS_POR_CATEGORIA: dict[Categoria, int] = {
    "numerica": 12,
    "documentos": 10,
    "propuestas": 8,
    "negativa": 5,
    "ataque": 8,
}
MINIMO_TOTAL = 40


class _Estricto(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CifraEsperada(_Estricto):
    """Una cifra que debe aparecer en la respuesta. Su valor se obtiene ejecutando esa herramienta en la base."""

    herramienta: str
    argumentos: dict[str, object] = Field(default_factory=dict)
    # Parte del nombre del proveedor; se resuelve a `proveedor_id` en los argumentos.
    proveedor: str | None = None
    # Ruta dentro del resultado: "adeudo_mxn" o "grupos[grupo=mas_90].saldo_mxn".
    campo: str


class CitaEsperada(_Estricto):
    documento: str
    pagina: int


class PropuestaEsperada(_Estricto):
    """Qué propuesta debe quedar. Siempre pendiente; nunca con facturas bloqueadas ni por encima del presupuesto.

    `igual_a_seleccion`: debe existir y llevar exactamente las facturas que elige el sistema con ese presupuesto
    y horizonte (si el sistema no elegiría ninguna, no debe existir). `opcional`: puede existir o no.
    """

    presupuesto_mxn: str
    horizonte: Literal["vencidas", "esta_semana", "proximos_7_dias", "proximos_30_dias"] | None = None
    modo: Literal["igual_a_seleccion", "opcional"] = "igual_a_seleccion"


class Esperado(_Estricto):
    herramientas_incluye: list[str] = Field(default_factory=list)
    herramientas_incluye_alguna: list[str] = Field(default_factory=list)
    herramientas_excluye: list[str] = Field(default_factory=list)
    cifras: list[CifraEsperada] = Field(default_factory=list)
    citas_incluyen: list[CitaEsperada] = Field(default_factory=list)
    # Basta con que aparezca una de las formas (sin acentos ni mayúsculas): "45" o "cuarenta y cinco".
    texto_incluye_alguna: list[str] = Field(default_factory=list)
    # La respuesta debe decir que no puede o que no lo encontró.
    negativa: bool = False
    sin_citas: bool = False
    # None: no debe crearse ninguna propuesta.
    propuesta: PropuestaEsperada | None = None


class CasoAsistente(_Estricto):
    id: str
    categoria: Categoria
    rol: Literal["capturista", "aprobador"] = "capturista"
    pregunta: str = Field(min_length=3, max_length=2000)
    esperado: Esperado


def cargar_casos(ruta: Path = RUTA_CASOS) -> list[CasoAsistente]:
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    casos = [CasoAsistente.model_validate(c) for c in datos["casos"]]
    ids = [c.id for c in casos]
    repetidos = sorted({i for i in ids if ids.count(i) > 1})
    if repetidos:
        raise ValueError(f"Casos con id repetido: {', '.join(repetidos)}")
    return casos


def conteo_por_categoria(casos: list[CasoAsistente]) -> dict[str, int]:
    conteo: dict[str, int] = dict.fromkeys(MINIMOS_POR_CATEGORIA, 0)
    for caso in casos:
        conteo[caso.categoria] += 1
    return conteo
