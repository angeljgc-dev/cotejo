"""Evaluación de Cotejo desde la terminal.

    python -m cotejo.evaluacion recuperador [--salida eval/resultados]
    python -m cotejo.evaluacion asistente   [--salida eval/resultados] [--solo id,id] [--archivo corrida.json]
    python -m cotejo.evaluacion publicar    [--resultados eval/resultados]

`recuperador` no usa modelo de lenguaje: indexa los documentos de demostración dentro de una transacción que se
revierte y mide la búsqueda. `asistente` necesita LLM_API_KEY y una base desechable (la reinicia en cada caso).
`publicar` imprime en Markdown las tablas de los resultados guardados, tal cual salieron.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session, sessionmaker

from cotejo.asistente.cliente_modelo import cliente_de_config
from cotejo.config import Settings
from cotejo.db import crear_motor
from cotejo.documentos.embeddings import obtener_embedder
from cotejo.evaluacion import casos as casos_asistente
from cotejo.evaluacion import ejecutor, publicacion, recuperador

CARPETA_RESULTADOS = Path("eval") / "resultados"


def _escribir(texto: str) -> None:
    sys.stdout.write(texto + "\n")


def _nombre_seguro(texto: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", texto).strip("-").lower() or "modelo"


def _url_de_base(config: Settings) -> str | None:
    if config.database_url is None:
        sys.stderr.write("Falta DATABASE_URL: la evaluación necesita una base PostgreSQL con pgvector.\n")
        return None
    return config.database_url.get_secret_value()


def _hoy(config: Settings) -> str:
    return datetime.now(ZoneInfo(config.zona_horaria)).date().isoformat()


def correr_recuperador(config: Settings, salida: Path | None) -> int:
    url = _url_de_base(config)
    if url is None:
        return 2
    motor = crear_motor(url)
    try:
        with Session(motor) as sesion:
            resultado = recuperador.evaluar_documentos_demo(
                sesion, obtener_embedder(config), recuperador.cargar_casos()
            )
            # Los documentos se indexaron solo para medir: nada queda en la base.
            sesion.rollback()
    finally:
        motor.dispose()
    resultado = {
        "tipo": "recuperador",
        "fecha": _hoy(config),
        "archivo_del_modelo": config.embeddings_archivo,
        "busqueda_modo": config.busqueda_modo,
        **resultado,
    }
    _escribir(recuperador.tabla(resultado))
    if salida is not None:
        salida.mkdir(parents=True, exist_ok=True)
        ruta = salida / f"recuperador_{resultado['fecha']}_{_nombre_seguro(str(resultado['embeddings']))}.json"
        ruta.write_text(json.dumps(resultado, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        _escribir(f"Resultado guardado en {ruta}")
    return 0


def correr_asistente(config: Settings, salida: Path, solo: list[str], archivo: Path | None) -> int:
    cliente = cliente_de_config(config)
    if cliente is None:
        sys.stderr.write(
            "Falta LLM_API_KEY: la batería del asistente se corre con un modelo real. "
            "Configura LLM_BASE_URL, LLM_MODELO y LLM_API_KEY.\n"
        )
        return 2
    url = _url_de_base(config)
    if url is None:
        return 2
    if not ejecutor.es_base_desechable(url):
        sys.stderr.write(
            'La evaluación reinicia la base en cada caso. Solo corre contra una base cuyo nombre contenga "eval" '
            'o "test".\n'
        )
        return 2
    casos = casos_asistente.cargar_casos()
    if solo:
        casos = [c for c in casos if c.id in solo]
    fecha = _hoy(config)
    ruta = archivo or salida / f"{fecha}_{_nombre_seguro(cliente.modelo)}.json"
    previos = ejecutor.leer_corrida(ruta)
    motor = crear_motor(url)
    fabrica = sessionmaker(bind=motor, expire_on_commit=False)

    def avisar(resultado: ejecutor.ResultadoCaso) -> None:
        estado = "ERROR" if resultado.error else ("pasa" if resultado.pasa else "FALLA")
        fallas = [str(c["nombre"]) for c in resultado.comprobaciones if not c["pasa"]]
        _escribir(f"{resultado.id:<12} {estado:<6} {resultado.error or ', '.join(fallas)}")

    try:
        resultados = ejecutor.ejecutar_bateria(
            fabrica,
            casos,
            cliente,
            config,
            ruta_salida=ruta,
            fecha=datetime.now(ZoneInfo(config.zona_horaria)).date(),
            pausa_s=config.eval_pausa_s,
            previos=previos,
            avisar=avisar,
        )
    finally:
        motor.dispose()
    resumen = ejecutor.totales(resultados)
    _escribir(f"{resumen['aprobados']} de {resumen['casos']} casos aprobados; {resumen['con_error']} con error.")
    _escribir(f"Resultado guardado en {ruta}")
    return 0


def publicar(carpeta: Path) -> int:
    _escribir(publicacion.markdown(carpeta))
    return 0


def main(argumentos: list[str] | None = None) -> int:
    analizador = argparse.ArgumentParser(prog="python -m cotejo.evaluacion", description="Evaluación de Cotejo.")
    comandos = analizador.add_subparsers(dest="comando", required=True)
    rec = comandos.add_parser("recuperador", help="recall@5 y MRR de la búsqueda, sin modelo de lenguaje")
    rec.add_argument("--salida", type=Path, default=None, help="carpeta donde guardar el resultado en JSON")
    asi = comandos.add_parser("asistente", help="batería del asistente con el modelo real")
    asi.add_argument("--salida", type=Path, default=CARPETA_RESULTADOS)
    asi.add_argument("--solo", default="", help="ids de casos separados por coma")
    asi.add_argument("--archivo", type=Path, default=None, help="archivo de corrida que se reanuda o se crea")
    pub = comandos.add_parser("publicar", help="tablas en Markdown de los resultados guardados")
    pub.add_argument("--resultados", type=Path, default=CARPETA_RESULTADOS)
    opciones = analizador.parse_args(argumentos)
    config = Settings()
    if opciones.comando == "recuperador":
        return correr_recuperador(config, opciones.salida)
    if opciones.comando == "asistente":
        solo = [s.strip() for s in str(opciones.solo).split(",") if s.strip()]
        return correr_asistente(config, opciones.salida, solo, opciones.archivo)
    return publicar(opciones.resultados)


if __name__ == "__main__":
    raise SystemExit(main())
