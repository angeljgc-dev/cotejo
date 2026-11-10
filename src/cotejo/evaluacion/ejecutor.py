"""Ejecutor de la batería del asistente (E2).

Cada caso empieza con la base recién sembrada y la fecha fija, se pregunta por el mismo servicio que usa la API
y se califica por hechos. El resultado se guarda tal cual salga, caso por caso, para poder reanudar: las cuotas
gratuitas de los proveedores de modelos son bajas y una corrida puede repartirse en varios días.

Reiniciar la base borra todos los datos de negocio. Por eso solo corre contra una base desechable, cuyo nombre
contenga "eval" o "test".
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

from sqlalchemy import make_url, select
from sqlalchemy.orm import Session

from cotejo.api.dependencias import Visitante
from cotejo.asistente import servicio
from cotejo.asistente.cliente_modelo import ClienteModelo
from cotejo.asistente.prompt import VERSION_PROMPT
from cotejo.config import Settings
from cotejo.evaluacion import calificador
from cotejo.evaluacion.casos import CasoAsistente
from cotejo.modelos import Usuario
from cotejo.semilla.generador import reiniciar_demo

FECHA_DE_EVALUACION = date(2026, 11, 2)
VISITANTE = Visitante(visitante="evaluacion", ip_hash="evaluacion")
SIN_LIMITE = 1_000_000

AbrirSesion = Callable[[], AbstractContextManager[Session]]


@dataclass
class ResultadoCaso:
    id: str
    categoria: str
    pregunta: str
    pasa: bool
    comprobaciones: list[dict[str, object]] = field(default_factory=list)
    texto: str = ""
    herramientas: list[dict[str, object]] = field(default_factory=list)
    advertencias: list[str] = field(default_factory=list)
    citas: list[dict[str, object]] = field(default_factory=list)
    propuesta_id: int | None = None
    cifras_esperadas: dict[str, str] = field(default_factory=dict)
    modelo: str | None = None
    latencia_ms: int = 0
    error: str | None = None


class BaseNoDesechable(RuntimeError):
    """La batería reinicia la base: se niega a correr contra una que no esté marcada como de pruebas."""


def es_nombre_desechable(nombre: str | None) -> bool:
    """El nombre lleva la palabra eval o test como parte separada: cotejo_eval, cotejo_test_123, test."""
    return re.search(r"(^|[_-])(eval|test)([_-]|$)", (nombre or "").lower()) is not None


def es_base_desechable(url: str) -> bool:
    return es_nombre_desechable(make_url(url).database)


def exigir_base_desechable(sesion: Session) -> None:
    nombre = sesion.get_bind().engine.url.database
    if not es_nombre_desechable(nombre):
        raise BaseNoDesechable(
            f"La base «{nombre}» no es desechable: su nombre debe llevar eval o test como parte separada."
        )


def config_de_evaluacion(config: Settings) -> Settings:
    """Misma configuración con la fecha fija de la batería y sin cuota de chat (la evaluación no es un visitante)."""
    return config.model_copy(
        update={
            "fecha_hoy_fija": FECHA_DE_EVALUACION,
            "chat_limite_visitante_dia": SIN_LIMITE,
            "chat_limite_global_dia": SIN_LIMITE,
        }
    )


def ejecutar_caso(sesion: Session, caso: CasoAsistente, cliente: ClienteModelo, config: Settings) -> ResultadoCaso:
    """Reinicia la base, pregunta y califica. Confirma la transacción: el estado final queda para inspeccionarlo."""
    exigir_base_desechable(sesion)
    hoy = config.fecha_hoy_fija or FECHA_DE_EVALUACION
    reiniciar_demo(
        sesion,
        semilla=config.semilla,
        fecha_base=hoy,
        empresa_rfc=config.empresa_rfc,
        empresa_nombre=config.empresa_nombre,
    )
    sesion.commit()
    resultado = ResultadoCaso(id=caso.id, categoria=caso.categoria, pregunta=caso.pregunta, pasa=False)
    usuario = sesion.scalars(
        select(Usuario).where(Usuario.rol == caso.rol, Usuario.es_demo).order_by(Usuario.id)
    ).first()
    if usuario is None:
        resultado.error = f"No hay usuario de demostración con rol {caso.rol}."
        return resultado
    expectativa = calificador.preparar(sesion, caso, config, hoy)
    resultado.cifras_esperadas = {nombre: str(valor) for nombre, valor in expectativa.cifras}
    antes = calificador.huella(sesion)
    inicio = time.perf_counter()
    try:
        mensaje = servicio.responder(
            sesion,
            config=config,
            cliente=cliente,
            usuario=usuario,
            visitante=VISITANTE,
            conversacion_id=None,
            texto=caso.pregunta,
        )
        sesion.commit()
    except servicio.ErrorAsistente as exc:
        sesion.rollback()
        resultado.error = f"{exc.codigo}: {exc.mensaje}"
        resultado.latencia_ms = int((time.perf_counter() - inicio) * 1000)
        return resultado
    resultado.latencia_ms = int((time.perf_counter() - inicio) * 1000)
    calificacion = calificador.calificar(
        sesion, caso, mensaje, antes=antes, despues=calificador.huella(sesion), expectativa=expectativa, hoy=hoy
    )
    resultado.pasa = calificacion.pasa
    resultado.comprobaciones = [asdict(c) for c in calificacion.comprobaciones]
    resultado.texto = mensaje.texto
    resultado.herramientas = [
        {"nombre": h.nombre, "argumentos": h.argumentos, "resumen": h.resumen, "error": h.error}
        for h in mensaje.herramientas
    ]
    resultado.advertencias = [a.codigo for a in mensaje.advertencias]
    resultado.citas = [{"documento": c.documento, "pagina": c.pagina} for c in mensaje.citas]
    resultado.propuesta_id = mensaje.propuesta_id
    resultado.modelo = mensaje.modelo
    return resultado


def totales(resultados: Sequence[ResultadoCaso]) -> dict[str, object]:
    por_categoria: dict[str, dict[str, int]] = {}
    for r in resultados:
        grupo = por_categoria.setdefault(r.categoria, {"aprobados": 0, "total": 0, "con_error": 0})
        grupo["total"] += 1
        grupo["aprobados"] += int(r.pasa)
        grupo["con_error"] += int(r.error is not None)
    return {
        "casos": len(resultados),
        "aprobados": sum(r.pasa for r in resultados),
        "con_error": sum(r.error is not None for r in resultados),
        "por_categoria": por_categoria,
    }


def commit_actual(raiz: Path | None = None) -> str | None:
    """Identificador corto del commit en que se corrió, leído de la carpeta .git; None si no se puede saber."""
    git = (raiz or Path.cwd()) / ".git"
    try:
        cabeza = (git / "HEAD").read_text(encoding="utf-8").strip()
        if not cabeza.startswith("ref: "):
            return cabeza[:12]
        referencia = git / cabeza.removeprefix("ref: ")
        return referencia.read_text(encoding="utf-8").strip()[:12] if referencia.is_file() else None
    except OSError:
        return None


def leer_corrida(ruta: Path) -> list[ResultadoCaso]:
    """Resultados ya guardados de una corrida, para reanudarla."""
    if not ruta.is_file():
        return []
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    return [ResultadoCaso(**caso) for caso in datos.get("resultados", [])]


def guardar_corrida(ruta: Path, encabezado: dict[str, object], resultados: Sequence[ResultadoCaso]) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    contenido = {**encabezado, "totales": totales(resultados), "resultados": [asdict(r) for r in resultados]}
    ruta.write_text(json.dumps(contenido, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def encabezado_de(cliente: ClienteModelo, config: Settings, fecha: date, total_de_casos: int) -> dict[str, object]:
    return {
        "tipo": "asistente",
        "fecha": fecha.isoformat(),
        "modelo": cliente.modelo,
        # Solo la URL: la llave nunca se escribe.
        "url_base": config.llm_base_url,
        "version_prompt": VERSION_PROMPT,
        "commit": commit_actual(),
        "fecha_de_los_datos": FECHA_DE_EVALUACION.isoformat(),
        "semilla": config.semilla,
        "casos_en_la_bateria": total_de_casos,
    }


def ejecutar_bateria(
    abrir_sesion: AbrirSesion,
    casos: Sequence[CasoAsistente],
    cliente: ClienteModelo,
    config: Settings,
    *,
    ruta_salida: Path | None = None,
    fecha: date,
    pausa_s: float = 0.0,
    previos: Sequence[ResultadoCaso] = (),
    avisar: Callable[[ResultadoCaso], None] | None = None,
    dormir: Callable[[float], None] = time.sleep,
) -> list[ResultadoCaso]:
    """Corre los casos que falten y devuelve todos los resultados en el orden de la batería.

    Un caso ya guardado sin error no se repite; uno que falló por el proveedor (límite de uso, sin respuesta) sí.
    """
    config = config_de_evaluacion(config)
    hechos = {r.id: r for r in previos if r.error is None}
    encabezado = encabezado_de(cliente, config, fecha, len(casos))
    resultados: list[ResultadoCaso] = [hechos[c.id] for c in casos if c.id in hechos]
    primero = True
    for caso in casos:
        if caso.id in hechos:
            continue
        if not primero and pausa_s > 0:
            dormir(pausa_s)
        primero = False
        with abrir_sesion() as sesion:
            resultado = ejecutar_caso(sesion, caso, cliente, config)
        resultados.append(resultado)
        if avisar is not None:
            avisar(resultado)
        if ruta_salida is not None:
            orden = {c.id: i for i, c in enumerate(casos)}
            guardar_corrida(ruta_salida, encabezado, sorted(resultados, key=lambda r: orden[r.id]))
    orden = {c.id: i for i, c in enumerate(casos)}
    return sorted(resultados, key=lambda r: orden[r.id])
