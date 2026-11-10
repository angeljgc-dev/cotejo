"""Partición del texto de una página en fragmentos con traslape.

Los fragmentos nunca cruzan de página porque la cita es documento y página. Se corta de preferencia en un fin
de párrafo, si no en un fin de oración y si no en un espacio, para que cada fragmento se lea completo.
"""

from __future__ import annotations

import re

OBJETIVO = 800
MAXIMO = 1000
TRASLAPE = 150
RESTO_MINIMO = 200

_FIN_ORACION = re.compile(r"[.!?;:](?=\s)")
_SALTOS_MULTIPLES = re.compile(r"\n{3,}")
_ESPACIOS_HORIZONTALES = re.compile(r"[ \t\r\f\v]+")


def limpiar_pagina(texto: str) -> str:
    """Unifica espacios sin perder los saltos de párrafo, que son los mejores puntos de corte."""
    lineas = [_ESPACIOS_HORIZONTALES.sub(" ", linea).strip() for linea in texto.replace("\r\n", "\n").split("\n")]
    return _SALTOS_MULTIPLES.sub("\n\n", "\n".join(lineas)).strip()


def _punto_de_corte(texto: str, inicio: int) -> int:
    """Índice (exclusivo) donde termina el fragmento que empieza en `inicio`."""
    limite = min(inicio + MAXIMO, len(texto))
    if limite == len(texto):
        return limite
    # Se busca desde la mitad del objetivo para no producir fragmentos diminutos.
    minimo = inicio + OBJETIVO // 2
    ventana = texto[minimo:limite]
    for separador in ("\n\n", "\n"):
        parrafo = ventana.rfind(separador)
        if parrafo != -1:
            return minimo + parrafo
    oraciones = list(_FIN_ORACION.finditer(ventana))
    if oraciones:
        return minimo + oraciones[-1].end()
    espacio = max(ventana.rfind(" "), ventana.rfind("\n"))
    if espacio != -1:
        return minimo + espacio
    return limite


def _inicio_con_traslape(texto: str, corte: int, inicio_anterior: int) -> int:
    """Retrocede hasta TRASLAPE caracteres y avanza al inicio de palabra para no partir una palabra."""
    candidato = max(corte - TRASLAPE, inicio_anterior + 1)
    while candidato < corte and not texto[candidato - 1].isspace():
        candidato += 1
    return candidato


def fragmentar_pagina(texto: str) -> list[str]:
    """Fragmentos de una página: objetivo 800 caracteres, máximo 1,000, traslape de 150.

    Un resto menor de 200 caracteres se une al fragmento anterior en lugar de quedar suelto.
    """
    limpio = limpiar_pagina(texto)
    if not limpio:
        return []
    fragmentos: list[str] = []
    inicio = 0
    while inicio < len(limpio):
        corte = _punto_de_corte(limpio, inicio)
        if len(limpio) - corte < RESTO_MINIMO:
            corte = len(limpio)
        pedazo = limpio[inicio:corte].strip()
        if pedazo:
            fragmentos.append(pedazo)
        if corte >= len(limpio):
            break
        inicio = _inicio_con_traslape(limpio, corte, inicio)
    return fragmentos
