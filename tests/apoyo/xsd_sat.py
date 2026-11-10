"""Validación contra los XSD oficiales del SAT, solo para pruebas.

Los esquemas de `tests/referencias/sat/` son copias sin modificar. Entre ellos se importan por URL del SAT; aquí
esas URL se resuelven a los archivos locales para que la validación no salga a la red.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from lxml import etree

if TYPE_CHECKING:
    from lxml.etree._docloader import _InputDocument

CARPETA = Path(__file__).resolve().parents[1] / "referencias" / "sat"

ESQUEMAS = {
    "http://www.sat.gob.mx/cfd/4": "cfdv40.xsd",
    "http://www.sat.gob.mx/TimbreFiscalDigital": "TimbreFiscalDigitalv11.xsd",
    "http://www.sat.gob.mx/Pagos20": "Pagos20.xsd",
    "http://www.sat.gob.mx/implocal": "implocal.xsd",
}


class _SoloLocal(etree.Resolver):
    """Resuelve cualquier importación al archivo local del mismo nombre y falla si no existe."""

    def resolve(self, system_url: str | None, public_id: str | None, context: object, /) -> _InputDocument | None:
        nombre = (system_url or "").rsplit("/", 1)[-1]
        ruta = CARPETA / nombre
        if not ruta.is_file():
            raise FileNotFoundError(f"El esquema {system_url} no está en {CARPETA}.")
        return self.resolve_filename(str(ruta), context)


def sumas_registradas() -> dict[str, str]:
    lineas = (CARPETA / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    return {nombre: suma for suma, nombre in (linea.split() for linea in lineas if linea.strip())}


def suma_de(nombre: str) -> str:
    return hashlib.sha256((CARPETA / nombre).read_bytes()).hexdigest()


@lru_cache(maxsize=1)
def esquema() -> etree.XMLSchema:
    """Esquema que conoce el comprobante 4.0 y los complementos que Cotejo lee."""
    importaciones = "".join(
        f'<xs:import namespace="{espacio}" schemaLocation="{archivo}"/>' for espacio, archivo in ESQUEMAS.items()
    )
    envoltura = f'<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">{importaciones}</xs:schema>'
    lector = etree.XMLParser(no_network=True)
    lector.resolvers.add(_SoloLocal())
    return etree.XMLSchema(etree.fromstring(envoltura.encode("utf-8"), lector, base_url=str(CARPETA / "envoltura.xsd")))


def errores(xml: bytes) -> list[str]:
    """Lista de errores de validación; vacía si el XML cumple los esquemas."""
    documento = etree.fromstring(xml, etree.XMLParser(no_network=True, resolve_entities=False))
    validador = esquema()
    if validador.validate(documento):
        return []
    return [f"línea {e.line}: {e.message}" for e in validador.error_log]
