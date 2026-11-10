"""Tablas en Markdown de los resultados de evaluación guardados, para la documentación.

Los números se toman tal cual de los archivos de `eval/resultados/`: aquí no se calcula ni se redondea nada
más allá de dar formato.
"""

from __future__ import annotations

import json
from pathlib import Path

SIN_CORRIDAS_DEL_ASISTENTE = (
    "Todavía no hay una corrida de la batería del asistente con un modelo real. "
    "Se corre con: python -m cotejo.evaluacion asistente"
)


def _leer(carpeta: Path) -> list[dict[str, object]]:
    corridas: list[dict[str, object]] = []
    for ruta in sorted(carpeta.glob("*.json")):
        dato = json.loads(ruta.read_text(encoding="utf-8"))
        if isinstance(dato, dict):
            corridas.append({**dato, "_archivo": ruta.name})
    return corridas


def _tabla_recuperador(corrida: dict[str, object]) -> list[str]:
    lineas = [
        f"### Recuperador, {corrida['fecha']}",
        "",
        f"Modelo de embeddings `{corrida['embeddings']}` (`{corrida.get('archivo_del_modelo', '')}`), "
        f"{corrida['casos']} preguntas sobre {corrida['fragmentos']} fragmentos de {corrida['documentos']} documentos. "
        f"Archivo: `{corrida['_archivo']}`.",
        "",
        f"| Búsqueda | recall@{corrida['k']} | MRR | Paráfrasis | Término exacto |",
        "|---|---|---|---|---|",
    ]
    variantes = corrida["variantes"]
    if isinstance(variantes, list):
        for v in variantes:
            parafrasis, exacto = v["por_tipo"]["parafrasis"], v["por_tipo"]["termino_exacto"]
            lineas.append(
                f"| {v['etiqueta']} | {v['recall_en_k']:.3f} ({v['aciertos']}/{v['casos']}) | {v['mrr']:.3f} | "
                f"{parafrasis['aciertos']}/{parafrasis['casos']} | {exacto['aciertos']}/{exacto['casos']} |"
            )
    return lineas


def _tabla_asistente(corrida: dict[str, object]) -> list[str]:
    totales = corrida["totales"]
    if not isinstance(totales, dict):
        return []
    lineas = [
        f"### Asistente, {corrida['fecha']}, modelo `{corrida['modelo']}`",
        "",
        f"Proveedor `{corrida['url_base']}`, versión de instrucciones `{corrida['version_prompt']}`, "
        f"commit `{corrida.get('commit')}`. Archivo: `{corrida['_archivo']}`.",
        "",
        "| Categoría | Aprobados | Total | Con error del proveedor |",
        "|---|---|---|---|",
    ]
    for categoria, grupo in totales["por_categoria"].items():
        lineas.append(f"| {categoria} | {grupo['aprobados']} | {grupo['total']} | {grupo['con_error']} |")
    lineas.append(f"| **Total** | **{totales['aprobados']}** | **{totales['casos']}** | {totales['con_error']} |")
    en_bateria = corrida.get("casos_en_la_bateria")
    if isinstance(en_bateria, int) and en_bateria != totales["casos"]:
        lineas += ["", f"Corrida parcial: {totales['casos']} de {en_bateria} casos de la batería."]
    return lineas


def markdown(carpeta: Path) -> str:
    """Sección de resultados lista para pegar en la documentación."""
    corridas = _leer(carpeta) if carpeta.is_dir() else []
    del_recuperador = [c for c in corridas if c.get("tipo") == "recuperador"]
    del_asistente = [c for c in corridas if c.get("tipo") == "asistente"]
    lineas: list[str] = ["## Resultados de evaluación", ""]
    for corrida in del_recuperador:
        lineas += [*_tabla_recuperador(corrida), ""]
    if not del_asistente:
        lineas += ["### Asistente", "", SIN_CORRIDAS_DEL_ASISTENTE, ""]
    for corrida in del_asistente:
        lineas += [*_tabla_asistente(corrida), ""]
    return "\n".join(lineas).rstrip() + "\n"
