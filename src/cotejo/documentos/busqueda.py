"""Búsqueda híbrida sobre los fragmentos (C2): significado (vector) y palabras (texto completo).

Cada método aporta sus 20 mejores candidatos y se fusionan por rango recíproco (RRF). No se usa un umbral de
similitud: las similitudes de e5 son muy parecidas entre sí, así que solo sirve el orden.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import ColumnElement, Select, Text, cast, func, or_, select, text
from sqlalchemy.dialects.postgresql import REGCONFIG
from sqlalchemy.orm import Session

from cotejo.documentos.embeddings import Embedder
from cotejo.documentos.indexado import IDIOMA
from cotejo.documentos.normalizar import normalizar
from cotejo.modelos import Documento, Fragmento, Proveedor

Modo = Literal["hibrida", "texto", "vector"]
Fuente = Literal["vector", "texto"]

CANDIDATOS_POR_METODO = 20
CONSTANTE_RRF = 60
EF_SEARCH = 40


@dataclass(frozen=True)
class Fusionado:
    fragmento_id: int
    puntaje: float
    fuentes: tuple[Fuente, ...]


@dataclass(frozen=True)
class Hallazgo:
    fragmento_id: int
    documento_id: int
    documento: str
    pagina: int
    orden: int
    texto: str
    puntaje: float
    fuentes: tuple[Fuente, ...]
    # Nombre del proveedor al que pertenece el documento; None en políticas generales.
    proveedor: str | None = None


def fusionar_rrf(listas: Mapping[Fuente, Sequence[int]], k: int) -> list[Fusionado]:
    """Fusión por rango recíproco: puntaje = suma de 1 / (60 + rango) en cada lista, con rango desde 1.

    Un fragmento que aparece en las dos listas le gana a uno que solo aparece en una en la misma posición.
    El empate se resuelve por id para que el resultado sea determinista.
    """
    puntajes: dict[int, float] = {}
    fuentes: dict[int, list[Fuente]] = {}
    for fuente, ids in listas.items():
        for rango, fragmento_id in enumerate(ids, start=1):
            puntajes[fragmento_id] = puntajes.get(fragmento_id, 0.0) + 1.0 / (CONSTANTE_RRF + rango)
            fuentes.setdefault(fragmento_id, []).append(fuente)
    orden = sorted(puntajes, key=lambda fid: (-puntajes[fid], fid))
    return [Fusionado(fid, puntajes[fid], tuple(fuentes[fid])) for fid in orden[:k]]


def priorizar_propios(fusionados: Sequence[Fusionado], propios: set[int], k: int) -> list[Fusionado]:
    """Pone primero los fragmentos de los documentos del proveedor consultado, hasta la mitad de los lugares.

    Si alguien pregunta por un proveedor, su contrato es la fuente principal aunque una política general
    coincida mejor por palabras. La otra mitad se deja al orden normal para que esas políticas sigan saliendo.
    """
    reservados = [f for f in fusionados if f.fragmento_id in propios][: (k + 1) // 2]
    elegidos = {f.fragmento_id for f in reservados}
    resto = [f for f in fusionados if f.fragmento_id not in elegidos]
    return [*reservados, *resto][:k]


def _con_filtros(
    consulta: Select[tuple[int]], proveedor_id: int | None, documento_ids: Sequence[int] | None
) -> Select[tuple[int]]:
    consulta = consulta.join(Documento, Documento.id == Fragmento.documento_id)
    if proveedor_id is not None:
        # Los documentos sin proveedor son políticas generales: aplican a todos.
        consulta = consulta.where(or_(Documento.proveedor_id == proveedor_id, Documento.proveedor_id.is_(None)))
    if documento_ids is not None:
        consulta = consulta.where(Documento.id.in_(documento_ids))
    return consulta


def _por_vector(
    sesion: Session, vector: object, proveedor_id: int | None, documento_ids: Sequence[int] | None
) -> list[int]:
    sesion.execute(text(f"SET LOCAL hnsw.ef_search = {EF_SEARCH}"))
    distancia = Fragmento.embedding.cosine_distance(vector)
    consulta = _con_filtros(select(Fragmento.id), proveedor_id, documento_ids)
    return list(sesion.scalars(consulta.order_by(distancia, Fragmento.id).limit(CANDIDATOS_POR_METODO)))


def consulta_de_palabras(q_normalizada: str, *, todas: bool = False) -> ColumnElement[object]:
    """tsquery con las palabras de la consulta reducidas a su raíz; por omisión basta con que aparezca una.

    Una pregunta en lenguaje natural casi nunca tiene todas sus palabras en un mismo fragmento, así que exigirlas
    todas deja la lista vacía. El orden lo pone ts_rank_cd, que premia a los fragmentos con más palabras de la
    consulta y más juntas. `todas=True` existe para medir esa diferencia en la evaluación del recuperador.
    """
    exigente = func.plainto_tsquery(IDIOMA, q_normalizada)
    if todas:
        return exigente
    # Las raíces ya vienen calculadas: se recombinan con "o" usando la configuración simple, que no las altera.
    return func.to_tsquery(cast("simple", REGCONFIG), func.replace(cast(exigente, Text), "&", "|"))


def _por_texto(
    sesion: Session,
    q_normalizada: str,
    proveedor_id: int | None,
    documento_ids: Sequence[int] | None,
    todas: bool,
) -> list[int]:
    consulta_ts = consulta_de_palabras(q_normalizada, todas=todas)
    # Una consulta formada solo por palabras vacías ("de la que") no produce términos: se omite.
    if not sesion.scalar(select(func.numnode(consulta_ts))):
        return []
    relevancia = func.ts_rank_cd(Fragmento.tsv, consulta_ts)
    consulta = _con_filtros(select(Fragmento.id), proveedor_id, documento_ids).where(
        Fragmento.tsv.op("@@")(consulta_ts)
    )
    return list(sesion.scalars(consulta.order_by(relevancia.desc(), Fragmento.id).limit(CANDIDATOS_POR_METODO)))


def buscar(
    sesion: Session,
    consulta: str,
    *,
    embedder: Embedder,
    modo: Modo = "hibrida",
    proveedor_id: int | None = None,
    k: int = 5,
    documento_ids: Sequence[int] | None = None,
    todas_las_palabras: bool = False,
) -> list[Hallazgo]:
    """Los `k` fragmentos más relevantes, con el documento, la página y qué método los encontró."""
    listas: dict[Fuente, Sequence[int]] = {}
    if modo in ("hibrida", "vector"):
        listas["vector"] = _por_vector(sesion, embedder.consulta(consulta), proveedor_id, documento_ids)
    if modo in ("hibrida", "texto"):
        listas["texto"] = _por_texto(sesion, normalizar(consulta), proveedor_id, documento_ids, todas_las_palabras)
    fusionados = fusionar_rrf(listas, CANDIDATOS_POR_METODO * 2)
    if not fusionados:
        return []
    filas = sesion.execute(
        select(
            Fragmento.id,
            Fragmento.documento_id,
            Documento.nombre,
            Documento.proveedor_id,
            Proveedor.nombre.label("proveedor_nombre"),
            Fragmento.pagina,
            Fragmento.orden,
            Fragmento.texto,
        )
        .join(Documento, Documento.id == Fragmento.documento_id)
        .outerjoin(Proveedor, Proveedor.id == Documento.proveedor_id)
        .where(Fragmento.id.in_([f.fragmento_id for f in fusionados]))
    ).all()
    por_id = {fila.id: fila for fila in filas}
    if proveedor_id is None:
        fusionados = fusionados[:k]
    else:
        propios = {fila.id for fila in filas if fila.proveedor_id == proveedor_id}
        fusionados = priorizar_propios(fusionados, propios, k)
    return [
        Hallazgo(
            fragmento_id=f.fragmento_id,
            documento_id=por_id[f.fragmento_id].documento_id,
            documento=por_id[f.fragmento_id].nombre,
            pagina=por_id[f.fragmento_id].pagina,
            orden=por_id[f.fragmento_id].orden,
            texto=por_id[f.fragmento_id].texto,
            puntaje=f.puntaje,
            fuentes=f.fuentes,
            proveedor=por_id[f.fragmento_id].proveedor_nombre,
        )
        for f in fusionados
        if f.fragmento_id in por_id
    ]
