"""Documentos ficticios de demostración: los genera (PDF) y los carga a la base.

Los PDF se construyen a partir de los textos de `datos/documentos_demo/fuentes/` para que el contenido se pueda
leer y corregir en el repositorio. Regenerarlos: python -m cotejo.documentos.semilla
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from cotejo.config import obtener_config
from cotejo.documentos.embeddings import Embedder, obtener_embedder
from cotejo.documentos.indexado import indexar_documento
from cotejo.documentos.pdf_simple import pdf_de_texto, pdf_escaneado
from cotejo.modelos import Proveedor

CARPETA_DEMO = Path("datos") / "documentos_demo"
MANIFIESTO = "manifiesto.json"
SEPARADOR_PAGINA = "=== página ==="
SEPARADOR_OCULTO = "=== texto oculto ==="
PDF_ESCANEADO = "contrato_papeleria_escaneado.pdf"


@dataclass(frozen=True)
class DocumentoDemo:
    archivo: str
    # Fragmento del nombre del proveedor al que se liga; None para documentos generales.
    proveedor: str | None


def carpeta_demo() -> Path:
    """Carpeta de los documentos de demostración: la del directorio de trabajo o la del repositorio."""
    candidatas = (Path.cwd() / CARPETA_DEMO, Path(__file__).resolve().parents[3] / CARPETA_DEMO)
    for carpeta in candidatas:
        if (carpeta / MANIFIESTO).is_file():
            return carpeta
    raise FileNotFoundError(f"No se encontró {CARPETA_DEMO / MANIFIESTO} en {' ni en '.join(map(str, candidatas))}.")


def leer_manifiesto(carpeta: Path) -> list[DocumentoDemo]:
    datos = json.loads((carpeta / MANIFIESTO).read_text(encoding="utf-8"))
    return [DocumentoDemo(archivo=str(d["archivo"]), proveedor=d.get("proveedor")) for d in datos["documentos"]]


def pdf_desde_fuente(fuente: str) -> bytes:
    """Convierte un texto con separadores de página y de texto oculto en un PDF."""
    paginas: list[str] = []
    oculto: dict[int, str] = {}
    for numero, bloque in enumerate(fuente.split(SEPARADOR_PAGINA), start=1):
        visible, _, escondido = bloque.partition(SEPARADOR_OCULTO)
        paginas.append(visible.strip())
        if escondido.strip():
            oculto[numero] = " ".join(escondido.split())
    return pdf_de_texto(paginas, oculto=oculto)


def generar_pdfs(carpeta: Path) -> dict[str, bytes]:
    """Contenido de cada PDF de demostración, por nombre de archivo. No escribe nada."""
    generados = {
        fuente.with_suffix(".pdf").name: pdf_desde_fuente(fuente.read_text(encoding="utf-8"))
        for fuente in sorted((carpeta / "fuentes").glob("*.txt"))
    }
    generados[PDF_ESCANEADO] = pdf_escaneado(paginas=2)
    return generados


def _proveedor_por_nombre(sesion: Session, fragmento: str | None) -> int | None:
    if not fragmento:
        return None
    return sesion.scalar(
        select(Proveedor.id).where(Proveedor.nombre.ilike(f"%{fragmento}%")).order_by(Proveedor.id).limit(1)
    )


def sembrar_documentos(sesion: Session, usuario_id: int, *, embedder: Embedder | None = None) -> int:
    """Carga los documentos de demostración en la transacción en curso. Devuelve cuántos quedaron en la base.

    Es idempotente: un documento ya cargado (mismo contenido) no se duplica. Cada documento se liga a su
    proveedor si existe uno cuyo nombre contenga el texto del manifiesto; si no, queda como documento general.
    """
    carpeta = carpeta_demo()
    embedder = embedder or obtener_embedder(obtener_config())
    total = 0
    for demo in leer_manifiesto(carpeta):
        contenido = (carpeta / demo.archivo).read_bytes()
        indexar_documento(
            sesion,
            nombre=demo.archivo,
            tipo=Path(demo.archivo).suffix.removeprefix("."),
            contenido=contenido,
            sha256=hashlib.sha256(contenido).hexdigest(),
            proveedor_id=_proveedor_por_nombre(sesion, demo.proveedor),
            usuario_id=usuario_id,
            embedder=embedder,
        )
        total += 1
    return total


def main() -> int:
    carpeta = carpeta_demo()
    for nombre, contenido in generar_pdfs(carpeta).items():
        (carpeta / nombre).write_bytes(contenido)
        sys.stdout.write(f"{nombre}: {len(contenido)} bytes\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
