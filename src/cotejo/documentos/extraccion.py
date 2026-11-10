"""Extracción de texto por página de PDF, TXT y MD (C1, C3).

Un PDF sin texto extraíble no es un error: se devuelve marcado como `sin_texto` con una explicación para la
persona que lo subió. Solo se rechaza lo que no se puede leer en absoluto.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass

from pypdf import PdfReader
from pypdf.errors import DependencyError

from cotejo.documentos.normalizar import quitar_controles

MAX_PAGINAS = 300
MAX_CARACTERES = 2_000_000
# Menos que esto en todo el documento se considera ruido de un escaneo, no texto.
MIN_CARACTERES_UTILES = 20

EXPLICACION_ESCANEADO = (
    "El PDF no tiene texto extraíble (probablemente es una imagen escaneada). Cotejo v1 no hace OCR."
)
EXPLICACION_PROTEGIDO = "El PDF está protegido con contraseña."
EXPLICACION_VACIO = "El archivo no contiene texto."
_CIERRES = ".:;?!"

# pypdf avisa por logging de cada objeto dañado; con archivos de terceros eso solo es ruido.
logging.getLogger("pypdf").setLevel(logging.ERROR)


class DocumentoRechazado(Exception):
    """El archivo no se puede leer como documento."""

    def __init__(self, codigo: str, mensaje: str) -> None:
        super().__init__(mensaje)
        self.codigo = codigo
        self.mensaje = mensaje


@dataclass(frozen=True)
class TextoExtraido:
    """Texto por página. `paginas[i]` es la página i + 1; una página sin texto queda como cadena vacía."""

    paginas: tuple[str, ...]
    explicacion_sin_texto: str | None = None

    @property
    def sin_texto(self) -> bool:
        return self.explicacion_sin_texto is not None

    @property
    def paginas_con_texto(self) -> list[int]:
        return [i for i, texto in enumerate(self.paginas, start=1) if texto.strip()]


def unir_renglones(texto: str) -> str:
    """Rehace los párrafos de una página de PDF, donde cada renglón impreso llega como una línea aparte.

    Un renglón que no termina en signo de cierre continúa en el siguiente; así una frase no queda partida a
    media oración y se puede buscar y citar completa.
    """
    parrafos: list[str] = []
    actual: list[str] = []
    for renglon in texto.splitlines():
        limpio = renglon.strip()
        if not limpio:
            if actual:
                parrafos.append(" ".join(actual))
                actual = []
            continue
        actual.append(limpio)
        if limpio[-1] in _CIERRES:
            parrafos.append(" ".join(actual))
            actual = []
    if actual:
        parrafos.append(" ".join(actual))
    return "\n".join(parrafos)


def _caracteres_utiles(paginas: list[str]) -> int:
    return sum(len("".join(p.split())) for p in paginas)


def _extraer_pdf(contenido: bytes) -> TextoExtraido:
    try:
        lector = PdfReader(io.BytesIO(contenido))
        if lector.is_encrypted and not lector.decrypt(""):
            return TextoExtraido(paginas=(), explicacion_sin_texto=EXPLICACION_PROTEGIDO)
        total = len(lector.pages)
        if total > MAX_PAGINAS:
            raise DocumentoRechazado("DEMASIADAS_PAGINAS", f"El PDF tiene {total} páginas; el máximo es {MAX_PAGINAS}.")
        paginas: list[str] = []
        acumulado = 0
        for pagina in lector.pages:
            texto = unir_renglones(quitar_controles(pagina.extract_text() or ""))
            acumulado += len(texto)
            if acumulado > MAX_CARACTERES:
                raise DocumentoRechazado(
                    "DOCUMENTO_DEMASIADO_LARGO",
                    f"El documento rebasa el máximo de {MAX_CARACTERES:,} caracteres de texto.",
                )
            paginas.append(texto)
    except DocumentoRechazado:
        raise
    except DependencyError:
        # Cifrado que pypdf no puede abrir sin bibliotecas adicionales: para la persona es un PDF protegido.
        return TextoExtraido(paginas=(), explicacion_sin_texto=EXPLICACION_PROTEGIDO)
    except Exception as exc:
        # Con archivos dañados pypdf lanza de todo (también NotImplementedError o AttributeError): cualquier
        # falla al leer es un PDF ilegible para la persona, y no debe tumbar la carga de los demás archivos.
        raise DocumentoRechazado("PDF_ILEGIBLE", "El PDF está dañado o no se pudo leer.") from exc
    if _caracteres_utiles(paginas) < MIN_CARACTERES_UTILES:
        return TextoExtraido(paginas=tuple("" for _ in paginas), explicacion_sin_texto=EXPLICACION_ESCANEADO)
    return TextoExtraido(paginas=tuple(paginas))


def _extraer_texto_plano(contenido: bytes) -> TextoExtraido:
    try:
        texto = contenido.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DocumentoRechazado(
            "TEXTO_NO_UTF8", "El archivo de texto no está en UTF-8. Guárdalo como UTF-8 y vuelve a subirlo."
        ) from exc
    if len(texto) > MAX_CARACTERES:
        raise DocumentoRechazado(
            "DOCUMENTO_DEMASIADO_LARGO", f"El documento rebasa el máximo de {MAX_CARACTERES:,} caracteres de texto."
        )
    texto = quitar_controles(texto)
    if not texto.strip():
        return TextoExtraido(paginas=("",), explicacion_sin_texto=EXPLICACION_VACIO)
    return TextoExtraido(paginas=(texto,))


def extraer(tipo: str, contenido: bytes) -> TextoExtraido:
    """Texto por página de un archivo `pdf`, `txt` o `md`. TXT y MD cuentan como una sola página."""
    if tipo == "pdf":
        return _extraer_pdf(contenido)
    if tipo in ("txt", "md"):
        return _extraer_texto_plano(contenido)
    raise DocumentoRechazado("TIPO_NO_PERMITIDO", f"Tipo de documento no permitido: {tipo}.")
