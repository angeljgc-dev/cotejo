"""Normalización de texto para la búsqueda por palabras.

Sustituye a la extensión `unaccent`: el mismo resultado en local, en CI y en producción sin instalar nada en la
base. Se aplica igual al fragmento (columna `texto_normalizado`) y a la consulta, así "garantia" encuentra
"garantía". La ñ se conserva porque en español distingue palabras (año, ano).
"""

from __future__ import annotations

import re
import unicodedata

_TILDE_COMBINANTE = "\u0303"
_ESPACIOS = re.compile(r"\s+")


def normalizar(texto: str) -> str:
    """Minúsculas, sin acentos (salvo la ñ) y con los espacios colapsados."""
    descompuesto = unicodedata.normalize("NFKD", texto.lower())
    salida: list[str] = []
    for caracter in descompuesto:
        if unicodedata.combining(caracter):
            if caracter == _TILDE_COMBINANTE and salida and salida[-1] == "n":
                salida[-1] = "ñ"
            continue
        salida.append(caracter)
    return _ESPACIOS.sub(" ", "".join(salida)).strip()


def quitar_controles(texto: str) -> str:
    """Elimina caracteres de control y de formato invisibles; conserva saltos de línea y tabuladores."""
    return "".join(c for c in texto if c in "\n\t" or unicodedata.category(c) not in ("Cc", "Cf", "Cs", "Co", "Cn"))
