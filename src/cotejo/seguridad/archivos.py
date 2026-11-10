"""Lectura segura de archivos subidos (A6): extensión permitida, tamaño acotado y firma mínima.

El contenido se lee en bloques hasta `límite + 1` bytes para cortar sin cargar archivos enormes en memoria.
El nombre del archivo solo se muestra; nunca se usa como ruta.
"""

from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath

from fastapi import UploadFile

TAMANO_BLOQUE = 64 * 1024
LARGO_MAXIMO_NOMBRE = 255

EXTENSIONES_CFDI = frozenset({".xml"})
EXTENSIONES_DOCUMENTO = frozenset({".pdf", ".txt", ".md"})
EXTENSIONES_LISTA_69B = frozenset({".csv"})


@dataclass(frozen=True)
class ArchivoSubido:
    nombre: str
    extension: str
    contenido: bytes
    sha256: str


class ArchivoRechazado(Exception):
    def __init__(self, codigo: str, mensaje: str, nombre: str = "") -> None:
        super().__init__(mensaje)
        self.codigo = codigo
        self.mensaje = mensaje
        self.nombre = nombre


def nombre_para_mostrar(nombre: str | None) -> str:
    """Último componente del nombre, sin caracteres de control y recortado."""
    base = PureWindowsPath(PurePosixPath(nombre or "").name).name
    limpio = "".join(c for c in base if unicodedata.category(c)[0] != "C").strip()
    return limpio[:LARGO_MAXIMO_NOMBRE] or "sin_nombre"


def _mb(limite_bytes: int) -> str:
    return f"{limite_bytes / (1024 * 1024):g} MB"


async def leer_subida(archivo: UploadFile, permitidas: frozenset[str], limite_bytes: int) -> ArchivoSubido:
    nombre = nombre_para_mostrar(archivo.filename)
    extension = PurePosixPath(nombre.lower()).suffix
    if extension not in permitidas:
        opciones = ", ".join(sorted(permitidas))
        raise ArchivoRechazado(
            "EXTENSION_NO_PERMITIDA", f"El archivo {nombre} no tiene una extensión permitida ({opciones}).", nombre
        )
    bloques: list[bytes] = []
    leidos = 0
    while leidos <= limite_bytes:
        bloque = await archivo.read(min(TAMANO_BLOQUE, limite_bytes + 1 - leidos))
        if not bloque:
            break
        bloques.append(bloque)
        leidos += len(bloque)
    if leidos > limite_bytes:
        raise ArchivoRechazado(
            "ARCHIVO_DEMASIADO_GRANDE", f"El archivo {nombre} rebasa el límite de {_mb(limite_bytes)}.", nombre
        )
    contenido = b"".join(bloques)
    if not contenido:
        raise ArchivoRechazado("ARCHIVO_VACIO", f"El archivo {nombre} está vacío.", nombre)
    if extension == ".pdf" and not contenido.startswith(b"%PDF-"):
        raise ArchivoRechazado("FIRMA_INVALIDA", f"El archivo {nombre} no es un PDF válido.", nombre)
    return ArchivoSubido(
        nombre=nombre, extension=extension, contenido=contenido, sha256=hashlib.sha256(contenido).hexdigest()
    )
