"""Bucle de herramientas del asistente: el modelo pide herramientas, el código las valida y ejecuta.

Límites duros para que una pregunta no consuma la cuota del proveedor: llamadas al modelo, llamadas a
herramientas, tiempo total y tamaño de cada resultado. Lo que el modelo pide nunca se ejecuta sin validar: una
herramienta desconocida o con argumentos inválidos recibe un error y la conversación sigue.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from pydantic import ValidationError

from cotejo.asistente import verificacion
from cotejo.asistente.cliente_modelo import ClienteModelo, LlamadaHerramienta, MensajeModelo
from cotejo.asistente.herramientas import (
    HERRAMIENTA_QUE_ESCRIBE,
    HERRAMIENTAS,
    ContextoHerramienta,
    ErrorHerramienta,
    Json,
    herramientas_para,
)
from cotejo.asistente.prompt import prompt_de_sistema

_log = logging.getLogger("cotejo.asistente")

MAX_LLAMADAS_MODELO = 6
MAX_LLAMADAS_HERRAMIENTA = 10
TIEMPO_TOTAL_S = 75.0
MAX_CARACTERES_RESULTADO = 8000
TEXTO_LIMITE_PASOS = "No pude completar la consulta; intenta con una pregunta más concreta."
TEXTO_SIN_RESPUESTA = "No obtuve una respuesta del modelo para esta pregunta. Intenta formularla de otra manera."


@dataclass(frozen=True)
class UsoHerramienta:
    """Una llamada a herramienta tal como ocurrió: lo que pidió el modelo y lo que se le devolvió."""

    nombre: str
    argumentos: Json
    resultado: Json
    error: str | None
    duracion_ms: int


@dataclass
class ResultadoBucle:
    texto: str
    modelo: str
    herramientas: list[UsoHerramienta] = field(default_factory=list)
    factura_ids: list[int] = field(default_factory=list)
    # fragmento_id -> (documento_id, nombre del documento, página), solo de fragmentos devueltos en este turno.
    fragmentos: dict[int, tuple[int, str, int]] = field(default_factory=dict)
    citas: list[int] = field(default_factory=list)
    propuesta_id: int | None = None
    advertencias: list[dict[str, str]] = field(default_factory=list)
    pasos: int = 0
    tokens_entrada: int = 0
    tokens_salida: int = 0


def a_json_compacto(dato: object) -> str:
    return json.dumps(dato, ensure_ascii=False, separators=(",", ":"))


def recortar(datos: Json, limite: int = MAX_CARACTERES_RESULTADO) -> Json:
    """Acota un resultado al tamaño máximo quitando elementos del final de su lista más larga.

    El resultado recortado sigue siendo JSON válido y lleva `recortado: true`, para que el modelo sepa que no
    vio todo. Las cifras totales no se pierden: vienen en campos propios, fuera de las listas.
    """
    if len(a_json_compacto(datos)) <= limite:
        return datos
    recortado: Json = dict(datos)
    recortado["recortado"] = True
    while len(a_json_compacto(recortado)) > limite:
        listas = [(len(v), k) for k, v in recortado.items() if isinstance(v, list) and v]
        if not listas:
            break
        _, clave = max(listas)
        lista = recortado[clave]
        if isinstance(lista, list):
            recortado[clave] = lista[: max(len(lista) - 1 - len(lista) // 4, 0)]
    if len(a_json_compacto(recortado)) > limite:
        return {"recortado": True, "error": "El resultado es demasiado grande; pide menos elementos."}
    return recortado


def _argumentos(llamada: LlamadaHerramienta) -> Json | str:
    """Argumentos decodificados, o un mensaje de error si el modelo no mandó un objeto JSON."""
    crudo = llamada.argumentos_json.strip() or "{}"
    try:
        dato = json.loads(crudo)
    except json.JSONDecodeError:
        return "Los argumentos no son JSON válido."
    if not isinstance(dato, dict):
        return "Los argumentos deben ser un objeto JSON."
    return dato


def _error_de_validacion(exc: ValidationError) -> str:
    partes = []
    for error in exc.errors(include_url=False, include_input=False)[:5]:
        campo = ".".join(str(p) for p in error["loc"]) or "argumentos"
        partes.append(f"{campo}: {error['msg']}")
    return "Argumentos inválidos. " + "; ".join(partes)


@dataclass
class _Turno:
    ctx: ContextoHerramienta
    resultado: ResultadoBucle
    llamadas_herramienta: int = 0

    def ejecutar(self, llamada: LlamadaHerramienta) -> Json:
        """Valida y ejecuta una llamada. Siempre devuelve un objeto JSON para el modelo; nunca lanza."""
        inicio = time.perf_counter()
        argumentos = _argumentos(llamada)
        datos, error = self._ejecutar_validada(llamada.nombre, argumentos)
        enviado = recortar(datos)
        self.resultado.herramientas.append(
            UsoHerramienta(
                nombre=llamada.nombre[:80],
                argumentos=argumentos if isinstance(argumentos, dict) else {"_crudo": llamada.argumentos_json[:500]},
                resultado=enviado,
                error=error,
                duracion_ms=int((time.perf_counter() - inicio) * 1000),
            )
        )
        return enviado

    def _ejecutar_validada(self, nombre: str, argumentos: Json | str) -> tuple[Json, str | None]:
        self.llamadas_herramienta += 1
        if self.llamadas_herramienta > MAX_LLAMADAS_HERRAMIENTA:
            return self._error("Se alcanzó el máximo de herramientas por pregunta. Responde con lo que ya tienes.")
        herramienta = HERRAMIENTAS.get(nombre)
        if herramienta is None:
            return self._error(f"La herramienta no existe. Disponibles: {', '.join(HERRAMIENTAS)}.")
        if isinstance(argumentos, str):
            return self._error(argumentos)
        if nombre == HERRAMIENTA_QUE_ESCRIBE and self.resultado.propuesta_id is not None:
            return self._error(
                f"Ya se creó la propuesta {self.resultado.propuesta_id} en esta respuesta; no se crea otra."
            )
        try:
            # Savepoint por herramienta: si falla, lo que haya escrito se deshace y la transacción sigue sana.
            with self.ctx.sesion.begin_nested():
                salida = herramienta.ejecutar(self.ctx, argumentos)
        except ValidationError as exc:
            return self._error(_error_de_validacion(exc))
        except ErrorHerramienta as exc:
            return {"error": exc.mensaje, **exc.detalle}, exc.mensaje
        except Exception:
            _log.exception("La herramienta %s falló de forma inesperada.", nombre)
            return self._error("La herramienta falló. Intenta con otros argumentos.")
        for factura_id in salida.factura_ids:
            if factura_id not in self.resultado.factura_ids:
                self.resultado.factura_ids.append(factura_id)
        self.resultado.fragmentos.update(salida.fragmentos)
        if salida.propuesta_id is not None:
            self.resultado.propuesta_id = salida.propuesta_id
        return salida.datos, None

    @staticmethod
    def _error(mensaje: str) -> tuple[Json, str]:
        return {"error": mensaje}, mensaje


def _verificar(resultado: ResultadoBucle) -> None:
    """Quita citas a fragmentos que no se devolvieron en el turno y marca cifras sin respaldo."""
    citas = verificacion.revisar_citas(resultado.texto, resultado.fragmentos)
    resultado.texto = citas.texto
    resultado.citas = list(citas.validas)
    if citas.invalidas:
        resultado.advertencias.append(
            verificacion.advertencia(
                verificacion.CITA_INVALIDA,
                "Se quitaron citas a fragmentos que no se consultaron en esta respuesta.",
            )
        )
    faltantes = verificacion.cifras_no_respaldadas(
        resultado.texto, [u.resultado for u in resultado.herramientas], resultado.citas
    )
    if faltantes:
        resultado.advertencias.append(
            verificacion.advertencia(
                verificacion.CIFRA_NO_RESPALDADA,
                "Estas cifras no provienen de ninguna consulta de esta respuesta y pueden ser incorrectas: "
                + ", ".join(faltantes[:8])
                + ".",
            )
        )


def ejecutar(
    cliente: ClienteModelo,
    ctx: ContextoHerramienta,
    *,
    pregunta: str,
    historial: Sequence[MensajeModelo] = (),
    reloj: Callable[[], float] = time.monotonic,
) -> ResultadoBucle:
    """Responde una pregunta. Lanza `ErrorModelo` si el proveedor falla; quien llama decide qué deshacer."""
    herramientas = herramientas_para(ctx.usuario)
    esquemas = [h.esquema for h in herramientas]
    mensajes: list[MensajeModelo] = [
        MensajeModelo("system", prompt_de_sistema(ctx.config.empresa_nombre, ctx.hoy, ctx.usuario.rol)),
        *historial,
        MensajeModelo("user", pregunta),
    ]
    resultado = ResultadoBucle(texto="", modelo=cliente.modelo)
    turno = _Turno(ctx=ctx, resultado=resultado)
    inicio = reloj()
    texto_final: str | None = None
    while resultado.pasos < MAX_LLAMADAS_MODELO and reloj() - inicio < TIEMPO_TOTAL_S:
        respuesta = cliente.completar(mensajes, esquemas)
        resultado.pasos += 1
        resultado.modelo = respuesta.modelo or resultado.modelo
        resultado.tokens_entrada += respuesta.tokens_entrada or 0
        resultado.tokens_salida += respuesta.tokens_salida or 0
        if not respuesta.llamadas:
            texto_final = (respuesta.texto or "").strip() or TEXTO_SIN_RESPUESTA
            break
        mensajes.append(MensajeModelo("assistant", respuesta.texto, llamadas=tuple(respuesta.llamadas)))
        for llamada in respuesta.llamadas:
            enviado = turno.ejecutar(llamada)
            mensajes.append(MensajeModelo("tool", a_json_compacto(enviado), llamada_id=llamada.id))
    if texto_final is None:
        resultado.texto = TEXTO_LIMITE_PASOS
        resultado.advertencias.append(
            verificacion.advertencia(
                verificacion.LIMITE_PASOS, "La consulta necesitó demasiados pasos y se detuvo antes de terminar."
            )
        )
        return resultado
    resultado.texto = texto_final
    _verificar(resultado)
    return resultado


def resultados_por_nombre(usos: Sequence[UsoHerramienta]) -> Mapping[str, list[Json]]:
    """Resultados agrupados por herramienta; útil para calificar una respuesta por lo que consultó."""
    agrupados: dict[str, list[Json]] = {}
    for uso in usos:
        agrupados.setdefault(uso.nombre, []).append(uso.resultado)
    return agrupados
