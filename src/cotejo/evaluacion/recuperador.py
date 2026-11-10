"""Evaluación del recuperador (E3): en qué proporción el fragmento correcto queda entre los primeros 5.

No usa modelo de lenguaje. Compara la búsqueda solo por vector, solo por palabras y la híbrida sobre los
documentos de demostración, con preguntas cuya respuesta se conoce.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from cotejo.documentos.busqueda import Hallazgo, Modo, buscar
from cotejo.documentos.embeddings import Embedder
from cotejo.documentos.normalizar import normalizar
from cotejo.documentos.semilla import sembrar_documentos
from cotejo.modelos import Documento, Fragmento, Usuario

RUTA_CASOS = Path("eval") / "casos_recuperador.json"
K = 5
TIPOS = ("parafrasis", "termino_exacto")


@dataclass(frozen=True)
class CasoRecuperador:
    id: str
    pregunta: str
    documento: str
    pagina: int
    frase_clave: str
    tipo: str = "parafrasis"


@dataclass(frozen=True)
class Variante:
    """Una forma de buscar que se mide. `todas_las_palabras` exige todos los términos de la pregunta."""

    clave: str
    etiqueta: str
    modo: Modo
    todas_las_palabras: bool = False


VARIANTES: tuple[Variante, ...] = (
    Variante("vector", "Solo vector (significado)", "vector"),
    Variante("texto", "Solo texto completo (alguna palabra)", "texto"),
    Variante("texto_todas", "Solo texto completo (todas las palabras)", "texto", todas_las_palabras=True),
    Variante("hibrida", "Híbrida (vector + texto, RRF)", "hibrida"),
)


@dataclass(frozen=True)
class Metricas:
    casos: int
    aciertos: int
    recall_en_k: float
    mrr: float
    fallos: tuple[str, ...]


def cargar_casos(ruta: Path = RUTA_CASOS) -> list[CasoRecuperador]:
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    return [
        CasoRecuperador(
            id=str(c["id"]),
            pregunta=str(c["pregunta"]),
            documento=str(c["documento"]),
            pagina=int(c["pagina"]),
            frase_clave=str(c["frase_clave"]),
            tipo=str(c.get("tipo", "parafrasis")),
        )
        for c in datos["casos"]
    ]


def es_acierto(caso: CasoRecuperador, hallazgo: Hallazgo) -> bool:
    """El fragmento es del documento y la página esperados y contiene la frase clave (sin acentos ni mayúsculas)."""
    return (
        hallazgo.documento == caso.documento
        and hallazgo.pagina == caso.pagina
        and normalizar(caso.frase_clave) in normalizar(hallazgo.texto)
    )


def posicion_del_acierto(caso: CasoRecuperador, hallazgos: Sequence[Hallazgo], k: int = K) -> int | None:
    """Posición (desde 1) del primer fragmento correcto entre los `k` primeros; None si no está."""
    for posicion, hallazgo in enumerate(hallazgos[:k], start=1):
        if es_acierto(caso, hallazgo):
            return posicion
    return None


def calificar(casos: Sequence[CasoRecuperador], resultados: Mapping[str, Sequence[Hallazgo]], k: int = K) -> Metricas:
    """recall@k = casos con acierto / casos; MRR = promedio de 1 / posición del acierto (0 si no hubo)."""
    if not casos:
        return Metricas(casos=0, aciertos=0, recall_en_k=0.0, mrr=0.0, fallos=())
    posiciones = {caso.id: posicion_del_acierto(caso, resultados.get(caso.id, ()), k) for caso in casos}
    aciertos = [p for p in posiciones.values() if p is not None]
    return Metricas(
        casos=len(casos),
        aciertos=len(aciertos),
        recall_en_k=len(aciertos) / len(casos),
        mrr=sum(1.0 / p for p in aciertos) / len(casos),
        fallos=tuple(caso_id for caso_id, p in posiciones.items() if p is None),
    )


def buscar_casos(
    sesion: Session,
    casos: Sequence[CasoRecuperador],
    embedder: Embedder,
    variante: Variante,
    *,
    documento_ids: Sequence[int],
    k: int = K,
) -> dict[str, list[Hallazgo]]:
    """Resultados de cada pregunta con una variante de búsqueda, limitada a los documentos indicados."""
    return {
        caso.id: buscar(
            sesion,
            caso.pregunta,
            embedder=embedder,
            modo=variante.modo,
            k=k,
            documento_ids=documento_ids,
            todas_las_palabras=variante.todas_las_palabras,
        )
        for caso in casos
    }


def evaluar_documentos_demo(sesion: Session, embedder: Embedder, casos: Sequence[CasoRecuperador]) -> dict[str, object]:
    """Indexa los documentos de demostración en la transacción en curso y los evalúa.

    Quien llama decide si confirma o revierte la transacción; la evaluación no necesita que los datos queden.
    """
    usuario = sesion.scalar(select(Usuario).order_by(Usuario.id).limit(1))
    if usuario is None:
        usuario = Usuario(usuario="evaluacion.recuperador", nombre="Evaluación del recuperador", rol="capturista")
        sesion.add(usuario)
        sesion.flush()
    sembrar_documentos(sesion, usuario.id, embedder=embedder)
    nombres = sorted({caso.documento for caso in casos})
    documento_ids = list(sesion.scalars(select(Documento.id).where(Documento.nombre.in_(nombres))))
    fragmentos = sesion.scalars(select(Fragmento.id).where(Fragmento.documento_id.in_(documento_ids))).all()
    variantes: list[dict[str, object]] = []
    for variante in VARIANTES:
        resultados = buscar_casos(sesion, casos, embedder, variante, documento_ids=documento_ids)
        por_tipo = {tipo: asdict(calificar([c for c in casos if c.tipo == tipo], resultados)) for tipo in TIPOS}
        variantes.append(
            {
                "clave": variante.clave,
                "etiqueta": variante.etiqueta,
                **asdict(calificar(casos, resultados)),
                "por_tipo": por_tipo,
            }
        )
    return {
        "embeddings": embedder.nombre,
        "k": K,
        "casos": len(casos),
        "documentos": len(documento_ids),
        "fragmentos": len(fragmentos),
        "variantes": variantes,
    }


def tabla(resultado: Mapping[str, object]) -> str:
    """Tabla en texto plano del resultado, para la terminal y la documentación."""
    variantes = resultado["variantes"]
    if not isinstance(variantes, list):
        raise TypeError("El resultado no tiene variantes.")
    k = resultado["k"]
    lineas = [
        f"Recuperador: {resultado['casos']} preguntas, {resultado['fragmentos']} fragmentos de "
        f"{resultado['documentos']} documentos, embeddings {resultado['embeddings']}",
        f"{'Variante':<42} {'recall@' + str(k):>9} {'MRR':>6}  {'paráfrasis':>11}  {'término exacto':>14}",
    ]
    for v in variantes:
        parafrasis, exacto = v["por_tipo"]["parafrasis"], v["por_tipo"]["termino_exacto"]
        lineas.append(
            f"{v['etiqueta']:<42} {v['recall_en_k']:>9.3f} {v['mrr']:>6.3f}  "
            f"{parafrasis['aciertos']:>7}/{parafrasis['casos']:<3}  {exacto['aciertos']:>10}/{exacto['casos']:<3}"
        )
    return "\n".join(lineas)
