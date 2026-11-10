"""Lectura de XML que no confía en el archivo (A6).

Tres capas: el archivo se rechaza antes de leerlo si declara un DTD o una entidad; el lector de lxml se configura
para no resolver entidades, no cargar DTD y no salir a la red; y después de leer se comprueba que el documento no
traiga DTD interno, por si una codificación rara esquivó la primera comprobación. Un CFDI legítimo nunca usa DTD.
"""

from __future__ import annotations

from lxml import etree

from cotejo.cfdi import codigos
from cotejo.config import MB_POR_XML

LIMITE_BYTES = MB_POR_XML * 1024 * 1024
_MARCAS_DTD = (b"<!DOCTYPE", b"<!ENTITY")


class XmlRechazado(Exception):
    def __init__(self, codigo: str, mensaje: str) -> None:
        super().__init__(mensaje)
        self.codigo = codigo
        self.mensaje = mensaje


def _declara_dtd(contenido: bytes) -> bool:
    # En UTF-16 y UTF-32 cada carácter ASCII va acompañado de bytes nulos: se quitan para buscar la marca.
    compacto = contenido.replace(b"\x00", b"").upper()
    return any(marca in compacto for marca in _MARCAS_DTD)


def parsear(contenido: bytes) -> etree._Element:
    """Devuelve el elemento raíz o lanza XmlRechazado. Nunca lee archivos locales ni abre conexiones."""
    if not contenido:
        raise XmlRechazado(codigos.ARCHIVO_VACIO, "El archivo está vacío.")
    if len(contenido) > LIMITE_BYTES:
        raise XmlRechazado(codigos.ARCHIVO_DEMASIADO_GRANDE, f"El XML rebasa el límite de {MB_POR_XML} MB.")
    if _declara_dtd(contenido):
        raise XmlRechazado(
            codigos.XML_DTD_PROHIBIDO,
            "El XML declara un DTD o entidades. Un CFDI no los usa y por seguridad no se procesa.",
        )
    # Un lector por llamada: no se comparte estado entre archivos de distintos usuarios.
    lector = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        dtd_validation=False,
        huge_tree=False,
        remove_comments=True,
        remove_pis=True,
        collect_ids=False,
    )
    try:
        raiz = etree.fromstring(contenido, lector)
    except etree.XMLSyntaxError as exc:
        raise XmlRechazado(codigos.XML_MAL_FORMADO, "El archivo no es un XML bien formado.") from exc
    if raiz.getroottree().docinfo.internalDTD is not None:
        raise XmlRechazado(
            codigos.XML_DTD_PROHIBIDO,
            "El XML declara un DTD o entidades. Un CFDI no los usa y por seguridad no se procesa.",
        )
    return raiz
