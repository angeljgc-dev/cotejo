"""Generador mínimo de PDF, sin dependencias, para los documentos de demostración y las pruebas.

Produce tres clases de archivo: páginas de texto, páginas con una imagen y sin texto (como un escaneo), y
texto con un párrafo invisible (blanco sobre blanco y diminuto), que es la forma habitual de esconder una
instrucción en un PDF. No pretende ser un generador general: letra Helvetica, tamaño carta, texto corrido.
"""

from __future__ import annotations

import textwrap
import zlib
from collections.abc import Mapping, Sequence

ANCHO, ALTO = 612, 792
MARGEN = 72
TAMANO_LETRA = 11
INTERLINEADO = 14
COLUMNAS = 82
LINEAS_POR_PAGINA = (ALTO - 2 * MARGEN) // INTERLINEADO


def _escapar(texto: str) -> bytes:
    # WinAnsi (cp1252) cubre los acentos y la ñ del español con la letra estándar Helvetica.
    crudo = texto.encode("cp1252", errors="replace")
    return crudo.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _lineas(texto: str) -> list[str]:
    lineas: list[str] = []
    for parrafo in texto.split("\n"):
        lineas.extend(textwrap.wrap(parrafo, COLUMNAS) or [""])
    return lineas


def _contenido_texto(texto: str, oculto: str | None) -> bytes:
    lineas = _lineas(texto)
    if len(lineas) > LINEAS_POR_PAGINA:
        raise ValueError(f"El texto ocupa {len(lineas)} líneas y en una página caben {LINEAS_POR_PAGINA}.")
    partes = [b"BT", f"/F1 {TAMANO_LETRA} Tf {INTERLINEADO} TL {MARGEN} {ALTO - MARGEN} Td".encode()]
    for linea in lineas:
        partes.append(b"(" + _escapar(linea) + b") Tj T*")
    partes.append(b"ET")
    if oculto:
        # Blanco sobre blanco y a 1 punto: una persona no lo ve, un extractor de texto sí.
        partes.append(b"BT 1 1 1 rg /F1 1 Tf 1.2 TL " + f"{MARGEN} {MARGEN // 2} Td".encode())
        for linea in textwrap.wrap(oculto, 400):
            partes.append(b"(" + _escapar(linea) + b") Tj T*")
        partes.append(b"ET")
    return b"\n".join(partes)


def _armar(objetos: list[bytes]) -> bytes:
    salida = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    posiciones: list[int] = []
    for numero, cuerpo in enumerate(objetos, start=1):
        posiciones.append(len(salida))
        salida += f"{numero} 0 obj\n".encode() + cuerpo + b"\nendobj\n"
    inicio_xref = len(salida)
    salida += f"xref\n0 {len(objetos) + 1}\n".encode() + b"0000000000 65535 f \n"
    for posicion in posiciones:
        salida += f"{posicion:010d} 00000 n \n".encode()
    salida += f"trailer\n<< /Size {len(objetos) + 1} /Root 1 0 R >>\nstartxref\n{inicio_xref}\n%%EOF\n".encode()
    return bytes(salida)


def _flujo(datos: bytes, extra: str = "") -> bytes:
    comprimido = zlib.compress(datos)
    return (
        f"<< /Length {len(comprimido)} /Filter /FlateDecode {extra}>>\nstream\n".encode() + comprimido + b"\nendstream"
    )


def pdf_de_texto(paginas: Sequence[str], *, oculto: Mapping[int, str] | None = None) -> bytes:
    """PDF con una página por elemento. `oculto` agrega texto invisible a la página indicada (desde 1)."""
    oculto = oculto or {}
    # Objetos: 1 catálogo, 2 árbol de páginas, 3 letra, y por cada página su objeto y su contenido.
    numeros_pagina = [4 + 2 * i for i in range(len(paginas))]
    hijos = " ".join(f"{n} 0 R" for n in numeros_pagina)
    objetos = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{hijos}] /Count {len(paginas)} >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    for indice, texto in enumerate(paginas, start=1):
        numero = numeros_pagina[indice - 1]
        objetos.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {ANCHO} {ALTO}] "
                f"/Resources << /Font << /F1 3 0 R >> >> /Contents {numero + 1} 0 R >>"
            ).encode()
        )
        objetos.append(_flujo(_contenido_texto(texto, oculto.get(indice))))
    return _armar(objetos)


def _imagen_de_renglones(ancho: int, alto: int) -> bytes:
    """Mapa de grises que imita renglones de texto escaneado: franjas oscuras sobre fondo claro."""
    filas = bytearray()
    for y in range(alto):
        en_renglon = 20 <= y < alto - 20 and (y // 6) % 3 == 0
        for x in range(ancho):
            tinta = en_renglon and 16 <= x < ancho - 16 and (x * 7 + y * 3) % 11 < 8
            filas.append(60 if tinta else 245)
    return bytes(filas)


def pdf_escaneado(paginas: int = 1) -> bytes:
    """PDF cuyas páginas son solo una imagen: no hay texto que extraer, como en un documento escaneado."""
    ancho, alto = 204, 264
    imagen = _flujo(
        _imagen_de_renglones(ancho, alto),
        f"/Type /XObject /Subtype /Image /Width {ancho} /Height {alto} /ColorSpace /DeviceGray /BitsPerComponent 8 ",
    )
    numeros_pagina = [4 + 2 * i for i in range(paginas)]
    hijos = " ".join(f"{n} 0 R" for n in numeros_pagina)
    objetos = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{hijos}] /Count {paginas} >>".encode(),
        imagen,
    ]
    for numero in numeros_pagina:
        objetos.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {ANCHO} {ALTO}] "
                f"/Resources << /XObject << /Im1 3 0 R >> >> /Contents {numero + 1} 0 R >>"
            ).encode()
        )
        objetos.append(_flujo(f"q {ANCHO} 0 0 {ALTO} 0 0 cm /Im1 Do Q".encode()))
    return _armar(objetos)
