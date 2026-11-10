"""Cliente guionado: sustituye al modelo de lenguaje en pruebas y en el ensayo de la evaluación (E1).

Solo se sustituye el modelo. El bucle, la validación de argumentos, las herramientas, las barreras y la
verificación que corren con él son los reales. Un paso puede ser una función de los mensajes recibidos, para
que el guion lea el resultado de la herramienta anterior (por ejemplo, tomar un `fragmento_id` y citarlo).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from cotejo.asistente.cliente_modelo import (
    ErrorModelo,
    EsquemaHerramienta,
    LlamadaHerramienta,
    MensajeModelo,
    RespuestaModelo,
)


@dataclass
class PasoGuion:
    """Lo que "responde el modelo" en una llamada: herramientas que pide, texto final o una falla del proveedor."""

    # (herramienta, argumentos). Los argumentos como texto se mandan tal cual, para probar JSON inválido.
    llamadas: list[tuple[str, Mapping[str, object] | str]] = field(default_factory=list)
    texto: str | None = None
    error: ErrorModelo | None = None


Paso = PasoGuion | Callable[[Sequence[MensajeModelo]], PasoGuion]


class ClienteGuionado:
    """Implementa ClienteModelo devolviendo los pasos en orden. Agotado el guion, repite el último paso."""

    def __init__(self, pasos: Sequence[Paso], modelo: str = "guionado") -> None:
        if not pasos:
            raise ValueError("El guion necesita al menos un paso.")
        self.modelo = modelo
        self._pasos = list(pasos)
        self._indice = 0
        # Lo que el bucle mandó en cada llamada, para afirmar sobre ello en las pruebas.
        self.recibidos: list[list[MensajeModelo]] = []
        self.herramientas_ofrecidas: list[list[str]] = []

    def completar(
        self, mensajes: Sequence[MensajeModelo], herramientas: Sequence[EsquemaHerramienta]
    ) -> RespuestaModelo:
        self.recibidos.append(list(mensajes))
        self.herramientas_ofrecidas.append([h.nombre for h in herramientas])
        paso = self._pasos[min(self._indice, len(self._pasos) - 1)]
        numero = self._indice
        self._indice += 1
        if not isinstance(paso, PasoGuion):
            paso = paso(mensajes)
        if paso.error is not None:
            raise paso.error
        llamadas = [
            LlamadaHerramienta(
                id=f"llamada_{numero}_{i}",
                nombre=nombre,
                argumentos_json=argumentos
                if isinstance(argumentos, str)
                else json.dumps(argumentos, ensure_ascii=False),
            )
            for i, (nombre, argumentos) in enumerate(paso.llamadas)
        ]
        return RespuestaModelo(
            texto=paso.texto, llamadas=llamadas, modelo=self.modelo, tokens_entrada=100, tokens_salida=20
        )


def resultados_de_herramientas(mensajes: Sequence[MensajeModelo]) -> list[dict[str, object]]:
    """Resultados de herramienta que el bucle devolvió al modelo, ya decodificados, en orden."""
    resultados: list[dict[str, object]] = []
    for mensaje in mensajes:
        if mensaje.rol == "tool" and mensaje.contenido:
            dato = json.loads(mensaje.contenido)
            if isinstance(dato, dict):
                resultados.append(dato)
    return resultados
